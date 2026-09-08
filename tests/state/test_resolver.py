"""D4.7 EffectiveStateResolver tests: the authoritative read gate."""

from datetime import UTC, datetime, timedelta

import pytest

from mind_runtime.contracts import StateDefinition, StateDomain, StateValueType
from mind_runtime.state.definitions import StateDefinitionRegistry
from mind_runtime.state.lifecycle import StateLifecycle
from mind_runtime.state.resolver import EffectiveStateResolver
from tests.golden.fixtures.common import make_scope, make_state

NOW = datetime(2026, 8, 21, 20, 0, tzinfo=UTC)

HEADACHE = StateDefinition(
    key="user.health.headache",
    domain=StateDomain.USER,
    value_type=StateValueType.CATEGORICAL,
    dynamics_policy="ttl_lifecycle",
    default_validity_policy="ttl:6h",
    bounds=None,
)


def make_resolver(*definitions: StateDefinition) -> EffectiveStateResolver:
    return EffectiveStateResolver(definitions=StateDefinitionRegistry(definitions))


def test_resolver_keeps_valid_active_state() -> None:
    state = make_state(dimension="user.health.headache", value="active", status="active")
    view = make_resolver(HEADACHE).resolve((state,), now=NOW)
    assert view.for_dimension("user.health.headache", make_scope()) is state
    assert view.resolved_at == NOW


def test_resolver_excludes_expired_current_like_state() -> None:
    expired = make_state(
        dimension="user.health.headache",
        value="active",
        status=StateLifecycle.EXPIRED.value,
    )
    view = make_resolver(HEADACHE).resolve((expired,), now=NOW)
    assert view.states == ()
    assert view.for_dimension("user.health.headache", make_scope()) is None


def test_resolver_excludes_ttl_lapsed_state_without_writing() -> None:
    # The fixture state has valid_until=None, so it never lapses; craft the
    # lapsed case via a TTL-derived envelope instead.
    from mind_runtime.state.reconciler import FactualReconciler, StateIntent
    from tests.support.fake_clock import FakeClock

    reconciler = FactualReconciler(
        clock=FakeClock(NOW - timedelta(hours=10)),
        definitions=StateDefinitionRegistry((HEADACHE,)),
    )
    created = reconciler.apply(
        (),
        (
            StateIntent(
                dimension="user.health.headache",
                value="active",
                observed_at=NOW - timedelta(hours=10),
                scope=make_scope(),
                origin_runtime_id="runtime-1",
                evidence_refs=("e-1",),
            ),
        ),
    ).effective_for("user.health.headache", make_scope())
    assert created is not None
    assert created.valid_until == NOW - timedelta(hours=4)
    view = make_resolver(HEADACHE).resolve((created,), now=NOW)
    assert view.states == ()
    # The read did not write anything: the record is untouched.
    assert created.status == StateLifecycle.ACTIVE.value


def test_resolver_keeps_terminal_states_effective() -> None:
    for status in (
        StateLifecycle.RESOLVED,
        StateLifecycle.COMPLETED,
        StateLifecycle.CANCELLED,
        StateLifecycle.SUPERSEDED,
    ):
        state = make_state(dimension="user.planning.calligraphy", value="x", status=status.value)
        view = make_resolver().resolve((state,), now=NOW)
        assert view.for_dimension("user.planning.calligraphy", make_scope()) is state, status


def test_resolver_overlay_replaces_canonical_for_dimension() -> None:
    """D4.8-ready: this turn's overlay record wins over canonical."""
    canonical = make_state(
        dimension="user.sleep.phase", value="sleeping", status="active", state_id="canonical"
    )
    overlay = make_state(
        dimension="user.sleep.phase", value="awake", status="active", state_id="overlay"
    )
    view = make_resolver().resolve((canonical,), now=NOW, overlay=(overlay,))
    assert view.for_dimension("user.sleep.phase", make_scope()) is overlay
    assert len(view.states) == 1


def test_resolver_overlay_does_not_mutate_canonical() -> None:
    canonical = make_state(
        dimension="user.sleep.phase", value="sleeping", status="active", state_id="canonical"
    )
    overlay = make_state(
        dimension="user.sleep.phase", value="awake", status="active", state_id="overlay"
    )
    make_resolver().resolve((canonical,), now=NOW, overlay=(overlay,))
    assert canonical.value == "sleeping"


def test_resolver_rejects_opaque_status_fail_closed() -> None:
    opaque = make_state(dimension="user.sleep.phase", value="x", status="current")
    with pytest.raises(ValueError, match="opaque"):
        make_resolver().resolve((opaque,), now=NOW)


def test_resolver_scope_isolation() -> None:
    scope_a = make_scope(user_id="user-a")
    scope_b = make_scope(user_id="user-b")
    state_a = make_state(
        dimension="user.sleep.phase", value="awake", status="active", scope=scope_a
    )
    state_b = make_state(
        dimension="user.sleep.phase", value="sleeping", status="active", scope=scope_b
    )
    view = make_resolver().resolve((state_b, state_a), now=NOW)
    assert view.for_scope(scope_a) == (state_a,)
    assert view.for_scope(scope_b) == (state_b,)
    # for_dimension scans past same-dimension records of other scopes.
    assert view.for_dimension("user.sleep.phase", scope_a) is state_a


def test_resolver_deterministic_for_replay() -> None:
    state = make_state(dimension="user.sleep.phase", value="awake", status="active")
    first = make_resolver().resolve((state,), now=NOW)
    second = make_resolver().resolve((state,), now=NOW)
    assert first == second


def test_resolver_duplicate_dimension_in_canonical_last_wins() -> None:
    older = make_state(
        dimension="user.sleep.phase", value="sleeping", status="active", state_id="old"
    )
    newer = make_state(dimension="user.sleep.phase", value="awake", status="active", state_id="new")
    view = make_resolver().resolve((older, newer), now=NOW)
    assert view.for_dimension("user.sleep.phase", make_scope()) is newer
    assert len(view.states) == 1


def test_resolver_overlay_can_introduce_new_dimension() -> None:
    overlay = make_state(
        dimension="user.health.headache", value="active", status="active", state_id="o-1"
    )
    view = make_resolver().resolve((), now=NOW, overlay=(overlay,))
    assert view.for_dimension("user.health.headache", make_scope()) is overlay


def test_resolver_keeps_state_valid_inside_envelope() -> None:
    """A current-like state with a future valid_until stays effective."""
    from mind_runtime.state.reconciler import FactualReconciler, StateIntent
    from tests.support.fake_clock import FakeClock

    reconciler = FactualReconciler(
        clock=FakeClock(NOW - timedelta(hours=1)),
        definitions=StateDefinitionRegistry((HEADACHE,)),
    )
    created = reconciler.apply(
        (),
        (
            StateIntent(
                dimension="user.health.headache",
                value="active",
                observed_at=NOW - timedelta(hours=1),
                scope=make_scope(),
                origin_runtime_id="runtime-1",
                evidence_refs=("e-1",),
            ),
        ),
    ).effective_for("user.health.headache", make_scope())
    assert created is not None
    assert created.valid_until == NOW + timedelta(hours=5)
    view = make_resolver(HEADACHE).resolve((created,), now=NOW)
    assert view.for_dimension("user.health.headache", make_scope()) is created
