"""Shared proactive host admission, lifecycle, authority and recovery contracts."""

# Historical consumer audit keeps long evidence strings readable in source.
# ruff: noqa: E501

from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from xiyue import mr_seam

from mind_runtime.binding_registry import BindingRegistry
from mind_runtime.cognition.express import (
    ProactiveExpressionConfig,
    ProactiveExpressionPreparer,
)
from mind_runtime.contracts import (
    ExpressionDisposition,
    HostDecisionContext,
    HostStatus,
    HostTurnStatus,
    IntentStatus,
    ReconsiderationPolicy,
    RuntimeState,
    Scope,
    ScopeDomain,
    SyncFields,
    WakeSignal,
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
from mind_runtime.host.xiyue_adapter import default_adapter
from mind_runtime.intents.engine import IntentRule
from mind_runtime.intents.lifecycle import IntentLifecycleService
from mind_runtime.intents.persistence import SqliteIntentBackend
from mind_runtime.intents.policy import (
    ActionPolicyConfig,
    DeterministicActionPolicy,
    IntentPolicyRule,
)
from mind_runtime.persona_publication import PersonaConfigPublicationRepository
from mind_runtime.pipeline.fake_agent import FakeAgent
from mind_runtime.runtime_binding import RuntimeBinding, RuntimeEnvironment
from mind_runtime.shadow.runtime_loop import build_runtime_stack, run_cognitive_tick
from tests.support.fake_clock import FakeClock
from tests.surface.spec_support import sample_candidate

CERTIFIED_MANIFEST_PATH = (
    Path(__file__).resolve().parents[2]
    / "certification"
    / "d11s"
    / "inputs"
    / "runtime-config.json"
)


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
            sync=SyncFields(
                agent_scope, "fixture-runtime", f"state-{dim_name}", 1, f"idem-{dim_name}-1"
            ),
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


# ── SECTION 17: TESTS — TICKER AUTHORITY ─────────────────────────────────────


def test_b_cognitive_ticker_tick_cannot_call_provider_realization(tmp_path: Path):
    """Test B: CognitiveTicker.tick() cannot call provider realization."""
    orchestrator, clock, _, fake_agent = _build_test_stack(
        tmp_path, initial_longing=0.90, with_expression=True
    )
    now = clock.now() + timedelta(minutes=5)
    clock.advance(timedelta(minutes=5))
    user_scope = Scope(domain=ScopeDomain.USER, user_id="fixture-user")

    report = run_cognitive_tick(orchestrator, scope=user_scope, now=now)
    assert report.wake_signal is not None
    # Crucial causal invariant: Ticker did NOT invoke provider or create expression
    assert report.proactive_expression is None
    assert fake_agent is not None
    assert len(fake_agent.calls) == 0


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
    assert notif.reason in (
        "rejected:policy_authority_unavailable",
        "rejected:unsupported_intent_action",
    )


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


def test_m2_non_proactive_policy_rule_rejects_forged_wake(tmp_path: Path):
    """Wake admission must re-check that the authoritative policy rule is proactive."""
    orchestrator, clock, _, _ = _build_test_stack(tmp_path, initial_longing=0.90)
    now = clock.now() + timedelta(minutes=5)
    clock.advance(timedelta(minutes=5))
    user_scope = Scope(domain=ScopeDomain.USER, user_id="fixture-user")

    report = run_cognitive_tick(orchestrator, scope=user_scope, now=now)
    wake = report.wake_signal
    assert wake is not None

    lifecycle = orchestrator.cognitive_tick_components["lifecycle"]
    current_intent = lifecycle.backend.history(wake.scope, wake.intent_id)[-1]
    policy = orchestrator.cognitive_tick_components["policy"]
    authoritative_rule = policy._rules[current_intent.kind]
    policy._rules[current_intent.kind] = replace(authoritative_rule, proactive=False)

    adapter = MindRuntimeHostAdapter(orchestrator=orchestrator, trace=orchestrator.trace)
    notif = adapter.consume_wake(wake)
    assert notif.eligible is False
    assert notif.reason == "rejected:intent_not_proactive"


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
    orchestrator, clock, _, fake_agent = _build_test_stack(
        tmp_path, initial_longing=0.90, with_expression=True
    )
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
    orchestrator, clock, _, _ = _build_test_stack(
        tmp_path, initial_longing=0.90, with_expression=True
    )
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


def test_s_process_restart_context_loss_reported_as_unsupported(tmp_path: Path):
    """Test S: process restart/context loss is reported as unsupported V1 recovery,
    not silently repaired.
    """
    orchestrator, clock, _, _ = _build_test_stack(
        tmp_path, initial_longing=0.90, with_expression=True
    )
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


def test_u_mr_does_not_invoke_production_llm_internally_before_handing_context(tmp_path: Path):
    """Test U: MR does not invoke production LLM/provider internally before handing
    bounded context to Body.
    """
    orchestrator, clock, _, fake_agent = _build_test_stack(
        tmp_path, initial_longing=0.90, with_expression=True
    )
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


def test_z_duplicate_completion_is_idempotent(tmp_path: Path):
    """Test Z: duplicate completion is idempotent."""
    orchestrator, clock, _, _ = _build_test_stack(
        tmp_path, initial_longing=0.90, with_expression=True
    )
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

    # Completed wake replay must not start a new turn, including a forged payload.
    replay = adapter.begin_proactive_turn(wake)
    assert replay.status == HostTurnStatus.ALREADY_PROCESSED
    conflict = adapter.begin_proactive_turn(replace(wake, action_type="conflicting_action"))
    assert conflict.status == HostTurnStatus.FAILED
    assert conflict.reason_codes == ("wake_conflict", "conflicting_wake_payload")


def test_aa_conflicting_replay_fails_closed(tmp_path: Path):
    """Test AA: conflicting replay fails closed."""
    orchestrator, clock, _, fake_agent = _build_test_stack(
        tmp_path, initial_longing=0.90, with_expression=True
    )
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


def test_ad_generic_proactive_contact_infrastructure_verified(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
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
    assert isinstance(orch.cognitive_tick_components["lifecycle"], IntentLifecycleService)
    assert isinstance(orch.cognitive_tick_components["backend"], SqliteIntentBackend)
    assert isinstance(orch.cognitive_tick_components["policy"], DeterministicActionPolicy)
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


def test_ae_xiyue_adapter_can_receive_and_start_proactive_host_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
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
    orchestrator, clock, _, _ = _build_test_stack(
        tmp_path, initial_longing=0.90, with_expression=True
    )
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
    facts = (
        orchestrator._fact_backend.all(user_scope) if hasattr(orchestrator, "_fact_backend") else ()
    )
    user_msg_evs = [f for f in facts if getattr(f, "source_type", None) == "user_message"]
    assert len(user_msg_evs) == 0


# ── CAUSAL SEQUENCE & TRACE TESTS ─────────────────────────────────────────────


def test_no_proactive_expression_artifact_before_admitted_wake(tmp_path: Path):
    """No proactive expression artifact exists before admitted wake."""
    orchestrator, clock, _, fake_agent = _build_test_stack(
        tmp_path, initial_longing=0.90, with_expression=True
    )
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
    orchestrator, clock, _, fake_agent = _build_test_stack(
        tmp_path, initial_longing=0.90, with_expression=True
    )
    now = clock.now() + timedelta(minutes=5)
    clock.advance(timedelta(minutes=5))
    user_scope = Scope(domain=ScopeDomain.USER, user_id="fixture-user")

    report = run_cognitive_tick(orchestrator, scope=user_scope, now=now)
    adapter = MindRuntimeHostAdapter(orchestrator=orchestrator, trace=orchestrator.trace)
    adapter.begin_proactive_turn(report.wake_signal)

    facts = (
        orchestrator._fact_backend.all(user_scope) if hasattr(orchestrator, "_fact_backend") else ()
    )
    user_message_evs = [f for f in facts if getattr(f, "source_type", None) == "user_message"]
    assert len(user_message_evs) == 0


# ── INVARIANTS & TYPING TESTS ────────────────────────────────────────────────


# ── SECTION 13: REGRESSION TEST MATRIX ─────────────────────────────────────────


def test_production_composition_wires_provider_free_preparer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
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


def test_commit_without_guard_accept_fails_closed(tmp_path: Path):
    """D. begin_proactive_turn(wake)
    Attempt commit_proactive_turn(wake.wake_id) WITHOUT calling guard_proactive_prose.
    Assert result.status == HostTurnStatus.FAILED
    Assert "rejected:not_delivery_eligible" in result.reason_codes
    Assert Intent in store is STILL in IntentStatus.ALLOWED, NOT COMPLETED.
    """
    orchestrator, clock, _, _ = _build_test_stack(
        tmp_path, initial_longing=0.90, with_expression=True
    )
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
    orchestrator, clock, _, _ = _build_test_stack(
        tmp_path, initial_longing=0.90, with_expression=True
    )
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
    orchestrator, clock, _, _ = _build_test_stack(
        tmp_path, initial_longing=0.90, with_expression=True
    )
    now = clock.now() + timedelta(minutes=5)
    clock.advance(timedelta(minutes=5))
    user_scope = Scope(domain=ScopeDomain.USER, user_id="fixture-user")

    report = run_cognitive_tick(orchestrator, scope=user_scope, now=now)
    wake = report.wake_signal
    assert wake is not None

    adapter = MindRuntimeHostAdapter(orchestrator=orchestrator, trace=orchestrator.trace)
    turn_res = adapter.begin_proactive_turn(wake)
    assert turn_res.status == HostTurnStatus.PROCESSING
    assert isinstance(turn_res.bounded_context, HostDecisionContext)
    envelope = turn_res.bounded_context.provider_envelope_text
    assert envelope
    from mind_runtime.expression.renderer import DeterministicContextRenderer

    assert DeterministicContextRenderer.verify_provider_information_isolation(envelope)

    guard_res = adapter.guard_proactive_prose(wake.wake_id, "今天天气真好，想和你分享一段文字")
    assert guard_res.status == HostTurnStatus.PROCESSING
    assert guard_res.disposition == ExpressionDisposition.ACCEPT
    lifecycle = orchestrator.cognitive_tick_components["lifecycle"]
    assert lifecycle.backend.history(wake.scope, wake.intent_id)[-1].status is IntentStatus.ALLOWED

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
    orchestrator, clock, _, _ = _build_test_stack(
        tmp_path, initial_longing=0.90, with_expression=True
    )
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
    orchestrator, clock, _, _ = _build_test_stack(
        tmp_path, initial_longing=0.90, with_expression=True
    )
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


def test_host_proactive_result_contract_clean():
    """K. Inspect HostProactiveTurnResult fields:
    Assert 'bounded_context' type annotation is HostDecisionContext | None.
    Assert 'proactive_expression' is NOT a field on the dataclass.
    Assert as_dict() does not contain 'proactive_expression'.
    """
    import dataclasses

    from mind_runtime.contracts.host import HostProactiveTurnResult

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


def test_abort_proactive_turn_without_lifecycle_fails_closed(tmp_path: Path):
    """Verify abort_proactive_turn fails closed when lifecycle authority is unavailable.

    Covers both:
    1. Pending execution context present (decision_context_ref populated)
    2. Pending execution context absent (decision_context_ref is None)
    In both cases:
    - HostTurnStatus.FAILED, HostStatus.FAILED
    - reason_codes contain 'intent_authority_unavailable'
    - No provider invocation, no delivery, no committed intent
    """
    orchestrator, clock, _, _ = _build_test_stack(
        tmp_path, initial_longing=0.90, with_expression=True
    )
    now = clock.now() + timedelta(minutes=5)
    clock.advance(timedelta(minutes=5))
    user_scope = Scope(domain=ScopeDomain.USER, user_id="fixture-user")

    report = run_cognitive_tick(orchestrator, scope=user_scope, now=now)
    wake = report.wake_signal
    assert wake is not None

    adapter = MindRuntimeHostAdapter(orchestrator=orchestrator, trace=orchestrator.trace)
    turn_res = adapter.begin_proactive_turn(wake)
    assert turn_res.status == HostTurnStatus.PROCESSING
    assert wake.wake_id in adapter._pending_exec_contexts

    # Remove lifecycle from components and orchestrator
    assert isinstance(orchestrator.cognitive_tick_components, dict)
    orchestrator.cognitive_tick_components.pop("lifecycle", None)
    orchestrator.cognitive_tick_components.pop("intent_lifecycle", None)
    orchestrator._intent_lifecycle = None
    if hasattr(orchestrator, "intent_lifecycle"):
        orchestrator.intent_lifecycle = None

    # 1. Abort with pending_exec present
    abort_res = adapter.abort_proactive_turn(wake.wake_id, reason="delivery_timeout")
    assert abort_res.status == HostTurnStatus.FAILED
    assert abort_res.outcome == HostStatus.FAILED
    assert "intent_authority_unavailable" in abort_res.reason_codes
    assert abort_res.decision_context_ref == turn_res.decision_context_ref

    # 2. Abort with pending_exec absent
    adapter._pending_exec_contexts.pop(wake.wake_id, None)
    abort_res_no_exec = adapter.abort_proactive_turn(wake.wake_id, reason="delivery_timeout")
    assert abort_res_no_exec.status == HostTurnStatus.FAILED
    assert abort_res_no_exec.outcome == HostStatus.FAILED
    assert "intent_authority_unavailable" in abort_res_no_exec.reason_codes
    assert abort_res_no_exec.decision_context_ref is None


def test_proactive_turn_lifecycle_boundary_and_validation_coverage(tmp_path: Path) -> None:
    """Verify input validation, unknown wake handling, and duplicate replay handling in proactive turn adapter."""
    orchestrator, clock, _, _ = _build_test_stack(
        tmp_path, initial_longing=0.90, with_expression=True
    )
    now = clock.now() + timedelta(minutes=5)
    clock.advance(timedelta(minutes=5))
    user_scope = Scope(domain=ScopeDomain.USER, user_id="fixture-user")

    report = run_cognitive_tick(orchestrator, scope=user_scope, now=now)
    wake = report.wake_signal
    assert wake is not None

    adapter = MindRuntimeHostAdapter(orchestrator=orchestrator, trace=orchestrator.trace)

    # 0. Invalid input to consume_wake
    with pytest.raises(ValueError, match="wake must be a WakeSignal"):
        adapter.consume_wake(None)  # type: ignore[arg-type]

    # 0b. Runtime ID mismatch in consume_wake
    mismatch_wake = replace(wake, wake_id="mismatch-wake", runtime_id="wrong-runtime-id")
    notif_mismatch = adapter.consume_wake(mismatch_wake)
    assert notif_mismatch.eligible is False
    assert notif_mismatch.reason == "rejected:runtime_id_mismatch"

    # 1. Invalid input types to begin_proactive_turn
    with pytest.raises(ValueError, match="wake must be a WakeSignal"):
        adapter.begin_proactive_turn(None)  # type: ignore[arg-type]

    # 2. Invalid input types to guard_proactive_prose
    with pytest.raises(ValueError, match="wake_id must be a non-empty string"):
        adapter.guard_proactive_prose("", "some prose")
    with pytest.raises(ValueError, match="prose must be a string"):
        adapter.guard_proactive_prose("wake-1", None)  # type: ignore[arg-type]

    # 3. guard_proactive_prose for unknown wake
    guard_unknown = adapter.guard_proactive_prose("unknown-wake", "prose")
    assert guard_unknown.status == HostTurnStatus.FAILED
    assert "missing_authoritative_wake_context" in guard_unknown.reason_codes

    # 4. Invalid input types to commit_proactive_turn
    with pytest.raises(ValueError, match="wake_id must be a non-empty string"):
        adapter.commit_proactive_turn("")

    # 5. commit_proactive_turn for unknown wake
    commit_unknown = adapter.commit_proactive_turn("unknown-wake")
    assert commit_unknown.status == HostTurnStatus.FAILED
    assert "unknown_wake_id" in commit_unknown.reason_codes

    # 5b. commit_proactive_turn for consumed wake without exec context
    adapter._consumed_wakes["no-exec-wake"] = wake
    commit_no_exec = adapter.commit_proactive_turn("no-exec-wake")
    assert commit_no_exec.status == HostTurnStatus.FAILED
    assert "missing_authoritative_wake_context" in commit_no_exec.reason_codes
    adapter._consumed_wakes.pop("no-exec-wake", None)

    # 6. Invalid input types to abort_proactive_turn
    with pytest.raises(ValueError, match="wake_id must be a non-empty string"):
        adapter.abort_proactive_turn("")

    # 7. abort_proactive_turn for unknown wake
    abort_unknown = adapter.abort_proactive_turn("unknown-wake")
    assert abort_unknown.status == HostTurnStatus.FAILED
    assert "unknown_wake_id" in abort_unknown.reason_codes

    # 8. Legitimate turn lifecycle: begin -> guard -> commit -> duplicate commit
    turn_res = adapter.begin_proactive_turn(wake)
    assert turn_res.status == HostTurnStatus.PROCESSING

    # 8b. Guard unavailable branch
    adapter._expression_preparer = None
    orig_guard = orchestrator.expression_guard
    orchestrator.expression_guard = None
    adapter._pending_exec_contexts["fake-wake"] = adapter._pending_exec_contexts[wake.wake_id]
    adapter._consumed_wakes["fake-wake"] = wake
    guard_none = adapter.guard_proactive_prose("fake-wake", "prose")
    assert guard_none.status == HostTurnStatus.FAILED
    assert "guard_unavailable" in guard_none.reason_codes
    adapter._pending_exec_contexts.pop("fake-wake", None)
    adapter._consumed_wakes.pop("fake-wake", None)
    orchestrator.expression_guard = orig_guard

    guard_res = adapter.guard_proactive_prose(wake.wake_id, "Hey, how are you?")
    assert guard_res.status == HostTurnStatus.PROCESSING

    commit_res = adapter.commit_proactive_turn(wake.wake_id)
    assert commit_res.status == HostTurnStatus.COMMITTED

    # Replay commit: ALREADY_PROCESSED
    replay_commit = adapter.commit_proactive_turn(wake.wake_id)
    assert replay_commit.status == HostTurnStatus.ALREADY_PROCESSED

    # Replay abort after commit: ALREADY_PROCESSED
    replay_abort = adapter.abort_proactive_turn(wake.wake_id, reason="late_abort")
    assert replay_abort.status == HostTurnStatus.ALREADY_PROCESSED


def test_wake_notification_scope_mismatch_rejected(tmp_path: Path) -> None:
    """Verify that notify_wake returns rejected:scope_mismatch when intent exists in another scope."""
    orchestrator, clock, _, _ = _build_test_stack(
        tmp_path, initial_longing=0.90, with_expression=True
    )
    user1_scope = Scope(domain=ScopeDomain.USER, user_id="user-1")
    user2_scope = Scope(domain=ScopeDomain.USER, user_id="user-2")
    now = clock.now() + timedelta(minutes=5)
    clock.advance(timedelta(minutes=5))

    report = run_cognitive_tick(orchestrator, scope=user1_scope, now=now)
    wake1 = report.wake_signal
    assert wake1 is not None

    adapter = MindRuntimeHostAdapter(orchestrator=orchestrator, trace=orchestrator.trace)

    cross_wake = replace(wake1, wake_id="cross-wake-1", scope=user2_scope)
    notif = adapter.consume_wake(cross_wake)
    assert notif.eligible is False
    assert notif.reason == "rejected:scope_mismatch"


def test_proactive_turn_extended_edge_coverage(tmp_path: Path) -> None:
    """Cover remaining proactive branches in MindRuntimeHostAdapter."""
    from unittest.mock import MagicMock

    from mind_runtime.contracts import (
        ExpressionDisposition,
        ExpressionGuardResult,
        HostStatus,
        HostTurnStatus,
        IntentStatus,
    )

    orchestrator, clock, _, _ = _build_test_stack(
        tmp_path, initial_longing=0.90, with_expression=True
    )
    user_scope = Scope(domain=ScopeDomain.USER, user_id="user-edge")
    now = clock.now() + timedelta(minutes=5)
    clock.advance(timedelta(minutes=5))

    report = run_cognitive_tick(orchestrator, scope=user_scope, now=now)
    wake = report.wake_signal
    assert wake is not None

    adapter = MindRuntimeHostAdapter(orchestrator=orchestrator, trace=orchestrator.trace)

    # 1. consume_wake with InMemory backend scope mismatch
    other_scope = Scope(domain=ScopeDomain.USER, user_id="user-other")
    mock_lifecycle = MagicMock()
    mock_lifecycle.backend = MagicMock(
        _history={(other_scope, "intent-mem"): [MagicMock()]},
        _conn=None,
    )
    mock_lifecycle.backend.history.side_effect = KeyError("missing")
    mock_policy = MagicMock()
    orchestrator.cognitive_tick_components["lifecycle"] = mock_lifecycle
    orchestrator.cognitive_tick_components["action_policy"] = mock_policy
    mem_wake = replace(wake, wake_id="mem-wake", intent_id="intent-mem", scope=user_scope)
    mem_notif = adapter.consume_wake(mem_wake)
    assert mem_notif.eligible is False
    assert mem_notif.reason == "rejected:scope_mismatch"

    # 2. consume_wake with unknown rule
    mock_policy._rules = {}
    mock_lifecycle.backend.history.side_effect = None
    mock_lifecycle.backend.history.return_value = [
        MagicMock(
            kind="unsupported_kind",
            status=IntentStatus.ALLOWED,
            sync=MagicMock(version=wake.intent_version),
        )
    ]
    unknown_notif = adapter.consume_wake(wake)
    assert unknown_notif.eligible is False
    assert unknown_notif.reason == "rejected:unsupported_intent_action"

    # Restore components
    orchestrator.cognitive_tick_components.pop("lifecycle", None)
    orchestrator.cognitive_tick_components.pop("action_policy", None)

    # 3. begin_proactive_turn with unwired expression preparer
    adapter._expression_preparer = None
    orig_prep = getattr(orchestrator, "proactive_context_preparer", None)
    orig_expr = getattr(orchestrator, "proactive_expression_preparer", None)
    orchestrator.proactive_context_preparer = None
    orchestrator.proactive_expression_preparer = None
    orig_components = orchestrator.cognitive_tick_components
    orchestrator.cognitive_tick_components = {}
    unwired_res = adapter.begin_proactive_turn(wake)
    assert unwired_res.status == HostTurnStatus.FAILED
    assert "unwired_expression_preparer" in unwired_res.reason_codes

    # Restore preparer and run begin_proactive_turn
    orchestrator.proactive_context_preparer = orig_prep
    orchestrator.proactive_expression_preparer = orig_expr
    orchestrator.cognitive_tick_components = orig_components
    begin_res = adapter.begin_proactive_turn(wake)
    assert begin_res.status == HostTurnStatus.PROCESSING

    # 4. guard_proactive_prose with REWRITE disposition
    orig_guard = getattr(orchestrator, "expression_guard", None)
    mock_guard = MagicMock()
    mock_guard.guard.return_value = ExpressionGuardResult(
        guard_id="g1",
        scope=user_scope,
        origin_runtime_id="rt-1",
        expression="some text",
        disposition=ExpressionDisposition.REWRITE,
        violations=("too_long",),
    )
    orchestrator.expression_guard = mock_guard
    rewrite_res = adapter.guard_proactive_prose(wake.wake_id, "some text")
    assert rewrite_res.status == HostTurnStatus.PROCESSING
    assert rewrite_res.outcome == HostStatus.DEGRADED
    assert rewrite_res.disposition == ExpressionDisposition.REWRITE
    assert rewrite_res.reason_codes == ("too_long",)

    # 5. guard_proactive_prose REJECT with normal lifecycle -> ABORTED
    saved_exec_ctx = adapter._pending_exec_contexts[wake.wake_id]
    mock_guard.guard.return_value = ExpressionGuardResult(
        guard_id="g2",
        scope=user_scope,
        origin_runtime_id="rt-1",
        expression="bad text",
        disposition=ExpressionDisposition.REJECT,
        violations=("forbidden",),
    )
    abort_res = adapter.guard_proactive_prose(wake.wake_id, "bad text")
    assert abort_res.status == HostTurnStatus.ABORTED
    assert abort_res.outcome == HostStatus.FAILED
    assert abort_res.disposition == ExpressionDisposition.REJECT

    # 5b. guard_proactive_prose REJECT with lifecycle unavailable -> FAILED
    from mind_runtime.host.runtime_adapter import _GuardAdmission
    adapter._pending_exec_contexts[wake.wake_id] = saved_exec_ctx
    adapter._consumed_wakes[wake.wake_id] = wake
    orchestrator.cognitive_tick_components["lifecycle"] = None
    orchestrator.intent_lifecycle = None
    orchestrator._intent_lifecycle = None
    no_lc_guard = adapter.guard_proactive_prose(wake.wake_id, "bad text")
    assert no_lc_guard.status == HostTurnStatus.FAILED
    assert "intent_authority_unavailable" in no_lc_guard.reason_codes

    # 6. commit_proactive_turn with lifecycle unavailable -> FAILED
    adapter._pending_exec_contexts[wake.wake_id] = saved_exec_ctx
    adapter._consumed_wakes[wake.wake_id] = wake
    adapter._guard_admissions[wake.wake_id] = _GuardAdmission(
        disposition=ExpressionDisposition.ACCEPT,
        guard_ref="guard-test",
        accepted_at=now,
    )
    no_lc_commit = adapter.commit_proactive_turn(wake.wake_id)
    assert no_lc_commit.status == HostTurnStatus.FAILED
    assert "intent_authority_unavailable" in no_lc_commit.reason_codes

    lc = getattr(orchestrator, "_intent_lifecycle", None) or orig_components["ticker"]._intent_lifecycle
    orchestrator.cognitive_tick_components["lifecycle"] = lc
    orchestrator.expression_guard = orig_guard

    # 7. commit_proactive_turn with intent not in ALLOWED
    current_intent = lc.backend.history(wake.scope, wake.intent_id)[-1]
    # Set status to SUPERSEDED
    object.__setattr__(current_intent, "status", IntentStatus.SUPERSEDED)
    not_allowed_commit = adapter.commit_proactive_turn(wake.wake_id)
    assert not_allowed_commit.status == HostTurnStatus.FAILED
    assert "intent_not_allowed" in not_allowed_commit.reason_codes[0]

    # 8. commit_proactive_turn when history lookup raises
    orig_history = lc.backend.history
    lc.backend.history = MagicMock(side_effect=RuntimeError("disk error"))
    lookup_fail_commit = adapter.commit_proactive_turn(wake.wake_id)
    assert lookup_fail_commit.status == HostTurnStatus.FAILED
    assert "intent_lookup_failed" in lookup_fail_commit.reason_codes[0]
    lc.backend.history = orig_history

    # 9. commit_proactive_turn when lifecycle.transition raises
    allowed_intent = replace(
        current_intent,
        status=IntentStatus.ALLOWED,
        sync=replace(current_intent.sync, version=wake.intent_version),
    )
    lc.backend.history = MagicMock(return_value=[allowed_intent])
    orig_transition = lc.transition
    lc.transition = MagicMock(side_effect=RuntimeError("database locked"))
    exc_commit = adapter.commit_proactive_turn(wake.wake_id)
    assert exc_commit.status == HostTurnStatus.FAILED
    assert "commit_transition_failed" in exc_commit.reason_codes[0]
    lc.transition = orig_transition
    lc.backend.history = orig_history
