"""C10-BW-UPSTREAM-R2 §A-§E authority chain tests.

Per the addendum to ticket C10-SALIENCE-IMPL:

  A. EventEffectRule does NOT own runtime salience
  B. EventEffectRule does NOT own evidence_refs
  C. None ≠ 0.0: unavailable salience stays None
  D. Longitudinal target implementation is preserved (no rollback)
  E. Final production topology: Evidence → Semantic / Appraisal →
     EffectMapper → longitudinal contribution → HomeostasisGate

These tests assert that the authority chain is correct: salience and
evidence_refs are appraisal surface authority, NOT static-rule authority.
"""

from __future__ import annotations

import inspect
from dataclasses import dataclass
from datetime import UTC, datetime

import pytest

from mind_runtime.contracts import (
    AffectiveDimensionProfile,
    AppraisalPath,
    AppraisalRouteDecision,
    Observation,
    Scope,
    ScopeDomain,
    SemanticAppraisal,
    SemanticEventCandidate,
    SemanticRoutingResult,
    Situation,
    SyncFields,
)
from mind_runtime.dynamics.engine import Contribution, DynamicsEngine, Impulse
from mind_runtime.dynamics.persona import PersonaProfile
from mind_runtime.emotional_transition.effects import EffectMapper, EventEffectRule
from mind_runtime.emotional_transition.semantic import (
    SemanticCandidateProvider,
    SemanticRouter,
)
from mind_runtime.homeostasis.contracts import HomeostasisDisposition
from mind_runtime.homeostasis.policy import (
    FixedSalienceThresholdConfig,
    SalienceThresholdPolicy,
)


NOW = datetime(2026, 8, 22, 12, 0, tzinfo=UTC)
USER_SCOPE = Scope(domain=ScopeDomain.USER, user_id="alice")
AGENT_SCOPE = Scope(domain=ScopeDomain.AGENT, agent_id="kayla", persona_id="kayla")


def sync(scope: Scope, oid: str, *, version: int = 1) -> SyncFields:
    return SyncFields(scope, "runtime-1", oid, version, f"idem-{oid}")


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


def _routing(
    candidate: SemanticEventCandidate,
    appraisals: dict[str, SemanticAppraisal] | None = None,
) -> SemanticRoutingResult:
    return SemanticRoutingResult(
        route=AppraisalRouteDecision(
            route_id="r1",
            scope=candidate.scope,
            path=AppraisalPath.DETERMINISTIC,
            ambiguity_score=None,
            confidence=0.8,
            reason_codes=(),
        ),
        candidates=(candidate,),
        abstention_reasons=(),
        provider_call_count=1,
        appraisals_by_candidate_id=appraisals or {},
    )


def _candidate(
    appraisal_salience: float | None = 0.95,
    evidence_refs: tuple[str, ...] = ("ev-appraisal-1",),
) -> tuple[SemanticEventCandidate, dict[str, SemanticAppraisal]]:
    """Build a SemanticEventCandidate plus its appraisal carrier dict.

    Per C10-SALIENCE-IMPL-R2: candidate and appraisal are separate objects
    at different layers. The carrier is
    SemanticRoutingResult.appraisals_by_candidate_id.
    """
    candidate_id = "cand-1"
    appraisals: dict[str, SemanticAppraisal] = {}
    appraisal: SemanticAppraisal | None = None
    if appraisal_salience is not None or evidence_refs:
        appraisal = SemanticAppraisal(
            appraisal_id=f"appraisal-{candidate_id}",
            scope=USER_SCOPE,
            origin_runtime_id="runtime-1",
            situation_ref="sit-1",
            meanings=("betrayal", "trust-impact"),
            valence="negative",
            relationship_relevance="primary",
            confidence=0.8,
            evidence_refs=evidence_refs,
            salience=appraisal_salience,
        )
        appraisals[candidate_id] = appraisal
    candidate = SemanticEventCandidate(
        candidate_id=candidate_id,
        scope=USER_SCOPE,
        origin_runtime_id="runtime-1",
        kind="plan_cancelled",
        attributes=(),
        confidence=0.8,
        evidence_refs=evidence_refs,
    )
    return candidate, appraisals


# ============================================================================
# §A — EventEffectRule does NOT own runtime salience
# ============================================================================


def test_S8_event_effect_rule_does_not_have_salience_field() -> None:
    """Per §A: EventEffectRule does not own runtime salience. The dataclass
    must NOT have a salience field. The contract is enforced by the type:
    `EventEffectRule(salience=...)` raises TypeError."""
    with pytest.raises(TypeError):
        EventEffectRule(
            event_kind="plan_cancelled",
            dimension="agent.affect.anxiety",
            base_amount=0.2,
            salience=0.95,  # MUST raise — rule is not a salience authority
        )


