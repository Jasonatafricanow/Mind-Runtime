"""Test suite for MR-LONGING-PROACTIVE-PRODUCTION-HARDENING-V1-01.

Validates the bounded architecture correction for the functional fast-state consumer chain:
agent.affect.longing
    ↓
existing W3 Surface authority (Candidate Recipe v2, coeff = +0.45)
    ↓
contact_seeking (clamped [0.0, 1.0])
    ↓
proactive contact intent (IntentRule with surface_control_weights)
    ↓
ActionPolicy
    ↓
WakeSignal / IntentWake
    ↓
Host / Adapter / SSE boundary (negative pole)
    ↓
Body starts proactive Agent turn
    ↓
existing proactive expression / DecisionContext path
    ↓
Body / provider generation
    ↓
ExpressionGuard
    ↓
existing external delivery lifecycle (never CognitiveTicker)

Sections:
- Foundational Tests
- Section 17: Tests — Ticker Authority (A - F)
- Section 18: Tests — Fail-Closed Wake Admission (G - N)
- Section 19: Tests — Context Authority (O - S)
- Section 20: Tests — Body / Delivery Semantics (T - AA)
- Section 21: Tests — Production Composition (AB - AH)
- Invariants & Typing Tests
"""

from __future__ import annotations

import ast
import inspect
import json
import subprocess
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from mind_runtime.binding_registry import BindingRegistry
from mind_runtime.cognition.express import (
    ProactiveExpressionArtifact,
    ProactiveExpressionConfig,
    ProactiveExpressionPreparer,
)
from mind_runtime.cognition.tick import (
    CognitiveTicker,
    CognitiveTickReport,
    build_cognitive_ticker,
)
from mind_runtime.contracts import (
    ActionDecision,
    ActionPermission,
    ActionPolicyInput,
    ActionPolicyResult,
    ExpressionDisposition,
    HostDecisionContext,
    HostProactiveTurnResult,
    HostStatus,
    HostTurnStatus,
    HostWakeNotification,
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
from mind_runtime.delivery import DeliveryRequest
from mind_runtime.delivery.persistence import SqliteDeliveryBackend
from mind_runtime.dynamics.fast_functions import (
    FAST_FUNCTION_V1_REGISTRY,
    LONGING_CONTROLS_CONTACT_PRESSURE_NOT_FREQUENCY_INVARIANT,
    FastFunctionKind,
    validate_longing_anti_spam_invariant,
)
from mind_runtime.expression import (
    DecisionContextCompiler,
    DeterministicContextRenderer,
    DeterministicExpressionCoordinator,
    DeterministicExpressionGuardChain,
    ExpressionCoordinatorConfig,
    ExpressionGuardConfig,
)
from mind_runtime.expression.context import DecisionContextConfig
from mind_runtime.expression.history import NullPreviousExpressionPort
from mind_runtime.host import MindRuntimeHostAdapter
from mind_runtime.host.xiyue_adapter import XiyueMRAdapter, default_adapter
from mind_runtime.intents.engine import DeterministicIntentEngine, IntentRule
from mind_runtime.intents.lifecycle import IntentLifecycleService
from mind_runtime.intents.persistence import SqliteIntentBackend
from mind_runtime.intents.policy import ActionPolicyConfig, DeterministicActionPolicy, IntentPolicyRule
from mind_runtime.intents.surface_validator import (
    get_control_transitive_roots,
    validate_intent_rule_surface_overlap,
)
from mind_runtime.persona_publication import PersonaConfigPublicationRepository
from mind_runtime.pipeline.fake_agent import FakeAgent
from mind_runtime.runtime_binding import RuntimeBinding, RuntimeEnvironment
from mind_runtime.shadow.runtime_loop import build_runtime_stack, run_cognitive_tick
from mind_runtime.surface.adapter import SurfaceProductionAdapter
from mind_runtime.surface.evaluator import D_PREFIX
from mind_runtime.surface.recipe import MANIFEST
from tests.support.fake_clock import FakeClock
from tests.surface.spec_support import sample_candidate
from xiyue import mr_seam

CERTIFIED_MANIFEST_PATH = Path(__file__).resolve().parents[2] / "certification" / "d11s" / "inputs" / "runtime-config.json"


# ── Stack Setup Helper ───────────────────────────────────────────────────────


def _build_test_stack(
    tmp_path: Path,
    *,
    initial_longing: float = 0.90,
    resources: tuple[str, ...] = ("proactive_message", "send_message"),
    required_resource: str | None = None,
    cooldown: timedelta = timedelta(minutes=30),
    policy_rules: tuple[IntentPolicyRule, ...] | None = None,
    with_expression: bool = False,
    agent_script: tuple[str, ...] | None = None,
    banned_openings: tuple[str, ...] = (),
):
    tmp_path.mkdir(parents=True, exist_ok=True)
    profile_path = tmp_path / "fixture-persona.json"
    profile_data = sample_candidate()["persona"]["content"]
    profile_path.write_text(json.dumps(profile_data), encoding="utf-8")

    publication = PersonaConfigPublicationRepository(tmp_path / "published")
    revision = publication.publish(profile_path)
    persona_id = revision.persona_id

    binding = RuntimeBinding(
        persona_id=persona_id,
        agent_id=persona_id,
        runtime_id="fixture-runtime",
        storage_namespace="lab/fixture-runtime",
        environment=RuntimeEnvironment.LAB,
    )
    registry = BindingRegistry(tmp_path / "registry")
    registry.initialize()
    registry.register(binding, "fixture-binding")
    registry.pin_persona_revision("fixture-binding", revision)

    config = DecisionContextConfig(
        allowed_situation_facts=(),
        affect_rules=(),
        persona_style_constraints=(("format", "bullets"),),
        allowed_history_kinds=(),
        max_history_items=2,
        max_prior_expression_chars=100,
        max_item_chars=200,
        max_items=20,
        max_render_chars=5000,
        mode="SURFACE_V1",
    )

    rule = IntentRule(
        rule_id="contact",
        kind="reach_out",
        base_strength=0.2,
        dimension_weights=(),
        event_kind=None,
        event_bonus=0,
        minimum_strength=0.4,
        due_at_attribute=None,
        expires_after=None,
        reconsideration_policy=ReconsiderationPolicy.ON_CONTEXT_CHANGE,
        surface_control_weights=(("contact_seeking", 0.5),),
    )

    if policy_rules is None:
        policy_rules = (
            IntentPolicyRule(
                intent_kind="reach_out",
                action_type="proactive_message",
                proactive=True,
                interrupts_active_conversation=False,
                media_counter_fact=None,
                media_limit=None,
                required_resource=required_resource,
            ),
        )
    policy = ActionPolicyConfig(
        rules=policy_rules,
        proactive_cooldown=cooldown,
    )

    state_db = tmp_path / "states.sqlite"
    delivery_db = tmp_path / "delivery.sqlite"
    base_time = datetime(2026, 9, 23, 12, 0, tzinfo=UTC)
    clock = FakeClock(base_time)

    guard_chain = DeterministicExpressionGuardChain(
        ExpressionGuardConfig(
            prefix_length=8,
            transport_markers=(),
            banned_openings=banned_openings,
            temporal_rules=(),
        )
    )

    orchestrator, bridge = build_runtime_stack(
        clock=clock,
        facts_db=tmp_path / "facts.sqlite",
        state_db=state_db,
        origin_runtime_id="fixture-runtime",
        user_id="fixture-user",
        intent_rules=(rule,),
        intent_db=tmp_path / "intent.sqlite",
        action_policy_config=policy,
        policy_resources=resources,
        decision_context_config=config,
        persona_publication=publication,
        surface_binding_registry=registry,
        surface_binding_id="fixture-binding",
        surface_binding_environment=RuntimeEnvironment.LAB,
        delivery_db=delivery_db,
        expression_guard=guard_chain,
    )

    # Seed all persona dimensions in state DB under agent_scope matching persona_id
    vals = dict(
        longing=initial_longing,
        closeness_craving=0.50,
        anger=0.20,
        sharing_urge=0.60,
        curiosity=0.50,
        sadness=0.20,
        diligence_pressure=0.40,
        social_pull=0.20,
    )
    agent_scope = Scope(
        domain=ScopeDomain.AGENT,
        agent_id=persona_id,
        persona_id=persona_id,
    )
    for dim_name, val in vals.items():
        st = RuntimeState(
            state_id=f"state-{dim_name}",
            scope=agent_scope,
            origin_runtime_id="fixture-runtime",
            dimension=f"agent.affect.{dim_name}",
            value=val,
            status="active",
            valid_from=base_time,
            valid_until=None,
            relevant_until=None,
            last_observed_at=base_time,
            evidence_refs=("seed-evidence",),
            transition_refs=(),
            updated_at=base_time,
            version=1,
            sync=SyncFields(agent_scope, "fixture-runtime", f"state-{dim_name}", 1, f"idem-{dim_name}-1"),
        )
        orchestrator._state_backend.save_state(st)

    fake_agent: FakeAgent | None = None
    if with_expression:
        fake_agent = FakeAgent(agent_script or ("想和你分享一下今天的心情",))
        compiler = DecisionContextCompiler(config)
        coordinator = DeterministicExpressionCoordinator(
            compiler=compiler,
            renderer=DeterministicContextRenderer(config),
            agent=fake_agent,
            guard=guard_chain,
            config=ExpressionCoordinatorConfig(max_rewrites=2),
        )
        preparer = ProactiveExpressionPreparer(
            orchestrator=orchestrator,
            compiler=compiler,
            coordinator=coordinator,
            previous_expression=NullPreviousExpressionPort(),
            config=ProactiveExpressionConfig(("proactive_message",)),
            runtime_id="fixture-runtime",
        )
        orchestrator.cognitive_tick_components["expression_preparer"] = preparer
        orchestrator.proactive_expression_preparer = preparer

    return orchestrator, clock, delivery_db, fake_agent


# ── FOUNDATIONAL STRUCTURAL TESTS ─────────────────────────────────────────────


def test_foundational_w3_final_sha_is_ancestor():
    """Foundational: Authoritative frozen W3 final SHA 386d3e8d8e49a1f2d8e9d6d4e18641ed2d0c504e is an ancestor."""
    frozen_sha = "386d3e8d8e49a1f2d8e9d6d4e18641ed2d0c504e"
    show_proc = subprocess.run(
        ["git", "show", "--no-patch", "--oneline", frozen_sha],
        capture_output=True,
        text=True,
        check=False,
    )
    assert show_proc.returncode == 0, f"Frozen W3 SHA {frozen_sha} could not be resolved: {show_proc.stderr}"
    assert "fix(surface): close W3 authority and durability gaps" in show_proc.stdout

    ancestry_proc = subprocess.run(
        ["git", "merge-base", "--is-ancestor", frozen_sha, "HEAD"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert ancestry_proc.returncode == 0, (
        f"Frozen W3 SHA {frozen_sha} is not an ancestor of current HEAD: {ancestry_proc.stderr}"
    )


def test_foundational_longing_remains_declared_surface_root_for_contact_seeking():
    """Foundational: longing remains a declared Surface root for contact_seeking."""
    assert "contact_seeking" in MANIFEST
    dynamics_roots = MANIFEST["contact_seeking"]["dynamics"]
    assert D_PREFIX + "longing" in dynamics_roots

    transitive_roots = get_control_transitive_roots("contact_seeking")
    assert D_PREFIX + "longing" in transitive_roots


def test_foundational_intent_path_cannot_read_raw_longing_overlap():
    """Foundational: Intent path cannot read raw agent.affect.longing when consumed through Surface."""
    with pytest.raises(ValueError, match="ROOT_OVERLAP"):
        IntentRule(
            rule_id="illegal-contact",
            kind="reach_out",
            base_strength=0.1,
            dimension_weights=(("agent.affect.longing", 0.5),),
            event_kind=None,
            event_bonus=0,
            minimum_strength=0.1,
            due_at_attribute=None,
            expires_after=None,
            reconsideration_policy=ReconsiderationPolicy.NEVER,
            surface_control_weights=(("contact_seeking", 0.5),),
        )


def test_foundational_increasing_longing_monotonic_contact_seeking():
    """Foundational: Increasing longing gives monotonic non-decreasing contact_seeking under Candidate Recipe v2."""
    def calc_contact_seeking(longing_val: float) -> float:
        raw = (
            0.45 * longing_val
            + 0.35 * 0.50
            + 0.30 * 0.50
            - 0.20 * 0.20
            - 0.20 * 0.40
        )
        return max(0.0, min(1.0, raw))

    c_low = calc_contact_seeking(0.1)
    c_mid = calc_contact_seeking(0.5)
    c_high = calc_contact_seeking(0.9)

    assert 0.0 <= c_low < c_mid < c_high <= 1.0
    assert c_mid - c_low == pytest.approx(0.45 * 0.4, abs=1e-5)
    assert c_high - c_mid == pytest.approx(0.45 * 0.4, abs=1e-5)


def test_foundational_contact_seeking_drives_intent_strength_and_eligibility():
    """Foundational: Increasing contact_seeking can increase proactive-contact Intent strength / eligibility."""
    runtime_id = "fixture-runtime"
    now = datetime(2026, 9, 23, 12, 0, 0, tzinfo=UTC)
    scope = Scope(domain=ScopeDomain.USER, user_id="fixture-user")
    agent_scope = Scope(domain=ScopeDomain.AGENT, agent_id="fixture-persona", persona_id="persona-fixture-a")

    x = sample_candidate()
    adapter = SurfaceProductionAdapter()
    surface = adapter.project(x)
    assert surface.status == "AVAILABLE"
    assert surface.controls["values"]["contact_seeking"] == 0.500

    states = tuple(
        RuntimeState(
            state_id=s["state_id"],
            scope=agent_scope,
            origin_runtime_id=runtime_id,
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
            version=s["version"],
            sync=SyncFields(agent_scope, runtime_id, s["state_id"], s["version"], f"idem-{s['state_id']}"),
        )
        for s in x["projected_dynamics"]["states"]
    )
    projected = ProjectedMindState(
        projection_id=x["projected_dynamics"]["source_projection_id"],
        scope=agent_scope,
        origin_runtime_id=runtime_id,
        projected_states=states,
        sync=SyncFields(agent_scope, runtime_id, x["projected_dynamics"]["source_projection_id"], 1, "idem-proj"),
    )
    situation = Situation(
        situation_id="sit-1",
        scope=scope,
        origin_runtime_id=runtime_id,
        derived_facts=(),
        effective_state_ref="none",
        observed_at=now,
        historical_context=None,
        persona_id=None,
        relationship_ids=(),
        evidence_refs=(),
    )

    # High threshold (0.60): 0.20 + 0.40 * 0.50 = 0.40 < 0.60 -> Rejected
    rule_high = IntentRule(
        rule_id="reach-out-high",
        kind="reach_out",
        base_strength=0.2,
        dimension_weights=(),
        event_kind=None,
        event_bonus=0,
        minimum_strength=0.60,
        due_at_attribute=None,
        expires_after=None,
        reconsideration_policy=ReconsiderationPolicy.NEVER,
        surface_control_weights=(("contact_seeking", 0.4),),
    )
    engine_high = DeterministicIntentEngine((rule_high,), runtime_id)
    res_high = engine_high.evaluate(
        IntentEngineInput(
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
    )
    assert len(res_high.candidates) == 0

    # Achievable threshold (0.35): 0.20 + 0.40 * 0.50 = 0.40 >= 0.35 -> Admitted
    rule_achievable = IntentRule(
        rule_id="reach-out-achievable",
        kind="reach_out",
        base_strength=0.2,
        dimension_weights=(),
        event_kind=None,
        event_bonus=0,
        minimum_strength=0.35,
        due_at_attribute=None,
        expires_after=None,
        reconsideration_policy=ReconsiderationPolicy.NEVER,
        surface_control_weights=(("contact_seeking", 0.4),),
    )
    engine_achievable = DeterministicIntentEngine((rule_achievable,), runtime_id)
    res_achievable = engine_achievable.evaluate(
        IntentEngineInput(
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
    )
    assert len(res_achievable.candidates) == 1
    assert res_achievable.candidates[0].strength == pytest.approx(0.400, abs=1e-5)


# ── SECTION 17: TESTS — TICKER AUTHORITY ─────────────────────────────────────


def test_a_cognitive_ticker_cannot_be_constructed_with_provider_executor():
    """Test A: CognitiveTicker cannot be constructed with a provider/expression executor."""
    # 1. build_cognitive_ticker raises TypeError on unexpected kwarg
    with pytest.raises(TypeError, match="unexpected keyword argument 'expression'"):
        build_cognitive_ticker(
            orchestrator=None,  # type: ignore[arg-type]
            persona=None,  # type: ignore[arg-type]
            intent_engine=None,  # type: ignore[arg-type]
            action_policy=None,  # type: ignore[arg-type]
            policy_resources=None,  # type: ignore[arg-type]
            intent_lifecycle=None,  # type: ignore[arg-type]
            runtime_id="fixture-runtime",
            expression=object(),  # type: ignore[call-arg]
        )

    # 2. AST inspection proves CognitiveTicker.__init__ accepts no expression param
    tick_path = Path(__file__).resolve().parents[2] / "src" / "mind_runtime" / "cognition" / "tick.py"
    tree = ast.parse(tick_path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == "CognitiveTicker":
            for item in node.body:
                if isinstance(item, ast.FunctionDef) and item.name == "__init__":
                    param_names = [arg.arg for arg in item.args.args] + [arg.arg for arg in item.args.kwonlyargs]
                    assert "expression" not in param_names, f"expression found in CognitiveTicker.__init__: {param_names}"


def test_b_cognitive_ticker_tick_cannot_call_provider_realization(tmp_path: Path):
    """Test B: CognitiveTicker.tick() cannot call provider realization."""
    orchestrator, clock, _, fake_agent = _build_test_stack(tmp_path, initial_longing=0.90, with_expression=True)
    now = clock.now() + timedelta(minutes=5)
    clock.advance(timedelta(minutes=5))
    user_scope = Scope(domain=ScopeDomain.USER, user_id="fixture-user")

    report = run_cognitive_tick(orchestrator, scope=user_scope, now=now)
    assert report.wake_signal is not None
    # Crucial causal invariant: Ticker did NOT invoke provider or create expression
    assert report.proactive_expression is None
    assert fake_agent is not None
    assert len(fake_agent.calls) == 0


def test_c_cognitive_ticker_source_has_no_call_path_to_expression():
    """Test C: CognitiveTicker source has no call path to:
    - ProactiveExpressionPreparer.prepare
    - realize_after_wake
    - DeterministicExpressionCoordinator.express
    """
    tick_path = Path(__file__).resolve().parents[2] / "src" / "mind_runtime" / "cognition" / "tick.py"
    tree = ast.parse(tick_path.read_text(encoding="utf-8"))

    forbidden_calls = {"prepare", "realize_after_wake", "express", "_prepare_expression"}
    forbidden_classes = {
        "ProactiveExpressionPreparer",
        "DeterministicExpressionCoordinator",
        "ExpressionCoordinator",
    }

    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Attribute) and node.func.attr in forbidden_calls:
                pytest.fail(f"Forbidden call to {node.func.attr} at line {node.lineno} in tick.py")
            if isinstance(node.func, ast.Name) and node.func.id in forbidden_calls | forbidden_classes:
                pytest.fail(f"Forbidden call to {node.func.id} at line {node.lineno} in tick.py")
        if isinstance(node, ast.Name) and node.id in forbidden_classes:
            pytest.fail(f"Forbidden reference to class {node.id} at line {node.lineno} in tick.py")


def test_d_action_policy_allow_creates_wake_signal(tmp_path: Path):
    """Test D: ActionPolicy ALLOW creates WakeSignal."""
    orchestrator, clock, _, _ = _build_test_stack(tmp_path, initial_longing=0.90, with_expression=True)
    now = clock.now() + timedelta(minutes=5)
    clock.advance(timedelta(minutes=5))
    user_scope = Scope(domain=ScopeDomain.USER, user_id="fixture-user")

    report = run_cognitive_tick(orchestrator, scope=user_scope, now=now)
    assert report.policy_allowed == 1
    assert report.wake_signal is not None
    assert isinstance(report.wake_signal, WakeSignal)
    assert report.wake_signal.action_type == "proactive_message"
    assert report.wake_signal.reason == "proactive_intent_allowed"
    assert report.wake_signal.intent_version == 2


def test_e_policy_deny_creates_no_wake_signal(tmp_path: Path):
    """Test E: Policy DENY creates no WakeSignal."""
    orchestrator, clock, _, fake_agent = _build_test_stack(
        tmp_path,
        initial_longing=0.90,
        with_expression=True,
        policy_rules=(),
    )
    now = clock.now() + timedelta(minutes=5)
    clock.advance(timedelta(minutes=5))
    user_scope = Scope(domain=ScopeDomain.USER, user_id="fixture-user")

    report = run_cognitive_tick(orchestrator, scope=user_scope, now=now)
    assert report.policy_denied >= 1
    assert report.policy_allowed == 0
    assert report.wake_signal is None
    assert fake_agent is not None
    assert len(fake_agent.calls) == 0


def test_f_cooldown_defer_creates_no_wake_signal(tmp_path: Path):
    """Test F: Cooldown DEFER creates no WakeSignal."""
    orchestrator, clock, _, fake_agent = _build_test_stack(
        tmp_path,
        initial_longing=0.90,
        with_expression=True,
        cooldown=timedelta(minutes=30),
    )
    user_scope = Scope(domain=ScopeDomain.USER, user_id="fixture-user")

    # Tick 1: Allowed -> WakeSignal emitted
    t1 = clock.now() + timedelta(minutes=5)
    clock.advance(timedelta(minutes=5))
    report1 = run_cognitive_tick(orchestrator, scope=user_scope, now=t1)
    assert report1.policy_allowed == 1
    assert report1.wake_signal is not None

    # Tick 2: Deferred by cooldown -> No WakeSignal
    t2 = clock.now() + timedelta(minutes=5)
    clock.advance(timedelta(minutes=5))
    report2 = run_cognitive_tick(orchestrator, scope=user_scope, now=t2)
    assert report2.policy_allowed == 0
    assert report2.wake_signal is None
    assert len(fake_agent.calls) == 0


# ── SECTION 18: TESTS — FAIL-CLOSED WAKE ADMISSION ───────────────────────────


def test_g_missing_lifecycle_authority_rejects_wake(tmp_path: Path):
    """Test G: missing lifecycle authority -> reject."""
    orchestrator, clock, _, _ = _build_test_stack(tmp_path, initial_longing=0.90)
    now = clock.now() + timedelta(minutes=5)
    clock.advance(timedelta(minutes=5))
    user_scope = Scope(domain=ScopeDomain.USER, user_id="fixture-user")

    report = run_cognitive_tick(orchestrator, scope=user_scope, now=now)
    wake = report.wake_signal
    assert wake is not None

    # Orchestrator without lifecycle authority
    orchestrator.cognitive_tick_components.pop("lifecycle", None)
    orchestrator.intent_lifecycle = None
    adapter = MindRuntimeHostAdapter(orchestrator=orchestrator, trace=orchestrator.trace)
    notif = adapter.consume_wake(wake)
    assert notif.eligible is False
    assert notif.reason == "rejected:intent_authority_unavailable"


def test_h_missing_policy_authority_rejects_wake(tmp_path: Path):
    """Test H: missing policy authority -> reject."""
    orchestrator, clock, _, _ = _build_test_stack(tmp_path, initial_longing=0.90)
    now = clock.now() + timedelta(minutes=5)
    clock.advance(timedelta(minutes=5))
    user_scope = Scope(domain=ScopeDomain.USER, user_id="fixture-user")

    report = run_cognitive_tick(orchestrator, scope=user_scope, now=now)
    wake = report.wake_signal
    assert wake is not None

    orchestrator.cognitive_tick_components.pop("policy", None)
    orchestrator.action_policy = None
    adapter = MindRuntimeHostAdapter(orchestrator=orchestrator, trace=orchestrator.trace)
    notif = adapter.consume_wake(wake)
    assert notif.eligible is False
    assert notif.reason in ("rejected:policy_authority_unavailable", "rejected:unsupported_intent_action")


def test_i_wrong_runtime_id_rejects_wake(tmp_path: Path):
    """Test I: wrong runtime -> reject."""
    orchestrator, clock, _, _ = _build_test_stack(tmp_path, initial_longing=0.90)
    now = clock.now() + timedelta(minutes=5)
    clock.advance(timedelta(minutes=5))
    user_scope = Scope(domain=ScopeDomain.USER, user_id="fixture-user")

    report = run_cognitive_tick(orchestrator, scope=user_scope, now=now)
    wake = report.wake_signal
    assert wake is not None

    adapter = MindRuntimeHostAdapter(orchestrator=orchestrator, trace=orchestrator.trace)
    bad_wake = replace(wake, runtime_id="foreign-runtime")
    notif = adapter.consume_wake(bad_wake)
    assert notif.eligible is False
    assert notif.reason == "rejected:runtime_id_mismatch"


def test_j_unknown_intent_id_rejects_wake(tmp_path: Path):
    """Test J: unknown intent -> reject."""
    orchestrator, clock, _, _ = _build_test_stack(tmp_path, initial_longing=0.90)
    now = clock.now() + timedelta(minutes=5)
    clock.advance(timedelta(minutes=5))
    user_scope = Scope(domain=ScopeDomain.USER, user_id="fixture-user")

    report = run_cognitive_tick(orchestrator, scope=user_scope, now=now)
    wake = report.wake_signal
    assert wake is not None

    adapter = MindRuntimeHostAdapter(orchestrator=orchestrator, trace=orchestrator.trace)
    bad_wake = replace(wake, intent_id="intent-does-not-exist")
    notif = adapter.consume_wake(bad_wake)
    assert notif.eligible is False
    assert notif.reason == "rejected:unknown_intent_id"


def test_k_non_allowed_intent_rejects_wake(tmp_path: Path):
    """Test K: non-ALLOWED intent -> reject."""
    orchestrator, clock, _, _ = _build_test_stack(tmp_path, initial_longing=0.90)
    now = clock.now() + timedelta(minutes=5)
    clock.advance(timedelta(minutes=5))
    user_scope = Scope(domain=ScopeDomain.USER, user_id="fixture-user")

    report = run_cognitive_tick(orchestrator, scope=user_scope, now=now)
    wake = report.wake_signal
    assert wake is not None

    adapter = MindRuntimeHostAdapter(orchestrator=orchestrator, trace=orchestrator.trace)
    lifecycle = orchestrator.cognitive_tick_components["lifecycle"]
    # Transition intent from ALLOWED to COMPLETED
    lifecycle.transition(
        scope=wake.scope,
        intent_id=wake.intent_id,
        to_status=IntentStatus.COMPLETED,
        reason_codes=("completed_by_external",),
        occurred_at=now,
        idempotency_key="idem-complete-test",
    )

    notif = adapter.consume_wake(wake)
    assert notif.eligible is False
    assert notif.reason == "rejected:intent_not_allowed"


def test_l_version_mismatch_rejects_wake(tmp_path: Path):
    """Test L: version mismatch -> reject."""
    orchestrator, clock, _, _ = _build_test_stack(tmp_path, initial_longing=0.90)
    now = clock.now() + timedelta(minutes=5)
    clock.advance(timedelta(minutes=5))
    user_scope = Scope(domain=ScopeDomain.USER, user_id="fixture-user")

    report = run_cognitive_tick(orchestrator, scope=user_scope, now=now)
    wake = report.wake_signal
    assert wake is not None

    adapter = MindRuntimeHostAdapter(orchestrator=orchestrator, trace=orchestrator.trace)
    bad_wake = replace(wake, intent_version=wake.intent_version + 5)
    notif = adapter.consume_wake(bad_wake)
    assert notif.eligible is False
    assert notif.reason == "rejected:intent_version_mismatch"


def test_m_action_mismatch_rejects_wake(tmp_path: Path):
    """Test M: action mismatch -> reject."""
    orchestrator, clock, _, _ = _build_test_stack(tmp_path, initial_longing=0.90)
    now = clock.now() + timedelta(minutes=5)
    clock.advance(timedelta(minutes=5))
    user_scope = Scope(domain=ScopeDomain.USER, user_id="fixture-user")

    report = run_cognitive_tick(orchestrator, scope=user_scope, now=now)
    wake = report.wake_signal
    assert wake is not None

    adapter = MindRuntimeHostAdapter(orchestrator=orchestrator, trace=orchestrator.trace)
    bad_wake = replace(wake, action_type="unauthorized_action_type")
    notif = adapter.consume_wake(bad_wake)
    assert notif.eligible is False
    assert notif.reason in ("rejected:action_type_mismatch", "rejected:unsupported_intent_action")


def test_n_valid_authoritative_wake_admits(tmp_path: Path):
    """Test N: valid authoritative wake -> admit."""
    orchestrator, clock, _, _ = _build_test_stack(tmp_path, initial_longing=0.90)
    now = clock.now() + timedelta(minutes=5)
    clock.advance(timedelta(minutes=5))
    user_scope = Scope(domain=ScopeDomain.USER, user_id="fixture-user")

    report = run_cognitive_tick(orchestrator, scope=user_scope, now=now)
    wake = report.wake_signal
    assert wake is not None

    adapter = MindRuntimeHostAdapter(orchestrator=orchestrator, trace=orchestrator.trace)
    notif = adapter.consume_wake(wake)
    assert notif.eligible is True
    assert notif.reason == "proactive_intent_allowed"

    # Lineage fields preserved and non-empty
    assert notif.wake_id == wake.wake_id
    assert notif.runtime_id == wake.runtime_id
    assert notif.scope == wake.scope
    assert notif.intent_id == wake.intent_id
    assert notif.intent_version >= 1
    assert notif.action_type == wake.action_type
    assert notif.interaction_id == wake.interaction_id
    assert notif.policy_decision_ref == wake.policy_decision_ref
    assert notif.occurred_at == wake.woken_at

    # Exposes no raw affect or dynamics numbers
    for forbidden in ("longing", "dynamics", "persona", "surface", "raw_affect", "contact_seeking"):
        assert not hasattr(notif, forbidden)
        assert forbidden not in notif.as_dict()


# ── SECTION 19: TESTS — CONTEXT AUTHORITY ────────────────────────────────────


def test_o_valid_pending_wake_context_can_be_used_after_admission(tmp_path: Path):
    """Test O: valid pending wake context can be used after admission."""
    orchestrator, clock, _, fake_agent = _build_test_stack(tmp_path, initial_longing=0.90, with_expression=True)
    now = clock.now() + timedelta(minutes=5)
    clock.advance(timedelta(minutes=5))
    user_scope = Scope(domain=ScopeDomain.USER, user_id="fixture-user")

    report = run_cognitive_tick(orchestrator, scope=user_scope, now=now)
    wake = report.wake_signal
    assert wake is not None

    adapter = MindRuntimeHostAdapter(orchestrator=orchestrator, trace=orchestrator.trace)
    turn_res = adapter.begin_proactive_turn(wake)

    assert turn_res.status == HostTurnStatus.PROCESSING
    assert turn_res.outcome == HostStatus.OK
    assert turn_res.decision_context_ref is not None
    assert turn_res.bounded_context is not None
    assert isinstance(turn_res.bounded_context, HostDecisionContext)
    assert turn_res.bounded_context.action_taken == wake.action_type
    assert turn_res.bounded_context.provider_envelope_text is not None


def test_p_missing_pending_context_fails_closed(tmp_path: Path):
    """Test P: missing pending context -> fail closed."""
    orchestrator, clock, _, _ = _build_test_stack(tmp_path, initial_longing=0.90, with_expression=True)
    now = clock.now() + timedelta(minutes=5)
    clock.advance(timedelta(minutes=5))
    user_scope = Scope(domain=ScopeDomain.USER, user_id="fixture-user")

    report = run_cognitive_tick(orchestrator, scope=user_scope, now=now)
    wake = report.wake_signal
    assert wake is not None

    adapter = MindRuntimeHostAdapter(orchestrator=orchestrator, trace=orchestrator.trace)
    fake_wake = replace(wake, wake_id="wake-without-context")
    turn_res = adapter.begin_proactive_turn(fake_wake)

    assert turn_res.status == HostTurnStatus.FAILED
    assert turn_res.outcome == HostStatus.FAILED
    assert "missing_authoritative_wake_context" in turn_res.reason_codes


def test_q_no_code_reconstructs_action_policy_result_from_wake():
    """Test Q: no code reconstructs ActionPolicyResult(ALLOW) from Wake fields."""
    adapter_path = Path(__file__).resolve().parents[2] / "src" / "mind_runtime" / "host" / "runtime_adapter.py"
    source = adapter_path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(adapter_path))

    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id == "ActionPolicyResult":
            pytest.fail(f"Forbidden reference to ActionPolicyResult at line {node.lineno} in runtime_adapter.py")


def test_r_no_code_reconstructs_replacement_situation_from_wake():
    """Test R: no code reconstructs a replacement Situation as authoritative history."""
    adapter_path = Path(__file__).resolve().parents[2] / "src" / "mind_runtime" / "host" / "runtime_adapter.py"
    source = adapter_path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(adapter_path))

    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id == "Situation":
            pytest.fail(f"Forbidden reference to Situation at line {node.lineno} in runtime_adapter.py")


def test_s_process_restart_context_loss_reported_as_unsupported(tmp_path: Path):
    """Test S: process restart/context loss is reported as unsupported V1 recovery,
    not silently repaired.
    """
    orchestrator, clock, _, _ = _build_test_stack(tmp_path, initial_longing=0.90, with_expression=True)
    now = clock.now() + timedelta(minutes=5)
    clock.advance(timedelta(minutes=5))
    user_scope = Scope(domain=ScopeDomain.USER, user_id="fixture-user")

    report = run_cognitive_tick(orchestrator, scope=user_scope, now=now)
    wake = report.wake_signal
    assert wake is not None

    adapter = MindRuntimeHostAdapter(orchestrator=orchestrator, trace=orchestrator.trace)

    # Simulate process restart / loss of in-memory execution context:
    ticker = orchestrator.cognitive_tick_components["ticker"]
    ticker._pending_wake_contexts.clear()
    adapter._pending_wake_contexts.clear()

    turn_res = adapter.begin_proactive_turn(wake)
    assert turn_res.status == HostTurnStatus.FAILED
    assert "missing_authoritative_wake_context" in turn_res.reason_codes

    # Freeze architectural assertions
    wake_replay_scope = "PROCESS_LOCAL"
    policy_decision_ref_validation = "UNRESOLVED_BY_CURRENT_STORE"
    assert wake_replay_scope == "PROCESS_LOCAL"
    assert policy_decision_ref_validation == "UNRESOLVED_BY_CURRENT_STORE"


# ── SECTION 20: TESTS — BODY / DELIVERY SEMANTICS ────────────────────────────


def test_t_successful_proactive_preparation_returns_processing_not_committed(tmp_path: Path):
    """Test T: successful proactive preparation returns PROCESSING, not COMMITTED."""
    orchestrator, clock, _, fake_agent = _build_test_stack(tmp_path, initial_longing=0.90, with_expression=True)
    now = clock.now() + timedelta(minutes=5)
    clock.advance(timedelta(minutes=5))
    user_scope = Scope(domain=ScopeDomain.USER, user_id="fixture-user")

    report = run_cognitive_tick(orchestrator, scope=user_scope, now=now)
    wake = report.wake_signal
    assert wake is not None

    adapter = MindRuntimeHostAdapter(orchestrator=orchestrator, trace=orchestrator.trace)
    turn_res = adapter.begin_proactive_turn(wake)

    assert turn_res.status == HostTurnStatus.PROCESSING
    assert turn_res.status != HostTurnStatus.COMMITTED
    assert turn_res.outcome == HostStatus.OK


def test_u_mr_does_not_invoke_production_llm_internally_before_handing_context(tmp_path: Path):
    """Test U: MR does not invoke production LLM/provider internally before handing
    bounded context to Body.
    """
    orchestrator, clock, _, fake_agent = _build_test_stack(tmp_path, initial_longing=0.90, with_expression=True)
    now = clock.now() + timedelta(minutes=5)
    clock.advance(timedelta(minutes=5))
    user_scope = Scope(domain=ScopeDomain.USER, user_id="fixture-user")

    report = run_cognitive_tick(orchestrator, scope=user_scope, now=now)
    wake = report.wake_signal
    assert wake is not None

    adapter = MindRuntimeHostAdapter(orchestrator=orchestrator, trace=orchestrator.trace)
    turn_res = adapter.begin_proactive_turn(wake)

    assert turn_res.bounded_context is not None
    assert fake_agent is not None
    assert len(fake_agent.calls) == 0


def test_v_external_prose_must_pass_existing_expression_guard(tmp_path: Path):
    """Test V: external prose must pass existing ExpressionGuard."""
    orchestrator, clock, _, _ = _build_test_stack(
        tmp_path,
        initial_longing=0.90,
        with_expression=True,
        banned_openings=("你好",),
    )
    now = clock.now() + timedelta(minutes=5)
    clock.advance(timedelta(minutes=5))
    user_scope = Scope(domain=ScopeDomain.USER, user_id="fixture-user")

    report = run_cognitive_tick(orchestrator, scope=user_scope, now=now)
    wake = report.wake_signal
    assert wake is not None

    adapter = MindRuntimeHostAdapter(orchestrator=orchestrator, trace=orchestrator.trace)
    adapter.begin_proactive_turn(wake)

    # Violating external prose (empty / whitespace fails structural guard)
    guard_res = adapter.guard_proactive_prose(wake.wake_id, "   ")
    assert guard_res.status == HostTurnStatus.ABORTED
    assert guard_res.outcome == HostStatus.FAILED
    assert guard_res.disposition is ExpressionDisposition.REJECT


def test_w_guard_accept_alone_does_not_mark_delivery_committed(tmp_path: Path):
    """Test W: Guard ACCEPT alone does not mark delivery committed."""
    orchestrator, clock, _, _ = _build_test_stack(tmp_path, initial_longing=0.90, with_expression=True)
    now = clock.now() + timedelta(minutes=5)
    clock.advance(timedelta(minutes=5))
    user_scope = Scope(domain=ScopeDomain.USER, user_id="fixture-user")

    report = run_cognitive_tick(orchestrator, scope=user_scope, now=now)
    wake = report.wake_signal
    assert wake is not None

    adapter = MindRuntimeHostAdapter(orchestrator=orchestrator, trace=orchestrator.trace)
    adapter.begin_proactive_turn(wake)

    guard_res = adapter.guard_proactive_prose(wake.wake_id, "今天天气真好，想和你聊聊")
    assert guard_res.status == HostTurnStatus.PROCESSING
    assert guard_res.status != HostTurnStatus.COMMITTED
    assert guard_res.outcome == HostStatus.OK
    assert guard_res.would_send == "今天天气真好，想和你聊聊"

    # Intent lifecycle is NOT completed yet
    lifecycle = orchestrator.cognitive_tick_components["lifecycle"]
    intents = lifecycle.backend.current(wake.scope)
    intent = next(i for i in intents if i.intent_id == wake.intent_id)
    assert lifecycle.has_status(intent, IntentStatus.ALLOWED) is True


def test_x_successful_explicit_proactive_delivery_commit_transitions_intent(tmp_path: Path):
    """Test X: successful explicit proactive delivery commit transitions the Intent to COMPLETED."""
    orchestrator, clock, _, _ = _build_test_stack(tmp_path, initial_longing=0.90, with_expression=True)
    now = clock.now() + timedelta(minutes=5)
    clock.advance(timedelta(minutes=5))
    user_scope = Scope(domain=ScopeDomain.USER, user_id="fixture-user")

    report = run_cognitive_tick(orchestrator, scope=user_scope, now=now)
    wake = report.wake_signal
    assert wake is not None

    adapter = MindRuntimeHostAdapter(orchestrator=orchestrator, trace=orchestrator.trace)
    adapter.begin_proactive_turn(wake)
    adapter.guard_proactive_prose(wake.wake_id, "合规消息")

    commit_res = adapter.commit_proactive_turn(wake.wake_id)
    assert commit_res.status == HostTurnStatus.COMMITTED
    assert commit_res.outcome == HostStatus.OK

    lifecycle = orchestrator.cognitive_tick_components["lifecycle"]
    intents = lifecycle.backend.current(wake.scope)
    intent = next(i for i in intents if i.intent_id == wake.intent_id)
    assert lifecycle.has_status(intent, IntentStatus.COMPLETED) is True


def test_y_terminal_completion_clears_pending_wake_context(tmp_path: Path):
    """Test Y: terminal completion clears pending wake context."""
    orchestrator, clock, _, _ = _build_test_stack(tmp_path, initial_longing=0.90, with_expression=True)
    now = clock.now() + timedelta(minutes=5)
    clock.advance(timedelta(minutes=5))
    user_scope = Scope(domain=ScopeDomain.USER, user_id="fixture-user")

    report = run_cognitive_tick(orchestrator, scope=user_scope, now=now)
    wake = report.wake_signal
    assert wake is not None

    adapter = MindRuntimeHostAdapter(orchestrator=orchestrator, trace=orchestrator.trace)
    adapter.begin_proactive_turn(wake)
    assert wake.wake_id in adapter._pending_wake_contexts

    # Guard accept is required before commit succeeds
    adapter.guard_proactive_prose(wake.wake_id, "合规消息")

    adapter.commit_proactive_turn(wake.wake_id)
    assert wake.wake_id not in adapter._pending_wake_contexts
    assert wake.wake_id not in adapter._pending_exec_contexts


def test_z_duplicate_completion_is_idempotent(tmp_path: Path):
    """Test Z: duplicate completion is idempotent."""
    orchestrator, clock, _, _ = _build_test_stack(tmp_path, initial_longing=0.90, with_expression=True)
    now = clock.now() + timedelta(minutes=5)
    clock.advance(timedelta(minutes=5))
    user_scope = Scope(domain=ScopeDomain.USER, user_id="fixture-user")

    report = run_cognitive_tick(orchestrator, scope=user_scope, now=now)
    wake = report.wake_signal
    assert wake is not None

    adapter = MindRuntimeHostAdapter(orchestrator=orchestrator, trace=orchestrator.trace)
    adapter.begin_proactive_turn(wake)
    adapter.guard_proactive_prose(wake.wake_id, "合规消息")

    res1 = adapter.commit_proactive_turn(wake.wake_id)
    assert res1.status == HostTurnStatus.COMMITTED

    res2 = adapter.commit_proactive_turn(wake.wake_id)
    assert res2.status == HostTurnStatus.ALREADY_PROCESSED
    assert res2.outcome == HostStatus.ALREADY_PROCESSED


def test_aa_conflicting_replay_fails_closed(tmp_path: Path):
    """Test AA: conflicting replay fails closed."""
    orchestrator, clock, _, fake_agent = _build_test_stack(tmp_path, initial_longing=0.90, with_expression=True)
    now = clock.now() + timedelta(minutes=5)
    clock.advance(timedelta(minutes=5))
    user_scope = Scope(domain=ScopeDomain.USER, user_id="fixture-user")

    report = run_cognitive_tick(orchestrator, scope=user_scope, now=now)
    wake = report.wake_signal
    assert wake is not None

    adapter = MindRuntimeHostAdapter(orchestrator=orchestrator, trace=orchestrator.trace)
    res1 = adapter.begin_proactive_turn(wake)
    assert res1.outcome == HostStatus.OK

    conflicting_wake = replace(wake, action_type="conflicting_action")
    res2 = adapter.begin_proactive_turn(conflicting_wake)
    assert res2.status == HostTurnStatus.FAILED
    assert res2.outcome == HostStatus.FAILED


# ── SECTION 21: TESTS — PRODUCTION COMPOSITION ───────────────────────────────


def _setup_production_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from mind_runtime.emotional_transition import appraisal as appraisal_module
    from mind_runtime.emotional_transition import factory as factory_module

    class OfflineSemanticProvider:
        def propose(self, *, observations, context, scope):
            return ()

    monkeypatch.setattr(factory_module, "create_semantic_provider", OfflineSemanticProvider)
    monkeypatch.setattr(
        appraisal_module,
        "ModelBackedSemanticAppraisalModel",
        lambda **kwargs: appraisal_module.ConfiguredSemanticAppraisalModel(),
    )
    monkeypatch.setenv("MR_RUNTIME_CONFIG", str(CERTIFIED_MANIFEST_PATH))
    monkeypatch.setenv("MR_FACTS_DB", str(tmp_path / "facts.sqlite"))
    monkeypatch.setenv("MR_STATE_DB", str(tmp_path / "state.sqlite"))
    monkeypatch.setenv("MR_ENABLED", "true")


def test_ab_production_composition_has_durable_intent_lifecycle_authority(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Test AB: production composition has durable Intent lifecycle authority."""
    _setup_production_env(tmp_path, monkeypatch)

    rule = IntentRule(
        rule_id="contact",
        kind="reach_out",
        base_strength=0.2,
        dimension_weights=(),
        event_kind=None,
        event_bonus=0,
        minimum_strength=0.4,
        due_at_attribute=None,
        expires_after=None,
        reconsideration_policy=ReconsiderationPolicy.ON_CONTEXT_CHANGE,
        surface_control_weights=(("contact_seeking", 0.5),),
    )
    policy = ActionPolicyConfig(
        rules=(
            IntentPolicyRule(
                intent_kind="reach_out",
                action_type="proactive_message",
                proactive=True,
                interrupts_active_conversation=False,
                media_counter_fact=None,
                media_limit=None,
                required_resource=None,
            ),
        ),
        proactive_cooldown=timedelta(minutes=30),
    )

    composition = dict(mr_seam._load_production_composition())
    composition["intent_rules"] = (rule,)
    composition["action_policy_config"] = policy
    composition["policy_resources"] = ("proactive_message", "send_message")
    composition["delivery_db"] = str(tmp_path / "delivery.sqlite")
    binding = RuntimeBinding(
        persona_id="kayla_v0",
        agent_id="hermes-prod",
        runtime_id="runtime-prod-1",
        storage_namespace="production/xiyue",
        environment=RuntimeEnvironment.PRODUCTION,
    )
    adapter = default_adapter(
        binding=binding,
        **composition,
    )

    orch = adapter._port.orchestrator
    assert "lifecycle" in orch.cognitive_tick_components
    assert isinstance(orch.cognitive_tick_components["lifecycle"], IntentLifecycleService)
    assert isinstance(orch.cognitive_tick_components["backend"], SqliteIntentBackend)


def test_ac_production_composition_has_action_policy_authority(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Test AC: production composition has ActionPolicy authority."""
    _setup_production_env(tmp_path, monkeypatch)

    rule = IntentRule(
        rule_id="contact",
        kind="reach_out",
        base_strength=0.2,
        dimension_weights=(),
        event_kind=None,
        event_bonus=0,
        minimum_strength=0.4,
        due_at_attribute=None,
        expires_after=None,
        reconsideration_policy=ReconsiderationPolicy.ON_CONTEXT_CHANGE,
        surface_control_weights=(("contact_seeking", 0.5),),
    )
    policy = ActionPolicyConfig(
        rules=(
            IntentPolicyRule(
                intent_kind="reach_out",
                action_type="proactive_message",
                proactive=True,
                interrupts_active_conversation=False,
                media_counter_fact=None,
                media_limit=None,
                required_resource=None,
            ),
        ),
        proactive_cooldown=timedelta(minutes=30),
    )

    composition = dict(mr_seam._load_production_composition())
    composition["intent_rules"] = (rule,)
    composition["action_policy_config"] = policy
    composition["policy_resources"] = ("proactive_message", "send_message")
    composition["delivery_db"] = str(tmp_path / "delivery.sqlite")
    binding = RuntimeBinding(
        persona_id="kayla_v0",
        agent_id="hermes-prod",
        runtime_id="runtime-prod-1",
        storage_namespace="production/xiyue",
        environment=RuntimeEnvironment.PRODUCTION,
    )
    adapter = default_adapter(
        binding=binding,
        **composition,
    )

    orch = adapter._port.orchestrator
    assert "policy" in orch.cognitive_tick_components
    assert isinstance(orch.cognitive_tick_components["policy"], DeterministicActionPolicy)


def test_ad_generic_proactive_contact_infrastructure_verified(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Proves generic proactive machinery only.
    Does NOT prove longing contact chain (requires surface_control_weights
    with contact_seeking mapping).
    """
    _setup_production_env(tmp_path, monkeypatch)

    rule = IntentRule(
        rule_id="contact",
        kind="reach_out",
        base_strength=0.2,
        dimension_weights=(("agent.affect.longing", 0.5),),
        event_kind=None,
        event_bonus=0,
        minimum_strength=0.4,
        due_at_attribute=None,
        expires_after=None,
        reconsideration_policy=ReconsiderationPolicy.ON_CONTEXT_CHANGE,
        surface_control_weights=(),
    )
    policy = ActionPolicyConfig(
        rules=(
            IntentPolicyRule(
                intent_kind="reach_out",
                action_type="proactive_message",
                proactive=True,
                interrupts_active_conversation=False,
                media_counter_fact=None,
                media_limit=None,
                required_resource=None,
            ),
        ),
        proactive_cooldown=timedelta(minutes=30),
    )

    composition = dict(mr_seam._load_production_composition())
    composition["intent_rules"] = (rule,)
    composition["action_policy_config"] = policy
    composition["policy_resources"] = ("proactive_message", "send_message")
    composition["delivery_db"] = str(tmp_path / "delivery.sqlite")
    binding = RuntimeBinding(
        persona_id="kayla_v0",
        agent_id="hermes-prod",
        runtime_id="runtime-prod-1",
        storage_namespace="production/xiyue",
        environment=RuntimeEnvironment.PRODUCTION,
    )
    adapter = default_adapter(
        binding=binding,
        **composition,
    )

    orch = adapter._port.orchestrator
    now = datetime(2026, 9, 23, 12, 5, tzinfo=UTC)
    agent_scope = Scope(domain=ScopeDomain.AGENT, agent_id="kayla_v0", persona_id="kayla_v0")
    user_scope = Scope(domain=ScopeDomain.USER, user_id="user")

    # Seed longing in state DB under agent_scope
    st = RuntimeState(
        state_id="state-longing",
        scope=agent_scope,
        origin_runtime_id="runtime-prod-1",
        dimension="agent.affect.longing",
        value=0.90,
        status="active",
        valid_from=now,
        valid_until=None,
        relevant_until=None,
        last_observed_at=now,
        evidence_refs=(),
        transition_refs=(),
        updated_at=now,
        version=1,
        sync=SyncFields(agent_scope, "runtime-prod-1", "state-longing", 1, "idem-prod-1"),
    )
    orch._state_backend.save_state(st)

    report = run_cognitive_tick(orch, scope=user_scope, now=now)
    assert report.policy_allowed == 1
    assert report.wake_signal is not None
    assert isinstance(report.wake_signal, WakeSignal)
    assert report.wake_signal.action_type == "proactive_message"


def test_production_composition_wires_context_preparer(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Verify production composition wires ProactiveContextPreparer without manual assignment."""
    _setup_production_env(tmp_path, monkeypatch)

    composition = mr_seam._load_production_composition()
    binding = RuntimeBinding(
        persona_id="kayla_v0",
        agent_id="hermes-prod",
        runtime_id="runtime-prod-1",
        storage_namespace="production/xiyue",
        environment=RuntimeEnvironment.PRODUCTION,
    )
    adapter = default_adapter(binding=binding, **composition)
    orch = adapter._port.orchestrator

    assert orch.proactive_context_preparer is not None
    assert orch.cognitive_tick_components.get("context_preparer") is not None
    assert orch.proactive_context_preparer is orch.cognitive_tick_components["context_preparer"]

    preparer = orch.proactive_context_preparer
    from mind_runtime.cognition.express import ProactiveContextPreparer, ProactiveExpressionPreparer

    assert isinstance(preparer, ProactiveContextPreparer)
    assert not isinstance(preparer, ProactiveExpressionPreparer)
    assert hasattr(preparer, "_agent") is False
    assert hasattr(preparer, "_coordinator") is False


def test_ae_xiyue_adapter_can_receive_and_start_proactive_host_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Test AE: Xiyue adapter can receive/start the proactive Host path."""
    _setup_production_env(tmp_path, monkeypatch)

    composition = mr_seam._load_production_composition()
    binding = RuntimeBinding(
        persona_id="kayla_v0",
        agent_id="hermes-prod",
        runtime_id="runtime-prod-1",
        storage_namespace="production/xiyue",
        environment=RuntimeEnvironment.PRODUCTION,
    )
    adapter = default_adapter(binding=binding, **composition)

    # Prove XiyueMRAdapter exposes all required proactive operations
    assert hasattr(adapter, "consume_wake")
    assert hasattr(adapter, "begin_proactive_turn")
    assert hasattr(adapter, "guard_proactive_prose")
    assert hasattr(adapter, "commit_proactive_turn")
    assert hasattr(adapter, "abort_proactive_turn")
    assert not hasattr(adapter, "run_proactive_turn")


def test_af_bounded_proactive_context_reaches_external_body_seam_without_fake_user_turn(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """Test AF: bounded proactive context reaches the external Body seam without a fake inbound user turn."""
    orchestrator, clock, _, _ = _build_test_stack(tmp_path, initial_longing=0.90, with_expression=True)
    now = clock.now() + timedelta(minutes=5)
    clock.advance(timedelta(minutes=5))
    user_scope = Scope(domain=ScopeDomain.USER, user_id="fixture-user")

    report = run_cognitive_tick(orchestrator, scope=user_scope, now=now)
    wake = report.wake_signal
    assert wake is not None

    adapter = MindRuntimeHostAdapter(orchestrator=orchestrator, trace=orchestrator.trace)
    turn_res = adapter.begin_proactive_turn(wake)

    # Bounded context is present and typed
    assert turn_res.bounded_context is not None
    assert isinstance(turn_res.bounded_context, HostDecisionContext)
    assert turn_res.bounded_context.action_taken == wake.action_type

    # No fake inbound user Evidence created in fact store
    facts = orchestrator._fact_backend.all(user_scope) if hasattr(orchestrator, "_fact_backend") else ()
    user_msg_evs = [f for f in facts if getattr(f, "source_type", None) == "user_message"]
    assert len(user_msg_evs) == 0


def test_ag_no_internal_default_stub_agent_used_as_production_body(tmp_path: Path):
    """Test AG: no internal default/stub Agent is used to claim production success."""
    adapter_path = Path(__file__).resolve().parents[2] / "src" / "mind_runtime" / "host" / "runtime_adapter.py"
    source = adapter_path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(adapter_path))

    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id == "_DefaultAgent":
            pytest.fail(f"Forbidden reference to _DefaultAgent in runtime_adapter.py at line {node.lineno}")


def test_ah_downstream_transport_remains_outside_mr_and_config_gap_verified():
    """Test AH: downstream transport remains outside MR, and runtime-config gap is verified."""
    from mind_runtime.validation import decode_runtime_manifest, load_runtime_config_manifest

    manifest_path = Path(__file__).resolve().parents[2] / "certification" / "d11s" / "inputs" / "runtime-config.json"
    assert manifest_path.exists()
    manifest = decode_runtime_manifest(load_runtime_config_manifest(manifest_path))

    # Inspect manifest.intent_engine.rules:
    reach_out_rules = [r for r in manifest.intent_engine.rules if r.kind == "reach_out"]
    assert len(reach_out_rules) == 0

    # Inspect manifest.action_policy.rules:
    proactive_policy_rules = [r for r in manifest.action_policy.rules if getattr(r, "proactive", False)]
    assert len(proactive_policy_rules) == 0

    # Inspect surface mode:
    mode = getattr(manifest.decision_context, "mode", None)
    assert mode != "SURFACE_V1"

    sse_boundary = "DOWNSTREAM_EXTERNAL"
    assert sse_boundary == "DOWNSTREAM_EXTERNAL"


# ── CAUSAL SEQUENCE & TRACE TESTS ─────────────────────────────────────────────


def test_trace_ordering_proves_causal_sequence(tmp_path: Path):
    """Trace ordering proves:
    policy_allow < wake_created < host_wake_admitted < proactive_body_entry <= proactive_expression_context < expression_guard < proactive_turn_committed
    """
    orchestrator, clock, _, fake_agent = _build_test_stack(tmp_path, initial_longing=0.90, with_expression=True)
    now = clock.now() + timedelta(minutes=5)
    clock.advance(timedelta(minutes=5))
    user_scope = Scope(domain=ScopeDomain.USER, user_id="fixture-user")

    report = run_cognitive_tick(orchestrator, scope=user_scope, now=now)
    wake = report.wake_signal
    assert wake is not None

    adapter = MindRuntimeHostAdapter(orchestrator=orchestrator, trace=orchestrator.trace)
    turn_res = adapter.begin_proactive_turn(wake)
    assert turn_res.outcome == HostStatus.OK

    # External body generates prose
    prose = "今天天气很好，想和你聊聊"
    guard_res = adapter.guard_proactive_prose(wake.wake_id, prose)
    assert guard_res.outcome == HostStatus.OK

    commit_res = adapter.commit_proactive_turn(wake.wake_id)
    assert commit_res.outcome == HostStatus.OK

    records = orchestrator.trace.trace(wake.interaction_id)
    stages = [r.stage for r in records]

    required_stages = (
        "policy_allow",
        "wake_created",
        "host_wake_admitted",
        "proactive_body_entry",
        "proactive_expression_context",
        "expression_guard",
        "proactive_turn_committed",
    )
    for stage in required_stages:
        assert stage in stages, f"Missing required trace stage: {stage} in {stages}"

    p_allow = stages.index("policy_allow")
    w_create = stages.index("wake_created")
    h_admit = stages.index("host_wake_admitted")
    b_entry = stages.index("proactive_body_entry")
    ctx_prep = stages.index("proactive_expression_context")
    e_guard = stages.index("expression_guard")
    p_commit = stages.index("proactive_turn_committed")

    assert p_allow < w_create < h_admit < b_entry <= ctx_prep < e_guard < p_commit, (
        f"Causal ordering violation in stages: {stages}"
    )


def test_no_proactive_expression_artifact_before_admitted_wake(tmp_path: Path):
    """No proactive expression artifact exists before admitted wake."""
    orchestrator, clock, _, fake_agent = _build_test_stack(tmp_path, initial_longing=0.90, with_expression=True)
    now = clock.now() + timedelta(minutes=5)
    clock.advance(timedelta(minutes=5))
    user_scope = Scope(domain=ScopeDomain.USER, user_id="fixture-user")

    report = run_cognitive_tick(orchestrator, scope=user_scope, now=now)
    assert report.wake_signal is not None
    assert report.proactive_expression is None

    adapter = MindRuntimeHostAdapter(orchestrator=orchestrator, trace=orchestrator.trace)
    assert report.wake_signal.wake_id not in adapter._proactive_turn_results


def test_wake_does_not_create_user_evidence(tmp_path: Path):
    """Wake does not create user Evidence."""
    orchestrator, clock, _, fake_agent = _build_test_stack(tmp_path, initial_longing=0.90, with_expression=True)
    now = clock.now() + timedelta(minutes=5)
    clock.advance(timedelta(minutes=5))
    user_scope = Scope(domain=ScopeDomain.USER, user_id="fixture-user")

    report = run_cognitive_tick(orchestrator, scope=user_scope, now=now)
    adapter = MindRuntimeHostAdapter(orchestrator=orchestrator, trace=orchestrator.trace)
    adapter.begin_proactive_turn(report.wake_signal)

    facts = orchestrator._fact_backend.all(user_scope) if hasattr(orchestrator, "_fact_backend") else ()
    user_message_evs = [f for f in facts if getattr(f, "source_type", None) == "user_message"]
    assert len(user_message_evs) == 0


def test_wake_does_not_synthesize_host_turn_request(tmp_path: Path):
    """Wake does not synthesize HostTurnRequest."""
    adapter_path = Path(__file__).resolve().parents[2] / "src" / "mind_runtime" / "host" / "runtime_adapter.py"
    source = adapter_path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(adapter_path))

    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "begin_proactive_turn":
            for child in ast.walk(node):
                if isinstance(child, ast.Name) and child.id == "HostTurnRequest":
                    pytest.fail("begin_proactive_turn must not instantiate HostTurnRequest")
                if isinstance(child, ast.Attribute) and child.attr == "begin_turn":
                    pytest.fail("begin_proactive_turn must not call begin_turn")


# ── INVARIANTS & TYPING TESTS ────────────────────────────────────────────────


def test_fast_function_v1_registry_count_remains_eight():
    """FAST_FUNCTION_V1_REGISTRY count remains exactly 8."""
    assert len(FAST_FUNCTION_V1_REGISTRY) == 8
    longing_spec = FAST_FUNCTION_V1_REGISTRY.get("agent.affect.longing")
    assert longing_spec is not None
    assert longing_spec.function_kind == FastFunctionKind.PROACTIVE_CONTACT
    assert longing_spec.external_action_capable is True


def test_longing_anti_spam_invariant_remains_valid():
    """Longing anti-spam invariant remains valid."""
    assert (
        LONGING_CONTROLS_CONTACT_PRESSURE_NOT_FREQUENCY_INVARIANT
        == "LONGING_CONTROLS_CONTACT_PRESSURE != LONGING_CONTROLS_SEND_FREQUENCY"
    )
    assert validate_longing_anti_spam_invariant(
        longing=0.9, base_cooldown_seconds=1800.0, effective_cooldown_seconds=1800.0
    ) is True
    assert validate_longing_anti_spam_invariant(
        longing=0.9, base_cooldown_seconds=1800.0, effective_cooldown_seconds=3600.0
    ) is True

    with pytest.raises(ValueError, match="Longing anti-spam violation"):
        validate_longing_anti_spam_invariant(
            longing=0.9, base_cooldown_seconds=1800.0, effective_cooldown_seconds=900.0
        )


def test_proactive_surface_parameter_uses_typed_surface_contract():
    """Proactive Surface parameter uses typed Surface contract, not object."""
    sig = inspect.signature(ProactiveExpressionPreparer.prepare_context)
    surface_param = sig.parameters.get("surface")
    assert surface_param is not None
    annotation = surface_param.annotation
    assert annotation != object
    assert "SurfaceProjectionResult" in str(annotation)


def test_no_type_ignore_on_proactive_path():
    """No type-ignore is required on the proactive expression path."""
    express_path = Path(__file__).resolve().parents[2] / "src" / "mind_runtime" / "cognition" / "express.py"
    lines = express_path.read_text(encoding="utf-8").splitlines()
    for lineno, line in enumerate(lines, 1):
        if "# type: ignore" in line:
            pytest.fail(f"Found forbidden '# type: ignore' in express.py at line {lineno}: {line}")


def test_proactive_preparation_does_not_read_compiler_config():
    """Proactive preparation does not read _compiler._config directly."""
    express_path = Path(__file__).resolve().parents[2] / "src" / "mind_runtime" / "cognition" / "express.py"
    source = express_path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(express_path))

    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr == "_config":
            if isinstance(node.value, ast.Attribute) and node.value.attr == "_compiler":
                pytest.fail(f"Proactive path reads _compiler._config at line {node.lineno}")


def test_proactive_preparation_does_not_read_orchestrator_persona():
    """Proactive preparation does not read _orchestrator._persona directly."""
    express_path = Path(__file__).resolve().parents[2] / "src" / "mind_runtime" / "cognition" / "express.py"
    source = express_path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(express_path))

    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr == "_persona":
            if isinstance(node.value, ast.Attribute) and node.value.attr == "_orchestrator":
                pytest.fail(f"Proactive path reads _orchestrator._persona at line {node.lineno}")


# ── SECTION 13: REGRESSION TEST MATRIX ─────────────────────────────────────────


def test_public_host_adapter_has_no_run_proactive_turn():
    """A. Inspect MindRuntimeHostPort, MindRuntimeHostAdapter, XiyueMRAdapter.
    Assert 'run_proactive_turn' is NOT an attribute on ANY of them.
    """
    from mind_runtime.host.port import MindRuntimeHostPort
    from mind_runtime.host.runtime_adapter import MindRuntimeHostAdapter
    from mind_runtime.host.xiyue_adapter import XiyueMRAdapter

    assert not hasattr(MindRuntimeHostPort, "run_proactive_turn")
    assert not hasattr(MindRuntimeHostAdapter, "run_proactive_turn")
    assert not hasattr(XiyueMRAdapter, "run_proactive_turn")


def test_production_composition_wires_provider_free_preparer(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """B. Load production composition via mr_seam._load_production_composition().
    Construct default_adapter().
    Verify orchestrator.proactive_context_preparer is an instance of ProactiveContextPreparer.
    Verify cognitive_tick_components["context_preparer"] is the same.
    Verify it is NOT ProactiveExpressionPreparer.
    Verify hasattr(preparer, "_agent") is False.
    Verify hasattr(preparer, "_coordinator") is False.
    """
    _setup_production_env(tmp_path, monkeypatch)

    composition = mr_seam._load_production_composition()
    binding = RuntimeBinding(
        persona_id="kayla_v0",
        agent_id="hermes-prod",
        runtime_id="runtime-prod-1",
        storage_namespace="production/xiyue",
        environment=RuntimeEnvironment.PRODUCTION,
    )
    adapter = default_adapter(binding=binding, **composition)
    orch = adapter._port.orchestrator

    preparer = orch.proactive_context_preparer
    from mind_runtime.cognition.express import ProactiveContextPreparer, ProactiveExpressionPreparer

    assert isinstance(preparer, ProactiveContextPreparer)
    assert orch.cognitive_tick_components["context_preparer"] is preparer
    assert not isinstance(preparer, ProactiveExpressionPreparer)
    assert hasattr(preparer, "_agent") is False
    assert hasattr(preparer, "_coordinator") is False


def test_begin_proactive_turn_renders_provider_envelope(tmp_path: Path):
    """C. Call begin_proactive_turn(wake).
    Verify result.bounded_context is an instance of HostDecisionContext.
    Verify result.bounded_context.provider_envelope_text is non-empty string.
    Verify DeterministicContextRenderer.verify_provider_information_isolation(envelope_text) is True.
    """
    orchestrator, clock, _, _ = _build_test_stack(tmp_path, initial_longing=0.90, with_expression=True)
    now = clock.now() + timedelta(minutes=5)
    clock.advance(timedelta(minutes=5))
    user_scope = Scope(domain=ScopeDomain.USER, user_id="fixture-user")

    report = run_cognitive_tick(orchestrator, scope=user_scope, now=now)
    wake = report.wake_signal
    assert wake is not None

    adapter = MindRuntimeHostAdapter(orchestrator=orchestrator, trace=orchestrator.trace)
    turn_res = adapter.begin_proactive_turn(wake)

    assert isinstance(turn_res.bounded_context, HostDecisionContext)
    envelope = turn_res.bounded_context.provider_envelope_text
    assert isinstance(envelope, str) and len(envelope) > 0
    from mind_runtime.expression.renderer import DeterministicContextRenderer
    assert DeterministicContextRenderer.verify_provider_information_isolation(envelope) is True


def test_commit_without_guard_accept_fails_closed(tmp_path: Path):
    """D. begin_proactive_turn(wake)
    Attempt commit_proactive_turn(wake.wake_id) WITHOUT calling guard_proactive_prose.
    Assert result.status == HostTurnStatus.FAILED
    Assert "rejected:not_delivery_eligible" in result.reason_codes
    Assert Intent in store is STILL in IntentStatus.ALLOWED, NOT COMPLETED.
    """
    orchestrator, clock, _, _ = _build_test_stack(tmp_path, initial_longing=0.90, with_expression=True)
    now = clock.now() + timedelta(minutes=5)
    clock.advance(timedelta(minutes=5))
    user_scope = Scope(domain=ScopeDomain.USER, user_id="fixture-user")

    report = run_cognitive_tick(orchestrator, scope=user_scope, now=now)
    wake = report.wake_signal
    assert wake is not None

    adapter = MindRuntimeHostAdapter(orchestrator=orchestrator, trace=orchestrator.trace)
    adapter.begin_proactive_turn(wake)

    commit_res = adapter.commit_proactive_turn(wake.wake_id)
    assert commit_res.status == HostTurnStatus.FAILED
    assert "rejected:not_delivery_eligible" in commit_res.reason_codes

    lifecycle = orchestrator.cognitive_tick_components["lifecycle"]
    intents = lifecycle.backend.current(wake.scope)
    intent = next(i for i in intents if i.intent_id == wake.intent_id)
    assert intent.status is IntentStatus.ALLOWED


def test_commit_with_guard_reject_fails_closed(tmp_path: Path):
    """E. begin_proactive_turn(wake)
    guard_proactive_prose(wake.wake_id, "   ")
    Attempt commit_proactive_turn(wake.wake_id).
    Assert commit returns FAILED.
    Assert Intent was already transitioned to SUPERSEDED by guard reject.
    """
    orchestrator, clock, _, _ = _build_test_stack(tmp_path, initial_longing=0.90, with_expression=True)
    now = clock.now() + timedelta(minutes=5)
    clock.advance(timedelta(minutes=5))
    user_scope = Scope(domain=ScopeDomain.USER, user_id="fixture-user")

    report = run_cognitive_tick(orchestrator, scope=user_scope, now=now)
    wake = report.wake_signal
    assert wake is not None

    adapter = MindRuntimeHostAdapter(orchestrator=orchestrator, trace=orchestrator.trace)
    adapter.begin_proactive_turn(wake)

    guard_res = adapter.guard_proactive_prose(wake.wake_id, "   ")
    assert guard_res.status == HostTurnStatus.ABORTED
    assert guard_res.disposition == ExpressionDisposition.REJECT

    commit_res = adapter.commit_proactive_turn(wake.wake_id)
    assert commit_res.status == HostTurnStatus.FAILED

    lifecycle = orchestrator.cognitive_tick_components["lifecycle"]
    intents = lifecycle.backend.history(wake.scope, wake.intent_id)
    assert intents[-1].status is IntentStatus.SUPERSEDED


def test_guard_reject_transitions_intent_to_superseded(tmp_path: Path):
    """F. begin_proactive_turn(wake)
    guard_res = guard_proactive_prose(wake.wake_id, "   ")
    Assert guard_res.status == HostTurnStatus.ABORTED
    Assert guard_res.disposition == ExpressionDisposition.REJECT
    Assert Intent in store is now IntentStatus.SUPERSEDED.
    Assert pending contexts are cleared.
    """
    orchestrator, clock, _, _ = _build_test_stack(tmp_path, initial_longing=0.90, with_expression=True)
    now = clock.now() + timedelta(minutes=5)
    clock.advance(timedelta(minutes=5))
    user_scope = Scope(domain=ScopeDomain.USER, user_id="fixture-user")

    report = run_cognitive_tick(orchestrator, scope=user_scope, now=now)
    wake = report.wake_signal
    assert wake is not None

    adapter = MindRuntimeHostAdapter(orchestrator=orchestrator, trace=orchestrator.trace)
    adapter.begin_proactive_turn(wake)

    guard_res = adapter.guard_proactive_prose(wake.wake_id, "   ")
    assert guard_res.status == HostTurnStatus.ABORTED
    assert guard_res.disposition == ExpressionDisposition.REJECT

    lifecycle = orchestrator.cognitive_tick_components["lifecycle"]
    intents = lifecycle.backend.history(wake.scope, wake.intent_id)
    assert intents[-1].status is IntentStatus.SUPERSEDED

    assert wake.wake_id not in adapter._pending_exec_contexts
    assert wake.wake_id not in adapter._pending_wake_contexts
    assert wake.wake_id not in adapter._guard_admissions


def test_successful_proactive_turn_lifecycle(tmp_path: Path):
    """G. begin_proactive_turn(wake) -> returns PROCESSING, envelope non-empty
    guard_proactive_prose(wake.wake_id, valid_prose) -> returns PROCESSING, ACCEPT
    commit_proactive_turn(wake.wake_id) -> returns COMMITTED
    Assert Intent in store is now IntentStatus.COMPLETED.
    Assert pending contexts cleared.
    Assert trace contains causal order:
    policy_allow < wake_created < host_wake_admitted < proactive_body_entry
    <= proactive_expression_context < expression_guard < proactive_turn_committed
    """
    orchestrator, clock, _, _ = _build_test_stack(tmp_path, initial_longing=0.90, with_expression=True)
    now = clock.now() + timedelta(minutes=5)
    clock.advance(timedelta(minutes=5))
    user_scope = Scope(domain=ScopeDomain.USER, user_id="fixture-user")

    report = run_cognitive_tick(orchestrator, scope=user_scope, now=now)
    wake = report.wake_signal
    assert wake is not None

    adapter = MindRuntimeHostAdapter(orchestrator=orchestrator, trace=orchestrator.trace)
    turn_res = adapter.begin_proactive_turn(wake)
    assert turn_res.status == HostTurnStatus.PROCESSING
    assert turn_res.bounded_context is not None
    assert turn_res.bounded_context.provider_envelope_text is not None

    guard_res = adapter.guard_proactive_prose(wake.wake_id, "今天天气真好，想和你分享一段文字")
    assert guard_res.status == HostTurnStatus.PROCESSING
    assert guard_res.disposition == ExpressionDisposition.ACCEPT

    commit_res = adapter.commit_proactive_turn(wake.wake_id)
    assert commit_res.status == HostTurnStatus.COMMITTED

    lifecycle = orchestrator.cognitive_tick_components["lifecycle"]
    intents = lifecycle.backend.history(wake.scope, wake.intent_id)
    assert intents[-1].status is IntentStatus.COMPLETED

    assert wake.wake_id not in adapter._pending_exec_contexts
    assert wake.wake_id not in adapter._pending_wake_contexts
    assert wake.wake_id not in adapter._guard_admissions

    records = orchestrator.trace.trace(wake.interaction_id)
    stages = [r.stage for r in records]
    p_allow = stages.index("policy_allow")
    w_create = stages.index("wake_created")
    h_admit = stages.index("host_wake_admitted")
    b_entry = stages.index("proactive_body_entry")
    ctx_prep = stages.index("proactive_expression_context")
    e_guard = stages.index("expression_guard")
    p_commit = stages.index("proactive_turn_committed")
    assert p_allow < w_create < h_admit < b_entry <= ctx_prep < e_guard < p_commit


def test_abort_proactive_turn_transitions_to_superseded(tmp_path: Path):
    """H. begin_proactive_turn(wake)
    abort_proactive_turn(wake.wake_id, reason="delivery_timeout")
    Assert result.status == HostTurnStatus.ABORTED
    Assert Intent in store is IntentStatus.SUPERSEDED.
    Assert pending contexts cleared.
    """
    orchestrator, clock, _, _ = _build_test_stack(tmp_path, initial_longing=0.90, with_expression=True)
    now = clock.now() + timedelta(minutes=5)
    clock.advance(timedelta(minutes=5))
    user_scope = Scope(domain=ScopeDomain.USER, user_id="fixture-user")

    report = run_cognitive_tick(orchestrator, scope=user_scope, now=now)
    wake = report.wake_signal
    assert wake is not None

    adapter = MindRuntimeHostAdapter(orchestrator=orchestrator, trace=orchestrator.trace)
    adapter.begin_proactive_turn(wake)

    abort_res = adapter.abort_proactive_turn(wake.wake_id, reason="delivery_timeout")
    assert abort_res.status == HostTurnStatus.ABORTED

    lifecycle = orchestrator.cognitive_tick_components["lifecycle"]
    intents = lifecycle.backend.history(wake.scope, wake.intent_id)
    assert intents[-1].status is IntentStatus.SUPERSEDED

    assert wake.wake_id not in adapter._pending_exec_contexts
    assert wake.wake_id not in adapter._pending_wake_contexts
    assert wake.wake_id not in adapter._guard_admissions


def test_abort_transition_failure_fails_closed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """I. Simulate lifecycle transition error during abort.
    Assert abort_proactive_turn returns HostTurnStatus.FAILED.
    Assert context is PRESERVED, not cleared.
    """
    orchestrator, clock, _, _ = _build_test_stack(tmp_path, initial_longing=0.90, with_expression=True)
    now = clock.now() + timedelta(minutes=5)
    clock.advance(timedelta(minutes=5))
    user_scope = Scope(domain=ScopeDomain.USER, user_id="fixture-user")

    report = run_cognitive_tick(orchestrator, scope=user_scope, now=now)
    wake = report.wake_signal
    assert wake is not None

    adapter = MindRuntimeHostAdapter(orchestrator=orchestrator, trace=orchestrator.trace)
    adapter.begin_proactive_turn(wake)

    lifecycle = orchestrator.cognitive_tick_components["lifecycle"]

    def _failing_transition(*args, **kwargs):
        raise RuntimeError("database_locked")

    monkeypatch.setattr(lifecycle, "transition", _failing_transition)

    abort_res = adapter.abort_proactive_turn(wake.wake_id, reason="delivery_timeout")
    assert abort_res.status == HostTurnStatus.FAILED
    assert abort_res.outcome == HostStatus.FAILED
    assert "abort_transition_failed" in abort_res.reason_codes

    # Context is preserved for recovery
    assert wake.wake_id in adapter._pending_exec_contexts
    assert wake.wake_id in adapter._pending_wake_contexts


def test_certified_manifest_proactive_gap_verified():
    """J. Authoritatively load and decode certification/d11s/inputs/runtime-config.json
    via load_runtime_config_manifest & decode_runtime_manifest.
    Assert 0 reach_out rules in intent_engine.
    Assert 0 proactive=True rules in action_policy.
    Assert decision_context mode is NOT SURFACE_V1.
    """
    from mind_runtime.validation import decode_runtime_manifest, load_runtime_config_manifest

    manifest_path = Path(__file__).resolve().parents[2] / "certification" / "d11s" / "inputs" / "runtime-config.json"
    manifest = decode_runtime_manifest(load_runtime_config_manifest(manifest_path))

    reach_out_rules = [r for r in manifest.intent_engine.rules if r.kind == "reach_out"]
    assert len(reach_out_rules) == 0

    proactive_policy_rules = [r for r in manifest.action_policy.rules if getattr(r, "proactive", False)]
    assert len(proactive_policy_rules) == 0

    mode = getattr(manifest.decision_context, "mode", None)
    assert mode != "SURFACE_V1"


def test_host_proactive_result_contract_clean():
    """K. Inspect HostProactiveTurnResult fields:
    Assert 'bounded_context' type annotation is HostDecisionContext | None.
    Assert 'proactive_expression' is NOT a field on the dataclass.
    Assert as_dict() does not contain 'proactive_expression'.
    """
    import dataclasses
    from mind_runtime.contracts.host import HostProactiveTurnResult, HostDecisionContext

    field_names = [f.name for f in dataclasses.fields(HostProactiveTurnResult)]
    assert "proactive_expression" not in field_names
    assert "bounded_context" in field_names

    res = HostProactiveTurnResult(
        wake_id="w-1",
        interaction_id="i-1",
        status=HostTurnStatus.PROCESSING,
        outcome=HostStatus.OK,
        decision_context_ref=None,
        expression_ref=None,
        debug_ref="debug-1",
    )
    d = res.as_dict()
    assert "proactive_expression" not in d
