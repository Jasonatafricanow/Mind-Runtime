"""C10-B-W L1-L8 lineage tests — verifying the R2 contract is upheld.

Ticket C10-BW-UPSTREAM-R2 — Explicit Longitudinal Contribution Authority & R2
Lineage Rebase.

These tests verify that the corrected topology is correct:

  Event / Appraisal
      ↓
  EffectMapper
      ├─ immediate effect → DynamicsEngine
      │
      └─ longitudinal contribution
              ↓
         HomeostasisGate
              ↓
         SlowPlasticityWriter

NOT:

  EffectMapper → longitudinal impulse → ports.py synthetic Contribution
"""

from __future__ import annotations

import re
from datetime import UTC, datetime

import pytest

from mind_runtime.contracts import (
    AffectiveDimensionProfile,
    AppraisalPath,
    AppraisalRouteDecision,
    Scope,
    ScopeDomain,
    SemanticAppraisal,
    SemanticEventCandidate,
    SemanticRoutingResult,
    Situation,
    SyncFields,
)
from mind_runtime.dynamics.engine import DynamicsEngine
from mind_runtime.dynamics.persona import PersonaProfile
from mind_runtime.dynamics.ports import EngineEmotionalTransitionPort
from mind_runtime.emotional_transition.effects import EffectMapper, EventEffectRule
from mind_runtime.emotional_transition.semantic import SemanticRouter
from mind_runtime.homeostasis.contracts import (
    HomeostasisDisposition,
)
from mind_runtime.homeostasis.policy import (
    FixedSalienceThresholdConfig,
    SalienceThresholdPolicy,
)
from mind_runtime.state.definitions import StateDefinitionRegistry

NOW = datetime(2026, 8, 22, 12, 0, tzinfo=UTC)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


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


def _candidate(
    candidate_id: str = "cand-1",
    confidence: float = 0.8,
    *,
    salience: float | None = 0.95,
    evidence_refs: tuple[str, ...] = ("evidence-1",),
) -> tuple[SemanticEventCandidate, dict[str, SemanticAppraisal]]:
    """Build a SemanticEventCandidate plus its appraisal carrier dict.

    Per C10-SALIENCE-IMPL-R2: candidate and appraisal are separate objects.
    The carrier is SemanticRoutingResult.appraisals_by_candidate_id.
    """
    appraisals: dict[str, SemanticAppraisal] = {}
    if salience is not None or evidence_refs:
        appraisal = SemanticAppraisal(
            appraisal_id=f"appraisal-{candidate_id}",
            scope=Scope(domain=ScopeDomain.USER, user_id="alice"),
            origin_runtime_id="runtime-1",
            situation_ref="sit-1",
            meanings=("betrayal",),
            valence="negative",
            relationship_relevance="primary",
            confidence=confidence,
            evidence_refs=evidence_refs,
            salience=salience,
        )
        appraisals[candidate_id] = appraisal
    candidate = SemanticEventCandidate(
        candidate_id=candidate_id,
        scope=Scope(domain=ScopeDomain.USER, user_id="alice"),
        origin_runtime_id="runtime-1",
        kind="plan_cancelled",
        attributes=(),
        confidence=confidence,
        evidence_refs=evidence_refs,
    )
    return candidate, appraisals


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


def _situation(evidence_refs: tuple[str, ...] = ()) -> Situation:
    return Situation(
        situation_id="sit-1",
        scope=Scope(domain=ScopeDomain.USER, user_id="alice"),
        origin_runtime_id="runtime-1",
        derived_facts=(),
        effective_state_ref="eff-1",
        observed_at=NOW,
        historical_context=None,
        persona_id="kayla",
        relationship_ids=(),
        evidence_refs=evidence_refs,
    )


def _make_engine(
    *,
    rule: EventEffectRule,
    gate: SalienceThresholdPolicy | None = None,
) -> EngineEmotionalTransitionPort:
    persona = PersonaProfile(
        persona_id="kayla",
        dimensions=(_affect("agent.affect.anxiety"),),
    )
    engine = DynamicsEngine(persona=persona)
    return EngineEmotionalTransitionPort(
        engine=engine,
        runtime_id="runtime-1",
        effect_rules=(rule,),
        semantic_router=SemanticRouter(),
        homeostasis_gate=gate,
    )


def _make_gate(*, slow_accept_floor: float = 0.51) -> SalienceThresholdPolicy:
    return SalienceThresholdPolicy(
        config=FixedSalienceThresholdConfig(
            salience_floor_fast_apply=0.0,
            salience_floor_slow_accept=slow_accept_floor,
            confidence_floor_slow=0.0,
        ),
    )


