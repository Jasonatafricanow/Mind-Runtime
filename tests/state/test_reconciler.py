"""D4.3 FactualReconciler tests: creation and reaffirm envelope refresh."""

from datetime import UTC, datetime, timedelta

import pytest

from mind_runtime.contracts import StateDefinition, StateDomain, StateValueType
from mind_runtime.state.definitions import StateDefinitionRegistry
from mind_runtime.state.lifecycle import StateLifecycle
from mind_runtime.state.reconciler import FactualReconciler, StateIntent
from tests.golden.fixtures.common import make_scope
from tests.support.fake_clock import FakeClock

NOW = datetime(2026, 8, 21, 9, 0, tzinfo=UTC)

TTL_HEADACHE = StateDefinition(
    key="user.health.headache",
    domain=StateDomain.USER,
    value_type=StateValueType.CATEGORICAL,
    dynamics_policy="ttl_lifecycle",
    default_validity_policy="ttl:6h",
    bounds=None,
)
EVENT_ONLY_PLAN = StateDefinition(
    key="user.planning.calligraphy",
    domain=StateDomain.USER,
    value_type=StateValueType.CATEGORICAL,
    dynamics_policy="event_only",
    default_validity_policy="event_only",
    bounds=None,
)


def make_reconciler(
    *definitions: StateDefinition, now: datetime = NOW
) -> tuple[FactualReconciler, FakeClock]:
    clock = FakeClock(now)
    registry = StateDefinitionRegistry(definitions)
    return FactualReconciler(clock=clock, definitions=registry), clock


def make_intent(
    *,
    dimension: str = "user.health.headache",
    value: object = "active",
    observed_at: datetime = NOW,
) -> StateIntent:
    return StateIntent(
        dimension=dimension,
        value=value,
        observed_at=observed_at,
        scope=make_scope(),
        origin_runtime_id="runtime-1",
        evidence_refs=("evidence-1",),
    )


def test_first_observation_creates_active_state_with_ttl_envelope() -> None:
    reconciler, _ = make_reconciler(TTL_HEADACHE)
    result = reconciler.apply((), (make_intent(),))
    assert result.transitions == ()
    state = result.effective_for("user.health.headache", make_scope())
    assert state is not None
    assert state.state_id == "user.health.headache:1"
    assert state.version == 1
    assert state.status == StateLifecycle.ACTIVE.value
    assert state.valid_from == NOW
    assert state.valid_until == NOW + timedelta(hours=6)
    assert state.evidence_refs == ("evidence-1",)


def test_creation_without_policy_has_no_valid_until() -> None:
    reconciler, _ = make_reconciler()
    result = reconciler.apply((), (make_intent(),))
    state = result.effective_for("user.health.headache", make_scope())
    assert state is not None
    assert state.valid_until is None


def test_reaffirm_refreshes_envelope_and_records_transition() -> None:
    reconciler, clock = make_reconciler(TTL_HEADACHE)
    created = reconciler.apply((), (make_intent(),)).effective_for(
        "user.health.headache", make_scope()
    )
    assert created is not None
    clock.advance(timedelta(hours=3))
    result = reconciler.apply((created,), (make_intent(),))
    refreshed = result.effective_for("user.health.headache", make_scope())
    assert refreshed is not None
    assert refreshed.status == StateLifecycle.ACTIVE.value
    assert refreshed.version == 2
    assert refreshed.state_id == "user.health.headache:2"
    assert refreshed.valid_from == NOW  # envelope start preserved
    assert refreshed.valid_until == NOW + timedelta(hours=3 + 6)  # refreshed
    assert refreshed.last_observed_at == NOW + timedelta(hours=3)
    assert len(result.transitions) == 1
    transition = result.transitions[0]
    assert transition.from_state is created
    assert transition.to_state is refreshed


def test_reaffirm_keeps_state_active_when_ttl_would_have_expired() -> None:
    """G2 core: reaffirm before lapse extends the envelope past the old TTL."""
    reconciler, clock = make_reconciler(TTL_HEADACHE)
    created = reconciler.apply((), (make_intent(),)).effective_for(
        "user.health.headache", make_scope()
    )
    assert created is not None
    assert created.valid_until == NOW + timedelta(hours=6)
    # Reaffirm at +5h (before the 6h lapse) refreshes the envelope.
    clock.advance(timedelta(hours=5))
    refreshed = reconciler.apply((created,), (make_intent(),)).effective_for(
        "user.health.headache", make_scope()
    )
    assert refreshed is not None
    assert refreshed.status == StateLifecycle.ACTIVE.value
    assert refreshed.valid_until == NOW + timedelta(hours=5 + 6)
    # At +7h — past the ORIGINAL lapse, inside the refreshed envelope — the
    # state is still active.
    clock.advance(timedelta(hours=2))
    still_active = reconciler.apply((refreshed,), ()).effective_for(
        "user.health.headache", make_scope()
    )
    assert still_active is not None
    assert still_active.status == StateLifecycle.ACTIVE.value


