"""W3-D Expression, Renderer, Host, and Provider Boundary Tests.

Verifies the W3-D contract requirements:
- CANDIDATE_EXPRESSION_MAP_V2 identity and digest (bba6794aeda7a1755f8c79ffe5c88bd100918e6bc979...)
- SURFACE_V1 disables raw affect bands, duplicate style, and Host Slow numeric summary
- Qualitative guidance bundle is visible at actual provider bytes
- Provider text contains zero raw Surface floats, traits, dynamics values, or digests
- Essential bundle budget failure: if budget cannot fit the bundle, dispatch is withheld
- Surface lineage validation (runtime, projection, phase, persona, recipe digest, state version)
- ActionPolicy ALLOW required before Expression entry
- Retries reuse the same compiled DecisionContext and preserve qualitative guidance
- Provider attempt trace links controls_id, expression_map_ref, and qualitative_guidance
- Parity between internal expression provider and Host render_bounded_context
"""

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest

from mind_runtime.contracts import (
    ActionDecision,
    ActionPermission,
    ActionPolicyResult,
    ExpressionDisposition,
    ExpressionGuardResult,
    Intent,
    IntentStatus,
    ProjectedMindState,
    ReconsiderationPolicy,
    RuntimeState,
    Scope,
    ScopeDomain,
    Situation,
    SyncFields,
)
from mind_runtime.contracts.surface import SurfaceProjectionResult, SurfaceProjectionStatus
from mind_runtime.expression.context import (
    AffectBand,
    AffectExpressionRule,
    DecisionContextCompiler,
    DecisionContextCompilerInput,
    DecisionContextConfig,
)
from mind_runtime.expression.coordinator import (
    DeterministicExpressionCoordinator,
    ExpressionCoordinatorConfig,
)
from mind_runtime.expression.expression_map import (
    CANDIDATE_EXPRESSION_MAP_V2,
    CANDIDATE_MAP_DIGEST,
    CANDIDATE_MAP_ID,
    CANDIDATE_MAP_VERSION,
    compute_map_digest,
)
from mind_runtime.expression.renderer import DeterministicContextRenderer
from mind_runtime.host.runtime_adapter import _bounded_context
from mind_runtime.host.xiyue_adapter import render_bounded_context
from mind_runtime.surface import SurfaceProductionAdapter
from tests.surface.spec_support import (
    STATIC_BASELINE_EXPRESSION_BUNDLE,
    STATIC_COUNTERFACTUAL_EXPRESSION_BUNDLE,
    sample_candidate,
)


