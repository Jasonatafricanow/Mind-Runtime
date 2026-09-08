from dataclasses import fields, replace

import pytest

from mind_runtime.contracts import Scope, ScopeDomain
from mind_runtime.memory.contracts import MemoryLifecycle
from mind_runtime.memory.store import CanonicalMemoryStore
from tests.memory.test_contracts import memory


class ScriptedProvider:
    def __init__(self, hits=(), error=None):
        self.hits, self.error, self.queries = hits, error, []

    def search(self, query):
        self.queries.append(query)
        if self.error:
            raise self.error
        return self.hits


def candidate(memory_id="memory-1", **kwargs):
    from mind_runtime.memory.retrieval import RetrievedMemoryCandidate

    return RetrievedMemoryCandidate(memory_id, "scripted", **kwargs)


def query(**kwargs):
    from mind_runtime.memory.retrieval import MemoryRetrievalQuery

    return MemoryRetrievalQuery(**(dict(scope=memory().scope, text="hello", limit=5) | kwargs))


def service(tmp_path, hits=(), memories=None, error=None):
    from mind_runtime.memory.retrieval import MemoryRetrievalService

    db = CanonicalMemoryStore(tmp_path / "memory.sqlite")
    db._commit((memory(),) if memories is None else memories)
    provider = ScriptedProvider(hits, error)
    return MemoryRetrievalService(store=db, provider=provider), db, provider


def test_canonical_content_wins_over_provider_text_and_ids_are_resolvable(tmp_path):
    hit = candidate(provider_ref="vector-uuid", score=0.95, provider_text="STALE")
    reader, db, _ = service(tmp_path, (hit,))
    result = reader.search(query())
    assert len(result) == 1
    assert result[0].memory.content == "hello"
    assert result[0].candidate == hit and result[0].rank == 1
    resolved = db.get(result[0].memory.memory_id)
    assert resolved.content == "hello" and resolved.provenance.evidence_refs == ("evidence-1",)


def test_query_scope_is_structured_and_candidate_has_no_authority_fields():
    q = query()
    assert q.scope == memory().scope
    assert "agent_id" not in {f.name for f in fields(q)}
    assert not (
        {"content", "provenance", "lifecycle", "authority"} & {f.name for f in fields(candidate())}
    )


@pytest.mark.parametrize(
    "changes",
    [
        {"scope": "user"},
        {"limit": True},
        {"limit": -1},
        {"limit": 101},
        {"text": ""},
        {"text": "x" * 4097},
    ],
)
def test_invalid_queries_fail_closed(changes):
    with pytest.raises(ValueError):
        query(**changes)


def test_provider_uuid_cannot_become_canonical_identity(tmp_path):
    with pytest.raises(ValueError):
        candidate("")
    reader, _, _ = service(tmp_path, (candidate("vector-uuid", provider_ref="vector-uuid"),))
    assert reader.search(query()) == ()


@pytest.mark.parametrize("state", [MemoryLifecycle.ARCHIVED, MemoryLifecycle.SUPERSEDED])
def test_canonical_lifecycle_overrides_stale_index(tmp_path, state):
    reader, _, _ = service(tmp_path, (candidate(),), (replace(memory(), lifecycle=state),))
    assert reader.search(query()) == ()


def test_canonical_scope_overrides_high_provider_rank(tmp_path):
    other = Scope(ScopeDomain.USER, user_id="unauthorized")
    m = replace(memory(), scope=other, sync=replace(memory().sync, scope=other))
    reader, _, provider = service(tmp_path, (candidate(score=1.0),), (m,))
    assert reader.search(query()) == ()
    assert provider.queries[0].scope == memory().scope


def test_order_dedup_and_limit_are_deterministic(tmp_path):
    second = replace(
        memory(),
        memory_id="memory-2",
        content="second",
        sync=replace(memory().sync, object_id="memory-2"),
    )
    hits = (candidate("memory-2", score=0.2), candidate("memory-2", score=0.9), candidate())
    reader, _, _ = service(tmp_path, hits, (memory(), second))
    result = reader.search(query(limit=3))
    assert [r.memory.memory_id for r in result] == ["memory-2", "memory-1"]
    assert [r.rank for r in result] == [1, 3]
    assert result[0].candidate.score == 0.2
    assert len(reader.search(query(limit=1))) == 1


def test_consumer_budget_drops_whole_propositions(tmp_path):
    from mind_runtime.memory.retrieval import MemorySurfaceBudget

    reader, _, _ = service(tmp_path, (candidate(),))
    assert reader.search(query(), budget=MemorySurfaceBudget(max_items=1, max_characters=4)) == ()
    assert (
        reader.search(query(), budget=MemorySurfaceBudget(max_items=1, max_characters=5))[
            0
        ].memory.content
        == "hello"
    )


def test_null_empty_and_outage_are_distinct(tmp_path):
    from mind_runtime.memory.retrieval import (
        MemoryRetrievalService,
        NullRetrievalProvider,
        RetrievalProviderUnavailable,
    )

    reader, db, _ = service(tmp_path)
    assert reader.search(query()) == ()
    assert NullRetrievalProvider().search(query()) == ()
    assert MemoryRetrievalService(store=db).search(query()) == ()
    reader, _, _ = service(tmp_path, error=TimeoutError("down"))
    with pytest.raises(RetrievalProviderUnavailable):
        reader.search(query())


def test_zero_budget_or_limit_never_calls_provider(tmp_path):
    from mind_runtime.memory.retrieval import MemorySurfaceBudget

    reader, _, provider = service(tmp_path, error=AssertionError("must not call"))
    assert reader.search(query(limit=0)) == ()
    assert reader.search(query(), budget=MemorySurfaceBudget(max_items=0)) == ()
    assert provider.queries == []


def test_readonly_restart_and_repeated_reads_preserve_database_bytes(tmp_path):
    from mind_runtime.memory.retrieval import MemoryRetrievalService

    path = tmp_path / "memory.sqlite"
    db = CanonicalMemoryStore(path)
    db._commit((memory(),))
    db.close()
    before = path.read_bytes()
    db = CanonicalMemoryStore(path, read_only=True)
    reader = MemoryRetrievalService(store=db, provider=ScriptedProvider((candidate(),)))
    for _ in range(10):
        assert reader.search(query())[0].memory == memory()
    import sqlite3

    with pytest.raises(sqlite3.OperationalError):
        db._conn.execute("DELETE FROM canonical_memory")
    db.close()
    assert path.read_bytes() == before


def test_readonly_missing_database_creates_nothing(tmp_path):
    import sqlite3

    path = tmp_path / "absent" / "memory.sqlite"
    with pytest.raises(sqlite3.OperationalError):
        CanonicalMemoryStore(path, read_only=True)
    assert not path.parent.exists()
