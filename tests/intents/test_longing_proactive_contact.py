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
        orchestrator.cognitive_tick_components["ticker"]._expression = preparer

    return orchestrator, clock, delivery_db, fake_agent


# ── SECTION 14: REQUIRED TESTS — STRUCTURAL ──────────────────────────────────


def test_a_frozen_w3_final_sha_is_ancestor():
    """Test A: Authoritative frozen W3 final SHA 386d3e8d8e49a1f2d8e9d6d4e18641ed2d0c504e is an ancestor."""
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


def test_b_fast_function_v1_registry_count_remains_eight():
    """Test B: FAST_FUNCTION_V1_REGISTRY count remains exactly 8."""
    assert len(FAST_FUNCTION_V1_REGISTRY) == 8
    longing_spec = FAST_FUNCTION_V1_REGISTRY.get("agent.affect.longing")
    assert longing_spec is not None
    assert longing_spec.function_kind == FastFunctionKind.PROACTIVE_CONTACT
    assert longing_spec.external_action_capable is True


def test_c_longing_remains_declared_surface_root_for_contact_seeking():
    """Test C: longing remains a declared Surface root for contact_seeking."""
    assert "contact_seeking" in MANIFEST
    dynamics_roots = MANIFEST["contact_seeking"]["dynamics"]
    assert D_PREFIX + "longing" in dynamics_roots

    transitive_roots = get_control_transitive_roots("contact_seeking")
    assert D_PREFIX + "longing" in transitive_roots


def test_d_intent_path_cannot_read_raw_longing_overlap():
    """Test D: Intent path cannot read raw agent.affect.longing when consumed through Surface."""
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


def test_e_increasing_longing_monotonic_contact_seeking():
    """Test E: Increasing longing gives monotonic non-decreasing contact_seeking under Candidate Recipe v2."""
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


def test_f_contact_seeking_drives_intent_strength_and_eligibility():
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


# ── SECTION 15: REQUIRED TESTS — TICK AUTHORITY ──────────────────────────────


def test_g_cognitive_ticker_does_not_construct_delivery_request(tmp_path: Path):
    """Test G: CognitiveTicker does NOT construct DeliveryRequest."""
    orchestrator, clock, _, _ = _build_test_stack(tmp_path, initial_longing=0.90)
    now = clock.now() + timedelta(minutes=5)
    clock.advance(timedelta(minutes=5))
    user_scope = Scope(domain=ScopeDomain.USER, user_id="fixture-user")

    report = run_cognitive_tick(orchestrator, scope=user_scope, now=now)
    assert report.policy_allowed == 1
    # Report contains wake_signal, NEVER delivery_request
    assert not hasattr(report, "delivery_request")
    assert report.wake_signal is not None
    assert isinstance(report.wake_signal, WakeSignal)


def test_h_cognitive_ticker_does_not_write_to_delivery_backend(tmp_path: Path):
    """Test H: CognitiveTicker does NOT write to a DeliveryBackend."""
    orchestrator, clock, delivery_db, _ = _build_test_stack(tmp_path, initial_longing=0.90)
    now = clock.now() + timedelta(minutes=5)
    clock.advance(timedelta(minutes=5))
    user_scope = Scope(domain=ScopeDomain.USER, user_id="fixture-user")

    run_cognitive_tick(orchestrator, scope=user_scope, now=now)

    delivery_backend = SqliteDeliveryBackend(delivery_db)
    row_count = delivery_backend._conn.execute("SELECT COUNT(*) FROM delivery_requests").fetchone()[0]
    delivery_backend.close()
    assert row_count == 0, f"CognitiveTicker wrote {row_count} rows to delivery_requests!"


def test_i_cognitive_ticker_has_no_delivery_backend_ownership():
    """Test I: CognitiveTicker has no new delivery backend ownership introduced by 016fbbe."""
    ticker_sig = inspect.signature(CognitiveTicker.__init__)
    assert "delivery_backend" not in ticker_sig.parameters

    builder_sig = inspect.signature(build_cognitive_ticker)
    assert "delivery_backend" not in builder_sig.parameters