def _build_test_harness(
    persona_name: str = "persona-fixture-a",
    mode: str = "SURFACE_V1",
    max_render_chars: int = 2000,
    max_items: int = 20,
    include_affect_rules: bool = True,
    include_slow_state: bool = True,
) -> tuple[
    DecisionContextCompiler,
    DecisionContextCompilerInput,
    DeterministicContextRenderer,
    Any,
]:
    now = datetime(2026, 9, 23, 12, 0, 0, tzinfo=UTC)
    scope = Scope(domain=ScopeDomain.AGENT, agent_id="fixture-persona", persona_id=persona_name)
    runtime_id = "fixture-runtime"

    x = sample_candidate(persona_name)
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
        projection_id="projection:fixture-1",
        scope=scope,
        origin_runtime_id=runtime_id,
        projected_states=states,
        sync=SyncFields(scope, runtime_id, "projection:fixture-1", 1, "idem-proj"),
    )

    situation = Situation(
        situation_id="sit-1",
        scope=scope,
        origin_runtime_id=runtime_id,
        derived_facts=(("time.daypart", "evening"),),
        effective_state_ref="state-ref-1",
        observed_at=now,
        historical_context=None,
        persona_id=scope.persona_id,
        relationship_ids=(),
        evidence_refs=(),
    )

    intent = Intent(
        intent_id="intent-1",
        scope=scope,
        origin_runtime_id=runtime_id,
        kind="respond",
        strength=0.8,
        earliest_at=None,
        due_at=None,
        expires_at=None,
        reconsideration_policy=ReconsiderationPolicy.ON_CONTEXT_CHANGE,
        cause_refs=("assessment-1",),
        state_refs=("projection:fixture-1",),
        status=IntentStatus.ALLOWED,
        sync=SyncFields(scope, runtime_id, "intent-1", 1, "idem-intent-1"),
    )

    policy = ActionPolicyResult(
        policy_id="policy-1",
        scope=scope,
        origin_runtime_id=runtime_id,
        intent_id="intent-1",
        decision=ActionDecision.ALLOW,
        permission=ActionPermission(
            permission_id="perm-1",
            scope=scope,
            origin_runtime_id=runtime_id,
            action_type="send_message",
            allowed=True,
            reasons=("allowed",),
            constraints=("concise",),
        ),
        reason_codes=("allowed",),
    )

    affect_rules = ()
    if include_affect_rules:
        affect_rules = (
            AffectExpressionRule(
                dimension="agent.affect.anger",
                output_key="anger_level",
                bands=(AffectBand(0.5, "low"), AffectBand(1.0, "high")),
                priority=20,
            ),
        )

    slow_records = ()
    if include_slow_state:
        slow_records = (
            RuntimeState(
                state_id="slow-state-1",
                scope=scope,
                dimension="agent.slow.intimacy",
                value=0.75,
                status="active",
                valid_from=now,
                valid_until=None,
                relevant_until=None,
                last_observed_at=now,
                evidence_refs=(),
                transition_refs=(),
                updated_at=now,
                origin_runtime_id=runtime_id,
                version=1,
                sync=SyncFields(scope, runtime_id, "slow-state-1", 1, "idem-slow-1"),
            ),
        )

    config = DecisionContextConfig(
        allowed_situation_facts=("time.daypart",),
        affect_rules=affect_rules,
        persona_style_constraints=(
            (("format", "bullets"),)
            if mode == "SURFACE_V1"
            else (("tone", "warm_concise"), ("format", "bullets"))
        ),
        allowed_history_kinds=(),
        max_history_items=5,
        max_prior_expression_chars=200,
        max_item_chars=100,
        max_items=max_items,
        max_render_chars=max_render_chars,
        mode=mode,
    )

    compiler = DecisionContextCompiler(config)
    inp = DecisionContextCompilerInput(
        interaction_id="fixture-1",
        scope=scope,
        origin_runtime_id=runtime_id,
        situation=situation,
        effective_user_state=states[0],
        projected_agent_state=projected,
        assessment_trace_ref="trace-1",
        intent=intent,
        policy_result=policy,
        persona_ref=persona_name,
        prior_expression=None,
        attempt=0,
        rewrite_reason_codes=(),
        slow_state_records=slow_records,
        surface=surface,
        mode=mode,
        persona_version=x["persona"]["persona_version"],
        persona_content_digest=x["persona"]["persona_content_digest"],
    )
    renderer = DeterministicContextRenderer(config)
    return compiler, inp, renderer, surface


def test_candidate_expression_map_v2_identity_and_digest():
    """W3-D: Verify frozen expression map v2 identity, revision, and digest."""
    from mind_runtime.expression.expression_map import normalized_expression_map

    assert CANDIDATE_EXPRESSION_MAP_V2["map_id"] == "surface-v1-candidate-map"
    assert CANDIDATE_EXPRESSION_MAP_V2["map_version"] == 2
    assert CANDIDATE_MAP_ID == "surface-v1-candidate-map"
    assert CANDIDATE_MAP_VERSION == 2
    assert (
        CANDIDATE_MAP_DIGEST == "bba6794aeda7a1755f8c79ffe5c88bd100918e6bc979ea29b5aa009e958eddf3"
    )
    norm = normalized_expression_map(CANDIDATE_EXPRESSION_MAP_V2)
    assert compute_map_digest("expression-map", norm) == CANDIDATE_MAP_DIGEST

    # Ensure excluded controls are NOT in expression map instructions
    consumed = CANDIDATE_EXPRESSION_MAP_V2["consumed_controls"]
    assert "contact_seeking" not in consumed
    assert "initiative" not in consumed
    assert set(consumed) == {
        "confrontation",
        "expressive_warmth",
        "expressive_restraint",
    }
    dims = CANDIDATE_EXPRESSION_MAP_V2["guidance_dimensions"]
    assert set(dims.keys()) == {"directness", "warmth", "restraint"}


def test_expression_map_exact_boundary_partition():
    from mind_runtime.expression.expression_map import evaluate_control_band

    assert evaluate_control_band(0.329999999) == "low"
    assert evaluate_control_band(0.33) == "moderate"
    assert evaluate_control_band(0.659999999) == "moderate"
    assert evaluate_control_band(0.66) == "high"


