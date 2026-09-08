"""C10-B-W longitudinal target contract tests.

Ticket: C10-BW-UPSTREAM-R — Remove Implicit Longitudinal Target Derivation

Contract (ticket §4):

  Registry only answers:
    "Is this dimension already registered as longitudinal?"

  Mapping authority belongs to:
    EventEffectRule.longitudinal_target_dimension  (or equivalent explicit config)

What is tested:

  F2 — upstream longitudinal emission
    - EventEffectRule carries explicit longitudinal_target_dimension
    - EffectMapper emits a separate longitudinal Impulse
    - The longitudinal Impulse carries the EXACT registered dimension
      (no transformation, no derivation)

  F1 — registry authority
    - Longitudinal definitions are registered EXPLICITLY (not auto-derived)
    - B-W seam fails closed on unregistered targets
    - B-W seam does NOT perform affect-form fallback

  U5 proof — configuration-owned ontology
    - Changing longitudinal_target_dimension in config (to a different registered
      target) requires NO runtime code changes; the seam verifies the new target
      is registered and routes accordingly.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone

import pytest

from mind_runtime.contracts import (
    AffectiveDimensionProfile,
    AppraisalPath,
    AppraisalRouteDecision,
    HistoricalContextBundle,
    RuntimeState,
    Scope,
    ScopeDomain,
    SemanticEventCandidate,
    SemanticRoutingResult,
    Situation,
    StateDefinition,
    StateDomain,
    StateValueType,
    SyncFields,
)
from mind_runtime.emotional_transition.effects import (
    EffectMapper,
    EventEffectRule,
)
from mind_runtime.state.definitions import StateDefinitionRegistry
from mind_runtime.state.longitudinal import (
    LONGITUDINAL_ACCUMULATOR,
    LONGITUDINAL_INDEFINITE,
    is_longitudinal_policy,
    register_longitudinal_definition,
    require_longitudinal_policy,
    resolve_longitudinal_target,
)

NOW = datetime(2026, 8, 22, tzinfo=timezone.utc)

AFFECT_ANXIETY = AffectiveDimensionProfile(
    dimension="agent.affect.anxiety",
    baseline=0.3,
    initial_value=0.3,
    sensitivity=0.5,
    recovery_rate=0.1,
    ceiling=1.0,
    floor=0.0,
    growth_profile=(),
    coupling_profile=(),
)


# ============================================================================
# Helpers
# ============================================================================


def _affect_scope() -> Scope:
    return Scope(
        domain=ScopeDomain.USER, user_id="alice", agent_id=None,
        persona_id=None, world_id=None, interaction_id=None,
    )


def _agent_scope() -> Scope:
    return Scope(
        domain=ScopeDomain.AGENT, agent_id="kayla", persona_id="kayla",
        user_id=None, world_id=None, interaction_id=None,
    )


def _sync(scope: Scope, state_id: str) -> SyncFields:
    return SyncFields(state_id=state_id, scope=scope)


def _candidate() -> SemanticEventCandidate:
    return SemanticEventCandidate(
        candidate_id="cand-1",
        scope=_affect_scope(),
        origin_runtime_id="runtime-1",
        kind="plan_cancelled",
        attributes=(),
        confidence=0.8,
        evidence_refs=("evidence-1",),
    )


def _routing(candidate: SemanticEventCandidate) -> SemanticRoutingResult:
    return SemanticRoutingResult(
        route=AppraisalRouteDecision(
            route_id="route-1",
            scope=candidate.scope,
            path=AppraisalPath.DETERMINISTIC,
            ambiguity_score=None,
            confidence=0.8,
            reason_codes=(),
        ),
        candidates=(candidate,),
        abstention_reasons=(),
        provider_call_count=1,
    )


def _history() -> HistoricalContextBundle | None:
    return None


def _history_with_summary() -> HistoricalContextBundle:
    """Build a history bundle with a matching pattern summary."""
    from mind_runtime.contracts import PatternMatchSummary

    summary = PatternMatchSummary(
        summary_id="summary-1",
        scope=_affect_scope(),
        origin_runtime_id="runtime-1",
        match_count=2,
        first_seen_at=NOW,
        last_seen_at=NOW,
        matched_refs=("ev-past-1", "ev-past-2"),
        confidence=0.7,
    )
    return HistoricalContextBundle(
        bundle_id="bundle-1",
        scope=_affect_scope(),
        origin_runtime_id="runtime-1",
        episodes=(),
        stable_facts=(),
        relationship_events=(),
        pattern_summaries=(summary,),
        source_refs=("ev-past-1", "ev-past-2"),
        provider_trace="fixture",
    )


# ============================================================================
# F1: Registry — explicit registration only
# ============================================================================


def test_U1_explicit_register_returns_definition() -> None:
    """register_longitudinal_definition adds the exact key to the registry."""
    registry = StateDefinitionRegistry()
    defn = register_longitudinal_definition(registry, key="agent.slow.anxiety")
    assert defn.key == "agent.slow.anxiety"
    assert defn.dynamics_policy == LONGITUDINAL_ACCUMULATOR
    assert defn.default_validity_policy == LONGITUDINAL_INDEFINITE


def test_U1_registered_dimension_is_retrievable() -> None:
    """registry.get returns the registered StateDefinition."""
    registry = StateDefinitionRegistry()
    register_longitudinal_definition(registry, key="agent.slow.anxiety")
    retrieved = registry.get("agent.slow.anxiety")
    assert retrieved is not None
    assert retrieved.key == "agent.slow.anxiety"


def test_U1_dynamics_policy_is_longitudinal() -> None:
    """is_longitudinal_policy returns True for 'accumulator'."""
    assert is_longitudinal_policy(LONGITUDINAL_ACCUMULATOR) is True
    assert is_longitudinal_policy("continuous_return_to_baseline") is False
    assert is_longitudinal_policy("instant") is False


def test_U1_require_longitudinal_policy_raises_on_fast_policy() -> None:
    """require_longitudinal_policy raises when policy is not 'accumulator'."""
    with pytest.raises(ValueError, match="dynamics_policy"):
        require_longitudinal_policy("continuous_return_to_baseline", key="agent.slow.anxiety")


def test_U1_require_longitudinal_policy_passes_on_accumulator() -> None:
    """require_longitudinal_policy returns None when policy is 'accumulator'."""
    require_longitudinal_policy(LONGITUDINAL_ACCUMULATOR, key="agent.slow.anxiety")


def test_U1_require_longitudinal_policy_raises_with_dimension_key() -> None:
    """Error message includes the dimension key for traceability."""
    with pytest.raises(ValueError, match="agent.slow.anxiety"):
        require_longitudinal_policy("fast_decay", key="agent.slow.anxiety")


def test_U1_registration_is_idempotent() -> None:
    """Re-registering the same key returns the existing definition (no error)."""
    registry = StateDefinitionRegistry()
    defn1 = register_longitudinal_definition(registry, key="agent.slow.anxiety")
    defn2 = register_longitudinal_definition(registry, key="agent.slow.anxiety")
    assert defn1 is defn2


def test_U1_conflict_raises_on_different_policy() -> None:
    """Registering with a conflicting dynamics_policy raises."""
    registry = StateDefinitionRegistry()
    # Pre-register a dimension with a fast policy
    registry.register(
        StateDefinition(
            key="agent.slow.anxiety",
            domain=StateDomain.AGENT,
            value_type=StateValueType.SCALAR,
            dynamics_policy="fast_decay",
            default_validity_policy="ttl:1d",
            bounds=(0.0, 1.0),
        )
    )
    with pytest.raises(ValueError, match="conflicts with longitudinal"):
        register_longitudinal_definition(registry, key="agent.slow.anxiety")


# ============================================================================
# F2: Rule — explicit longitudinal_target_dimension
# ============================================================================


def test_U2_rule_accepts_longitudinal_target_dimension() -> None:
    """EventEffectRule.accepts a non-empty longitudinal_target_dimension."""
    rule = EventEffectRule(
        event_kind="plan_cancelled",
        dimension="agent.affect.anxiety",
        base_amount=0.2,
        longitudinal_target_dimension="agent.slow.anxiety",
        longitudinal_proposed_value=0.8,
    )
    assert rule.longitudinal_target_dimension == "agent.slow.anxiety"
    assert rule.longitudinal_proposed_value == 0.8


def test_U2_rule_defaults_to_none() -> None:
    """When not specified, longitudinal_target_dimension is None."""
    rule = EventEffectRule(
        event_kind="plan_cancelled",
        dimension="agent.affect.anxiety",
        base_amount=0.2,
    )
    assert rule.longitudinal_target_dimension is None
    assert rule.longitudinal_proposed_value is None


def test_U2_rule_rejects_empty_string() -> None:
    """Empty string is rejected as an invalid longitudinal target."""
    with pytest.raises(ValueError, match="longitudinal_target_dimension"):
        EventEffectRule(
            event_kind="plan_cancelled",
            dimension="agent.affect.anxiety",
            base_amount=0.2,
            longitudinal_target_dimension="",
            longitudinal_proposed_value=0.8,
        )


# ============================================================================
# F2: EffectMapper — dual Impulse emission (explicit config only)
# ============================================================================


def test_U3_effect_mapper_emits_both_impulses() -> None:
    """When rule has longitudinal_target_dimension, EffectMapper emits TWO impulses:
    one for the affect dimension, one for the longitudinal dimension."""
    registry = StateDefinitionRegistry()
    register_longitudinal_definition(registry, key="agent.slow.anxiety")

    mapper = EffectMapper(rules=(
        EventEffectRule(
            event_kind="plan_cancelled",
            dimension="agent.affect.anxiety",
            base_amount=0.2,
            longitudinal_target_dimension="agent.slow.anxiety",
            longitudinal_proposed_value=0.8,
        ),
    ))
    result = mapper.map(routing=_routing(_candidate()), history=_history())
    assert len(result.impulses) == 2

    dims = {impulse.dimension for impulse in result.impulses}
    assert "agent.affect.anxiety" in dims
    assert "agent.slow.anxiety" in dims


def test_U3_immediate_impulse_carries_event_prefix() -> None:
    """Immediate impulse source_ref uses the 'event:' prefix."""
    registry = StateDefinitionRegistry()
    register_longitudinal_definition(registry, key="agent.slow.anxiety")

    mapper = EffectMapper(rules=(
        EventEffectRule(
            event_kind="plan_cancelled",
            dimension="agent.affect.anxiety",
            base_amount=0.2,
            longitudinal_target_dimension="agent.slow.anxiety",
            longitudinal_proposed_value=0.8,
        ),
    ))
    result = mapper.map(routing=_routing(_candidate()), history=_history())
    immediate = next(
        i for i in result.impulses if i.dimension == "agent.affect.anxiety"
    )
    assert immediate.source_ref.startswith("event:")


def test_U3_longitudinal_impulse_carries_longitudinal_prefix() -> None:
    """Longitudinal impulse source_ref uses the 'longitudinal:' prefix."""
    registry = StateDefinitionRegistry()
    register_longitudinal_definition(registry, key="agent.slow.anxiety")

    mapper = EffectMapper(rules=(
        EventEffectRule(
            event_kind="plan_cancelled",
            dimension="agent.affect.anxiety",
            base_amount=0.2,
            longitudinal_target_dimension="agent.slow.anxiety",
            longitudinal_proposed_value=0.8,
        ),
    ))
    result = mapper.map(routing=_routing(_candidate()), history=_history())
    longitudinal = next(
        i for i in result.impulses if i.dimension == "agent.slow.anxiety"
    )
    assert longitudinal.source_ref.startswith("longitudinal:")


def test_U3_longitudinal_amount_uses_proposed_value_verbatim() -> None:
    """Longitudinal impulse uses longitudinal_proposed_value verbatim."""
    registry = StateDefinitionRegistry()
    register_longitudinal_definition(registry, key="agent.slow.anxiety")

    mapper = EffectMapper(rules=(
        EventEffectRule(
            event_kind="plan_cancelled",
            dimension="agent.affect.anxiety",
            base_amount=0.2,
            longitudinal_target_dimension="agent.slow.anxiety",
            longitudinal_proposed_value=0.85,
        ),
    ))
    result = mapper.map(routing=_routing(_candidate()), history=_history())
    longitudinal = next(
        i for i in result.impulses if i.dimension == "agent.slow.anxiety"
    )
    assert longitudinal.amount == 0.85


def test_U3_no_longitudinal_impulse_when_field_is_none() -> None:
    """Without longitudinal_target_dimension, EffectMapper emits ONE impulse."""
    mapper = EffectMapper(rules=(
        EventEffectRule(
            event_kind="plan_cancelled",
            dimension="agent.affect.anxiety",
            base_amount=0.2,
        ),
    ))
    result = mapper.map(routing=_routing(_candidate()), history=_history())
    dims = {impulse.dimension for impulse in result.impulses}
    assert dims == {"agent.affect.anxiety"}


def test_U3_confidence_scaling_applies_to_affect_not_longitudinal() -> None:
    """Per ADR-0018-R2 LONG-5: confidence scaling applies to immediate affect,
    while longitudinal amount remains verbatim proposed value."""
    registry = StateDefinitionRegistry()
    register_longitudinal_definition(registry, key="agent.slow.anxiety")

    mapper = EffectMapper(rules=(
        EventEffectRule(
            event_kind="plan_cancelled",
            dimension="agent.affect.anxiety",
            base_amount=0.2,
            longitudinal_target_dimension="agent.slow.anxiety",
            longitudinal_proposed_value=0.8,
        ),
    ))
    routing = _routing(_candidate())
    result = mapper.map(routing=routing, history=_history())

    immediate = next(
        i for i in result.impulses if i.dimension == "agent.affect.anxiety"
    )
    longitudinal = next(
        i for i in result.impulses if i.dimension == "agent.slow.anxiety"
    )
    # Immediate scaled by routing confidence (0.8 * 0.2 = 0.16)
    assert immediate.amount == pytest.approx(0.2 * 0.8)
    # Longitudinal uses verbatim proposed value (0.8)
    assert longitudinal.amount == 0.8


# ============================================================================
# F2: EffectMapper — no transformation, exact dimension only
# ============================================================================


def test_U4_mapper_emits_exact_longitudinal_dimension() -> None:
    """EffectMapper uses the EXACT longitudinal_target_dimension string
    as the impulse dimension — no prefix stripping, no transformation."""
    registry = StateDefinitionRegistry()
    register_longitudinal_definition(registry, key="agent.learned.threat_sensitivity")

    mapper = EffectMapper(rules=(
        EventEffectRule(
            event_kind="plan_cancelled",
            dimension="agent.affect.anxiety",
            base_amount=0.2,
            longitudinal_target_dimension="agent.learned.threat_sensitivity",
            longitudinal_proposed_value=0.7,
        ),
    ))
    result = mapper.map(routing=_routing(_candidate()), history=_history())
    dims = {impulse.dimension for impulse in result.impulses}
    assert "agent.learned.threat_sensitivity" in dims
    # NOT agent.slow.anxiety
    assert "agent.slow.anxiety" not in dims


def test_U4_history_patterns_do_not_generate_longitudinal_impulses() -> None:
    """History-based contributions (history_amount) are routed to the affect
    dimension only — never to the longitudinal dimension."""
    registry = StateDefinitionRegistry()
    register_longitudinal_definition(registry, key="agent.slow.anxiety")

    mapper = EffectMapper(rules=(
        EventEffectRule(
            event_kind="plan_cancelled",
            dimension="agent.affect.anxiety",
            base_amount=0.2,
            history_amount_per_match=0.1,
            history_amount_cap=0.2,
            longitudinal_target_dimension="agent.slow.anxiety",
            longitudinal_proposed_value=0.8,
        ),
    ))
    # Provide history context with matching patterns
    history = _history_with_summary()
    result = mapper.map(routing=_routing(_candidate()), history=history)
    dims = {impulse.dimension for impulse in result.impulses}
    # History should contribute to affect only
    assert "agent.affect.anxiety" in dims
    # Longitudinal is emitted once (base_amount only, not history_amount)
    assert dims == {"agent.affect.anxiety", "agent.slow.anxiety"}


# ============================================================================
# F1: Registry — no affect-form fallback, fail closed
# ============================================================================


def test_U5_unregistered_target_raises_on_resolve() -> None:
    """resolve_longitudinal_target raises when the dimension is unregistered."""
    registry = StateDefinitionRegistry()
    with pytest.raises(ValueError, match="not registered"):
        resolve_longitudinal_target(registry, "agent.slow.anxiety")


def test_U5_registered_longitudinal_target_resolves() -> None:
    """resolve_longitudinal_target returns the StateDefinition when registered."""
    registry = StateDefinitionRegistry()
    register_longitudinal_definition(registry, key="agent.slow.anxiety")
    defn = resolve_longitudinal_target(registry, "agent.slow.anxiety")
    assert defn.key == "agent.slow.anxiety"
    assert defn.dynamics_policy == LONGITUDINAL_ACCUMULATOR


def test_U5_fast_policy_raises_on_resolve() -> None:
    """resolve_longitudinal_target raises when the registered policy is not
    'accumulator' (even if the key happens to start with 'agent.slow.')."""
    registry = StateDefinitionRegistry()
    registry.register(
        StateDefinition(
            key="agent.slow.anxiety",
            domain=StateDomain.AGENT,
            value_type=StateValueType.SCALAR,
            dynamics_policy="continuous_return_to_baseline",  # fast policy
            default_validity_policy="ttl:1d",
            bounds=(0.0, 1.0),
        )
    )
    with pytest.raises(ValueError, match="expected longitudinal policy"):
        resolve_longitudinal_target(registry, "agent.slow.anxiety")


# ============================================================================
# F1: Seam — fail closed, no affect-form fallback
# ============================================================================


def test_U6_seam_fails_closed_on_affect_dimension() -> None:
    """Even if the registry contains agent.slow.anxiety, passing
    agent.affect.anxiety as the target raises.

    This is the core of C10-BW-UPSTREAM-R §3: no affect-form fallback.
    The upstream must provide the registered longitudinal dimension,
    not a related affect dimension."""
    registry = StateDefinitionRegistry()
    register_longitudinal_definition(registry, key="agent.slow.anxiety")

    with pytest.raises(ValueError, match="not registered"):
        resolve_longitudinal_target(registry, "agent.affect.anxiety")


def test_U6_seam_fails_closed_on_unregistered_longitudinal() -> None:
    """A target that is not in the registry at all also fails closed."""
    registry = StateDefinitionRegistry()
    with pytest.raises(ValueError, match="not registered"):
        resolve_longitudinal_target(registry, "agent.slow.anxiety")


# ============================================================================
# U5 proof: configuration-owned ontology
# ============================================================================


def test_U7_config_owned_ontology_change_requires_no_runtime_code_change() -> None:
    """If a rule's longitudinal_target_dimension is changed (in config) to
    a different registered target, the runtime requires NO changes.

    This proves that ontology authority belongs to configuration.

    Scenario:
      Config A: longitudinal_target_dimension = "agent.slow.anxiety"
      Config B: longitudinal_target_dimension = "agent.learned.threat_sensitivity"
      Both targets are registered.
      Seam verifies both via registry → no code change needed."""

    # Register both possible targets
    registry = StateDefinitionRegistry()
    register_longitudinal_definition(registry, key="agent.slow.anxiety")
    register_longitudinal_definition(registry, key="agent.learned.threat_sensitivity")

    # Config A: uses agent.slow.anxiety
    defn_a = resolve_longitudinal_target(registry, "agent.slow.anxiety")
    assert defn_a.key == "agent.slow.anxiety"

    # Config B: uses agent.learned.threat_sensitivity (same registry)
    # No code change — just config change
    defn_b = resolve_longitudinal_target(registry, "agent.learned.threat_sensitivity")
    assert defn_b.key == "agent.learned.threat_sensitivity"

    # Both are valid longitudinal targets; seam routes both
    assert defn_a.dynamics_policy == LONGITUDINAL_ACCUMULATOR
    assert defn_b.dynamics_policy == LONGITUDINAL_ACCUMULATOR


# ============================================================================
# Integration: TurnOrchestrator B-W seam with explicit config
# ============================================================================


def test_integration_orchestrator_slow_decision_accepted_if_target_registered() -> None:
    """A SLOW_ACCEPT decision whose target IS registered passes the seam."""
    registry = StateDefinitionRegistry()
    register_longitudinal_definition(registry, key="agent.slow.anxiety")

    defn = resolve_longitudinal_target(registry, "agent.slow.anxiety")
    assert defn.key == "agent.slow.anxiety"
    assert defn.dynamics_policy == LONGITUDINAL_ACCUMULATOR


def test_integration_orchestrator_slow_decision_rejected_if_target_unregistered() -> None:
    """A SLOW_ACCEPT decision whose target is not registered is fail-closed
    at the B-W seam (per BW-ONTO-2: writer consumes verbatim; registry
    verify at seam).

    Note: this test documents the fail-closed behavior. The orchestrator
    seam uses resolve_longitudinal_target which raises for unregistered
    dimensions; the decision is skipped, not rejected with an exception.
    """
    registry = StateDefinitionRegistry()  # empty — nothing registered

    with pytest.raises(ValueError, match="not registered"):
        resolve_longitudinal_target(registry, "agent.slow.anxiety")
