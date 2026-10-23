"""Configured inquiry integration: host lifecycle, cooldown and competition."""

# Historical consumer audit keeps long evidence strings readable in source.
# ruff: noqa: E501

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from mind_runtime.binding_registry import BindingRegistry
from mind_runtime.cognition.tick import (
    CognitiveTicker,
)
from mind_runtime.contracts import (
    HostDecisionContext,
    HostStatus,
    HostTurnStatus,
    IntentStatus,
    ReconsiderationPolicy,
    RuntimeState,
    Scope,
    ScopeDomain,
    Situation,
    SyncFields,
)
from mind_runtime.dynamics.fast_functions import (
    validate_curiosity_anti_spam_invariant,
)
from mind_runtime.expression import (
    DeterministicContextRenderer,
    DeterministicExpressionGuardChain,
    ExpressionGuardConfig,
)
from mind_runtime.expression.context import DecisionContextConfig
from mind_runtime.host import MindRuntimeHostAdapter
from mind_runtime.intents.engine import IntentRule
from mind_runtime.intents.policy import (
    ActionPolicyConfig,
    IntentPolicyRule,
)
from mind_runtime.persona_publication import PersonaConfigPublicationRepository
from mind_runtime.runtime_binding import RuntimeBinding, RuntimeEnvironment
from mind_runtime.shadow.runtime_loop import build_runtime_stack, run_cognitive_tick
from mind_runtime.surface.recipe import (
    CANDIDATE_RECIPE_DIGEST,
    CANDIDATE_RECIPE_ID,
    CANDIDATE_RECIPE_VERSION,
)
from tests.support.fake_clock import FakeClock
from tests.surface.spec_support import sample_candidate

CERTIFIED_MANIFEST_PATH = (
    Path(__file__).resolve().parents[2]
    / "certification"
    / "d11s"
    / "inputs"
    / "runtime-config.json"
)

CURIOSITY_CALIBRATION_STATUS = "PROVISIONAL"
CURIOSITY_PRODUCTION_ACTIVATION = "BLOCKED_BY_CONFIG"
CURIOSITY_RETRIEVAL_BRANCH = "DEFERRED"
RETRIEVAL_IS_ACTION_AUTHORITY = "NO"


# ── Stack Setup Helper ───────────────────────────────────────────────────────


