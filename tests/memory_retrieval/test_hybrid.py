from dataclasses import replace

import pytest

from mind_runtime.contracts import Scope, ScopeDomain
from mind_runtime.memory.contracts import MemoryLifecycle
from mind_runtime.memory.providers.bm25 import BM25RetrievalProvider, lexical_tokens
from mind_runtime.memory.providers.hybrid import (
    HybridRRFProvider,
    HyDEAugmentedProvider,
    PromptHyDEExpander,
    RetrievalArm,
)
from mind_runtime.memory.retrieval import (
    MemoryRetrievalQuery,
    RetrievalProviderUnavailable,
    RetrievedMemoryCandidate,
)
from tests.memory.test_contracts import memory


def make_memory(memory_id, content, *, scope=None, lifecycle=MemoryLifecycle.ACTIVE):
    base = memory()
    chosen_scope = base.scope if scope is None else scope
    return replace(
        base,
        memory_id=memory_id,
        scope=chosen_scope,
        content=content,
        lifecycle=lifecycle,
        sync=replace(
            base.sync,
            scope=chosen_scope,
            object_id=memory_id,
            idempotency_key=memory_id,
        ),
    )


def test_lexical_tokens_cover_exact_terms_numbers_and_cjk_bigrams():
    assert lexical_tokens("MacBook M4 / ORA-00942") == ("macbook", "m4", "ora", "00942")
    assert lexical_tokens("电脑越来越卡") == (
        "电脑越来越卡",
        "电脑",
        "脑越",
        "越来",
        "来越",
        "越卡",
    )
    assert lexical_tokens("ＡＢＣ １２３") == ("abc", "123")


def test_bm25_exact_and_scope_sensitive_retrieval():
    other = Scope(ScopeDomain.USER, user_id="other")
    provider = BM25RetrievalProvider(
        (
            make_memory("m1", "MacBook M4 price is 9999"),
            make_memory("m2", "I want to replace my slow computer"),
            make_memory("m3", "MacBook M4 price is 1", scope=other),
            make_memory(
                "m4",
                "MacBook M4 old archived note",
                lifecycle=MemoryLifecycle.ARCHIVED,
            ),
        )
    )
    query = MemoryRetrievalQuery(memory().scope, "M4 price", limit=5)
    hits = provider.search(query)
    assert [hit.memory_id for hit in hits] == ["m1"]
    assert hits[0].provider == "bm25"
    assert hits[0].provider_ref == "bm25:m1"
    assert hits[0].score is not None and hits[0].score > 0


def test_bm25_semantic_gap_is_not_magically_solved():
    provider = BM25RetrievalProvider(
        (
            make_memory("m1", "I want to replace my slow computer"),
            make_memory("m2", "The old laptop fan is noisy"),
        )
    )
    query = MemoryRetrievalQuery(memory().scope, "M4 price", limit=5)
    assert provider.search(query) == ()


def test_bm25_chinese_query_and_deterministic_limit():
    provider = BM25RetrievalProvider(
        (
            make_memory("m1", "电脑越来越卡，我开始考虑换电脑"),
            make_memory("m2", "电脑价格太贵，所以暂时不换"),
            make_memory("m3", "今天吃了午饭"),
        )
    )
    hits = provider.search(MemoryRetrievalQuery(memory().scope, "越来越卡", limit=1))
    assert len(hits) == 1
    assert hits[0].memory_id == "m1"
    assert provider.search(MemoryRetrievalQuery(memory().scope, "!!!", limit=5)) == ()
    assert provider.search(MemoryRetrievalQuery(memory().scope, "电脑", limit=0)) == ()


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"k1": 0}, "k1"),
        ({"k1": float("inf")}, "k1"),
        ({"b": -0.1}, "b"),
        ({"b": 1.1}, "b"),
    ],
)
def test_bm25_parameter_validation(kwargs, message):
    with pytest.raises(ValueError, match=message):
        BM25RetrievalProvider((memory(),), **kwargs)


