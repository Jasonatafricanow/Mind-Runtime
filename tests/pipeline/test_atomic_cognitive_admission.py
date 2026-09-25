"""Tests for C10-RUNTIME-ATOMICITY-02: Atomic Cognitive Admission Implementation.

Authority: ADR-0021 (Cognitive Turn Atomic Admission Authority, ACCEPTED).

Invariants verified:
- One shared SQLite connection between SqliteStateBackend and SqliteCommitMarkerStore.
- Outer transaction owns BEGIN / COMMIT / ROLLBACK.
- Nested cognitive transactions fail closed immediately.
- Shared connection borrower close() is a no-op.
- Turn-local slow transient staging and durable transaction are within unified cleanup.
- Full C1-C11 crash matrix:
  * C1a: partial accept failure -> pending cleared, DB unchanged.
  * C1b: prepare_flush failure -> pending cleared, DB unchanged.
  * C2: fast state write failure -> ROLLBACK, DB unchanged.
  * C3: transition write failure -> ROLLBACK, DB unchanged.
  * C4: slow ledger append failure -> ROLLBACK, DB unchanged.
  * C5: slow trim failure -> ROLLBACK, DB unchanged.
  * C6: slow accumulator state failure -> ROLLBACK, DB unchanged.
  * C7: marker insert failure -> ROLLBACK, DB unchanged.
  * C8: crash after COMMIT -> reload restores complete canonical and slow state.
  * C9: retry after COMMIT -> replay suppression, zero duplicate writes.
  * C10: facts durable + cognition rolled back -> retry completes cognitive admission.
  * C11: failed slow staging retry -> exactly 1 contribution committed.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from mind_runtime.contracts import (
    Evidence,
    Interaction,
    InteractionStatus,
    Observation,
    RuntimeState,
    Scope,
    ScopeDomain,
    SyncFields,
)
from mind_runtime.facts.persistence import SqliteFactBackend
from mind_runtime.facts.ports import FactAdmissionDisposition, FactAdmissionResult
from mind_runtime.facts.service import FactIngestService
from mind_runtime.homeostasis.contracts import (
    CandidateStateDelta,
    HomeostasisDecision,
    HomeostasisDisposition,
)
from mind_runtime.pipeline.orchestrator import (
    CanonicalPersistenceError,
    TurnOrchestrator,
    TurnState,
)
from mind_runtime.pipeline.stubs import StubEmotionalTransition
from mind_runtime.pipeline.trace import TraceRecorder
from mind_runtime.runtime_admission import NamespaceAdmissionAuthority
from mind_runtime.slow_plasticity.writer import SlowPlasticityWriter
from mind_runtime.state.definitions import StateDefinitionRegistry
from mind_runtime.state.ids import canonical_state_id
from mind_runtime.state.longitudinal import register_longitudinal_definition
from mind_runtime.state.persistence import (
    CommitMarkerStore,
    SqliteCommitMarkerStore,
    SqliteStateBackend,
)
from tests.golden.fixtures.common import make_evidence, make_scope, make_state
from tests.support.fake_clock import FakeClock

NOW = datetime(2026, 9, 6, 12, 0, tzinfo=UTC)
FAST_DIM = "user.affect.stub"
SLOW_DIM = "agent.longitudinal.relationship_security"
SEED_TIME = NOW - timedelta(hours=2)


# ---------------------------------------------------------------------------
# Helpers & Fixtures
# ---------------------------------------------------------------------------


def _db_snapshot(db_path: Path | str) -> dict[str, list[tuple[Any, ...]]]:
    """Capture raw row snapshot of all four cognitive tables in cognition_state.sqlite."""
    with sqlite3.connect(str(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        tables = ("states", "state_transitions", "slow_contribution_window", "commit_markers")
        snapshot = {}
        for table in tables:
            rows = conn.execute(f"SELECT * FROM {table}").fetchall()
            snapshot[table] = [tuple(r) for r in rows]
        return snapshot


class _TypedFactPort:
    def __init__(self, *, value: object = "test-value") -> None:
        self._value = value

    def admit(
        self,
        evidence: Evidence,
        *,
        interaction_id: str,
        writing_runtime: str,
        writing_persona_id: str | None,
    ) -> FactAdmissionResult:
        scope = evidence.scope
        observation_id = f"observation-{evidence.id}"
        observation = Observation(
            id=observation_id,
            interaction_id=interaction_id,
            scope=scope,
            origin_runtime_id=writing_runtime,
            type="factual",
            key=f"{evidence.source_type}.observed",
            value=self._value,
            confidence=1.0,
            observed_at=evidence.occurred_at,
            evidence_refs=(evidence.id,),
            sync=SyncFields(scope, writing_runtime, observation_id, 1, "idem"),
        )
        return FactAdmissionResult(observation, FactAdmissionDisposition.NEW)


class _TransitionWithSlowDecision:
    def __init__(self, delegate: Any, *, proposed_value: float = 0.8, salience: float = 0.9) -> None:
        self._delegate = delegate
        self._proposed_value = proposed_value
        self._salience = salience

    def transition_with_gate(self, transition_input: Any) -> Any:
        from types import SimpleNamespace

        result = self._delegate.transition(transition_input)
        slow_scope = Scope(domain=ScopeDomain.AGENT, agent_id="default", persona_id="default")
        decision = HomeostasisDecision(
            candidate=CandidateStateDelta(
                target_dimension=SLOW_DIM,
                proposed_value=self._proposed_value,
                scope=slow_scope,
                evidence_refs=("ev-1",),
                source_event_ref="evt-test",
                salience=self._salience,
                confidence=1.0,
                observed_at=NOW,
            ),
            prior_value=None,
            decision=HomeostasisDisposition.SLOW_ACCEPT,
            reason_code="test-slow",
            decided_at=NOW,
        )
        return SimpleNamespace(
            transition_result=result,
            slow_decisions=(decision,),
        )


def _seed_db(state_db: Path | str) -> None:
    backend = SqliteStateBackend(state_db)
    # Ensure commit_markers table exists before taking pre-turn baseline snapshots
    SqliteCommitMarkerStore(state_db, connection=backend.connection)
    backend.save_state(
        make_state(
            dimension=FAST_DIM,
            value="seed-val",
            state_id=canonical_state_id(FAST_DIM, 1),
            now=SEED_TIME,
        )
    )
    registry = StateDefinitionRegistry()
    register_longitudinal_definition(registry, key=SLOW_DIM)
    for defn in registry.all():
        backend.save_definition(defn)
    backend.close()


def _make_stack(
    state_db: Path | str,
    *,
    fact_port: Any = None,
    proposed_value: float = 0.8,
    salience: float = 0.9,
    window_size: int = 4,
) -> tuple[TurnOrchestrator, SqliteStateBackend, SqliteCommitMarkerStore, SlowPlasticityWriter]:
    backend = SqliteStateBackend(state_db)
    # Shared connection wiring
    markers = SqliteCommitMarkerStore(state_db, connection=backend.connection)
    writer = SlowPlasticityWriter(
        backend=backend,
        runtime_id="runtime-1",
        window_size=window_size,
        clock=FakeClock(NOW),
    )
    registry = StateDefinitionRegistry()
    register_longitudinal_definition(registry, key=SLOW_DIM)

    clock = FakeClock(NOW)
    orch = TurnOrchestrator(
        clock=clock,
        trace=TraceRecorder(),
        fact_ingest=fact_port or _TypedFactPort(),
        state_backend=backend,
        commit_markers=markers,
        emotional_transition=_TransitionWithSlowDecision(
            StubEmotionalTransition(clock=clock),
            proposed_value=proposed_value,
            salience=salience,
        ),
        definitions=registry,
        slow_plasticity_writer=writer,
        turn_admission=NamespaceAdmissionAuthority.for_state_db(state_db),
    )
    return orch, backend, markers, writer


def _interaction(interaction_id: str) -> Interaction:
    return Interaction(
        interaction_id=interaction_id,
        scope=make_scope(),
        channel="chat",
        session_id=f"session-{interaction_id}",
        turn_id=f"turn-{interaction_id}",
        started_at=NOW,
        committed_at=None,
        status=InteractionStatus.OPEN,
    )


# ---------------------------------------------------------------------------
# Invariant Tests: Connection Lifecycle & Transaction Ownership
# ---------------------------------------------------------------------------


def test_shared_connection_close_is_noop_for_borrower(tmp_path: Path) -> None:
    db_path = tmp_path / "shared_conn.sqlite"
    backend = SqliteStateBackend(db_path)
    assert backend._owns_conn is True

    marker_store = SqliteCommitMarkerStore(db_path, connection=backend.connection)
    assert marker_store._owns_conn is False

    # Closing borrower store must NOT close the shared connection
    marker_store.close()
    assert backend.connection.execute("SELECT 1").fetchone()[0] == 1

    # Closing owner DOES close the connection
    backend.close()
    with pytest.raises(sqlite3.ProgrammingError):
        backend.connection.execute("SELECT 1")


def test_nested_transaction_fails_closed(tmp_path: Path) -> None:
    db_path = tmp_path / "nested_tx.sqlite"
    backend = SqliteStateBackend(db_path)
    try:
        with backend.transaction():
            with pytest.raises(RuntimeError, match="nested cognitive transaction forbidden"):
                with backend.transaction():
                    pass
    finally:
        backend.close()


def test_dynamic_marker_connection_adoption_lifecycle(tmp_path: Path) -> None:
    """Verify dynamic adoption lifecycle (A1–A4):
    - A1: Marker adopts backend.connection and becomes borrower (_owns_conn=False).
    - A4: Old marker connection is explicitly closed (no handle leak).
    - A2: Borrower marker.close() does not close shared backend connection.
    - A3: Owner backend.close() closes shared connection once.
    - No double-close errors on repeated cleanup.
    """
    db_path = tmp_path / "adoption_lifecycle.sqlite"
    backend = SqliteStateBackend(db_path)
    markers = SqliteCommitMarkerStore(db_path)

    conn_b = markers._conn
    assert backend._owns_conn is True
    assert markers._owns_conn is True
    assert conn_b is not backend.connection

    # Construct TurnOrchestrator -> triggers dynamic connection adoption
    orch = TurnOrchestrator(
        clock=FakeClock(NOW),
        trace=TraceRecorder(),
        state_backend=backend,
        commit_markers=markers,
    )

    # A1: Marker now uses backend connection and has borrower status
    assert markers._conn is backend.connection
    assert markers._owns_conn is False

    # A4: Old connection B was closed immediately at adoption (no leak)
    with pytest.raises(sqlite3.ProgrammingError, match="Cannot operate on a closed database"):
        conn_b.execute("SELECT 1")

    # A2: Borrower marker.close() is a no-op; shared connection A remains usable
    markers.close()
    assert backend.connection.execute("SELECT 1").fetchone()[0] == 1

    # A3: Owner backend.close() closes shared connection A
    backend.close()
    with pytest.raises(sqlite3.ProgrammingError):
        backend.connection.execute("SELECT 1")

    # Teardown: calling marker.close() again does not error (no double close)
    markers.close()


# ---------------------------------------------------------------------------
# Happy Path Atomic Commit
# ---------------------------------------------------------------------------


def test_atomic_fast_slow_marker_happy_path(tmp_path: Path) -> None:
    state_db = tmp_path / "cognition_state.sqlite"
    _seed_db(state_db)
    orch, backend, markers, writer = _make_stack(state_db)

    orch.begin_turn(_interaction("interaction-1"))
    orch.ingest(make_evidence(text="hello", evidence_id="ev-1", occurred_at=NOW))
    orch.run()
    orch.commit_turn()

    assert orch.state is TurnState.COMMITTED
    # Marker recorded
    slow_scope = Scope(domain=ScopeDomain.AGENT, agent_id="default", persona_id="default")
    assert markers.has_commit(interaction_id="interaction-1", scope=_interaction("interaction-1").scope)

    # Slow window persisted
    window = backend.load_slow_window(slow_scope, SLOW_DIM)
    assert len(window) == 1
    assert window[0]["proposed_value"] == 0.8

    # Slow accumulator state persisted
    slow_states = backend.load_slow_states(slow_scope, SLOW_DIM)
    assert len(slow_states) == 1
    assert slow_states[0].value == pytest.approx(0.8)

    # Fast states persisted
    fast_states = [s for s in backend.load_states() if s.dimension == FAST_DIM]
    assert len(fast_states) >= 2  # Seed + new state

    backend.close()


# ---------------------------------------------------------------------------
# C1–C11 Crash Matrix Tests
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("target_name", "method_name", "failure"),
    [
        ("writer", "accept", RuntimeError("accept failed")),
        ("writer", "prepare_flush", RuntimeError("prepare flush failed")),
        ("backend", "save_state", sqlite3.OperationalError("state write failed")),
        ("backend", "save_transition", sqlite3.OperationalError("transition write failed")),
        ("writer", "execute_flush_plan", sqlite3.OperationalError("slow flush failed")),
        ("markers", "record_commit", sqlite3.OperationalError("marker insert failed")),
    ],
    ids=["accept", "prepare-flush", "fast-state", "transition", "slow-flush", "marker"],
)
def test_precommit_failures_roll_back_all_cognitive_writes(
    tmp_path: Path,
    target_name: str,
    method_name: str,
    failure: Exception,
) -> None:
    """Any failure before COMMIT clears pending slow state and leaves the DB unchanged."""
    state_db = tmp_path / "cognition_state.sqlite"
    _seed_db(state_db)
    snapshot_before = _db_snapshot(state_db)
    orch, backend, markers, writer = _make_stack(state_db)
    targets = {"backend": backend, "markers": markers, "writer": writer}

    with patch.object(targets[target_name], method_name, side_effect=failure):
        orch.begin_turn(_interaction("interaction-failure"))
        orch.ingest(
            make_evidence(text="failure", evidence_id="ev-failure", occurred_at=NOW)
        )
        orch.run()
        with pytest.raises(CanonicalPersistenceError):
            orch.commit_turn()

    assert _db_snapshot(state_db) == snapshot_before
    assert len(writer._pending) == 0
    backend.close()


def test_c5_slow_window_trim_failure_rolls_back_all(tmp_path: Path) -> None:
    state_db = tmp_path / "cognition_state.sqlite"
    _seed_db(state_db)

    # Prime with 4 items to trigger trim when window_size=4
    orch, backend, markers, writer = _make_stack(state_db, window_size=4)
    for i in range(4):
        orch.begin_turn(_interaction(f"interaction-prime-{i}"))
        orch.ingest(make_evidence(text=f"prime-{i}", evidence_id=f"ev-prime-{i}", occurred_at=NOW + timedelta(seconds=i)))
        orch.run()
        orch.commit_turn()

    snapshot_before = _db_snapshot(state_db)

    # Now on the 5th turn, trim will execute DELETE. Inject failure in DELETE.
    with patch.object(backend, "_trim_slow_window", side_effect=sqlite3.OperationalError("injected trim DELETE failure")):
        orch.begin_turn(_interaction("interaction-c5"))
        orch.ingest(make_evidence(text="c5", evidence_id="ev-c5", occurred_at=NOW + timedelta(seconds=10)))
        orch.run()
        with pytest.raises(CanonicalPersistenceError):
            orch.commit_turn()

    assert _db_snapshot(state_db) == snapshot_before
    assert len(writer._pending) == 0
    backend.close()


def test_c6_slow_accumulator_state_failure_rolls_back_all(tmp_path: Path) -> None:
    state_db = tmp_path / "cognition_state.sqlite"
    _seed_db(state_db)
    snapshot_before = _db_snapshot(state_db)

    orch, backend, markers, writer = _make_stack(state_db)

    orig_insert = backend._insert_state

    # Inject failure during the accumulator RuntimeState write (dimension == SLOW_DIM)
    def failing_insert(state: RuntimeState) -> None:
        if state.dimension == SLOW_DIM:
            raise sqlite3.OperationalError("injected slow accumulator state failure")
        orig_insert(state)

    with patch.object(backend, "_insert_state", side_effect=failing_insert):
        orch.begin_turn(_interaction("interaction-c6"))
        orch.ingest(make_evidence(text="c6", evidence_id="ev-c6", occurred_at=NOW))
        orch.run()
        with pytest.raises(CanonicalPersistenceError):
            orch.commit_turn()

    # Everything rolled back: no fast state, no transition, no slow row, no marker
    assert _db_snapshot(state_db) == snapshot_before
    assert len(writer._pending) == 0
    backend.close()


def test_c8_crash_after_commit_reloads_complete_canonical_and_slow(tmp_path: Path) -> None:
    state_db = tmp_path / "cognition_state.sqlite"
    _seed_db(state_db)

    orch, backend, markers, writer = _make_stack(state_db)
    orch.begin_turn(_interaction("interaction-c8"))
    orch.ingest(make_evidence(text="c8", evidence_id="ev-c8", occurred_at=NOW))
    orch.run()
    orch.commit_turn()

    backend.close()

    # Restart in fresh process
    orch2, backend2, markers2, writer2 = _make_stack(state_db)
    slow_scope = Scope(domain=ScopeDomain.AGENT, agent_id="default", persona_id="default")
    writer2.load(slow_scope)

    # Canonical contains loaded fast states
    assert any(s.dimension == FAST_DIM for s in orch2.canonical)
    # Slow window contains the committed record
    window = backend2.load_slow_window(slow_scope, SLOW_DIM)
    assert len(window) == 1
    # Marker is present
    assert markers2.has_commit(interaction_id="interaction-c8", scope=_interaction("interaction-c8").scope)
    backend2.close()


def test_c9_retry_after_commit_is_idempotent_no_op(tmp_path: Path) -> None:
    state_db = tmp_path / "cognition_state.sqlite"
    _seed_db(state_db)

    orch, backend, markers, writer = _make_stack(state_db)
    orch.begin_turn(_interaction("interaction-c9"))
    orch.ingest(make_evidence(text="c9", evidence_id="ev-c9", occurred_at=NOW))
    orch.run()
    orch.commit_turn()

    snapshot_after_first = _db_snapshot(state_db)

    # Retry the same interaction
    orch.begin_turn(_interaction("interaction-c9"))
    orch.ingest(make_evidence(text="c9", evidence_id="ev-c9", occurred_at=NOW))
    orch.run()
    orch.commit_turn()

    # Absolutely identical: 0 new rows in any table
    assert _db_snapshot(state_db) == snapshot_after_first
    backend.close()


def test_c10_facts_committed_cognition_rolled_back_resumes_cleanly(tmp_path: Path) -> None:
    facts_db = tmp_path / "facts.sqlite"
    state_db = tmp_path / "cognition_state.sqlite"
    _seed_db(state_db)

    clock = FakeClock(NOW)
    fact_service = FactIngestService(clock=clock, backend=SqliteFactBackend(facts_db))

    orch, backend, markers, writer = _make_stack(state_db, fact_port=fact_service)

    # First attempt: ingest facts, then fail during cognitive transaction
    interaction = _interaction("interaction-c10")
    evidence = make_evidence(text="c10-msg", evidence_id="ev-c10", occurred_at=NOW)

    orch.begin_turn(interaction)
    obs = orch.ingest(evidence)
    assert obs is not None
    orch.run()

    # Injected error during cognitive write
    with patch.object(markers, "record_commit", side_effect=sqlite3.OperationalError("tx fail")):
        with pytest.raises(CanonicalPersistenceError):
            orch.commit_turn()

    # Verify facts are durable in facts.sqlite
    stored_evidence, original_id = fact_service._backend.find_evidence(evidence.scope, evidence.id)
    assert stored_evidence is not None
    # But cognitive marker is ABSENT
    assert markers.has_commit(interaction_id="interaction-c10", scope=interaction.scope) is False

    # Retry: second turn with same interaction & evidence
    orch.begin_turn(interaction)
    replay_obs = orch.ingest(evidence)
    assert replay_obs is not None
    assert replay_obs.id == obs.id

    orch.run()
    orch.commit_turn()

    assert orch.state is TurnState.COMMITTED
    assert markers.has_commit(interaction_id="interaction-c10", scope=interaction.scope) is True
    backend.close()


def test_c11_failed_slow_staging_retry_produces_single_contribution(tmp_path: Path) -> None:
    state_db = tmp_path / "cognition_state.sqlite"
    _seed_db(state_db)

    orch, backend, markers, writer = _make_stack(state_db)

    # First attempt: fail in prepare_flush
    with patch.object(writer, "prepare_flush", side_effect=RuntimeError("transient prep fail")):
        orch.begin_turn(_interaction("interaction-c11"))
        orch.ingest(make_evidence(text="c11", evidence_id="ev-c11", occurred_at=NOW))
        orch.run()
        with pytest.raises(CanonicalPersistenceError):
            orch.commit_turn()

    # Retry without failure
    orch.begin_turn(_interaction("interaction-c11"))
    orch.ingest(make_evidence(text="c11", evidence_id="ev-c11", occurred_at=NOW))
    orch.run()
    orch.commit_turn()

    slow_scope = Scope(domain=ScopeDomain.AGENT, agent_id="default", persona_id="default")
    window = backend.load_slow_window(slow_scope, SLOW_DIM)
    # Exactly one contribution row in the window, NOT two!
    assert len(window) == 1
    assert window[0]["sequence"] == 1
    backend.close()
