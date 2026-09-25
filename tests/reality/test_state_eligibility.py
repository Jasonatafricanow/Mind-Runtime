"""RED 5 tests for StateEligibility gate."""

from datetime import UTC, datetime, timedelta

from mind_runtime.contracts import (
    EffectiveWindow,
    EffectiveWindowKind,
    Observation,
    ObservationModality,
    Scope,
    ScopeDomain,
    SemanticDaypart,
    SemanticPrecision,
    SemanticRelation,
    SemanticTime,
    SyncFields,
)
from mind_runtime.reality.eligibility import (
    StateEligibility,
    evaluate_state_eligibility,
)

NOW = datetime(2026, 9, 9, 14, 0, tzinfo=UTC)
SCOPE = Scope(domain=ScopeDomain.USER, user_id="u1")


_DEFAULT_WINDOW = object()


def make_obs(
    key: str = "user.health.stomach_pain.observed",
    modality: ObservationModality = ObservationModality.ASSERTED,
    semantic_time: SemanticTime | None = None,
    effective_window: EffectiveWindow | None | object = _DEFAULT_WINDOW,
) -> Observation:
    if semantic_time is None:
        semantic_time = SemanticTime(
            relation=SemanticRelation.CURRENT, precision=SemanticPrecision.INSTANT
        )
    if effective_window is _DEFAULT_WINDOW:
        effective_window = EffectiveWindow(
            kind=EffectiveWindowKind.OPEN_INTERVAL, start_at=NOW, end_at=None
        )
    assert effective_window is None or isinstance(effective_window, EffectiveWindow)
    return Observation(
        id="obs-1",
        interaction_id="i1",
        scope=SCOPE,
        origin_runtime_id="r1",
        type="factual",
        key=key,
        value="active",
        confidence=1.0,
        observed_at=NOW,
        evidence_refs=("ev-1",),
        modality=modality,
        semantic_time=semantic_time,
        effective_window=effective_window,
        sync=SyncFields(SCOPE, "r1", "obs-1", 1, "idem-obs-1"),
    )


def test_eligible_current() -> None:
    obs = make_obs()
    decision = evaluate_state_eligibility(obs, admission_anchor=NOW, has_exact_target=False)
    assert decision is StateEligibility.ELIGIBLE_CURRENT


def test_eligible_terminal() -> None:
    obs = make_obs(
        key="user.health.stomach_pain.resolved",
        effective_window=EffectiveWindow(
            kind=EffectiveWindowKind.OPEN_INTERVAL, start_at=NOW, end_at=None
        ),
    )
    decision = evaluate_state_eligibility(obs, admission_anchor=NOW, has_exact_target=True)
    assert decision is StateEligibility.ELIGIBLE_TERMINAL


def test_terminal_without_target_is_observation_only() -> None:
    obs = make_obs(key="user.health.stomach_pain.resolved")
    decision = evaluate_state_eligibility(obs, admission_anchor=NOW, has_exact_target=False)
    assert decision is StateEligibility.OBSERVATION_ONLY


def test_planned_and_tentative_are_observation_only() -> None:
    for mod in [
        ObservationModality.PLANNED,
        ObservationModality.TENTATIVE,
        ObservationModality.ESTIMATED,
        ObservationModality.INFERRED,
    ]:
        obs = make_obs(modality=mod)
        decision = evaluate_state_eligibility(obs, admission_anchor=NOW, has_exact_target=False)
        assert decision is StateEligibility.OBSERVATION_ONLY


def test_past_assertion_without_terminal_is_observation_only() -> None:
    obs = make_obs(
        key="user.sleep.phase.observed",
        semantic_time=SemanticTime(
            relation=SemanticRelation.PAST,
            precision=SemanticPrecision.DAYPART,
            daypart=SemanticDaypart.NIGHT,
        ),
        effective_window=EffectiveWindow(
            kind=EffectiveWindowKind.INTERVAL,
            start_at=NOW - timedelta(hours=10),
            end_at=NOW - timedelta(hours=4),
        ),
    )
    decision = evaluate_state_eligibility(obs, admission_anchor=NOW, has_exact_target=False)
    assert decision is StateEligibility.OBSERVATION_ONLY


def test_future_window_is_observation_only() -> None:
    obs = make_obs(
        effective_window=EffectiveWindow(
            kind=EffectiveWindowKind.INTERVAL,
            start_at=NOW + timedelta(hours=2),
            end_at=NOW + timedelta(hours=6),
        )
    )
    decision = evaluate_state_eligibility(obs, admission_anchor=NOW, has_exact_target=False)
    assert decision is StateEligibility.OBSERVATION_ONLY


def test_point_window_is_not_current_state_proof() -> None:
    obs = make_obs(
        effective_window=EffectiveWindow(
            kind=EffectiveWindowKind.POINT,
            start_at=NOW,
            end_at=None,
        )
    )
    decision = evaluate_state_eligibility(obs, admission_anchor=NOW, has_exact_target=False)
    assert decision is StateEligibility.OBSERVATION_ONLY


def test_null_window_is_observation_only() -> None:
    obs = make_obs(effective_window=None)
    decision = evaluate_state_eligibility(obs, admission_anchor=NOW, has_exact_target=False)
    assert decision is StateEligibility.OBSERVATION_ONLY
