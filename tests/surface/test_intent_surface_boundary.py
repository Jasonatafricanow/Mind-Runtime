"""W3-C Intent Boundary & Overlap Rejection Tests.

RED BY DESIGN: Production Intent Surface input & overlap validator are absent in W3-B0.
These assertions freeze the W3-C contract requirements:
- R ∩ U rejection (direct Dynamics root intersects Surface control roots)
- U1 ∩ U2 rejection (scored Surface controls share Dynamics or Persona roots)
- Surface-aware rule event_bonus != 0 rejection
- ActionPolicy authority: high Surface controls cannot bypass ActionPolicy DENY
"""

import pytest


def test_intent_direct_root_and_surface_overlap_rejected():
    """W3-C: Direct longing (R) + contact_seeking (U) must be rejected by composition validator."""
    try:
        from mind_runtime.intents.surface_validator import validate_intent_rule_surface_overlap
    except ImportError as e:
        pytest.fail(f"RED BY DESIGN: Intent Surface validator seam missing: {e}")

    # R = {agent.affect.longing}, Surface = {contact_seeking} which has longing
    rule = {
        "kind": "reach_out",
        "direct_dynamics_weights": {"agent.affect.longing": 0.5},
        "surface_control_weights": {"contact_seeking": 0.4},
        "event_bonus": 0.0,
    }
    with pytest.raises(ValueError, match="ROOT_OVERLAP"):
        validate_intent_rule_surface_overlap(rule)


def test_intent_pairwise_surface_control_overlap_rejected():
    """W3-C: contact_seeking + confrontation share anger -> rejected by composition validator."""
    try:
        from mind_runtime.intents.surface_validator import validate_intent_rule_surface_overlap
    except ImportError as e:
        pytest.fail(f"RED BY DESIGN: Intent Surface validator seam missing: {e}")

    # U1 = contact_seeking (has anger), U2 = confrontation (has anger) -> U1 ∩ U2 != empty
    rule = {
        "kind": "assert_boundary",
        "direct_dynamics_weights": {},
        "surface_control_weights": {"contact_seeking": 0.3, "confrontation": 0.5},
        "event_bonus": 0.0,
    }
    with pytest.raises(ValueError, match="ROOT_OVERLAP"):
        validate_intent_rule_surface_overlap(rule)


def test_intent_persona_root_overlap_rejected():
    """W3-C: Scored controls sharing a Persona root (e.g. expressive_restraint) must be rejected."""
    try:
        from mind_runtime.intents.surface_validator import validate_intent_rule_surface_overlap
    except ImportError as e:
        pytest.fail(f"RED BY DESIGN: Intent Surface validator seam missing: {e}")

    # contact_seeking and expressive_restraint both depend on P.expressive_restraint
    rule = {
        "kind": "restrained_contact",
        "direct_dynamics_weights": {},
        "surface_control_weights": {"contact_seeking": 0.3, "expressive_restraint": 0.3},
        "event_bonus": 0.0,
    }
    with pytest.raises(ValueError, match="ROOT_OVERLAP"):
        validate_intent_rule_surface_overlap(rule)


def test_intent_surface_rule_event_bonus_forbidden():
    """W3-C: Surface-aware rules must have event_bonus == 0 in V1."""
    try:
        from mind_runtime.intents.surface_validator import validate_intent_rule_surface_overlap
    except ImportError as e:
        pytest.fail(f"RED BY DESIGN: Intent Surface validator seam missing: {e}")

    rule = {
        "kind": "reach_out",
        "direct_dynamics_weights": {},
        "surface_control_weights": {"contact_seeking": 0.5},
        "event_bonus": 0.2,  # Nonzero event bonus forbidden on surface-aware rules
    }
    with pytest.raises(ValueError, match="SURFACE_EVENT_BONUS_FORBIDDEN"):
        validate_intent_rule_surface_overlap(rule)


def test_action_policy_denial_prevents_dispatch_despite_high_controls():
    """W3-C: High contact_seeking and initiative cannot grant permission if ActionPolicy denies."""
    try:
        from mind_runtime.intents.engine import DeterministicIntentEngine
        from mind_runtime.intents.policy import ActionPolicy
    except ImportError as e:
        pytest.fail(f"RED BY DESIGN: Intent/Policy production seam missing: {e}")

    _ = (DeterministicIntentEngine, ActionPolicy)
    # Surface controls high (e.g. 0.95), but Policy returns DENY -> no dispatch
    pytest.fail("RED BY DESIGN: Intent Surface dispatch integration seam missing")