def test_S8_salience_originates_from_semantic_routing_result_appraisal() -> None:
    """Per C10-SALIENCE-IMPL-R2: salience authority lives in
    SemanticRoutingResult.appraisals_by_candidate_id (the appraisal surface),
    and propagates to MappedEffects.salience_by_source via the mapper."""
    rule = EventEffectRule(
        event_kind="plan_cancelled",
        dimension="agent.affect.anxiety",
        base_amount=0.2,
        longitudinal_target_dimension="agent.slow.anxiety",
        longitudinal_proposed_value=0.8,
    )
    candidate, appraisals = _candidate(appraisal_salience=0.77)
    mapper = EffectMapper(rules=(rule,))
    result = mapper.map(
        routing=_routing(candidate, appraisals), history=None
    )

    # Per §A: salience is on candidate (appraisal), not on rule
    # Per §E: the longitudinal contribution inherits the same per-turn
    # appraisal salience as the immediate contribution
    assert result.salience_by_source["event:cand-1"] == 0.77
    assert result.salience_by_source["longitudinal:cand-1"] == 0.77


# ============================================================================
# §B — EventEffectRule does NOT own evidence_refs
# ============================================================================


def test_P4_event_effect_rule_does_not_have_evidence_refs_field() -> None:
    """Per §B: EventEffectRule does not own evidence_refs. The dataclass
    must NOT have an evidence_refs field. Static rule identity cannot
    impersonate per-turn evidence lineage."""
    with pytest.raises(TypeError):
        EventEffectRule(
            event_kind="plan_cancelled",
            dimension="agent.affect.anxiety",
            base_amount=0.2,
            evidence_refs=("ev-1",),  # MUST raise — rule is not evidence authority
        )


def test_P3_per_turn_evidence_refs_come_from_candidate_not_rule() -> None:
    """Per §B / P3: different turns (different candidates) produce
    different evidence_refs in the longitudinal contribution. The rule
    itself does NOT carry evidence_refs; the per-turn evidence lineage
    is owned by the appraisal surface."""
    rule = EventEffectRule(
        event_kind="plan_cancelled",
        dimension="agent.affect.anxiety",
        base_amount=0.2,
        longitudinal_target_dimension="agent.slow.anxiety",
        longitudinal_proposed_value=0.8,
    )
    # Turn 1: candidate with evidence ref "ev-turn-1"
    cand1, appr1 = _candidate(appraisal_salience=0.95, evidence_refs=("ev-turn-1",))
    result1 = EffectMapper(rules=(rule,)).map(
        routing=_routing(cand1, appr1), history=None
    )
    # Turn 2: candidate with evidence ref "ev-turn-2"
    cand2, appr2 = _candidate(appraisal_salience=0.95, evidence_refs=("ev-turn-2", "ev-turn-2b"))
    result2 = EffectMapper(rules=(rule,)).map(
        routing=_routing(cand2, appr2), history=None
    )

    # P3: the longitudinal contribution's evidence_refs reflects per-turn
    # appraisal evidence, NOT a static rule.
    assert result1.evidence_refs_by_source["longitudinal:cand-1"] == ("ev-turn-1",)
    assert result2.evidence_refs_by_source["longitudinal:cand-1"] == (
        "ev-turn-2",
        "ev-turn-2b",
    )
    # P3: different turns produce different evidence lineage
    assert result1.evidence_refs_by_source != result2.evidence_refs_by_source


def test_P4_static_rule_id_does_not_impersonate_evidence() -> None:
    """Per §B / P4: a static rule identity (the dataclass itself) is
    configuration, not evidence. The rule must NOT have an evidence_refs
    field that could be confused with per-turn evidence lineage."""
    # Inspect the dataclass fields
    rule_fields = {
        f.name
        for f in EventEffectRule.__dataclass_fields__.values()
    }
    assert "evidence_refs" not in rule_fields, (
        f"§B/P4: EventEffectRule must not have evidence_refs field; "
        f"current fields: {rule_fields}"
    )


# ============================================================================
# §C — None ≠ 0.0: unavailable salience stays None
# ============================================================================


def test_M1_missing_salience_stays_none_through_authority_chain() -> None:
    """Per §C: unavailable salience is None throughout the upstream
    authority chain. None and 0.0 carry different meanings — None = not
    appraised, 0.0 = appraised-as-negligible. The cast `None → 0.0` is
    contractually required only at the very last step, where
    `CandidateStateDelta.salience: float` is non-Optional. The mapper
    must NOT substitute.
    """
    rule = EventEffectRule(
        event_kind="plan_cancelled",
        dimension="agent.affect.anxiety",
        base_amount=0.2,
        longitudinal_target_dimension="agent.slow.anxiety",
        longitudinal_proposed_value=0.8,
    )
    candidate, appraisals = _candidate(appraisal_salience=None, evidence_refs=())
    mapper = EffectMapper(rules=(rule,))
    result = mapper.map(routing=_routing(candidate, appraisals), history=None)

    # Per C10-SALIENCE-IMPL-R2: unavailable salience is None throughout the
    # upstream authority chain. The seam forwards None directly.
    assert result.salience_by_source["event:cand-1"] is None
    assert result.salience_by_source["longitudinal:cand-1"] is None
    # The gate's SalienceThresholdPolicy REJECTs None salience (never SLOW_ACCEPT).


