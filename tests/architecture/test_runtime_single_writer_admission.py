"""MR-RUNTIME-05: runtime single-writer admission authority — required tests.

T1 two consumers, one admission sequence (mutual exclusion under concurrency)
T4 no false commit marker on persistence failure
T5 persistence False → explicit failure (no silent continue, no memory advance)
T6 authority keyed by namespace, not thread/session/channel
T7 different namespaces remain parallel-independent
T8 restart: same binding → same durable canonical after authority release
T9 lab destroy → recreate gets a fresh working authority
T10 host-adapter level: commit failure releases the admission (no deadlock)
"""

from __future__ import annotations

import threading
from dataclasses import replace
from typing import Any

import pytest

from mind_runtime.contracts import Scope, ScopeDomain
from mind_runtime.contracts.host import HostCommitRequest, HostTurnRequest
from mind_runtime.host import MindRuntimeHostAdapter
from mind_runtime.pipeline.orchestrator import TurnOrchestrator
from mind_runtime.pipeline.trace import TraceRecorder
from mind_runtime.runtime_admission import NamespaceAdmissionAuthority
from mind_runtime.state.persistence import SqliteCommitMarkerStore, SqliteStateBackend
from tests.architecture.test_single_writer_reality_probe import (
    NOW,
    _current,
    _durable_values,
    _fingerprint,
    _interaction,
    _orchestrator,
    _run_turn,
    _seed,
    _TypedFactPort,
)
from tests.golden.fixtures.common import make_evidence
from tests.support.fake_clock import FakeClock


def _enrolled(state_db: Any, *, value: str, markers: Any = None) -> TurnOrchestrator:
    return _orchestrator(state_db, value=value, markers=markers)


# ---------------------------------------------------------------------------
# T1 — same binding, two consumers: one admission sequence
# ---------------------------------------------------------------------------


def test_t1_two_consumers_cannot_admit_concurrently(tmp_path: Any) -> None:
    from datetime import timedelta

    state_db = tmp_path / "cognition_state.sqlite"
    _seed(state_db)
    markers = SqliteCommitMarkerStore(state_db)

    # A's stack (constructed and driven in the main thread — SQLite
    # connections are thread-affine, mirroring production's per-thread
    # stacks).
    orch_a = _enrolled(state_db, value="A", markers=markers)
    orch_a.begin_turn(_interaction("interaction-A"))

    # B's consumer runs its WHOLE turn in another thread — its orchestrator,
    # backend, and marker store are constructed IN that thread (thread
    # affinity), exactly like a second thread-local Hermes adapter.
    b_started = threading.Event()
    b_blocked = threading.Event()
    b_done = threading.Event()
    b_error: list[Exception] = []
    b_result: list[Any] = []

    def _b_turn() -> None:
        try:
            markers_b = SqliteCommitMarkerStore(state_db)
            orch_b = _enrolled(state_db, value="B", markers=markers_b)
            b_started.set()
            orch_b.begin_turn(_interaction("interaction-B"))  # blocks on A's lease
            b_blocked.set()
            orch_b.ingest(
                make_evidence(
                    text="B observed",
                    evidence_id="ev-interaction-B",
                    occurred_at=NOW + timedelta(hours=1),
                )
            )
            orch_b.run()
            orch_b.commit_turn()
            b_result.append(orch_b)
            orch_b._state_backend.close()
            markers_b.close()
        except Exception as exc:  # pragma: no cover — surfaced via b_error
            b_error.append(exc)
        finally:
            b_done.set()

    thread_b = threading.Thread(target=_b_turn, daemon=True)
    thread_b.start()
    assert b_started.wait(timeout=5.0)
    thread_b.join(timeout=1.0)
    assert thread_b.is_alive(), "B completed while A's turn was still open"

    # A completes its admission; B must then proceed WITH A's committed base.
    orch_a.ingest(
        make_evidence(
            text="A observed", evidence_id="ev-interaction-A",
            occurred_at=NOW - timedelta(hours=1),
        )
    )
    orch_a.run()
    orch_a.commit_turn()
    thread_b.join(timeout=10.0)
    assert not thread_b.is_alive(), "B stayed blocked after A's admission completed"
    assert not b_error
    # B's canonical was refreshed at admission: it built on A's outcome.
    assert b_result and _current(b_result[0]) == "B"

    durable = _durable_values(state_db)
    assert any(v == "A" for v in durable.values())
    assert any(v == "B" for v in durable.values())
    # No in-memory / DB divergence for either writer.
    fresh = _enrolled(state_db, value="ignored", markers=markers)
    assert _current(fresh) == "B"
    fresh._state_backend.close()
    orch_a._state_backend.close()
    markers.close()


