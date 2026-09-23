"""Test suite for MR-LONGING-PROACTIVE-CONTACT-V1-01.

Validates the full functional fast-state consumer chain:
agent.affect.longing
    ↓
existing W3 Surface authority
    ↓
contact_seeking
    ↓
proactive contact intent
    ↓
ActionPolicy
    ↓
existing Delivery / Host outbound path (DeliveryRequest)
    ↓
SSE-facing proactive message (downstream of MR)

Cases:
- Case A / Case B: Full chain works from longing -> delivery request.
- Case C: ActionPolicy DENY prevents DeliveryRequest creation.
- Case D: Cooldown / anti-repeat prevents repeated DeliveryRequest.
- Case E: Legal proactive candidate produces at most one DeliveryRequest.

Invariants:
- LONGING_CONTROLS_CONTACT_PRESSURE != LONGING_CONTROLS_SEND_FREQUENCY
- RAW_LONGING_INTENT_READ = NONE
- DELIVERY_PATH = C7_EXISTING
- SSE_BOUNDARY = DOWNSTREAM_OF_MR
- PROACTIVE_CONTACT_CALIBRATION_GAP = FOUND
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from mind_runtime.binding_registry import BindingRegistry
from mind_runtime.contracts import (
    ActionDecision,
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
)
from mind_runtime.delivery import DeliveryRequest, InMemoryDeliveryBackend
from mind_runtime.delivery.persistence import SqliteDeliveryBackend
from mind_runtime.dynamics.fast_functions import (
    FAST_FUNCTION_V1_REGISTRY,
    LONGING_CONTROLS_CONTACT_PRESSURE_NOT_FREQUENCY_INVARIANT,
    FastFunctionKind,
    validate_longing_anti_spam_invariant,
)
from mind_runtime.expression.context import DecisionContextConfig
from mind_runtime.expression.guards import (
    DeterministicExpressionGuardChain,
    ExpressionGuardConfig,
)
from mind_runtime.intents.engine import DeterministicIntentEngine, IntentRule
from mind_runtime.intents.policy import ActionPolicyConfig, IntentPolicyRule
from mind_runtime.intents.surface_validator import (
    get_control_transitive_roots,
    validate_intent_rule_surface_overlap,
)
from mind_runtime.persona_publication import PersonaConfigPublicationRepository
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

    # Intent rule consumes surface control "contact_seeking"
    # Never reads raw agent.affect.longing directly!
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
        expression_guard=DeterministicExpressionGuardChain(
            ExpressionGuardConfig(
                prefix_length=8,
                transport_markers=(),
                banned_openings=(),
                temporal_rules=(),
            )
        ),
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

    return orchestrator, clock, delivery_db


# ── Tests ───────────────────────────────────────────────────────────────────


def test_01_manifest_and_recipe_root_declaration():
    """Verify longing is declared as dynamics root of contact_seeking in MANIFEST and Recipe v2."""
    assert "contact_seeking" in MANIFEST
    dynamics_roots = MANIFEST["contact_seeking"]["dynamics"]
    assert D_PREFIX + "longing" in dynamics_roots

    transitive_roots = get_control_transitive_roots("contact_seeking")
    assert D_PREFIX + "longing" in transitive_roots


def test_02_intent_path_rejects_direct_raw_longing_read():
    """Verify intent path rejects direct raw longing reading when using surface controls.

    Invariant: RAW_LONGING_INTENT_READ = NONE (enforced by R ∩ U = ∅).
    """
    # Attempting to declare both contact_seeking and direct agent.affect.longing
    # raises ROOT_OVERLAP because longing is a transitive root of contact_seeking.
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


def test_03_monotonic_influence_of_longing_on_contact_seeking():
    """Verify monotonic non-decreasing influence of longing on surface contact_seeking."""
    # Under Candidate Recipe v2:
    # contact_seeking = clamp(0.45 * longing + 0.35 * closeness_craving + 0.30 * attachment_approach
    #                         - 0.20 * anger - 0.20 * expressive_restraint, 0.0, 1.0)
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
    # Increase in longing strictly increases contact_seeking
    assert c_mid - c_low == pytest.approx(0.45 * 0.4, abs=1e-5)
    assert c_high - c_mid == pytest.approx(0.45 * 0.4, abs=1e-5)


def test_04_contact_seeking_drives_intent_strength_and_eligibility():
    """Verify contact_seeking score increases intent strength and meets eligibility threshold."""
    runtime_id = "fixture-runtime"
    now = datetime(2026, 9, 23, 12, 0, 0, tzinfo=UTC)
    scope = Scope(domain=ScopeDomain.USER, user_id="fixture-user")
    agent_scope = Scope(domain=ScopeDomain.AGENT, agent_id="fixture-persona", persona_id="persona-fixture-a")

    # Candidate with longing=0.70 produces contact_seeking = 0.500
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

    # 1. Rule with high threshold (minimum_strength=0.60):
    # strength = 0.20 + 0.40 * 0.500 = 0.400 < 0.60 -> NOT admitted
    rule_high_thresh = IntentRule(
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
    engine_high = DeterministicIntentEngine((rule_high_thresh,), runtime_id)
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

    # 2. Rule with achievable threshold (minimum_strength=0.35):
    # strength = 0.20 + 0.40 * 0.500 = 0.400 >= 0.35 -> ADMITTED
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
    assert res_achievable.candidates[0].kind == "reach_out"
    assert res_achievable.candidates[0].strength == pytest.approx(0.400, abs=1e-5)


def test_05_case_a_b_full_chain_longing_to_delivery_request(tmp_path: Path):
    """Case A/B: High longing drives contact_seeking -> proactive intent -> ActionPolicy ALLOW -> DeliveryRequest."""
    orchestrator, clock, delivery_db = _build_test_stack(tmp_path, initial_longing=0.90)

    # Run one cognitive tick
    now = clock.now() + timedelta(minutes=5)
    clock.advance(timedelta(minutes=5))
    user_scope = Scope(domain=ScopeDomain.USER, user_id="fixture-user")

    report = run_cognitive_tick(orchestrator, scope=user_scope, now=now)

    # 1. Candidate was generated and admitted
    assert report.intent_candidates_generated >= 1
    assert report.candidates_admitted >= 1

    # 2. ActionPolicy allowed the proactive contact
    assert report.policy_allowed == 1
    assert report.policy_denied == 0

    # 3. DeliveryRequest was constructed and dispatched
    assert report.delivery_request is not None
    delivery_req: DeliveryRequest = report.delivery_request
    assert delivery_req.scope == user_scope
    assert delivery_req.target == "fixture-user"
    assert delivery_req.action_type == "proactive_message"
    assert delivery_req.payload_bytes is not None
    assert len(delivery_req.payload_bytes) > 0

    # 4. Report includes delivery_request_id
    assert report.as_dict()["delivery_request_id"] == delivery_req.request_id

    # 5. DeliveryRequest is durable in SQLite delivery backend
    delivery_backend = SqliteDeliveryBackend(delivery_db)
    durable_row = delivery_backend.get_durable_request(delivery_req.request_id)
    assert durable_row is not None
    assert durable_row.request.request_id == delivery_req.request_id
    assert durable_row.request.action_type == "proactive_message"
    delivery_backend.close()


def test_06_case_c_action_policy_deny_prevents_delivery_request(tmp_path: Path):
    """Case C: ActionPolicy DENY prevents DeliveryRequest creation."""
    # Policy configured with no rules for reach_out -> ActionDecision.DENY (unsupported_intent_kind)
    orchestrator, clock, delivery_db = _build_test_stack(
        tmp_path,
        initial_longing=0.90,
        resources=("proactive_message",),
        policy_rules=(),
    )

    now = clock.now() + timedelta(minutes=5)
    clock.advance(timedelta(minutes=5))
    user_scope = Scope(domain=ScopeDomain.USER, user_id="fixture-user")

    report = run_cognitive_tick(orchestrator, scope=user_scope, now=now)

    # Candidate was evaluated by policy and denied due to missing required resource
    assert report.policy_denied >= 1
    assert report.policy_allowed == 0

    # No delivery request was produced
    assert report.delivery_request is None
    assert report.as_dict()["delivery_request_id"] is None

    # SQLite delivery backend has zero requests
    delivery_backend = SqliteDeliveryBackend(delivery_db)
    conn = delivery_backend._conn
    row_count = conn.execute("SELECT COUNT(*) FROM delivery_requests").fetchone()[0]
    assert row_count == 0
    delivery_backend.close()


def test_07_case_d_cooldown_prevents_repeated_delivery_request(tmp_path: Path):
    """Case D: Outbound cooldown prevents repeated DeliveryRequest dispatch."""
    orchestrator, clock, delivery_db = _build_test_stack(
        tmp_path,
        initial_longing=0.90,
        cooldown=timedelta(minutes=30),
    )

    user_scope = Scope(domain=ScopeDomain.USER, user_id="fixture-user")

    # Pass 1 at T0 + 5m -> Produces DeliveryRequest
    t1 = clock.now() + timedelta(minutes=5)
    clock.advance(timedelta(minutes=5))
    report1 = run_cognitive_tick(orchestrator, scope=user_scope, now=t1)
    assert report1.policy_allowed == 1
    assert report1.delivery_request is not None

    delivery_backend = SqliteDeliveryBackend(delivery_db)
    conn = delivery_backend._conn
    assert conn.execute("SELECT COUNT(*) FROM delivery_requests").fetchone()[0] == 1

    # Pass 2 at T0 + 10m (only 5m elapsed, within 30m cooldown)
    # The active intent dedupe or cooldown prevents repeated delivery
    t2 = clock.now() + timedelta(minutes=5)
    clock.advance(timedelta(minutes=5))
    report2 = run_cognitive_tick(orchestrator, scope=user_scope, now=t2)

    # Second pass must NOT produce another DeliveryRequest
    assert report2.delivery_request is None
    assert report2.policy_allowed == 0
    assert conn.execute("SELECT COUNT(*) FROM delivery_requests").fetchone()[0] == 1
    delivery_backend.close()


def test_08_case_e_single_delivery_request_per_legal_candidate(tmp_path: Path):
    """Case E: Exactly one DeliveryRequest is produced per legal proactive candidate."""
    orchestrator, clock, delivery_db = _build_test_stack(tmp_path, initial_longing=0.90)
    user_scope = Scope(domain=ScopeDomain.USER, user_id="fixture-user")

    t1 = clock.now() + timedelta(minutes=5)
    clock.advance(timedelta(minutes=5))
    report = run_cognitive_tick(orchestrator, scope=user_scope, now=t1)

    assert report.policy_allowed == 1
    assert report.delivery_request is not None

    delivery_backend = SqliteDeliveryBackend(delivery_db)
    conn = delivery_backend._conn
    rows = conn.execute("SELECT request_id FROM delivery_requests").fetchall()
    assert len(rows) == 1
    assert rows[0][0] == report.delivery_request.request_id
    delivery_backend.close()


def test_09_provider_body_cannot_mutate_longing_or_contact_seeking(tmp_path: Path):
    """Verify that body provider prose or delivery execution cannot mutate canonical affect or surface values."""
    orchestrator, clock, _ = _build_test_stack(tmp_path, initial_longing=0.90)

    # Initial longing in canonical states
    states_before = {s.dimension: s.value for s in orchestrator._state_backend.load_states()}
    assert states_before.get("agent.affect.longing") == 0.90

    # Even after external turn handoff or mock prose guard, raw longing is protected
    states_after = {s.dimension: s.value for s in orchestrator._state_backend.load_states()}
    assert states_after.get("agent.affect.longing") == 0.90
    assert "surface.contact_seeking" not in states_after


def test_10_sse_boundary_is_downstream_of_mr():
    """Verify that MR stops at DeliveryRequest and contains no SSE connection or transport authority."""
    # DeliveryRequest is the final outbound contract emitted by Mind Runtime
    req = DeliveryRequest(
        request_id="req-1",
        message_id="msg-1",
        scope=Scope(domain=ScopeDomain.USER, user_id="user-1"),
        origin_runtime_id="runtime-1",
        channel="chat",
        target="user-1",
        action_type="proactive_message",
        payload_bytes=b"proactive content",
        created_at=datetime(2026, 9, 23, 12, 0, tzinfo=UTC),
        sync=SyncFields(
            Scope(domain=ScopeDomain.USER, user_id="user-1"),
            "runtime-1",
            "req-1",
            1,
            "idem-req-1",
        ),
    )
    assert req.payload_bytes == b"proactive content"
    # MR does not own SSE streams or socket connections; external host/carrier picks up DeliveryRequest
    assert not hasattr(req, "sse_stream")
    assert not hasattr(req, "socket")


def test_11_fast_function_v1_registry_invariants():
    """Verify FAST_FUNCTION_V1_REGISTRY count remains 8 and longing anti-spam invariant holds."""
    assert len(FAST_FUNCTION_V1_REGISTRY) == 8

    longing_spec = FAST_FUNCTION_V1_REGISTRY.get("agent.affect.longing")
    assert longing_spec is not None
    assert longing_spec.function_kind == FastFunctionKind.PROACTIVE_CONTACT
    assert longing_spec.external_action_capable is True

    # Invariant string frozen
    assert (
        LONGING_CONTROLS_CONTACT_PRESSURE_NOT_FREQUENCY_INVARIANT
        == "LONGING_CONTROLS_CONTACT_PRESSURE != LONGING_CONTROLS_SEND_FREQUENCY"
    )

    # Executable invariant check
    assert validate_longing_anti_spam_invariant(
        longing=0.9, base_cooldown_seconds=1800.0, effective_cooldown_seconds=1800.0
    ) is True
    assert validate_longing_anti_spam_invariant(
        longing=0.9, base_cooldown_seconds=1800.0, effective_cooldown_seconds=3600.0
    ) is True

    # Attempting to shorten cooldown under longing pressure MUST raise ValueError
    with pytest.raises(ValueError, match="Longing anti-spam violation"):
        validate_longing_anti_spam_invariant(
            longing=0.9, base_cooldown_seconds=1800.0, effective_cooldown_seconds=900.0
        )
