from __future__ import annotations

from dataclasses import replace

from mind_runtime.decision import (
    DecisionAnswer,
    DecisionCapability,
    DecisionKind,
    DecisionModelUnavailable,
    DecisionRequest,
    DecisionResult,
)
from mind_runtime.memory.retrieval import MemoryRetrievalQuery, MemoryRetrievalService
from mind_runtime.memory.store import CanonicalMemoryStore
from tests.memory.test_contracts import memory
from tests.memory_retrieval.test_retrieval import ScriptedProvider, candidate


class SemanticRerankBackend:
    def __init__(self) -> None:
        self.requests: list[DecisionRequest] = []

    @property
    def backend_name(self) -> str:
        return "semantic-fixture"

    def evaluate(self, request: DecisionRequest) -> DecisionResult:
        self.requests.append(request)
        answers = []
        for question in request.questions:
            index = int(question.question_id.rsplit("_", 1)[1])
            content = request.state[f"candidate_{index}"]
            yes = 0.95 if "price" in content else 0.05
            answers.append(
                DecisionAnswer(
                    question.question_id,
                    DecisionKind.BOOLEAN,
                    {"false": 1.0 - yes, "true": yes},
                    selected="true" if yes >= 0.5 else "false",
                )
            )
        return DecisionResult(
            backend=self.backend_name,
            model_version="fixture-v1",
            answers=tuple(answers),
        )


class OfflineBackend:
    @property
    def backend_name(self) -> str:
        return "offline"

    def evaluate(self, request: DecisionRequest) -> DecisionResult:
        del request
        raise DecisionModelUnavailable("no decision compute")


def _second_memory():
    base = memory()
    return replace(
        base,
        memory_id="memory-2",
        content="M4 price dropped enough to reconsider the purchase",
        sync=replace(
            base.sync,
            object_id="memory-2",
            idempotency_key="memory-2",
        ),
    )


def test_decision_reranks_only_after_canonical_revalidation(tmp_path) -> None:
    store = CanonicalMemoryStore(tmp_path / "memory.sqlite")
    store._commit((memory(), _second_memory()))
    backend = SemanticRerankBackend()
    provider = ScriptedProvider(
        (
            candidate("memory-1", provider_text="price price price"),
            candidate("missing", provider_text="price"),
            candidate("memory-2", provider_text="STALE unrelated provider text"),
        )
    )
    service = MemoryRetrievalService(
        store=store,
        provider=provider,
        decision=DecisionCapability(backend),
    )
    result = service.search(
        MemoryRetrievalQuery(memory().scope, "should I reconsider the M4?", limit=3)
    )
    assert [item.memory.memory_id for item in result] == ["memory-2", "memory-1"]
    assert len(backend.requests) == 1
    state = backend.requests[0].state
    assert "STALE unrelated provider text" not in state.values()
    assert "price price price" not in state.values()
    assert set(key for key in state if key.startswith("candidate_")) == {
        "candidate_0",
        "candidate_1",
    }
    store.close()


def test_absent_or_offline_decision_model_preserves_baseline_order(tmp_path) -> None:
    store = CanonicalMemoryStore(tmp_path / "memory.sqlite")
    store._commit((memory(), _second_memory()))
    provider = ScriptedProvider((candidate("memory-1"), candidate("memory-2")))
    query = MemoryRetrievalQuery(memory().scope, "hello", limit=2)

    baseline = MemoryRetrievalService(store=store, provider=provider).search(query)
    absent = MemoryRetrievalService(
        store=store,
        provider=provider,
        decision=DecisionCapability(),
    ).search(query)
    offline = MemoryRetrievalService(
        store=store,
        provider=provider,
        decision=DecisionCapability(OfflineBackend()),
    ).search(query)

    expected = ["memory-1", "memory-2"]
    assert [item.memory.memory_id for item in baseline] == expected
    assert [item.memory.memory_id for item in absent] == expected
    assert [item.memory.memory_id for item in offline] == expected
    store.close()