def test_surface_v1_disables_raw_affect_bands_and_slow_numeric_summary(
    expression_surface_compiler: Any,
):
    """W3-D: In SURFACE_V1 mode, compiler omits raw affect bands and Slow numeric summaries."""
    compiler = expression_surface_compiler
    assert hasattr(compiler, "compile_surface_v1") or hasattr(compiler, "admit_surface_controls")

    # 1. In SURFACE_V1 mode:
    comp, inp, renderer, surface = _build_test_harness(mode="SURFACE_V1")
    ctx, trace = comp.compile(inp)

    # Surface guidance items must be present
    surface_items = [it for it in ctx.expression_context if it.kind.value == "surface_guidance"]
    assert len(surface_items) == 3
    surface_keys = {it.key for it in surface_items}
    assert surface_keys == {"directness", "restraint", "warmth"}

    # Raw affect bands (INTERNAL_STATE) and Slow numeric state items MUST NOT be admitted
    internal_items = [it for it in ctx.expression_context if it.kind.value == "internal_state"]
    assert len(internal_items) == 0

    # Behavioral persona style ("tone") must be stripped, non-behavioral ("format") kept
    style_items = [it for it in ctx.expression_context if it.kind.value == "persona_style"]
    style_keys = {it.key for it in style_items}
    assert "format" in style_keys
    assert "tone" not in style_keys

    # 2. In LEGACY mode for contrast:
    comp_leg, inp_leg, _, _ = _build_test_harness(mode="LEGACY")
    ctx_leg, _ = comp_leg.compile(inp_leg)

    # In LEGACY, affect rules and slow states ARE present, surface guidance is NOT
    leg_surface_items = [
        it for it in ctx_leg.expression_context if it.kind.value == "surface_guidance"
    ]
    assert len(leg_surface_items) == 0
    leg_internal_items = [
        it for it in ctx_leg.expression_context if it.kind.value == "internal_state"
    ]
    assert len(leg_internal_items) > 0


def test_surface_qualitative_bundle_visible_at_actual_provider_bytes(
    expression_surface_renderer: Any,
):
    """W3-D: Qualitative guidance (directness/warmth/restraint) must reach provider payload."""
    renderer_seam = expression_surface_renderer
    assert hasattr(renderer_seam, "render_surface_bundle") or hasattr(
        renderer_seam, "format_surface_guidance"
    )

    # Test Baseline: persona-fixture-a -> low directness, moderate warmth, moderate restraint
    comp_a, inp_a, renderer, _ = _build_test_harness("persona-fixture-a")
    ctx_a, _ = comp_a.compile(inp_a)
    rendered_a = renderer.render(ctx_a)

    # Provider text contains the section and items
    assert "[SURFACE_GUIDANCE]" in rendered_a.text or "[EXPRESSION GUIDANCE]" in rendered_a.text
    assert "directness: low" in rendered_a.text
    assert "warmth: moderate" in rendered_a.text
    assert "restraint: moderate" in rendered_a.text

    bundle_a = renderer.render_surface_bundle(ctx_a)
    assert bundle_a == STATIC_BASELINE_EXPRESSION_BUNDLE

    # Test Counterfactual: persona-fixture-b -> moderate directness, moderate warmth, low restraint
    comp_b, inp_b, _, _ = _build_test_harness("persona-fixture-b")
    ctx_b, _ = comp_b.compile(inp_b)
    rendered_b = renderer.render(ctx_b)

    assert "directness: moderate" in rendered_b.text
    assert "warmth: moderate" in rendered_b.text
    assert "restraint: low" in rendered_b.text

    bundle_b = renderer.render_surface_bundle(ctx_b)
    assert bundle_b == STATIC_COUNTERFACTUAL_EXPRESSION_BUNDLE

    # Formatter output
    formatted = renderer.format_surface_guidance(bundle_a)
    assert "directness: low" in formatted
    assert "warmth: moderate" in formatted
    assert "restraint: moderate" in formatted


