import json
import sqlite3
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from mind_runtime.contracts import Scope, ScopeDomain
from mind_runtime.memory.contracts import MemoryLifecycle
from mind_runtime.memory.product import (
    MemoryAttention,
    MemoryProductConflict,
    MemoryProductStore,
    MemorySurfacePolicy,
    SurfaceMode,
    ThreadStatus,
)
from mind_runtime.memory.retrieval import (
    MemoryRetrievalQuery,
    MemoryRetrievalService,
    RetrievedMemoryCandidate,
)
from mind_runtime.memory.store import CanonicalMemoryStore
from tests.memory.test_contracts import memory


class OneHitProvider:
    def search(self, query):
        return (RetrievedMemoryCandidate("memory-1", "fixture", score=0.9),)


def setup_store(tmp_path, rows=None):
    path = tmp_path / "memory.sqlite"
    canonical = CanonicalMemoryStore(path)
    canonical._commit(tuple(rows) if rows is not None else (memory(),))
    product = MemoryProductStore(path, canonical)
    return path, canonical, product


def second_memory():
    original = memory()
    return replace(
        original,
        memory_id="memory-2",
        content="second",
        provenance=replace(
            original.provenance,
            evidence_refs=("evidence-2",),
            observation_id="observation-2",
            interaction_id="interaction-2",
        ),
        sync=replace(original.sync, object_id="memory-2", idempotency_key="memory-2"),
    )


def same_turn_second_memory():
    original = second_memory()
    return replace(
        original,
        provenance=replace(original.provenance, interaction_id="interaction-1"),
    )


def other_scope_memory():
    original = second_memory()
    scope = Scope(ScopeDomain.USER, user_id="other")
    return replace(original, scope=scope, sync=replace(original.sync, scope=scope))


def test_attention_defaults_update_reinforce_and_restart(tmp_path):
    path, canonical, product = setup_store(tmp_path)
    assert product.attention("memory-1") == MemoryAttention("memory-1")
    updated = product.set_attention(
        "memory-1", importance=8, resolved=True, digested=True, dont_surface=True
    )
    assert updated.importance == 8
    assert updated.resolved and updated.digested and updated.dont_surface
    at = datetime(2026, 9, 25, tzinfo=UTC)
    reinforced = product.reinforce("memory-1", at=at)
    assert reinforced.activation_count == 1
    assert reinforced.last_reinforced_at == at
    product.close()
    product = MemoryProductStore(path, canonical)
    assert product.attention("memory-1") == reinforced
    product.close()
    canonical.close()


@pytest.mark.parametrize(
    "value",
    [
        MemoryAttention("memory-1"),
        MemoryAttention("memory-1", importance=1),
        MemoryAttention("memory-1", importance=10, activation_count=2),
    ],
)
def test_attention_contract_accepts_valid_values(value):
    assert value.memory_id == "memory-1"


def test_attention_validation_and_unknown_memory_fail_closed(tmp_path):
    _, canonical, product = setup_store(tmp_path)
    with pytest.raises(ValueError):
        MemoryAttention("", importance=5)
    with pytest.raises(ValueError):
        MemoryAttention("memory-1", importance=0)
    with pytest.raises(ValueError):
        MemoryAttention("memory-1", activation_count=-1)
    with pytest.raises(ValueError):
        MemoryAttention("memory-1", resolved=1)
    with pytest.raises(ValueError):
        MemoryAttention(
            "memory-1",
            last_reinforced_at=datetime(2026, 9, 25),
        )
    with pytest.raises(ValueError):
        product.attention("unknown")
    with pytest.raises(ValueError):
        product.set_attention("memory-1", importance=11)
    with pytest.raises(ValueError):
        product.reinforce("memory-1", at=datetime(2026, 9, 25))
    product.close()
    canonical.close()