def test_reaffirm_after_expiry_starts_fresh_state() -> None:
    """A new intent on an already-expired record starts fresh (D4.4)."""
    reconciler, clock = make_reconciler(TTL_HEADACHE)
    created = reconciler.apply((), (make_intent(),)).effective_for(
        "user.health.headache", make_scope()
    )
    assert created is not None
    clock.advance(timedelta(hours=7))  # past the 6h envelope
    result = reconciler.apply((created,), (make_intent(),))
    fresh = result.effective_for("user.health.headache", make_scope())
    assert fresh is not None
    assert fresh.status == StateLifecycle.ACTIVE.value
    assert fresh.version == 3


def test_validity_pass_expires_stale_active_without_intents() -> None:
    reconciler, clock = make_reconciler(TTL_HEADACHE)
    created = reconciler.apply((), (make_intent(),)).effective_for(
        "user.health.headache", make_scope()
    )
    assert created is not None
    clock.advance(timedelta(hours=7))
    result = reconciler.apply((created,), ())
    expired = result.effective_for("user.health.headache", make_scope())
    assert expired is not None
    assert expired.status == StateLifecycle.EXPIRED.value
    assert expired.version == 2
    assert len(result.transitions) == 1
    assert result.transitions[0].to_state is expired


def test_reaffirm_on_event_only_dimension_is_noop() -> None:
    reconciler, clock = make_reconciler(EVENT_ONLY_PLAN)
    created = reconciler.apply(
        (),
        (make_intent(dimension="user.planning.calligraphy", value="planned"),),
    ).effective_for("user.planning.calligraphy", make_scope())
    assert created is not None
    clock.advance(timedelta(hours=5))
    result = reconciler.apply(
        (created,),
        (make_intent(dimension="user.planning.calligraphy", value="planned"),),
    )
    refreshed = result.effective_for("user.planning.calligraphy", make_scope())
    assert refreshed is created  # no envelope refresh, no new record
    assert result.transitions == ()


def test_supersession_new_value_ends_old_as_superseded() -> None:
    """D4.4 categorical supersession: A -> B keeps one current state."""
    reconciler, clock = make_reconciler(TTL_HEADACHE)
    created = reconciler.apply((), (make_intent(),)).effective_for(
        "user.health.headache", make_scope()
    )
    assert created is not None
    clock.advance(timedelta(hours=1))
    result = reconciler.apply((created,), (make_intent(value="recovered"),))
    fresh = result.effective_for("user.health.headache", make_scope())
    assert fresh is not None
    assert fresh.value == "recovered"
    assert fresh.status == StateLifecycle.ACTIVE.value
    assert fresh.version == 3  # old v1 -> superseded v2 -> fresh v3
    # Exactly one current state per dimension (single effective state).
    assert len(result.canonical) == 1
    # Two transitions: active -> superseded, superseded -> fresh active.
    assert len(result.transitions) == 2
    superseded = result.transitions[0].to_state
    assert superseded.status == StateLifecycle.SUPERSEDED.value
    assert result.transitions[1].from_state is superseded
    assert result.transitions[1].to_state is fresh


def test_superseded_terminal_is_protected_from_expiry() -> None:
    """The SUPERSEDED record is terminal: time never expires it."""
    reconciler, clock = make_reconciler(TTL_HEADACHE)
    created = reconciler.apply((), (make_intent(),)).effective_for(
        "user.health.headache", make_scope()
    )
    assert created is not None
    result = reconciler.apply((created,), (make_intent(value="recovered"),))
    superseded = result.transitions[0].to_state
    assert superseded.status == StateLifecycle.SUPERSEDED.value
    # Time passes far beyond the envelope; the superseded record stays.
    clock.advance(timedelta(days=30))
    still = reconciler.apply((superseded,), ()).effective_for("user.health.headache", make_scope())
    assert still is not None
    assert still.status == StateLifecycle.SUPERSEDED.value