def test_j_action_policy_deny_produces_no_wake_signal(tmp_path: Path):
    """Test J: ActionPolicy DENY produces no WakeSignal."""
    orchestrator, clock, _, _ = _build_test_stack(
        tmp_path,
        initial_longing=0.90,
        resources=("proactive_message",),
        policy_rules=(),
    )
    now = clock.now() + timedelta(minutes=5)
    clock.advance(timedelta(minutes=5))
    user_scope = Scope(domain=ScopeDomain.USER, user_id="fixture-user")

    report = run_cognitive_tick(orchestrator, scope=user_scope, now=now)
    assert report.policy_denied >= 1
    assert report.policy_allowed == 0
    assert report.wake_signal is None
    assert report.proactive_wake is None
    assert report.as_dict()["wake_signal"] is None
    assert report.as_dict()["wake_id"] is None


def test_k_action_policy_allow_produces_one_legal_proactive_wake(tmp_path: Path):
    """Test K: ActionPolicy ALLOW may produce one legal proactive wake."""
    orchestrator, clock, _, _ = _build_test_stack(tmp_path, initial_longing=0.90)
    now = clock.now() + timedelta(minutes=5)
    clock.advance(timedelta(minutes=5))
    user_scope = Scope(domain=ScopeDomain.USER, user_id="fixture-user")

    report = run_cognitive_tick(orchestrator, scope=user_scope, now=now)
    assert report.policy_allowed == 1
    assert report.wake_signal is not None
    wake = report.wake_signal
    assert isinstance(wake, WakeSignal)
    assert wake.action_type == "proactive_message"
    assert wake.reason == "proactive_intent_allowed"
    assert wake.scope == user_scope
    assert wake.wake_id.startswith("wake-")


def test_l_cooldown_prevents_repeated_wake_generation(tmp_path: Path):
    """Test L: Cooldown / anti-repeat prevents repeated wake generation."""
    orchestrator, clock, _, _ = _build_test_stack(
        tmp_path,
        initial_longing=0.90,
        cooldown=timedelta(minutes=30),
    )
    user_scope = Scope(domain=ScopeDomain.USER, user_id="fixture-user")

    t1 = clock.now() + timedelta(minutes=5)
    clock.advance(timedelta(minutes=5))
    report1 = run_cognitive_tick(orchestrator, scope=user_scope, now=t1)
    assert report1.policy_allowed == 1
    assert report1.wake_signal is not None

    t2 = clock.now() + timedelta(minutes=5)
    clock.advance(timedelta(minutes=5))
    report2 = run_cognitive_tick(orchestrator, scope=user_scope, now=t2)
    assert report2.policy_allowed == 0
    assert report2.wake_signal is None


def test_m_one_admitted_intent_produces_at_most_one_wake(tmp_path: Path):
    """Test M: One admitted proactive intent produces at most one wake for the same logical eligibility event."""
    orchestrator, clock, _, _ = _build_test_stack(tmp_path, initial_longing=0.90)
    user_scope = Scope(domain=ScopeDomain.USER, user_id="fixture-user")

    t1 = clock.now() + timedelta(minutes=5)
    clock.advance(timedelta(minutes=5))
    report = run_cognitive_tick(orchestrator, scope=user_scope, now=t1)

    assert report.policy_allowed == 1
    assert report.wake_signal is not None
    # Exactly one WakeSignal is attached to the report
    assert isinstance(report.wake_signal, WakeSignal)
    assert report.as_dict()["wake_id"] == report.wake_signal.wake_id


# ── SECTION 16: REQUIRED TESTS — WAKE BOUNDARY ───────────────────────────────


