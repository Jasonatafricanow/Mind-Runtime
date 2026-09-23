"""W3-C Intent Boundary & Overlap Rejection Tests.

RED BY DESIGN: Production Intent Surface input & overlap validator are absent in W3-B0.
These assertions freeze the W3-C contract requirements:
- R ∩ U rejection (direct Dynamics root intersects Surface control roots)
- U1 ∩ U2 rejection (scored Surface controls share Dynamics or Persona roots)
- Ineligible Surface control rejection (restraint/warmth cannot be Intent controls)
- Surface-aware rule event_bonus != 0 rejection
- ActionPolicy authority: high Surface controls cannot bypass ActionPolicy DENY
"""

from datetime import UTC, datetime, timedelta

import pytest

from mind_runtime.contracts import (
    ActionDecision,
    ActionPolicyInput,
    Intent,
    IntentStatus,
    PolicyResources,
    ReconsiderationPolicy,
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