def test_new_observation_after_terminal_starts_fresh_state() -> None:
    """A terminal answers 'what happened'; a new plan starts fresh (D4.4)."""
    reconciler, clock = make_reconciler(TTL_HEADACHE)
    from tests.golden.fixtures.common import make_state

    cancelled = make_state(
        dimension="user.planning.calligraphy", value="cancelled", status="cancelled"
    )
    clock.advance(timedelta(hours=3))
    result = reconciler.apply(
        (cancelled,),
        (
            make_intent(
                dimension="user.planning.calligraphy",
                value="planned",
                observed_at=NOW + timedelta(hours=3),
            ),
        ),
    )
    fresh = result.effective_for("user.planning.calligraphy", make_scope())
    assert fresh is not None
    assert fresh.value == "planned"
    assert fresh.status == StateLifecycle.ACTIVE.value
    assert len(result.transitions) == 1
    assert result.transitions[0].from_state is cancelled
    # The cancelled record itself was never rewritten.
    assert cancelled.status == "cancelled"


def test_opaque_status_fails_closed() -> None:
    reconciler, _ = make_reconciler(TTL_HEADACHE)
    from tests.golden.fixtures.common import make_state

    opaque = make_state(dimension="user.health.headache", value="x", status="current")
    with pytest.raises(ValueError, match="opaque"):
        reconciler.apply((opaque,), (make_intent(),))


def test_scope_isolation_same_dimension_different_scopes() -> None:
    reconciler, _ = make_reconciler(TTL_HEADACHE)
    scope_a = make_scope(user_id="user-a")
    scope_b = make_scope(user_id="user-b")
    intent_a = StateIntent(
        dimension="user.health.headache",
        value="active",
        observed_at=NOW,
        scope=scope_a,
        origin_runtime_id="runtime-1",
        evidence_refs=("e-a",),
    )
    intent_b = StateIntent(
        dimension="user.health.headache",
        value="active",
        observed_at=NOW,
        scope=scope_b,
        origin_runtime_id="runtime-1",
        evidence_refs=("e-b",),
    )
    result = reconciler.apply((), (intent_a, intent_b))
    state_a = result.effective_for("user.health.headache", scope_a)
    state_b = result.effective_for("user.health.headache", scope_b)
    assert state_a is not None
    assert state_b is not None
    assert state_a.evidence_refs == ("e-a",)
    assert state_b.evidence_refs == ("e-b",)


def test_sequential_intents_bump_versions() -> None:
    reconciler, clock = make_reconciler(TTL_HEADACHE)
    first = reconciler.apply((), (make_intent(),)).effective_for(
        "user.health.headache", make_scope()
    )
    assert first is not None
    clock.advance(timedelta(minutes=10))
    second = reconciler.apply((first,), (make_intent(),)).effective_for(
        "user.health.headache", make_scope()
    )
    assert second is not None
    assert second.version == 2
    clock.advance(timedelta(minutes=10))
    third = reconciler.apply(
        (second,), (make_intent(observed_at=NOW + timedelta(minutes=20)),)
    ).effective_for("user.health.headache", make_scope())
    assert third is not None
    assert third.version == 3
    assert third.state_id == "user.health.headache:3"


def test_replay_determinism() -> None:
    reconciler, _ = make_reconciler(TTL_HEADACHE)
    first = reconciler.apply((), (make_intent(),))
    second = reconciler.apply((), (make_intent(),))
    assert first == second


def test_effective_for_unknown_dimension_returns_none() -> None:
    reconciler, _ = make_reconciler(TTL_HEADACHE)
    result = reconciler.apply((), (make_intent(),))
    assert result.effective_for("user.never.seen", make_scope()) is None


def test_explicit_terminal_intent_cancels_current_state() -> None:
    """D4.4 explicit terminal: CANCELLED intent turns the state terminal."""
    reconciler, clock = make_reconciler(TTL_HEADACHE)
    created = reconciler.apply((), (make_intent(),)).effective_for(
        "user.health.headache", make_scope()
    )
    assert created is not None
    clock.advance(timedelta(hours=1))
    intent = StateIntent(
        dimension="user.health.headache",
        value="active",
        observed_at=NOW + timedelta(hours=1),
        scope=make_scope(),
        origin_runtime_id="runtime-1",
        evidence_refs=("evidence-2",),
        lifecycle=StateLifecycle.CANCELLED,
    )
    result = reconciler.apply((created,), (intent,))
    cancelled = result.effective_for("user.health.headache", make_scope())
    assert cancelled is not None
    assert cancelled.status == StateLifecycle.CANCELLED.value
    assert cancelled.value == "active"  # value preserved; lifecycle answered
    assert len(result.transitions) == 1
    assert result.transitions[0].to_state is cancelled


