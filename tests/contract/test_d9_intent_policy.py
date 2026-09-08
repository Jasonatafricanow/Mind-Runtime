"""D9 Intent, scheduler, and ActionPolicy contracts fail closed."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import cast

import pytest

from mind_runtime.contracts import (
    ActionDecision,
    ActionPermission,
    ActionPolicyInput,
    ActionPolicyResult,
    AppraisalPath,
    AppraisalRouteDecision,
    AssessmentTrace,
    EmotionalTransitionResult,
    Intent,
    IntentEngineInput,
    IntentEngineResult,
    IntentScoreContribution,
    IntentScoreTrace,
    IntentStatus,
    IntentTransition,
    IntentWake,
    PolicyResources,
    ProjectedMindState,
    ReconsiderationPolicy,
    RuntimeState,
    Scope,
    ScopeDomain,
    SemanticEventCandidate,
    Situation,
    SyncFields,
)

NOW = datetime(2026, 8, 22, 12, 0, tzinfo=UTC)
USER_SCOPE = Scope(domain=ScopeDomain.USER, user_id="user-1")
OTHER_SCOPE = Scope(domain=ScopeDomain.USER, user_id="user-2")
AGENT_SCOPE = Scope(domain=ScopeDomain.AGENT, agent_id="kayla", persona_id="kayla")


def sync(scope: Scope, object_id: str, version: int = 1) -> SyncFields:
    return SyncFields(scope, "runtime-1", object_id, version, f"idem-{object_id}-v{version}")


def context(scope: Scope = USER_SCOPE) -> Situation:
    return Situation(
        situation_id="situation-1",
        scope=scope,
        origin_runtime_id="runtime-1",
        derived_facts=(("conversation.active", "false"),),
        effective_state_ref="effective-1",
        observed_at=NOW,
        historical_context=None,
        persona_id="kayla",
        relationship_ids=(),
        evidence_refs=("evidence-1",),
    )


def projected() -> ProjectedMindState:
    state_id = "agent.affect.longing:2"
    state = RuntimeState(
        state_id=state_id,
        scope=AGENT_SCOPE,
        origin_runtime_id="runtime-1",
        dimension="agent.affect.longing",
        value=0.8,
        status="active",
        valid_from=NOW,
        valid_until=None,
        relevant_until=None,
        last_observed_at=NOW,
        evidence_refs=("evidence-1",),
        transition_refs=(),
        updated_at=NOW,
        version=2,
        sync=sync(AGENT_SCOPE, state_id, 2),
    )
    return ProjectedMindState(
        projection_id="projection-1",
        scope=AGENT_SCOPE,
        origin_runtime_id="runtime-1",
        projected_states=(state,),
        sync=sync(AGENT_SCOPE, "projection-1"),
    )


def candidate(
    candidate_id: str = "candidate-1", scope: Scope = USER_SCOPE
) -> SemanticEventCandidate:
    return SemanticEventCandidate(
        candidate_id=candidate_id,
        scope=scope,
        origin_runtime_id="runtime-1",
        kind="follow_up_due",
        attributes=(("due_at", "2026-08-23T10:00:00+00:00"),),
        confidence=0.9,
        evidence_refs=("evidence-1",),
    )


def assessment(scope: Scope = USER_SCOPE) -> AssessmentTrace:
    return AssessmentTrace(
        trace_id="assessment-1",
        scope=scope,
        origin_runtime_id="runtime-1",
        context_ref="situation-1",
        persona_id="kayla",
        persona_version=1,
        state_before=(("agent.affect.longing", 0.7),),
        contributions=(),
        state_after=(("agent.affect.longing", 0.8),),
        evidence_refs=("evidence-1",),
        history_refs=(),
        abstention_reasons=(),
        route_decision=AppraisalRouteDecision(
            route_id="route-1",
            scope=scope,
            path=AppraisalPath.TYPED_MAPPING,
            ambiguity_score=0.0,
            confidence=0.9,
            reason_codes=("trusted_typed_event",),
        ),
        created_at=NOW,
    )


def intent(status: IntentStatus = IntentStatus.CANDIDATE, version: int = 1) -> Intent:
    return Intent(
        intent_id="intent-1",
        scope=USER_SCOPE,
        origin_runtime_id="runtime-1",
        kind="contact_user",
        strength=0.7,
        earliest_at=NOW,
        due_at=None,
        expires_at=NOW + timedelta(hours=1),
        reconsideration_policy=ReconsiderationPolicy.ON_CONTEXT_CHANGE,
        cause_refs=("situation-1",),
        state_refs=("projection-1",),
        status=status,
        sync=sync(USER_SCOPE, "intent-1", version),
    )


def score_trace(intent_id: str = "intent-1") -> IntentScoreTrace:
    return IntentScoreTrace(
        trace_id="intent-score-1",
        scope=USER_SCOPE,
        rule_id="contact-rule",
        intent_id=intent_id,
        contributions=(
            IntentScoreContribution(
                source_kind="dimension",
                source_ref="agent.affect.longing",
                amount=0.6,
            ),
        ),
        unclamped_score=0.7,
        final_strength=0.7,
        admitted=True,
        reason_codes=("threshold_met",),
        created_at=NOW,
    )


def permission(allowed: bool) -> ActionPermission:
    return ActionPermission(
        permission_id="permission-1",
        scope=USER_SCOPE,
        origin_runtime_id="runtime-1",
        action_type="text_message",
        allowed=allowed,
        reasons=("allowed" if allowed else "cooldown_active",),
        constraints=(),
    )


def test_emotional_transition_exposes_accepted_events_not_intents() -> None:
    event = candidate()
    result = EmotionalTransitionResult(
        projected=projected(),
        accepted_events=(event,),
        assessment_trace=assessment(),
    )

    assert result.accepted_events == (event,)
    assert not hasattr(result, "intents")
    with pytest.raises(ValueError, match="scope"):
        replace(result, accepted_events=(candidate(scope=OTHER_SCOPE),))
    with pytest.raises(ValueError, match="unique"):
        replace(result, accepted_events=(event, event))


def test_intent_engine_contracts_validate_scope_scores_and_linkage() -> None:
    engine_input = IntentEngineInput(
        interaction_id="interaction-1",
        scope=USER_SCOPE,
        origin_runtime_id="runtime-1",
        context=context(),
        projected=projected(),
        accepted_events=(candidate(),),
        clock=NOW,
    )
    result = IntentEngineResult(candidates=(intent(),), traces=(score_trace(),))
    assert engine_input.projected.scope == AGENT_SCOPE
    assert result.candidates[0].strength == 0.7

    with pytest.raises(ValueError, match="context scope"):
        replace(engine_input, context=context(OTHER_SCOPE))
    with pytest.raises(ValueError, match="event scope"):
        replace(engine_input, accepted_events=(candidate(scope=OTHER_SCOPE),))
    with pytest.raises(ValueError, match="unique"):
        replace(engine_input, accepted_events=(candidate(), candidate()))
    with pytest.raises(ValueError, match="amount"):
        replace(score_trace().contributions[0], amount=True)
    with pytest.raises(ValueError, match="unclamped_score"):
        replace(score_trace(), unclamped_score=True)
    with pytest.raises(ValueError, match="final_strength"):
        replace(score_trace(), final_strength=1.1)
    with pytest.raises(ValueError, match="admitted"):
        replace(score_trace(), admitted=cast(bool, "yes"))
    with pytest.raises(ValueError, match="trace"):
        replace(result, traces=(score_trace("other-intent"),))
    with pytest.raises(ValueError, match="admitted"):
        replace(result, traces=(replace(score_trace(), admitted=False),))
    with pytest.raises(ValueError, match="strength"):
        replace(result, traces=(replace(score_trace(), final_strength=0.8),))
    with pytest.raises(ValueError, match="scope"):
        replace(result, traces=(replace(score_trace(), scope=OTHER_SCOPE),))
    with pytest.raises(ValueError, match="unique"):
        replace(result, candidates=(intent(), intent()))


def test_intent_transition_and_wake_validate_version_status_scope_and_time() -> None:
    transition = IntentTransition(
        transition_id="intent-transition-2",
        scope=USER_SCOPE,
        origin_runtime_id="runtime-1",
        intent_id="intent-1",
        from_status=IntentStatus.CANDIDATE,
        to_status=IntentStatus.DEFERRED,
        reason_codes=("cooldown_active",),
        occurred_at=NOW,
        version=2,
        sync=sync(USER_SCOPE, "intent-transition-2", 2),
    )
    wake = IntentWake(
        wake_id="wake-intent-1-v2",
        scope=USER_SCOPE,
        intent_id="intent-1",
        reason="due_reconsideration",
        woken_at=NOW,
        intent_version=2,
    )
    assert transition.to_status is IntentStatus.DEFERRED
    assert wake.intent_version == 2

    with pytest.raises(ValueError, match="must differ"):
        replace(transition, to_status=IntentStatus.CANDIDATE)
    with pytest.raises(ValueError, match="version"):
        replace(transition, version=1, sync=sync(USER_SCOPE, "intent-transition-2", 1))
    with pytest.raises(ValueError, match="sync.version"):
        replace(transition, sync=sync(USER_SCOPE, "intent-transition-2", 3))
    with pytest.raises(ValueError, match="scope"):
        replace(transition, sync=sync(OTHER_SCOPE, "intent-transition-2", 2))
    with pytest.raises(ValueError, match="IntentStatus"):
        replace(transition, to_status=cast(IntentStatus, "deferred"))
    with pytest.raises(ValueError, match="aware UTC"):
        replace(wake, woken_at=NOW.replace(tzinfo=None))
    with pytest.raises(ValueError, match="intent_version"):
        replace(wake, intent_version=0)


def test_policy_input_and_result_cannot_contradict_permission() -> None:
    policy_input = ActionPolicyInput(
        intent=intent(),
        context=context(),
        scope=USER_SCOPE,
        clock=NOW,
        resources=PolicyResources(available_actions=("text_message",)),
    )
    assert policy_input.resources.available_actions == ("text_message",)

    with pytest.raises(ValueError, match="intent scope"):
        replace(policy_input, scope=OTHER_SCOPE)
    with pytest.raises(ValueError, match="context scope"):
        replace(policy_input, context=context(OTHER_SCOPE))
    with pytest.raises(ValueError, match="unique"):
        replace(policy_input, resources=PolicyResources(("text_message", "text_message")))

    allowed = ActionPolicyResult(
        policy_id="policy-1",
        scope=USER_SCOPE,
        origin_runtime_id="runtime-1",
        intent_id="intent-1",
        decision=ActionDecision.ALLOW,
        permission=permission(True),
        reason_codes=("allowed",),
    )
    with pytest.raises(ValueError, match="ALLOW"):
        replace(allowed, permission=permission(False))
    with pytest.raises(ValueError, match="DENY"):
        replace(allowed, decision=ActionDecision.DENY, permission=permission(True))
    with pytest.raises(ValueError, match="DENY"):
        replace(allowed, decision=ActionDecision.DENY, permission=None)
    with pytest.raises(ValueError, match="permission scope"):
        replace(allowed, permission=replace(permission(True), scope=OTHER_SCOPE))
    with pytest.raises(ValueError, match="permission origin"):
        replace(
            allowed,
            permission=replace(permission(True), origin_runtime_id="other-runtime"),
        )