def test_provider_context_contains_no_raw_numbers_or_digests(
    expression_surface_renderer: Any,
):
    """W3-D: Provider context contains zero raw floats, raw traits, raw dynamics, or digests."""
    renderer_seam = expression_surface_renderer
    assert hasattr(renderer_seam, "verify_provider_information_isolation")

    comp, inp, renderer, _ = _build_test_harness("persona-fixture-a")
    ctx, _ = comp.compile(inp)
    rendered = renderer.render(ctx)

    # The production-rendered text must pass isolation check
    assert renderer.verify_provider_information_isolation(rendered.text) is True

    # Adversarial verification: verify that the check raises on every forbidden category
    # 1. Raw floats
    with pytest.raises(AssertionError, match="raw floats"):
        renderer.verify_provider_information_isolation(rendered.text + "\nwarmth_score = 0.410")

    # 2. Raw dynamics dimension names
    with pytest.raises(AssertionError, match="raw dynamics dimension"):
        renderer.verify_provider_information_isolation(rendered.text + "\ncloseness_craving")

    # 3. Excluded surface controls
    with pytest.raises(AssertionError, match="excluded surface control"):
        renderer.verify_provider_information_isolation(rendered.text + "\ncontact_seeking: high")
    with pytest.raises(AssertionError, match="excluded surface control"):
        renderer.verify_provider_information_isolation(rendered.text + "\ninitiative: moderate")

    # 4. Raw Persona trait assignment
    with pytest.raises(AssertionError, match="raw trait"):
        renderer.verify_provider_information_isolation(rendered.text + "\nstability: 0.8")

    # 5. Cryptographic hashes (64 hex characters)
    with pytest.raises(AssertionError, match="internal content digests"):
        renderer.verify_provider_information_isolation(
            rendered.text + "\n4f37f46f89f6176fd5fefe0167ec7a81e341839f4fb9b98fa3cc348ddeaf9a55"
        )

    # 6. Slow numeric state
    with pytest.raises(AssertionError, match="slow numeric state"):
        renderer.verify_provider_information_isolation(
            rendered.text + "\nslow_state: intimacy = 0.75"
        )


def test_essential_bundle_overflow_withholds_provider_dispatch(
    expression_surface_compiler: Any,
):
    """W3-D: If prompt budget cannot accommodate essential bundle, dispatch is withheld."""
    compiler = expression_surface_compiler
    assert hasattr(compiler, "withhold_on_budget_overflow")

    # Construct harness with budget that cannot fit essential bundle
    comp_overflow, inp_overflow, _, _ = _build_test_harness(max_render_chars=10)

    # Withhold check returns True
    candidates = comp_overflow.admit_surface_controls(inp_overflow.surface, inp_overflow)
    assert (
        compiler.withhold_on_budget_overflow(candidates, comp_overflow._config, mode="SURFACE_V1")
        is True
    )

    # Compile raises ValueError withholding provider dispatch
    with pytest.raises(ValueError, match="essential context items exceed configured budget"):
        comp_overflow.compile(inp_overflow)


def test_surface_lineage_validation_and_mismatch_withholds_dispatch():
    """W3-D: DecisionContextCompiler validates surface lineage against input authority."""
    comp, inp, _, surface = _build_test_harness()

    # 1. UNAVAILABLE surface is rejected
    unavail = SurfaceProjectionResult(
        status=SurfaceProjectionStatus.UNAVAILABLE,
        reasons=["SURFACE_MISSING_STATE"],
        controls=None,
    )
    with pytest.raises(ValueError, match="Surface projection is not AVAILABLE"):
        comp.admit_surface_controls(unavail, inp)

    # 2. Runtime mismatch
    def tampered(**changes):
        def thaw(value):
            if isinstance(value, dict) or hasattr(value, "items"):
                return {key: thaw(item) for key, item in value.items()}
            if isinstance(value, (list, tuple)):
                return [thaw(item) for item in value]
            return value

        controls = thaw(surface.controls)
        controls.update(changes)
        return SurfaceProjectionResult(status="AVAILABLE", reasons=(), controls=controls)

    bad_runtime_surface = tampered(runtime_id="different-runtime")
    with pytest.raises(ValueError, match="SURFACE_LINEAGE_MISMATCH"):
        comp.admit_surface_controls(bad_runtime_surface, inp)

    # 3. Projection ID mismatch
    bad_proj_surface = tampered(source_projection_id="projection:mismatched")
    with pytest.raises(ValueError, match="SURFACE_LINEAGE_MISMATCH"):
        comp.admit_surface_controls(bad_proj_surface, inp)

    # 4. Source phase must be 'projected'
    bad_phase_surface = tampered(source_phase="canonical")
    with pytest.raises(ValueError, match="SURFACE_LINEAGE_MISMATCH"):
        comp.admit_surface_controls(bad_phase_surface, inp)

    # 5. Persona ID mismatch
    bad_persona_surface = tampered(persona_id="persona-different")
    with pytest.raises(ValueError, match="SURFACE_LINEAGE_MISMATCH"):
        comp.admit_surface_controls(bad_persona_surface, inp)
    _, _, _, coherent_other_persona = _build_test_harness("persona-fixture-b")
    with pytest.raises(ValueError, match="SURFACE_LINEAGE_MISMATCH"):
        comp.admit_surface_controls(coherent_other_persona, inp)

    # 6. Recipe digest mismatch
    bad_digest_surface = tampered(recipe_digest="0" * 64)
    with pytest.raises(ValueError, match="SURFACE_LINEAGE_MISMATCH"):
        comp.admit_surface_controls(bad_digest_surface, inp)

    # 7. State version mismatch
    bad_ver_surface = tampered(
        source_states=[
            {"dimension": "agent.affect.anger", "version": 999},
        ]
    )
    with pytest.raises(ValueError, match="SURFACE_LINEAGE_MISMATCH"):
        comp.admit_surface_controls(bad_ver_surface, inp)


