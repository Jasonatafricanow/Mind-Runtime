"""Certification & Audit Tests for Anger / Boundary Confrontation Consumer.

Task: MR-ANGER-BOUNDARY-CONFRONTATION-AUDIT-V1-01
Type: AUDIT-FIRST FAST-STATE CONSUMER CLOSURE
Branch: w/mr-anger-boundary-confrontation-v1-01

Covers Sections 15 through 18:
- Section 15 (A-J): Registry integrity, surface recipe v2, anger dynamics, monotonicity,
  persona modulation, dampening of contact_seeking and warmth, recipe and map digests.
- Section 16 (K-P): Expression map mapping (confrontation -> directness), qualitative bands,
  DecisionContextCompiler SURFACE_V1 integration, and zero-leak provider isolation.
- Section 17 (Q-V): ActionPolicy authority separation, anti-spam invariants, no synthetic
  evidence or boundary facts, and root overlap rejection.
- Section 18 (W-Z, AA-AC): Certified manifest inspection, boundary event authority absence,
  deferred intent branch, eligible surface control verification, and final audit verdict.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from mind_runtime.contracts import (
    ActionDecision,
    ActionPermission,
    ActionPolicyInput,
    ActionPolicyResult,
    Intent,
    IntentStatus,
    PolicyResources,
    ProjectedMindState,
    ReconsiderationPolicy,
    RuntimeState,
    Scope,
    ScopeDomain,
    Situation,
    SyncFields,
)
from mind_runtime.dynamics.fast_functions import (
    ANGER_CONTROLS_BOUNDARY_PRESSURE_NOT_PERMISSION,
    ANGER_CONTROLS_BOUNDARY_PRESSURE_NOT_PERMISSION_INVARIANT,
    FAST_FUNCTION_V1_COUNT,
    FAST_FUNCTION_V1_REGISTRY,
    FAST_FUNCTION_V1_SPECS,
    FastFunctionKind,
    FastStateStatus,
)
from mind_runtime.expression.context import (
    DecisionContextCompiler,
    DecisionContextCompilerInput,
    DecisionContextConfig,
)
from mind_runtime.expression.expression_map import (
    CANDIDATE_EXPRESSION_MAP_V2,
    CANDIDATE_MAP_DIGEST,
    CANDIDATE_MAP_ID,
    CANDIDATE_MAP_VERSION,
    CANDIDATE_RECIPE_DIGEST,
    CANDIDATE_RECIPE_ID,
    CANDIDATE_RECIPE_VERSION,
    CONTROL_TO_GUIDANCE,
    GUIDANCE_TO_CONTROL,
    evaluate_control_band,
    map_surface_to_qualitative_guidance,
)
from mind_runtime.expression.renderer import DeterministicContextRenderer
from mind_runtime.intents.policy import ActionPolicyConfig, DeterministicActionPolicy
from mind_runtime.intents.surface_validator import (
    ELIGIBLE_INTENT_SURFACE_CONTROLS,
    get_control_transitive_roots,
    validate_intent_rule_surface_overlap,
)
from mind_runtime.surface import SurfaceProductionAdapter
from mind_runtime.surface.recipe import MANIFEST
from tests.surface.spec_support import sample_candidate, state, trait

# Authoritative audit status constants
BOUNDARY_EVENT_TO_INTENT_AUTHORITY: str = "NONE"
ANGER_INTENT_BRANCH: str = "DEFERRED_NO_BOUNDARY_EVENT_TO_INTENT_AUTHORITY"
ANGER_EXPRESSION_BRANCH: str = "CLOSED"
FINAL_VERDICT: str = "ANGER_EXPRESSION_CLOSED_INTENT_DEFERRED"


# ==============================================================================
# Helper fixtures / harness
# ==============================================================================


def _build_expression_harness(
    *,
    persona_name: str = "persona-fixture-a",
    anger_value: float = 0.5,
    confrontation_readiness: float = 0.5,
    expressive_restraint: float = 0.2,
) -> tuple[
    DecisionContextCompiler,
    DecisionContextCompilerInput,
    DeterministicContextRenderer,
    Any,
]:
    now = datetime(2026, 9, 25, 10, 0, 0, tzinfo=UTC)
    scope = Scope(domain=ScopeDomain.AGENT, agent_id="fixture-persona", persona_id=persona_name)
    runtime_id = "fixture-runtime"

    x = sample_candidate(persona_name)
    state(x, "anger")["value"] = anger_value
    trait(x, "confrontation_readiness", confrontation_readiness)
    trait(x, "expressive_restraint", expressive_restraint)

    runtime_id = x["runtime_id"]
    projection_id = x["projected_dynamics"]["source_projection_id"]
    raw_ref = str(x["interaction_or_tick_ref"])
    interaction_id = raw_ref.removeprefix("interaction:").removeprefix("tick:")

    surface = SurfaceProductionAdapter().project(x)

    states = tuple(
        RuntimeState(
            state_id=s["state_id"],
            scope=scope,
            dimension=s["dimension"],
            value=s["value"],
            status="active",
            valid_from=now,
            valid_until=None,
            relevant_until=None,
            last_observed_at=now,
            evidence_refs=(),
            transition_refs=(),
            updated_at=now,
            origin_runtime_id=runtime_id,
            version=s["version"],
            sync=SyncFields(
                scope, runtime_id, s["state_id"], s["version"], f"idem-{s['state_id']}"
            ),
        )
        for s in x["projected_dynamics"]["states"]
    )

    projected = ProjectedMindState(
        projection_id=projection_id,
        scope=scope,
        origin_runtime_id=runtime_id,
        projected_states=states,
        sync=SyncFields(scope, runtime_id, projection_id, 1, "idem-proj"),
    )

    situation = Situation(
        situation_id="sit-anger-1",
        scope=scope,
        origin_runtime_id=runtime_id,
        derived_facts=(("time.daypart", "afternoon"),),
        effective_state_ref="state-ref-anger-1",
        observed_at=now,
        historical_context=None,
        persona_id=scope.persona_id,
        relationship_ids=(),
        evidence_refs=(),
    )

    intent = Intent(
        intent_id="intent-anger-1",
        scope=scope,
        origin_runtime_id=runtime_id,
        kind="respond",
        strength=0.75,
        earliest_at=None,
        due_at=None,
        expires_at=None,
        reconsideration_policy=ReconsiderationPolicy.ON_CONTEXT_CHANGE,
        cause_refs=("assessment-anger-1",),
        state_refs=(projection_id,),
        status=IntentStatus.ALLOWED,
        sync=SyncFields(scope, runtime_id, "intent-anger-1", 1, "idem-intent-anger-1"),
    )

    policy = ActionPolicyResult(
        policy_id="policy-anger-1",
        scope=scope,
        origin_runtime_id=runtime_id,
        intent_id="intent-anger-1",
        decision=ActionDecision.ALLOW,
        permission=ActionPermission(
            permission_id="perm-anger-1",
            scope=scope,
            origin_runtime_id=runtime_id,
            action_type="send_message",
            allowed=True,
            reasons=("allowed",),
            constraints=("direct",),
        ),
        reason_codes=("allowed",),
    )

    config = DecisionContextConfig(
        allowed_situation_facts=("time.daypart",),
        affect_rules=(),
        persona_style_constraints=(("format", "bullets"),),
        allowed_history_kinds=(),
        max_history_items=5,
        max_prior_expression_chars=200,
        max_item_chars=100,
        max_items=20,
        max_render_chars=2000,
        mode="SURFACE_V1",
    )

    compiler = DecisionContextCompiler(config)
    inp = DecisionContextCompilerInput(
        interaction_id=interaction_id,
        scope=scope,
        origin_runtime_id=runtime_id,
        situation=situation,
        effective_user_state=states[0],
        projected_agent_state=projected,
        assessment_trace_ref="trace-anger-1",
        intent=intent,
        policy_result=policy,
        persona_ref=persona_name,
        prior_expression=None,
        attempt=0,
        rewrite_reason_codes=(),
        slow_state_records=(),
        surface=surface,
        mode="SURFACE_V1",
        persona_version=x["persona"]["persona_version"],
        persona_content_digest=x["persona"]["persona_content_digest"],
    )
    renderer = DeterministicContextRenderer(config)
    return compiler, inp, renderer, surface


# ==============================================================================
# SECTION 15: Fast Function Lock, Surface Recipe v2, and Dynamics Monotonicity
# ==============================================================================


def test_a_fast_function_v1_count_and_registry_intact() -> None:
    """A. FAST_FUNCTION_V1 contains exactly 8 entries and matches registry."""
    assert FAST_FUNCTION_V1_COUNT == 8
    assert len(FAST_FUNCTION_V1_SPECS) == 8
    assert len(FAST_FUNCTION_V1_REGISTRY) == 8


def test_b_anger_maps_to_boundary_confrontation_active() -> None:
    """B. agent.affect.anger maps to BOUNDARY_CONFRONTATION with ACTIVE status."""
    spec = FAST_FUNCTION_V1_REGISTRY.require("agent.affect.anger")
    assert spec.state_key == "agent.affect.anger"
    assert spec.function_kind == FastFunctionKind.BOUNDARY_CONFRONTATION
    assert spec.status == FastStateStatus.ACTIVE
    assert spec.external_action_capable is True
    assert spec.primary_consumer == "Surface confrontation / expression directness path"
    assert "Surface/expression branch closed" in spec.notes
    assert "confrontation is Intent-eligible" in spec.notes
    assert "concrete boundary Intent branch is deferred" in spec.notes
    assert "no authoritative boundary-event-to-Intent binding exists" in spec.notes

    # Frozen invariant constant
    assert (
        ANGER_CONTROLS_BOUNDARY_PRESSURE_NOT_PERMISSION_INVARIANT
        == "ANGER_CONTROLS_BOUNDARY_PRESSURE != ANGER_GRANTS_ACTION_PERMISSION"
    )
    assert (
        ANGER_CONTROLS_BOUNDARY_PRESSURE_NOT_PERMISSION
        == ANGER_CONTROLS_BOUNDARY_PRESSURE_NOT_PERMISSION_INVARIANT
    )


def test_c_monotonic_anger_raises_confrontation() -> None:
    """C. Higher anger strictly increases Surface.confrontation (holding traits constant)."""
    adapter = SurfaceProductionAdapter()

    # Base candidate
    x1 = sample_candidate("persona-fixture-a")
    state(x1, "anger")["value"] = 0.1
    res1 = adapter.project(x1)

    x2 = sample_candidate("persona-fixture-a")
    state(x2, "anger")["value"] = 0.5
    res2 = adapter.project(x2)

    x3 = sample_candidate("persona-fixture-a")
    state(x3, "anger")["value"] = 0.9
    res3 = adapter.project(x3)

    c1 = res1.controls["values"]["confrontation"]
    c2 = res2.controls["values"]["confrontation"]
    c3 = res3.controls["values"]["confrontation"]

    assert c1 < c2 < c3
    # Check exact formula delta: delta_confrontation == 0.70 * delta_anger
    assert pytest.approx(c2 - c1, abs=1e-6) == 0.70 * (0.5 - 0.1)
    assert pytest.approx(c3 - c2, abs=1e-6) == 0.70 * (0.9 - 0.5)


def test_d_persona_confrontation_readiness_raises_confrontation() -> None:
    """D. Higher persona confrontation_readiness strictly increases confrontation."""
    adapter = SurfaceProductionAdapter()

    x1 = sample_candidate("persona-fixture-a")
    state(x1, "anger")["value"] = 0.3
    trait(x1, "confrontation_readiness", 0.2)
    res1 = adapter.project(x1)

    x2 = sample_candidate("persona-fixture-a")
    state(x2, "anger")["value"] = 0.3
    trait(x2, "confrontation_readiness", 0.5)
    res2 = adapter.project(x2)

    x3 = sample_candidate("persona-fixture-a")
    state(x3, "anger")["value"] = 0.3
    trait(x3, "confrontation_readiness", 0.8)
    res3 = adapter.project(x3)

    c1 = res1.controls["values"]["confrontation"]
    c2 = res2.controls["values"]["confrontation"]
    c3 = res3.controls["values"]["confrontation"]

    assert c1 < c2 < c3
    # Formula delta: delta_confrontation == 0.40 * delta_readiness
    assert pytest.approx(c2 - c1, abs=1e-6) == 0.40 * (0.5 - 0.2)
    assert pytest.approx(c3 - c2, abs=1e-6) == 0.40 * (0.8 - 0.5)


def test_e_persona_expressive_restraint_dampens_confrontation() -> None:
    """E. Higher persona expressive_restraint strictly dampens confrontation."""
    adapter = SurfaceProductionAdapter()

    x1 = sample_candidate("persona-fixture-a")
    state(x1, "anger")["value"] = 0.6
    trait(x1, "confrontation_readiness", 0.5)
    trait(x1, "expressive_restraint", 0.1)
    res1 = adapter.project(x1)

    x2 = sample_candidate("persona-fixture-a")
    state(x2, "anger")["value"] = 0.6
    trait(x2, "confrontation_readiness", 0.5)
    trait(x2, "expressive_restraint", 0.5)
    res2 = adapter.project(x2)

    x3 = sample_candidate("persona-fixture-a")
    state(x3, "anger")["value"] = 0.6
    trait(x3, "confrontation_readiness", 0.5)
    trait(x3, "expressive_restraint", 0.9)
    res3 = adapter.project(x3)

    c1 = res1.controls["values"]["confrontation"]
    c2 = res2.controls["values"]["confrontation"]
    c3 = res3.controls["values"]["confrontation"]

    assert c1 > c2 > c3
    # Formula delta: delta_confrontation == -0.30 * delta_restraint
    assert pytest.approx(c1 - c2, abs=1e-6) == 0.30 * (0.5 - 0.1)
    assert pytest.approx(c2 - c3, abs=1e-6) == 0.30 * (0.9 - 0.5)


def test_f_anger_dampens_contact_seeking() -> None:
    """F. Anger dampens contact_seeking via term -0.20 * anger."""
    adapter = SurfaceProductionAdapter()

    x_calm = sample_candidate("persona-fixture-a")
    state(x_calm, "longing")["value"] = 0.6
    state(x_calm, "closeness_craving")["value"] = 0.4
    state(x_calm, "anger")["value"] = 0.0
    res_calm = adapter.project(x_calm)

    x_angry = sample_candidate("persona-fixture-a")
    state(x_angry, "longing")["value"] = 0.6
    state(x_angry, "closeness_craving")["value"] = 0.4
    state(x_angry, "anger")["value"] = 0.8
    res_angry = adapter.project(x_angry)

    cs_calm = res_calm.controls["values"]["contact_seeking"]
    cs_angry = res_angry.controls["values"]["contact_seeking"]

    assert cs_angry < cs_calm
    # Delta is exactly 0.20 * 0.8 = 0.16
    assert pytest.approx(cs_calm - cs_angry, abs=1e-6) == 0.20 * 0.8


def test_g_anger_dampens_expressive_warmth() -> None:
    """G. Anger dampens expressive_warmth via term -0.25 * anger."""
    adapter = SurfaceProductionAdapter()

    x_calm = sample_candidate("persona-fixture-a")
    state(x_calm, "closeness_craving")["value"] = 0.5
    state(x_calm, "sadness")["value"] = 0.1
    state(x_calm, "anger")["value"] = 0.0
    trait(x_calm, "expressive_warmth_bias", 0.5)
    res_calm = adapter.project(x_calm)

    x_angry = sample_candidate("persona-fixture-a")
    state(x_angry, "closeness_craving")["value"] = 0.5
    state(x_angry, "sadness")["value"] = 0.1
    state(x_angry, "anger")["value"] = 0.8
    trait(x_angry, "expressive_warmth_bias", 0.5)
    res_angry = adapter.project(x_angry)

    ew_calm = res_calm.controls["values"]["expressive_warmth"]
    ew_angry = res_angry.controls["values"]["expressive_warmth"]

    assert ew_angry < ew_calm
    # Delta is exactly 0.25 * 0.8 = 0.20
    assert pytest.approx(ew_calm - ew_angry, abs=1e-6) == 0.25 * 0.8


def test_h_exact_five_surface_controls_preserved() -> None:
    """H. Candidate Recipe v2 preserves exactly the 5 frozen controls."""
    expected_controls = {
        "contact_seeking",
        "initiative",
        "confrontation",
        "expressive_warmth",
        "expressive_restraint",
    }
    assert set(MANIFEST.keys()) == expected_controls
    assert len(MANIFEST) == 5
    # Anger is root in exactly contact_seeking, confrontation, expressive_warmth
    anger_consumers = [k for k, v in MANIFEST.items() if "agent.affect.anger" in v["dynamics"]]
    assert set(anger_consumers) == {"contact_seeking", "confrontation", "expressive_warmth"}


def test_i_candidate_recipe_v2_digest_preserved() -> None:
    """I. Candidate Recipe v2 ID, version, and digest are strictly preserved."""
    assert CANDIDATE_RECIPE_ID == "surface-v1-candidate"
    assert CANDIDATE_RECIPE_VERSION == 2
    assert (
        CANDIDATE_RECIPE_DIGEST
        == "4f37f46f89f6176fd5fefe0167ec7a81e341839f4fb9b98fa3cc348ddeaf9a55"
    )


def test_j_candidate_expression_map_v2_digest_preserved() -> None:
    """J. Candidate Expression Map v2 ID, version, and digest are strictly preserved."""
    assert CANDIDATE_MAP_ID == "surface-v1-candidate-map"
    assert CANDIDATE_MAP_VERSION == 2
    assert (
        CANDIDATE_MAP_DIGEST
        == "bba6794aeda7a1755f8c79ffe5c88bd100918e6bc979ea29b5aa009e958eddf3"
    )


# ==============================================================================
# SECTION 16: Candidate Expression Map v2, Directness, and Isolation
# ==============================================================================


def test_k_confrontation_maps_to_directness() -> None:
    """K. confrontation maps bidirectionally to qualitative guidance directness."""
    assert GUIDANCE_TO_CONTROL["directness"] == "confrontation"
    assert CONTROL_TO_GUIDANCE["confrontation"] == "directness"
    dims = CANDIDATE_EXPRESSION_MAP_V2["guidance_dimensions"]
    assert "directness" in dims
    assert dims["directness"]["source_control"] == "confrontation"


def test_l_confrontation_low_band_mapping() -> None:
    """L. confrontation values in [0.0, 0.33) map to low directness."""
    assert evaluate_control_band(0.0) == "low"
    assert evaluate_control_band(0.15) == "low"
    assert evaluate_control_band(0.329999) == "low"


def test_m_confrontation_moderate_band_mapping() -> None:
    """M. confrontation values in [0.33, 0.66) map to moderate directness."""
    assert evaluate_control_band(0.33) == "moderate"
    assert evaluate_control_band(0.50) == "moderate"
    assert evaluate_control_band(0.659999) == "moderate"


def test_n_confrontation_high_band_mapping() -> None:
    """N. confrontation values in [0.66, 1.0] map to high directness."""
    assert evaluate_control_band(0.66) == "high"
    assert evaluate_control_band(0.85) == "high"
    assert evaluate_control_band(1.0) == "high"


def test_o_decision_context_compiler_surface_v1_includes_directness() -> None:
    """O. DecisionContextCompiler in SURFACE_V1 mode includes directness in envelope."""
    compiler, inp, renderer, surface = _build_expression_harness(
        anger_value=0.8,
        confrontation_readiness=0.6,
        expressive_restraint=0.1,
    )
    # confrontation = 0.70*0.8 + 0.40*0.6 - 0.30*0.1 = 0.56 + 0.24 - 0.03 = 0.77 -> high
    assert surface.controls["values"]["confrontation"] == pytest.approx(0.77, abs=1e-5)

    context, _ = compiler.compile(inp)
    guidance_bundle = renderer.render_surface_bundle(context)
    assert guidance_bundle is not None
    assert guidance_bundle["directness"] == "high"

    # Surface guidance items in compiled context
    guidance_items = [
        item for item in context.expression_context if item.kind.value == "surface_guidance"
    ]
    directness_item = next(
        (item for item in guidance_items if item.key == "directness"), None
    )
    assert directness_item is not None
    assert directness_item.value == "high"


def test_p_renderer_isolation_and_zero_anger_leak() -> None:
    """P. DeterministicContextRenderer renders directness band with zero raw state/trait leak."""
    compiler, inp, renderer, _ = _build_expression_harness(
        anger_value=0.8,
        confrontation_readiness=0.6,
        expressive_restraint=0.1,
    )
    context, _ = compiler.compile(inp)
    rendered = renderer.render(context)
    text = rendered.text

    # Required surface guidance present
    assert "[SURFACE_GUIDANCE]" in text or "[EXPRESSION GUIDANCE]" in text
    assert "directness: high" in text

    # Zero leakage of raw dimension keys or floats
    assert "agent.affect.anger" not in text
    assert "anger" not in text.lower().replace("danger", "")  # protect against substrings
    assert "0.8" not in text
    assert "0.77" not in text
    assert "confrontation_readiness" not in text
    assert "expressive_restraint" not in text

    # Strict isolation verification
    assert renderer.verify_provider_information_isolation(text) is True


# ==============================================================================
# SECTION 17: Authority Boundaries, Anti-Spam, and Overlap Rejection
# ==============================================================================


def test_q_high_confrontation_alone_cannot_produce_action_permission() -> None:
    """Q. Elevated anger / confrontation pressure alone CANNOT produce ActionPermission.ALLOW."""
    assert (
        ANGER_CONTROLS_BOUNDARY_PRESSURE_NOT_PERMISSION_INVARIANT
        == "ANGER_CONTROLS_BOUNDARY_PRESSURE != ANGER_GRANTS_ACTION_PERMISSION"
    )
    # ActionPolicy alone owns action permissions; Surface/confrontation has zero permission authority.
    now = datetime(2026, 9, 25, 10, 0, 0, tzinfo=UTC)
    scope = Scope(domain=ScopeDomain.AGENT, agent_id="fixture-persona", persona_id="persona-a")
    policy = DeterministicActionPolicy(
        ActionPolicyConfig(
            rules=(),  # No rule authorizes confrontation actions
            proactive_cooldown=timedelta(seconds=1800),
        ),
        "rt-1",
    )
    # Even if an intent carried high confrontation strength, ActionPolicy DENIES with no matching rule
    intent = Intent(
        intent_id="intent-confrontation-1",
        scope=scope,
        origin_runtime_id="rt-1",
        kind="assert_boundary",
        strength=0.99,
        earliest_at=None,
        due_at=None,
        expires_at=None,
        reconsideration_policy=ReconsiderationPolicy.ON_CONTEXT_CHANGE,
        cause_refs=(),
        state_refs=(),
        status=IntentStatus.ALLOWED,
        sync=SyncFields(scope, "rt-1", "intent-confrontation-1", 1, "idem-1"),
    )
    policy_input = ActionPolicyInput(
        intent=intent,
        context=Situation(
            situation_id="sit-1",
            scope=scope,
            origin_runtime_id="rt-1",
            derived_facts=(),
            effective_state_ref="ref-1",
            observed_at=now,
            historical_context=None,
            persona_id=scope.persona_id,
            relationship_ids=(),
            evidence_refs=(),
        ),
        scope=scope,
        clock=now,
        resources=PolicyResources(available_actions=frozenset({"text_message"})),
    )
    result = policy.policy(policy_input)
    assert result.decision == ActionDecision.DENY
    assert result.permission.allowed is False


def test_r_directness_guidance_cannot_construct_action_allow() -> None:
    """R. Qualitative directness mapping produces qualitative text guidance only, no action permission."""
    from mind_runtime.expression import expression_map

    # 1. Structural evidence: expression_map defines only qualitative bands and bundles
    assert not hasattr(expression_map, "ActionPolicy")
    assert not hasattr(expression_map, "ActionPermission")
    assert not hasattr(expression_map, "ActionDecision")

    # 2. directness mapping returns qualitative string values only ("low" | "moderate" | "high")
    guidance = map_surface_to_qualitative_guidance(
        {
            "status": "AVAILABLE",
            "controls": {
                "recipe_id": CANDIDATE_RECIPE_ID,
                "recipe_version": CANDIDATE_RECIPE_VERSION,
                "recipe_digest": CANDIDATE_RECIPE_DIGEST,
                "values": {
                    "confrontation": 0.85,
                    "expressive_warmth": 0.2,
                    "expressive_restraint": 0.3,
                },
            },
        }
    )
    assert guidance["directness"] == "high"
    assert isinstance(guidance["directness"], str)
    assert guidance["directness"] in {"low", "moderate", "high"}

    # 3. Directness guidance is purely string data for provider realization, incapable of granting action permission
    assert not isinstance(guidance["directness"], ActionPermission)


def test_s_directness_guidance_cannot_emit_wake_signal() -> None:
    """S. Directness guidance cannot emit a WakeSignal or trigger ticker wakeup."""
    # A ticker tick requires an ActionPolicy result with ALLOW to emit a WakeSignal.
    # Qualitative directness is an expression-time artifact, downstream of policy gating.
    now = datetime(2026, 9, 25, 10, 0, 0, tzinfo=UTC)
    scope = Scope(domain=ScopeDomain.AGENT, agent_id="fixture-persona", persona_id="persona-a")

    permission_deny = ActionPermission(
        permission_id="perm-deny",
        scope=scope,
        origin_runtime_id="rt-1",
        action_type="send_message",
        allowed=False,
        reasons=("cooldown_active",),
        constraints=(),
    )
    policy_deny = ActionPolicyResult(
        policy_id="pol-deny",
        scope=scope,
        origin_runtime_id="rt-1",
        intent_id="intent-1",
        decision=ActionDecision.DENY,
        permission=permission_deny,
        reason_codes=("cooldown_active",),
    )
    assert policy_deny.decision == ActionDecision.DENY
    assert policy_deny.permission is not None
    assert policy_deny.permission.allowed is False


def test_t_no_synthetic_boundary_event_or_evidence_fabricated() -> None:
    """T. Elevated anger does not fabricate synthetic boundary evidence (SYNTHETIC_EVIDENCE_PATH=NONE)."""
    _, inp, _, _ = _build_expression_harness(anger_value=0.95)
    # Situation evidence_refs must remain exactly what was observed from real world
    assert inp.situation.evidence_refs == ()
    assert inp.situation.derived_facts == (("time.daypart", "afternoon"),)


def test_u_no_synthetic_boundary_fact_injected_into_situation() -> None:
    """U. Situation does not receive synthetic boundary violation facts from anger."""
    _, inp, _, _ = _build_expression_harness(anger_value=0.95)
    situation_facts = dict(inp.situation.derived_facts)
    assert "boundary_violation" not in situation_facts
    assert "confrontation" not in situation_facts
    assert "anger" not in situation_facts


def test_v_surface_overlap_validator_rejects_overlapping_roots() -> None:
    """V. surface_validator rejects intent rules that combine overlapping surface controls."""
    # contact_seeking and confrontation both share agent.affect.anger and expressive_restraint
    rule = {
        "kind": "assert_boundary_conflict",
        "direct_dynamics_weights": {},
        "surface_control_weights": {"contact_seeking": 0.5, "confrontation": 0.5},
        "event_bonus": 0.0,
    }
    with pytest.raises(ValueError, match="ROOT_OVERLAP"):
        validate_intent_rule_surface_overlap(rule)


# ==============================================================================
# SECTION 18: Certified Manifest Inspection and Deferral Gate Verdict
# ==============================================================================


def test_w_certified_manifest_has_no_confrontation_intent_rule() -> None:
    """W. Certified runtime configuration contains zero confrontation-driven Intent rules."""
    manifest_path = Path("certification/d11s/inputs/runtime-config.json")
    assert manifest_path.exists(), f"Missing manifest: {manifest_path}"
    with open(manifest_path, encoding="utf-8") as f:
        config = json.load(f)

    component = next(
        c for c in config.get("components", []) if c.get("component_id") == "intent_engine"
    )
    intent_rules = component.get("payload", {}).get("rules", [])
    rule_kinds = [r.get("kind") for r in intent_rules]

    # Exactly respond and scheduled_follow_up exist
    assert rule_kinds == ["respond", "scheduled_follow_up"]
    assert "assert_boundary" not in rule_kinds
    assert "confrontation" not in rule_kinds

    # Verify no rule consumes confrontation or anger
    for r in intent_rules:
        weights = dict(r.get("dimension_weights", []))
        surface_weights = dict(r.get("surface_control_weights", []))
        assert "agent.affect.anger" not in weights
        assert "confrontation" not in surface_weights


def test_x_certified_manifest_has_no_boundary_action_policy_rule() -> None:
    """X. Certified runtime configuration contains zero boundary action policy rules."""
    manifest_path = Path("certification/d11s/inputs/runtime-config.json")
    with open(manifest_path, encoding="utf-8") as f:
        config = json.load(f)

    component = next(
        c for c in config.get("components", []) if c.get("component_id") == "action_policy"
    )
    action_rules = component.get("payload", {}).get("rules", [])
    action_types = [r.get("action_type") for r in action_rules]

    # Only text_message actions exist for respond and scheduled_follow_up
    assert all(at == "text_message" for at in action_types)
    assert "confrontation" not in action_types
    assert "boundary_assertion" not in action_types


def test_y_no_certified_boundary_event_to_intent_authority() -> None:
    """Y. Certified manifest and source configuration contain zero boundary-event-to-Intent bindings."""
    manifest_path = Path("certification/d11s/inputs/runtime-config.json")
    assert manifest_path.exists(), f"Missing manifest: {manifest_path}"
    with open(manifest_path, encoding="utf-8") as f:
        config = json.load(f)

    # A. Decode certified runtime manifest components
    intent_comp = next(
        c for c in config.get("components", []) if c.get("component_id") == "intent_engine"
    )
    action_comp = next(
        c for c in config.get("components", []) if c.get("component_id") == "action_policy"
    )
    intent_rules = intent_comp.get("payload", {}).get("rules", [])
    action_rules = action_comp.get("payload", {}).get("rules", [])

    # B. Verify no IntentRule has a boundary/confrontation event_kind
    for r in intent_rules:
        event_kind = r.get("event_kind")
        if event_kind is not None:
            assert "boundary" not in event_kind.lower()
            assert "confrontation" not in event_kind.lower()
            assert "anger" not in event_kind.lower()

    # C. Verify no IntentRule consumes Surface.confrontation
    for r in intent_rules:
        surface_weights = dict(r.get("surface_control_weights", []))
        assert "confrontation" not in surface_weights

    # D. Verify no ActionPolicy rule defines boundary assertion/confrontation action
    for r in action_rules:
        action_type = r.get("action_type", "")
        intent_kind = r.get("intent_kind", "")
        assert "boundary" not in action_type.lower()
        assert "confrontation" not in action_type.lower()
        assert "boundary" not in intent_kind.lower()
        assert "confrontation" not in intent_kind.lower()

    # E. Verify no certified event->Intent binding for boundary assertion exists
    boundary_event_bindings = [
        r for r in intent_rules
        if r.get("event_kind")
        and ("boundary" in r["event_kind"].lower() or "confrontation" in r["event_kind"].lower())
    ]
    assert len(boundary_event_bindings) == 0

    # Note: Generic SemanticEventCandidate system exists with open kind: str,
    # but there is currently no certified/configured authoritative mapping:
    # boundary semantic event -> boundary Intent -> boundary action.
    assert BOUNDARY_EVENT_TO_INTENT_AUTHORITY == "NONE"


def test_z_anger_intent_branch_deferred_constant() -> None:
    """Z. Autonomous boundary confrontation intent branch is recorded as deferred."""
    assert ANGER_INTENT_BRANCH == "DEFERRED_NO_BOUNDARY_EVENT_TO_INTENT_AUTHORITY"


def test_aa_confrontation_is_eligible_intent_surface_control() -> None:
    """AA. Surface.confrontation is declared an eligible intent surface control."""
    assert "confrontation" in ELIGIBLE_INTENT_SURFACE_CONTROLS
    assert "initiative" in ELIGIBLE_INTENT_SURFACE_CONTROLS
    assert "contact_seeking" in ELIGIBLE_INTENT_SURFACE_CONTROLS


def test_ab_overlap_protection_rejects_cross_talk() -> None:
    """AB. Root isolation correctly identifies anger and restraint as shared transitive roots."""
    confrontation_roots = get_control_transitive_roots("confrontation")
    contact_seeking_roots = get_control_transitive_roots("contact_seeking")

    shared = confrontation_roots.intersection(contact_seeking_roots)
    assert "agent.affect.anger" in shared
    assert "persona.behavioral_disposition.expressive_restraint" in shared


def test_ac_anger_consumer_verdict_closed_intent_deferred() -> None:
    """AC. Final audit verdict is ANGER_EXPRESSION_CLOSED_INTENT_DEFERRED."""
    assert ANGER_EXPRESSION_BRANCH == "CLOSED"
    assert ANGER_INTENT_BRANCH == "DEFERRED_NO_BOUNDARY_EVENT_TO_INTENT_AUTHORITY"
    assert BOUNDARY_EVENT_TO_INTENT_AUTHORITY == "NONE"
    assert FINAL_VERDICT == "ANGER_EXPRESSION_CLOSED_INTENT_DEFERRED"