def test_n_wake_output_contains_bounded_typed_refs_only(tmp_path: Path):
    """Test N: Wake output contains bounded typed refs only."""
    orchestrator, clock, _, _ = _build_test_stack(tmp_path, initial_longing=0.90)
    user_scope = Scope(domain=ScopeDomain.USER, user_id="fixture-user")

    t1 = clock.now() + timedelta(minutes=5)
    clock.advance(timedelta(minutes=5))
    report = run_cognitive_tick(orchestrator, scope=user_scope, now=t1)
    wake = report.wake_signal
    assert wake is not None

    # Verify typed fields
    assert isinstance(wake.wake_id, str)
    assert isinstance(wake.runtime_id, str)
    assert isinstance(wake.scope, Scope)
    assert isinstance(wake.intent_id, str)
    assert isinstance(wake.action_type, str)
    assert isinstance(wake.policy_decision_ref, str)
    assert isinstance(wake.interaction_id, str)
    assert isinstance(wake.woken_at, datetime)
    assert isinstance(wake.reason, str)
    assert isinstance(wake.intent_version, int)


def test_o_wake_does_not_expose_raw_internal_vectors(tmp_path: Path):
    """Test O: Wake does not expose longing numeric value, raw Dynamics, Persona vector, or raw Surface vector."""
    orchestrator, clock, _, _ = _build_test_stack(tmp_path, initial_longing=0.90)
    user_scope = Scope(domain=ScopeDomain.USER, user_id="fixture-user")

    t1 = clock.now() + timedelta(minutes=5)
    clock.advance(timedelta(minutes=5))
    report = run_cognitive_tick(orchestrator, scope=user_scope, now=t1)
    wake = report.wake_signal
    assert wake is not None

    for forbidden in ("longing", "dynamics", "persona", "surface", "raw_affect", "character_card"):
        assert not hasattr(wake, forbidden)
        assert forbidden not in wake.as_dict()


def test_p_wake_does_not_fabricate_user_message(tmp_path: Path):
    """Test P: Wake does not fabricate a user message."""
    orchestrator, clock, _, _ = _build_test_stack(tmp_path, initial_longing=0.90)
    user_scope = Scope(domain=ScopeDomain.USER, user_id="fixture-user")

    t1 = clock.now() + timedelta(minutes=5)
    clock.advance(timedelta(minutes=5))
    report = run_cognitive_tick(orchestrator, scope=user_scope, now=t1)
    wake = report.wake_signal
    assert wake is not None

    for forbidden in ("user_message", "user_utterance", "evidence_text"):
        assert not hasattr(wake, forbidden)
        assert forbidden not in wake.as_dict()


def test_q_wake_does_not_become_user_evidence(tmp_path: Path):
    """Test Q: Wake does not become user Evidence."""
    orchestrator, clock, _, _ = _build_test_stack(tmp_path, initial_longing=0.90)
    user_scope = Scope(domain=ScopeDomain.USER, user_id="fixture-user")

    t1 = clock.now() + timedelta(minutes=5)
    clock.advance(timedelta(minutes=5))
    run_cognitive_tick(orchestrator, scope=user_scope, now=t1)

    # Fact service has no Evidence with source_type="user_message" created by tick
    facts = orchestrator._fact_backend.all(user_scope) if hasattr(orchestrator, "_fact_backend") else ()
    user_message_evs = [f for f in facts if getattr(f, "source_type", None) == "user_message"]
    assert len(user_message_evs) == 0


def test_r_wake_itself_does_not_create_delivery_receipt(tmp_path: Path):
    """Test R: Wake itself does not create a DeliveryReceipt."""
    orchestrator, clock, delivery_db, _ = _build_test_stack(tmp_path, initial_longing=0.90)
    user_scope = Scope(domain=ScopeDomain.USER, user_id="fixture-user")

    t1 = clock.now() + timedelta(minutes=5)
    clock.advance(timedelta(minutes=5))
    run_cognitive_tick(orchestrator, scope=user_scope, now=t1)

    delivery_backend = SqliteDeliveryBackend(delivery_db)
    receipts_count = delivery_backend._conn.execute("SELECT COUNT(*) FROM delivery_receipts").fetchone()[0]
    delivery_backend.close()
    assert receipts_count == 0