def test_M2_missing_salience_does_not_slow_accept() -> None:
    """Per C10-SALIENCE-IMPL-R2 M2: when salience is None (not appraised),
    the gate must NOT disposition SLOW_ACCEPT. SalienceThresholdPolicy
    REJECTs None at the policy level. No slow state is written."""
    # Build a real transition path with missing salience (no appraisal in routing)
    from unittest.mock import MagicMock

    from mind_runtime.contracts.emotional_transition import (
        EmotionalTransitionInput,
    )
    from mind_runtime.dynamics.ports import EngineEmotionalTransitionPort

    rule = EventEffectRule(
        event_kind="plan_cancelled",
        dimension="agent.affect.anxiety",
        base_amount=0.2,
        longitudinal_target_dimension="agent.slow.anxiety",
        longitudinal_proposed_value=0.8,
    )
    gate = SalienceThresholdPolicy(
        config=FixedSalienceThresholdConfig(
            salience_floor_fast_apply=0.0,
            salience_floor_slow_accept=0.51,
            confidence_floor_slow=0.0,
        ),
    )
    # Candidate with an appraisal that carries salience=None (unavailable)
    cand, _appraisals = _candidate(appraisal_salience=None, evidence_refs=("ev-1",))
    # appraisal exists but with salience=None (the semantic we're testing)
    assert cand.candidate_id in _appraisals
    assert _appraisals[cand.candidate_id].salience is None

    # Build a mock router that returns a routing with the salience=None appraisal
    mock_routing = _routing(cand, _appraisals)
    mock_router = MagicMock()
    mock_router.route.return_value = mock_routing

    em = EngineEmotionalTransitionPort(
        engine=DynamicsEngine(
            persona=PersonaProfile(
                persona_id="kayla", dimensions=(_affect("agent.affect.anxiety"),)
            )
        ),
        runtime_id="runtime-1",
        effect_rules=(rule,),
        semantic_router=mock_router,
        homeostasis_gate=gate,
    )
    inp = EmotionalTransitionInput(
        interaction_id="t-1",
        scope=USER_SCOPE,
        origin_runtime_id="runtime-1",
        context=Situation(
            situation_id="s-1",
            scope=USER_SCOPE,
            origin_runtime_id="runtime-1",
            derived_facts=(),
            effective_state_ref="eff-1",
            observed_at=NOW,
            historical_context=None,
            persona_id="kayla",
            relationship_ids=(),
            evidence_refs=("ev-1",),
        ),
        current_affect=(),
        elapsed=__import__("datetime").timedelta(0),
        persona_id="kayla",
        persona_version=1,
        persona=(_affect("agent.affect.anxiety"),),
        observations=(),
        semantic_candidates=(cand,),
        history_context=None,
        clock=NOW,
        projection_scope=AGENT_SCOPE,
    )
    outcome = em.transition_with_gate(inp)

    # M2: the gate must NEVER disposition SLOW_ACCEPT for missing salience
    for d in outcome.slow_decisions:
        assert d.decision != HomeostasisDisposition.SLOW_ACCEPT, (
            f"M2: gate must not SLOW_ACCEPT for missing salience; "
            f"got decision={d.decision!r} for target={d.candidate.target_dimension!r}"
        )


# ============================================================================
# §D — Longitudinal target implementation is preserved (no rollback)
# ============================================================================


def test_S9_same_rule_different_appraisal_salience_produces_different_candidate_salience() -> None:
    """Per §D: longitudinal_target_dimension is preserved as configuration.
    Per §S9 / §A: the same rule with different appraisal salience
    produces different candidate salience in the longitudinal contribution.
    Salience is appraisal authority, not rule authority."""
    rule = EventEffectRule(
        event_kind="plan_cancelled",
        dimension="agent.affect.anxiety",
        base_amount=0.2,
        longitudinal_target_dimension="agent.slow.anxiety",
        longitudinal_proposed_value=0.8,
    )

    # Turn 1: appraisal assigns high salience
    cand_high, appr_high = _candidate(appraisal_salience=0.95)
    result_high = EffectMapper(rules=(rule,)).map(
        routing=_routing(cand_high, appr_high), history=None
    )

    # Turn 2: appraisal assigns low salience (different event)
    cand_low, appr_low = _candidate(appraisal_salience=0.20)
    result_low = EffectMapper(rules=(rule,)).map(
        routing=_routing(cand_low, appr_low), history=None
    )

    # S9: same rule, different appraisal salience → different candidate salience
    assert result_high.salience_by_source["longitudinal:cand-1"] == 0.95
    assert result_low.salience_by_source["longitudinal:cand-1"] == 0.20
    assert (
        result_high.salience_by_source["longitudinal:cand-1"]
        != result_low.salience_by_source["longitudinal:cand-1"]
    )


