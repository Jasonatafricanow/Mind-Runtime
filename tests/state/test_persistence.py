"""D4.4 SqliteStateBackend tests: states/state_transitions/state_definitions."""

import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

from mind_runtime.contracts import StateDefinition, StateDomain, StateValueType
from mind_runtime.state.definitions import StateDefinitionRegistry
from mind_runtime.state.persistence import SqliteStateBackend, canonical_state_rows_equal
from mind_runtime.state.reconciler import FactualReconciler, ReconcileResult, StateIntent
from tests.golden.fixtures.common import make_scope, make_state
from tests.support.fake_clock import FakeClock

NOW = datetime(2026, 8, 21, 16, 0, tzinfo=UTC)


def test_canonical_state_rows_equal_is_persistence_only_and_includes_status() -> None:
    admitted = make_state(status="active")
    changed_status = make_state(status="expired")

    assert canonical_state_rows_equal(admitted, admitted)
    assert not canonical_state_rows_equal(admitted, changed_status)

DEFINITION = StateDefinition(
    key="user.health.headache",
    domain=StateDomain.USER,
    value_type=StateValueType.CATEGORICAL,
    dynamics_policy="ttl_lifecycle",
    default_validity_policy="ttl:6h",
    bounds=None,
)


def make_reconciled(path: Path) -> tuple[SqliteStateBackend, ReconcileResult]:
    """Run one creation + supersession and persist everything."""
    backend = SqliteStateBackend(path)
    registry = StateDefinitionRegistry((DEFINITION,))
    reconciler = FactualReconciler(clock=FakeClock(NOW), definitions=registry)
    intent = StateIntent(
        dimension="user.health.headache",
        value="active",
        observed_at=NOW,
        scope=make_scope(),
        origin_runtime_id="runtime-1",
        evidence_refs=("evidence-1",),
    )
    result = reconciler.apply((), (intent,))
    superseded_result = reconciler.apply(
        result.canonical,
        (
            StateIntent(
                dimension="user.health.headache",
                value="recovered",
                observed_at=NOW + timedelta(hours=1),
                scope=make_scope(),
                origin_runtime_id="runtime-1",
                evidence_refs=("evidence-2",),
            ),
        ),
    )
    # Persist definitions, every record touched by a transition, and the
    # canonical currents, then the transitions.
    backend.save_definition(DEFINITION)
    records = set(superseded_result.canonical)
    for transition in superseded_result.transitions:
        records.add(transition.from_state)
        records.add(transition.to_state)
    for state in records:
        assert backend.save_state(state) is True
    for transition in superseded_result.transitions:
        assert backend.save_transition(transition) is True
    return backend, superseded_result


def test_state_db_inventory(tmp_path: Path) -> None:
    """D4 baseline (3 tables) + C10-B-W slow_contribution_window (1 table) +
    sqlite_sequence (auto-created by AUTOINCREMENT) = 5 tables total."""
    backend = SqliteStateBackend(tmp_path / "state.db")
    assert set(backend.table_names()) == {
        "state_definitions",
        "states",
        "slow_contribution_window",
        "sqlite_sequence",
        "state_transitions",
    }


def test_definition_round_trip(tmp_path: Path) -> None:
    backend = SqliteStateBackend(tmp_path / "state.db")
    backend.save_definition(DEFINITION)
    assert backend.load_definitions() == (DEFINITION,)


def test_definition_upsert_is_idempotent(tmp_path: Path) -> None:
    backend = SqliteStateBackend(tmp_path / "state.db")
    backend.save_definition(DEFINITION)
    backend.save_definition(DEFINITION)
    assert len(backend.load_definitions()) == 1


def test_non_serializable_state_value_fails_loud(tmp_path: Path) -> None:
    import pytest

    from mind_runtime.state.reconciler import StateIntent

    backend = SqliteStateBackend(tmp_path / "state.db")
    registry = StateDefinitionRegistry((DEFINITION,))
    reconciler = FactualReconciler(clock=FakeClock(NOW), definitions=registry)
    intent = StateIntent(
        dimension="user.health.headache",
        value=b"raw-bytes",  # deliberate corrupt input for the loud-failure test
        observed_at=NOW,
        scope=make_scope(),
        origin_runtime_id="runtime-1",
        evidence_refs=(),
    )
    state = reconciler.apply((), (intent,)).effective_for("user.health.headache", make_scope())
    assert state is not None
    with pytest.raises(ValueError, match="JSON-serializable"):
        backend.save_state(state)


def test_states_and_transitions_round_trip(tmp_path: Path) -> None:
    backend, result = make_reconciled(tmp_path / "state.db")
    loaded_states = backend.load_states()
    loaded_transitions = backend.load_transitions()
    # All records round-trip: 1 initial + 1 superseded + 1 fresh.
    assert len(loaded_states) == 3
    fresh = result.effective_for("user.health.headache", make_scope())
    assert fresh is not None
    assert any(state.state_id == fresh.state_id for state in loaded_states)
    assert len(loaded_transitions) == 2
    # Transition endpoints resolve to real records, not stubs.
    for transition in loaded_transitions:
        assert transition.from_state.dimension == "user.health.headache"
        assert transition.to_state.dimension == "user.health.headache"
    # The superseded terminal record is preserved in history.
    superseded_ids = {
        t.to_state.state_id for t in loaded_transitions if t.to_state.status == "superseded"
    }
    assert superseded_ids == {"user.health.headache:2"}


def test_duplicate_state_and_transition_rejected(tmp_path: Path) -> None:
    backend, _ = make_reconciled(tmp_path / "state.db")
    states = backend.load_states()
    assert backend.save_state(states[0]) is False
    transitions = backend.load_transitions()
    assert backend.save_transition(transitions[0]) is False


def test_transition_with_missing_state_fails_closed(tmp_path: Path) -> None:
    path = tmp_path / "state.db"
    SqliteStateBackend(path)
    conn = sqlite3.connect(path)
    conn.execute(
        "INSERT INTO state_transitions ("
        "transition_id, scope_domain, scope_user_id, origin_runtime_id, intent_id,"
        " from_state_id, to_state_id, committed_at, sync_version, sync_idem_key"
        ") VALUES ('transition:ghost', 'user', 'user-1', 'runtime-1', 'intent:ghost',"
        " 'missing-a', 'missing-b', ?, 1, 'idem')",
        (NOW.isoformat(),),
    )
    conn.commit()
    conn.close()
    backend = SqliteStateBackend(path)
    try:
        backend.load_transitions()
    except ValueError as error:
        assert "missing state" in str(error)
    else:
        raise AssertionError("load_transitions must fail closed on missing states")


def test_backend_close_and_reopen(tmp_path: Path) -> None:
    path = tmp_path / "state.db"
    backend, _ = make_reconciled(path)
    backend.close()
    reopened = SqliteStateBackend(path)
    assert len(reopened.load_states()) == 3
    assert len(reopened.load_transitions()) == 2
