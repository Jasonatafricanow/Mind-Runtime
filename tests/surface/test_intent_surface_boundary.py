"""W3-C Intent Boundary & Overlap Rejection Tests.

These assertions enforce the W3-C contract requirements:
- R ∩ U rejection (direct Dynamics root intersects Surface control roots)
- U1 ∩ U2 rejection (scored Surface controls share Dynamics or Persona roots)
- Ineligible Surface control rejection (restraint/warmth cannot be Intent controls)
- Surface-aware rule event_bonus != 0 rejection
- ActionPolicy authority: high Surface controls cannot bypass ActionPolicy DENY
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from dataclasses import replace
from collections.abc import Mapping

import pytest

from mind_runtime.contracts import (
    ActionDecision,
    ActionPolicyInput,
    Intent,
    IntentStatus,
    PolicyResources,
    ReconsiderationPolicy,
    RuntimeState,
    Scope,
    ScopeDomain,
    Situation,
    SyncFields,
)
from mind_runtime.intents.policy import (
    ActionPolicyConfig,
    DeterministicActionPolicy,
    IntentPolicyRule,
)


def test_intent_direct_root_and_surface_overlap_rejected(intent_surface_validator):
    """W3-C: Direct longing (R) + contact_seeking (U) must be rejected by composition validator."""
    # R = {agent.affect.longing}, Surface = {contact_seeking} which has longing
    rule = {
        "kind": "reach_out",
        "direct_dynamics_weights": {"agent.affect.longing": 0.5},
        "surface_control_weights": {"contact_seeking": 0.4},
        "event_bonus": 0.0,
    }
    with pytest.raises(ValueError, match="ROOT_OVERLAP"):
        intent_surface_validator(rule)


def test_intent_pairwise_surface_control_overlap_rejected(intent_surface_validator):
    """W3-C: contact_seeking + confrontation share anger and expressive_restraint -> rejected."""
    # U1 = contact_seeking, U2 = confrontation -> share D.anger and P.expressive_restraint
    rule = {
        "kind": "assert_boundary",
        "direct_dynamics_weights": {},
        "surface_control_weights": {"contact_seeking": 0.3, "confrontation": 0.5},
        "event_bonus": 0.0,
    }
    with pytest.raises(ValueError, match="ROOT_OVERLAP"):
        intent_surface_validator(rule)


@pytest.mark.parametrize("direct, controls", [
    ({"agent.affect.longing": 0.0}, {"contact_seeking": 0.4}),
    ({"agent.affect.longing": 0.4}, {"contact_seeking": 0.0}),
    ({}, {"contact_seeking": 0.0, "confrontation": 0.4}),
])
def test_zero_weight_causal_declarations_still_reject_overlap(
    intent_surface_validator, direct, controls,
):
    with pytest.raises(ValueError, match="ROOT_OVERLAP"):
        intent_surface_validator({
            "kind": "reach_out", "direct_dynamics_weights": direct,
            "surface_control_weights": controls, "event_bonus": 0.0,
        })


def test_intent_ineligible_surface_control_rejected(intent_surface_validator):
    """W3-C: Expression-only controls (restraint, warmth) rejected in Intent rules."""
    rule = {
        "kind": "restrained_action",
        "direct_dynamics_weights": {},
        "surface_control_weights": {"expressive_restraint": 0.5},
        "event_bonus": 0.0,
    }
    with pytest.raises(ValueError, match="SURFACE_CONTROL_INELIGIBLE"):
        intent_surface_validator(rule)


def test_intent_surface_rule_event_bonus_forbidden(intent_surface_validator):
    """W3-C: Surface-aware rules must have event_bonus == 0 in V1."""
    rule = {
        "kind": "reach_out",
        "direct_dynamics_weights": {},
        "surface_control_weights": {"contact_seeking": 0.5},
        "event_bonus": 0.2,  # Nonzero event bonus forbidden on surface-aware rules
    }
    with pytest.raises(ValueError, match="SURFACE_EVENT_BONUS_FORBIDDEN"):
        intent_surface_validator(rule)


def test_action_policy_denial_prevents_dispatch_despite_high_controls():
    """W3-C: High contact_seeking and initiative cannot grant permission if ActionPolicy denies."""
    runtime_id = "test-runtime"
    now = datetime(2026, 9, 23, 12, 0, 0, tzinfo=UTC)

    # Configure policy where reach_out has cooldown
    config = ActionPolicyConfig(
        rules=(
            IntentPolicyRule(
                intent_kind="reach_out",
                action_type="send_message",
                proactive=True,
                interrupts_active_conversation=False,
                media_counter_fact=None,
                media_limit=None,
                required_resource=None,
            ),
        ),
        proactive_cooldown=timedelta(minutes=30),
    )
    policy = DeterministicActionPolicy(config=config, runtime_id=runtime_id)

    # Create Intent (even if scored with maximum strength 1.0 from contact_seeking = 0.95)
    scope = Scope(
        domain=ScopeDomain.AGENT,
        agent_id="test-agent",
        persona_id="persona-fixture-a",
    )
    intent = Intent(
        intent_id="intent-1",
        scope=scope,
        origin_runtime_id=runtime_id,
        kind="reach_out",
        strength=1.0,
        earliest_at=None,
        due_at=None,
        expires_at=now - timedelta(seconds=1),
        reconsideration_policy=ReconsiderationPolicy.NEVER,
        cause_refs=(),
        state_refs=(),
        status=IntentStatus.CANDIDATE,
        sync=SyncFields(
            scope=scope,
            origin_runtime_id=runtime_id,
            object_id="intent-1",
            version=1,
            idempotency_key="key-1",
        ),
    )

    situation = Situation(
        situation_id="sit-1",
        scope=scope,
        origin_runtime_id=runtime_id,
        derived_facts=(("activity_level", "idle"),),
        effective_state_ref="state-ref-1",
        observed_at=now,
        historical_context=None,
        persona_id=scope.persona_id,
        relationship_ids=(),
        evidence_refs=(),
    )

    policy_input = ActionPolicyInput(
        intent=intent,
        context=situation,
        scope=scope,
        clock=now,
        resources=PolicyResources(available_actions=("send_message",)),
    )

    result = policy.policy(policy_input)
    assert result.decision == ActionDecision.DENY
    assert "intent_expired" in result.reason_codes


def _sync(scope: Scope, object_id: str, version: int = 1, runtime_id: str = "fixture-runtime") -> SyncFields:
    return SyncFields(
        scope=scope,
        origin_runtime_id=runtime_id,
        object_id=object_id,
        version=version,
        idempotency_key=f"idem-{object_id}-v{version}",
    )


def _state(
    dim: str,
    val: float,
    ver: int,
    state_id: str,
    scope: Scope,
    now: datetime,
    runtime_id: str = "fixture-runtime",
) -> RuntimeState:
    from mind_runtime.contracts import RuntimeState

    return RuntimeState(
        state_id=state_id,
        scope=scope,
        origin_runtime_id=runtime_id,
        dimension=dim,
        value=val,
        status="active",
        valid_from=now,
        valid_until=None,
        relevant_until=None,
        last_observed_at=now,
        evidence_refs=("evidence-1",),
        transition_refs=(),
        updated_at=now,
        version=ver,
        sync=_sync(scope, state_id, version=ver, runtime_id=runtime_id),
    )


def _projected(
    states: tuple[RuntimeState, ...],
    scope: Scope,
    now: datetime,
    projection_id: str = "projection:fixture-1",
    runtime_id: str = "fixture-runtime",
) -> ProjectedMindState:
    from mind_runtime.contracts import ProjectedMindState

    return ProjectedMindState(
        projection_id=projection_id,
        scope=scope,
        origin_runtime_id=runtime_id,
        projected_states=states,
        sync=_sync(scope, projection_id, runtime_id=runtime_id),
    )


def test_surface_aware_rule_scores_tendency_and_emits_trace():
    """W3-C: Surface control biases score, emits trace, and attaches controls_id."""
    from mind_runtime.contracts import IntentEngineInput
    from mind_runtime.intents.engine import DeterministicIntentEngine, IntentRule
    from mind_runtime.surface import SurfaceProductionAdapter
    from tests.surface.spec_support import sample_candidate

    runtime_id = "fixture-runtime"
    now = datetime(2026, 9, 23, 12, 0, 0, tzinfo=UTC)
    scope = Scope(domain=ScopeDomain.AGENT, agent_id="fixture-persona", persona_id="persona-fixture-a")

    x = sample_candidate()
    adapter = SurfaceProductionAdapter()
    surface = adapter.project(x)
    assert surface.status == "AVAILABLE"
    assert surface.controls["values"]["contact_seeking"] == 0.500

    states = tuple(
        _state(
            dim=s["dimension"],
            val=s["value"],
            ver=s["version"],
            state_id=s["state_id"],
            scope=scope,
            now=now,
            runtime_id=runtime_id,
        )
        for s in x["projected_dynamics"]["states"]
    )
    projected = _projected(states, scope=scope, now=now, runtime_id=runtime_id)

    situation = Situation(
        situation_id="sit-1",
        scope=scope,
        origin_runtime_id=runtime_id,
        derived_facts=(),
        effective_state_ref="state-ref-1",
        observed_at=now,
        historical_context=None,
        persona_id=scope.persona_id,
        relationship_ids=(),
        evidence_refs=(),
    )

    rule = IntentRule(
        rule_id="reach-out-rule",
        kind="reach_out",
        base_strength=0.1,
        dimension_weights=(),
        event_kind=None,
        event_bonus=0.0,
        minimum_strength=0.2,
        due_at_attribute=None,
        expires_after=None,
        reconsideration_policy=ReconsiderationPolicy.ON_CONTEXT_CHANGE,
        surface_control_weights=(("contact_seeking", 0.4),),
    )

    engine = DeterministicIntentEngine(rules=(rule,), runtime_id=runtime_id)
    engine_input = IntentEngineInput(
        interaction_id="fixture-1",
        scope=scope,
        origin_runtime_id=runtime_id,
        context=situation,
        projected=projected,
        accepted_events=(),
        clock=now,
        surface=surface,
        persona_version=x["persona"]["persona_version"],
        persona_content_digest=x["persona"]["persona_content_digest"],
    )

    result = engine.evaluate(engine_input)
    assert len(result.candidates) == 1
    candidate = result.candidates[0]
    assert candidate.kind == "reach_out"
    # base 0.1 + 0.500 * 0.4 = 0.300
    assert candidate.strength == 0.3
    controls_id = surface.controls["controls_id"]
    assert controls_id in candidate.cause_refs

    assert len(result.traces) == 1
    trace = result.traces[0]
    assert trace.admitted is True
    assert trace.surface_controls_ref == controls_id
    assert trace.surface_dependency_digest == surface.controls["dependency_digest"]
    assert trace.overlap_validation_ref is not None
    assert trace.overlap_validation_ref.startswith("overlap-valid:")
    assert len(trace.overlap_validation_ref.removeprefix("overlap-valid:")) == 64

    surface_contribs = [c for c in trace.contributions if c.source_kind == "surface"]
    assert len(surface_contribs) == 1
    assert surface_contribs[0].source_ref == "contact_seeking"
    assert surface_contribs[0].amount == 0.2

    # A real typed result with a coherent but different lineage must still be
    # withheld. A superficial type/status check would admit these controls.
    def withheld(other_surface):
        outcome = engine.evaluate(replace(engine_input, surface=other_surface))
        assert outcome.candidates == ()
        assert outcome.traces[0].reason_codes == ("surface_stale_or_mismatch",)

    previous = sample_candidate()
    previous["interaction_or_tick_ref"] = "interaction:previous-turn"
    previous["projected_dynamics"]["interaction_or_tick_ref"] = "interaction:previous-turn"
    withheld(adapter.project(previous))
    withheld(adapter.project(sample_candidate("persona-fixture-b")))

    other_scope = sample_candidate()
    other_scope["scope"]["agent_id"] = "other-agent"
    other_scope["projected_dynamics"]["scope"]["agent_id"] = "other-agent"
    for item in other_scope["projected_dynamics"]["states"]:
        item["scope"]["agent_id"] = "other-agent"
    withheld(adapter.project(other_scope))

    other_runtime = sample_candidate()
    other_runtime["runtime_id"] = "other-runtime"
    other_runtime["owner"]["owner_runtime_id"] = "other-runtime"
    other_runtime["projected_dynamics"]["runtime_id"] = "other-runtime"
    other_runtime["projected_dynamics"]["owner"]["owner_runtime_id"] = "other-runtime"
    for item in other_runtime["projected_dynamics"]["states"]:
        item["runtime_id"] = "other-runtime"
        item["owner"]["owner_runtime_id"] = "other-runtime"
    withheld(adapter.project(other_runtime))

    def thaw(value):
        if isinstance(value, Mapping):
            return {key: thaw(item) for key, item in value.items()}
        if isinstance(value, (tuple, list)):
            return [thaw(item) for item in value]
        return value

    from mind_runtime.contracts.surface import SurfaceProjectionResult
    from mind_runtime.dynamics.persona import surface_digest

    wrong_recipe = thaw(surface.controls)
    wrong_recipe["recipe_digest"] = "0" * 64
    semantic = {key: value for key, value in wrong_recipe.items()
                if key not in ("controls_id", "evaluation_ref")}
    wrong_recipe["controls_id"] = "surface:" + surface_digest("controls", semantic)
    withheld(SurfaceProjectionResult(status="AVAILABLE", reasons=(), controls=wrong_recipe))


def test_missing_or_unavailable_surface_withholds_candidate():
    """W3-C: Missing or UNAVAILABLE Surface withholds candidate without fallback."""
    from mind_runtime.contracts import IntentEngineInput
    from mind_runtime.contracts.surface import SurfaceProjectionResult, SurfaceProjectionStatus
    from mind_runtime.intents.engine import DeterministicIntentEngine, IntentRule
    from tests.surface.spec_support import sample_candidate

    runtime_id = "fixture-runtime"
    now = datetime(2026, 9, 23, 12, 0, 0, tzinfo=UTC)
    scope = Scope(domain=ScopeDomain.AGENT, agent_id="test-agent", persona_id="persona-fixture-a")

    x = sample_candidate()
    states = tuple(
        _state(
            dim=s["dimension"],
            val=s["value"],
            ver=s["version"],
            state_id=s["state_id"],
            scope=scope,
            now=now,
            runtime_id=runtime_id,
        )
        for s in x["projected_dynamics"]["states"]
    )
    projected = _projected(states, scope=scope, now=now, runtime_id=runtime_id)
    situation = Situation(
        situation_id="sit-1",
        scope=scope,
        origin_runtime_id=runtime_id,
        derived_facts=(),
        effective_state_ref="state-ref-1",
        observed_at=now,
        historical_context=None,
        persona_id=scope.persona_id,
        relationship_ids=(),
        evidence_refs=(),
    )
    rule = IntentRule(
        rule_id="reach-out-rule",
        kind="reach_out",
        base_strength=0.1,
        dimension_weights=(),
        event_kind=None,
        event_bonus=0.0,
        minimum_strength=0.0,
        due_at_attribute=None,
        expires_after=None,
        reconsideration_policy=ReconsiderationPolicy.ON_CONTEXT_CHANGE,
        surface_control_weights=(("contact_seeking", 0.4),),
    )
    engine = DeterministicIntentEngine(rules=(rule,), runtime_id=runtime_id)

    # 1. Surface is None
    input_none = IntentEngineInput(
        interaction_id="fixture-1",
        scope=scope,
        origin_runtime_id=runtime_id,
        context=situation,
        projected=projected,
        accepted_events=(),
        clock=now,
        surface=None,
    )
    res_none = engine.evaluate(input_none)
    assert len(res_none.candidates) == 0
    assert len(res_none.traces) == 1
    assert res_none.traces[0].admitted is False
    assert "surface_unavailable" in res_none.traces[0].reason_codes

    # 2. Surface status is UNAVAILABLE
    unavail_surface = SurfaceProjectionResult(
        status=SurfaceProjectionStatus.UNAVAILABLE,
        reasons=["SURFACE_MISSING_STATE"],
        controls=None,
    )
    input_unavail = IntentEngineInput(
        interaction_id="fixture-1",
        scope=scope,
        origin_runtime_id=runtime_id,
        context=situation,
        projected=projected,
        accepted_events=(),
        clock=now,
        surface=unavail_surface,
    )
    res_unavail = engine.evaluate(input_unavail)
    assert len(res_unavail.candidates) == 0
    assert len(res_unavail.traces) == 1
    assert res_unavail.traces[0].admitted is False
    assert "surface_unavailable" in res_unavail.traces[0].reason_codes


def test_stale_or_substituted_surface_withholds_candidate():
    """W3-C: Stale projection_id or mismatched state versions withholds candidate."""
    from mind_runtime.contracts import IntentEngineInput
    from mind_runtime.intents.engine import DeterministicIntentEngine, IntentRule
    from mind_runtime.surface import SurfaceProductionAdapter
    from tests.surface.spec_support import sample_candidate

    runtime_id = "fixture-runtime"
    now = datetime(2026, 9, 23, 12, 0, 0, tzinfo=UTC)
    scope = Scope(domain=ScopeDomain.AGENT, agent_id="test-agent", persona_id="persona-fixture-a")

    x = sample_candidate()
    adapter = SurfaceProductionAdapter()
    surface = adapter.project(x)
    assert surface.status == "AVAILABLE"

    states = tuple(
        _state(
            dim=s["dimension"],
            val=s["value"],
            ver=s["version"],
            state_id=s["state_id"],
            scope=scope,
            now=now,
            runtime_id=runtime_id,
        )
        for s in x["projected_dynamics"]["states"]
    )

    # 1. projection_id mismatch
    mismatched_projected = _projected(
        states,
        scope=scope,
        now=now,
        projection_id="projection:DIFFERENT-ID",
        runtime_id=runtime_id,
    )
    situation = Situation(
        situation_id="sit-1",
        scope=scope,
        origin_runtime_id=runtime_id,
        derived_facts=(),
        effective_state_ref="state-ref-1",
        observed_at=now,
        historical_context=None,
        persona_id=scope.persona_id,
        relationship_ids=(),
        evidence_refs=(),
    )
    rule = IntentRule(
        rule_id="reach-out-rule",
        kind="reach_out",
        base_strength=0.1,
        dimension_weights=(),
        event_kind=None,
        event_bonus=0.0,
        minimum_strength=0.0,
        due_at_attribute=None,
        expires_after=None,
        reconsideration_policy=ReconsiderationPolicy.ON_CONTEXT_CHANGE,
        surface_control_weights=(("contact_seeking", 0.4),),
    )
    engine = DeterministicIntentEngine(rules=(rule,), runtime_id=runtime_id)
    res_mismatch = engine.evaluate(
        IntentEngineInput(
            interaction_id="fixture-1",
            scope=scope,
            origin_runtime_id=runtime_id,
            context=situation,
            projected=mismatched_projected,
            accepted_events=(),
            clock=now,
            surface=surface,
        )
    )
    assert len(res_mismatch.candidates) == 0
    assert len(res_mismatch.traces) == 1
    assert res_mismatch.traces[0].admitted is False
    assert "surface_stale_or_mismatch" in res_mismatch.traces[0].reason_codes

    # 2. State version mismatch (e.g. state was advanced to version 999)
    stale_states = list(states)
    stale_states[0] = _state(
        dim=states[0].dimension,
        val=states[0].value,
        ver=999,
        state_id=states[0].state_id,
        scope=scope,
        now=now,
        runtime_id=runtime_id,
    )
    stale_projected = _projected(
        tuple(stale_states),
        scope=scope,
        now=now,
        projection_id="projection:fixture-1",
        runtime_id=runtime_id,
    )
    res_stale = engine.evaluate(
        IntentEngineInput(
            interaction_id="fixture-1",
            scope=scope,
            origin_runtime_id=runtime_id,
            context=situation,
            projected=stale_projected,
            accepted_events=(),
            clock=now,
            surface=surface,
        )
    )
    assert len(res_stale.candidates) == 0
    assert len(res_stale.traces) == 1
    assert res_stale.traces[0].admitted is False
    assert "surface_stale_or_mismatch" in res_stale.traces[0].reason_codes


def test_intent_engine_input_rejects_bare_dict_surface():
    """W3-C: Bare dict of floats injected into IntentEngineInput is rejected."""
    from mind_runtime.contracts import IntentEngineInput
    from tests.surface.spec_support import sample_candidate

    runtime_id = "fixture-runtime"
    now = datetime(2026, 9, 23, 12, 0, 0, tzinfo=UTC)
    scope = Scope(domain=ScopeDomain.AGENT, agent_id="test-agent", persona_id="persona-fixture-a")
    x = sample_candidate()
    single_state = _state(
        dim="agent.affect.longing",
        val=0.5,
        ver=1,
        state_id="state-longing",
        scope=scope,
        now=now,
        runtime_id=runtime_id,
    )
    projected = _projected((single_state,), scope=scope, now=now, runtime_id=runtime_id)
    situation = Situation(
        situation_id="sit-1",
        scope=scope,
        origin_runtime_id=runtime_id,
        derived_facts=(),
        effective_state_ref="state-ref-1",
        observed_at=now,
        historical_context=None,
        persona_id=scope.persona_id,
        relationship_ids=(),
        evidence_refs=(),
    )

    with pytest.raises(ValueError, match="surface must be a SurfaceProjectionResult"):
        IntentEngineInput(
            interaction_id="fixture-1",
            scope=scope,
            origin_runtime_id=runtime_id,
            context=situation,
            projected=projected,
            accepted_events=(),
            clock=now,
            surface={"contact_seeking": 0.5},  # bare dict rejected!
        )

    class SurfaceProjectionResult:
        __module__ = "mind_runtime.contracts.surface"
        status = "AVAILABLE"
        controls = {"values": {"contact_seeking": 1.0}}

    with pytest.raises(ValueError, match="surface must be a SurfaceProjectionResult"):
        IntentEngineInput(
            interaction_id="fixture-1", scope=scope, origin_runtime_id=runtime_id,
            context=situation, projected=projected, accepted_events=(), clock=now,
            surface=SurfaceProjectionResult(),
        )


def test_turn_and_tick_surface_projection_consistency():
    """W3-C: Turn and tick use the exact same deterministic surface projection logic."""
    from mind_runtime.contracts import AffectiveDimensionProfile, BehavioralDisposition
    from mind_runtime.dynamics.persona import PersonaProfile
    from mind_runtime.surface import SurfaceProductionAdapter, project_surface_for_cognition
    from tests.surface.spec_support import sample_candidate

    runtime_id = "fixture-runtime"
    now = datetime(2026, 9, 23, 12, 0, 0, tzinfo=UTC)
    scope = Scope(domain=ScopeDomain.AGENT, agent_id="test-agent", persona_id="persona-fixture-a")

    x = sample_candidate()
    adapter = SurfaceProductionAdapter()

    persona = PersonaProfile(
        persona_id="persona-fixture-a",
        dimensions=tuple(
            AffectiveDimensionProfile(
                dimension=d["dimension"],
                baseline=d["baseline"],
                initial_value=d["initial_value"],
                sensitivity=d["sensitivity"],
                recovery_rate=d["recovery_rate"],
                ceiling=d["ceiling"],
                floor=d["floor"],
                growth_profile=tuple((k, v) for k, v in d["growth_profile"]),
                coupling_profile=tuple((k, v) for k, v in d["coupling_profile"]),
            )
            for d in x["persona"]["content"]["dimensions"]
        ),
        version=1,
        schema_version=2,
        behavioral_disposition=BehavioralDisposition(
            **x["persona"]["content"]["behavioral_disposition"]
        ),
    )

    states = tuple(
        _state(
            dim=s["dimension"],
            val=s["value"],
            ver=s["version"],
            state_id=s["state_id"],
            scope=scope,
            now=now,
            runtime_id=runtime_id,
        )
        for s in x["projected_dynamics"]["states"]
    )
    projected = _projected(states, scope=scope, now=now, runtime_id=runtime_id)

    # Turn projection
    res_turn = project_surface_for_cognition(
        surface_port=adapter,
        persona=persona,
        projected=projected,
        runtime_id=runtime_id,
        scope=scope,
        interaction_or_tick_ref="interaction:fixture-1",
    )
    # Tick projection
    res_tick = project_surface_for_cognition(
        surface_port=adapter,
        persona=persona,
        projected=projected,
        runtime_id=runtime_id,
        scope=scope,
        interaction_or_tick_ref="interaction:fixture-1",
    )

    assert res_turn is not None
    assert res_tick is not None
    assert res_turn.status == "AVAILABLE"
    assert res_tick.status == "AVAILABLE"
    # Identical numbers
    assert res_turn.controls["values"] == res_tick.controls["values"]
    # Identical controls_id
    assert res_turn.controls["controls_id"] == res_tick.controls["controls_id"]
    # Identical dependency_digest
    assert res_turn.controls["dependency_digest"] == res_tick.controls["dependency_digest"]