def test_S9_longitudinal_target_dimension_preserved() -> None:
    """Per §D: longitudinal_target_dimension implementation is preserved.
    The rule still owns the explicit longitudinal target declaration;
    no rollback to inference or affect-form fallback."""
    rule = EventEffectRule(
        event_kind="plan_cancelled",
        dimension="agent.affect.anxiety",
        base_amount=0.2,
        longitudinal_target_dimension="agent.slow.anxiety",
        longitudinal_proposed_value=0.8,
    )
    mapper = EffectMapper(rules=(rule,))
    cand, appr = _candidate()
    result = mapper.map(routing=_routing(cand, appr), history=None)

    # §D: longitudinal target is the exact configured dimension
    longitudinal_impulses = [
        i for i in result.impulses if i.source_ref.startswith("longitudinal:")
    ]
    assert len(longitudinal_impulses) == 1
    assert longitudinal_impulses[0].dimension == "agent.slow.anxiety"


# ============================================================================
# §E — Final production topology smoke check
# ============================================================================


def test_E_impulse_never_carries_salience_or_evidence_refs() -> None:
    """Per §E: Impulse does not carry salience/evidence_refs. The mapper's
    data surface is a separate per-source table (`salience_by_source` /
    `evidence_refs_by_source`), populated from the appraisal surface.

    This enforces the architectural rule: rule/engine/mapper emit
    `Impulse` and `Contribution`; appraisal surface (via `MappedEffects`)
    carries authority values. No authority laundering via Impulse fields.
    """
    imp_fields = {f.name for f in Impulse.__dataclass_fields__.values()}
    assert "salience" not in imp_fields, (
        f"§E: Impulse must not carry salience; fields={imp_fields}"
    )
    assert "evidence_refs" not in imp_fields, (
        f"§E: Impulse must not carry evidence_refs; fields={imp_fields}"
    )

    contrib_fields = {f.name for f in Contribution.__dataclass_fields__.values()}
    assert "salience" not in contrib_fields, (
        f"§E: Contribution must not carry salience; fields={contrib_fields}"
    )
    assert "evidence_refs" not in contrib_fields, (
        f"§E: Contribution must not carry evidence_refs; fields={contrib_fields}"
    )


def test_E_audit_contribution_confidence_is_required() -> None:
    """Per C10-ASSESSMENT-CONFIDENCE-SCHEMA: AssessmentContribution.confidence
    is float | None. None is the structural 'no upstream authority for this
    row' signal (R3 §7 frozen: recovery / coupling / relationship have no
    confidence column). The audit must honestly reflect this absence, not
    fabricate a value.
    """
    from mind_runtime.contracts.emotional_transition import (
        AssessmentContribution,
    )

    # confidence=None is valid for non-impulse rows (recovery, coupling,
    # relationship). Per R3 §7 these kinds have no upstream confidence.
    contrib_none = AssessmentContribution(
        dimension="agent.affect.anxiety",
        source_kind="recovery",
        source_ref="recovery",
        amount=0.1,
        confidence=None,
        applied=True,
        reason_code=None,
    )
    assert contrib_none.confidence is None

    # Valid construction with float confidence works (impulse rows)
    contrib_float = AssessmentContribution(
        dimension="agent.affect.anxiety",
        source_kind="event",
        source_ref="ev-1",
        amount=0.2,
        confidence=0.85,
        applied=True,
        reason_code=None,
    )
    assert contrib_float.confidence == 0.85

    # Invalid: confidence must be in [0, 1] or None
    with pytest.raises((TypeError, ValueError)):
        AssessmentContribution(
            dimension="agent.affect.anxiety",
            source_kind="event",
            source_ref="ev-1",
            amount=0.2,
            confidence=-0.1,
            applied=True,
            reason_code=None,
        )


# ============================================================================
# Sanity: source-level audit (no synthetic fallback patterns)
# ============================================================================


def test_E_no_salience_equals_confidence_heuristic_in_source() -> None:
    """AST scan: ports.py must not contain `salience = confidence` heuristic
    in executable code (excluding comments)."""
    import ast

    from mind_runtime.dynamics import ports

    source = inspect.getsource(ports)
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "salience":
                    value_repr = ast.unparse(node.value).strip()
                    assert value_repr != "confidence", (
                        f"salience = confidence heuristic found in executable code"
                    )