def test_surface_policy_separates_truth_from_visibility():
    item = memory()
    now = item.committed_at + timedelta(days=30)
    policy = MemorySurfacePolicy(decay_lambda=0.05, resolved_factor=0.2)
    base = MemoryAttention(item.memory_id, importance=8, activation_count=2)
    automatic = policy.evaluate(item, base, mode=SurfaceMode.AUTOMATIC, now=now)
    assert automatic.allowed and automatic.score > 0
    resolved = policy.evaluate(
        item, replace(base, resolved=True), mode=SurfaceMode.AUTOMATIC, now=now
    )
    assert resolved.allowed and resolved.score < automatic.score

    hidden = replace(base, digested=True, dont_surface=True)
    decision = policy.evaluate(item, hidden, mode=SurfaceMode.AUTOMATIC, now=now)
    assert not decision.allowed
    assert decision.reasons == ("dont_surface", "digested")
    assert policy.evaluate(item, hidden, mode=SurfaceMode.EXPLICIT_SEARCH, now=now).allowed
    assert policy.evaluate(item, hidden, mode=SurfaceMode.LCE, now=now).allowed

    inactive = replace(item, lifecycle=MemoryLifecycle.ARCHIVED)
    assert not policy.evaluate(inactive, base, mode=SurfaceMode.LCE, now=now).allowed
    with pytest.raises(ValueError):
        policy.evaluate(
            item, MemoryAttention("different"), mode=SurfaceMode.AUTOMATIC, now=now
        )
    with pytest.raises(ValueError):
        policy.evaluate(item, base, mode=SurfaceMode.AUTOMATIC, now=datetime(2026, 9, 25))
    with pytest.raises(ValueError):
        MemorySurfacePolicy(decay_lambda=-1)
    with pytest.raises(ValueError):
        MemorySurfacePolicy(resolved_factor=2)


def test_retrieval_is_read_only_and_does_not_reinforce(tmp_path):
    _, canonical, product = setup_store(tmp_path)
    before = product.attention("memory-1")
    reader = MemoryRetrievalService(store=canonical, provider=OneHitProvider())
    results = reader.search(MemoryRetrievalQuery(memory().scope, "hello"))
    assert results[0].memory.memory_id == "memory-1"
    assert product.attention("memory-1") == before
    product.close()
    canonical.close()


def test_open_update_resolve_thread_is_bounded_durable_and_handoff_ready(tmp_path):
    path, canonical, product = setup_store(tmp_path, rows=(memory(), second_memory()))
    at = datetime(2026, 9, 25, tzinfo=UTC)
    thread = product.open_thread(
        thread_id="thread-upgrade",
        scope=memory().scope,
        open_question="Will the computer replacement happen?",
        supporting_memory_ids=("memory-1",),
        at=at,
        importance=7,
    )
    assert thread.status is ThreadStatus.OPEN
    assert thread.origin_memory_ids == ("memory-1",)
    assert thread.current_support_ids == ("memory-1",)
    assert not thread.mature

    updated = product.update_thread(
        "thread-upgrade",
        supporting_memory_ids=("memory-1", "memory-2"),
        at=at + timedelta(days=2),
        working_summary="Price delayed replacement; performance pressure reopened it.",
        mature=True,
    )
    assert updated.touch_count == 1
    assert updated.current_support_ids == ("memory-1", "memory-2")
    assert updated.mature
    assert product.thread_handoff("thread-upgrade") == updated

    product.close()
    product = MemoryProductStore(path, canonical)
    assert product.get_thread("thread-upgrade") == updated

    resolved = product.resolve_thread(
        "thread-upgrade",
        memory_id="memory-2",
        at=at + timedelta(days=4),
        working_summary="Replacement line closed after the final decision.",
    )
    assert resolved.status is ThreadStatus.RESOLVED
    assert resolved.mature
    assert product.thread_handoff("thread-upgrade") == resolved
    assert product.surface_threads(memory().scope, now=at + timedelta(days=6)) == ()
    product.close()
    canonical.close()


def test_thread_maturity_requires_cross_interaction_support(tmp_path):
    _, canonical, product = setup_store(
        tmp_path,
        rows=(memory(), same_turn_second_memory()),
    )
    at = datetime(2026, 9, 25, tzinfo=UTC)

    with pytest.raises(ValueError, match="at least two interactions"):
        product.open_thread(
            thread_id="forged-mature",
            scope=memory().scope,
            open_question="Can one turn fake maturity?",
            supporting_memory_ids=("memory-1", "memory-2"),
            at=at,
            working_summary="Two rows, one interaction.",
            mature=True,
        )

    product.open_thread(
        thread_id="t1",
        scope=memory().scope,
        open_question="Can one turn fake maturity?",
        supporting_memory_ids=("memory-1",),
        at=at,
        working_summary="Initial line.",
    )
    with pytest.raises(ValueError, match="at least two interactions"):
        product.update_thread(
            "t1",
            supporting_memory_ids=("memory-1", "memory-2"),
            at=at + timedelta(days=1),
            working_summary="Still one source interaction.",
            mature=True,
        )

    resolved = product.resolve_thread(
        "t1",
        memory_id="memory-2",
        at=at + timedelta(days=2),
        working_summary="Resolution still came from one interaction.",
    )
    assert not resolved.mature
    with pytest.raises(ValueError, match="not mature"):
        product.thread_handoff("t1")
    product.close()
    canonical.close()