def test_bm25_rejects_noncanonical_and_duplicate_identity():
    with pytest.raises(ValueError, match="CommittedMemory"):
        BM25RetrievalProvider((object(),))
    duplicate = make_memory("m1", "one")
    with pytest.raises(ValueError, match="duplicate"):
        BM25RetrievalProvider((duplicate, duplicate))


class RecordingProvider:
    def __init__(self, responses, *, error=None):
        self.responses = responses
        self.error = error
        self.queries = []

    def search(self, query):
        self.queries.append(query)
        if self.error is not None:
            raise self.error
        return self.responses.get(query.text, self.responses.get("*", ()))


def hit(memory_id, provider="fixture", *, score=None, ref=None):
    return RetrievedMemoryCandidate(
        memory_id,
        provider,
        provider_ref=ref,
        score=score,
    )


def test_rrf_fuses_rank_not_raw_score_and_expands_candidate_window():
    lexical = RecordingProvider({"*": (hit("m1", score=1000), hit("m2", score=1))})
    dense = RecordingProvider({"*": (hit("m2", score=0.01), hit("m3", score=0.99))})
    provider = HybridRRFProvider(
        (
            RetrievalArm("bm25", lexical),
            RetrievalArm("dense", dense),
        ),
        candidate_multiplier=4,
    )
    hits = provider.search(MemoryRetrievalQuery(memory().scope, "computer", limit=2))
    assert [item.memory_id for item in hits] == ["m2", "m1"]
    assert hits[0].provider == "rrf:bm25+dense"
    assert lexical.queries[0].limit == 8
    assert dense.queries[0].limit == 8
    assert hits[0].score is not None and hits[0].score > hits[1].score


def test_rrf_weights_duplicates_and_tie_breaking_are_deterministic():
    first = RecordingProvider(
        {"*": (hit("m1", ref="a1"), hit("m1", ref="duplicate"), hit("m2", ref="a2"))}
    )
    second = RecordingProvider({"*": (hit("m2", ref="b1"), hit("m3", ref="b2"))})
    provider = HybridRRFProvider(
        (
            RetrievalArm("first", first, weight=1.0),
            RetrievalArm("second", second, weight=2.0),
        ),
        rrf_k=10,
        candidate_multiplier=1,
    )
    hits = provider.search(MemoryRetrievalQuery(memory().scope, "q", limit=3))
    assert [item.memory_id for item in hits] == ["m2", "m3", "m1"]
    assert hits[0].provider_ref == "first:a2|second:b1"


@pytest.mark.parametrize(
    "factory",
    [
        lambda: RetrievalArm("", RecordingProvider({})),
        lambda: RetrievalArm("x", RecordingProvider({}), weight=0),
        lambda: HybridRRFProvider((RetrievalArm("only", RecordingProvider({})),)),
        lambda: HybridRRFProvider(
            (
                RetrievalArm("x", RecordingProvider({})),
                RetrievalArm("x", RecordingProvider({})),
            )
        ),
        lambda: HybridRRFProvider(
            (
                RetrievalArm("x", RecordingProvider({})),
                RetrievalArm("y", RecordingProvider({})),
            ),
            rrf_k=0,
        ),
        lambda: HybridRRFProvider(
            (
                RetrievalArm("x", RecordingProvider({})),
                RetrievalArm("y", RecordingProvider({})),
            ),
            candidate_multiplier=21,
        ),
    ],
)
def test_hybrid_configuration_validation(factory):
    with pytest.raises(ValueError):
        factory()


def test_hybrid_fails_closed_when_configured_arm_fails():
    provider = HybridRRFProvider(
        (
            RetrievalArm("ok", RecordingProvider({"*": (hit("m1"),)})),
            RetrievalArm("down", RecordingProvider({}, error=TimeoutError("down"))),
        )
    )
    with pytest.raises(RetrievalProviderUnavailable, match="down"):
        provider.search(MemoryRetrievalQuery(memory().scope, "q", limit=5))
    assert provider.search(MemoryRetrievalQuery(memory().scope, "q", limit=0)) == ()


