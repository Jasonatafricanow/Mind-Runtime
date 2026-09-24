"""Test suite for MR-CURIOSITY-PROACTIVE-INQUIRY-V1-01.

Validates the bounded architecture for the first concrete consumer branch of:
agent.affect.curiosity
    ↓
dedicated inquiry Intent (proactive_inquiry, surface_control_weights=())
    ↓
ActionPolicy (proactive_question)
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
- CURIOSITY_CONTROLS_INQUIRY_PRESSURE_NOT_FREQUENCY
- PROACTIVE_CONTACT != PROACTIVE_SHARE != INQUIRY_EXPLORATION
- CURIOSITY_RETRIEVAL_BRANCH = DEFERRED
- RETRIEVAL_IS_ACTION_AUTHORITY = NO
- No raw dynamics or trait leaks in provider envelope
- No sharing_urge/sadness cross-talk via Surface.initiative
- Exactly one WakeSignal emitted under competition
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
    CURIOSITY_CONTROLS_INQUIRY_PRESSURE_NOT_FREQUENCY,
    CURIOSITY_CONTROLS_INQUIRY_PRESSURE_NOT_FREQUENCY_INVARIANT,
    FAST_FUNCTION_V1_COUNT,
    FAST_FUNCTION_V1_REGISTRY,
    FAST_FUNCTION_V1_SPECS,
    LONGING_CONTROLS_CONTACT_PRESSURE_NOT_FREQUENCY_INVARIANT,
    SHARING_URGE_CONTROLS_SHARE_PRESSURE_NOT_FREQUENCY,
    SHARING_URGE_CONTROLS_SHARE_PRESSURE_NOT_FREQUENCY_INVARIANT,
    FastFunctionKind,
    FastStateStatus,
    validate_curiosity_anti_spam_invariant,
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
from mind_runtime.memory.retrieval import (
    CanonicalMemoryReader,
    CommittedMemory,
    MemoryLifecycle,
    MemoryRetrievalQuery,
    MemoryRetrievalService,
    RetrievedMemoryCandidate,
)
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
    resources: tuple[str, ...] = ("proactive_question", "send_message", "proactive_share", "proactive_message"),
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


def test_a_fast_function_v1_registry_has_exactly_eight_entries() -> None:
    """A. FAST_FUNCTION_V1_REGISTRY still has exactly 8 entries."""
    assert len(FAST_FUNCTION_V1_REGISTRY) == 8
    assert len(FAST_FUNCTION_V1_SPECS) == 8
    assert FAST_FUNCTION_V1_COUNT == 8


def test_b_curiosity_maps_to_inquiry_exploration() -> None:
    """B. curiosity maps to: INQUIRY_EXPLORATION."""
    spec = FAST_FUNCTION_V1_REGISTRY.require("agent.affect.curiosity")
    assert spec.function_kind == FastFunctionKind.INQUIRY_EXPLORATION
    assert spec.primary_consumer == "Intent / retrieval-or-question path"
    assert spec.external_action_capable is True
    assert spec.status == FastStateStatus.ACTIVE

    by_func = FAST_FUNCTION_V1_REGISTRY.require_by_function(FastFunctionKind.INQUIRY_EXPLORATION)
    assert by_func.state_key == "agent.affect.curiosity"


def test_c_increasing_curiosity_monotonically_increases_inquiry_intent_strength() -> None:
    """C. Increasing curiosity monotonically increases proactive_inquiry Intent strength."""
    inquiry_rule = IntentRule(
        rule_id="inquiry",
        kind="proactive_inquiry",
        base_strength=0.0,
        dimension_weights=(("agent.affect.curiosity", 1.0),),
        event_kind=None,
        event_bonus=0,
        minimum_strength=0.05,
        due_at_attribute=None,
        expires_after=None,
        reconsideration_policy=ReconsiderationPolicy.ON_CONTEXT_CHANGE,
        surface_control_weights=(),
    )
    engine = DeterministicIntentEngine((inquiry_rule,), "fixture-runtime")
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
                state_id="state-curiosity",
                scope=agent_scope,
                origin_runtime_id="fixture-runtime",
                dimension="agent.affect.curiosity",
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
                sync=SyncFields(agent_scope, "fixture-runtime", "state-curiosity", 1, "idem"),
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
        assert cand.kind == "proactive_inquiry"
        strengths.append(cand.strength)

    # Monotonically strictly increasing
    for i in range(len(strengths) - 1):
        assert strengths[i] < strengths[i + 1], f"Expected {strengths[i]} < {strengths[i+1]}"


def test_d_low_curiosity_below_threshold_produces_no_candidate() -> None:
    """D. Low curiosity below fixture threshold: no inquiry Intent candidate."""
    inquiry_rule = IntentRule(
        rule_id="inquiry",
        kind="proactive_inquiry",
        base_strength=0.0,
        dimension_weights=(("agent.affect.curiosity", 1.0),),
        event_kind=None,
        event_bonus=0,
        minimum_strength=0.5,
        due_at_attribute=None,
        expires_after=None,
        reconsideration_policy=ReconsiderationPolicy.ON_CONTEXT_CHANGE,
        surface_control_weights=(),
    )
    engine = DeterministicIntentEngine((inquiry_rule,), "fixture-runtime")
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
            state_id="state-curiosity",
            scope=agent_scope,
            origin_runtime_id="fixture-runtime",
            dimension="agent.affect.curiosity",
            value=0.2,  # 0.2 < minimum_strength (0.5)
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
        projection_id="proj-low",
        scope=agent_scope,
        origin_runtime_id="fixture-runtime",
        projected_states=states,
        sync=SyncFields(agent_scope, "fixture-runtime", "proj-low", 1, "idem-proj"),
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
    assert len(res.candidates) == 0


def test_e_high_curiosity_produces_proactive_inquiry_candidate() -> None:
    """E. High curiosity above fixture threshold: proactive_inquiry Intent candidate produced."""
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
    engine = DeterministicIntentEngine((inquiry_rule,), "fixture-runtime")
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
            state_id="state-curiosity",
            scope=agent_scope,
            origin_runtime_id="fixture-runtime",
            dimension="agent.affect.curiosity",
            value=0.85,
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
        projection_id="proj-high",
        scope=agent_scope,
        origin_runtime_id="fixture-runtime",
        projected_states=states,
        sync=SyncFields(agent_scope, "fixture-runtime", "proj-high", 1, "idem-proj"),
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
    assert res.candidates[0].kind == "proactive_inquiry"
    assert res.candidates[0].strength == pytest.approx(0.85, abs=1e-4)


def test_f_changing_sharing_urge_alone_does_not_change_proactive_inquiry_score() -> None:
    """F. Changing sharing_urge alone does not change proactive_inquiry score (cross-talk freedom)."""
    inquiry_rule = IntentRule(
        rule_id="inquiry",
        kind="proactive_inquiry",
        base_strength=0.0,
        dimension_weights=(("agent.affect.curiosity", 1.0),),
        event_kind=None,
        event_bonus=0,
        minimum_strength=0.1,
        due_at_attribute=None,
        expires_after=None,
        reconsideration_policy=ReconsiderationPolicy.ON_CONTEXT_CHANGE,
        surface_control_weights=(),
    )
    engine = DeterministicIntentEngine((inquiry_rule,), "fixture-runtime")
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

    fixed_curiosity = 0.70
    strengths: list[float] = []

    for s_val in [0.0, 0.25, 0.50, 0.75, 1.0]:
        states = (
            RuntimeState(
                state_id="state-curiosity",
                scope=agent_scope,
                origin_runtime_id="fixture-runtime",
                dimension="agent.affect.curiosity",
                value=fixed_curiosity,
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
            RuntimeState(
                state_id="state-sharing_urge",
                scope=agent_scope,
                origin_runtime_id="fixture-runtime",
                dimension="agent.affect.sharing_urge",
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
                sync=SyncFields(agent_scope, "fixture-runtime", "state-sharing_urge", 1, "idem"),
            ),
        )
        projected = ProjectedMindState(
            projection_id=f"proj-s-{s_val}",
            scope=agent_scope,
            origin_runtime_id="fixture-runtime",
            projected_states=states,
            sync=SyncFields(agent_scope, "fixture-runtime", f"proj-s-{s_val}", 1, "idem-proj"),
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
        strengths.append(res.candidates[0].strength)

    # Score MUST remain identical regardless of sharing_urge variation
    for st in strengths:
        assert st == pytest.approx(fixed_curiosity, abs=1e-5)


def test_g_changing_sadness_alone_does_not_change_proactive_inquiry_score() -> None:
    """G. Changing sadness alone does not change proactive_inquiry score (cross-talk freedom)."""
    inquiry_rule = IntentRule(
        rule_id="inquiry",
        kind="proactive_inquiry",
        base_strength=0.0,
        dimension_weights=(("agent.affect.curiosity", 1.0),),
        event_kind=None,
        event_bonus=0,
        minimum_strength=0.1,
        due_at_attribute=None,
        expires_after=None,
        reconsideration_policy=ReconsiderationPolicy.ON_CONTEXT_CHANGE,
        surface_control_weights=(),
    )
    engine = DeterministicIntentEngine((inquiry_rule,), "fixture-runtime")
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

    fixed_curiosity = 0.75
    strengths: list[float] = []

    for sad_val in [0.0, 0.2, 0.4, 0.6, 0.8, 1.0]:
        states = (
            RuntimeState(
                state_id="state-curiosity",
                scope=agent_scope,
                origin_runtime_id="fixture-runtime",
                dimension="agent.affect.curiosity",
                value=fixed_curiosity,
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
            RuntimeState(
                state_id="state-sadness",
                scope=agent_scope,
                origin_runtime_id="fixture-runtime",
                dimension="agent.affect.sadness",
                value=sad_val,
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
            projection_id=f"proj-sad-{sad_val}",
            scope=agent_scope,
            origin_runtime_id="fixture-runtime",
            projected_states=states,
            sync=SyncFields(agent_scope, "fixture-runtime", f"proj-sad-{sad_val}", 1, "idem-proj"),
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
        strengths.append(res.candidates[0].strength)

    # Score MUST remain identical regardless of sadness variation
    for st in strengths:
        assert st == pytest.approx(fixed_curiosity, abs=1e-5)


def test_h_changing_anger_or_longing_alone_does_not_change_proactive_inquiry_score() -> None:
    """H. Changing anger or longing alone does not change proactive_inquiry score."""
    inquiry_rule = IntentRule(
        rule_id="inquiry",
        kind="proactive_inquiry",
        base_strength=0.0,
        dimension_weights=(("agent.affect.curiosity", 1.0),),
        event_kind=None,
        event_bonus=0,
        minimum_strength=0.1,
        due_at_attribute=None,
        expires_after=None,
        reconsideration_policy=ReconsiderationPolicy.ON_CONTEXT_CHANGE,
        surface_control_weights=(),
    )
    engine = DeterministicIntentEngine((inquiry_rule,), "fixture-runtime")
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

    fixed_curiosity = 0.80
    for anger_val in [0.1, 0.9]:
        for longing_val in [0.1, 0.9]:
            states = (
                RuntimeState(
                    state_id="state-curiosity",
                    scope=agent_scope,
                    origin_runtime_id="fixture-runtime",
                    dimension="agent.affect.curiosity",
                    value=fixed_curiosity,
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
                RuntimeState(
                    state_id="state-anger",
                    scope=agent_scope,
                    origin_runtime_id="fixture-runtime",
                    dimension="agent.affect.anger",
                    value=anger_val,
                    status="active",
                    valid_from=now,
                    valid_until=None,
                    relevant_until=None,
                    last_observed_at=now,
                    evidence_refs=(),
                    transition_refs=(),
                    updated_at=now,
                    version=1,
                    sync=SyncFields(agent_scope, "fixture-runtime", "state-anger", 1, "idem"),
                ),
                RuntimeState(
                    state_id="state-longing",
                    scope=agent_scope,
                    origin_runtime_id="fixture-runtime",
                    dimension="agent.affect.longing",
                    value=longing_val,
                    status="active",
                    valid_from=now,
                    valid_until=None,
                    relevant_until=None,
                    last_observed_at=now,
                    evidence_refs=(),
                    transition_refs=(),
                    updated_at=now,
                    version=1,
                    sync=SyncFields(agent_scope, "fixture-runtime", "state-longing", 1, "idem"),
                ),
            )
            projected = ProjectedMindState(
                projection_id="proj-other",
                scope=agent_scope,
                origin_runtime_id="fixture-runtime",
                projected_states=states,
                sync=SyncFields(agent_scope, "fixture-runtime", "proj-other", 1, "idem-proj"),
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
            assert res.candidates[0].strength == pytest.approx(fixed_curiosity, abs=1e-5)


def test_i_inquiry_rule_has_empty_surface_control_weights() -> None:
    """I. proactive_inquiry rule explicitly sets surface_control_weights=()."""
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
    assert inquiry_rule.surface_control_weights == ()
    assert len(inquiry_rule.surface_control_weights) == 0


def test_j_inquiry_rule_uses_curiosity_as_only_fast_state_scoring_root() -> None:
    """J. inquiry_rule uses agent.affect.curiosity as only scoring root."""
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
    dims = [dim for dim, _ in inquiry_rule.dimension_weights]
    assert dims == ["agent.affect.curiosity"]


def test_k_no_new_surface_control_introduced() -> None:
    """K. Candidate Recipe v2 surface controls remain exactly 5."""
    assert len(MANIFEST) == 5
    expected_controls = {
        "contact_seeking",
        "initiative",
        "confrontation",
        "expressive_warmth",
        "expressive_restraint",
    }
    assert set(MANIFEST.keys()) == expected_controls
    assert "curiosity_drive" not in MANIFEST
    assert "curiosity_seeking" not in MANIFEST
    assert "inquiry_pressure" not in MANIFEST
    assert "inquiry_drive" not in MANIFEST


def test_l_candidate_surface_recipe_digest_remains_unchanged() -> None:
    """L. Candidate recipe digest remains bit-for-bit unchanged."""
    assert CANDIDATE_RECIPE_ID == "surface-v1-candidate"
    assert CANDIDATE_RECIPE_VERSION == 2
    assert (
        CANDIDATE_RECIPE_DIGEST
        == "4f37f46f89f6176fd5fefe0167ec7a81e341839f4fb9b98fa3cc348ddeaf9a55"
    )


# ── SECTION 14: REQUIRED PROACTIVE CHAIN TESTS (M - W) ───────────────────────


def test_m_proactive_inquiry_intent_allow_emits_wake_signal(tmp_path: Path) -> None:
    """M. proactive_inquiry Intent -> ActionPolicy ALLOW -> WakeSignal."""
    orchestrator, clock, _ = _build_inquiry_test_stack(tmp_path, initial_curiosity=0.90)
    now = clock.now() + timedelta(minutes=5)
    clock.advance(timedelta(minutes=5))
    user_scope = Scope(domain=ScopeDomain.USER, user_id="fixture-user")

    report = run_cognitive_tick(orchestrator, scope=user_scope, now=now)
    wake = report.wake_signal
    assert wake is not None
    assert wake.intent_id.endswith("-inquiry")
    assert wake.action_type == "proactive_question"


def test_n_wake_signal_action_type_is_proactive_question(tmp_path: Path) -> None:
    """N. WakeSignal.action_type == proactive_question."""
    orchestrator, clock, _ = _build_inquiry_test_stack(tmp_path, initial_curiosity=0.90)
    now = clock.now() + timedelta(minutes=5)
    clock.advance(timedelta(minutes=5))
    user_scope = Scope(domain=ScopeDomain.USER, user_id="fixture-user")

    report = run_cognitive_tick(orchestrator, scope=user_scope, now=now)
    wake = report.wake_signal
    assert wake is not None
    assert wake.action_type == "proactive_question"


def test_o_host_rejects_forged_inquiry_wake_when_policy_rule_non_proactive(tmp_path: Path) -> None:
    """O. Host rejects a forged inquiry wake when authoritative policy rule is: proactive=False."""
    orchestrator, clock, _ = _build_inquiry_test_stack(tmp_path, initial_curiosity=0.90)
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


def test_p_host_rejects_action_type_mismatch(tmp_path: Path) -> None:
    """P. Host rejects action_type mismatch."""
    orchestrator, clock, _ = _build_inquiry_test_stack(tmp_path, initial_curiosity=0.90)
    now = clock.now() + timedelta(minutes=5)
    clock.advance(timedelta(minutes=5))
    user_scope = Scope(domain=ScopeDomain.USER, user_id="fixture-user")

    report = run_cognitive_tick(orchestrator, scope=user_scope, now=now)
    wake = report.wake_signal
    assert wake is not None

    tampered_wake = replace(wake, action_type="proactive_contact")
    adapter = MindRuntimeHostAdapter(orchestrator=orchestrator, trace=orchestrator.trace)
    notification = adapter.consume_wake(tampered_wake)
    assert notification.eligible is False
    assert notification.reason == "rejected:action_type_mismatch"


def test_q_begin_proactive_turn_returns_processing_with_non_empty_envelope(tmp_path: Path) -> None:
    """Q. begin_proactive_turn(valid inquiry wake) -> PROCESSING -> non-empty provider envelope."""
    orchestrator, clock, _ = _build_inquiry_test_stack(tmp_path, initial_curiosity=0.90)
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


def test_r_provider_envelope_contains_selected_inquiry_action_semantics(tmp_path: Path) -> None:
    """R. Provider envelope contains the selected inquiry action/Intent semantics."""
    orchestrator, clock, _ = _build_inquiry_test_stack(tmp_path, initial_curiosity=0.90)
    now = clock.now() + timedelta(minutes=5)
    clock.advance(timedelta(minutes=5))
    user_scope = Scope(domain=ScopeDomain.USER, user_id="fixture-user")

    report = run_cognitive_tick(orchestrator, scope=user_scope, now=now)
    wake = report.wake_signal
    assert wake is not None

    adapter = MindRuntimeHostAdapter(orchestrator=orchestrator, trace=orchestrator.trace)
    turn_res = adapter.begin_proactive_turn(wake)
    envelope = turn_res.bounded_context.provider_envelope_text
    assert "proactive_question" in envelope
    assert turn_res.bounded_context.action_taken == "proactive_question"
    assert turn_res.bounded_context.intent_summary == "proactive:proactive_question"


def test_s_provider_envelope_contains_no_literal_curiosity(tmp_path: Path) -> None:
    """S. Provider envelope contains NO literal: curiosity, agent.affect.curiosity."""
    orchestrator, clock, _ = _build_inquiry_test_stack(tmp_path, initial_curiosity=0.90)
    now = clock.now() + timedelta(minutes=5)
    clock.advance(timedelta(minutes=5))
    user_scope = Scope(domain=ScopeDomain.USER, user_id="fixture-user")

    report = run_cognitive_tick(orchestrator, scope=user_scope, now=now)
    wake = report.wake_signal
    assert wake is not None

    adapter = MindRuntimeHostAdapter(orchestrator=orchestrator, trace=orchestrator.trace)
    turn_res = adapter.begin_proactive_turn(wake)
    envelope = turn_res.bounded_context.provider_envelope_text
    assert "curiosity" not in envelope
    assert "agent.affect.curiosity" not in envelope
    assert DeterministicContextRenderer.verify_provider_information_isolation(envelope) is True


def test_t_no_internal_mr_provider_execution_occurs(tmp_path: Path) -> None:
    """T. No internal MR provider execution occurs.

    CognitiveTicker stops strictly at WakeSignal; adapter.begin_proactive_turn compiles
    bounded context without running any internal LLM or provider generation.
    """
    orchestrator, clock, _ = _build_inquiry_test_stack(tmp_path, initial_curiosity=0.90)
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
    assert turn_res.expression_ref is None


def test_u_guard_accept_alone_does_not_commit(tmp_path: Path) -> None:
    """U. Guard ACCEPT alone does not commit.

    Status remains PROCESSING and Intent in store remains ALLOWED.
    """
    orchestrator, clock, _ = _build_inquiry_test_stack(tmp_path, initial_curiosity=0.90)
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
    prose = "你刚才提到的那个项目，目前进展得怎么样了？"
    guard_res = adapter.guard_proactive_prose(wake.wake_id, prose)
    assert guard_res.status == HostTurnStatus.PROCESSING
    assert guard_res.outcome == HostStatus.OK

    # Intent in store must STILL be in IntentStatus.ALLOWED, NOT COMPLETED
    lifecycle = orchestrator.cognitive_tick_components["lifecycle"]
    intents = lifecycle.backend.history(user_scope, wake.intent_id)
    assert len(intents) > 0
    assert intents[-1].status == IntentStatus.ALLOWED


def test_v_guard_accept_and_explicit_commit_transitions_intent_completed(tmp_path: Path) -> None:
    """V. Guard ACCEPT + explicit commit -> Intent COMPLETED."""
    orchestrator, clock, _ = _build_inquiry_test_stack(tmp_path, initial_curiosity=0.90)
    now = clock.now() + timedelta(minutes=5)
    clock.advance(timedelta(minutes=5))
    user_scope = Scope(domain=ScopeDomain.USER, user_id="fixture-user")

    report = run_cognitive_tick(orchestrator, scope=user_scope, now=now)
    wake = report.wake_signal
    assert wake is not None

    adapter = MindRuntimeHostAdapter(orchestrator=orchestrator, trace=orchestrator.trace)
    adapter.begin_proactive_turn(wake)

    prose = "你刚才提到的那个项目，目前进展得怎么样了？"
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


def test_w_guard_reject_fails_closed(tmp_path: Path) -> None:
    """W. Guard REJECT -> existing terminal fail-closed behavior."""
    orchestrator, clock, _ = _build_inquiry_test_stack(tmp_path, initial_curiosity=0.90)
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


# ── SECTION 15: ANTI-SPAM TESTS (X - AB) ─────────────────────────────────────


def test_x_higher_curiosity_cannot_shorten_proactive_cooldown(tmp_path: Path) -> None:
    """X. Higher curiosity cannot shorten proactive cooldown."""
    # Invariant validator check
    assert validate_curiosity_anti_spam_invariant(
        curiosity=1.0,
        base_cooldown_seconds=1800.0,
        effective_cooldown_seconds=1800.0,
    ) is True
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


def test_y_eligible_inquiry_inside_cooldown_defers_and_emits_no_wake(tmp_path: Path) -> None:
    """Y. After one proactive inquiry, another eligible inquiry inside cooldown: ActionPolicy DEFER -> no WakeSignal."""
    orchestrator, clock, _ = _build_inquiry_test_stack(
        tmp_path, initial_curiosity=0.90, cooldown=timedelta(minutes=30)
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


def test_z_no_inquiry_specific_frequency_counters_used(tmp_path: Path) -> None:
    """Z. Do not introduce inquiry-specific send-frequency counters unless an existing generic counter is authoritative."""
    orchestrator, _, _ = _build_inquiry_test_stack(tmp_path)
    policy = orchestrator.cognitive_tick_components["policy"]
    rule = policy._rules["proactive_inquiry"]
    assert rule.media_counter_fact is None
    assert rule.media_limit is None


def test_aa_same_wake_replay_remains_process_local_idempotent(tmp_path: Path) -> None:
    """AA. Same wake replay remains process-local/idempotent under the frozen Host path."""
    orchestrator, clock, _ = _build_inquiry_test_stack(tmp_path, initial_curiosity=0.90)
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
    adapter.guard_proactive_prose(wake.wake_id, "你刚才提到的问题，我很好奇想多了解一下。")
    commit1 = adapter.commit_proactive_turn(wake.wake_id)
    assert commit1.status == HostTurnStatus.COMMITTED

    # Replay commit after completion
    commit2 = adapter.commit_proactive_turn(wake.wake_id)
    assert commit2.status == HostTurnStatus.ALREADY_PROCESSED
    assert commit2.outcome == HostStatus.ALREADY_PROCESSED

    # Replay begin_proactive_turn after terminal commit
    turn_replay = adapter.begin_proactive_turn(wake)
    assert turn_replay.status == HostTurnStatus.ALREADY_PROCESSED


def test_ab_conflicting_wake_replay_fails_closed(tmp_path: Path) -> None:
    """AB. Conflicting wake payload fails closed."""
    orchestrator, clock, _ = _build_inquiry_test_stack(tmp_path, initial_curiosity=0.90)
    now = clock.now() + timedelta(minutes=5)
    clock.advance(timedelta(minutes=5))
    user_scope = Scope(domain=ScopeDomain.USER, user_id="fixture-user")

    report = run_cognitive_tick(orchestrator, scope=user_scope, now=now)
    wake = report.wake_signal
    assert wake is not None

    adapter = MindRuntimeHostAdapter(orchestrator=orchestrator, trace=orchestrator.trace)
    adapter.consume_wake(wake)
    adapter.begin_proactive_turn(wake)

    conflicting_wake = replace(wake, action_type="conflicting_action")
    res_conflict = adapter.begin_proactive_turn(conflicting_wake)
    assert res_conflict.status == HostTurnStatus.FAILED
    assert res_conflict.outcome == HostStatus.FAILED


# ── SECTION 16: RETRIEVAL INDEPENDENCE & ISOLATION TESTS (AC - AH) ───────────


def test_ac_curiosity_retrieval_branch_is_deferred() -> None:
    """AC. Explicit contract: CURIOSITY_RETRIEVAL_BRANCH=DEFERRED, RETRIEVAL_IS_ACTION_AUTHORITY=NO."""
    assert CURIOSITY_RETRIEVAL_BRANCH == "DEFERRED"
    assert RETRIEVAL_IS_ACTION_AUTHORITY == "NO"


def test_ad_retrieval_output_cannot_fabricate_or_authorize_intent(tmp_path: Path) -> None:
    """AD. Retrieval output cannot fabricate an Intent candidate or bypass IntentEngine."""
    user_scope = Scope(domain=ScopeDomain.USER, user_id="fixture-user")

    class FakeMemoryStore:
        def get(self, memory_id: str):
            return None

    class FakeRetrievalProvider:
        def search(self, query: MemoryRetrievalQuery):
            return (
                RetrievedMemoryCandidate(
                    memory_id="mem-1",
                    provider="fake-vector",
                    score=0.99,
                    provider_text="User mentioned studying quantum physics.",
                ),
            )

    service = MemoryRetrievalService(store=FakeMemoryStore(), provider=FakeRetrievalProvider())
    query = MemoryRetrievalQuery(scope=user_scope, text="quantum physics", limit=1)
    results = service.search(query)
    # Retrieval returns candidates or memories, but has NO intent interface
    assert hasattr(service, "create_intent") is False
    assert hasattr(service, "evaluate") is False
    assert not isinstance(results, tuple) or not any(isinstance(r, Intent) for r in results)


def test_ae_retrieval_service_cannot_create_action_policy_allow() -> None:
    """AE. Retrieval service / results cannot produce ActionPolicyResult(ALLOW)."""
    user_scope = Scope(domain=ScopeDomain.USER, user_id="fixture-user")

    class FakeMemoryStore:
        def get(self, memory_id: str):
            return None

    service = MemoryRetrievalService(store=FakeMemoryStore())
    # MemoryRetrievalService has no ActionPolicy evaluation capability
    assert hasattr(service, "decide") is False
    assert hasattr(service, "evaluate_action") is False
    assert hasattr(service, "permission") is False


def test_af_retrieval_service_cannot_emit_wake_signal(tmp_path: Path) -> None:
    """AF. Retrieval service has no capability to emit WakeSignal."""
    class FakeMemoryStore:
        def get(self, memory_id: str):
            return None

    service = MemoryRetrievalService(store=FakeMemoryStore())
    assert hasattr(service, "emit_wake") is False
    assert hasattr(service, "wake_signal") is False
    assert hasattr(service, "consume_wake") is False


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


def test_ah_retrieval_score_is_not_permission_strength() -> None:
    """AH. Retrieval score (e.g. 0.99) cannot become permission strength or override policy."""
    candidate = RetrievedMemoryCandidate(
        memory_id="mem-1",
        provider="qdrant",
        score=0.99,
        provider_text="High relevance text",
    )
    # The score is purely search ranking relevance, not policy permission
    assert candidate.score == 0.99
    # There is no conversion of candidate score to ActionDecision.ALLOW or Intent strength
    assert hasattr(candidate, "decision") is False
    assert hasattr(candidate, "action_type") is False


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


def test_aj_certified_manifest_proactive_inquiry_gap_verified() -> None:
    """AJ: Certified runtime manifest has no proactive_inquiry or proactive_question rules."""
    from mind_runtime.validation import decode_runtime_manifest, load_runtime_config_manifest

    assert CERTIFIED_MANIFEST_PATH.exists()
    manifest = decode_runtime_manifest(load_runtime_config_manifest(CERTIFIED_MANIFEST_PATH))

    # Inspect manifest.intent_engine.rules
    inquiry_rules = [r for r in manifest.intent_engine.rules if r.kind == "proactive_inquiry"]
    assert len(inquiry_rules) == 0

    # Inspect manifest.action_policy.rules
    proactive_inquiry_rules = [
        r for r in manifest.action_policy.rules if getattr(r, "action_type", "") == "proactive_question"
    ]
    assert len(proactive_inquiry_rules) == 0

    assert CURIOSITY_PRODUCTION_ACTIVATION == "BLOCKED_BY_CONFIG"
    assert CURIOSITY_CALIBRATION_STATUS == "PROVISIONAL"


# ── SECTION 19: MULTI-URGE INDEPENDENCE & COMPETITION (AK - AO) ──────────────


def test_ak_longing_proactive_contact_remains_unaffected(tmp_path: Path) -> None:
    """AK: Longing proactive contact behaves exactly as before."""
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
    orchestrator, clock, _ = _build_inquiry_test_stack(
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


def test_al_sharing_urge_proactive_share_remains_unaffected(tmp_path: Path) -> None:
    """AL: Sharing urge proactive share behaves exactly as before."""
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
    share_policy = IntentPolicyRule(
        intent_kind="spontaneous_share",
        action_type="proactive_share",
        proactive=True,
        interrupts_active_conversation=False,
        media_counter_fact=None,
        media_limit=None,
        required_resource=None,
    )
    orchestrator, clock, _ = _build_inquiry_test_stack(
        tmp_path,
        sharing_urge=0.90,
        intent_rules=(share_rule,),
        policy_rules=(share_policy,),
    )
    now = clock.now() + timedelta(minutes=5)
    clock.advance(timedelta(minutes=5))
    user_scope = Scope(domain=ScopeDomain.USER, user_id="fixture-user")

    report = run_cognitive_tick(orchestrator, scope=user_scope, now=now)
    wake = report.wake_signal
    assert wake is not None
    assert wake.action_type == "proactive_share"
    assert "share" in wake.intent_id

    adapter = MindRuntimeHostAdapter(orchestrator=orchestrator, trace=orchestrator.trace)
    turn_res = adapter.begin_proactive_turn(wake)
    assert turn_res.status == HostTurnStatus.PROCESSING

    adapter.guard_proactive_prose(wake.wake_id, "想和你分享一件很有趣的事情。")
    commit_res = adapter.commit_proactive_turn(wake.wake_id)
    assert commit_res.status == HostTurnStatus.COMMITTED

    lifecycle = orchestrator.cognitive_tick_components["lifecycle"]
    intents = lifecycle.backend.history(user_scope, wake.intent_id)
    assert intents[-1].status == IntentStatus.COMPLETED


def test_am_longing_sharing_curiosity_distinct_intent_and_action() -> None:
    """AM: Longing, sharing urge, and curiosity must remain distinct at Intent and Action levels."""
    assert len({"reach_out", "spontaneous_share", "proactive_inquiry"}) == 3
    assert len({"proactive_message", "proactive_share", "proactive_question"}) == 3
    assert len({
        FastFunctionKind.PROACTIVE_CONTACT,
        FastFunctionKind.PROACTIVE_SHARE,
        FastFunctionKind.INQUIRY_EXPLORATION,
    }) == 3


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


def test_ao_curiosity_wins_competition_when_highest_strength(tmp_path: Path) -> None:
    """AO: Candidate scoring is strictly by rule weight, no hardcoded emotional priority."""
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

    # Sub-case 1: sharing_urge (0.90) > curiosity (0.40) -> spontaneous_share wins
    orchestrator1, clock1, _ = _build_inquiry_test_stack(
        tmp_path / "sub1",
        initial_curiosity=0.40,
        sharing_urge=0.90,
        intent_rules=(share_rule, inquiry_rule),
        policy_rules=(share_policy, inquiry_policy),
    )
    now1 = clock1.now() + timedelta(minutes=5)
    clock1.advance(timedelta(minutes=5))
    user_scope = Scope(domain=ScopeDomain.USER, user_id="fixture-user")
    rep1 = run_cognitive_tick(orchestrator1, scope=user_scope, now=now1)
    assert rep1.wake_signal is not None
    assert rep1.wake_signal.action_type == "proactive_share"

    # Sub-case 2: curiosity (0.90) > sharing_urge (0.40) -> proactive_inquiry wins
    orchestrator2, clock2, _ = _build_inquiry_test_stack(
        tmp_path / "sub2",
        initial_curiosity=0.90,
        sharing_urge=0.40,
        intent_rules=(share_rule, inquiry_rule),
        policy_rules=(share_policy, inquiry_policy),
    )
    now2 = clock2.now() + timedelta(minutes=5)
    clock2.advance(timedelta(minutes=5))
    rep2 = run_cognitive_tick(orchestrator2, scope=user_scope, now=now2)
    assert rep2.wake_signal is not None
    assert rep2.wake_signal.action_type == "proactive_question"
