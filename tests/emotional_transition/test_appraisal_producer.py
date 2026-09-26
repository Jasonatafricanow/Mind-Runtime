"""Tests for ADR-0019-R4 SemanticAppraisalProducer and end-to-end longitudinal activation.

Covers:
1. Field ownership:
   - appraisal_id is system-authored (not model-proposed)
   - scope, origin_runtime_id, situation_ref are system-bound
   - evidence_refs must be a subset of trusted_evidence_pool; out-of-pool -> salience=None
2. History fail-closed rule:
   - When proposal references historical pattern, trusted history ref is required
   - Missing trusted history ref -> salience=None
3. Source-independent confidence:
   - Appraisal confidence comes from proposal, not candidate attribution confidence
4. Range validation:
   - Salience out of [0, 1] -> salience=None (no clamping)
   - Confidence out of [0, 1] -> salience=None
5. End-to-end integration:
   - Observation / typed event -> SemanticRouter -> Candidate -> AppraisalProducer
   - -> appraisals_by_candidate_id -> EffectMapper -> Impulse
   - -> HomeostasisGate (SLOW_ACCEPT) -> SlowPlasticityWriter -> SQLite state persisted
6. Negative end-to-end:
   - Appraisal failure (salience=None) -> Gate veto / REJECT -> writer not invoked
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
import pytest

from mind_runtime.contracts import (
    AffectiveDimensionProfile,
    AppraisalPath,
    AppraisalRouteDecision,
    HistoricalContextBundle,
    PatternMatchSummary,
    RuntimeState,
    Scope,
    ScopeDomain,
    SemanticAppraisal,
    SemanticAppraisalContext,
    SemanticAppraisalModelPort,
    SemanticEventCandidate,
    SemanticRoutingResult,
    Situation,
    StateDefinition,
    StateDomain,
    StateValueType,
    SyncFields,
)
from mind_runtime.contracts.appraisal import AppraisalModelProposal
from mind_runtime.dynamics.engine import DynamicsEngine
from mind_runtime.dynamics.persona import PersonaProfile
from mind_runtime.dynamics.ports import EngineEmotionalTransitionPort
from mind_runtime.emotional_transition.appraisal import (
    ConfiguredSemanticAppraisalModel,
    SemanticAppraisalProducer,
)
from mind_runtime.emotional_transition.effects import EffectMapper, EventEffectRule
from mind_runtime.emotional_transition.projection_journal import ProjectionJournal
from mind_runtime.emotional_transition.semantic import SemanticRouter
from mind_runtime.homeostasis.contracts import HomeostasisDisposition
from mind_runtime.homeostasis.policy import (
    FixedSalienceThresholdConfig,
    SalienceThresholdPolicy,
)
from mind_runtime.slow_plasticity.writer import SlowPlasticityWriter
from mind_runtime.state.definitions import StateDefinitionRegistry
from mind_runtime.state.persistence import SqliteStateBackend

NOW = datetime(2026, 8, 22, 12, 0, tzinfo=UTC)
USER_SCOPE = Scope(domain=ScopeDomain.USER, user_id="alice")
AGENT_SCOPE = Scope(domain=ScopeDomain.AGENT, agent_id="kayla", persona_id="kayla")


def _projection_definitions() -> StateDefinitionRegistry:
    return StateDefinitionRegistry(
        (
            StateDefinition("agent.affect.anxiety", StateDomain.AGENT,
                            StateValueType.SCALAR, "deterministic_affect", None, (0.0, 1.0)),
            StateDefinition("agent.longitudinal.relationship_security", StateDomain.AGENT,
                            StateValueType.SCALAR, "accumulator", "indefinite", (0.0, 1.0)),
        )
    )


def _affect(dim: str) -> AffectiveDimensionProfile:
    return AffectiveDimensionProfile(
        dimension=dim,
        baseline=0.3,
        initial_value=0.3,
        sensitivity=1.0,
        recovery_rate=0.1,
        ceiling=1.0,
        floor=0.0,
        growth_profile=(),
        coupling_profile=(),
    )


def _candidate(
    candidate_id: str = "cand-1",
    kind: str = "plan_cancelled",
    confidence: float = 0.95,
    evidence_refs: tuple[str, ...] = ("ev-cand-1",),
) -> SemanticEventCandidate:
    return SemanticEventCandidate(
        candidate_id=candidate_id,
        scope=USER_SCOPE,
        origin_runtime_id="runtime-1",
        kind=kind,
        attributes=(),
        confidence=confidence,
        evidence_refs=evidence_refs,
    )


def _situation(evidence_refs: tuple[str, ...] = ("ev-sit-1",)) -> Situation:
    return Situation(
        situation_id="sit-1",
        scope=USER_SCOPE,
        origin_runtime_id="runtime-1",
        derived_facts=(),
        effective_state_ref="eff-1",
        observed_at=NOW,
        historical_context=None,
        persona_id="kayla",
        relationship_ids=(),
        evidence_refs=evidence_refs,
    )


def _history(with_pattern: bool = False) -> HistoricalContextBundle:
    pattern_summaries = ()
    if with_pattern:
        pattern_summaries = (
            PatternMatchSummary(
                summary_id="pat-1",
                scope=USER_SCOPE,
                origin_runtime_id="runtime-1",
                match_count=3,
                first_seen_at=NOW - timedelta(days=5),
                last_seen_at=NOW - timedelta(days=1),
                matched_refs=("ev-hist-1", "ev-hist-2"),
                confidence=0.85,
            ),
        )
    return HistoricalContextBundle(
        bundle_id="hist-1",
        scope=USER_SCOPE,
        origin_runtime_id="runtime-1",
        episodes=(),
        stable_facts=(),
        relationship_events=(),
        pattern_summaries=pattern_summaries,
        source_refs=("ev-hist-main",),
        provider_trace="trace-hist",
    )


# ============================================================================
# 1. Field Ownership Tests (ADR-0019-R4 §2)
# ============================================================================


class _MockModel(SemanticAppraisalModelPort):
    def __init__(self, proposal: AppraisalModelProposal) -> None:
        self.proposal = proposal
        self.last_pool: tuple[str, ...] = ()

    def propose(
        self,
        *,
        candidate: SemanticEventCandidate,
        context: SemanticAppraisalContext,
        trusted_evidence_pool: tuple[str, ...],
    ) -> AppraisalModelProposal:
        self.last_pool = trusted_evidence_pool
        return self.proposal


def test_system_authored_identity_and_system_bound_fields() -> None:
    candidate = _candidate(candidate_id="turn-candidate-99")
    situation = _situation()
    history = _history()
    context = SemanticAppraisalContext(
        candidate=candidate,
        situation=situation,
        persona=(_affect("agent.affect.anxiety"),),
        history=history,
    )

    proposal = AppraisalModelProposal(
        meanings=("plan_interrupted", "expectation_breach"),
        valence="negative",
        relationship_relevance="high",
        salience=0.88,
        appraisal_confidence=0.79,
        supporting_evidence_refs=("ev-cand-1",),
    )
    model = _MockModel(proposal)
    producer = SemanticAppraisalProducer(model=model)

    appraisal = producer.assemble(candidate=candidate, context=context)

    # 2.1: appraisal_id is system-authored
    assert appraisal.appraisal_id == "appraisal-turn-candidate-99"
    # 2.2: scope, origin_runtime_id, situation_ref are system-bound
    assert appraisal.scope == USER_SCOPE
    assert appraisal.origin_runtime_id == "runtime-1"
    assert appraisal.situation_ref == "sit-1"
    # Model values accepted
    assert appraisal.salience == 0.88
    assert appraisal.confidence == 0.79
    assert appraisal.evidence_refs == ("ev-cand-1",)


def test_trusted_evidence_pool_aggregation() -> None:
    candidate = _candidate(evidence_refs=("ev-cand-1",))
    situation = _situation(evidence_refs=("ev-sit-1",))
    history = _history(with_pattern=True)
    context = SemanticAppraisalContext(
        candidate=candidate,
        situation=situation,
        persona=(),
        history=history,
    )

    proposal = AppraisalModelProposal(
        meanings=("test",),
        valence="neutral",
        relationship_relevance="test",
        salience=0.5,
        appraisal_confidence=0.5,
        supporting_evidence_refs=("ev-cand-1",),
    )
    model = _MockModel(proposal)
    producer = SemanticAppraisalProducer(model=model)

    producer.assemble(candidate=candidate, context=context)
    pool = model.last_pool
    # Candidate evidence
    assert "ev-cand-1" in pool
    # Situation evidence
    assert "ev-sit-1" in pool
    # History pattern matched refs & source refs
    assert "ev-hist-1" in pool
    assert "ev-hist-2" in pool
    assert "ev-hist-main" in pool


def test_out_of_pool_evidence_fails_closed() -> None:
    candidate = _candidate(evidence_refs=("ev-cand-1",))
    situation = _situation(evidence_refs=())
    context = SemanticAppraisalContext(
        candidate=candidate,
        situation=situation,
        persona=(),
        history=None,
    )

    # Proposal introduces invented ref "ev-invented-by-model"
    proposal = AppraisalModelProposal(
        meanings=("unauthorized_evidence",),
        valence="negative",
        relationship_relevance="test",
        salience=0.8,
        appraisal_confidence=0.8,
        supporting_evidence_refs=("ev-cand-1", "ev-invented-by-model"),
    )
    producer = SemanticAppraisalProducer(model=_MockModel(proposal))
    appraisal = producer.assemble(candidate=candidate, context=context)

    # Must fail closed: salience is None
    assert appraisal.salience is None


# ============================================================================
# 2. History Provenance Fail-Closed Rule (ADR-0019-R4 §2.3)
# ============================================================================


def test_history_dependence_without_trusted_history_ref_fails_closed() -> None:
    candidate = _candidate(evidence_refs=("ev-cand-1",))
    # Context has NO history
    context = SemanticAppraisalContext(
        candidate=candidate,
        situation=_situation(),
        persona=(),
        history=None,
    )

    # Model proposes a meaning referencing recurring historical pattern
    proposal = AppraisalModelProposal(
        meanings=("recurring_cancellation_pattern",),
        valence="negative",
        relationship_relevance="relational_drift",
        salience=0.92,
        appraisal_confidence=0.85,
        supporting_evidence_refs=("ev-cand-1",),
    )
    producer = SemanticAppraisalProducer(model=_MockModel(proposal))
    appraisal = producer.assemble(candidate=candidate, context=context)

    # Material dependence without corresponding trusted history ref -> fails closed
    assert appraisal.salience is None


def test_history_dependence_with_trusted_history_ref_preserves_lineage() -> None:
    candidate = _candidate(evidence_refs=("ev-cand-1",))
    history = _history(with_pattern=True)
    context = SemanticAppraisalContext(
        candidate=candidate,
        situation=_situation(),
        persona=(),
        history=history,
    )

    proposal = AppraisalModelProposal(
        meanings=("recurring_cancellation_pattern",),
        valence="negative",
        relationship_relevance="relational_drift",
        salience=0.92,
        appraisal_confidence=0.85,
        supporting_evidence_refs=("ev-cand-1",),
    )
    producer = SemanticAppraisalProducer(model=_MockModel(proposal))
    appraisal = producer.assemble(candidate=candidate, context=context)

    # Salience is valid because history pattern ref is available in pool and preserved
    assert appraisal.salience == 0.92
    assert "ev-cand-1" in appraisal.evidence_refs
    assert any(ref in appraisal.evidence_refs for ref in ("ev-hist-1", "ev-hist-2"))


# ============================================================================
# 3. Source-Independent Confidence and Range Validation
# ============================================================================


def test_appraisal_confidence_is_source_independent() -> None:
    # Candidate attribution confidence is 0.99
    candidate = _candidate(confidence=0.99)
    context = SemanticAppraisalContext(
        candidate=candidate,
        situation=_situation(),
        persona=(),
        history=None,
    )

    # Appraisal model proposes appraisal_confidence = 0.65
    proposal = AppraisalModelProposal(
        meanings=("interpretation",),
        valence="negative",
        relationship_relevance="low",
        salience=0.70,
        appraisal_confidence=0.65,
        supporting_evidence_refs=("ev-cand-1",),
    )
    producer = SemanticAppraisalProducer(model=_MockModel(proposal))
    appraisal = producer.assemble(candidate=candidate, context=context)

    assert appraisal.salience == 0.70
    assert appraisal.confidence == 0.65  # Not candidate's 0.99


def test_salience_out_of_range_fails_closed_without_clamping() -> None:
    # AppraisalModelProposal itself strictly validates [0, 1] and raises ValueError
    with pytest.raises(ValueError, match="salience must be in"):
        AppraisalModelProposal(
            meanings=("test",),
            valence="negative",
            relationship_relevance="low",
            salience=1.25,  # Out of [0, 1]
            appraisal_confidence=0.8,
            supporting_evidence_refs=("ev-cand-1",),
        )

    # When a model throws an exception (such as ValueError or invalid range), producer fails closed
    class _FailingModel(SemanticAppraisalModelPort):
        def propose(self, *, candidate: SemanticEventCandidate, context: SemanticAppraisalContext, trusted_evidence_pool: tuple[str, ...]) -> AppraisalModelProposal:
            raise ValueError("model failed range check")

    candidate = _candidate()
    context = SemanticAppraisalContext(
        candidate=candidate,
        situation=_situation(),
        persona=(),
        history=None,
    )
    producer = SemanticAppraisalProducer(model=_FailingModel())
    appraisal = producer.assemble(candidate=candidate, context=context)
    assert appraisal.salience is None


# ============================================================================
# 4. End-to-End Longitudinal Activation Test
# ============================================================================


def test_e2e_production_appraisal_to_slow_persistence(tmp_path: Path) -> None:
    """Full production pipeline activation check:
    Event -> SemanticRouter -> Candidate -> AppraisalProducer (model)
    -> routing.appraisals_by_candidate_id -> EffectMapper -> Impulse
    -> HomeostasisGate (SLOW_ACCEPT) -> SlowPlasticityWriter
    -> SqliteStateBackend canonical slow state persisted.
    """
    db_path = tmp_path / "state.db"
    backend = SqliteStateBackend(db_path)

    # Register longitudinal state definition per ADR-0018-R2
    backend.save_definition(
        StateDefinition(
            key="agent.longitudinal.relationship_security",
            domain=StateDomain.AGENT,
            value_type=StateValueType.SCALAR,
            dynamics_policy="accumulator",
            default_validity_policy="indefinite",
            bounds=(0.0, 1.0),
        )
    )

    # Rule configured with ADR-0018-R2 pairwise longitudinal target
    rule = EventEffectRule(
        event_kind="plan_cancelled",
        dimension="agent.affect.anxiety",
        base_amount=0.2,
        longitudinal_target_dimension="agent.longitudinal.relationship_security",
        longitudinal_proposed_value=0.30,
    )

    # Production V1 ConfiguredSemanticAppraisalModel and Producer
    appraisal_model = ConfiguredSemanticAppraisalModel()
    producer = SemanticAppraisalProducer(model=appraisal_model)

    # Homeostasis gate with production threshold (salience >= 0.51 -> SLOW_ACCEPT)
    gate = SalienceThresholdPolicy(
        config=FixedSalienceThresholdConfig(
            salience_floor_fast_apply=0.0,
            salience_floor_slow_accept=0.51,
            confidence_floor_slow=0.0,
        )
    )

    engine_port = EngineEmotionalTransitionPort(
        engine=DynamicsEngine(
            persona=PersonaProfile(
                persona_id="kayla",
                dimensions=(_affect("agent.affect.anxiety"),),
            )
        ),
        runtime_id="runtime-1",
        effect_rules=(rule,),
        semantic_router=SemanticRouter(),
        homeostasis_gate=gate,
        appraisal_producer=producer,
        projection_journal=ProjectionJournal(tmp_path / "projection.sqlite"),
        state_definitions=_projection_definitions(),
    )

    writer = SlowPlasticityWriter(
        backend=backend,
        runtime_id="runtime-1",
        window_size=8,
    )

    candidate = _candidate(
        candidate_id="cand-live-1",
        kind="plan_cancelled",
        confidence=0.85,
        evidence_refs=("ev-user-msg-1",),
    )
    situation = _situation(evidence_refs=("ev-sit-1",))

    from mind_runtime.contracts.emotional_transition import EmotionalTransitionInput

    transition_input = EmotionalTransitionInput(
        interaction_id="turn-live-1",
        scope=USER_SCOPE,
        origin_runtime_id="runtime-1",
        context=situation,
        current_affect=(),
        elapsed=timedelta(seconds=0),
        persona_id="kayla",
        persona_version=1,
        persona=(_affect("agent.affect.anxiety"),),
        observations=(),
        semantic_candidates=(candidate,),
        history_context=_history(with_pattern=True),
        clock=NOW,
        projection_scope=AGENT_SCOPE,
    )

    outcome = engine_port.transition_with_gate(transition_input)

    # Verify appraisal was produced and populated in routing
    assert outcome.slow_decisions, "Expected at least one homeostasis decision"

    # Find the longitudinal decision
    longitudinal_decisions = [
        d for d in outcome.slow_decisions
        if d.candidate.target_dimension == "agent.longitudinal.relationship_security"
    ]
    assert len(longitudinal_decisions) == 1
    decision = longitudinal_decisions[0]

    # Verify gate disposition is SLOW_ACCEPT
    assert decision.decision == HomeostasisDisposition.SLOW_ACCEPT
    assert decision.candidate.salience is not None
    assert decision.candidate.salience >= 0.51
    assert decision.candidate.proposed_value == 0.30

    # Pass decision to SlowPlasticityWriter and flush
    writer.accept(decision, target_scope=AGENT_SCOPE)
    writer.flush(AGENT_SCOPE)

    # Verify canonical state is durably written to SQLite
    states = backend.load_states()
    longitudinal_states = [
        s for s in states
        if s.dimension == "agent.longitudinal.relationship_security"
    ]
    assert len(longitudinal_states) == 1
    assert longitudinal_states[0].value == 0.30
    assert longitudinal_states[0].scope == AGENT_SCOPE


def test_e2e_appraisal_failure_vetoes_slow_accept(tmp_path: Path) -> None:
    """When appraisal fails (salience=None), gate REJECTs and writer receives nothing."""
    rule = EventEffectRule(
        event_kind="plan_cancelled",
        dimension="agent.affect.anxiety",
        base_amount=0.2,
        longitudinal_target_dimension="agent.longitudinal.relationship_security",
        longitudinal_proposed_value=0.30,
    )

    # Model that fails proposal (returns salience=None)
    failing_proposal = AppraisalModelProposal(
        meanings=("unappraised",),
        valence="negative",
        relationship_relevance="unknown",
        salience=None,
        appraisal_confidence=0.5,
        supporting_evidence_refs=("ev-cand-1",),
    )
    producer = SemanticAppraisalProducer(model=_MockModel(failing_proposal))
    gate = SalienceThresholdPolicy(
        config=FixedSalienceThresholdConfig(
            salience_floor_fast_apply=0.0,
            salience_floor_slow_accept=0.51,
            confidence_floor_slow=0.0,
        )
    )

    engine_port = EngineEmotionalTransitionPort(
        engine=DynamicsEngine(
            persona=PersonaProfile(
                persona_id="kayla",
                dimensions=(_affect("agent.affect.anxiety"),),
            )
        ),
        runtime_id="runtime-1",
        effect_rules=(rule,),
        semantic_router=SemanticRouter(),
        homeostasis_gate=gate,
        appraisal_producer=producer,
        projection_journal=ProjectionJournal(tmp_path / "projection.sqlite"),
        state_definitions=_projection_definitions(),
    )

    candidate = _candidate(candidate_id="cand-fail-1")
    from mind_runtime.contracts.emotional_transition import EmotionalTransitionInput

    transition_input = EmotionalTransitionInput(
        interaction_id="turn-fail-1",
        scope=USER_SCOPE,
        origin_runtime_id="runtime-1",
        context=_situation(),
        current_affect=(),
        elapsed=timedelta(seconds=0),
        persona_id="kayla",
        persona_version=1,
        persona=(_affect("agent.affect.anxiety"),),
        observations=(),
        semantic_candidates=(candidate,),
        history_context=None,
        clock=NOW,
        projection_scope=AGENT_SCOPE,
    )

    outcome = engine_port.transition_with_gate(transition_input)

    # Gate must NOT SLOW_ACCEPT
    for d in outcome.slow_decisions:
        assert d.decision != HomeostasisDisposition.SLOW_ACCEPT


def test_model_backed_appraisal_model_propose_and_assembly() -> None:
    """Test ModelBackedSemanticAppraisalModel happy path with custom ChatTransport."""
    import json
    from mind_runtime.emotional_transition.appraisal import ModelBackedSemanticAppraisalModel

    class FakeTransport:
        def __init__(self) -> None:
            self.posted: list[dict[str, object]] = []

        def post_json(
            self, url: str, framed: dict[str, object], timeout_s: float
        ) -> dict[str, object]:
            self.posted.append({"url": url, "framed": framed, "timeout": timeout_s})
            return {
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "meanings": ["meaning-1", "meaning-2"],
                                    "valence": "positive",
                                    "relationship_relevance": "high",
                                    "salience": 0.89,
                                    "appraisal_confidence": 0.81,
                                    "supporting_evidence_refs": ["ev-cand-1"],
                                }
                            )
                        }
                    }
                ]
            }

    transport = FakeTransport()
    model = ModelBackedSemanticAppraisalModel(
        endpoint_url="https://model.example.com/v1/chat",
        model="test-appraisal-v1",
        api_key_env="TEST_API_KEY",
        transport=transport,
        allowed_hosts=("model.example.com",),
    )

    producer = SemanticAppraisalProducer(model=model)
    candidate = _candidate(evidence_refs=("ev-cand-1",))
    context = SemanticAppraisalContext(
        candidate=candidate,
        situation=_situation(),
        persona=(_affect("agent.affect.excitement"),),
        history=None,
    )

    appraisal = producer.assemble(candidate=candidate, context=context)

    assert len(transport.posted) == 1
    assert appraisal.salience == 0.89
    assert appraisal.confidence == 0.81
    assert appraisal.evidence_refs == ("ev-cand-1",)
    assert appraisal.meanings == ("meaning-1", "meaning-2")
    assert appraisal.valence == "positive"


def test_model_backed_appraisal_model_missing_api_key_fails_fast() -> None:
    """Without API key, UrllibChatTransport fails fast without connecting."""
    import os
    from mind_runtime.emotional_transition.appraisal import ModelBackedSemanticAppraisalModel

    os.environ.pop("UNSET_APPRAISAL_KEY", None)
    model = ModelBackedSemanticAppraisalModel(
        endpoint_url="https://model.example.com/v1/chat",
        model="test-appraisal-v1",
        api_key_env="UNSET_APPRAISAL_KEY",
        allowed_hosts=("model.example.com",),
    )
    producer = SemanticAppraisalProducer(model=model)
    candidate = _candidate()
    context = SemanticAppraisalContext(
        candidate=candidate,
        situation=_situation(),
        persona=(),
        history=None,
    )

    # assemble catches ProviderUnavailableError and returns salience=None
    appraisal = producer.assemble(candidate=candidate, context=context)
    assert appraisal.salience is None
    assert appraisal.confidence == 0.0


def test_model_backed_appraisal_model_untrusted_evidence_fails_closed() -> None:
    """If model proposes evidence not in trusted pool, producer fails closed (salience=None)."""
    import json
    from mind_runtime.emotional_transition.appraisal import ModelBackedSemanticAppraisalModel

    class RogueTransport:
        def post_json(
            self, url: str, framed: dict[str, object], timeout_s: float
        ) -> dict[str, object]:
            return {
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "meanings": ["meaning-1"],
                                    "valence": "positive",
                                    "relationship_relevance": "high",
                                    "salience": 0.95,
                                    "appraisal_confidence": 0.90,
                                    "supporting_evidence_refs": ["untrusted-invented-ref"],
                                }
                            )
                        }
                    }
                ]
            }

    model = ModelBackedSemanticAppraisalModel(
        endpoint_url="https://model.example.com/v1/chat",
        model="test-appraisal-v1",
        transport=RogueTransport(),
    )
    producer = SemanticAppraisalProducer(model=model)
    candidate = _candidate(evidence_refs=("ev-cand-1",))
    context = SemanticAppraisalContext(
        candidate=candidate,
        situation=_situation(),
        persona=(),
        history=None,
    )

    appraisal = producer.assemble(candidate=candidate, context=context)
    assert appraisal.salience is None


def test_body_supplied_appraisal_proposal_needs_no_local_model() -> None:
    candidate = _candidate()
    context = SemanticAppraisalContext(
        candidate=candidate,
        situation=_situation(),
        persona=(),
        history=None,
        current_affect=(),
    )
    proposal = AppraisalModelProposal(
        meanings=("the plan was cancelled",),
        valence="negative",
        relationship_relevance="relevant",
        salience=0.88,
        appraisal_confidence=0.91,
        supporting_evidence_refs=candidate.evidence_refs,
    )
    producer = SemanticAppraisalProducer(model=None)
    acceptance = producer.accept(
        candidate=candidate,
        context=context,
        interaction_id="interaction-1",
        persona_id="kayla",
        route_abstention_reasons=(),
        projection_scope=AGENT_SCOPE,
        proposal=proposal,
    )
    assert acceptance.status == "ACCEPTED"
    assert acceptance.appraisal.meanings == proposal.meanings
    assert acceptance.appraisal.salience == proposal.salience
