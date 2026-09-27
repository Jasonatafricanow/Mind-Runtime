from datetime import UTC, datetime

import pytest

from mind_runtime.contracts import (
    AffectiveDimensionProfile,
    AppraisalModelProposal,
    Scope,
    ScopeDomain,
    SemanticAppraisalContext,
    encode_body_factor_attributes,
    SemanticEventCandidate,
    Situation,
    StateDefinition,
    StateDomain,
    StateValueType,
)
from mind_runtime.dynamics.persona import PersonaProfile
from mind_runtime.emotional_transition.appraisal import SemanticAppraisalProducer
from mind_runtime.emotional_transition.effects import (
    AppraisalProjector,
    mapping_from_projection,
)
from mind_runtime.state.definitions import StateDefinitionRegistry

NOW = datetime(2026, 9, 27, tzinfo=UTC)
USER_SCOPE = Scope(ScopeDomain.USER, user_id="user-1")
AGENT_SCOPE = Scope(ScopeDomain.AGENT, agent_id="agent-1", persona_id="agent-1")


def _profile(dimension: str) -> AffectiveDimensionProfile:
    return AffectiveDimensionProfile(
        dimension=dimension,
        baseline=0.3,
        initial_value=0.3,
        sensitivity=1.0,
        recovery_rate=0.2,
        ceiling=1.0,
        floor=0.0,
        growth_profile=(),
        coupling_profile=(),
    )


def _persona(*dimensions: str) -> PersonaProfile:
    return PersonaProfile(
        persona_id="agent-1",
        dimensions=tuple(_profile(d) for d in dimensions),
    )


def _definitions(*dimensions: str) -> StateDefinitionRegistry:
    return StateDefinitionRegistry(
        tuple(
            StateDefinition(
                key=d,
                domain=StateDomain.AGENT,
                value_type=StateValueType.SCALAR,
                dynamics_policy="deterministic_affect",
                default_validity_policy=None,
                bounds=(0.0, 1.0),
            )
            for d in dimensions
        )
    )


def _acceptance(
    *,
    factors: tuple[tuple[str, float], ...],
    candidate_id: str = "frame-1",
    attributes: tuple[tuple[str, str], ...] = (),
):
    candidate = SemanticEventCandidate(
        candidate_id=candidate_id,
        scope=USER_SCOPE,
        origin_runtime_id="runtime-1",
        kind="__body_semantic__",
        attributes=encode_body_factor_attributes(factors) + attributes,
        confidence=0.9,
        evidence_refs=("ev-1",),
    )
    situation = Situation(
        situation_id="situation-1",
        scope=USER_SCOPE,
        origin_runtime_id="runtime-1",
        derived_facts=(),
        effective_state_ref="effective-1",
        observed_at=NOW,
        historical_context=None,
        persona_id="agent-1",
        relationship_ids=(),
        evidence_refs=("ev-1",),
    )
    context = SemanticAppraisalContext(
        candidate=candidate,
        situation=situation,
        persona=(),
        history=None,
    )
    proposal = AppraisalModelProposal(
        meanings=("open natural-language meaning",),
        valence="mixed",
        relationship_relevance="open",
        salience=0.8,
        appraisal_confidence=0.9,
        supporting_evidence_refs=("ev-1",),
        factors=factors,
    )
    return SemanticAppraisalProducer(model=None).accept(
        candidate=candidate,
        context=context,
        interaction_id="turn-1",
        persona_id="agent-1",
        route_abstention_reasons=(),
        projection_scope=AGENT_SCOPE,
        proposal=proposal,
    )


def _mapped(
    factors: tuple[tuple[str, float], ...],
    *,
    dimensions: tuple[str, ...],
    attributes: tuple[tuple[str, str], ...] = (),
):
    persona = _persona(*dimensions)
    projector = AppraisalProjector(
        rules=(),
        persona_profile=persona,
        definitions=_definitions(*dimensions),
    )
    projection = projector.project(
        acceptance=_acceptance(factors=factors, attributes=attributes),
        persona=persona.dimensions,
    )
    return projection, mapping_from_projection(projection)


def test_anxiety_requires_causal_combination_not_event_label() -> None:
    dimension = "agent.affect.anxiety"
    projection, mapped = _mapped(
        (("threat", 0.9), ("uncertainty", 0.8)),
        dimensions=(dimension,),
    )

    assert projection.status.value == "MAPPED"
    assert len(mapped.impulses) == 1
    assert mapped.impulses[0].dimension == dimension
    assert mapped.impulses[0].amount == pytest.approx(0.10368)


def test_event_hint_cannot_change_body_affect_projection() -> None:
    factors = (("threat", 0.9), ("uncertainty", 0.8))
    _, left = _mapped(
        factors,
        dimensions=("agent.affect.anxiety",),
        attributes=(("__event_hint__", "plan_cancelled"),),
    )
    _, right = _mapped(
        factors,
        dimensions=("agent.affect.anxiety",),
        attributes=(("__event_hint__", "warm_reunion"),),
    )

    assert left.impulses == right.impulses


def test_open_semantics_without_affect_factors_is_valid_but_unmapped() -> None:
    projection, mapped = _mapped((), dimensions=("agent.affect.anxiety",))

    assert projection.status.value == "UNMAPPED"
    assert projection.reason_codes == ("no_affect_factors",)
    assert mapped.impulses == ()


def test_relationship_factors_can_raise_or_reduce_longing_without_event_taxonomy() -> None:
    dimension = "agent.affect.longing"
    _, separated = _mapped(
        (("separation", 0.8), ("relationship_relevance", 0.9)),
        dimensions=(dimension,),
    )
    _, connected = _mapped(
        (("connection", 0.8), ("relationship_relevance", 0.9)),
        dimensions=(dimension,),
    )

    assert separated.impulses[0].amount > 0
    assert connected.impulses[0].amount < 0
    assert abs(separated.impulses[0].amount) <= 0.20
    assert abs(connected.impulses[0].amount) <= 0.20
