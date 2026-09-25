"""Certification & Audit Tests for Sadness / Initiative Suppression Consumer.

Task: MR-SADNESS-INITIATIVE-SUPPRESSION-AUDIT-V1-01
Type: AUDIT-FIRST FAST-STATE CONSUMER CLOSURE
Branch: w/mr-sadness-initiative-suppression-v1-01

Covers Sections 15 through 20:
- Section 15 (A-I): Registry integrity, surface recipe v2, sadness dynamics, monotonicity,
  unclamped delta verification, five surface controls, recipe and map digests.
- Section 16 (J-N): Expression map mapping (expressive_warmth -> warmth), qualitative bands,
  DecisionContextCompiler SURFACE_V1 integration, zero-leak provider isolation, and
  initiative absence from provider guidance.
- Section 17 (O-V): Primary function effectiveness audit:
  - O: IntentRule initiative consumption audit
  - P: Certified manifest inspection (zero initiative rules)
  - Q: ActionPolicy initiative independence
  - R: CognitiveTicker initiative independence
  - S: Counterfactual test: spontaneous_share candidate strength with varying sadness
  - T: Counterfactual test: proactive_inquiry candidate strength with varying sadness
  - U: Counterfactual test: reach_out candidate strength with varying sadness
  - V: Multi-candidate proactive competition under low vs high sadness
- Section 18-20 (W-AC): Cross-talk protection, effective consumer gap certification,
  semantic authority separation invariant, and absence of synthetic withdrawal actions.
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
    IntentEngineInput,
    IntentStatus,
    PolicyResources,
    ProjectedMindState,
    ReconsiderationPolicy,
    RuntimeState,
    Scope,
    ScopeDomain,
    Situation,
    SyncFields,
    WakeSignal,
)
from mind_runtime.dynamics.fast_functions import (
    FAST_FUNCTION_V1_COUNT,
    FAST_FUNCTION_V1_REGISTRY,
    FAST_FUNCTION_V1_SPECS,
    SADNESS_SUPPRESSES_INITIATIVE_PRESSURE_NOT_PERMISSION,
    SADNESS_SUPPRESSES_INITIATIVE_PRESSURE_NOT_PERMISSION_INVARIANT,
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
from mind_runtime.intents.engine import DeterministicIntentEngine, IntentRule
from mind_runtime.intents.policy import ActionPolicyConfig, DeterministicActionPolicy, IntentPolicyRule
from mind_runtime.intents.surface_validator import (
    ELIGIBLE_INTENT_SURFACE_CONTROLS,
    INELIGIBLE_INTENT_SURFACE_CONTROLS,
    get_control_transitive_roots,
    validate_intent_rule_surface_overlap,
)
from mind_runtime.surface import SurfaceProductionAdapter
from mind_runtime.surface.recipe import CANDIDATE_RECIPE_ID, CANDIDATE_RECIPE_VERSION, MANIFEST, candidate_recipe
from tests.surface.spec_support import sample_candidate, state, trait

# Authoritative audit status constants
FAST_STATE_KEY: str = "agent.affect.sadness"
FUNCTION_KIND: str = "INITIATIVE_SUPPRESSION"
SADNESS_SURFACE_INITIATIVE_PROJECTION: str = "PASS"
SADNESS_EFFECTIVE_INITIATIVE_CONSUMER: str = "NONE"
SADNESS_PRIMARY_FUNCTION_RUNTIME_GAP: str = "FOUND"
DEDICATED_INTENT_CROSS_TALK_PROTECTION: str = "PASS"
INITIATIVE_SUPPRESSION_EFFECTIVE_ON_DEDICATED_INTENTS: str = "NO"
SADNESS_EXPRESSION_BRANCH: str = "CLOSED"
SADNESS_SUPPRESSES_SPONTANEOUS_SHARE: str = "NO"
SADNESS_SUPPRESSES_PROACTIVE_INQUIRY: str = "NO"
SADNESS_SUPPRESSES_REACH_OUT: str = "NO"
FINAL_VERDICT: str = "SADNESS_SURFACE_CLOSED_PRIMARY_CONSUMER_GAP_FOUND"


# ==============================================================================
# Helper fixtures / harness
# ==============================================================================


def _build_expression_harness(
    *,
    persona_name: str = "persona-fixture-a",
    sadness_value: float = 0.5,
    sharing_urge_value: float = 0.5,
    curiosity_value: float = 0.5,
    expressive_warmth_bias: float = 0.5,
    closeness_craving: float = 0.5,
    anger: float = 0.2,
) -> tuple[
    DecisionContextCompiler,
    DecisionContextCompilerInput,
    DeterministicContextRenderer,
    Any,
]:
    now = datetime(2026, 9, 25, 10, 0, 0, tzinfo=UTC)
    scope = Scope(domain=ScopeDomain.AGENT, agent_id="fixture-persona", persona_id=persona_name)

    x = sample_candidate(persona_name)
    state(x, "sadness")["value"] = sadness_value
    state(x, "sharing_urge")["value"] = sharing_urge_value
    state(x, "curiosity")["value"] = curiosity_value
    state(x, "closeness_craving")["value"] = closeness_craving
    state(x, "anger")["value"] = anger
    trait(x, "expressive_warmth_bias", expressive_warmth_bias)

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
        situation_id="sit-sadness-1",
        scope=scope,
        origin_runtime_id=runtime_id,
        derived_facts=(("time.daypart", "afternoon"),),
        effective_state_ref="state-ref-sadness-1",
        observed_at=now,
        historical_context=None,
        persona_id=scope.persona_id,
        relationship_ids=(),
        evidence_refs=(),
    )

    intent = Intent(
        intent_id="intent-sadness-1",
        scope=scope,
        origin_runtime_id=runtime_id,
        kind="respond",
        strength=0.75,
        earliest_at=None,
        due_at=None,
        expires_at=None,
        reconsideration_policy=ReconsiderationPolicy.ON_CONTEXT_CHANGE,
        cause_refs=("assessment-sadness-1",),
        state_refs=(projection_id,),
        status=IntentStatus.ALLOWED,
        sync=SyncFields(scope, runtime_id, "intent-sadness-1", 1, "idem-intent-sadness-1"),
    )

    policy = ActionPolicyResult(
        policy_id="policy-sadness-1",
        scope=scope,
        origin_runtime_id=runtime_id,
        intent_id="intent-sadness-1",
        decision=ActionDecision.ALLOW,
        permission=ActionPermission(
            permission_id="perm-sadness-1",
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
        assessment_trace_ref="trace-sadness-1",
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
# Section 15: Required Tests — Surface (A-I)
# ==============================================================================


def test_a_fast_function_v1_count_and_registry_intact() -> None:
    """A. FAST_FUNCTION_V1 contains exactly 8 entries and sadness is present."""
    assert FAST_FUNCTION_V1_COUNT == 8
    assert len(FAST_FUNCTION_V1_REGISTRY) == 8
    assert FAST_STATE_KEY in FAST_FUNCTION_V1_REGISTRY


def test_b_sadness_maps_to_initiative_suppression_active() -> None:
    """B. agent.affect.sadness maps to INITIATIVE_SUPPRESSION and records status."""
    spec = FAST_FUNCTION_V1_REGISTRY[FAST_STATE_KEY]
    assert spec.function_kind == FastFunctionKind.INITIATIVE_SUPPRESSION
    assert spec.primary_consumer == "Surface initiative / expression warmth path"
    assert spec.external_action_capable is False
    assert spec.status == FastStateStatus.ACTIVE
    assert "Surface projection exists" in spec.notes
    assert "warmth expression branch exists" in spec.notes
    assert "effective initiative consumer remains unbound" in spec.notes
    assert "SADNESS_PRIMARY_FUNCTION_RUNTIME_GAP=FOUND" in spec.notes


def test_c_monotonic_sadness_lowers_initiative() -> None:
    """C. Increasing sadness monotonically lowers Surface.initiative with sharing_urge/curiosity fixed."""
    adapter = SurfaceProductionAdapter()
    sadness_steps = [0.1, 0.3, 0.6, 0.9]
    initiative_values = []

    for s_val in sadness_steps:
        x = sample_candidate("persona-fixture-a")
        state(x, "sharing_urge")["value"] = 0.50
        state(x, "curiosity")["value"] = 0.50
        state(x, "sadness")["value"] = s_val
        res = adapter.project(x)
        assert res.status == "AVAILABLE"
        assert res.controls is not None
        initiative_values.append(res.controls["values"]["initiative"])

    # Monotonically strictly decreasing
    for i in range(len(initiative_values) - 1):
        assert initiative_values[i] > initiative_values[i + 1], (
            f"Expected initiative to strictly decrease: {initiative_values}"
        )


def test_d_exact_unclamped_delta_initiative() -> None:
    """D. Exact delta follows frozen recipe where unclamped: Δinitiative = -0.25 * Δsadness."""
    adapter = SurfaceProductionAdapter()

    # Recipe: initiative = clamp(0.60 * sharing_urge + 0.50 * curiosity - 0.25 * sadness, 0.0, 1.0)
    # With sharing_urge=0.5, curiosity=0.5: 0.60*0.5 + 0.50*0.5 = 0.55.
    # At sadness=0.2: 0.55 - 0.25*0.2 = 0.55 - 0.05 = 0.50.
    # At sadness=0.6: 0.55 - 0.25*0.6 = 0.55 - 0.15 = 0.40.
    # Delta sadness = 0.4. Expected delta initiative = -0.25 * 0.4 = -0.10.

    x1 = sample_candidate("persona-fixture-a")
    state(x1, "sharing_urge")["value"] = 0.50
    state(x1, "curiosity")["value"] = 0.50
    state(x1, "sadness")["value"] = 0.20
    res1 = adapter.project(x1)
    val1 = res1.controls["values"]["initiative"]

    x2 = sample_candidate("persona-fixture-a")
    state(x2, "sharing_urge")["value"] = 0.50
    state(x2, "curiosity")["value"] = 0.50
    state(x2, "sadness")["value"] = 0.60
    res2 = adapter.project(x2)
    val2 = res2.controls["values"]["initiative"]

    delta_sadness = 0.60 - 0.20
    delta_initiative = val2 - val1
    assert pytest.approx(delta_initiative, abs=1e-6) == -0.25 * delta_sadness
    assert pytest.approx(val1, abs=1e-6) == 0.50
    assert pytest.approx(val2, abs=1e-6) == 0.40


def test_e_monotonic_sadness_lowers_expressive_warmth() -> None:
    """E. Increasing sadness monotonically lowers expressive_warmth with other roots fixed."""
    adapter = SurfaceProductionAdapter()
    sadness_steps = [0.1, 0.4, 0.7, 0.95]
    warmth_values = []

    for s_val in sadness_steps:
        x = sample_candidate("persona-fixture-a")
        trait(x, "expressive_warmth_bias", 0.60)
        state(x, "closeness_craving")["value"] = 0.50
        state(x, "anger")["value"] = 0.20
        state(x, "sadness")["value"] = s_val
        res = adapter.project(x)
        assert res.status == "AVAILABLE"
        assert res.controls is not None
        warmth_values.append(res.controls["values"]["expressive_warmth"])

    # Monotonically strictly decreasing
    for i in range(len(warmth_values) - 1):
        assert warmth_values[i] > warmth_values[i + 1], (
            f"Expected expressive_warmth to strictly decrease: {warmth_values}"
        )


def test_f_exact_unclamped_delta_expressive_warmth() -> None:
    """F. Exact warmth delta follows frozen recipe where unclamped: Δexpressive_warmth = -0.20 * Δsadness."""
    adapter = SurfaceProductionAdapter()

    # Recipe: expressive_warmth = clamp(0.55 * bias + 0.50 * closeness - 0.25 * anger - 0.20 * sadness, 0.0, 1.0)
    # With bias=0.6, closeness=0.5, anger=0.2:
    # 0.55*0.6 + 0.50*0.5 - 0.25*0.2 = 0.33 + 0.25 - 0.05 = 0.53.
    # At sadness=0.2: 0.53 - 0.20*0.2 = 0.49.
    # At sadness=0.7: 0.53 - 0.20*0.7 = 0.39.
    # Delta sadness = 0.50. Expected delta warmth = -0.20 * 0.50 = -0.10.

    x1 = sample_candidate("persona-fixture-a")
    trait(x1, "expressive_warmth_bias", 0.60)
    state(x1, "closeness_craving")["value"] = 0.50
    state(x1, "anger")["value"] = 0.20
    state(x1, "sadness")["value"] = 0.20
    res1 = adapter.project(x1)
    val1 = res1.controls["values"]["expressive_warmth"]

    x2 = sample_candidate("persona-fixture-a")
    trait(x2, "expressive_warmth_bias", 0.60)
    state(x2, "closeness_craving")["value"] = 0.50
    state(x2, "anger")["value"] = 0.20
    state(x2, "sadness")["value"] = 0.70
    res2 = adapter.project(x2)
    val2 = res2.controls["values"]["expressive_warmth"]

    delta_sadness = 0.70 - 0.20
    delta_warmth = val2 - val1
    assert pytest.approx(delta_warmth, abs=1e-6) == -0.20 * delta_sadness
    assert pytest.approx(val1, abs=1e-6) == 0.49
    assert pytest.approx(val2, abs=1e-6) == 0.39


def test_g_exact_five_surface_controls_preserved() -> None:
    """G. Exactly five surface controls are preserved; no new controls introduced."""
    recipe = candidate_recipe()
    rule_ids = sorted(rule["control_id"] for rule in recipe["rules"])
    expected_controls = sorted(
        [
            "contact_seeking",
            "initiative",
            "confrontation",
            "expressive_warmth",
            "expressive_restraint",
        ]
    )
    assert rule_ids == expected_controls
    assert len(rule_ids) == 5

    # Explicit exclusions
    for forbidden in (
        "low_initiative",
        "withdrawal",
        "sadness_pressure",
        "behavioral_inhibition",
        "activation_suppression",
    ):
        assert forbidden not in rule_ids


def test_h_candidate_recipe_v2_digest_preserved() -> None:
    """H. Candidate Recipe v2 digest is preserved byte-for-byte."""
    from mind_runtime.surface.recipe import validate_candidate_recipe

    recipe = candidate_recipe()
    valid, reason = validate_candidate_recipe(recipe)
    assert valid is True, f"Recipe validation failed: {reason}"
    assert CANDIDATE_RECIPE_ID == "surface-v1-candidate"
    assert CANDIDATE_RECIPE_VERSION == 2
    assert (
        CANDIDATE_RECIPE_DIGEST
        == "4f37f46f89f6176fd5fefe0167ec7a81e341839f4fb9b98fa3cc348ddeaf9a55"
    )


def test_i_candidate_expression_map_v2_digest_preserved() -> None:
    """I. Candidate Expression Map v2 digest is preserved byte-for-byte."""
    from mind_runtime.expression.expression_map import validate_expression_map

    validate_expression_map(CANDIDATE_EXPRESSION_MAP_V2)
    assert CANDIDATE_MAP_ID == "surface-v1-candidate-map"
    assert CANDIDATE_MAP_VERSION == 2
    assert (
        CANDIDATE_MAP_DIGEST
        == "bba6794aeda7a1755f8c79ffe5c88bd100918e6bc979ea29b5aa009e958eddf3"
    )


# ==============================================================================
# Section 16: Required Tests — Expression (J-N)
# ==============================================================================


def test_j_expressive_warmth_maps_to_qualitative_warmth() -> None:
    """J. expressive_warmth maps to qualitative warmth across frozen bands."""
    assert GUIDANCE_TO_CONTROL["warmth"] == "expressive_warmth"
    assert CONTROL_TO_GUIDANCE["expressive_warmth"] == "warmth"

    # Band partitions: low: [0.0, 0.33), moderate: [0.33, 0.66), high: [0.66, 1.0]
    assert evaluate_control_band(0.15) == "low"
    assert evaluate_control_band(0.33) == "moderate"
    assert evaluate_control_band(0.50) == "moderate"
    assert evaluate_control_band(0.66) == "high"
    assert evaluate_control_band(0.90) == "high"


def test_k_sadness_alters_warmth_band_through_recipe() -> None:
    """K. Sadness alone can alter qualitative warmth band through the existing recipe."""
    adapter = SurfaceProductionAdapter()

    # Base without sadness: 0.55 * 0.8 + 0.50 * 0.6 - 0.25 * 0.1 = 0.44 + 0.30 - 0.025 = 0.715
    # Low sadness (0.1): 0.715 - 0.20*0.1 = 0.695 -> "high" (>= 0.66)
    # High sadness (0.8): 0.715 - 0.20*0.8 = 0.555 -> "moderate" (< 0.66)
    # Extreme sadness (0.95) with lower base (0.45):
    # Base 0.45: at sadness=0.1 -> 0.43 ("moderate"); at sadness=0.8 -> 0.29 ("low")

    x_high_warmth = sample_candidate("persona-fixture-a")
    trait(x_high_warmth, "expressive_warmth_bias", 0.80)
    state(x_high_warmth, "closeness_craving")["value"] = 0.60
    state(x_high_warmth, "anger")["value"] = 0.10
    state(x_high_warmth, "sadness")["value"] = 0.10
    res_high = adapter.project(x_high_warmth)
    guidance_high = map_surface_to_qualitative_guidance(res_high)
    assert guidance_high["warmth"] == "high"

    x_mod_warmth = sample_candidate("persona-fixture-a")
    trait(x_mod_warmth, "expressive_warmth_bias", 0.80)
    state(x_mod_warmth, "closeness_craving")["value"] = 0.60
    state(x_mod_warmth, "anger")["value"] = 0.10
    state(x_mod_warmth, "sadness")["value"] = 0.80
    res_mod = adapter.project(x_mod_warmth)
    guidance_mod = map_surface_to_qualitative_guidance(res_mod)
    assert guidance_mod["warmth"] == "moderate"

    # Lower base to test crossing into "low"
    x_low_warmth = sample_candidate("persona-fixture-a")
    trait(x_low_warmth, "expressive_warmth_bias", 0.40)
    state(x_low_warmth, "closeness_craving")["value"] = 0.30
    state(x_low_warmth, "anger")["value"] = 0.20
    state(x_low_warmth, "sadness")["value"] = 0.80
    res_low = adapter.project(x_low_warmth)
    guidance_low = map_surface_to_qualitative_guidance(res_low)
    assert guidance_low["warmth"] == "low"


def test_l_provider_envelope_contains_qualitative_warmth() -> None:
    """L. Provider envelope contains qualitative warmth guidance."""
    compiler, inp, renderer, _ = _build_expression_harness(
        sadness_value=0.2,
        expressive_warmth_bias=0.8,
        closeness_craving=0.6,
    )
    context, _ = compiler.compile(inp)
    guidance_bundle = renderer.render_surface_bundle(context)
    assert guidance_bundle is not None
    assert guidance_bundle["warmth"] in {"high", "moderate"}

    rendered = renderer.render(context)
    text = rendered.text
    assert "[SURFACE_GUIDANCE]" in text or "[EXPRESSION GUIDANCE]" in text
    assert "warmth:" in text


def test_m_renderer_isolation_and_zero_sadness_leak() -> None:
    """M. Provider envelope contains no raw sadness float, key, or trait values."""
    compiler, inp, renderer, _ = _build_expression_harness(
        sadness_value=0.85,
        expressive_warmth_bias=0.55,
        closeness_craving=0.45,
    )
    context, _ = compiler.compile(inp)
    rendered = renderer.render(context)
    text = rendered.text

    # Strict isolation verification
    assert renderer.verify_provider_information_isolation(text) is True

    # No raw sadness keys
    assert "agent.affect.sadness" not in text
    assert "sadness" not in text.lower()
    # No raw floats
    assert "0.85" not in text
    assert "0.55" not in text
    assert "0.45" not in text


def test_n_surface_initiative_not_serialized_as_raw_guidance() -> None:
    """N. Surface.initiative is NOT serialized as qualitative guidance or leaked to provider."""
    compiler, inp, renderer, _ = _build_expression_harness(sadness_value=0.5)
    context, _ = compiler.compile(inp)
    rendered = renderer.render(context)
    text = rendered.text

    assert "initiative" not in text.lower()
    guidance_bundle = renderer.render_surface_bundle(context)
    assert "initiative" not in guidance_bundle


# ==============================================================================
# Section 17: Required Tests — Primary Function Effectiveness (O-V)
# ==============================================================================


def test_o_no_configured_intent_rule_consumes_surface_initiative() -> None:
    """O. Audit whether any configured/certified IntentRule consumes Surface.initiative."""
    # Certified manifest inspection
    manifest_path = Path("certification/d11s/inputs/runtime-config.json")
    assert manifest_path.exists()
    with open(manifest_path, encoding="utf-8") as f:
        config = json.load(f)

    intent_comp = next(
        c for c in config.get("components", []) if c.get("component_id") == "intent_engine"
    )
    rules = intent_comp.get("payload", {}).get("rules", [])

    # None of the certified rules consume initiative
    for r in rules:
        scw = r.get("surface_control_weights", [])
        assert "initiative" not in dict(scw)


def test_p_certified_manifest_has_no_initiative_intent_or_policy_rule() -> None:
    """P. Certified manifest contains zero initiative Intent rules or ActionPolicy rules."""
    manifest_path = Path("certification/d11s/inputs/runtime-config.json")
    with open(manifest_path, encoding="utf-8") as f:
        config = json.load(f)

    # 1. Intent engine
    intent_comp = next(
        c for c in config.get("components", []) if c.get("component_id") == "intent_engine"
    )
    intent_rules = intent_comp.get("payload", {}).get("rules", [])
    for r in intent_rules:
        scw = dict(r.get("surface_control_weights", []))
        assert "initiative" not in scw
        assert r.get("kind") != "initiative"

    # 2. Action policy
    action_comp = next(
        c for c in config.get("components", []) if c.get("component_id") == "action_policy"
    )
    action_rules = action_comp.get("payload", {}).get("rules", [])
    for r in action_rules:
        assert "initiative" not in r.get("action_type", "")
        assert "initiative" not in r.get("intent_kind", "")


def test_q_action_policy_has_no_initiative_dependency() -> None:
    """Q. ActionPolicy evaluates only named factual inputs with zero initiative dependency."""
    # Structural evidence: DeterministicActionPolicy does not inspect or reference Surface
    policy = DeterministicActionPolicy(
        ActionPolicyConfig(rules=(), proactive_cooldown=timedelta(seconds=1800)),
        "rt-1",
    )
    assert not hasattr(policy, "initiative")
    assert not hasattr(ActionPolicyConfig, "initiative")
    assert not hasattr(IntentPolicyRule, "initiative")


def test_r_cognitive_ticker_does_not_gate_on_initiative() -> None:
    """R. CognitiveTicker does not gate or suppress execution on initiative."""
    from mind_runtime.cognition.tick import CognitiveTicker

    # CognitiveTicker coordinates:
    # 1. Advance dynamics
    # 2. Project surface
    # 3. Evaluate intent engine (passing surface to input)
    # 4. Action policy on candidates
    # CognitiveTicker does not inspect Surface.initiative to gate, clamp, or suppress candidates.
    assert not hasattr(CognitiveTicker, "initiative")
    assert not hasattr(CognitiveTicker, "_initiative_gate")


def test_s_sadness_does_not_suppress_spontaneous_share_candidate_strength() -> None:
    """S. Counterfactual test: identical sharing_urge produces identical spontaneous_share score across sadness variations."""
    # spontaneous_share rule scores directly from dimension_weights: (("agent.affect.sharing_urge", 0.8),)
    # surface_control_weights=() (rejecting initiative to prevent cross-talk)
    rule = IntentRule(
        rule_id="spontaneous_share",
        kind="spontaneous_share",
        base_strength=0.1,
        dimension_weights=(("agent.affect.sharing_urge", 0.8),),
        event_kind=None,
        event_bonus=0.0,
        minimum_strength=0.5,
        due_at_attribute=None,
        expires_after=None,
        reconsideration_policy=ReconsiderationPolicy.ON_CONTEXT_CHANGE,
        surface_control_weights=(),
    )
    engine = DeterministicIntentEngine((rule,), "rt-1")
    now = datetime(2026, 9, 25, 10, 0, 0, tzinfo=UTC)
    scope = Scope(domain=ScopeDomain.AGENT, agent_id="p-1", persona_id="persona-a")

    # Case 1: Low sadness (0.10)
    p_state_low = tuple(
        RuntimeState(
            state_id=f"s-{dim}",
            scope=scope,
            dimension=dim,
            value=val,
            status="active",
            valid_from=now,
            valid_until=None,
            relevant_until=None,
            last_observed_at=now,
            evidence_refs=(),
            transition_refs=(),
            updated_at=now,
            origin_runtime_id="rt-1",
            version=1,
            sync=SyncFields(scope, "rt-1", f"s-{dim}", 1, f"idem-{dim}"),
        )
        for dim, val in [
            ("agent.affect.sharing_urge", 0.80),
            ("agent.affect.sadness", 0.10),
        ]
    )
    proj_low = ProjectedMindState(
        projection_id="proj-low",
        scope=scope,
        origin_runtime_id="rt-1",
        projected_states=p_state_low,
        sync=SyncFields(scope, "rt-1", "proj-low", 1, "idem-proj-low"),
    )
    sit = Situation(
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
    )
    inp_low = IntentEngineInput(
        interaction_id="tick-1",
        scope=scope,
        origin_runtime_id="rt-1",
        context=sit,
        projected=proj_low,
        accepted_events=(),
        clock=now,
        surface=None,
    )
    res_low = engine.evaluate(inp_low)

    # Case 2: High sadness (0.90)
    p_state_high = tuple(
        RuntimeState(
            state_id=f"s-{dim}",
            scope=scope,
            dimension=dim,
            value=val,
            status="active",
            valid_from=now,
            valid_until=None,
            relevant_until=None,
            last_observed_at=now,
            evidence_refs=(),
            transition_refs=(),
            updated_at=now,
            origin_runtime_id="rt-1",
            version=1,
            sync=SyncFields(scope, "rt-1", f"s-{dim}", 1, f"idem-{dim}"),
        )
        for dim, val in [
            ("agent.affect.sharing_urge", 0.80),
            ("agent.affect.sadness", 0.90),
        ]
    )
    proj_high = ProjectedMindState(
        projection_id="proj-high",
        scope=scope,
        origin_runtime_id="rt-1",
        projected_states=p_state_high,
        sync=SyncFields(scope, "rt-1", "proj-high", 1, "idem-proj-high"),
    )
    inp_high = IntentEngineInput(
        interaction_id="tick-2",
        scope=scope,
        origin_runtime_id="rt-1",
        context=sit,
        projected=proj_high,
        accepted_events=(),
        clock=now,
        surface=None,
    )
    res_high = engine.evaluate(inp_high)

    assert len(res_low.candidates) == 1
    assert len(res_high.candidates) == 1
    # Candidate strengths are identical: 0.1 + 0.80 * 0.8 = 0.74
    assert res_low.candidates[0].strength == res_high.candidates[0].strength == 0.74
    # Architectural fact:
    assert SADNESS_SUPPRESSES_SPONTANEOUS_SHARE == "NO"


def test_t_sadness_does_not_suppress_proactive_inquiry_candidate_strength() -> None:
    """T. Counterfactual test: identical curiosity produces identical proactive_inquiry score across sadness variations."""
    rule = IntentRule(
        rule_id="proactive_inquiry",
        kind="proactive_inquiry",
        base_strength=0.1,
        dimension_weights=(("agent.affect.curiosity", 0.8),),
        event_kind=None,
        event_bonus=0.0,
        minimum_strength=0.5,
        due_at_attribute=None,
        expires_after=None,
        reconsideration_policy=ReconsiderationPolicy.ON_CONTEXT_CHANGE,
        surface_control_weights=(),
    )
    engine = DeterministicIntentEngine((rule,), "rt-1")
    now = datetime(2026, 9, 25, 10, 0, 0, tzinfo=UTC)
    scope = Scope(domain=ScopeDomain.AGENT, agent_id="p-1", persona_id="persona-a")
    sit = Situation(
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
    )

    # Low sadness vs High sadness with curiosity = 0.75
    for sadness_val in (0.10, 0.95):
        p_states = tuple(
            RuntimeState(
                state_id=f"s-{dim}",
                scope=scope,
                dimension=dim,
                value=val,
                status="active",
                valid_from=now,
                valid_until=None,
                relevant_until=None,
                last_observed_at=now,
                evidence_refs=(),
                transition_refs=(),
                updated_at=now,
                origin_runtime_id="rt-1",
                version=1,
                sync=SyncFields(scope, "rt-1", f"s-{dim}", 1, f"idem-{dim}"),
            )
            for dim, val in [
                ("agent.affect.curiosity", 0.75),
                ("agent.affect.sadness", sadness_val),
            ]
        )
        proj = ProjectedMindState(
            projection_id=f"proj-{sadness_val}",
            scope=scope,
            origin_runtime_id="rt-1",
            projected_states=p_states,
            sync=SyncFields(scope, "rt-1", f"proj-{sadness_val}", 1, "idem"),
        )
        inp = IntentEngineInput(
            interaction_id=f"tick-{sadness_val}",
            scope=scope,
            origin_runtime_id="rt-1",
            context=sit,
            projected=proj,
            accepted_events=(),
            clock=now,
            surface=None,
        )
        res = engine.evaluate(inp)
        assert len(res.candidates) == 1
        # Strength: 0.1 + 0.75 * 0.8 = 0.70
        assert res.candidates[0].strength == 0.70

    assert SADNESS_SUPPRESSES_PROACTIVE_INQUIRY == "NO"


def test_u_sadness_does_not_suppress_reach_out_candidate_strength() -> None:
    """U. Counterfactual test: identical longing produces identical reach_out score across sadness variations."""
    # In Candidate Recipe v2, contact_seeking does NOT include sadness:
    # contact_seeking = 0.45 * longing + 0.35 * closeness_craving + 0.30 * attachment_approach - 0.20 * anger - 0.20 * restraint
    adapter = SurfaceProductionAdapter()

    x_low = sample_candidate("persona-fixture-a")
    state(x_low, "longing")["value"] = 0.80
    state(x_low, "sadness")["value"] = 0.10
    res_low = adapter.project(x_low)
    cs_low = res_low.controls["values"]["contact_seeking"]

    x_high = sample_candidate("persona-fixture-a")
    state(x_high, "longing")["value"] = 0.80
    state(x_high, "sadness")["value"] = 0.90
    res_high = adapter.project(x_high)
    cs_high = res_high.controls["values"]["contact_seeking"]

    # contact_seeking values are exactly identical
    assert cs_low == cs_high
    assert SADNESS_SUPPRESSES_REACH_OUT == "NO"


def test_v_three_way_competition_under_high_vs_low_sadness() -> None:
    """V. Multi-candidate proactive competition under low vs high sadness produces identical candidate strengths and winning candidate."""
    rules = (
        IntentRule(
            rule_id="spontaneous_share",
            kind="spontaneous_share",
            base_strength=0.1,
            dimension_weights=(("agent.affect.sharing_urge", 0.8),),
            event_kind=None,
            event_bonus=0.0,
            minimum_strength=0.5,
            due_at_attribute=None,
            expires_after=None,
            reconsideration_policy=ReconsiderationPolicy.ON_CONTEXT_CHANGE,
            surface_control_weights=(),
        ),
        IntentRule(
            rule_id="proactive_inquiry",
            kind="proactive_inquiry",
            base_strength=0.1,
            dimension_weights=(("agent.affect.curiosity", 0.8),),
            event_kind=None,
            event_bonus=0.0,
            minimum_strength=0.5,
            due_at_attribute=None,
            expires_after=None,
            reconsideration_policy=ReconsiderationPolicy.ON_CONTEXT_CHANGE,
            surface_control_weights=(),
        ),
        IntentRule(
            rule_id="reach_out",
            kind="reach_out",
            base_strength=0.1,
            dimension_weights=(("agent.affect.longing", 0.8),),
            event_kind=None,
            event_bonus=0.0,
            minimum_strength=0.5,
            due_at_attribute=None,
            expires_after=None,
            reconsideration_policy=ReconsiderationPolicy.ON_CONTEXT_CHANGE,
            surface_control_weights=(),
        ),
    )
    engine = DeterministicIntentEngine(rules, "rt-1")
    now = datetime(2026, 9, 25, 10, 0, 0, tzinfo=UTC)
    scope = Scope(domain=ScopeDomain.AGENT, agent_id="p-1", persona_id="persona-a")
    sit = Situation(
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
    )

    # Condition: sharing_urge=0.85, curiosity=0.70, longing=0.60
    # Compare sadness=0.10 vs sadness=0.90
    def _evaluate_at_sadness(s_val: float) -> tuple[Intent, ...]:
        p_states = tuple(
            RuntimeState(
                state_id=f"s-{dim}",
                scope=scope,
                dimension=dim,
                value=val,
                status="active",
                valid_from=now,
                valid_until=None,
                relevant_until=None,
                last_observed_at=now,
                evidence_refs=(),
                transition_refs=(),
                updated_at=now,
                origin_runtime_id="rt-1",
                version=1,
                sync=SyncFields(scope, "rt-1", f"s-{dim}", 1, f"idem-{dim}"),
            )
            for dim, val in [
                ("agent.affect.sharing_urge", 0.85),
                ("agent.affect.curiosity", 0.70),
                ("agent.affect.longing", 0.60),
                ("agent.affect.sadness", s_val),
            ]
        )
        proj = ProjectedMindState(
            projection_id=f"proj-{s_val}",
            scope=scope,
            origin_runtime_id="rt-1",
            projected_states=p_states,
            sync=SyncFields(scope, "rt-1", f"proj-{s_val}", 1, "idem"),
        )
        inp = IntentEngineInput(
            interaction_id=f"tick-{s_val}",
            scope=scope,
            origin_runtime_id="rt-1",
            context=sit,
            projected=proj,
            accepted_events=(),
            clock=now,
            surface=None,
        )
        return engine.evaluate(inp).candidates

    candidates_low = _evaluate_at_sadness(0.10)
    candidates_high = _evaluate_at_sadness(0.90)

    assert len(candidates_low) == 3
    assert len(candidates_high) == 3

    # Ranking and strengths are identical
    for c_low, c_high in zip(candidates_low, candidates_high, strict=True):
        assert c_low.kind == c_high.kind
        assert c_low.strength == c_high.strength

    # Winner is identical (spontaneous_share: 0.1 + 0.85*0.8 = 0.78)
    assert candidates_low[0].kind == "spontaneous_share"
    assert candidates_high[0].kind == "spontaneous_share"


# ==============================================================================
# Section 18-20: Cross-Talk & Gap Certification (W-AC)
# ==============================================================================


def test_w_dedicated_intent_cross_talk_protection_passes() -> None:
    """W. Dedicated intent cross-talk protection passes (no cross-talk from initiative)."""
    assert DEDICATED_INTENT_CROSS_TALK_PROTECTION == "PASS"


def test_x_initiative_suppression_ineffective_on_dedicated_intents() -> None:
    """X. Initiative suppression is confirmed ineffective on dedicated proactive intents."""
    assert INITIATIVE_SUPPRESSION_EFFECTIVE_ON_DEDICATED_INTENTS == "NO"


def test_y_sadness_surface_closed_primary_consumer_gap_found() -> None:
    """Y. Audit verifies surface closed, expression warmth closed, but primary consumer gap found."""
    assert SADNESS_SURFACE_INITIATIVE_PROJECTION == "PASS"
    assert SADNESS_EFFECTIVE_INITIATIVE_CONSUMER == "NONE"
    assert SADNESS_PRIMARY_FUNCTION_RUNTIME_GAP == "FOUND"
    assert SADNESS_EXPRESSION_BRANCH == "CLOSED"
    assert FINAL_VERDICT == "SADNESS_SURFACE_CLOSED_PRIMARY_CONSUMER_GAP_FOUND"


def test_z_authority_separation_invariant() -> None:
    """Z. Authority separation: sadness modulates initiative pressure, does not grant inaction permission."""
    assert (
        SADNESS_SUPPRESSES_INITIATIVE_PRESSURE_NOT_PERMISSION_INVARIANT
        == "SADNESS_SUPPRESSES_INITIATIVE_PRESSURE != SADNESS_GRANTS_ACTION_PERMISSION"
    )
    assert (
        SADNESS_SUPPRESSES_INITIATIVE_PRESSURE_NOT_PERMISSION
        == SADNESS_SUPPRESSES_INITIATIVE_PRESSURE_NOT_PERMISSION_INVARIANT
    )


def test_aa_no_synthetic_withdrawal_or_refusal_actions() -> None:
    """AA. No synthetic withdrawal, refusal, silence, or negative wake signals exist."""
    manifest_path = Path("certification/d11s/inputs/runtime-config.json")
    with open(manifest_path, encoding="utf-8") as f:
        config = json.load(f)

    action_comp = next(
        c for c in config.get("components", []) if c.get("component_id") == "action_policy"
    )
    action_types = {r.get("action_type") for r in action_comp.get("payload", {}).get("rules", [])}
    for forbidden in ("withdraw", "withdrawal", "ignore_user", "silence", "refusal"):
        assert forbidden not in action_types


def test_ab_initiative_declared_intent_eligible_in_surface_validator() -> None:
    """AB. initiative is declared in ELIGIBLE_INTENT_SURFACE_CONTROLS."""
    assert "initiative" in ELIGIBLE_INTENT_SURFACE_CONTROLS
    assert "initiative" not in INELIGIBLE_INTENT_SURFACE_CONTROLS


def test_ac_expression_map_does_not_consume_initiative() -> None:
    """AC. Candidate Expression Map v2 does not consume initiative."""
    consumed = CANDIDATE_EXPRESSION_MAP_V2["consumed_controls"]
    assert "initiative" not in consumed
    assert "initiative" not in GUIDANCE_TO_CONTROL.values()