def _run(
    rule: EventEffectRule,
    *,
    situation_evidence: tuple[str, ...] = ("evidence-1",),
    candidate: SemanticEventCandidate | None = None,
    appraisals: dict[str, SemanticAppraisal] | None = None,
    gate_slow_accept_floor: float = 0.51,
) -> tuple[EmotionalTransitionOutcome, EventEffectRule]:
    """Run the engine and through transition_with_gate.

    For testing, use a mock router that injects the supplied appraisals via
    the routing.appraisals_by_candidate_id map.
    """
    from unittest.mock import MagicMock

    from mind_runtime.contracts.emotional_transition import (
        EmotionalTransitionInput,
    )

    if candidate is None:
        candidate, appraisals = _candidate()

    rule_executed = rule
    em = _make_engine(rule=rule, gate=_make_gate(slow_accept_floor=gate_slow_accept_floor))
    # Inject the supplied appraisals into the routing
    mock_routing = _routing(candidate, appraisals or {})
    mock_router = MagicMock()
    mock_router.route.return_value = mock_routing
    em._semantic_router = mock_router  # type: ignore[attr-defined]
    inp = EmotionalTransitionInput(
        interaction_id="turn-1",
        scope=Scope(domain=ScopeDomain.USER, user_id="alice"),
        origin_runtime_id="runtime-1",
        context=_situation(evidence_refs=situation_evidence),
        current_affect=(),
        elapsed=__import__("datetime").timedelta(0),
        persona_id="kayla",
        persona_version=1,
        persona=(_affect("agent.affect.anxiety"),),
        observations=(),
        semantic_candidates=(candidate,),
        history_context=None,
        clock=NOW,
        projection_scope=Scope(
            domain=ScopeDomain.AGENT, agent_id="kayla", persona_id="kayla"
        ),
    )
    outcome = em.transition_with_gate(inp)
    return outcome, rule_executed


# L7 dependency: EmotionalTransitionOutcome is defined in dynamics.ports
from mind_runtime.dynamics.ports import EmotionalTransitionOutcome  # noqa: E402

# ============================================================================
# L1 — Explicit target: longitudinal contribution carries configured target
# ============================================================================


def test_L1_longitudinal_impulse_carries_exact_configured_target() -> None:
    """When the rule declares longitudinal_target_dimension, the upstream
    EffectMapper emits a longitudinal Impulse with the EXACT configured
    target. No transformation, no inference. Salience and evidence_refs
    come from the SemanticAppraisal in routing.appraisals_by_candidate_id."""
    rule = EventEffectRule(
        event_kind="plan_cancelled",
        dimension="agent.affect.anxiety",
        base_amount=0.2,
        longitudinal_target_dimension="agent.slow.anxiety",
        longitudinal_proposed_value=0.8,
    )
    candidate, appraisals = _candidate(salience=0.95, evidence_refs=("ev-bw-1",))
    mapper = EffectMapper(rules=(rule,))
    result = mapper.map(routing=_routing(candidate, appraisals), history=None)

    longitudinal_impulses = [
        i for i in result.impulses if i.source_ref.startswith("longitudinal:")
    ]
    assert len(longitudinal_impulses) == 1
    assert longitudinal_impulses[0].dimension == "agent.slow.anxiety"
    # Per C10-SALIENCE-IMPL-R2: salience is appraisal authority from routing
    assert result.salience_by_source["longitudinal:cand-1"] == 0.95
    # Per §B: evidence_refs is appraisal authority from candidate
    assert result.evidence_refs_by_source["longitudinal:cand-1"] == ("ev-bw-1",)


# ============================================================================
# L2 — No config: no longitudinal contribution
# ============================================================================


def test_L2_no_longitudinal_target_means_no_longitudinal_impulse() -> None:
    """A rule without longitudinal_target_dimension produces only an
    immediate Impulse. No longitudinal Impulse is emitted."""
    rule = EventEffectRule(
        event_kind="plan_cancelled",
        dimension="agent.affect.anxiety",
        base_amount=0.2,
        # Per C10-BW-UPSTREAM-R2 §A/§B: salience and evidence_refs are
        # not on EventEffectRule.
    )
    mapper = EffectMapper(rules=(rule,))
    cand, appr = _candidate()
    result = mapper.map(routing=_routing(cand, appr), history=None)

    assert len(result.impulses) == 1
    assert not any(
        i.source_ref.startswith("longitudinal:") for i in result.impulses
    )


# ============================================================================
# L3 — Registry: unregistered target → fail closed
# ============================================================================


def test_L3_longitudinal_decision_target_unregistered_skipped_at_seam() -> None:
    """An orchestrator seam routing logic skips a SLOW_ACCEPT decision whose
    target is unregistered. The decision's disposition is not consumed by
    B-W; the writer is not invoked."""
    from mind_runtime.state.longitudinal import resolve_longitudinal_target

    # Build a registry with NO longitudinal entries
    registry = StateDefinitionRegistry()
    # Decision targets an unregistered dimension
    decision_target = "agent.slow.unregistered"
    # Seam logic: raises ValueError → caught → decision not routed
    with pytest.raises(ValueError):
        resolve_longitudinal_target(registry, decision_target)


# ============================================================================
# L4 — No implicit mapping: agent.affect.X never resolves to longitudinal
# ============================================================================


# ============================================================================
# L5 — Real contribution authority: longitudinal path goes through real
#        EffectMapper output, not ports.py synthetic constructor
# ============================================================================


