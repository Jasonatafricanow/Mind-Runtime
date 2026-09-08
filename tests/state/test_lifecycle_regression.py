"""D4.9 Statebar lifecycle regression suite (migrated, no old schema).

The V0.1.4 baseline requires Statebar's core lifecycle regressions to be
re-expressed as new Domain tests. Each test maps to one P0 finding from the
Statebar audit (Track A):

- P0-1 EffectiveStateResolver is the only read gate (DECISION-005).
- P0-2 CURRENT_LIKE expiration by TTL.
- P0-3 terminal status protection (never rewritten to expired by time).
- P0-4 reaffirm refresh of the temporal envelope.
- P0-5 the reconciler consumes the resolved view, never raw status.
- P0-6 relevance is an independent filter from lifecycle.
- P0-7 lifecycle transition legality (illegal transitions fail closed).
- P0-8 transactional writes (each durable write is atomic; duplicates
  rejected without partial state).
- P0-9 ambiguous terminal intent fails closed.

No Statebar schema, table, or value vocabulary is copied.
"""

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from mind_runtime.contracts import StateDefinition, StateDomain, StateValueType
from mind_runtime.state.definitions import StateDefinitionRegistry
from mind_runtime.state.lifecycle import StateLifecycle
from mind_runtime.state.reconciler import FactualReconciler, StateIntent
from mind_runtime.state.resolver import EffectiveStateResolver
from mind_runtime.state.validity import evaluate_validity
from tests.golden.fixtures.common import make_scope, make_state
from tests.support.fake_clock import FakeClock

NOW = datetime(2026, 8, 21, 23, 0, tzinfo=UTC)

HEADACHE = StateDefinition(
    key="user.health.headache",
    domain=StateDomain.USER,
    value_type=StateValueType.CATEGORICAL,
    dynamics_policy="ttl_lifecycle",
    default_validity_policy="ttl:6h",
    bounds=None,
)


def make_reconciler(now: datetime = NOW) -> tuple[FactualReconciler, FakeClock]:
    clock = FakeClock(now)
    reconciler = FactualReconciler(clock=clock, definitions=StateDefinitionRegistry((HEADACHE,)))
    return reconciler, clock


def make_intent(value: object = "active", *, observed_at: datetime = NOW) -> StateIntent:
    return StateIntent(
        dimension="user.health.headache",
        value=value,
        observed_at=observed_at,
        scope=make_scope(),
        origin_runtime_id="runtime-1",
        evidence_refs=("evidence-1",),
    )


def test_p0_1_consumers_see_only_the_resolver_view() -> None:
    """DECISION-005: 'current state' is a computed result, never raw reads."""
    reconciler, clock = make_reconciler()
    stale = reconciler.apply((), (make_intent(),)).effective_for(
        "user.health.headache", make_scope()
    )
    assert stale is not None
    # The raw record says active; time moves past its envelope.
    clock.advance(timedelta(hours=7))
    view = EffectiveStateResolver(definitions=StateDefinitionRegistry((HEADACHE,))).resolve(
        (stale,), now=clock.now()
    )
    # The authoritative view says: no effective headache state.
    assert view.for_dimension("user.health.headache", make_scope()) is None
    # A raw consumer would be wrong to use the stale 'active' record.


def test_p0_2_current_like_expiration() -> None:
    reconciler, clock = make_reconciler()
    created = reconciler.apply((), (make_intent(),)).effective_for(
        "user.health.headache", make_scope()
    )
    assert created is not None
    clock.advance(timedelta(hours=7))
    outcome = evaluate_validity(created, now=clock.now())
    assert outcome.expired is True
    assert outcome.state.status == StateLifecycle.EXPIRED.value


def test_p0_3_terminal_status_never_expires() -> None:
    for status in (
        StateLifecycle.RESOLVED,
        StateLifecycle.COMPLETED,
        StateLifecycle.CANCELLED,
        StateLifecycle.SUPERSEDED,
    ):
        terminal = make_state(dimension="user.planning.calligraphy", value="x", status=status.value)
        outcome = evaluate_validity(terminal, now=NOW + timedelta(days=3650))
        assert outcome.changed is False, status
        assert terminal.status == status.value


def test_p0_4_reaffirm_refreshes_envelope() -> None:
    reconciler, clock = make_reconciler()
    created = reconciler.apply((), (make_intent(),)).effective_for(
        "user.health.headache", make_scope()
    )
    assert created is not None
    clock.advance(timedelta(hours=3))
    refreshed = reconciler.apply((created,), (make_intent(observed_at=clock.now()),)).effective_for(
        "user.health.headache", make_scope()
    )
    assert refreshed is not None
    assert refreshed.status == StateLifecycle.ACTIVE.value
    assert refreshed.valid_until == clock.now() + timedelta(hours=6)


def test_p0_5_reconciler_never_revives_raw_active() -> None:
    """The Statebar bug: DB active, snapshot expired, reconciler sees active.

    In Mind Runtime the reconciler's validity pass runs first, so a stale
    'active' record is resolved to expired before any intent applies; the
    old record itself is never rewritten.
    """
    reconciler, clock = make_reconciler()
    created = reconciler.apply((), (make_intent(),)).effective_for(
        "user.health.headache", make_scope()
    )
    assert created is not None
    clock.advance(timedelta(hours=7))
    result = reconciler.apply((created,), ())
    resolved = result.effective_for("user.health.headache", make_scope())
    assert resolved is not None
    assert resolved.status == StateLifecycle.EXPIRED.value
    # The raw record still says active — but no consumer reads it raw.
    assert created.status == StateLifecycle.ACTIVE.value


def test_p0_6_relevance_is_independent_of_lifecycle() -> None:
    from dataclasses import replace

    from mind_runtime.state.relevance import evaluate_relevance

    cancelled = make_state(
        dimension="user.planning.calligraphy",
        value="cancelled",
        status=StateLifecycle.CANCELLED.value,
    )
    lapsed = replace(cancelled, relevant_until=NOW - timedelta(hours=1))
    assert cancelled.status == StateLifecycle.CANCELLED.value
    assert evaluate_relevance(cancelled, now=NOW).recently_cancelled is True
    assert evaluate_relevance(lapsed, now=NOW).recently_cancelled is False
    # Lifecycle untouched by the relevance window.
    assert lapsed.status == StateLifecycle.CANCELLED.value


def test_p0_7_illegal_lifecycle_transition_fails_closed() -> None:
    reconciler, _ = make_reconciler()
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


def test_p0_8_durable_writes_are_atomic(tmp_path: Path) -> None:
    """Each durable write is one transaction; duplicates never partial-write."""
    from mind_runtime.state.persistence import SqliteStateBackend

    backend = SqliteStateBackend(tmp_path / "regression.db")
    state = make_state(dimension="user.sleep.phase", value="awake", status="active", state_id="s-1")
    assert backend.save_state(state) is True
    assert backend.save_state(state) is False
    assert len(backend.load_states()) == 1


def test_p0_9_ambiguous_terminal_fails_closed() -> None:
    """An unresolvable lifecycle string can never enter the state plane."""
    opaque = make_state(dimension="user.health.headache", value="x", status="limbo")
    with pytest.raises(ValueError, match="opaque"):
        EffectiveStateResolver(definitions=StateDefinitionRegistry((HEADACHE,))).resolve(
            (opaque,), now=NOW
        )