def test_thread_working_state_validation_and_legacy_event_collapse(tmp_path):
    path, canonical, product = setup_store(tmp_path, rows=(memory(), second_memory()))
    at = datetime(2026, 9, 25, tzinfo=UTC)
    product.open_thread(
        thread_id="t1",
        scope=memory().scope,
        open_question="open?",
        supporting_memory_ids=("memory-1",),
        at=at,
    )
    with pytest.raises(ValueError, match="1..8"):
        product.update_thread(
            "t1",
            supporting_memory_ids=(),
            at=at + timedelta(days=1),
        )
    with pytest.raises(ValueError, match="mature Thread requires"):
        product.update_thread(
            "t1",
            supporting_memory_ids=("memory-1",),
            at=at + timedelta(days=1),
            mature=True,
        )
    with pytest.raises(ValueError, match="not mature"):
        product.thread_handoff("t1")
    product.close()

    legacy_payload = {
        "thread_id": "legacy",
        "scope": {
            "domain": memory().scope.domain.value,
            "user_id": memory().scope.user_id,
            "agent_id": memory().scope.agent_id,
            "persona_id": memory().scope.persona_id,
            "relationship_id": memory().scope.relationship_id,
            "world_id": memory().scope.world_id,
            "interaction_id": memory().scope.interaction_id,
        },
        "open_question": "legacy?",
        "status": "open",
        "importance": 5,
        "created_at": at.isoformat(),
        "updated_at": (at + timedelta(days=1)).isoformat(),
        "touch_count": 2,
        "suppressed": False,
        "events": [
            {"memory_id": "memory-1", "transition": "opened", "at": at.isoformat(), "note": ""},
            {
                "memory_id": "memory-2",
                "transition": "progress",
                "at": (at + timedelta(days=1)).isoformat(),
                "note": "old semantic label",
            },
        ],
    }
    with sqlite3.connect(path) as conn:
        conn.execute(
            "INSERT INTO memory_threads(thread_id,payload) VALUES(?,?)",
            ("legacy", json.dumps(legacy_payload)),
        )

    product = MemoryProductStore(path, canonical)
    migrated = product.get_thread("legacy")
    assert migrated is not None
    assert migrated.origin_memory_ids == ("memory-1",)
    assert migrated.current_support_ids == ("memory-1", "memory-2")
    assert migrated.working_summary is None
    assert not migrated.mature
    product.close()
    canonical.close()


def test_thread_scope_authority_conflict_and_lifecycle_guards(tmp_path):
    rows = (memory(), other_scope_memory())
    _, canonical, product = setup_store(tmp_path, rows=rows)
    at = datetime(2026, 9, 25, tzinfo=UTC)
    with pytest.raises(ValueError):
        product.open_thread(
            thread_id="bad",
            scope=memory().scope,
            open_question="bad",
            supporting_memory_ids=("memory-2",),
            at=at,
        )
    with pytest.raises(ValueError):
        product.open_thread(
            thread_id="empty",
            scope=memory().scope,
            open_question="bad",
            supporting_memory_ids=(),
            at=at,
        )
    with pytest.raises(ValueError):
        product.open_thread(
            thread_id="duplicate-support",
            scope=memory().scope,
            open_question="bad",
            supporting_memory_ids=("memory-1", "memory-1"),
            at=at,
        )
    product.open_thread(
        thread_id="t1",
        scope=memory().scope,
        open_question="open?",
        supporting_memory_ids=("memory-1",),
        at=at,
    )
    with pytest.raises(MemoryProductConflict):
        product.open_thread(
            thread_id="t1",
            scope=memory().scope,
            open_question="different?",
            supporting_memory_ids=("memory-1",),
            at=at,
        )
    with pytest.raises(ValueError):
        product.update_thread(
            "t1",
            supporting_memory_ids=("memory-2",),
            at=at,
        )
    abandoned = product.abandon_thread("t1", at=at + timedelta(days=1))
    assert abandoned.status is ThreadStatus.ABANDONED
    assert product.abandon_thread("t1", at=at + timedelta(days=2)) == abandoned
    with pytest.raises(ValueError):
        product.resolve_thread("t1", memory_id="memory-1", at=at + timedelta(days=3))
    with pytest.raises(ValueError):
        product.update_thread(
            "t1",
            supporting_memory_ids=("memory-1",),
            at=at + timedelta(days=3),
        )
    with pytest.raises(ValueError):
        product.abandon_thread("missing", at=at)
    with pytest.raises(ValueError):
        product.suppress_thread("missing")
    with pytest.raises(ValueError):
        product.suppress_thread("t1", 1)
    product.close()
    canonical.close()