@pytest.mark.parametrize(
    "style",
    [
        (("affection", "be very warm"),),
        (("attachment_approach", "0.8"),),
        (("format", "be very warm"),),
    ],
)
def test_surface_style_admission_rejects_parallel_behavioral_authority(style):
    from dataclasses import replace

    compiler, inp, _, _ = _build_test_harness(mode="SURFACE_V1")
    with pytest.raises(ValueError, match="SURFACE_STYLE_UNADMITTED"):
        replace(compiler._config, persona_style_constraints=style)
    legacy, _, _, _ = _build_test_harness(mode="LEGACY")
    with pytest.raises(ValueError, match="DECISION_CONTEXT_MODE_MISMATCH"):
        legacy.compile(replace(inp, mode="SURFACE_V1"))


def test_coordinator_retry_preserves_surface_and_records_trace():
    """W3-D: Expression coordinator retry preserves surface items and links trace metadata."""
    comp, inp, renderer, surface = _build_test_harness("persona-fixture-a")
    ctx, _ = comp.compile(inp)

    class FakeAgent:
        def respond(self, provider_context):
            return "Valid expression response."

    class FakeGuard:
        def __init__(self):
            self.count = 0

        def guard(self, guard_input):
            self.count += 1
            if self.count == 1:
                return ExpressionGuardResult(
                    guard_id="guard-1",
                    scope=guard_input.decision_context.scope,
                    origin_runtime_id=guard_input.decision_context.origin_runtime_id,
                    expression=guard_input.expression,
                    disposition=ExpressionDisposition.REWRITE,
                    violations=("forbidden_opening",),
                )
            return ExpressionGuardResult(
                guard_id="guard-1",
                scope=guard_input.decision_context.scope,
                origin_runtime_id=guard_input.decision_context.origin_runtime_id,
                expression=guard_input.expression,
                disposition=ExpressionDisposition.ACCEPT,
                violations=(),
            )

    coordinator = DeterministicExpressionCoordinator(
        config=ExpressionCoordinatorConfig(max_rewrites=2),
        compiler=comp,
        renderer=renderer,
        agent=FakeAgent(),
        guard=FakeGuard(),
    )

    outcome = coordinator.express(ctx)
    assert outcome.final_disposition == ExpressionDisposition.ACCEPT
    assert len(outcome.attempts) == 2

    # Both attempts link the controls ref, expression map ref, and qualitative guidance
    for att in outcome.attempts:
        assert att.surface_controls_ref == surface.controls["controls_id"]
        assert att.expression_map_ref == f"{CANDIDATE_MAP_ID}:{CANDIDATE_MAP_VERSION}"
        assert att.qualitative_guidance == (
            ("directness", "low"),
            ("restraint", "moderate"),
            ("warmth", "moderate"),
        )


def test_host_adapter_parity_and_isolation():
    """W3-D: Host render_bounded_context exposes qualitative guidance and passes isolation."""
    comp, inp, renderer, _ = _build_test_harness("persona-fixture-a")
    ctx, _ = comp.compile(inp)

    fake_orchestrator = SimpleNamespace(
        decision_context=ctx,
        context_renderer=renderer,
        surface_handoff_request=lambda: SimpleNamespace(
            payload_bytes=renderer.render(ctx).text.encode("utf-8"),
            surface_handoff=SimpleNamespace(context_id=ctx.context_id),
        ),
    )

    bounded = _bounded_context(fake_orchestrator)
    assert bounded is not None

    host_rendered = render_bounded_context(bounded)
    assert host_rendered is not None

    # Host text contains qualitative guidance
    assert "- directness: low" in host_rendered
    assert "- restraint: moderate" in host_rendered
    assert "- warmth: moderate" in host_rendered
    assert host_rendered == renderer.render(ctx).text
    assert "[POLICY_CONSTRAINT]" in host_rendered
    assert "- concise: concise" in host_rendered

    # Host text does NOT contain slow numeric state
    assert "slow_state:" not in host_rendered

    # Host text passes information isolation
    assert renderer.verify_provider_information_isolation(host_rendered) is True
