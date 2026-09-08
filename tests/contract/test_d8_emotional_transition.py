"""D8 emotional transition contracts fail closed at authority boundaries."""

from dataclasses import fields, replace
from datetime import UTC, datetime, timedelta

import pytest

import mind_runtime.contracts as contracts
from mind_runtime.contracts import (
    AppraisalPath,
    AppraisalRouteDecision,
    AssessmentTrace,
    EmotionalTransitionInput,
    HistoricalContextBundle,
    Observation,
    ProjectedMindState,
    RuntimeState,
    Scope,
    ScopeDomain,
    SemanticEventCandidate,
    Situation,
    SyncFields,
)

NOW = datetime(2026, 8, 22, 12, 0, tzinfo=UTC)


def user_scope() -> Scope:
    return Scope(domain=ScopeDomain.USER, user_id="user-1")


def agent_scope() -> Scope:
    return Scope(domain=ScopeDomain.AGENT, agent_id="kayla", persona_id="kayla")


def sync(scope: Scope, object_id: str, *, version: int = 1) -> SyncFields:
    return SyncFields(scope, "runtime-1", object_id, version, f"idem-{object_id}")


def state(
    dimension: str,
    value: float,
    *,
    scope: Scope | None = None,
    state_id: str | None = None,
) -> RuntimeState:
    owned_scope = scope or agent_scope()
    object_id = state_id or f"{dimension}:projected"
    return RuntimeState(
        state_id=object_id,
        scope=owned_scope,
        origin_runtime_id="runtime-1",
        dimension=dimension,
        value=value,
        status="active",
        valid_from=NOW,
        valid_until=None,
        relevant_until=None,
        last_observed_at=NOW,
        evidence_refs=("evidence-1",),
        transition_refs=(),
        updated_at=NOW,
        version=2,
        sync=sync(owned_scope, object_id, version=2),
    )


def projection(*states: RuntimeState) -> ProjectedMindState:
    owned_scope = agent_scope()
    return ProjectedMindState(
        projection_id="projection-1",
        scope=owned_scope,
        origin_runtime_id="runtime-1",
        projected_states=states,
        sync=sync(owned_scope, "projection-1"),
        committed=False,
    )


def route(*, scope: Scope | None = None) -> AppraisalRouteDecision:
    owned_scope = scope or user_scope()
    return AppraisalRouteDecision(
        route_id="route-1",
        scope=owned_scope,
        path=AppraisalPath.TYPED_MAPPING,
        ambiguity_score=0.0,
        confidence=1.0,
        reason_codes=("trusted_typed_event",),
    )


def candidate(
    *, scope: Scope | None = None, candidate_id: str = "candidate-1"
) -> SemanticEventCandidate:
    return SemanticEventCandidate(
        candidate_id=candidate_id,
        scope=scope or user_scope(),
        origin_runtime_id="runtime-1",
        kind="plan_cancelled",
        attributes=(("recurrence", "2"),),
        confidence=0.8,
        evidence_refs=("evidence-1",),
    )


def context() -> Situation:
    scope = user_scope()
    return Situation(
        situation_id="context-1",
        scope=scope,
        origin_runtime_id="runtime-1",
        derived_facts=(("conversation.active", "true"),),
        effective_state_ref="effective-1",
        observed_at=NOW,
        historical_context=None,
        persona_id="kayla",
        relationship_ids=(),
        evidence_refs=("evidence-1",),
    )


def observation(*, scope: Scope | None = None) -> Observation:
    owned_scope = scope or user_scope()
    return Observation(
        id="observation-1",
        interaction_id="interaction-1",
        scope=owned_scope,
        type="factual",
        key="typed_event.observed",
        value={"kind": "plan_cancelled", "attributes": {"recurrence": "2"}},
        confidence=1.0,
        observed_at=NOW,
        evidence_refs=("evidence-1",),
        origin_runtime_id="runtime-1",
        sync=sync(owned_scope, "observation-1"),
    )


def history(*, scope: Scope | None = None) -> HistoricalContextBundle:
    owned_scope = scope or user_scope()
    return HistoricalContextBundle(
        bundle_id="history-1",
        scope=owned_scope,
        origin_runtime_id="runtime-1",
        episodes=(),
        stable_facts=(),
        relationship_events=(),
        pattern_summaries=(),
        source_refs=("evidence-old",),
        provider_trace="fixture",
    )


