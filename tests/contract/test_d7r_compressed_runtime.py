"""D7R compressed Context -> EmotionalTransition -> Intent contracts."""

from dataclasses import FrozenInstanceError, fields, replace
from datetime import UTC, datetime, timedelta

import pytest

import mind_runtime.contracts as contracts
from mind_runtime.contracts import (
    AppraisalPath,
    AppraisalRouteDecision,
    AssessmentContribution,
    AssessmentTrace,
    DecisionContext,
    EmotionalTransitionInput,
    EmotionalTransitionResult,
    HistoricalContextBundle,
    Intent,
    IntentStatus,
    ProjectedMindState,
    ReconsiderationPolicy,
    RuntimeState,
    Scope,
    ScopeDomain,
    SemanticEventCandidate,
    Situation,
    SyncFields,
    TurnProjection,
)

NOW = datetime(2026, 8, 22, 12, 0, tzinfo=UTC)


def make_scope() -> Scope:
    return Scope(domain=ScopeDomain.USER, user_id="user-1")


def make_agent_scope() -> Scope:
    return Scope(domain=ScopeDomain.AGENT, agent_id="kayla", persona_id="kayla")


def make_sync(scope: Scope, object_id: str) -> SyncFields:
    return SyncFields(scope, "runtime-1", object_id, 1, f"idem-{object_id}")


def make_context(scope: Scope) -> Situation:
    return Situation(
        situation_id="context-1",
        scope=scope,
        origin_runtime_id="runtime-1",
        derived_facts=(("conversation.active", "true"),),
        effective_state_ref="state-user-1",
        observed_at=NOW,
        historical_context=None,
        persona_id="kayla",
        relationship_ids=(),
        evidence_refs=("evidence-1",),
    )


def make_projected(scope: Scope) -> ProjectedMindState:
    state = RuntimeState(
        state_id="agent.affect.longing:projected",
        scope=scope,
        origin_runtime_id="runtime-1",
        dimension="agent.affect.longing",
        value=0.4,
        status="active",
        valid_from=NOW,
        valid_until=None,
        relevant_until=None,
        last_observed_at=NOW,
        evidence_refs=(),
        transition_refs=(),
        updated_at=NOW,
        version=1,
        sync=make_sync(scope, "agent.affect.longing:projected"),
    )
    return ProjectedMindState(
        projection_id="projection-1",
        scope=scope,
        origin_runtime_id="runtime-1",
        projected_states=(state,),
        sync=make_sync(scope, "projection-1"),
    )


def make_candidate(scope: Scope) -> SemanticEventCandidate:
    return SemanticEventCandidate(
        candidate_id="semantic-1",
        scope=scope,
        origin_runtime_id="runtime-1",
        kind="plan_cancelled",
        attributes=(("recurrence", "2"),),
        confidence=0.8,
        evidence_refs=("evidence-1",),
    )


def make_intent(scope: Scope) -> Intent:
    return Intent(
        intent_id="intent-1",
        scope=scope,
        origin_runtime_id="runtime-1",
        kind="respond",
        strength=0.6,
        earliest_at=NOW,
        due_at=None,
        expires_at=NOW + timedelta(hours=1),
        reconsideration_policy=ReconsiderationPolicy.ON_CONTEXT_CHANGE,
        cause_refs=("semantic-1",),
        state_refs=("projection-1",),
        status=IntentStatus.CANDIDATE,
        sync=make_sync(scope, "intent-1"),
    )


def make_trace(scope: Scope) -> AssessmentTrace:
    return AssessmentTrace(
        trace_id="assessment-1",
        scope=scope,
        origin_runtime_id="runtime-1",
        context_ref="context-1",
        persona_id="kayla",
        persona_version=1,
        state_before=(("agent.affect.longing", 0.3),),
        contributions=(
            AssessmentContribution(
                dimension="agent.affect.longing",
                source_kind="event",
                source_ref="semantic-1",
                amount=0.1,
                confidence=0.8,
                applied=True,
                reason_code=None,
            ),
        ),
        state_after=(("agent.affect.longing", 0.4),),
        evidence_refs=("evidence-1",),
        history_refs=(),
        abstention_reasons=(),
        route_decision=AppraisalRouteDecision(
            route_id="route-1",
            scope=scope,
            path=AppraisalPath.TYPED_MAPPING,
            ambiguity_score=0.0,
            confidence=0.8,
            reason_codes=("candidate_supplied",),
        ),
        created_at=NOW,
    )


def test_semantic_candidate_cannot_carry_affect_intent_or_policy() -> None:
    candidate = make_candidate(make_scope())
    assert candidate.attributes == (("recurrence", "2"),)
    assert not hasattr(candidate, "affective_impulses")
    assert not hasattr(candidate, "intent")
    assert not hasattr(candidate, "allowed")


@pytest.mark.parametrize("confidence", [-0.1, 1.1, True])
def test_semantic_candidate_rejects_invalid_confidence(confidence: float) -> None:
    scope = make_scope()
    with pytest.raises(ValueError, match="confidence"):
        SemanticEventCandidate(
            candidate_id="semantic-bad",
            scope=scope,
            origin_runtime_id="runtime-1",
            kind="plan_cancelled",
            attributes=(),
            confidence=confidence,
            evidence_refs=(),
        )


def test_intent_is_versioned_candidate_not_permission() -> None:
    intent = make_intent(make_scope())
    assert intent.status is IntentStatus.CANDIDATE
    assert intent.sync_fields() is intent.sync
    assert not hasattr(intent, "allowed")
    assert not hasattr(intent, "permission")
    with pytest.raises(FrozenInstanceError):
        intent.status = IntentStatus.ALLOWED  # type: ignore[misc]