# ---------------------------------------------------------------------------
# T4/T5 — persistence failure: explicit failure, no false marker, no memory
# advance, admission released
# ---------------------------------------------------------------------------


class _FailingOnProjectedBackend:
    """Delegating backend whose save_state fails for projected-* state ids.

    The stub projection's durable row has state_id ``projected-<turn>`` (its
    DIMENSION is a user-plane stub dimension), so the failure filter must
    key on state_id.
    """

    def __init__(self, inner: Any) -> None:
        self._inner = inner

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)

    def save_state(self, state: Any) -> bool:
        if str(state.state_id).startswith("projected-"):
            return False
        return self._inner.save_state(state)


def _failing_orchestrator(state_db: Any, *, value: str, markers: Any) -> TurnOrchestrator:
    return TurnOrchestrator(
        clock=FakeClock(NOW),
        trace=TraceRecorder(),
        fact_ingest=_TypedFactPort(value=value),
        state_backend=_FailingOnProjectedBackend(SqliteStateBackend(state_db)),
        commit_markers=markers,
        turn_admission=NamespaceAdmissionAuthority.for_state_db(state_db),
    )


def test_t4_t5_persistence_failure_fails_admission_loudly(tmp_path: Any) -> None:
    from mind_runtime.pipeline.orchestrator import CanonicalPersistenceError

    state_db = tmp_path / "cognition_state.sqlite"
    _seed(state_db)
    markers = SqliteCommitMarkerStore(state_db)

    orch_a = _failing_orchestrator(state_db, value="A", markers=markers)
    interaction = _interaction("interaction-A")
    orch_a.begin_turn(interaction)
    orch_a.ingest(make_evidence(text="A observed", evidence_id="ev-A"))
    orch_a.run()

    memory_before = _fingerprint(orch_a)
    with pytest.raises(CanonicalPersistenceError):
        orch_a.commit_turn()

    # T5: no silent continue — the failure surfaced as an exception.
    # T4: no false-positive commit marker for the failed admission.
    assert not markers.has_commit(interaction_id="interaction-A", scope=interaction.scope)
    # In-memory canonical did not advance on the failed admission.
    assert _fingerprint(orch_a) == memory_before

    # The admission was RELEASED despite the failure — the next consumer is
    # not blocked forever (no deadlock).
    orch_b = _enrolled(state_db, value="B", markers=markers)
    orch_b.begin_turn(_interaction("interaction-B"))
    orch_b.commit_turn()

    # The failed turn's projected state was NOT durably admitted either.
    durable = _durable_values(state_db)
    assert not any(
        str(state_id).startswith("projected-interaction-A") for state_id in durable
    )
    orch_a._state_backend.close()
    orch_b._state_backend.close()
    markers.close()


# ---------------------------------------------------------------------------
# T6 — authority key is the namespace, not thread/session/channel
# ---------------------------------------------------------------------------


def test_t6_authority_keyed_by_namespace_not_session(tmp_path: Any) -> None:
    a1 = NamespaceAdmissionAuthority.for_state_db(
        tmp_path / "ns" / "cognition_state.sqlite"
    )
    a2 = NamespaceAdmissionAuthority.for_state_db(
        tmp_path / "ns" / "cognition_state.sqlite"
    )
    other = NamespaceAdmissionAuthority.for_state_db(
        tmp_path / "other" / "cognition_state.sqlite"
    )
    assert a1 is a2  # same namespace → same admission authority
    assert a1 is not other  # different namespace → independent authority


# ---------------------------------------------------------------------------
# T7 — different namespaces remain parallel-independent
# ---------------------------------------------------------------------------


def test_t7_different_namespaces_do_not_block_each_other(tmp_path: Any) -> None:
    from datetime import timedelta

    ns_a = tmp_path / "lab-a" / "cognition_state.sqlite"
    ns_b = tmp_path / "lab-b" / "cognition_state.sqlite"
    for path in (ns_a, ns_b):
        path.parent.mkdir(parents=True, exist_ok=True)
        _seed(path)
    markers_a = SqliteCommitMarkerStore(ns_a)
    markers_b = SqliteCommitMarkerStore(ns_b)

    orch_a = _enrolled(ns_a, value="A", markers=markers_a)
    orch_b = _enrolled(ns_b, value="B", markers=markers_b)

    # A holds ITS namespace's admission lease...
    orch_a.begin_turn(_interaction("interaction-A"))
    # ...and B is admitted IMMEDIATELY on its own namespace (no
    # cross-namespace serialization): both namespaces run full turns.
    orch_b.begin_turn(_interaction("interaction-B"))
    orch_b.ingest(
        make_evidence(
            text="B observed", evidence_id="ev-interaction-B",
            occurred_at=NOW + timedelta(hours=1),
        )
    )
    orch_b.run()
    orch_b.commit_turn()
    orch_a.ingest(
        make_evidence(
            text="A observed", evidence_id="ev-interaction-A",
            occurred_at=NOW - timedelta(hours=1),
        )
    )
    orch_a.run()
    orch_a.commit_turn()

    assert _current(orch_b) == "B"
    assert _current(orch_a) == "A"
    orch_a._state_backend.close()
    orch_b._state_backend.close()
    markers_a.close()
    markers_b.close()


