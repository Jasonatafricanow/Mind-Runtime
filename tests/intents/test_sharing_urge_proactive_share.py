"""Configured sharing integration: host lifecycle and cooldown."""

# Historical consumer audit keeps long evidence strings readable in source.
# ruff: noqa: E501

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from mind_runtime.binding_registry import BindingRegistry
from mind_runtime.contracts import (
    HostDecisionContext,
    HostStatus,
    HostTurnStatus,
    IntentStatus,
    ReconsiderationPolicy,
    RuntimeState,
    Scope,
    ScopeDomain,
    SyncFields,
)
from mind_runtime.dynamics.fast_functions import (
    validate_sharing_urge_anti_spam_invariant,
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
from tests.support.fake_clock import FakeClock
from tests.surface.spec_support import sample_candidate

CERTIFIED_MANIFEST_PATH = (
    Path(__file__).resolve().parents[2]
    / "certification"
    / "d11s"
    / "inputs"
    / "runtime-config.json"
)

SHARING_URGE_CALIBRATION_STATUS = "PROVISIONAL"
SHARING_URGE_PRODUCTION_ACTIVATION = "BLOCKED_BY_CONFIG"


# ── Stack Setup Helper ───────────────────────────────────────────────────────


def _build_share_test_stack(
    tmp_path: Path,
    *,
    initial_sharing_urge: float = 0.90,
    initial_longing: float = 0.20,
    curiosity: float = 0.50,
    sadness: float = 0.20,
    resources: tuple[str, ...] = ("proactive_share", "proactive_message", "send_message"),
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
        share_rule = IntentRule(
            rule_id="share",
            kind="spontaneous_share",
            base_strength=0.0,
            dimension_weights=(("agent.affect.sharing_urge", 1.0),),
            event_kind=None,
            event_bonus=0,
            minimum_strength=0.4,
            due_at_attribute=None,
            expires_after=None,
            reconsideration_policy=ReconsiderationPolicy.ON_CONTEXT_CHANGE,
            surface_control_weights=(),
        )
        intent_rules = (share_rule,)

    if policy_rules is None:
        share_policy_rule = IntentPolicyRule(
            intent_kind="spontaneous_share",
            action_type="proactive_share",
            proactive=True,
            interrupts_active_conversation=False,
            media_counter_fact=None,
            media_limit=None,
            required_resource=required_resource,
        )
        policy_rules = (share_policy_rule,)

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

    # Seed all persona dimensions in state DB under agent_scope matching persona_id
    vals = dict(
        longing=initial_longing,
        closeness_craving=0.50,
        anger=0.20,
        sharing_urge=initial_sharing_urge,
        curiosity=curiosity,
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


# ── SECTION 13: REQUIRED STRUCTURAL TESTS (A - K) ────────────────────────────


# ── SECTION 14: REQUIRED PROACTIVE CHAIN TESTS (L - V) ───────────────────────


def test_u_guard_accept_and_explicit_commit_transitions_intent_completed(tmp_path: Path) -> None:
    """U. Guard ACCEPT + explicit commit -> Intent COMPLETED."""
    orchestrator, clock, _ = _build_share_test_stack(tmp_path, initial_sharing_urge=0.90)
    now = clock.now() + timedelta(minutes=5)
    clock.advance(timedelta(minutes=5))
    user_scope = Scope(domain=ScopeDomain.USER, user_id="fixture-user")

    report = run_cognitive_tick(orchestrator, scope=user_scope, now=now)
    wake = report.wake_signal
    assert wake is not None
    assert wake.intent_id.endswith("-share")
    assert wake.action_type == "proactive_share"

    adapter = MindRuntimeHostAdapter(orchestrator=orchestrator, trace=orchestrator.trace)
    begun = adapter.begin_proactive_turn(wake)
    assert begun.status == HostTurnStatus.PROCESSING
    assert isinstance(begun.bounded_context, HostDecisionContext)
    envelope = begun.bounded_context.provider_envelope_text
    assert envelope and "proactive_share" in envelope
    assert DeterministicContextRenderer.verify_provider_information_isolation(envelope)

    prose = "我刚刚看到一篇很有意思的文章，想和你分享一下。"
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


# ── SECTION 15: ANTI-SPAM TESTS (W - Z) ──────────────────────────────────────


def test_w_higher_sharing_urge_cannot_shorten_proactive_cooldown(tmp_path: Path) -> None:
    """W. Higher sharing_urge cannot shorten proactive cooldown."""
    # Invariant validator check
    assert (
        validate_sharing_urge_anti_spam_invariant(
            sharing_urge=1.0,
            base_cooldown_seconds=1800.0,
            effective_cooldown_seconds=1800.0,
        )
        is True
    )
    with pytest.raises(ValueError, match="Sharing urge anti-spam violation"):
        validate_sharing_urge_anti_spam_invariant(
            sharing_urge=1.0,
            base_cooldown_seconds=1800.0,
            effective_cooldown_seconds=300.0,
        )

    # Runtime check: even with sharing_urge=1.0, active cooldown defers and prevents wake
    orchestrator, clock, _ = _build_share_test_stack(
        tmp_path, initial_sharing_urge=1.0, cooldown=timedelta(minutes=30)
    )
    user_scope = Scope(domain=ScopeDomain.USER, user_id="fixture-user")

    # Tick 1: Allowed -> WakeSignal emitted
    t1 = clock.now() + timedelta(minutes=5)
    clock.advance(timedelta(minutes=5))
    report1 = run_cognitive_tick(orchestrator, scope=user_scope, now=t1)
    assert report1.policy_allowed == 1
    assert report1.wake_signal is not None

    # Tick 2 (5 minutes later, while cooldown is 30m): Even with sharing_urge=1.0, cooldown DEFER
    t2 = clock.now() + timedelta(minutes=5)
    clock.advance(timedelta(minutes=5))
    report2 = run_cognitive_tick(orchestrator, scope=user_scope, now=t2)
    assert report2.policy_allowed == 0
    assert report2.wake_signal is None


# ── SECTION 16: NO RAW-STATE PROVIDER LEAK ───────────────────────────────────


def test_information_isolation_explicitly_forbids_sharing_urge() -> None:
    """Section 16: 'sharing_urge' is explicitly forbidden in provider-visible text."""
    from mind_runtime.expression.renderer import DeterministicContextRenderer

    with pytest.raises(AssertionError, match="sharing_urge"):
        DeterministicContextRenderer.verify_provider_information_isolation(
            "ACTION: selected_action = proactive_share\nDynamics: sharing_urge = 0.9"
        )

    with pytest.raises(AssertionError, match="sharing_urge"):
        DeterministicContextRenderer.verify_provider_information_isolation(
            "agent.affect.sharing_urge is high"
        )


# ── SECTION 17: PRODUCTION CONFIG STATUS ─────────────────────────────────────


# ── SECTION 18 & 12: DO NOT TOUCH LONGING & COMPETITION ─────────────────────