def test_intent_rejects_invalid_strength_and_schedule_order() -> None:
    scope = make_scope()
    with pytest.raises(ValueError, match="strength"):
        replace(make_intent(scope), strength=1.1)
    with pytest.raises(ValueError, match="schedule"):
        replace(
            make_intent(scope),
            earliest_at=NOW + timedelta(hours=2),
            expires_at=NOW + timedelta(hours=1),
        )


def test_assessment_trace_records_persona_version_and_contributions() -> None:
    trace = make_trace(make_scope())
    assert trace.persona_id == "kayla"
    assert trace.persona_version == 1
    assert trace.contributions[0].amount == 0.1
    with pytest.raises(FrozenInstanceError):
        trace.persona_version = 2  # type: ignore[misc]


def test_transition_input_and_result_have_no_policy_authority() -> None:
    scope = make_scope()
    transition_input = EmotionalTransitionInput(
        interaction_id="interaction-1",
        scope=scope,
        origin_runtime_id="runtime-1",
        context=make_context(scope),
        current_affect=(make_projected(make_agent_scope()).projected_states[0],),
        elapsed=timedelta(0),
        persona_id="kayla",
        persona_version=1,
        persona=(),
        observations=(),
        semantic_candidates=(make_candidate(scope),),
        history_context=None,
        clock=NOW,
        projection_scope=make_agent_scope(),
    )
    result = EmotionalTransitionResult(
        projected=make_projected(make_agent_scope()),
        accepted_events=(make_candidate(scope),),
        assessment_trace=make_trace(scope),
    )
    assert transition_input.context.situation_id == "context-1"
    assert result.accepted_events[0].kind == "plan_cancelled"
    assert not hasattr(result, "policy_result")


def test_frozen_resolved_appraisal_and_motivation_are_not_canonical_exports() -> None:
    assert not hasattr(contracts, "ResolvedAppraisal")
    assert not hasattr(contracts, "Motivation")


def test_decision_context_references_one_trace_intent_and_policy_result() -> None:
    field_names = {field.name for field in fields(DecisionContext)}
    assert {"assessment_trace_ref", "intent_ref", "policy_result_ref"} <= field_names
    assert "resolved_appraisal_ref" not in field_names
    assert "motivation_refs" not in field_names


def test_turn_projection_references_trace_and_cognitive_intents_once() -> None:
    field_names = {field.name for field in fields(TurnProjection)}
    assert {"assessment_trace_ref", "intent_refs", "transition_intents"} <= field_names
    assert "resolved_appraisal" not in field_names
    assert "motivations" not in field_names


def test_dimension_value_sets_reject_duplicates_and_bool_values() -> None:
    scope = make_scope()
    trace = make_trace(scope)
    with pytest.raises(ValueError, match="unique"):
        replace(
            trace,
            state_before=(
                ("agent.affect.longing", 0.2),
                ("agent.affect.longing", 0.3),
            ),
        )
    with pytest.raises(ValueError, match="numeric"):
        replace(trace, state_after=(("agent.affect.longing", True),))


def test_assessment_contribution_rejects_invalid_typed_fields() -> None:
    contribution = make_trace(make_scope()).contributions[0]
    with pytest.raises(ValueError, match="amount"):
        replace(contribution, amount=True)
    with pytest.raises(ValueError, match="confidence"):
        replace(contribution, confidence=1.1)
    with pytest.raises(ValueError, match="applied"):
        replace(contribution, applied="yes")  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="reason_code"):
        replace(contribution, reason_code=" ")


def test_assessment_trace_rejects_invalid_version_and_refs() -> None:
    trace = make_trace(make_scope())
    with pytest.raises(ValueError, match="persona_version"):
        replace(trace, persona_version=0)
    with pytest.raises(ValueError, match="history_refs"):
        replace(trace, history_refs=("",))
    with pytest.raises(ValueError, match="abstention_reasons"):
        replace(trace, abstention_reasons=("",))


def test_transition_input_rejects_conflicting_or_invalid_inputs() -> None:
    scope = make_scope()
    transition_input = EmotionalTransitionInput(
        interaction_id="interaction-1",
        scope=scope,
        origin_runtime_id="runtime-1",
        context=make_context(scope),
        current_affect=(),
        elapsed=timedelta(0),
        persona_id="kayla",
        persona_version=1,
        persona=(),
        observations=(),
        semantic_candidates=(),
        history_context=None,
        clock=NOW,
        projection_scope=None,
    )
    other_scope = Scope(domain=ScopeDomain.USER, user_id="user-2")
    with pytest.raises(ValueError, match="context.scope"):
        replace(transition_input, scope=other_scope)
    with pytest.raises(ValueError, match="persona_version"):
        replace(transition_input, persona_version=0)
    with pytest.raises(ValueError, match="elapsed"):
        replace(transition_input, elapsed=-timedelta(seconds=1))
    with pytest.raises(ValueError, match="semantic candidate scope"):
        replace(
            transition_input,
            semantic_candidates=(replace(make_candidate(scope), scope=other_scope),),
        )
    with pytest.raises(ValueError, match="history context scope"):
        replace(
            transition_input,
            history_context=HistoricalContextBundle(
                bundle_id="history-other",
                scope=other_scope,
                origin_runtime_id="runtime-1",
                episodes=(),
                stable_facts=(),
                relationship_events=(),
                pattern_summaries=(),
                source_refs=(),
                provider_trace="fixture",
            ),
        )


def test_intent_rejects_unknown_enum_values() -> None:
    intent = make_intent(make_scope())
    with pytest.raises(ValueError, match="reconsideration_policy"):
        replace(intent, reconsideration_policy="sometimes")  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="status"):
        replace(intent, status="maybe")  # type: ignore[arg-type]