def test_repeat_same_terminal_intent_is_idempotent() -> None:
    reconciler, _ = make_reconciler(TTL_HEADACHE)
    created = reconciler.apply((), (make_intent(),)).effective_for(
        "user.health.headache", make_scope()
    )
    assert created is not None
    intent = StateIntent(
        dimension="user.health.headache",
        value="active",
        observed_at=NOW,
        scope=make_scope(),
        origin_runtime_id="runtime-1",
        evidence_refs=("evidence-2",),
        lifecycle=StateLifecycle.CANCELLED,
    )
    cancelled = reconciler.apply((created,), (intent,)).effective_for(
        "user.health.headache", make_scope()
    )
    assert cancelled is not None
    result = reconciler.apply((cancelled,), (intent,))
    assert result.effective_for("user.health.headache", make_scope()) is cancelled
    assert result.transitions == ()


def test_terminal_to_different_terminal_is_illegal() -> None:
    reconciler, _ = make_reconciler(TTL_HEADACHE)
    created = reconciler.apply((), (make_intent(),)).effective_for(
        "user.health.headache", make_scope()
    )
    assert created is not None
    cancel = StateIntent(
        dimension="user.health.headache",
        value="active",
        observed_at=NOW,
        scope=make_scope(),
        origin_runtime_id="runtime-1",
        evidence_refs=(),
        lifecycle=StateLifecycle.CANCELLED,
    )
    cancelled = reconciler.apply((created,), (cancel,)).effective_for(
        "user.health.headache", make_scope()
    )
    assert cancelled is not None
    resolve = StateIntent(
        dimension="user.health.headache",
        value="active",
        observed_at=NOW,
        scope=make_scope(),
        origin_runtime_id="runtime-1",
        evidence_refs=(),
        lifecycle=StateLifecycle.RESOLVED,
    )
    with pytest.raises(ValueError, match="illegal terminal transition"):
        reconciler.apply((cancelled,), (resolve,))


def test_explicit_completed_and_resolved_terminals() -> None:
    for lifecycle in (StateLifecycle.COMPLETED, StateLifecycle.RESOLVED):
        reconciler, _ = make_reconciler(TTL_HEADACHE)
        created = reconciler.apply((), (make_intent(),)).effective_for(
            "user.health.headache", make_scope()
        )
        assert created is not None
        intent = StateIntent(
            dimension="user.health.headache",
            value="active",
            observed_at=NOW,
            scope=make_scope(),
            origin_runtime_id="runtime-1",
            evidence_refs=(),
            lifecycle=lifecycle,
        )
        terminal = reconciler.apply((created,), (intent,)).effective_for(
            "user.health.headache", make_scope()
        )
        assert terminal is not None
        assert terminal.status == lifecycle.value


def test_new_observation_after_expiry_starts_fresh_state() -> None:
    """An expired current is not resurrected; the observation starts fresh."""
    reconciler, clock = make_reconciler(TTL_HEADACHE)
    created = reconciler.apply((), (make_intent(),)).effective_for(
        "user.health.headache", make_scope()
    )
    assert created is not None
    clock.advance(timedelta(hours=7))  # past the 6h envelope
    result = reconciler.apply((created,), (make_intent(),))
    fresh = result.effective_for("user.health.headache", make_scope())
    assert fresh is not None
    assert fresh.status == StateLifecycle.ACTIVE.value
    assert fresh.version == 3  # v1 active -> v2 expired -> v3 fresh
    expired = result.transitions[0].to_state
    assert expired.status == StateLifecycle.EXPIRED.value
    assert len(result.transitions) == 2


def test_reaffirm_indefinite_policy_keeps_valid_until_none() -> None:
    reconciler, clock = make_reconciler()  # no definition -> indefinite
    created = reconciler.apply((), (make_intent(),)).effective_for(
        "user.health.headache", make_scope()
    )
    assert created is not None
    assert created.valid_until is None
    clock.advance(timedelta(hours=2))
    refreshed = reconciler.apply((created,), (make_intent(),)).effective_for(
        "user.health.headache", make_scope()
    )
    assert refreshed is not None
    assert refreshed.valid_until is None
    assert refreshed.last_observed_at == NOW + timedelta(hours=2)


def test_duplicate_dimension_in_canonical_last_wins() -> None:
    reconciler, _ = make_reconciler(TTL_HEADACHE)
    from tests.golden.fixtures.common import make_state

    older = make_state(
        dimension="user.health.headache", value="old", status="active", state_id="old"
    )
    newer = make_state(
        dimension="user.health.headache", value="active", status="active", state_id="new"
    )
    result = reconciler.apply((older, newer), (make_intent(),))
    state = result.effective_for("user.health.headache", make_scope())
    assert state is not None
    assert state.version == 2  # refreshed from the NEWER record, not the older
    assert len(result.canonical) == 1