def _build_inquiry_test_stack(
    tmp_path: Path,
    *,
    initial_curiosity: float = 0.90,
    initial_longing: float = 0.20,
    sharing_urge: float = 0.20,
    sadness: float = 0.20,
    anger: float = 0.20,
    resources: tuple[str, ...] = (
        "proactive_question",
        "send_message",
        "proactive_share",
        "proactive_message",
    ),
    required_resource: str | None = None,
    cooldown: timedelta = timedelta(minutes=30),
    intent_rules: tuple[IntentRule, ...] | None = None,
    policy_rules: tuple[IntentPolicyRule, ...] | None = None,
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

    if intent_rules is None:
        inquiry_rule = IntentRule(
            rule_id="inquiry",
            kind="proactive_inquiry",
            base_strength=0.0,
            dimension_weights=(("agent.affect.curiosity", 1.0),),
            event_kind=None,
            event_bonus=0,
            minimum_strength=0.4,
            due_at_attribute=None,
            expires_after=None,
            reconsideration_policy=ReconsiderationPolicy.ON_CONTEXT_CHANGE,
            surface_control_weights=(),
        )
        intent_rules = (inquiry_rule,)

    if policy_rules is None:
        inquiry_policy_rule = IntentPolicyRule(
            intent_kind="proactive_inquiry",
            action_type="proactive_question",
            proactive=True,
            interrupts_active_conversation=False,
            media_counter_fact=None,
            media_limit=None,
            required_resource=required_resource,
        )
        policy_rules = (inquiry_policy_rule,)

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
        intent_rules=intent_rules,
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

    vals = dict(
        longing=initial_longing,
        closeness_craving=0.50,
        anger=anger,
        sharing_urge=sharing_urge,
        curiosity=initial_curiosity,
        sadness=sadness,
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

    return orchestrator, clock, delivery_db


# ── SECTION 13: REQUIRED STRUCTURAL & SCORING TESTS (A - L) ─────────────────


def test_l_candidate_surface_recipe_digest_remains_unchanged() -> None:
    """L. Candidate recipe digest remains bit-for-bit unchanged."""
    assert CANDIDATE_RECIPE_ID == "surface-v1-candidate"
    assert CANDIDATE_RECIPE_VERSION == 2
    assert (
        CANDIDATE_RECIPE_DIGEST
        == "4f37f46f89f6176fd5fefe0167ec7a81e341839f4fb9b98fa3cc348ddeaf9a55"
    )


# ── SECTION 14: REQUIRED PROACTIVE CHAIN TESTS (M - W) ───────────────────────


def test_v_guard_accept_and_explicit_commit_transitions_intent_completed(tmp_path: Path) -> None:
    """V. Guard ACCEPT + explicit commit -> Intent COMPLETED."""
    orchestrator, clock, _ = _build_inquiry_test_stack(tmp_path, initial_curiosity=0.90)
    now = clock.now() + timedelta(minutes=5)
    clock.advance(timedelta(minutes=5))
    user_scope = Scope(domain=ScopeDomain.USER, user_id="fixture-user")

    report = run_cognitive_tick(orchestrator, scope=user_scope, now=now)
    wake = report.wake_signal
    assert wake is not None
    assert wake.intent_id.endswith("-inquiry")
    assert wake.action_type == "proactive_question"

    adapter = MindRuntimeHostAdapter(orchestrator=orchestrator, trace=orchestrator.trace)
    begun = adapter.begin_proactive_turn(wake)
    assert begun.status == HostTurnStatus.PROCESSING
    assert isinstance(begun.bounded_context, HostDecisionContext)
    envelope = begun.bounded_context.provider_envelope_text
    assert envelope and "proactive_question" in envelope
    assert DeterministicContextRenderer.verify_provider_information_isolation(envelope)

    prose = "你刚才提到的那个项目，目前进展得怎么样了？"
    guard_res = adapter.guard_proactive_prose(wake.wake_id, prose)
    assert guard_res.status == HostTurnStatus.PROCESSING
    assert guard_res.outcome == HostStatus.OK
    lifecycle = orchestrator.cognitive_tick_components["lifecycle"]
    assert lifecycle.backend.history(user_scope, wake.intent_id)[-1].status == IntentStatus.ALLOWED

    commit_res = adapter.commit_proactive_turn(wake.wake_id)
    assert commit_res.status == HostTurnStatus.COMMITTED
    assert commit_res.outcome == HostStatus.OK

    # Intent in store is now COMPLETED
    lifecycle = orchestrator.cognitive_tick_components["lifecycle"]
    intents = lifecycle.backend.history(user_scope, wake.intent_id)
    assert len(intents) > 0
    assert intents[-1].status == IntentStatus.COMPLETED


# ── SECTION 15: ANTI-SPAM TESTS (X - AB) ─────────────────────────────────────


def test_x_higher_curiosity_cannot_shorten_proactive_cooldown(tmp_path: Path) -> None:
    """X. Higher curiosity cannot shorten proactive cooldown."""
    # Invariant validator check
    assert (
        validate_curiosity_anti_spam_invariant(
            curiosity=1.0,
            base_cooldown_seconds=1800.0,
            effective_cooldown_seconds=1800.0,
        )
        is True
    )
    with pytest.raises(ValueError, match="Curiosity anti-spam violation"):
        validate_curiosity_anti_spam_invariant(
            curiosity=1.0,
            base_cooldown_seconds=1800.0,
            effective_cooldown_seconds=300.0,
        )

    # Runtime check: even with curiosity=1.0, active cooldown defers and prevents wake
    orchestrator, clock, _ = _build_inquiry_test_stack(
        tmp_path, initial_curiosity=1.0, cooldown=timedelta(minutes=30)
    )
    user_scope = Scope(domain=ScopeDomain.USER, user_id="fixture-user")

    # Tick 1: Allowed -> WakeSignal emitted
    t1 = clock.now() + timedelta(minutes=5)
    clock.advance(timedelta(minutes=5))
    report1 = run_cognitive_tick(orchestrator, scope=user_scope, now=t1)
    assert report1.policy_allowed == 1
    assert report1.wake_signal is not None

    # Tick 2 (5 minutes later, while cooldown is 30m): Even with curiosity=1.0, cooldown DEFER
    t2 = clock.now() + timedelta(minutes=5)
    clock.advance(timedelta(minutes=5))
    report2 = run_cognitive_tick(orchestrator, scope=user_scope, now=t2)
    assert report2.policy_allowed == 0
    assert report2.wake_signal is None


# ── SECTION 16: RETRIEVAL INDEPENDENCE & ISOLATION TESTS (AC - AH) ───────────


def test_ag_cognitive_ticker_does_not_invoke_retrieval(tmp_path: Path) -> None:
    """AG. CognitiveTicker does NOT invoke retrieval; tick situation has historical_context=None."""
    orchestrator, clock, _ = _build_inquiry_test_stack(tmp_path, initial_curiosity=0.90)
    ticker: CognitiveTicker = orchestrator.cognitive_tick_components["ticker"]

    # Verify CognitiveTicker has no memory retrieval service injected
    assert hasattr(ticker, "retrieval_service") is False
    assert hasattr(ticker, "_retrieval_service") is False

    user_scope = Scope(domain=ScopeDomain.USER, user_id="fixture-user")
    now = clock.now() + timedelta(minutes=5)
    clock.advance(timedelta(minutes=5))

    report = run_cognitive_tick(orchestrator, scope=user_scope, now=now)
    wake = report.wake_signal
    assert wake is not None

    # Check pending wake context
    ctx = ticker.get_pending_wake_context(wake.wake_id)
    assert ctx is not None
    situation: Situation = ctx["situation"]
    assert situation.historical_context is None


# ── SECTION 17: NO RAW-STATE PROVIDER LEAK (AI) ──────────────────────────────


def test_ai_information_isolation_explicitly_forbids_curiosity() -> None:
    """AI: 'curiosity' is explicitly forbidden in provider-visible text."""
    with pytest.raises(AssertionError, match="curiosity"):
        DeterministicContextRenderer.verify_provider_information_isolation(
            "ACTION: selected_action = proactive_question\nDynamics: curiosity = 0.9"
        )

    with pytest.raises(AssertionError, match="curiosity"):
        DeterministicContextRenderer.verify_provider_information_isolation(
            "agent.affect.curiosity is high"
        )


# ── SECTION 18: PRODUCTION CONFIG STATUS (AJ) ────────────────────────────────


# ── SECTION 19: MULTI-URGE INDEPENDENCE & COMPETITION (AK - AO) ──────────────


def test_an_three_way_competition_emits_single_wake(tmp_path: Path) -> None:
    """AN: When reach_out, spontaneous_share, and proactive_inquiry all exist, exactly one WakeSignal is emitted."""
    contact_rule = IntentRule(
        rule_id="contact",
        kind="reach_out",
        base_strength=0.2,
        dimension_weights=(),
        event_kind=None,
        event_bonus=0,
        minimum_strength=0.3,
        due_at_attribute=None,
        expires_after=None,
        reconsideration_policy=ReconsiderationPolicy.ON_CONTEXT_CHANGE,
        surface_control_weights=(("contact_seeking", 0.5),),
    )
    share_rule = IntentRule(
        rule_id="share",
        kind="spontaneous_share",
        base_strength=0.0,
        dimension_weights=(("agent.affect.sharing_urge", 1.0),),
        event_kind=None,
        event_bonus=0,
        minimum_strength=0.3,
        due_at_attribute=None,
        expires_after=None,
        reconsideration_policy=ReconsiderationPolicy.ON_CONTEXT_CHANGE,
        surface_control_weights=(),
    )
    inquiry_rule = IntentRule(
        rule_id="inquiry",
        kind="proactive_inquiry",
        base_strength=0.0,
        dimension_weights=(("agent.affect.curiosity", 1.0),),
        event_kind=None,
        event_bonus=0,
        minimum_strength=0.3,
        due_at_attribute=None,
        expires_after=None,
        reconsideration_policy=ReconsiderationPolicy.ON_CONTEXT_CHANGE,
        surface_control_weights=(),
    )
    contact_policy = IntentPolicyRule(
        intent_kind="reach_out",
        action_type="proactive_message",
        proactive=True,
        interrupts_active_conversation=False,
        media_counter_fact=None,
        media_limit=None,
        required_resource=None,
    )
    share_policy = IntentPolicyRule(
        intent_kind="spontaneous_share",
        action_type="proactive_share",
        proactive=True,
        interrupts_active_conversation=False,
        media_counter_fact=None,
        media_limit=None,
        required_resource=None,
    )
    inquiry_policy = IntentPolicyRule(
        intent_kind="proactive_inquiry",
        action_type="proactive_question",
        proactive=True,
        interrupts_active_conversation=False,
        media_counter_fact=None,
        media_limit=None,
        required_resource=None,
    )

    # Setup with curiosity highest: curiosity=0.95, sharing_urge=0.50, longing=0.50
    orchestrator, clock, _ = _build_inquiry_test_stack(
        tmp_path,
        initial_curiosity=0.95,
        sharing_urge=0.50,
        initial_longing=0.50,
        intent_rules=(contact_rule, share_rule, inquiry_rule),
        policy_rules=(contact_policy, share_policy, inquiry_policy),
    )
    now = clock.now() + timedelta(minutes=5)
    clock.advance(timedelta(minutes=5))
    user_scope = Scope(domain=ScopeDomain.USER, user_id="fixture-user")

    report = run_cognitive_tick(orchestrator, scope=user_scope, now=now)
    assert report.wake_signal is not None
    # proactive_inquiry won the competition
    assert report.wake_signal.action_type == "proactive_question"
    assert "inquiry" in report.wake_signal.intent_id

    # The other candidates were superseded
    lifecycle = orchestrator.cognitive_tick_components["lifecycle"]
    current_intents = {i.kind: i.status for i in lifecycle.backend.current(user_scope)}
    assert current_intents["proactive_inquiry"] == IntentStatus.ALLOWED
    assert current_intents["spontaneous_share"] == IntentStatus.SUPERSEDED
    assert current_intents["reach_out"] == IntentStatus.SUPERSEDED
