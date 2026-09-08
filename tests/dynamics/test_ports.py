"""D7R EngineEmotionalTransitionPort tests."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from mind_runtime.contracts import (
    AffectiveDimensionProfile,
    EmotionalTransitionInput,
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

NOW = datetime(2026, 8, 23, 9, 0, tzinfo=UTC)
USER_SCOPE = Scope(domain=ScopeDomain.USER, user_id="user-1")
AGENT_SCOPE = Scope(domain=ScopeDomain.AGENT, agent_id="test", persona_id="test")


def make_profile(dimension: str, *, baseline: float = 0.3) -> AffectiveDimensionProfile:
    return AffectiveDimensionProfile(
        dimension=dimension,
        baseline=baseline,
        initial_value=baseline,
        sensitivity=0.8,
        recovery_rate=0.2,
        ceiling=1.0,
        floor=0.0,
        growth_profile=(),
        coupling_profile=(),
    )


def make_context() -> Situation:
    return Situation(
        situation_id="context-1",
        scope=USER_SCOPE,
        origin_runtime_id="runtime-1",
        derived_facts=(("conversation.active", "true"),),
        effective_state_ref="state-1",
        observed_at=NOW,
        historical_context=None,
        persona_id="test",
        relationship_ids=(),
        evidence_refs=("evidence-1",),
    )


def make_port(*dimensions: AffectiveDimensionProfile) -> EngineEmotionalTransitionPort:
    persona = PersonaProfile(persona_id="test", dimensions=dimensions, version=3)
    return EngineEmotionalTransitionPort(
        engine=DynamicsEngine(persona=persona), runtime_id="runtime-1"
    )


def make_current(dimension: str, value: float) -> RuntimeState:
    state_id = f"{dimension}:1"
    return RuntimeState(
        state_id=state_id,
        scope=AGENT_SCOPE,
        origin_runtime_id="runtime-1",
        dimension=dimension,
        value=value,
        status="active",
        valid_from=NOW - timedelta(seconds=5),
        valid_until=None,
        relevant_until=None,
        last_observed_at=NOW - timedelta(seconds=5),
        evidence_refs=(),
        transition_refs=(),
        updated_at=NOW - timedelta(seconds=5),
        version=1,
        sync=SyncFields(AGENT_SCOPE, "runtime-1", state_id, 1, f"idem-{state_id}"),
    )


def make_input(
    dimensions: tuple[AffectiveDimensionProfile, ...],
    *,
    current: tuple[RuntimeState, ...] = (),
    elapsed: timedelta = timedelta(0),
    projection_scope: Scope | None = None,
    semantic_candidates: tuple[SemanticEventCandidate, ...] = (),
) -> EmotionalTransitionInput:
    return EmotionalTransitionInput(
        interaction_id="interaction-1",
        scope=USER_SCOPE,
        origin_runtime_id="runtime-1",
        context=make_context(),
        current_affect=current,
        elapsed=elapsed,
        persona_id="test",
        persona_version=3,
        persona=dimensions,
        observations=(),
        semantic_candidates=semantic_candidates,
        history_context=None,
        clock=NOW,
        projection_scope=projection_scope,
    )


def test_transition_recovers_and_records_complete_d7_trace() -> None:
    dimensions = (
        make_profile("agent.affect.longing"),
        make_profile("agent.affect.anxiety", baseline=0.2),
    )
    result = make_port(*dimensions).transition(
        make_input(
            dimensions,
            current=(
                make_current("agent.affect.longing", 0.9),
                make_current("agent.affect.anxiety", 0.2),
            ),
            elapsed=timedelta(seconds=5),
            projection_scope=AGENT_SCOPE,
        )
    )
    assert result.projected.projected_states[0].scope == AGENT_SCOPE
    assert result.projected.projected_states[0].dimension == "agent.affect.longing"
    projected_value = result.projected.projected_states[0].value
    assert isinstance(projected_value, float)
    assert 0.3 < projected_value < 0.9
    assert result.assessment_trace.persona_id == "test"
    assert result.assessment_trace.persona_version == 3
    assert result.assessment_trace.state_after[1] == ("agent.affect.anxiety", 0.2)
    assert result.assessment_trace.contributions[0].source_kind == "recovery"
    assert result.accepted_events == ()


def test_transition_rejects_persona_metadata_mismatch() -> None:
    dimensions = (make_profile("agent.affect.longing"),)
    transition_input = make_input(dimensions)
    with pytest.raises(ValueError, match="persona metadata"):
        make_port(*dimensions).transition(replace(transition_input, persona_version=4))


def test_transition_rejects_explicit_wrong_projection_scope() -> None:
    dimensions = (make_profile("agent.affect.longing"),)
    with pytest.raises(ValueError, match="conflicts with projection scope domain user"):
        make_port(*dimensions).transition(make_input(dimensions, projection_scope=USER_SCOPE))


def test_transition_empty_persona_fails_closed() -> None:
    with pytest.raises(ValueError, match="no affect dimensions"):
        make_port().transition(make_input(()))


def test_projection_scope_supports_user_dimensions() -> None:
    dimensions = (make_profile("user.affect.energy"),)
    result = make_port(*dimensions).transition(make_input(dimensions))
    assert result.projected.scope == USER_SCOPE


def test_projection_scope_derives_agent_scope_from_persona() -> None:
    dimensions = (make_profile("agent.affect.longing"),)
    result = make_port(*dimensions).transition(make_input(dimensions))
    assert result.projected.scope == AGENT_SCOPE


def test_projection_scope_rejects_mixed_domains() -> None:
    dimensions = (
        make_profile("agent.affect.longing"),
        make_profile("user.affect.energy"),
    )
    with pytest.raises(ValueError, match="uniformly agent"):
        make_port(*dimensions).transition(make_input(dimensions))


def test_projection_scope_helper_rejects_empty_persona() -> None:
    from mind_runtime.dynamics.ports import _projection_scope_for

    engine = DynamicsEngine(persona=PersonaProfile(persona_id="test", dimensions=()))
    with pytest.raises(ValueError, match="no affect dimensions"):
        _projection_scope_for(engine, turn_scope=USER_SCOPE, explicit=None)


def test_semantic_candidate_evidence_is_preserved_in_trace_and_projection() -> None:
    dimensions = (make_profile("agent.affect.longing"),)
    candidate = SemanticEventCandidate(
        candidate_id="candidate-1",
        scope=USER_SCOPE,
        origin_runtime_id="runtime-1",
        kind="plan_cancelled",
        attributes=(),
        confidence=0.9,
        evidence_refs=("evidence-2", "evidence-1"),
    )

    result = make_port(*dimensions).transition(
        make_input(
            dimensions,
            projection_scope=AGENT_SCOPE,
            semantic_candidates=(candidate,),
        )
    )

    assert result.assessment_trace.evidence_refs == ("evidence-1", "evidence-2")
    assert result.projected.projected_states[0].evidence_refs == (
        "evidence-1",
        "evidence-2",
    )