# ---------------------------------------------------------------------------
# T8 — restart: same binding → same durable canonical after release
# ---------------------------------------------------------------------------


def test_t8_restart_reconstructs_same_durable_canonical(tmp_path: Any) -> None:
    state_db = tmp_path / "cognition_state.sqlite"
    _seed(state_db)
    markers = SqliteCommitMarkerStore(state_db)
    orch_a = _enrolled(state_db, value="A", markers=markers)
    _run_turn(orch_a, "interaction-A", "A observed")
    orch_a._state_backend.close()
    markers.close()

    # A brand-new "process": fresh markers, fresh orchestrator, same namespace.
    markers2 = SqliteCommitMarkerStore(state_db)
    fresh = _enrolled(state_db, value="ignored", markers=markers2)
    assert _current(fresh) == "A"
    fresh._state_backend.close()
    markers2.close()


# ---------------------------------------------------------------------------
# T9 — lab destroy → recreate gets a fresh working authority
# ---------------------------------------------------------------------------


def test_t9_lab_destroy_and_recreate_releases_admission(tmp_path: Any) -> None:
    from mind_runtime.lab import LabRuntimeSpec, create_lab_runtime, destroy_lab_runtime

    spec = LabRuntimeSpec(persona_id="kayla_v0", storage_namespace="admission-cycle")
    runtime = create_lab_runtime(spec, lab_root=tmp_path)
    runtime.close()
    destroy_lab_runtime(runtime.binding, lab_root=tmp_path)

    # Recreate after destroy: the namespace's admission authority is reusable
    # (no stuck lease, no dead handle) and the fresh runtime is usable.
    again = create_lab_runtime(spec, lab_root=tmp_path)
    try:
        assert again.orchestrator.canonical == ()
        assert again.inspect().state_count == 0
    finally:
        again.close()

    # A second lab namespace is untouched by any of this.
    other = create_lab_runtime(
        LabRuntimeSpec(persona_id="kayla_v0", storage_namespace="admission-other"),
        lab_root=tmp_path,
    )
    other.close()
    assert other.storage_paths.state_db.exists()


# ---------------------------------------------------------------------------
# T10 — host-adapter level: commit failure releases the admission (no deadlock)
# ---------------------------------------------------------------------------


def test_t10_host_commit_failure_releases_admission(tmp_path: Any) -> None:
    state_db = tmp_path / "cognition_state.sqlite"
    _seed(state_db)
    markers = SqliteCommitMarkerStore(state_db)

    orchestrator = _failing_orchestrator(state_db, value="A", markers=markers)
    host = MindRuntimeHostAdapter(orchestrator=orchestrator)
    result = host.begin_turn(
        HostTurnRequest(
            interaction_id="interaction-A",
            runtime_id="probe-runtime",
            scope=Scope(domain=ScopeDomain.USER, user_id="user-1"),
            occurred_at=NOW,
            user_message="A observed",
            channel="chat",
            session_id="session-1",
        )
    )
    receipt = host.commit_turn(
        HostCommitRequest(turn_id=result.turn_id, interaction_id="interaction-A")
    )
    assert receipt.status.name == "FAILED"

    # The failed admission did NOT wedge the namespace: another consumer on
    # the same namespace is admitted immediately, and the failed turn was
    # aborted (no open turn left behind).
    orch_b = _enrolled(state_db, value="B", markers=markers)
    orch_b.begin_turn(_interaction("interaction-B"))
    orch_b.commit_turn()
    orchestrator._state_backend.close()
    orch_b._state_backend.close()
    markers.close()


# ---------------------------------------------------------------------------
# MR-05-R1: replay identity is authoritative interaction identity (marker),
# NEVER projection-content equality.
# ---------------------------------------------------------------------------