def test_projected_mind_state_owns_an_atomic_ordered_vector() -> None:
    projected = projection(
        state("agent.affect.longing", 0.31),
        state("agent.affect.anxiety", 0.42),
    )

    assert tuple(item.dimension for item in projected.projected_states) == (
        "agent.affect.longing",
        "agent.affect.anxiety",
    )
    assert not hasattr(projected, "projected_state")


def test_projected_vector_rejects_empty_duplicate_and_mixed_scope_states() -> None:
    with pytest.raises(ValueError, match="non-empty"):
        projection()
    longing = state("agent.affect.longing", 0.31)
    with pytest.raises(ValueError, match="unique"):
        projection(longing, state("agent.affect.longing", 0.4, state_id="longing-other"))
    with pytest.raises(ValueError, match="scope"):
        projection(longing, state("user.affect.anxiety", 0.42, scope=user_scope()))


def test_projected_vector_rejects_non_boolean_committed_flag() -> None:
    with pytest.raises(ValueError, match="committed"):
        replace(
            projection(state("agent.affect.longing", 0.31)),
            committed="no",  # type: ignore[arg-type]
        )


def test_semantic_routing_result_validates_scope_ids_and_call_count() -> None:
    routing_type = contracts.SemanticRoutingResult
    routing = routing_type(
        route=route(),
        candidates=(candidate(),),
        provider_call_count=0,
        abstention_reasons=(),
    )
    assert routing.route.path is AppraisalPath.TYPED_MAPPING
    assert routing.candidates[0].kind == "plan_cancelled"

    with pytest.raises(ValueError, match="scope"):
        replace(routing, candidates=(candidate(scope=agent_scope()),))
    with pytest.raises(ValueError, match="unique"):
        replace(routing, candidates=(candidate(), candidate()))
    with pytest.raises(ValueError, match="provider_call_count"):
        replace(routing, provider_call_count=-1)


def test_transition_input_carries_observations_and_same_scope_history() -> None:
    transition_input = EmotionalTransitionInput(
        interaction_id="interaction-1",
        scope=user_scope(),
        origin_runtime_id="runtime-1",
        context=context(),
        current_affect=(state("agent.affect.longing", 0.3),),
        elapsed=timedelta(minutes=5),
        persona_id="kayla",
        persona_version=1,
        persona=(),
        observations=(observation(),),
        semantic_candidates=(candidate(),),
        history_context=history(),
        clock=NOW,
        projection_scope=agent_scope(),
    )
    assert transition_input.observations[0].id == "observation-1"
    assert transition_input.history_context is not None
    assert transition_input.history_context.bundle_id == "history-1"

    with pytest.raises(ValueError, match="observation scope"):
        replace(transition_input, observations=(observation(scope=agent_scope()),))
    with pytest.raises(ValueError, match="history context scope"):
        replace(transition_input, history_context=history(scope=agent_scope()))

    wrong_scope_state = state(
        "user.affect.longing", 0.3, scope=user_scope(), state_id="wrong-scope"
    )
    with pytest.raises(ValueError, match="current affect scope"):
        replace(transition_input, current_affect=(wrong_scope_state,))
    with pytest.raises(ValueError, match="dimensions must be unique"):
        replace(
            transition_input,
            current_affect=(
                state("agent.affect.longing", 0.3, state_id="longing-1"),
                state("agent.affect.longing", 0.4, state_id="longing-2"),
            ),
        )
    with pytest.raises(ValueError, match="values must be numeric"):
        replace(
            transition_input,
            current_affect=(replace(state("agent.affect.longing", 0.3), value="high"),),
        )


def test_assessment_trace_embeds_one_semantic_route() -> None:
    assert "route_decision" in {field.name for field in fields(AssessmentTrace)}

    with pytest.raises(ValueError, match="route_decision.scope"):
        AssessmentTrace(
            trace_id="trace-1",
            scope=user_scope(),
            origin_runtime_id="runtime-1",
            context_ref="context-1",
            persona_id="kayla",
            persona_version=1,
            state_before=(),
            contributions=(),
            state_after=(),
            evidence_refs=(),
            history_refs=(),
            abstention_reasons=(),
            route_decision=route(scope=agent_scope()),
            created_at=NOW,
        )
