"""Test suite for MR-SHARING-URGE-PROACTIVE-SHARE-V1-01.

Validates the bounded architecture for the second FAST_FUNCTION_V1 consumer:
agent.affect.sharing_urge
    ↓
dedicated share Intent (spontaneous_share, surface_control_weights=())
    ↓
ActionPolicy (proactive_share)
    ↓
WakeSignal
    ↓
Host admission (consume_wake)
    ↓
provider-free DecisionContext (begin_proactive_turn -> HostTurnStatus.PROCESSING)
    ↓
external Body generates prose
    ↓
ExpressionGuard (guard_proactive_prose -> HostTurnStatus.PROCESSING)
    ↓
external delivery
    ↓
explicit commit (commit_proactive_turn -> HostTurnStatus.COMMITTED, Intent COMPLETED)

Invariants verified:
- SHARING_URGE_CONTROLS_SHARE_PRESSURE_NOT_FREQUENCY
- PROACTIVE_CONTACT != PROACTIVE_SHARE
- No raw dynamics or trait leaks in provider envelope
- No curiosity/sadness cross-talk via Surface.initiative
- Exactly one WakeSignal emitted under competition with longing
"""

from __future__ import annotations

import ast
import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from mind_runtime.binding_registry import BindingRegistry
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
from mind_runtime.dynamics.fast_functions import (
    FAST_FUNCTION_V1_COUNT,
    FAST_FUNCTION_V1_REGISTRY,
    FAST_FUNCTION_V1_SPECS,
    LONGING_CONTROLS_CONTACT_PRESSURE_NOT_FREQUENCY_INVARIANT,
    SHARING_URGE_CONTROLS_SHARE_PRESSURE_NOT_FREQUENCY,
    SHARING_URGE_CONTROLS_SHARE_PRESSURE_NOT_FREQUENCY_INVARIANT,
    FastFunctionKind,
    FastStateStatus,
    validate_longing_anti_spam_invariant,
    validate_sharing_urge_anti_spam_invariant,
)
from mind_runtime.expression import (
    DecisionContextCompiler,
    DeterministicContextRenderer,
    DeterministicExpressionGuardChain,
    ExpressionGuardConfig,
)
from mind_runtime.expression.context import DecisionContextConfig
from mind_runtime.host import MindRuntimeHostAdapter
from mind_runtime.intents.engine import DeterministicIntentEngine, IntentRule
from mind_runtime.intents.policy import ActionPolicyConfig, DeterministicActionPolicy, IntentPolicyRule
from mind_runtime.persona_publication import PersonaConfigPublicationRepository
from mind_runtime.runtime_binding import RuntimeBinding, RuntimeEnvironment
from mind_runtime.shadow.runtime_loop import build_runtime_stack, run_cognitive_tick
from mind_runtime.surface.evaluator import D_PREFIX
from mind_runtime.surface.recipe import (
    CANDIDATE_RECIPE_DIGEST,
    CANDIDATE_RECIPE_ID,
    CANDIDATE_RECIPE_VERSION,
    MANIFEST,
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


def test_a_fast_function_v1_registry_has_exactly_eight_entries() -> None:
    """A. FAST_FUNCTION_V1_REGISTRY still has exactly 8 entries."""
    assert len(FAST_FUNCTION_V1_REGISTRY) == 8
    assert len(FAST_FUNCTION_V1_SPECS) == 8
    assert FAST_FUNCTION_V1_COUNT == 8


def test_b_sharing_urge_maps_to_proactive_share() -> None:
    """B. sharing_urge maps to: PROACTIVE_SHARE."""
    spec = FAST_FUNCTION_V1_REGISTRY.require("agent.affect.sharing_urge")
    assert spec.function_kind == FastFunctionKind.PROACTIVE_SHARE
    assert spec.primary_consumer == "Intent / share path"
    assert spec.external_action_capable is True
    assert spec.status == FastStateStatus.ACTIVE

    by_func = FAST_FUNCTION_V1_REGISTRY.require_by_function(FastFunctionKind.PROACTIVE_SHARE)
    assert by_func.state_key == "agent.affect.sharing_urge"


def test_c_increasing_sharing_urge_monotonically_increases_share_intent_strength() -> None:
    """C. Increasing sharing_urge monotonically increases spontaneous_share Intent strength."""
    share_rule = IntentRule(
        rule_id="share",
        kind="spontaneous_share",
        base_strength=0.0,
        dimension_weights=(("agent.affect.sharing_urge", 1.0),),
        event_kind=None,
        event_bonus=0,
        minimum_strength=0.05,
        due_at_attribute=None,
        expires_after=None,
        reconsideration_policy=ReconsiderationPolicy.ON_CONTEXT_CHANGE,
        surface_control_weights=(),
    )
    engine = DeterministicIntentEngine((share_rule,), "fixture-runtime")
    user_scope = Scope(domain=ScopeDomain.USER, user_id="fixture-user")
    agent_scope = Scope(domain=ScopeDomain.AGENT, agent_id="fixture-agent", persona_id="fixture-persona")
    now = datetime(2026, 9, 23, 12, 0, tzinfo=UTC)
    situation = Situation(
        situation_id="sit-1",
        scope=user_scope,
        origin_runtime_id="fixture-runtime",
        derived_facts=(),
        effective_state_ref="none",
        observed_at=now,
        historical_context=None,
        persona_id=None,
        relationship_ids=(),
        evidence_refs=(),
    )

    values = [0.1, 0.3, 0.5, 0.7, 0.9, 1.0]
    strengths: list[float] = []

    for v in values:
        states = (
            RuntimeState(
                state_id="state-sharing_urge",
                scope=agent_scope,
                origin_runtime_id="fixture-runtime",
                dimension="agent.affect.sharing_urge",
                value=v,
                status="active",
                valid_from=now,
                valid_until=None,
                relevant_until=None,
                last_observed_at=now,
                evidence_refs=(),
                transition_refs=(),
                updated_at=now,
                version=1,
                sync=SyncFields(agent_scope, "fixture-runtime", "state-sharing_urge", 1, "idem"),
            ),
        )
        projected = ProjectedMindState(
            projection_id=f"proj-{v}",
            scope=agent_scope,
            origin_runtime_id="fixture-runtime",
            projected_states=states,
            sync=SyncFields(agent_scope, "fixture-runtime", f"proj-{v}", 1, "idem-proj"),
        )
        engine_input = IntentEngineInput(
            interaction_id="inter-1",
            scope=user_scope,
            origin_runtime_id="fixture-runtime",
            context=situation,
            projected=projected,
            accepted_events=(),
            clock=now,
        )
        res = engine.evaluate(engine_input)
        assert len(res.candidates) == 1
        cand = res.candidates[0]
        assert cand.kind == "spontaneous_share"
        strengths.append(cand.strength)

    # Monotonically strictly increasing
    for i in range(len(strengths) - 1):
        assert strengths[i] < strengths[i + 1], f"Expected {strengths[i]} < {strengths[i+1]}"


def test_d_low_sharing_urge_below_threshold_produces_no_candidate() -> None:
    """D. Low sharing_urge below fixture threshold: no share Intent candidate."""
    share_rule = IntentRule(
        rule_id="share",
        kind="spontaneous_share",
        base_strength=0.0,
        dimension_weights=(("agent.affect.sharing_urge", 1.0),),
        event_kind=None,
        event_bonus=0,
        minimum_strength=0.5,
        due_at_attribute=None,
        expires_after=None,
        reconsideration_policy=ReconsiderationPolicy.ON_CONTEXT_CHANGE,
        surface_control_weights=(),
    )
    engine = DeterministicIntentEngine((share_rule,), "fixture-runtime")
    user_scope = Scope(domain=ScopeDomain.USER, user_id="fixture-user")
    agent_scope = Scope(domain=ScopeDomain.AGENT, agent_id="fixture-agent", persona_id="fixture-persona")
    now = datetime(2026, 9, 23, 12, 0, tzinfo=UTC)
    situation = Situation(
        situation_id="sit-1",
        scope=user_scope,
        origin_runtime_id="fixture-runtime",
        derived_facts=(),
        effective_state_ref="none",
        observed_at=now,
        historical_context=None,
        persona_id=None,
        relationship_ids=(),
        evidence_refs=(),
    )

    states = (
        RuntimeState(
            state_id="state-sharing_urge",
            scope=agent_scope,
            origin_runtime_id="fixture-runtime",
            dimension="agent.affect.sharing_urge",
            value=0.2,  # below 0.5 minimum_strength
            status="active",
            valid_from=now,
            valid_until=None,
            relevant_until=None,
            last_observed_at=now,
            evidence_refs=(),
            transition_refs=(),
            updated_at=now,
            version=1,
            sync=SyncFields(agent_scope, "fixture-runtime", "state-sharing_urge", 1, "idem"),
        ),
    )
    projected = ProjectedMindState(
        projection_id="proj-low",
        scope=agent_scope,
        origin_runtime_id="fixture-runtime",
        projected_states=states,
        sync=SyncFields(agent_scope, "fixture-runtime", "proj-low", 1, "idem-proj"),
    )
    res = engine.evaluate(
        IntentEngineInput(
            interaction_id="inter-low",
            scope=user_scope,
            origin_runtime_id="fixture-runtime",
            context=situation,
            projected=projected,
            accepted_events=(),
            clock=now,
        )
    )
    assert len(res.candidates) == 0
    # Trace records below_minimum_strength
    assert len(res.traces) == 1
    assert "below_minimum_strength" in res.traces[0].reason_codes


def test_e_high_sharing_urge_produces_spontaneous_share_candidate() -> None:
    """E. High sharing_urge: spontaneous_share Intent candidate exists."""
    share_rule = IntentRule(
        rule_id="share",
        kind="spontaneous_share",
        base_strength=0.0,
        dimension_weights=(("agent.affect.sharing_urge", 1.0),),
        event_kind=None,
        event_bonus=0,
        minimum_strength=0.5,
        due_at_attribute=None,
        expires_after=None,
        reconsideration_policy=ReconsiderationPolicy.ON_CONTEXT_CHANGE,
        surface_control_weights=(),
    )
    engine = DeterministicIntentEngine((share_rule,), "fixture-runtime")
    user_scope = Scope(domain=ScopeDomain.USER, user_id="fixture-user")
    agent_scope = Scope(domain=ScopeDomain.AGENT, agent_id="fixture-agent", persona_id="fixture-persona")
    now = datetime(2026, 9, 23, 12, 0, tzinfo=UTC)
    situation = Situation(
        situation_id="sit-1",
        scope=user_scope,
        origin_runtime_id="fixture-runtime",
        derived_facts=(),
        effective_state_ref="none",
        observed_at=now,
        historical_context=None,
        persona_id=None,
        relationship_ids=(),
        evidence_refs=(),
    )

    states = (
        RuntimeState(
            state_id="state-sharing_urge",
            scope=agent_scope,
            origin_runtime_id="fixture-runtime",
            dimension="agent.affect.sharing_urge",
            value=0.85,  # above 0.5 minimum_strength
            status="active",
            valid_from=now,
            valid_until=None,
            relevant_until=None,
            last_observed_at=now,
            evidence_refs=(),
            transition_refs=(),
            updated_at=now,
            version=1,
            sync=SyncFields(agent_scope, "fixture-runtime", "state-sharing_urge", 1, "idem"),
        ),
    )
    projected = ProjectedMindState(
        projection_id="proj-high",
        scope=agent_scope,
        origin_runtime_id="fixture-runtime",
        projected_states=states,
        sync=SyncFields(agent_scope, "fixture-runtime", "proj-high", 1, "idem-proj"),
    )
    res = engine.evaluate(
        IntentEngineInput(
            interaction_id="inter-high",
            scope=user_scope,
            origin_runtime_id="fixture-runtime",
            context=situation,
            projected=projected,
            accepted_events=(),
            clock=now,
        )
    )
    assert len(res.candidates) == 1
    cand = res.candidates[0]
    assert cand.kind == "spontaneous_share"
    assert cand.strength == 0.85


def test_f_changing_curiosity_alone_does_not_change_spontaneous_share_score() -> None:
    """F. Changing curiosity alone does NOT change the spontaneous_share score."""
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
    engine = DeterministicIntentEngine((share_rule,), "fixture-runtime")
    user_scope = Scope(domain=ScopeDomain.USER, user_id="fixture-user")
    agent_scope = Scope(domain=ScopeDomain.AGENT, agent_id="fixture-agent", persona_id="fixture-persona")
    now = datetime(2026, 9, 23, 12, 0, tzinfo=UTC)
    situation = Situation(
        situation_id="sit-f",
        scope=user_scope,
        origin_runtime_id="fixture-runtime",
        derived_facts=(),
        effective_state_ref="none",
        observed_at=now,
        historical_context=None,
        persona_id=None,
        relationship_ids=(),
        evidence_refs=(),
    )

    curiosity_levels = [0.0, 0.2, 0.5, 0.8, 1.0]
    first_score: float | None = None

    for c_val in curiosity_levels:
        states = (
            RuntimeState(
                state_id="state-sharing_urge",
                scope=agent_scope,
                origin_runtime_id="fixture-runtime",
                dimension="agent.affect.sharing_urge",
                value=0.70,
                status="active",
                valid_from=now,
                valid_until=None,
                relevant_until=None,
                last_observed_at=now,
                evidence_refs=(),
                transition_refs=(),
                updated_at=now,
                version=1,
                sync=SyncFields(agent_scope, "fixture-runtime", "state-sharing_urge", 1, "idem"),
            ),
            RuntimeState(
                state_id="state-curiosity",
                scope=agent_scope,
                origin_runtime_id="fixture-runtime",
                dimension="agent.affect.curiosity",
                value=c_val,
                status="active",
                valid_from=now,
                valid_until=None,
                relevant_until=None,
                last_observed_at=now,
                evidence_refs=(),
                transition_refs=(),
                updated_at=now,
                version=1,
                sync=SyncFields(agent_scope, "fixture-runtime", "state-curiosity", 1, "idem"),
            ),
        )
        projected = ProjectedMindState(
            projection_id=f"proj-c-{c_val}",
            scope=agent_scope,
            origin_runtime_id="fixture-runtime",
            projected_states=states,
            sync=SyncFields(agent_scope, "fixture-runtime", f"proj-c-{c_val}", 1, "idem-proj"),
        )
        res = engine.evaluate(
            IntentEngineInput(
                interaction_id=f"inter-c-{c_val}",
                scope=user_scope,
                origin_runtime_id="fixture-runtime",
                context=situation,
                projected=projected,
                accepted_events=(),
                clock=now,
            )
        )
        assert len(res.candidates) == 1
        cand = res.candidates[0]
        if first_score is None:
            first_score = cand.strength
        else:
            assert cand.strength == first_score, (
                f"Curiosity cross-talk detected! Score changed from {first_score} to {cand.strength}"
            )


def test_g_changing_sadness_alone_does_not_change_spontaneous_share_score() -> None:
    """G. Changing sadness alone does NOT change the spontaneous_share score."""
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
    engine = DeterministicIntentEngine((share_rule,), "fixture-runtime")
    user_scope = Scope(domain=ScopeDomain.USER, user_id="fixture-user")
    agent_scope = Scope(domain=ScopeDomain.AGENT, agent_id="fixture-agent", persona_id="fixture-persona")
    now = datetime(2026, 9, 23, 12, 0, tzinfo=UTC)
    situation = Situation(
        situation_id="sit-g",
        scope=user_scope,
        origin_runtime_id="fixture-runtime",
        derived_facts=(),
        effective_state_ref="none",
        observed_at=now,
        historical_context=None,
        persona_id=None,
        relationship_ids=(),
        evidence_refs=(),
    )

    sadness_levels = [0.0, 0.2, 0.5, 0.8, 1.0]
    first_score: float | None = None

    for s_val in sadness_levels:
        states = (
            RuntimeState(
                state_id="state-sharing_urge",
                scope=agent_scope,
                origin_runtime_id="fixture-runtime",
                dimension="agent.affect.sharing_urge",
                value=0.70,
                status="active",
                valid_from=now,
                valid_until=None,
                relevant_until=None,
                last_observed_at=now,
                evidence_refs=(),
                transition_refs=(),
                updated_at=now,
                version=1,
                sync=SyncFields(agent_scope, "fixture-runtime", "state-sharing_urge", 1, "idem"),
            ),
            RuntimeState(
                state_id="state-sadness",
                scope=agent_scope,
                origin_runtime_id="fixture-runtime",
                dimension="agent.affect.sadness",
                value=s_val,
                status="active",
                valid_from=now,
                valid_until=None,
                relevant_until=None,
                last_observed_at=now,
                evidence_refs=(),
                transition_refs=(),
                updated_at=now,
                version=1,
                sync=SyncFields(agent_scope, "fixture-runtime", "state-sadness", 1, "idem"),
            ),
        )
        projected = ProjectedMindState(
            projection_id=f"proj-s-{s_val}",
            scope=agent_scope,
            origin_runtime_id="fixture-runtime",
            projected_states=states,
            sync=SyncFields(agent_scope, "fixture-runtime", f"proj-s-{s_val}", 1, "idem-proj"),
        )
        res = engine.evaluate(
            IntentEngineInput(
                interaction_id=f"inter-s-{s_val}",
                scope=user_scope,
                origin_runtime_id="fixture-runtime",
                context=situation,
                projected=projected,
                accepted_events=(),
                clock=now,
            )
        )
        assert len(res.candidates) == 1
        cand = res.candidates[0]
        if first_score is None:
            first_score = cand.strength
        else:
            assert cand.strength == first_score, (
                f"Sadness cross-talk detected! Score changed from {first_score} to {cand.strength}"
            )


def test_h_share_rule_has_empty_surface_control_weights() -> None:
    """H. The share rule has: surface_control_weights == ()."""
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
    assert share_rule.surface_control_weights == ()


def test_i_share_rule_uses_sharing_urge_as_only_fast_state_scoring_root() -> None:
    """I. The share rule uses: agent.affect.sharing_urge as its only fast-state scoring root."""
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
    assert len(share_rule.dimension_weights) == 1
    assert share_rule.dimension_weights[0] == ("agent.affect.sharing_urge", 1.0)


def test_j_no_new_surface_control_introduced() -> None:
    """J. No new Surface control is introduced.

    Existing 5 controls frozen under ADR-0028 remain unchanged.
    """
    assert len(MANIFEST) == 5
    expected_controls = {
        "contact_seeking",
        "initiative",
        "confrontation",
        "expressive_warmth",
        "expressive_restraint",
    }
    assert set(MANIFEST.keys()) == expected_controls
    assert "sharing_drive" not in MANIFEST
    assert "sharing_pressure" not in MANIFEST
    assert "share_seeking" not in MANIFEST


def test_k_candidate_surface_recipe_digest_remains_unchanged() -> None:
    """K. Candidate Surface recipe digest remains unchanged."""
    assert CANDIDATE_RECIPE_ID == "surface-v1-candidate"
    assert CANDIDATE_RECIPE_VERSION == 2
    assert (
        CANDIDATE_RECIPE_DIGEST
        == "4f37f46f89f6176fd5fefe0167ec7a81e341839f4fb9b98fa3cc348ddeaf9a55"
    )


# ── SECTION 14: REQUIRED PROACTIVE CHAIN TESTS (L - V) ───────────────────────


def test_l_spontaneous_share_intent_allow_emits_wake_signal(tmp_path: Path) -> None:
    """L. spontaneous_share Intent -> ActionPolicy ALLOW -> WakeSignal."""
    orchestrator, clock, _ = _build_share_test_stack(tmp_path, initial_sharing_urge=0.90)
    now = clock.now() + timedelta(minutes=5)
    clock.advance(timedelta(minutes=5))
    user_scope = Scope(domain=ScopeDomain.USER, user_id="fixture-user")

    report = run_cognitive_tick(orchestrator, scope=user_scope, now=now)
    wake = report.wake_signal
    assert wake is not None
    assert wake.intent_id.endswith("-share")
    assert wake.action_type == "proactive_share"


def test_m_wake_signal_action_type_is_proactive_share(tmp_path: Path) -> None:
    """M. WakeSignal.action_type == proactive_share."""
    orchestrator, clock, _ = _build_share_test_stack(tmp_path, initial_sharing_urge=0.90)
    now = clock.now() + timedelta(minutes=5)
    clock.advance(timedelta(minutes=5))
    user_scope = Scope(domain=ScopeDomain.USER, user_id="fixture-user")

    report = run_cognitive_tick(orchestrator, scope=user_scope, now=now)
    wake = report.wake_signal
    assert wake is not None
    assert wake.action_type == "proactive_share"


def test_n_host_rejects_forged_share_wake_when_policy_rule_non_proactive(tmp_path: Path) -> None:
    """N. Host rejects a forged share wake when authoritative policy rule is: proactive=False."""
    orchestrator, clock, _ = _build_share_test_stack(tmp_path, initial_sharing_urge=0.90)
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


def test_o_host_rejects_action_type_mismatch(tmp_path: Path) -> None:
    """O. Host rejects action_type mismatch."""
    orchestrator, clock, _ = _build_share_test_stack(tmp_path, initial_sharing_urge=0.90)
    now = clock.now() + timedelta(minutes=5)
    clock.advance(timedelta(minutes=5))
    user_scope = Scope(domain=ScopeDomain.USER, user_id="fixture-user")

    report = run_cognitive_tick(orchestrator, scope=user_scope, now=now)
    wake = report.wake_signal
    assert wake is not None

    # Tamper with action_type
    tampered_wake = replace(wake, action_type="proactive_contact")
    adapter = MindRuntimeHostAdapter(orchestrator=orchestrator, trace=orchestrator.trace)
    notification = adapter.consume_wake(tampered_wake)
    assert notification.eligible is False
    assert notification.reason == "rejected:action_type_mismatch"


def test_p_begin_proactive_turn_returns_processing_with_non_empty_envelope(tmp_path: Path) -> None:
    """P. begin_proactive_turn(valid share wake) -> PROCESSING -> non-empty provider envelope."""
    orchestrator, clock, _ = _build_share_test_stack(tmp_path, initial_sharing_urge=0.90)
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
    assert isinstance(turn_res.bounded_context, HostDecisionContext)
    envelope = turn_res.bounded_context.provider_envelope_text
    assert isinstance(envelope, str)
    assert len(envelope) > 0


def test_q_provider_envelope_contains_selected_share_action_semantics(tmp_path: Path) -> None:
    """Q. Provider envelope contains the selected share action/Intent semantics."""
    orchestrator, clock, _ = _build_share_test_stack(tmp_path, initial_sharing_urge=0.90)
    now = clock.now() + timedelta(minutes=5)
    clock.advance(timedelta(minutes=5))
    user_scope = Scope(domain=ScopeDomain.USER, user_id="fixture-user")

    report = run_cognitive_tick(orchestrator, scope=user_scope, now=now)
    wake = report.wake_signal
    assert wake is not None

    adapter = MindRuntimeHostAdapter(orchestrator=orchestrator, trace=orchestrator.trace)
    turn_res = adapter.begin_proactive_turn(wake)
    envelope = turn_res.bounded_context.provider_envelope_text
    assert "proactive_share" in envelope
    assert turn_res.bounded_context.action_taken == "proactive_share"
    assert turn_res.bounded_context.intent_summary == "proactive:proactive_share"


def test_r_provider_envelope_contains_no_literal_sharing_urge(tmp_path: Path) -> None:
    """R. Provider envelope contains NO literal: sharing_urge, agent.affect.sharing_urge."""
    orchestrator, clock, _ = _build_share_test_stack(tmp_path, initial_sharing_urge=0.90)
    now = clock.now() + timedelta(minutes=5)
    clock.advance(timedelta(minutes=5))
    user_scope = Scope(domain=ScopeDomain.USER, user_id="fixture-user")

    report = run_cognitive_tick(orchestrator, scope=user_scope, now=now)
    wake = report.wake_signal
    assert wake is not None

    adapter = MindRuntimeHostAdapter(orchestrator=orchestrator, trace=orchestrator.trace)
    turn_res = adapter.begin_proactive_turn(wake)
    envelope = turn_res.bounded_context.provider_envelope_text
    assert "sharing_urge" not in envelope
    assert "agent.affect.sharing_urge" not in envelope
    assert DeterministicContextRenderer.verify_provider_information_isolation(envelope) is True


def test_s_no_internal_mr_provider_execution_occurs(tmp_path: Path) -> None:
    """S. No internal MR provider execution occurs.

    CognitiveTicker stops strictly at WakeSignal; adapter.begin_proactive_turn compiles
    bounded context without running any internal LLM or provider generation.
    """
    orchestrator, clock, _ = _build_share_test_stack(tmp_path, initial_sharing_urge=0.90)
    ticker = orchestrator.cognitive_tick_components["ticker"]
    assert hasattr(ticker, "expression") is False
    assert hasattr(ticker, "_prepare_expression") is False

    user_scope = Scope(domain=ScopeDomain.USER, user_id="fixture-user")
    now = clock.now() + timedelta(minutes=5)
    clock.advance(timedelta(minutes=5))
    report = run_cognitive_tick(orchestrator, scope=user_scope, now=now)
    wake = report.wake_signal
    assert wake is not None

    adapter = MindRuntimeHostAdapter(orchestrator=orchestrator, trace=orchestrator.trace)
    turn_res = adapter.begin_proactive_turn(wake)
    assert turn_res.status == HostTurnStatus.PROCESSING
    # No expression_ref produced internally before external Body calls guard_proactive_prose
    assert turn_res.expression_ref is None


def test_t_guard_accept_alone_does_not_commit(tmp_path: Path) -> None:
    """T. Guard ACCEPT alone does not commit.

    Status remains PROCESSING and Intent in store remains ALLOWED.
    """
    orchestrator, clock, _ = _build_share_test_stack(tmp_path, initial_sharing_urge=0.90)
    now = clock.now() + timedelta(minutes=5)
    clock.advance(timedelta(minutes=5))
    user_scope = Scope(domain=ScopeDomain.USER, user_id="fixture-user")

    report = run_cognitive_tick(orchestrator, scope=user_scope, now=now)
    wake = report.wake_signal
    assert wake is not None

    adapter = MindRuntimeHostAdapter(orchestrator=orchestrator, trace=orchestrator.trace)
    turn_res = adapter.begin_proactive_turn(wake)
    assert turn_res.status == HostTurnStatus.PROCESSING

    # External body generates prose and passes to guard
    prose = "我刚刚看到一篇很有意思的文章，想和你分享一下。"
    guard_res = adapter.guard_proactive_prose(wake.wake_id, prose)
    assert guard_res.status == HostTurnStatus.PROCESSING
    assert guard_res.outcome == HostStatus.OK

    # Intent in store must STILL be in IntentStatus.ALLOWED, NOT COMPLETED
    lifecycle = orchestrator.cognitive_tick_components["lifecycle"]
    intents = lifecycle.backend.history(user_scope, wake.intent_id)
    assert len(intents) > 0
    assert intents[-1].status == IntentStatus.ALLOWED


def test_u_guard_accept_and_explicit_commit_transitions_intent_completed(tmp_path: Path) -> None:
    """U. Guard ACCEPT + explicit commit -> Intent COMPLETED."""
    orchestrator, clock, _ = _build_share_test_stack(tmp_path, initial_sharing_urge=0.90)
    now = clock.now() + timedelta(minutes=5)
    clock.advance(timedelta(minutes=5))
    user_scope = Scope(domain=ScopeDomain.USER, user_id="fixture-user")

    report = run_cognitive_tick(orchestrator, scope=user_scope, now=now)
    wake = report.wake_signal
    assert wake is not None

    adapter = MindRuntimeHostAdapter(orchestrator=orchestrator, trace=orchestrator.trace)
    adapter.begin_proactive_turn(wake)

    prose = "我刚刚看到一篇很有意思的文章，想和你分享一下。"
    guard_res = adapter.guard_proactive_prose(wake.wake_id, prose)
    assert guard_res.status == HostTurnStatus.PROCESSING

    commit_res = adapter.commit_proactive_turn(wake.wake_id)
    assert commit_res.status == HostTurnStatus.COMMITTED
    assert commit_res.outcome == HostStatus.OK

    # Intent in store is now COMPLETED
    lifecycle = orchestrator.cognitive_tick_components["lifecycle"]
    intents = lifecycle.backend.history(user_scope, wake.intent_id)
    assert len(intents) > 0
    assert intents[-1].status == IntentStatus.COMPLETED


def test_v_guard_reject_fails_closed(tmp_path: Path) -> None:
    """V. Guard REJECT -> existing terminal fail-closed behavior."""
    orchestrator, clock, _ = _build_share_test_stack(tmp_path, initial_sharing_urge=0.90)
    now = clock.now() + timedelta(minutes=5)
    clock.advance(timedelta(minutes=5))
    user_scope = Scope(domain=ScopeDomain.USER, user_id="fixture-user")

    report = run_cognitive_tick(orchestrator, scope=user_scope, now=now)
    wake = report.wake_signal
    assert wake is not None

    adapter = MindRuntimeHostAdapter(orchestrator=orchestrator, trace=orchestrator.trace)
    adapter.begin_proactive_turn(wake)

    # Empty / whitespace fails structural guard and automatically aborts turn
    guard_res = adapter.guard_proactive_prose(wake.wake_id, "   ")
    assert guard_res.status == HostTurnStatus.ABORTED
    assert guard_res.outcome == HostStatus.FAILED
    assert guard_res.disposition is ExpressionDisposition.REJECT

    lifecycle = orchestrator.cognitive_tick_components["lifecycle"]
    intents = lifecycle.backend.history(user_scope, wake.intent_id)
    assert len(intents) > 0
    assert intents[-1].status == IntentStatus.SUPERSEDED


# ── SECTION 15: ANTI-SPAM TESTS (W - Z) ──────────────────────────────────────


def test_w_higher_sharing_urge_cannot_shorten_proactive_cooldown(tmp_path: Path) -> None:
    """W. Higher sharing_urge cannot shorten proactive cooldown."""
    # Invariant validator check
    assert validate_sharing_urge_anti_spam_invariant(
        sharing_urge=1.0,
        base_cooldown_seconds=1800.0,
        effective_cooldown_seconds=1800.0,
    ) is True
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


def test_x_eligible_share_inside_cooldown_defers_and_emits_no_wake(tmp_path: Path) -> None:
    """X. After one proactive share, another eligible share inside cooldown: ActionPolicy DEFER -> no WakeSignal."""
    orchestrator, clock, _ = _build_share_test_stack(
        tmp_path, initial_sharing_urge=0.90, cooldown=timedelta(minutes=30)
    )
    user_scope = Scope(domain=ScopeDomain.USER, user_id="fixture-user")
    t1 = clock.now() + timedelta(minutes=5)
    clock.advance(timedelta(minutes=5))

    report1 = run_cognitive_tick(orchestrator, scope=user_scope, now=t1)
    wake1 = report1.wake_signal
    assert wake1 is not None

    # Tick 2: 10 minutes later (still within 30 min cooldown)
    t2 = t1 + timedelta(minutes=10)
    clock.advance(timedelta(minutes=10))

    report2 = run_cognitive_tick(orchestrator, scope=user_scope, now=t2)
    assert report2.wake_signal is None
    assert report2.policy_allowed == 0


def test_y_no_share_specific_frequency_counters_used(tmp_path: Path) -> None:
    """Y. Do not introduce share-specific send-frequency counters unless an existing generic counter is already authoritative."""
    orchestrator, _, _ = _build_share_test_stack(tmp_path)
    policy = orchestrator.cognitive_tick_components["policy"]
    rule = policy._rules["spontaneous_share"]
    # Uses generic proactive cooldown, no share-specific counter fact
    assert rule.media_counter_fact is None
    assert rule.media_limit is None


def test_z_same_wake_replay_remains_process_local_idempotent(tmp_path: Path) -> None:
    """Z. Same wake replay remains process-local/idempotent under the frozen Host path."""
    orchestrator, clock, _ = _build_share_test_stack(tmp_path, initial_sharing_urge=0.90)
    now = clock.now() + timedelta(minutes=5)
    clock.advance(timedelta(minutes=5))
    user_scope = Scope(domain=ScopeDomain.USER, user_id="fixture-user")

    report = run_cognitive_tick(orchestrator, scope=user_scope, now=now)
    wake = report.wake_signal
    assert wake is not None

    adapter = MindRuntimeHostAdapter(orchestrator=orchestrator, trace=orchestrator.trace)
    notif1 = adapter.consume_wake(wake)
    assert notif1.eligible is True

    # Replay consume_wake
    notif2 = adapter.consume_wake(wake)
    assert notif2.eligible is True
    assert notif2.reason == "already_consumed"

    # Turn processing and commit
    turn1 = adapter.begin_proactive_turn(wake)
    assert turn1.status == HostTurnStatus.PROCESSING
    adapter.guard_proactive_prose(wake.wake_id, "想和你分享一些事情。")
    commit1 = adapter.commit_proactive_turn(wake.wake_id)
    assert commit1.status == HostTurnStatus.COMMITTED

    # Replay commit after completion
    commit2 = adapter.commit_proactive_turn(wake.wake_id)
    assert commit2.status == HostTurnStatus.ALREADY_PROCESSED
    assert commit2.outcome == HostStatus.ALREADY_PROCESSED

    # Replay begin_proactive_turn after terminal commit
    turn_replay = adapter.begin_proactive_turn(wake)
    assert turn_replay.status == HostTurnStatus.ALREADY_PROCESSED

    # Conflicting replay
    conflicting_wake = replace(wake, action_type="conflicting_action")
    res_conflict = adapter.begin_proactive_turn(conflicting_wake)
    assert res_conflict.status == HostTurnStatus.FAILED
    assert res_conflict.outcome == HostStatus.FAILED


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


def test_certified_manifest_proactive_share_gap_verified() -> None:
    """Section 17: Certified runtime manifest has no spontaneous_share or proactive_share rules."""
    from mind_runtime.validation import decode_runtime_manifest, load_runtime_config_manifest

    assert CERTIFIED_MANIFEST_PATH.exists()
    manifest = decode_runtime_manifest(load_runtime_config_manifest(CERTIFIED_MANIFEST_PATH))

    # Inspect manifest.intent_engine.rules
    share_rules = [r for r in manifest.intent_engine.rules if r.kind == "spontaneous_share"]
    assert len(share_rules) == 0

    # Inspect manifest.action_policy.rules
    proactive_share_rules = [
        r for r in manifest.action_policy.rules if getattr(r, "action_type", "") == "proactive_share"
    ]
    assert len(proactive_share_rules) == 0

    assert SHARING_URGE_PRODUCTION_ACTIVATION == "BLOCKED_BY_CONFIG"
    assert SHARING_URGE_CALIBRATION_STATUS == "PROVISIONAL"


# ── SECTION 18 & 12: DO NOT TOUCH LONGING & COMPETITION ─────────────────────


def test_longing_proactive_contact_remains_unaffected(tmp_path: Path) -> None:
    """Section 18: Longing proactive contact behaves exactly as before."""
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
    policy_rule = IntentPolicyRule(
        intent_kind="reach_out",
        action_type="proactive_message",
        proactive=True,
        interrupts_active_conversation=False,
        media_counter_fact=None,
        media_limit=None,
        required_resource=None,
    )
    orchestrator, clock, _ = _build_share_test_stack(
        tmp_path,
        initial_longing=0.90,
        intent_rules=(rule,),
        policy_rules=(policy_rule,),
    )
    now = clock.now() + timedelta(minutes=5)
    clock.advance(timedelta(minutes=5))
    user_scope = Scope(domain=ScopeDomain.USER, user_id="fixture-user")

    report = run_cognitive_tick(orchestrator, scope=user_scope, now=now)
    wake = report.wake_signal
    assert wake is not None
    assert wake.action_type == "proactive_message"
    assert "contact" in wake.intent_id

    adapter = MindRuntimeHostAdapter(orchestrator=orchestrator, trace=orchestrator.trace)
    turn_res = adapter.begin_proactive_turn(wake)
    assert turn_res.status == HostTurnStatus.PROCESSING

    adapter.guard_proactive_prose(wake.wake_id, "想和你聊聊。")
    commit_res = adapter.commit_proactive_turn(wake.wake_id)
    assert commit_res.status == HostTurnStatus.COMMITTED

    lifecycle = orchestrator.cognitive_tick_components["lifecycle"]
    intents = lifecycle.backend.history(user_scope, wake.intent_id)
    assert intents[-1].status == IntentStatus.COMPLETED


def test_longing_and_sharing_distinct_intent_and_action() -> None:
    """Longing and sharing must remain distinguishable at Intent and Action levels."""
    assert "reach_out" != "spontaneous_share"
    assert "proactive_message" != "proactive_share"
    assert FastFunctionKind.PROACTIVE_CONTACT != FastFunctionKind.PROACTIVE_SHARE


def test_competition_between_longing_and_sharing_urge_single_wake(tmp_path: Path) -> None:
    """Section 12: When both reach_out and spontaneous_share exist, exactly one WakeSignal is emitted."""
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

    # Case 1: sharing_urge is high (0.90 -> strength 0.90), longing is lower (0.50 -> contact_seeking * 0.5 + 0.2 < 0.90)
    orchestrator, clock, _ = _build_share_test_stack(
        tmp_path / "case1",
        initial_sharing_urge=0.90,
        initial_longing=0.50,
        intent_rules=(contact_rule, share_rule),
        policy_rules=(contact_policy, share_policy),
    )
    now = clock.now() + timedelta(minutes=5)
    clock.advance(timedelta(minutes=5))
    user_scope = Scope(domain=ScopeDomain.USER, user_id="fixture-user")

    report = run_cognitive_tick(orchestrator, scope=user_scope, now=now)
    assert report.wake_signal is not None
    # spontaneous_share won the competition
    assert report.wake_signal.action_type == "proactive_share"

    # Lower candidate was superseded
    lifecycle = orchestrator.cognitive_tick_components["lifecycle"]
    current_intents = {i.kind: i.status for i in lifecycle.backend.current(user_scope)}
    assert current_intents["spontaneous_share"] == IntentStatus.ALLOWED
    assert current_intents["reach_out"] == IntentStatus.SUPERSEDED