# --- D4.5 delayed observation anti-rollback (G9) ---


def test_delayed_different_value_never_rolls_back_newer_state() -> None:
    """G9 core: an old 'sleeping' event must not roll back 'awake'."""
    reconciler, clock = make_reconciler()
    from tests.golden.fixtures.common import make_state

    awake = make_state(
        dimension="user.sleep.phase",
        value="awake",
        status="active",
        now=NOW,
    )
    clock.advance(timedelta(hours=2))
    delayed = StateIntent(
        dimension="user.sleep.phase",
        value="sleeping",
        observed_at=NOW - timedelta(minutes=1),  # strictly older
        scope=make_scope(),
        origin_runtime_id="runtime-1",
        evidence_refs=("evidence-delayed",),
    )
    result = reconciler.apply((awake,), (delayed,))
    current = result.effective_for("user.sleep.phase", make_scope())
    assert current is awake  # unchanged, no rollback
    assert result.transitions == ()
    assert result.deferred == (delayed,)


def test_delayed_same_value_does_not_refresh_envelope() -> None:
    """A delayed reaffirm must not extend the envelope from stale evidence."""
    reconciler, clock = make_reconciler(TTL_HEADACHE)
    created = reconciler.apply((), (make_intent(),)).effective_for(
        "user.health.headache", make_scope()
    )
    assert created is not None
    clock.advance(timedelta(hours=2))
    delayed = StateIntent(
        dimension="user.health.headache",
        value="active",
        observed_at=NOW - timedelta(minutes=1),  # strictly older
        scope=make_scope(),
        origin_runtime_id="runtime-1",
        evidence_refs=("evidence-old",),
    )
    result = reconciler.apply((created,), (delayed,))
    assert result.effective_for("user.health.headache", make_scope()) is created
    assert result.transitions == ()
    assert len(result.deferred) == 1


def test_ontime_observation_still_supersedes() -> None:
    """Anti-rollback only shields newer states from OLDER intents."""
    reconciler, clock = make_reconciler(TTL_HEADACHE)
    created = reconciler.apply((), (make_intent(),)).effective_for(
        "user.health.headache", make_scope()
    )
    assert created is not None
    clock.advance(timedelta(hours=2))
    on_time = StateIntent(
        dimension="user.health.headache",
        value="recovered",
        observed_at=NOW + timedelta(hours=2),  # equal to last_observed_at
        scope=make_scope(),
        origin_runtime_id="runtime-1",
        evidence_refs=("evidence-new",),
    )
    result = reconciler.apply((created,), (on_time,))
    fresh = result.effective_for("user.health.headache", make_scope())
    assert fresh is not None
    assert fresh.value == "recovered"
    assert result.deferred == ()


def test_multiple_delayed_intents_all_deferred() -> None:
    reconciler, clock = make_reconciler()
    from tests.golden.fixtures.common import make_state

    awake = make_state(
        dimension="user.sleep.phase",
        value="awake",
        status="active",
        now=NOW,
    )
    clock.advance(timedelta(hours=1))
    first = StateIntent(
        dimension="user.sleep.phase",
        value="sleeping",
        observed_at=NOW - timedelta(minutes=1),
        scope=make_scope(),
        origin_runtime_id="runtime-1",
        evidence_refs=("e-1",),
    )
    second = StateIntent(
        dimension="user.sleep.phase",
        value="dreaming",
        observed_at=NOW - timedelta(minutes=2),
        scope=make_scope(),
        origin_runtime_id="runtime-1",
        evidence_refs=("e-2",),
    )
    result = reconciler.apply((awake,), (first, second))
    assert result.deferred == (first, second)
    assert result.effective_for("user.sleep.phase", make_scope()) is awake


def test_delayed_intent_on_fresh_dimension_still_creates() -> None:
    """Anti-rollback needs a newer state to protect; creation is unaffected."""
    reconciler, _ = make_reconciler()
    old_intent = StateIntent(
        dimension="user.sleep.phase",
        value="sleeping",
        observed_at=NOW - timedelta(days=1),
        scope=make_scope(),
        origin_runtime_id="runtime-1",
        evidence_refs=("e-old",),
    )
    result = reconciler.apply((), (old_intent,))
    created = result.effective_for("user.sleep.phase", make_scope())
    assert created is not None
    assert created.value == "sleeping"
    assert result.deferred == ()