def test_thread_surface_is_bounded_decaying_and_suppressible(tmp_path):
    _, canonical, product = setup_store(tmp_path, rows=(memory(), second_memory()))
    at = datetime(2026, 9, 1, tzinfo=UTC)
    old = product.open_thread(
        thread_id="old",
        scope=memory().scope,
        open_question="old?",
        supporting_memory_ids=("memory-1",),
        at=at,
        importance=5,
    )
    new = product.open_thread(
        thread_id="new",
        scope=memory().scope,
        open_question="new?",
        supporting_memory_ids=("memory-2",),
        at=at + timedelta(days=20),
        importance=5,
    )
    surfaced = product.surface_threads(
        memory().scope, now=at + timedelta(days=24), limit=1, decay_lambda=0.1
    )
    assert surfaced == (new,)
    assert old not in surfaced
    assert product.suppress_thread("new").suppressed
    assert product.surface_threads(
        memory().scope, now=at + timedelta(days=24), limit=5, decay_lambda=0.1
    ) == (old,)
    assert not product.suppress_thread("new", False).suppressed
    assert product.surface_threads(memory().scope, now=at, limit=0) == ()
    with pytest.raises(ValueError):
        product.surface_threads(memory().scope, now=at, limit=101)
    with pytest.raises(ValueError):
        product.surface_threads(memory().scope, now=at, decay_lambda=-0.1)
    with pytest.raises(ValueError):
        product.surface_threads(
            memory().scope, now=datetime(2026, 9, 25), decay_lambda=0.1
        )
    product.close()
    canonical.close()


def test_inactive_support_prevents_thread_surface(tmp_path):
    path, canonical, product = setup_store(tmp_path)
    at = datetime(2026, 9, 25, tzinfo=UTC)
    product.open_thread(
        thread_id="t1",
        scope=memory().scope,
        open_question="still open?",
        supporting_memory_ids=("memory-1",),
        at=at,
    )
    product.close()
    canonical.close()

    with sqlite3.connect(path) as conn:
        payload = conn.execute(
            "SELECT payload FROM canonical_memory WHERE memory_id='memory-1'"
        ).fetchone()[0]
        data = json.loads(payload)
        data["lifecycle"] = "archived"
        conn.execute(
            "UPDATE canonical_memory SET payload=? WHERE memory_id='memory-1'",
            (json.dumps(data, sort_keys=True, ensure_ascii=False),),
        )

    canonical = CanonicalMemoryStore(path)
    product = MemoryProductStore(path, canonical)
    assert product.surface_threads(memory().scope, now=at + timedelta(days=1)) == ()
    with pytest.raises(ValueError):
        product.open_thread(
            thread_id="inactive",
            scope=memory().scope,
            open_question="bad?",
            supporting_memory_ids=("memory-1",),
            at=at,
        )
    product.close()
    canonical.close()


def test_read_only_product_store_on_legacy_db_defaults_and_rejects_write(tmp_path):
    path = tmp_path / "memory.sqlite"
    canonical = CanonicalMemoryStore(path)
    canonical._commit((memory(),))
    readonly = MemoryProductStore(path, canonical, read_only=True)
    assert readonly.attention("memory-1") == MemoryAttention("memory-1")
    assert readonly.get_thread("missing") is None
    assert readonly.surface_threads(memory().scope, now=memory().committed_at) == ()
    with pytest.raises(sqlite3.OperationalError):
        readonly.reinforce("memory-1", at=memory().committed_at)
    readonly.close()
    canonical.close()


def test_automatic_history_respects_product_visibility(tmp_path):
    from mind_runtime.memory.history import MemoryHistoricalContextAdapter
    from tests.memory_retrieval.test_history import inputs
    from tests.memory_retrieval.test_retrieval import candidate, service

    reader, db, _ = service(tmp_path, (candidate(),))
    product = MemoryProductStore(tmp_path / "memory.sqlite", db)
    product.set_attention("memory-1", digested=True)
    assert MemoryHistoricalContextAdapter(reader, product=product).read(**inputs()) is None
    product.set_attention("memory-1", digested=False)
    assert MemoryHistoricalContextAdapter(reader, product=product).read(**inputs()) is not None
    product.close()
    db.close()
