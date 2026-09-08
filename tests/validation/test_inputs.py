"""Executable, typed D11S input-fixture contracts."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from typing import Any, cast

import pytest

import mind_runtime.validation.contracts as subject
from mind_runtime.contracts import (
    AuthorityLevel,
    DeliveryStatus,
    Evidence,
    HistoricalContextBundle,
    Intent,
    IntentStatus,
    Interaction,
    Observation,
    ReconsiderationPolicy,
    RuntimeState,
    Scope,
    ScopeDomain,
    StateDomain,
    StateTransition,
    StateValueType,
    TurnCheckpoint,
)
from mind_runtime.dynamics.kayla_v0 import kayla_v0_profile
from mind_runtime.emotional_transition.effects import EventEffectRule
from mind_runtime.expression.context import DecisionContextConfig
from mind_runtime.expression.coordinator import ExpressionCoordinatorConfig
from mind_runtime.expression.guards import ExpressionGuardConfig
from mind_runtime.intents.policy import ActionPolicyConfig

ROOT = Path(__file__).parents[2]
INPUTS = ROOT / "certification/d11s/inputs"

REQUIRED_EVENT_PATHS = {
    "neutral_noop",
    "positive_typed_event",
    "negative_typed_event",
    "idempotent_replay",
    "false_history",
    "authoritative_correction",
    "return_to_baseline",
    "near_upper_bound",
    "near_lower_bound",
    "intent_due",
    "intent_expired",
    "intent_reconsidered",
    "restart_checkpoint",
}


def test_runtime_manifest_decodes_named_executable_fixture() -> None:
    manifest = subject.load_runtime_config_manifest(INPUTS / "runtime-config.json")
    decoded = subject.decode_runtime_manifest(manifest)

    assert isinstance(decoded, subject.DecodedRuntimeConfig)
    assert manifest.manifest_version == "d11s-kayla-v0-g6-g14-g24-v1"
    registry = decoded.state_definitions
    assert tuple(definition.key for definition in registry.all()) == (
        "agent.affect.longing",
        "agent.affect.irritation",
        "agent.affect.anxiety",
        "agent.affect.excitement",
        "agent.longitudinal.relationship_security",
    )
    assert all(
        definition.domain is StateDomain.AGENT
        and definition.value_type is StateValueType.SCALAR
        and definition.bounds == (0.0, 1.0)
        for definition in registry.all()
    )
    assert decoded.persona_profile == kayla_v0_profile()

    effects = decoded.emotional_effects
    assert isinstance(effects, tuple) and len(effects) == 4
    assert (
        EventEffectRule(
            event_kind="plan_cancelled",
            dimension="agent.affect.anxiety",
            base_amount=0.2,
            history_amount_per_match=0.03,
            history_amount_cap=0.05,
            minimum_history_confidence=0.5,
            longitudinal_target_dimension="agent.longitudinal.relationship_security",
            longitudinal_proposed_value=0.3,
        )
        in effects
    )

    history = decoded.historical_context
    assert isinstance(history, subject.HistoricalContextConfig)
    assert (history.mode, history.provider_mode, history.budget) == (
        "bounded_read_only",
        "manifest_fixture",
        8,
    )

    intent = decoded.intent_engine
    assert isinstance(intent, subject.IntentEngineConfig)
    assert intent.runtime_id == "runtime-1"
    assert tuple(rule.kind for rule in intent.rules) == ("respond", "scheduled_follow_up")
    assert intent.rules[1].event_kind == "follow_up_due"
    assert intent.rules[1].expires_after == timedelta(hours=4)
    assert intent.rules[1].reconsideration_policy is ReconsiderationPolicy.ON_DUE

    policy = decoded.action_policy
    assert isinstance(policy, ActionPolicyConfig)
    assert tuple(rule.intent_kind for rule in policy.rules) == (
        "respond",
        "scheduled_follow_up",
    )
    assert policy.proactive_cooldown == timedelta(minutes=30)
    resources = decoded.policy_resources
    assert resources.available_actions == ("text_message",)

    context = decoded.decision_context
    assert context == DecisionContextConfig((), (), (), (), 1, 32, 160, 16, 2048)
    assert isinstance(decoded.expression_guard, ExpressionGuardConfig)
    assert decoded.expression_guard.prefix_length == 8
    assert decoded.expression_guard.transport_markers == ("【助手】",)
    assert decoded.expression_coordinator == ExpressionCoordinatorConfig(2)

    previous = decoded.previous_expression
    assert isinstance(previous, subject.PreviousExpressionConfig)
    assert previous.mode == "fixed"
    assert previous.expression is not None
    assert previous.expression.delivery_status is DeliveryStatus.SENT
    assert previous.expression.text == "今天真的很想和你聊聊"
    assert previous.expression.origin_runtime_id == "runtime-1"

    assert decoded.fact_ingest == subject.FactIngestConfig(
        backend="sqlite",
        clock="simulation",
        certification_channel="d11s-fixed-clock",
        certification_scope=Scope(ScopeDomain.USER, user_id="user-1"),
    )
    assert decoded.effective_state == subject.EffectiveStateConfig("state_definitions", "sqlite")
    assert decoded.intent_lifecycle == subject.IntentLifecycleConfig("sqlite")
    assert decoded.checkpoint_policy == subject.CheckpointPolicyConfig(timedelta(days=1), "sqlite")
    assert decoded.semantic_provider == subject.SemanticProviderConfig("enabled", 0.75, 0.1)
    assert decoded.receipt_registry == subject.ReceiptRegistryConfig("in_memory")
    assert decoded.slow_plasticity == subject.SlowPlasticityConfig(8)
    assert decoded.appraisal_producer_strategy == subject.AppraisalProducerStrategyConfig(
        strategy="model_backed",
        model="model-appraisal-v1",
        endpoint_url="https://api.deepseek.com/v1/chat/completions",
        api_key_env="APPRAISAL_API_KEY",
        timeout_s=15.0,
        allowed_hosts=("api.deepseek.com",),
    )
    assert decoded.homeostasis == subject.HomeostasisConfig(
        salience_floor_fast_apply=0.7,
        salience_floor_slow_accept=0.6,
        confidence_floor_slow=0.8,
    )


def test_fact_ingest_config_rejects_unbound_scope_and_wrong_modes() -> None:
    with pytest.raises(ValueError, match="certification_scope"):
        subject.FactIngestConfig("sqlite", "simulation", "channel", cast(Any, object()))
    with pytest.raises(ValueError, match="sqlite and simulation"):
        subject._fact_ingest(
            {
                "backend": "memory",
                "clock": "simulation",
                "certification_channel": "d11s-fixed-clock",
                "certification_scope": {
                    "domain": "user",
                    "user_id": "user-1",
                    "agent_id": None,
                    "persona_id": None,
                    "relationship_id": None,
                    "world_id": None,
                    "interaction_id": None,
                },
            }
        )


@pytest.mark.parametrize("days", [30, 90])
def test_horizon_fixtures_decode_every_required_typed_category(days: int) -> None:
    template = subject.load_horizon_template(INPUTS / f"horizon-{days}.json")
    assert template == subject.decode_horizon_template_bytes(
        (INPUTS / f"horizon-{days}.json").read_bytes()
    )

    assert template.horizon_days == days
    assert template.persona_version == "kayla_v0"
    assert template.checkpoint_interval == timedelta(days=1)
    assert {event.expected_path for event in template.events} == REQUIRED_EVENT_PATHS
    assert all(isinstance(event.evidence, tuple) for event in template.events)
    assert all(
        isinstance(evidence, Evidence) for event in template.events for evidence in event.evidence
    )
    assert all(
        evidence.origin_runtime_id == "runtime-1"
        for event in template.events
        for evidence in event.evidence
    )
    assert all(
        event.historical_context is None
        or event.historical_context.origin_runtime_id == "runtime-1"
        for event in template.events
    )
    evidence_ids = [evidence.id for event in template.events for evidence in event.evidence]
    assert len(evidence_ids) > len(set(evidence_ids))

    false_history = next(
        event for event in template.events if event.expected_path == "false_history"
    )
    correction = next(
        event for event in template.events if event.expected_path == "authoritative_correction"
    )
    assert isinstance(false_history.historical_context, HistoricalContextBundle)
    assert correction.at_offset > false_history.at_offset
    assert correction.evidence[0].authority_level is AuthorityLevel.VERIFIED
    offsets = tuple(event.at_offset for event in template.events)
    assert max(
        right - left for left, right in zip(offsets, offsets[1:], strict=False)
    ) >= timedelta(days=7)


def test_model_swap_history_and_restart_fixtures_decode_complete_types() -> None:
    left = subject.load_model_swap_fixture(INPUTS / "model-swap-left.json")
    right = subject.load_model_swap_fixture(INPUTS / "model-swap-right.json")
    assert len(left.responses) == len(right.responses) == 1
    assert left.responses != right.responses
    assert all(response.strip() for response in left.responses + right.responses)

    history = subject.load_history_fixture(INPUTS / "history-g27.json")
    assert history.retrieval_count == 3
    assert len(history.bundle.episodes) == 1
    assert len(history.bundle.pattern_summaries) == 1
    item = history.bundle.episodes[0]
    summary = history.bundle.pattern_summaries[0]
    assert summary.matched_refs == (item.item_id,)
    assert summary.match_count == 1
    assert summary.confidence == 1.0
    assert history.bundle.origin_runtime_id == "runtime-1"

    restart = subject.load_restart_fixture(INPUTS / "restart-g12.json")
    assert restart.durable_store_modes == subject.DurableStoreModes(
        "sqlite", "sqlite", "sqlite", "sqlite"
    )
    assert restart.interactions and all(
        isinstance(interaction, Interaction) for interaction in restart.interactions
    )
    assert len(restart.evidence) == 1 and isinstance(restart.evidence[0], Evidence)
    assert isinstance(restart.expected_observation, Observation)
    interaction_ids = {interaction.interaction_id for interaction in restart.interactions}
    evidence_ids = {evidence.id for evidence in restart.evidence}
    assert restart.expected_observation.interaction_id in interaction_ids
    assert set(restart.expected_observation.evidence_refs) <= evidence_ids
    assert restart.checkpoint.interaction_id in interaction_ids
    assert {state.scope.domain for state in restart.states} == {
        ScopeDomain.USER,
        ScopeDomain.AGENT,
        ScopeDomain.RELATIONSHIP,
    }
    assert all(isinstance(state, RuntimeState) for state in restart.states)
    assert all(state.origin_runtime_id == "runtime-1" for state in restart.states)
    assert restart.state_transitions and all(
        isinstance(transition, StateTransition) for transition in restart.state_transitions
    )
    transition_ids = {transition.transition_id for transition in restart.state_transitions}
    assert all(set(state.transition_refs) <= transition_ids for state in restart.states)
    assert tuple(intent.status for intent in restart.intent_history) == (
        IntentStatus.CANDIDATE,
        IntentStatus.DEFERRED,
    )
    assert all(isinstance(intent, Intent) for intent in restart.intent_history)
    assert len(restart.intent_transitions) == 1
    assert isinstance(restart.checkpoint, TurnCheckpoint)
    assert restart.checkpoint.action_id == "action-restart-g12-1"
    assert restart.checkpoint.delivery_status is DeliveryStatus.UNKNOWN
    assert isinstance(restart.historical_context, HistoricalContextBundle)
    origins = (
        tuple(item.origin_runtime_id for item in restart.evidence)
        + (restart.expected_observation.origin_runtime_id,)
        + tuple(item.origin_runtime_id for item in restart.states)
        + tuple(item.origin_runtime_id for item in restart.state_transitions)
        + tuple(item.origin_runtime_id for item in restart.intent_history)
        + tuple(item.origin_runtime_id for item in restart.intent_transitions)
        + (restart.checkpoint.origin_runtime_id, restart.historical_context.origin_runtime_id)
    )
    assert set(origins) == {"runtime-1"}
    assert "memory" not in (INPUTS / "restart-g12.json").read_text(encoding="utf-8").lower()


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (
            lambda raw: raw["expected_observation"].update(
                {"interaction_id": "missing-interaction"}
            ),
            "interaction_id",
        ),
        (
            lambda raw: raw["checkpoint"].update({"interaction_id": "missing-interaction"}),
            "interaction_id",
        ),
        (
            lambda raw: raw["expected_observation"].update({"evidence_refs": ["missing-evidence"]}),
            "evidence_refs",
        ),
        (
            lambda raw: raw["states"][1].update({"transition_refs": ["missing-transition"]}),
            "transition_refs",
        ),
        (
            lambda raw: raw["states"][1].update(
                {"transition_refs": ["restart-g12-relationship-transition-v2"]}
            ),
            "transition_refs",
        ),
    ],
)
def test_restart_fixture_rejects_unresolved_associations(
    mutate: object, message: str, tmp_path: Path
) -> None:
    raw = json.loads((INPUTS / "restart-g12.json").read_text(encoding="utf-8"))
    mutate(raw)  # type: ignore[operator]
    changed = tmp_path / "restart-g12.json"
    changed.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(ValueError, match=message):
        subject.load_restart_fixture(changed)


@pytest.mark.parametrize("collection", ["interactions", "state_transitions"])
def test_restart_fixture_requires_full_public_record_collections(
    collection: str, tmp_path: Path
) -> None:
    raw = json.loads((INPUTS / "restart-g12.json").read_text(encoding="utf-8"))
    raw.pop(collection, None)
    changed = tmp_path / "restart-g12.json"
    changed.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(ValueError, match="schema"):
        subject.load_restart_fixture(changed)


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda raw: raw.update({"interactions": []}), "interaction IDs"),
        (
            lambda raw: raw["interactions"].append(dict(raw["interactions"][0])),
            "interaction IDs",
        ),
        (
            lambda raw: raw["evidence"].append(dict(raw["evidence"][0])),
            "evidence IDs",
        ),
        (lambda raw: raw.update({"state_transitions": []}), "transition IDs"),
        (
            lambda raw: raw["state_transitions"].append(dict(raw["state_transitions"][0])),
            "transition IDs",
        ),
    ],
)
def test_restart_fixture_rejects_empty_or_duplicate_seed_identities(
    mutate: object, message: str, tmp_path: Path
) -> None:
    raw = json.loads((INPUTS / "restart-g12.json").read_text(encoding="utf-8"))
    mutate(raw)  # type: ignore[operator]
    changed = tmp_path / "restart-g12.json"
    changed.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(ValueError, match=message):
        subject.load_restart_fixture(changed)


@pytest.mark.parametrize(
    ("filename", "loader"),
    [
        ("horizon-30.json", subject.load_horizon_template),
        ("model-swap-left.json", subject.load_model_swap_fixture),
        ("history-g27.json", subject.load_history_fixture),
        ("restart-g12.json", subject.load_restart_fixture),
    ],
)
def test_fixture_decoders_reject_unknown_top_level_fields(
    filename: str, loader: object, tmp_path: Path
) -> None:
    raw = json.loads((INPUTS / filename).read_text(encoding="utf-8"))
    raw["unexpected"] = True
    changed = tmp_path / filename
    changed.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(ValueError, match="schema"):
        loader(changed)  # type: ignore[operator]


@pytest.mark.parametrize(
    ("filename", "loader", "mutate"),
    [
        (
            "horizon-30.json",
            subject.load_horizon_template,
            lambda raw: raw["events"][0].update({"unexpected": True}),
        ),
        (
            "model-swap-left.json",
            subject.load_model_swap_fixture,
            lambda raw: raw.update({"responses": [1]}),
        ),
        (
            "history-g27.json",
            subject.load_history_fixture,
            lambda raw: raw["bundle"]["episodes"][0].pop("proposition"),
        ),
        (
            "restart-g12.json",
            subject.load_restart_fixture,
            lambda raw: raw["checkpoint"].update({"unexpected": True}),
        ),
    ],
)
def test_fixture_decoders_reject_nested_schema_drift(
    filename: str, loader: object, mutate: object, tmp_path: Path
) -> None:
    raw = json.loads((INPUTS / filename).read_text(encoding="utf-8"))
    mutate(raw)  # type: ignore[operator]
    changed = tmp_path / filename
    changed.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(ValueError, match="schema|responses"):
        loader(changed)  # type: ignore[operator]


def test_manifest_and_horizon_records_reject_incomplete_runtime_inputs() -> None:
    manifest = subject.load_runtime_config_manifest(INPUTS / "runtime-config.json")
    with pytest.raises(ValueError, match="fixture artifact paths"):
        replace(manifest, fixture_artifacts=manifest.fixture_artifacts[:-1])
    with pytest.raises(ValueError, match="manifest_version"):
        subject.decode_runtime_manifest(replace(manifest, manifest_version="d11s-v2"))

    template = subject.load_horizon_template(INPUTS / "horizon-30.json")
    with pytest.raises(ValueError, match="horizon_days"):
        replace(template, horizon_days=cast(Any, 31))
    with pytest.raises(ValueError, match="unique"):
        replace(template, events=(template.events[0], template.events[0]))
    with pytest.raises(ValueError, match="exceed"):
        replace(
            template,
            events=(replace(template.events[0], at_offset=timedelta(days=31)),),
        )
    with pytest.raises(ValueError, match="checkpoint_interval"):
        replace(template, checkpoint_interval=timedelta(0))


def test_nested_constructor_decoders_reject_wrong_wire_types_and_enums() -> None:
    with pytest.raises(ValueError, match="array"):
        subject._array({}, "value")
    with pytest.raises(ValueError, match="UTC Z"):
        subject._datetime("2026-01-01T00:00:00+00:00", "at")
    with pytest.raises(ValueError, match="UTC Z"):
        subject._datetime("not-a-timeZ", "at")

    scope = {
        "domain": "invalid",
        "user_id": "user-1",
        "agent_id": None,
        "persona_id": None,
        "relationship_id": None,
        "world_id": None,
        "interaction_id": None,
    }
    with pytest.raises(ValueError, match="ScopeDomain"):
        subject._scope(scope, "scope")

    manifest_raw = json.loads((INPUTS / "runtime-config.json").read_text(encoding="utf-8"))
    definition = dict(manifest_raw["components"][0]["payload"]["definitions"][0])
    definition["bounds"] = [0.0]
    with pytest.raises(ValueError, match="two values"):
        subject._state_definition(definition, "definition")
    definition["bounds"] = [0.0, 1.0]
    definition["domain"] = "invalid"
    with pytest.raises(ValueError, match="enum"):
        subject._state_definition(definition, "definition")

    assert subject._pairs([["agent.affect.anxiety", 0.5]], "pairs") == (
        ("agent.affect.anxiety", 0.5),
    )
    with pytest.raises(ValueError, match="pair"):
        subject._pairs([["only-one"]], "pairs")

    intent_rule = dict(manifest_raw["components"][7]["payload"]["rules"][0])
    intent_rule["reconsideration_policy"] = "invalid"
    with pytest.raises(ValueError, match="enum"):
        subject._intent_rule(intent_rule, "intent_rule")

    policy_rule = dict(manifest_raw["components"][9]["payload"]["rules"][0])
    policy_rule["proactive"] = 1
    with pytest.raises(ValueError, match="boolean"):
        subject._policy_rule(policy_rule, "policy_rule")
    policy_rule["proactive"] = True
    policy_rule["media_counter_fact"] = "counter.media"
    policy_rule["media_limit"] = 1
    assert subject._policy_rule(policy_rule, "policy_rule").media_limit == 1

    previous = dict(manifest_raw["components"][15]["payload"]["expression"])
    previous["delivery_status"] = "invalid"
    with pytest.raises(ValueError, match="delivery_status"):
        subject._previous_expression(previous, "previous")

    decision_context = dict(manifest_raw["components"][11]["payload"])
    decision_context["affect_rules"] = ["unexpected"]
    with pytest.raises(ValueError, match="affect_rules"):
        subject._context(decision_context)
    decision_context["affect_rules"] = []
    decision_context["persona_style_constraints"] = [["missing-value"]]
    with pytest.raises(ValueError, match="schema"):
        subject._context(decision_context)

    guard = dict(manifest_raw["components"][13]["payload"])
    guard["temporal_rules"] = ["unexpected"]
    with pytest.raises(ValueError, match="temporal_rules"):
        subject._guard(guard)

    semantic = dict(manifest_raw["components"][17]["payload"])
    semantic["mode"] = "live"
    with pytest.raises(ValueError, match="disabled"):
        subject._semantic(semantic)


def test_typed_fixture_decoders_reject_invalid_nested_identity_and_modes(tmp_path: Path) -> None:
    horizon_raw = json.loads((INPUTS / "horizon-30.json").read_text(encoding="utf-8"))
    evidence = horizon_raw["events"][1]["evidence"][0]
    evidence["authority"]["level"] = "invalid"
    with pytest.raises(ValueError, match="level enum"):
        subject._evidence(evidence, "evidence")
    evidence["authority"]["level"] = "asserted"
    evidence["authority_level"] = "invalid"
    with pytest.raises(ValueError, match="authority_level"):
        subject._evidence(evidence, "evidence")

    restart_raw = json.loads((INPUTS / "restart-g12.json").read_text(encoding="utf-8"))
    interaction = dict(restart_raw["interactions"][0])
    interaction["status"] = "invalid"
    with pytest.raises(ValueError, match="status enum"):
        subject._interaction(interaction, "interaction")
    intent = dict(restart_raw["intent_history"][0])
    intent["status"] = "invalid"
    with pytest.raises(ValueError, match="enum"):
        subject._intent(intent, "intent")
    transition = dict(restart_raw["intent_transitions"][0])
    transition["to_status"] = "invalid"
    with pytest.raises(ValueError, match="status enum"):
        subject._intent_transition(transition, "transition")
    checkpoint = dict(restart_raw["checkpoint"])
    checkpoint["delivery_status"] = "invalid"
    with pytest.raises(ValueError, match="enum"):
        subject._checkpoint_record(checkpoint, "checkpoint")

    invalid_json = tmp_path / "invalid.json"
    with pytest.raises(ValueError, match="valid UTF-8 JSON"):
        subject.decode_horizon_template_bytes(b"\xff")
    with pytest.raises(ValueError, match="valid UTF-8 JSON"):
        subject.load_horizon_template(tmp_path / "missing-horizon.json")
    with pytest.raises(ValueError, match="valid UTF-8 JSON"):
        subject.load_model_swap_fixture(invalid_json)
    invalid_json.write_text("[]", encoding="utf-8")
    with pytest.raises(ValueError, match="schema"):
        subject.load_model_swap_fixture(invalid_json)

    horizon_raw["horizon_days"] = 31
    invalid_json.write_text(json.dumps(horizon_raw), encoding="utf-8")
    with pytest.raises(ValueError, match="horizon_days"):
        subject.load_horizon_template(invalid_json)

    model_raw = json.loads((INPUTS / "model-swap-left.json").read_text(encoding="utf-8"))
    model_raw["responses"].append("second")
    invalid_json.write_text(json.dumps(model_raw), encoding="utf-8")
    with pytest.raises(ValueError, match="exactly one"):
        subject.load_model_swap_fixture(invalid_json)

    history_raw = json.loads((INPUTS / "history-g27.json").read_text(encoding="utf-8"))
    history_raw["retrieval_count"] = 2
    invalid_json.write_text(json.dumps(history_raw), encoding="utf-8")
    with pytest.raises(ValueError, match="exactly three"):
        subject.load_history_fixture(invalid_json)
    history_raw["retrieval_count"] = 3
    history_raw["bundle"]["pattern_summaries"][0]["matched_refs"] = ["missing-item"]
    invalid_json.write_text(json.dumps(history_raw), encoding="utf-8")
    with pytest.raises(ValueError, match="matched_refs"):
        subject.load_history_fixture(invalid_json)

    restart_raw["durable_store_modes"]["facts"] = "memory"
    invalid_json.write_text(json.dumps(restart_raw), encoding="utf-8")
    with pytest.raises(ValueError, match="all be sqlite"):
        subject.load_restart_fixture(invalid_json)
