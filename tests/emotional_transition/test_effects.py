"""Accepted semantic events become bounded Dynamics impulses exactly once."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from mind_runtime.contracts import (
    AffectiveDimensionProfile,
    EmotionalTransitionInput,
    HistoricalContextBundle,
    PatternMatchSummary,
    RuntimeState,
    Scope,
    ScopeDomain,
    SemanticEventCandidate,
    Situation,
    SyncFields,
)
from mind_runtime.dynamics.engine import DynamicsEngine
from mind_runtime.dynamics.persona import PersonaProfile
from mind_runtime.dynamics.ports import EngineEmotionalTransitionPort
from mind_runtime.emotional_transition.effects import EffectMapper, EventEffectRule
from mind_runtime.emotional_transition.semantic import SemanticRouter

NOW = datetime(2026, 8, 22, 12, 0, tzinfo=UTC)
USER_SCOPE = Scope(domain=ScopeDomain.USER, user_id="user-1")
AGENT_SCOPE = Scope(domain=ScopeDomain.AGENT, agent_id="test", persona_id="test")


def sync(scope: Scope, object_id: str, *, version: int = 1) -> SyncFields:
    return SyncFields(scope, "runtime-1", object_id, version, f"idem-{object_id}")


def profile() -> AffectiveDimensionProfile:
    return AffectiveDimensionProfile(
        dimension="agent.affect.anxiety",
        baseline=0.25,
        initial_value=0.25,
        sensitivity=0.5,
        recovery_rate=0.2,
        ceiling=1.0,
        floor=0.0,
        growth_profile=(),
        coupling_profile=(),
    )


def current(value: float = 0.25) -> RuntimeState:
    return RuntimeState(
        state_id="agent.affect.anxiety:1",
        scope=AGENT_SCOPE,
        origin_runtime_id="runtime-1",
        dimension="agent.affect.anxiety",
        value=value,
        status="active",
        valid_from=NOW - timedelta(minutes=5),
        valid_until=None,
        relevant_until=None,
        last_observed_at=NOW - timedelta(minutes=5),
        evidence_refs=(),
        transition_refs=(),
        updated_at=NOW - timedelta(minutes=5),
        version=1,
        sync=sync(AGENT_SCOPE, "agent.affect.anxiety:1"),
    )


def context() -> Situation:
    return Situation(
        situation_id="context-1",
        scope=USER_SCOPE,
        origin_runtime_id="runtime-1",
        derived_facts=(),
        effective_state_ref="effective-1",
        observed_at=NOW,
        historical_context=None,
        persona_id="test",
        relationship_ids=(),
        evidence_refs=("evidence-current",),
    )


def candidate(*, confidence: float = 0.8, kind: str = "plan_cancelled") -> SemanticEventCandidate:
    return SemanticEventCandidate(
        candidate_id="candidate-1",
        scope=USER_SCOPE,
        origin_runtime_id="runtime-1",
        kind=kind,
        attributes=(),
        confidence=confidence,
        evidence_refs=("evidence-current",),
    )


def pattern(
    summary_id: str = "summary-1",
    *,
    confidence: float = 0.7,
) -> PatternMatchSummary:
    return PatternMatchSummary(
        summary_id=summary_id,
        scope=USER_SCOPE,
        origin_runtime_id="runtime-1",
        match_count=3,
        first_seen_at=NOW - timedelta(days=10),
        last_seen_at=NOW - timedelta(days=1),
        matched_refs=("old-1", "old-2"),
        confidence=confidence,
    )


def history(*summaries: PatternMatchSummary) -> HistoricalContextBundle:
    return HistoricalContextBundle(
        bundle_id="history-1",
        scope=USER_SCOPE,
        origin_runtime_id="runtime-1",
        episodes=(),
        stable_facts=(),
        relationship_events=(),
        pattern_summaries=summaries,
        source_refs=("old-1", "old-2"),
        provider_trace="fixture",
    )


def rule() -> EventEffectRule:
    return EventEffectRule(
        event_kind="plan_cancelled",
        dimension="agent.affect.anxiety",
        base_amount=0.2,
        history_amount_per_match=0.03,
        history_amount_cap=0.05,
        minimum_history_confidence=0.5,
    )


def transition_input(
    *,
    candidates: tuple[SemanticEventCandidate, ...] = (candidate(),),
    history_context: HistoricalContextBundle | None = None,
    elapsed: timedelta = timedelta(0),
    current_state: tuple[RuntimeState, ...] = (current(),),
) -> EmotionalTransitionInput:
    dimension = profile()
    return EmotionalTransitionInput(
        interaction_id="interaction-1",
        scope=USER_SCOPE,
        origin_runtime_id="runtime-1",
        context=context(),
        current_affect=current_state,
        elapsed=elapsed,
        persona_id="test",
        persona_version=1,
        persona=(dimension,),
        observations=(),
        semantic_candidates=candidates,
        history_context=history_context,
        clock=NOW,
        projection_scope=AGENT_SCOPE,
    )


def port(*rules: EventEffectRule) -> EngineEmotionalTransitionPort:
    persona = PersonaProfile(persona_id="test", dimensions=(profile(),))
    return EngineEmotionalTransitionPort(
        engine=DynamicsEngine(persona=persona),
        runtime_id="runtime-1",
        effect_rules=rules,
    )


def projected_value(result: object) -> float:
    from mind_runtime.contracts import EmotionalTransitionResult

    assert isinstance(result, EmotionalTransitionResult)
    value = result.projected.projected_states[0].value
    assert isinstance(value, float)
    return value


def test_event_confidence_and_persona_sensitivity_apply_once() -> None:
    result = port(rule()).transition(transition_input())

    assert projected_value(result) == pytest.approx(0.33)
    event = next(
        contribution
        for contribution in result.assessment_trace.contributions
        if contribution.source_kind == "event"
    )
    assert event.amount == pytest.approx(0.08)
    assert event.confidence == 0.8
    assert event.applied is True


def test_repeated_history_adds_one_separate_capped_contribution() -> None:
    result = port(rule()).transition(transition_input(history_context=history(pattern())))

    assert projected_value(result) == pytest.approx(0.355)
    history_contributions = tuple(
        contribution
        for contribution in result.assessment_trace.contributions
        if contribution.source_kind == "history"
    )
    assert len(history_contributions) == 1
    assert history_contributions[0].amount == pytest.approx(0.025)
    assert history_contributions[0].source_ref == "summary-1"


def test_duplicate_history_summary_does_not_multiply_influence() -> None:
    repeated = pattern()
    result = port(rule()).transition(transition_input(history_context=history(repeated, repeated)))

    assert projected_value(result) == pytest.approx(0.355)
    assert (
        sum(
            contribution.source_kind == "history"
            for contribution in result.assessment_trace.contributions
        )
        == 1
    )


def test_low_confidence_history_is_audited_but_not_applied() -> None:
    result = port(rule()).transition(
        transition_input(history_context=history(pattern(confidence=0.49)))
    )

    assert projected_value(result) == pytest.approx(0.33)
    rejected = next(
        contribution
        for contribution in result.assessment_trace.contributions
        if contribution.source_kind == "history"
    )
    assert rejected.applied is False
    assert rejected.reason_code == "low_history_confidence"


def test_unknown_event_is_audited_without_affect_change() -> None:
    result = port(rule()).transition(
        transition_input(candidates=(candidate(kind="unknown_event"),))
    )

    assert projected_value(result) == pytest.approx(0.25)
    rejected = result.assessment_trace.contributions[0]
    assert rejected.applied is False
    assert rejected.reason_code == "unknown_event_kind"


def test_low_semantic_confidence_abstains_before_dynamics() -> None:
    result = port(rule()).transition(transition_input(candidates=(candidate(confidence=0.74),)))

    assert projected_value(result) == pytest.approx(0.25)
    assert "low_confidence" in result.assessment_trace.abstention_reasons
    rejected = result.assessment_trace.contributions[0]
    assert rejected.applied is False
    assert rejected.reason_code == "low_confidence"


def test_no_candidate_keeps_elapsed_recovery_operational() -> None:
    result = port(rule()).transition(
        transition_input(
            candidates=(),
            elapsed=timedelta(seconds=5),
            current_state=(current(0.5),),
        )
    )

    assert 0.25 < projected_value(result) < 0.5
    assert result.assessment_trace.route_decision.reason_codes == ("no_semantic_event",)


def test_effect_rule_rejects_invalid_numeric_configuration() -> None:
    with pytest.raises(ValueError, match="base_amount"):
        replace(rule(), base_amount=True)
    with pytest.raises(ValueError, match="history_amount_cap"):
        replace(rule(), history_amount_cap=-0.1)
    with pytest.raises(ValueError, match="history_amount_per_match"):
        replace(rule(), history_amount_per_match=-0.1)
    with pytest.raises(ValueError, match="minimum_history_confidence"):
        replace(rule(), minimum_history_confidence=True)


def test_effect_mapper_rejects_duplicate_rules_and_wrong_history_scope() -> None:
    with pytest.raises(ValueError, match="rule kinds must be unique"):
        EffectMapper(rules=(rule(), rule()))

    routing = SemanticRouter().route(
        observations=(),
        context=context(),
        supplied_candidates=(candidate(),),
    )
    wrong_scope = replace(
        history(),
        scope=Scope(domain=ScopeDomain.USER, user_id="user-2"),
    )
    with pytest.raises(ValueError, match="history scope"):
        EffectMapper(rules=(rule(),)).map(routing=routing, history=wrong_scope)


def test_zero_history_amount_is_not_emitted() -> None:
    no_history_effect = replace(rule(), history_amount_per_match=0.0, history_amount_cap=0.0)
    result = port(no_history_effect).transition(
        transition_input(history_context=history(pattern()))
    )
    assert all(
        contribution.source_kind != "history"
        for contribution in result.assessment_trace.contributions
    )