class StaticExpander:
    def __init__(self, value=None, *, error=None):
        self.value = value
        self.error = error
        self.queries = []

    def expand(self, query):
        self.queries.append(query)
        if self.error is not None:
            raise self.error
        return self.value


def test_hyde_fuses_original_and_hypothetical_query():
    base = RecordingProvider(
        {
            "why did I not buy it": (hit("m1"), hit("m2")),
            "price was too high so purchase was postponed": (hit("m2"), hit("m3")),
        }
    )
    expander = StaticExpander("price was too high so purchase was postponed")
    provider = HyDEAugmentedProvider(base, expander, candidate_multiplier=2)
    hits = provider.search(
        MemoryRetrievalQuery(memory().scope, "why did I not buy it", limit=2)
    )
    assert [item.memory_id for item in hits] == ["m2", "m1"]
    assert [query.text for query in base.queries] == [
        "why did I not buy it",
        "price was too high so purchase was postponed",
    ]
    assert all(query.limit == 4 for query in base.queries)
    assert expander.queries == ["why did I not buy it"]


def test_hyde_same_query_avoids_duplicate_search():
    base = RecordingProvider({"same": (hit("m1"), hit("m2"))})
    provider = HyDEAugmentedProvider(base, StaticExpander("same"))
    hits = provider.search(MemoryRetrievalQuery(memory().scope, "same", limit=1))
    assert [item.memory_id for item in hits] == ["m1"]
    assert len(base.queries) == 1


def test_hyde_failure_is_explicit_unless_fallback_is_configured():
    base = RecordingProvider({"original": (hit("m1"),)})
    strict = HyDEAugmentedProvider(
        base,
        StaticExpander(error=TimeoutError("llm")),
    )
    with pytest.raises(RetrievalProviderUnavailable, match="HyDE"):
        strict.search(MemoryRetrievalQuery(memory().scope, "original", limit=1))

    fallback_base = RecordingProvider({"original": (hit("m1"), hit("m2"))})
    fallback = HyDEAugmentedProvider(
        fallback_base,
        StaticExpander(error=TimeoutError("llm")),
        fallback_to_original=True,
    )
    result = fallback.search(MemoryRetrievalQuery(memory().scope, "original", limit=1))
    assert [item.memory_id for item in result] == ["m1"]


def test_hyde_base_failure_and_invalid_configuration_fail_closed():
    down = RecordingProvider({}, error=TimeoutError("down"))
    provider = HyDEAugmentedProvider(down, StaticExpander("expanded"))
    with pytest.raises(RetrievalProviderUnavailable, match="base"):
        provider.search(MemoryRetrievalQuery(memory().scope, "q", limit=1))
    assert provider.search(MemoryRetrievalQuery(memory().scope, "q", limit=0)) == ()

    with pytest.raises(ValueError):
        HyDEAugmentedProvider(RecordingProvider({}), StaticExpander("x"), rrf_k=0)
    with pytest.raises(ValueError):
        HyDEAugmentedProvider(
            RecordingProvider({}),
            StaticExpander("x"),
            candidate_multiplier=0,
        )
    with pytest.raises(ValueError):
        HyDEAugmentedProvider(
            RecordingProvider({}),
            StaticExpander("x"),
            fallback_to_original=1,
        )


def test_prompt_hyde_expander_is_model_agnostic_and_bounded():
    prompts = []

    def complete(prompt):
        prompts.append(prompt)
        return "  M4 purchase was postponed because the price was high.  "

    expander = PromptHyDEExpander(complete, max_characters=128)
    result = expander.expand("why did I not buy the M4?")
    assert result == "M4 purchase was postponed because the price was high."
    assert "M4" in prompts[0] and "Return only" in prompts[0]

    long = PromptHyDEExpander(lambda _: "x" * 300, max_characters=128)
    assert len(long.expand("query")) == 128

    with pytest.raises(ValueError):
        PromptHyDEExpander(complete, max_characters=127)
    with pytest.raises(ValueError):
        expander.expand(" ")
    with pytest.raises(ValueError):
        PromptHyDEExpander(lambda _: "", max_characters=128).expand("query")