class _SlowDecisionTransition:
    """Gate-path transition that also emits one SLOW_ACCEPT decision."""

    def __init__(self, delegate) -> None:
        self._delegate = delegate

    def transition_with_gate(self, transition_input):
        from tests.expression.test_context_slow_state import make_slow_decision
        from types import SimpleNamespace

        result = self._delegate.transition(transition_input)
        decision = make_slow_decision(proposed_value=0.8, salience=0.88)
        return SimpleNamespace(
            transition_result=result,
            slow_decisions=(decision,),
        )


def _slow_writer_orchestrator(state_db, *, markers, admission=None):
    from mind_runtime.pipeline.stubs import StubEmotionalTransition
    from mind_runtime.slow_plasticity.writer import SlowPlasticityWriter
    from mind_runtime.state.definitions import StateDefinitionRegistry
    from mind_runtime.state.longitudinal import register_longitudinal_definition
    from tests.expression.test_context_slow_state import SLOW_DIM

    registry = StateDefinitionRegistry()
    register_longitudinal_definition(registry, key=SLOW_DIM)
    backend = SqliteStateBackend(state_db)
    for definition in registry.all():
        backend.save_definition(definition)
    writer = SlowPlasticityWriter(backend=backend, runtime_id="runtime-1", window_size=4)
    return TurnOrchestrator(
        clock=FakeClock(NOW),
        trace=TraceRecorder(),
        fact_ingest=_TypedFactPort(value="seeded"),
        state_backend=backend,
        commit_markers=markers,
        emotional_transition=_SlowDecisionTransition(
            StubEmotionalTransition(clock=FakeClock(NOW))
        ),
        definitions=registry,
        slow_plasticity_writer=writer,
        turn_admission=admission
        if admission is not None
        else NamespaceAdmissionAuthority.for_state_db(state_db),
    )


def _slow_versions(state_db):
    from mind_runtime.contracts import Scope, ScopeDomain
    from tests.expression.test_context_slow_state import SLOW_DIM

    # The seam derives the slow scope from the turn (no persona in these
    # tests) -> AGENT scope with the 'default' identity.
    slow_scope = Scope(
        domain=ScopeDomain.AGENT, agent_id="default", persona_id="default"
    )
    backend = SqliteStateBackend(state_db)
    try:
        states = backend.load_slow_states(slow_scope, SLOW_DIM)
        return sorted(s.version for s in states)
    finally:
        backend.close()


def test_t1_r1_same_interaction_marker_replay_writes_longitudinal_once(
    tmp_path: Any,
) -> None:
    state_db = tmp_path / "cognition_state.sqlite"
    _seed(state_db)
    markers = SqliteCommitMarkerStore(state_db)
    orch = _slow_writer_orchestrator(state_db, markers=markers)

    # First admission of interaction-A: the longitudinal seam runs.
    _run_turn(orch, "interaction-A", "A observed")
    first_versions = _slow_versions(state_db)
    assert len(first_versions) == 1

    # Same interaction committed AGAIN (admitted-turn replay, marker present):
    # the seam must NOT re-run — no second longitudinal contribution.
    _run_turn(orch, "interaction-A", "A observed again")
    assert _slow_versions(state_db) == first_versions
    orch._state_backend.close()
    markers.close()


def test_t2_r1_different_interaction_same_projection_is_not_a_replay(
    tmp_path: Any,
) -> None:
    from mind_runtime.contracts import Scope, ScopeDomain

    state_db = tmp_path / "cognition_state.sqlite"
    _seed(state_db)
    markers = SqliteCommitMarkerStore(state_db)
    orch_a = _slow_writer_orchestrator(state_db, markers=markers)

    # Interaction A admits (the stub projection is deterministic).
    _run_turn(orch_a, "interaction-A", "A observed")
    versions_after_a = _slow_versions(state_db)
    assert len(versions_after_a) == 1

    # Interaction B: DIFFERENT interaction identity. Whatever its projection
    # content is, projection equality must NOT classify B as a replay —
    # B's longitudinal contribution is real and appends.
    orch_b = _slow_writer_orchestrator(state_db, markers=markers)
    _run_turn(orch_b, "interaction-B", "B observed")
    versions_after_b = _slow_versions(state_db)
    assert len(versions_after_b) == len(versions_after_a) + 1

    scope = Scope(domain=ScopeDomain.USER, user_id="user-1")
    assert markers.has_commit(interaction_id="interaction-A", scope=scope)
    assert markers.has_commit(interaction_id="interaction-B", scope=scope)
    orch_a._state_backend.close()
    orch_b._state_backend.close()
    markers.close()
