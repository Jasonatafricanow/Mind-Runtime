"""D4.6 relevance separation tests: cancelled stays cancelled, relevance lapses."""

from datetime import UTC, datetime, timedelta

import pytest

from mind_runtime.contracts import RuntimeState, SyncFields
from mind_runtime.state.lifecycle import StateLifecycle
from mind_runtime.state.relevance import RelevanceOutcome, evaluate_relevance
from tests.golden.fixtures.common import make_scope

NOW = datetime(2026, 8, 21, 18, 0, tzinfo=UTC)


def make_state(
    *,
    status: str,
    relevant_until: datetime | None,
    dimension: str = "user.planning.calligraphy",
    value: str = "cancelled",
) -> RuntimeState:
    scope = make_scope()
    return RuntimeState(
        state_id=f"{dimension}:1",
        scope=scope,
        dimension=dimension,
        value=value,
        status=status,
        valid_from=NOW - timedelta(hours=3),
        valid_until=None,
        relevant_until=relevant_until,
        last_observed_at=NOW - timedelta(hours=3),
        evidence_refs=(),
        transition_refs=(),
        updated_at=NOW - timedelta(hours=3),
        origin_runtime_id="runtime-1",
        version=1,
        sync=SyncFields(scope, "runtime-1", f"{dimension}:1", 1, "idem"),
    )


def test_cancelled_without_relevant_until_is_recently_cancelled() -> None:
    outcome = evaluate_relevance(make_state(status="cancelled", relevant_until=None), now=NOW)
    assert isinstance(outcome, RelevanceOutcome)
    assert outcome.recently_cancelled is True
    assert outcome.reason == "cancelled_within_window"


def test_cancelled_within_window_is_recently_cancelled() -> None:
    state = make_state(status="cancelled", relevant_until=NOW + timedelta(hours=1))
    outcome = evaluate_relevance(state, now=NOW)
    assert outcome.recently_cancelled is True


def test_cancelled_at_window_boundary_is_recently_cancelled() -> None:
    state = make_state(status="cancelled", relevant_until=NOW)
    outcome = evaluate_relevance(state, now=NOW)
    assert outcome.recently_cancelled is True


def test_cancelled_with_lapsed_window_loses_relevance_not_lifecycle() -> None:
    """G3 core: cancelled never becomes expired; relevance can lapse."""
    state = make_state(status="cancelled", relevant_until=NOW - timedelta(hours=1))
    outcome = evaluate_relevance(state, now=NOW)
    assert outcome.recently_cancelled is False
    assert outcome.reason == "cancelled_window_lapsed"
    # The lifecycle record is untouched.
    assert state.status == StateLifecycle.CANCELLED.value


def test_non_cancelled_states_are_not_recently_cancelled() -> None:
    for status in (
        StateLifecycle.ACTIVE.value,
        StateLifecycle.EXPIRED.value,
        StateLifecycle.RESOLVED.value,
        StateLifecycle.COMPLETED.value,
        StateLifecycle.SUPERSEDED.value,
        StateLifecycle.IMPROVING.value,
    ):
        outcome = evaluate_relevance(make_state(status=status, relevant_until=None), now=NOW)
        assert outcome.recently_cancelled is False, status
        assert outcome.reason == "not_cancelled"


def test_relevance_dimension_and_scope_carried() -> None:
    state = make_state(status="cancelled", relevant_until=None)
    outcome = evaluate_relevance(state, now=NOW)
    assert outcome.dimension == "user.planning.calligraphy"
    assert outcome.scope == state.scope


def test_relevance_deterministic_for_replay() -> None:
    state = make_state(status="cancelled", relevant_until=NOW - timedelta(hours=1))
    assert evaluate_relevance(state, now=NOW) == evaluate_relevance(state, now=NOW)


def test_reconcile_keeps_cancelled_and_relevance_stays_true() -> None:
    """Golden G3 path: cancelled state with no intents keeps lifecycle and context."""
    from mind_runtime.state.definitions import StateDefinitionRegistry
    from mind_runtime.state.reconciler import FactualReconciler
    from tests.support.fake_clock import FakeClock

    registry = StateDefinitionRegistry()
    reconciler = FactualReconciler(clock=FakeClock(NOW), definitions=registry)
    cancelled = make_state(status="cancelled", relevant_until=None)
    result = reconciler.apply((cancelled,), ())
    current = result.effective_for("user.planning.calligraphy", make_scope())
    assert current is not None
    assert current.status == StateLifecycle.CANCELLED.value
    outcome = evaluate_relevance(current, now=NOW)
    assert outcome.recently_cancelled is True


@pytest.mark.parametrize("status", ["active", "expired", "resolved", "completed", "superseded"])
def test_validity_and_relevance_do_not_touch_lifecycle(status: str) -> None:
    """relevance evaluation never rewrites lifecycle (read-only view)."""
    state = make_state(status=status, relevant_until=NOW - timedelta(hours=5))
    before = state.status
    evaluate_relevance(state, now=NOW)
    assert state.status == before