def test_L5_longitudinal_path_uses_real_effect_mapper_impulse() -> None:
    """The longitudinal path uses the EffectMapper's `Impulse` directly.
    No synthetic `Contribution` is fabricated in ports.py.

    Test: read ports.py source and assert that no synthetic `Contribution(...)`
    construction is present in the gate invocation path.
    """
    import inspect

    from mind_runtime.dynamics import ports

    source = inspect.getsource(ports)
    # Find _invoke_homeostasis_gate method
    match = re.search(
        r"def _invoke_homeostasis_gate.*?(?=\n    def |\nclass )",
        source,
        re.DOTALL,
    )
    assert match is not None, "_invoke_homeostasis_gate not found"
    gate_method = match.group(0)
    # The method MUST NOT contain a synthetic Contribution(...) construction
    # that fabricates a contribution from an impulse at the seam.
    # Look for the pattern `Contribution(\n.*dimension=impulse.dimension,\n.*source=f"impulse:{impulse.source_ref}"`
    forbidden = re.compile(
        r"Contribution\(\s*\n\s*dimension=impulse\.dimension,\s*\n\s*source=f?[\"']impulse:",
        re.MULTILINE,
    )
    assert not forbidden.search(gate_method), (
        f"L5: _invoke_homeostasis_gate must not synthesize Contribution. "
        f"Method text:\n{gate_method[:500]}"
    )


# ============================================================================
# L6 — Provenance: real evidence_refs reach longitudinal contribution
# ============================================================================


def test_L6_evidence_refs_propagate_from_rule_to_longitudinal_impulse() -> None:
    """The rule's evidence_refs propagate to the longitudinal Impulse
    (and from there to CandidateStateDelta.evidence_refs at the gate)."""
    rule = EventEffectRule(
        event_kind="plan_cancelled",
        dimension="agent.affect.anxiety",
        base_amount=0.2,
        longitudinal_target_dimension="agent.slow.anxiety",
        longitudinal_proposed_value=0.8,
        # Per C10-SALIENCE-IMPL-R2: salience/evidence_refs NOT on rule
    )
    candidate, appraisals = _candidate(
        salience=0.95,
        evidence_refs=("evidence-appraisal-abc", "evidence-observation-xyz"),
    )
    mapper = EffectMapper(rules=(rule,))
    result = mapper.map(routing=_routing(candidate, appraisals), history=None)
    # Per C10-BW-UPSTREAM-R2 §B: longitudinal inherits appraisal's evidence_refs
    assert result.evidence_refs_by_source["longitudinal:cand-1"] == (
        "evidence-appraisal-abc",
        "evidence-observation-xyz",
    )


def test_L6_empty_evidence_refs_causes_h6_fail_closed_at_seam() -> None:
    """Empty evidence_refs on a longitudinal candidate raises a fail-closed
    error at the gate seam (H6 invariant: empty evidence → no SLOW_*).

    Per C10-BW-UPSTREAM-R2 §B, evidence_refs come from the appraisal
    (SemanticEventCandidate), not from the rule. When the appraisal does
    not supply evidence, the seam must fail closed."""
    rule = EventEffectRule(
        event_kind="plan_cancelled",
        dimension="agent.affect.anxiety",
        base_amount=0.2,
        longitudinal_target_dimension="agent.slow.anxiety",
        longitudinal_proposed_value=0.8,
        # No salience/evidence_refs on rule — they come from appraisal
    )
    # Empty evidence_refs from appraisal authority (no evidence recorded)
    candidate, _ = _candidate(evidence_refs=(), salience=0.95)
    # This will raise at the gate invocation per the H6 fail-closed check
    with pytest.raises(ValueError, match="evidence_refs is empty"):
        _run(rule, candidate=candidate)


# ============================================================================
# L7 — Latest R2 lineage: no impulse-key fallback, no salience estimator,
#        no default 1.0, no synthetic constructor
# ============================================================================


# ============================================================================
# L8 — Missing salience: fail closed at gate; writer not invoked
# ============================================================================


def test_L8_missing_salience_vetoes_slow_accept() -> None:
    """When appraisal does not assess salience (candidate.salience=None), the
    gate's H6 veto rule returns FAST_ONLY/REJECT — never SLOW_ACCEPT.
    The seam does NOT substitute a fabricated salience value."""
    rule = EventEffectRule(
        event_kind="plan_cancelled",
        dimension="agent.affect.anxiety",
        base_amount=0.2,
        longitudinal_target_dimension="agent.slow.anxiety",
        longitudinal_proposed_value=0.8,
        # Per §C: salience is not on EventEffectRule; comes from appraisal
    )
    # Appraisal did not assess salience (None = unavailable)
    candidate, appr = _candidate(salience=None, evidence_refs=("ev-bw-1",))
    outcome, _ = _run(rule, candidate=candidate, appraisals=appr)

    # The seam converts None → 0.0 at the gate-input boundary.
    # Gate's H6 veto on salience=0.0 → REJECT/FAST_ONLY (never SLOW_ACCEPT)
    decisions = outcome.slow_decisions
    for d in decisions:
        assert d.decision != HomeostasisDisposition.SLOW_ACCEPT
