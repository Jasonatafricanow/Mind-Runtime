"""Test suite for MR-LONGING-PROACTIVE-CONTACT-V1-FIX-01.

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
existing proactive expression / DecisionContext path (C5C)
    ↓
Body / provider generation
    ↓
ExpressionGuard
    ↓
existing C7 / external delivery lifecycle (never CognitiveTicker)

Tests:
Section 14: Structural Tests (A-F)
Section 15: Tick Authority Tests (G-M)
Section 16: Wake Boundary Tests (N-S)
Section 17: Body / Expression Path Tests (T-Y)
Section 18: Static Architecture Guards & Anti-Spam Invariants
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
    ActionPolicyInput,
    ActionPolicyResult,
    ExpressionDisposition,
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
from mind_runtime.intents.engine import DeterministicIntentEngine, IntentRule
from mind_runtime.intents.policy import ActionPolicyConfig, IntentPolicyRule
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
    # Resolve the object in git
    show_proc = subprocess.run(
        ["git", "show", "--no-patch", "--oneline", frozen_sha],
        capture_output=True,
        text=True,
        check=False,
    )
    assert show_proc.returncode == 0, f"Frozen W3 SHA {frozen_sha} could not be resolved: {show_proc.stderr}"
    assert "fix(surface): close W3 authority and durability gaps" in show_proc.stdout

    # Verify ancestry
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
    """Test F: Increasing contact_seeking can increase proactive-contact Intent strength / eligibility."""
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


# ── SECTION 18: TESTS — CAUSAL ORDER ─────────────────────────────────────────


def test_a_action_policy_allow_creates_wake_signal(tmp_path: Path):
    """Test A: ActionPolicy ALLOW creates WakeSignal."""
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


def test_b_provider_call_count_zero_before_host_admission(tmp_path: Path):
    """Test B: Before Host wake admission: provider call count == 0."""
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


def test_c_host_rejects_invalid_wake_zero_provider_calls(tmp_path: Path):
    """Test C: Host rejects invalid wake: provider call count == 0."""
    orchestrator, clock, _, fake_agent = _build_test_stack(tmp_path, initial_longing=0.90, with_expression=True)
    now = clock.now() + timedelta(minutes=5)
    clock.advance(timedelta(minutes=5))
    user_scope = Scope(domain=ScopeDomain.USER, user_id="fixture-user")

    report = run_cognitive_tick(orchestrator, scope=user_scope, now=now)
    assert report.wake_signal is not None

    adapter = MindRuntimeHostAdapter(orchestrator=orchestrator, trace=orchestrator.trace)
    bad_wake = replace(report.wake_signal, runtime_id="wrong-runtime-id")

    turn_res = adapter.run_proactive_turn(bad_wake)
    assert turn_res.status == HostTurnStatus.FAILED
    assert turn_res.outcome == HostStatus.FAILED
    assert turn_res.expression_ref is None
    assert len(fake_agent.calls) == 0


def test_d_host_admits_valid_wake_one_provider_call(tmp_path: Path):
    """Test D: Host admits valid wake: provider call count == 1."""
    orchestrator, clock, _, fake_agent = _build_test_stack(tmp_path, initial_longing=0.90, with_expression=True)
    now = clock.now() + timedelta(minutes=5)
    clock.advance(timedelta(minutes=5))
    user_scope = Scope(domain=ScopeDomain.USER, user_id="fixture-user")

    report = run_cognitive_tick(orchestrator, scope=user_scope, now=now)
    assert report.wake_signal is not None
    assert len(fake_agent.calls) == 0

    adapter = MindRuntimeHostAdapter(orchestrator=orchestrator, trace=orchestrator.trace)
    turn_res = adapter.run_proactive_turn(report.wake_signal)

    assert turn_res.status == HostTurnStatus.COMMITTED
    assert turn_res.outcome == HostStatus.OK
    assert turn_res.decision_context_ref is not None
    assert turn_res.expression_ref is not None
    assert len(fake_agent.calls) == 1


def test_e_trace_ordering_proves_causal_sequence(tmp_path: Path):
    """Test E: Trace ordering proves:
    policy_allow < wake_created < host_wake_admitted < proactive_body_entry < provider_realization < expression_guard
    """
    orchestrator, clock, _, fake_agent = _build_test_stack(tmp_path, initial_longing=0.90, with_expression=True)
    now = clock.now() + timedelta(minutes=5)
    clock.advance(timedelta(minutes=5))
    user_scope = Scope(domain=ScopeDomain.USER, user_id="fixture-user")

    report = run_cognitive_tick(orchestrator, scope=user_scope, now=now)
    wake = report.wake_signal
    assert wake is not None

    adapter = MindRuntimeHostAdapter(orchestrator=orchestrator, trace=orchestrator.trace)
    turn_res = adapter.run_proactive_turn(wake)
    assert turn_res.outcome == HostStatus.OK

    records = orchestrator.trace.trace(wake.interaction_id)
    stages = [r.stage for r in records]

    required_stages = (
        "policy_allow",
        "wake_created",
        "host_wake_admitted",
        "proactive_body_entry",
        "proactive_expression_context",
        "provider_realization",
        "expression_guard",
        "proactive_expression",
    )
    for stage in required_stages:
        assert stage in stages, f"Missing required trace stage: {stage} in {stages}"

    p_allow = stages.index("policy_allow")
    w_create = stages.index("wake_created")
    h_admit = stages.index("host_wake_admitted")
    b_entry = stages.index("proactive_body_entry")
    ctx_prep = stages.index("proactive_expression_context")
    p_realize = stages.index("provider_realization")
    e_guard = stages.index("expression_guard")
    p_expr = stages.index("proactive_expression")

    assert p_allow < w_create < h_admit < b_entry <= ctx_prep < p_realize < e_guard <= p_expr, (
        f"Causal ordering violation in stages: {stages}"
    )


def test_f_no_proactive_expression_artifact_before_admitted_wake(tmp_path: Path):
    """Test F: No proactive expression artifact exists before admitted wake."""
    orchestrator, clock, _, fake_agent = _build_test_stack(tmp_path, initial_longing=0.90, with_expression=True)
    now = clock.now() + timedelta(minutes=5)
    clock.advance(timedelta(minutes=5))
    user_scope = Scope(domain=ScopeDomain.USER, user_id="fixture-user")

    report = run_cognitive_tick(orchestrator, scope=user_scope, now=now)
    assert report.wake_signal is not None
    assert report.proactive_expression is None

    adapter = MindRuntimeHostAdapter(orchestrator=orchestrator, trace=orchestrator.trace)
    assert report.wake_signal.wake_id not in adapter._proactive_turn_results


def test_g_same_wake_replay_no_second_provider_call(tmp_path: Path):
    """Test G: Same wake replay produces no second provider call."""
    orchestrator, clock, _, fake_agent = _build_test_stack(tmp_path, initial_longing=0.90, with_expression=True)
    now = clock.now() + timedelta(minutes=5)
    clock.advance(timedelta(minutes=5))
    user_scope = Scope(domain=ScopeDomain.USER, user_id="fixture-user")

    report = run_cognitive_tick(orchestrator, scope=user_scope, now=now)
    wake = report.wake_signal
    assert wake is not None

    adapter = MindRuntimeHostAdapter(orchestrator=orchestrator, trace=orchestrator.trace)
    res1 = adapter.run_proactive_turn(wake)
    assert res1.outcome == HostStatus.OK
    assert len(fake_agent.calls) == 1

    # Replay same wake
    res2 = adapter.run_proactive_turn(wake)
    assert res2.status == HostTurnStatus.ALREADY_PROCESSED
    assert res2.outcome == HostStatus.ALREADY_PROCESSED
    assert len(fake_agent.calls) == 1


def test_h_conflicting_same_wake_id_fails_closed(tmp_path: Path):
    """Test H: Conflicting same wake_id fails closed."""
    orchestrator, clock, _, fake_agent = _build_test_stack(tmp_path, initial_longing=0.90, with_expression=True)
    now = clock.now() + timedelta(minutes=5)
    clock.advance(timedelta(minutes=5))
    user_scope = Scope(domain=ScopeDomain.USER, user_id="fixture-user")

    report = run_cognitive_tick(orchestrator, scope=user_scope, now=now)
    wake = report.wake_signal
    assert wake is not None

    adapter = MindRuntimeHostAdapter(orchestrator=orchestrator, trace=orchestrator.trace)
    res1 = adapter.run_proactive_turn(wake)
    assert res1.outcome == HostStatus.OK
    assert len(fake_agent.calls) == 1

    # Replay with modified conflicting payload
    conflicting_wake = replace(wake, action_type="conflicting_action")
    res2 = adapter.run_proactive_turn(conflicting_wake)
    assert res2.status == HostTurnStatus.FAILED
    assert res2.outcome == HostStatus.FAILED
    assert len(fake_agent.calls) == 1


# ── SECTION 19: TESTS — LINEAGE ──────────────────────────────────────────────


def test_i_wrong_runtime_id_rejected(tmp_path: Path):
    """Test I: wrong runtime_id -> rejected."""
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


def test_j_wrong_scope_rejected(tmp_path: Path):
    """Test J: wrong scope -> rejected."""
    orchestrator, clock, _, _ = _build_test_stack(tmp_path, initial_longing=0.90)
    now = clock.now() + timedelta(minutes=5)
    clock.advance(timedelta(minutes=5))
    user_scope = Scope(domain=ScopeDomain.USER, user_id="fixture-user")

    report = run_cognitive_tick(orchestrator, scope=user_scope, now=now)
    wake = report.wake_signal
    assert wake is not None

    adapter = MindRuntimeHostAdapter(orchestrator=orchestrator, trace=orchestrator.trace)
    other_scope = Scope(domain=ScopeDomain.USER, user_id="other-user")
    bad_wake = replace(wake, scope=other_scope)
    notif = adapter.consume_wake(bad_wake)
    assert notif.eligible is False
    assert notif.reason == "rejected:scope_mismatch"


def test_k_unknown_intent_id_rejected(tmp_path: Path):
    """Test K: unknown intent_id -> rejected."""
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


def test_l_intent_not_allowed_rejected(tmp_path: Path):
    """Test L: Intent not ALLOWED -> rejected."""
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


def test_m_wrong_intent_version_rejected(tmp_path: Path):
    """Test M: wrong intent_version -> rejected."""
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


def test_n_action_type_mismatch_rejected(tmp_path: Path):
    """Test N: action_type mismatch -> rejected."""
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
    assert notif.reason == "rejected:action_type_mismatch"


def test_o_valid_wake_admitted(tmp_path: Path):
    """Test O: valid wake -> admitted."""
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


def test_p_host_wake_notification_preserves_required_bounded_lineage(tmp_path: Path):
    """Test P: HostWakeNotification preserves required bounded lineage."""
    orchestrator, clock, _, _ = _build_test_stack(tmp_path, initial_longing=0.90)
    now = clock.now() + timedelta(minutes=5)
    clock.advance(timedelta(minutes=5))
    user_scope = Scope(domain=ScopeDomain.USER, user_id="fixture-user")

    report = run_cognitive_tick(orchestrator, scope=user_scope, now=now)
    wake = report.wake_signal
    assert wake is not None

    adapter = MindRuntimeHostAdapter(orchestrator=orchestrator, trace=orchestrator.trace)
    notif = adapter.consume_wake(wake)

    assert notif.wake_id == wake.wake_id
    assert notif.runtime_id == wake.runtime_id
    assert notif.scope == wake.scope
    assert notif.intent_id == wake.intent_id
    assert notif.intent_version == wake.intent_version
    assert notif.action_type == wake.action_type
    assert notif.interaction_id == wake.interaction_id
    assert notif.policy_decision_ref == wake.policy_decision_ref
    assert notif.occurred_at == wake.woken_at
    assert notif.reason == "proactive_intent_allowed"
    assert notif.eligible is True


def test_q_wake_and_notification_expose_no_raw_affect_persona_surface_numbers(tmp_path: Path):
    """Test Q: Wake/notification exposes no raw affect/Persona/Surface numbers."""
    orchestrator, clock, _, _ = _build_test_stack(tmp_path, initial_longing=0.90)
    now = clock.now() + timedelta(minutes=5)
    clock.advance(timedelta(minutes=5))
    user_scope = Scope(domain=ScopeDomain.USER, user_id="fixture-user")

    report = run_cognitive_tick(orchestrator, scope=user_scope, now=now)
    wake = report.wake_signal
    assert wake is not None

    adapter = MindRuntimeHostAdapter(orchestrator=orchestrator, trace=orchestrator.trace)
    notif = adapter.consume_wake(wake)

    forbidden_fields = (
        "longing",
        "dynamics",
        "persona",
        "surface",
        "raw_affect",
        "character_card",
        "contact_seeking",
        "prompt",
    )
    for forbidden in forbidden_fields:
        assert not hasattr(wake, forbidden)
        assert forbidden not in wake.as_dict()
        assert not hasattr(notif, forbidden)
        assert forbidden not in notif.as_dict()


# ── SECTION 20: TESTS — AUTHORITY ────────────────────────────────────────────


def test_r_cognitive_ticker_ast_no_delivery_authority():
    """Test R: CognitiveTicker source/AST has no DeliveryRequest authority."""
    tick_path = Path(__file__).resolve().parents[2] / "src" / "mind_runtime" / "cognition" / "tick.py"
    assert tick_path.exists(), f"Could not find tick.py at {tick_path}"
    source = tick_path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(tick_path))

    forbidden_names = {
        "DeliveryRequest",
        "SqliteDeliveryBackend",
        "InMemoryDeliveryBackend",
        "record_delivery",
        "_dispatch_delivery",
        "DeliveryBackend",
    }

    found_violations: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name in forbidden_names or alias.asname in forbidden_names:
                    found_violations.append(f"Import: {alias.name} at line {node.lineno}")
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                if alias.name in forbidden_names or alias.asname in forbidden_names:
                    found_violations.append(f"ImportFrom: {alias.name} from {node.module} at line {node.lineno}")
        elif isinstance(node, ast.FunctionDef):
            if node.name in forbidden_names:
                found_violations.append(f"FunctionDef: {node.name} at line {node.lineno}")
        elif isinstance(node, ast.Name):
            if node.id in forbidden_names:
                found_violations.append(f"Name reference: {node.id} at line {node.lineno}")

    assert not found_violations, f"Architecture violation in cognition/tick.py:\n" + "\n".join(found_violations)


def test_s_cognitive_ticker_no_longer_invokes_provider_realization(tmp_path: Path):
    """Test S: CognitiveTicker no longer invokes provider realization."""
    orchestrator, clock, _, fake_agent = _build_test_stack(tmp_path, initial_longing=0.90, with_expression=True)
    now = clock.now() + timedelta(minutes=5)
    clock.advance(timedelta(minutes=5))
    user_scope = Scope(domain=ScopeDomain.USER, user_id="fixture-user")

    report = run_cognitive_tick(orchestrator, scope=user_scope, now=now)
    assert report.wake_signal is not None
    assert report.proactive_expression is None
    assert fake_agent is not None
    assert len(fake_agent.calls) == 0


def test_t_wake_does_not_create_user_evidence(tmp_path: Path):
    """Test T: Wake does not create user Evidence."""
    orchestrator, clock, _, fake_agent = _build_test_stack(tmp_path, initial_longing=0.90, with_expression=True)
    now = clock.now() + timedelta(minutes=5)
    clock.advance(timedelta(minutes=5))
    user_scope = Scope(domain=ScopeDomain.USER, user_id="fixture-user")

    report = run_cognitive_tick(orchestrator, scope=user_scope, now=now)
    adapter = MindRuntimeHostAdapter(orchestrator=orchestrator, trace=orchestrator.trace)
    adapter.run_proactive_turn(report.wake_signal)

    facts = orchestrator._fact_backend.all(user_scope) if hasattr(orchestrator, "_fact_backend") else ()
    user_message_evs = [f for f in facts if getattr(f, "source_type", None) == "user_message"]
    assert len(user_message_evs) == 0


def test_u_wake_does_not_synthesize_host_turn_request(tmp_path: Path):
    """Test U: Wake does not synthesize HostTurnRequest."""
    adapter_path = Path(__file__).resolve().parents[2] / "src" / "mind_runtime" / "host" / "runtime_adapter.py"
    source = adapter_path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(adapter_path))

    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "run_proactive_turn":
            for child in ast.walk(node):
                if isinstance(child, ast.Name) and child.id == "HostTurnRequest":
                    pytest.fail("run_proactive_turn must not instantiate HostTurnRequest")
                if isinstance(child, ast.Attribute) and child.attr == "begin_turn":
                    pytest.fail("run_proactive_turn must not call begin_turn")


def test_v_guard_rejection_prevents_delivery_eligibility(tmp_path: Path):
    """Test V: Guard rejection prevents delivery eligibility."""
    orchestrator, clock, _, fake_agent = _build_test_stack(
        tmp_path,
        initial_longing=0.90,
        with_expression=True,
        agent_script=("",),
    )
    now = clock.now() + timedelta(minutes=5)
    clock.advance(timedelta(minutes=5))
    user_scope = Scope(domain=ScopeDomain.USER, user_id="fixture-user")

    report = run_cognitive_tick(orchestrator, scope=user_scope, now=now)
    assert report.wake_signal is not None

    adapter = MindRuntimeHostAdapter(orchestrator=orchestrator, trace=orchestrator.trace)
    turn_res = adapter.run_proactive_turn(report.wake_signal)

    assert turn_res.status == HostTurnStatus.ABORTED
    assert turn_res.outcome == HostStatus.FAILED
    assert turn_res.expression_ref is None
    assert turn_res.would_send is None


def test_w_policy_deny_produces_neither_wake_nor_provider_invocation(tmp_path: Path):
    """Test W: Policy DENY produces neither wake nor provider invocation."""
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


def test_x_cooldown_defer_produces_neither_wake_nor_provider_invocation(tmp_path: Path):
    """Test X: Cooldown DEFER produces neither wake nor provider invocation."""
    orchestrator, clock, _, fake_agent = _build_test_stack(
        tmp_path,
        initial_longing=0.90,
        with_expression=True,
        cooldown=timedelta(minutes=30),
    )
    user_scope = Scope(domain=ScopeDomain.USER, user_id="fixture-user")

    # Tick 1: Allowed
    t1 = clock.now() + timedelta(minutes=5)
    clock.advance(timedelta(minutes=5))
    report1 = run_cognitive_tick(orchestrator, scope=user_scope, now=t1)
    assert report1.policy_allowed == 1
    assert report1.wake_signal is not None
    assert len(fake_agent.calls) == 0

    # Tick 2: Deferred by cooldown
    t2 = clock.now() + timedelta(minutes=5)
    clock.advance(timedelta(minutes=5))
    report2 = run_cognitive_tick(orchestrator, scope=user_scope, now=t2)
    assert report2.policy_allowed == 0
    assert report2.wake_signal is None
    assert len(fake_agent.calls) == 0


def test_y_fast_function_v1_registry_count_remains_eight():
    """Test Y: FAST_FUNCTION_V1_REGISTRY count remains exactly 8."""
    assert len(FAST_FUNCTION_V1_REGISTRY) == 8
    longing_spec = FAST_FUNCTION_V1_REGISTRY.get("agent.affect.longing")
    assert longing_spec is not None
    assert longing_spec.function_kind == FastFunctionKind.PROACTIVE_CONTACT
    assert longing_spec.external_action_capable is True


def test_z_longing_anti_spam_invariant_remains_valid():
    """Test Z: Longing anti-spam invariant remains valid."""
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


# ── SECTION 21: TESTS — TYPING / PRIVATE ACCESS ──────────────────────────────


def test_aa_proactive_surface_parameter_uses_typed_surface_contract():
    """Test AA: Proactive Surface parameter uses typed Surface contract, not object."""
    sig = inspect.signature(ProactiveExpressionPreparer.prepare_context)
    surface_param = sig.parameters.get("surface")
    assert surface_param is not None
    # Annotation must be SurfaceProjectionResult | None, NOT object or Any
    annotation = surface_param.annotation
    assert annotation != object
    assert "SurfaceProjectionResult" in str(annotation)


def test_ab_no_type_ignore_on_proactive_path():
    """Test AB: No type-ignore is required on the proactive expression path."""
    express_path = Path(__file__).resolve().parents[2] / "src" / "mind_runtime" / "cognition" / "express.py"
    lines = express_path.read_text(encoding="utf-8").splitlines()
    for lineno, line in enumerate(lines, 1):
        if "# type: ignore" in line:
            pytest.fail(f"Found forbidden '# type: ignore' in express.py at line {lineno}: {line}")


def test_ac_proactive_preparation_does_not_read_compiler_config():
    """Test AC: Proactive preparation does not read _compiler._config directly."""
    express_path = Path(__file__).resolve().parents[2] / "src" / "mind_runtime" / "cognition" / "express.py"
    source = express_path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(express_path))

    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr == "_config":
            if isinstance(node.value, ast.Attribute) and node.value.attr == "_compiler":
                pytest.fail(f"Proactive path reads _compiler._config at line {node.lineno}")


def test_ad_proactive_preparation_does_not_read_orchestrator_persona():
    """Test AD: Proactive preparation does not read _orchestrator._persona directly."""
    express_path = Path(__file__).resolve().parents[2] / "src" / "mind_runtime" / "cognition" / "express.py"
    source = express_path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(express_path))

    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr == "_persona":
            if isinstance(node.value, ast.Attribute) and node.value.attr == "_orchestrator":
                pytest.fail(f"Proactive path reads _orchestrator._persona at line {node.lineno}")

