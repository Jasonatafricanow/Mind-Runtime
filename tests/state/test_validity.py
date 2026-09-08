"""D4.2 TTL / validity resolver tests."""

from datetime import UTC, datetime, timedelta

from mind_runtime.contracts import RuntimeState, SyncFields
from mind_runtime.state.lifecycle import StateLifecycle
from mind_runtime.state.validity import evaluate_validity
from tests.golden.fixtures.common import make_scope

NOW = datetime(2026, 8, 21, 18, 0, tzinfo=UTC)


def make_state(
    *,
    status: str,
    valid_until: datetime | None,
    state_id: str = "state-1",
    version: int = 1,
    relevant_until: datetime | None = None,
) -> RuntimeState:
    scope = make_scope()
    return RuntimeState(
        state_id=state_id,
        scope=scope,
        dimension="user.health.headache",
        value="active",
        status=status,
        valid_from=NOW - timedelta(hours=10),
        valid_until=valid_until,
        relevant_until=relevant_until,
        last_observed_at=NOW - timedelta(hours=10),
        evidence_refs=("evidence-1",),
        transition_refs=(),
        updated_at=NOW - timedelta(hours=10),
        origin_runtime_id="runtime-1",
        version=version,
        sync=SyncFields(scope, "runtime-1", state_id, version, f"idem-{state_id}"),
    )


def test_active_expires_when_past_valid_until() -> None:
    state = make_state(status=StateLifecycle.ACTIVE.value, valid_until=NOW - timedelta(hours=1))
    outcome = evaluate_validity(state, now=NOW)
    assert outcome.changed is True
    assert outcome.expired is True
    assert outcome.reason == "expired_by_ttl"
    assert outcome.state.status == StateLifecycle.EXPIRED.value
    assert outcome.state.state_id == "user.health.headache:2"
    assert outcome.state.version == state.version + 1
    assert outcome.state.updated_at == NOW
    # The original record is untouched (immutable history).
    assert state.status == StateLifecycle.ACTIVE.value


def test_improving_expires_when_past_valid_until() -> None:
    state = make_state(
        status=StateLifecycle.IMPROVING.value, valid_until=NOW - timedelta(minutes=1)
    )
    outcome = evaluate_validity(state, now=NOW)
    assert outcome.expired is True
    assert outcome.state.status == StateLifecycle.EXPIRED.value


def test_active_valid_at_boundary_inclusive() -> None:
    state = make_state(status=StateLifecycle.ACTIVE.value, valid_until=NOW)
    outcome = evaluate_validity(state, now=NOW)
    assert outcome.changed is False
    assert outcome.reason == "valid"
    assert outcome.state is state


def test_active_without_valid_until_stays_valid() -> None:
    state = make_state(status=StateLifecycle.ACTIVE.value, valid_until=None)
    outcome = evaluate_validity(state, now=NOW)
    assert outcome.changed is False
    assert outcome.reason == "valid"


def test_terminal_never_expires_even_past_valid_until() -> None:
    for status in (
        StateLifecycle.RESOLVED,
        StateLifecycle.COMPLETED,
        StateLifecycle.CANCELLED,
        StateLifecycle.SUPERSEDED,
    ):
        state = make_state(status=status.value, valid_until=NOW - timedelta(days=30))
        outcome = evaluate_validity(state, now=NOW)
        assert outcome.changed is False, status
        assert outcome.expired is False, status
        assert outcome.reason == "terminal_protected"
        assert outcome.state is state
        assert state.status == status.value


def test_terminal_protection_ignores_relevant_until() -> None:
    # Relevance (D4.6) is separate: even with a lapsed relevant_until the
    # lifecycle stays terminal, never expired.
    state = make_state(
        status=StateLifecycle.CANCELLED.value,
        valid_until=NOW - timedelta(days=1),
        relevant_until=NOW - timedelta(hours=3),
    )
    outcome = evaluate_validity(state, now=NOW)
    assert outcome.changed is False
    assert outcome.reason == "terminal_protected"


def test_unknown_status_is_opaque_and_untouched() -> None:
    state = make_state(status="current", valid_until=NOW - timedelta(hours=1))
    outcome = evaluate_validity(state, now=NOW)
    assert outcome.changed is False
    assert outcome.reason == "opaque_status"
    assert outcome.state is state


def test_expiration_is_deterministic_for_replay() -> None:
    state = make_state(status=StateLifecycle.ACTIVE.value, valid_until=NOW - timedelta(hours=1))
    first = evaluate_validity(state, now=NOW)
    second = evaluate_validity(state, now=NOW)
    assert first.state == second.state
    assert first.state.sync == second.state.sync