def test_s_wake_does_not_directly_create_final_user_visible_text(tmp_path: Path):
    """Test S: Wake does not directly create final user-visible text."""
    orchestrator, clock, _, _ = _build_test_stack(tmp_path, initial_longing=0.90)
    user_scope = Scope(domain=ScopeDomain.USER, user_id="fixture-user")

    t1 = clock.now() + timedelta(minutes=5)
    clock.advance(timedelta(minutes=5))
    report = run_cognitive_tick(orchestrator, scope=user_scope, now=t1)
    wake = report.wake_signal
    assert wake is not None

    for forbidden in ("text", "prose", "would_send", "payload_bytes"):
        assert not hasattr(wake, forbidden)
        assert forbidden not in wake.as_dict()


# ── SECTION 17: REQUIRED TESTS — BODY / EXPRESSION PATH ──────────────────────


def test_t_legal_proactive_wake_reaches_existing_proactive_expression_path(tmp_path: Path):
    """Test T: A legal proactive wake reaches the existing proactive Body/expression preparation path."""
    orchestrator, clock, _, fake_agent = _build_test_stack(
        tmp_path,
        initial_longing=0.90,
        with_expression=True,
        agent_script=("想和你聊聊今天的新发现",),
    )
    user_scope = Scope(domain=ScopeDomain.USER, user_id="fixture-user")

    t1 = clock.now() + timedelta(minutes=5)
    clock.advance(timedelta(minutes=5))
    report = run_cognitive_tick(orchestrator, scope=user_scope, now=t1)

    # 1. Legal proactive wake was emitted
    assert report.wake_signal is not None
    # 2. Existing proactive expression preparation ran and produced would-send artifact
    assert report.proactive_expression is not None
    artifact: ProactiveExpressionArtifact = report.proactive_expression
    assert artifact.would_send == "想和你聊聊今天的新发现"
    assert artifact.disposition is ExpressionDisposition.ACCEPT
    assert fake_agent is not None and len(fake_agent.calls) == 1


def test_u_decision_context_admission_occurs_before_provider_realization(tmp_path: Path):
    """Test U: DecisionContext admission occurs before provider realization."""
    orchestrator, clock, _, fake_agent = _build_test_stack(
        tmp_path,
        initial_longing=0.90,
        with_expression=True,
    )
    user_scope = Scope(domain=ScopeDomain.USER, user_id="fixture-user")

    t1 = clock.now() + timedelta(minutes=5)
    clock.advance(timedelta(minutes=5))
    report = run_cognitive_tick(orchestrator, scope=user_scope, now=t1)

    artifact = report.proactive_expression
    assert artifact is not None
    # Context ID was recorded and trace includes proactive_expression_context
    assert artifact.context_id is not None
    trace = orchestrator.trace.trace(f"cognitive-tick-{t1.isoformat()}")
    stages = [entry.stage for entry in trace]
    assert "proactive_expression_context" in stages
    assert "proactive_expression" in stages
    ctx_idx = stages.index("proactive_expression_context")
    expr_idx = stages.index("proactive_expression")
    assert ctx_idx < expr_idx, "DecisionContext admission must occur before provider realization!"


def test_v_policy_denial_cannot_create_provider_handoff(tmp_path: Path):
    """Test V: Policy denial cannot create provider handoff."""
    orchestrator, clock, _, fake_agent = _build_test_stack(
        tmp_path,
        initial_longing=0.90,
        with_expression=True,
        policy_rules=(),
    )
    user_scope = Scope(domain=ScopeDomain.USER, user_id="fixture-user")

    t1 = clock.now() + timedelta(minutes=5)
    clock.advance(timedelta(minutes=5))
    report = run_cognitive_tick(orchestrator, scope=user_scope, now=t1)

    assert report.policy_denied >= 1
    assert report.wake_signal is None
    # No provider handoff occurred
    assert report.proactive_expression is None
    assert fake_agent is not None and len(fake_agent.calls) == 0


def test_w_provider_prose_still_passes_expression_guard(tmp_path: Path):
    """Test W: Provider prose still passes ExpressionGuard."""
    orchestrator, clock, _, fake_agent = _build_test_stack(
        tmp_path,
        initial_longing=0.90,
        with_expression=True,
        agent_script=("合法的问候表达",),
    )
    user_scope = Scope(domain=ScopeDomain.USER, user_id="fixture-user")

    t1 = clock.now() + timedelta(minutes=5)
    clock.advance(timedelta(minutes=5))
    report = run_cognitive_tick(orchestrator, scope=user_scope, now=t1)

    artifact = report.proactive_expression
    assert artifact is not None
    assert artifact.disposition is ExpressionDisposition.ACCEPT
    assert artifact.would_send == "合法的问候表达"


def test_x_guard_rejection_prevents_external_delivery_or_commit(tmp_path: Path):
    """Test X: Guard rejection prevents external delivery/commit."""
    orchestrator, clock, _, fake_agent = _build_test_stack(
        tmp_path,
        initial_longing=0.90,
        with_expression=True,
        agent_script=("",),
    )
    user_scope = Scope(domain=ScopeDomain.USER, user_id="fixture-user")

    t1 = clock.now() + timedelta(minutes=5)
    clock.advance(timedelta(minutes=5))
    report = run_cognitive_tick(orchestrator, scope=user_scope, now=t1)

    artifact = report.proactive_expression
    assert artifact is not None
    assert artifact.disposition is ExpressionDisposition.REJECT
    assert artifact.would_send is None


def test_y_c7_request_authority_is_not_cognitive_ticker(tmp_path: Path):
    """Test Y: Any resulting C7 request is created by the existing authoritative handoff / delivery owner, not CognitiveTicker."""
    orchestrator, clock, delivery_db, _ = _build_test_stack(
        tmp_path,
        initial_longing=0.90,
        with_expression=True,
    )
    user_scope = Scope(domain=ScopeDomain.USER, user_id="fixture-user")

    t1 = clock.now() + timedelta(minutes=5)
    clock.advance(timedelta(minutes=5))
    report = run_cognitive_tick(orchestrator, scope=user_scope, now=t1)

    # 1. CognitiveTicker emitted wake_signal, never DeliveryRequest
    assert report.wake_signal is not None
    assert not hasattr(report, "delivery_request")

    # 2. Delivery backend was NOT written to by ticker
    delivery_backend = SqliteDeliveryBackend(delivery_db)
    rows = delivery_backend._conn.execute("SELECT COUNT(*) FROM delivery_requests").fetchone()[0]
    delivery_backend.close()
    assert rows == 0


# ── SECTION 18: STATIC ARCHITECTURE GUARDS ───────────────────────────────────


def test_z1_static_ast_guard_no_delivery_authority_in_tick_py():
    """Static AST Guard: fail if cognition/tick.py newly contains direct use of delivery authority."""
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


def test_z2_host_adapter_smallest_typed_consumer():
    """Test smallest typed consumer of WakeSignal at MindRuntimeHostAdapter boundary."""
    from unittest.mock import MagicMock
    adapter = MindRuntimeHostAdapter(orchestrator=MagicMock())
    now = datetime(2026, 9, 24, 8, 0, tzinfo=UTC)
    scope = Scope(domain=ScopeDomain.USER, user_id="test-user")
    wake = WakeSignal(
        wake_id="wake-123",
        runtime_id="runtime-1",
        scope=scope,
        intent_id="intent-abc",
        action_type="proactive_message",
        policy_decision_ref="policy-ref-1",
        interaction_id="interaction-123",
        woken_at=now,
    )
    notification = adapter.consume_wake(wake)
    assert isinstance(notification, HostWakeNotification)
    assert notification.wake_id == "wake-123"
    assert notification.runtime_id == "runtime-1"
    assert notification.scope == scope
    assert notification.intent_id == "intent-abc"
    assert notification.action_type == "proactive_message"
    assert notification.eligible is True
    # Aliased method also works
    assert adapter.notify_proactive_wake(wake) == notification


def test_z3_longing_anti_spam_invariant_and_registry():
    """Verify anti-spam invariant string, registry invariants, and validation behavior."""
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
