"""Frozen, typed D11S certification records and closed config decoders."""

# ruff: noqa: E501

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from math import isfinite
from pathlib import Path, PurePosixPath
from typing import Literal, cast

from mind_runtime.contracts import (
    AffectiveDimensionProfile,
    Authority,
    AuthorityLevel,
    DeliveryStatus,
    Evidence,
    HistoricalContextBundle,
    HistoricalContextItem,
    Intent,
    IntentStatus,
    IntentTransition,
    Interaction,
    InteractionStatus,
    Observation,
    PatternMatchSummary,
    PolicyResources,
    PreviousExpression,
    ReconsiderationPolicy,
    RuntimeState,
    Scope,
    ScopeDomain,
    StateDefinition,
    StateDomain,
    StateTransition,
    StateValueType,
    SyncFields,
    TurnCheckpoint,
    TurnStage,
)
from mind_runtime.contracts.common import freeze_mapping, require_aware_utc, require_non_empty
from mind_runtime.dynamics.persona import PersonaProfile
from mind_runtime.emotional_transition.effects import EventEffectRule
from mind_runtime.expression.context import DecisionContextConfig
from mind_runtime.expression.coordinator import ExpressionCoordinatorConfig
from mind_runtime.expression.guards import ExpressionGuardConfig
from mind_runtime.intents.engine import IntentRule
from mind_runtime.intents.policy import ActionPolicyConfig, IntentPolicyRule
from mind_runtime.situation.builder import SituationBuilder
from mind_runtime.state.definitions import StateDefinitionRegistry

_HASH_LENGTH = 64
_GIT_SHA_LENGTH = 40

REQUIRED_COMPONENT_IDS = frozenset(
    {
        "state_definitions",
        "persona_profile",
        "fact_ingest",
        "effective_state",
        "situation",
        "emotional_effects",
        "historical_context",
        "intent_engine",
        "intent_lifecycle",
        "action_policy",
        "policy_resources",
        "decision_context",
        "context_renderer",
        "expression_guard",
        "expression_coordinator",
        "previous_expression",
        "checkpoint_policy",
        "semantic_provider",
        "receipt_registry",
        "slow_plasticity",
        "appraisal_producer_strategy",
        "homeostasis",
    }
)

REQUIRED_FIXTURE_PATHS = frozenset(
    {
        "certification/d11s/inputs/horizon-30.json",
        "certification/d11s/inputs/horizon-90.json",
        "certification/d11s/inputs/model-swap-left.json",
        "certification/d11s/inputs/model-swap-right.json",
        "certification/d11s/inputs/history-g27.json",
        "certification/d11s/inputs/restart-g12.json",
    }
)

RUNTIME_MANIFEST_VERSION = "d11s-kayla-v0-g6-g14-g24-v1"


def _require_hash(value: str, name: str) -> None:
    if len(value) != _HASH_LENGTH or any(char not in "0123456789abcdef" for char in value):
        raise ValueError(f"{name} must be 64 lowercase hexadecimal characters")


def _require_git_sha(value: object, name: str) -> None:
    if (
        not isinstance(value, str)
        or len(value) != _GIT_SHA_LENGTH
        or any(char not in "0123456789abcdef" for char in value)
    ):
        raise ValueError(f"{name} must be exactly 40 lowercase hexadecimal characters")


def _require_tuple(value: object, name: str) -> None:
    if not isinstance(value, tuple):
        raise ValueError(f"{name} must be an immutable tuple")


def _require_utc(value: datetime, name: str) -> None:
    require_aware_utc(value, name)
    if value.utcoffset() != timedelta(0):
        raise ValueError(f"{name} must be UTC")


@dataclass(frozen=True, slots=True)
class SimulationEvent:
    event_id: str
    at_offset: timedelta
    evidence: tuple[Evidence, ...]
    historical_context: HistoricalContextBundle | None
    expected_path: str

    def __post_init__(self) -> None:
        require_non_empty(self.event_id, "event_id")
        if self.at_offset < timedelta(0):
            raise ValueError("at_offset must be non-negative")
        require_non_empty(self.expected_path, "expected_path")
        if not isinstance(self.evidence, tuple):
            raise ValueError("evidence must be an immutable tuple")
        if any(not isinstance(item, Evidence) for item in self.evidence):
            raise ValueError("evidence entries must be Evidence")
        if self.historical_context is not None and not isinstance(
            self.historical_context, HistoricalContextBundle
        ):
            raise ValueError("historical_context must be HistoricalContextBundle or None")


@dataclass(frozen=True, slots=True)
class RuntimeComponentConfig:
    component_id: str
    schema_version: str
    payload: Mapping[str, object]
    payload_sha256: str

    def __post_init__(self) -> None:
        require_non_empty(self.component_id, "component_id")
        require_non_empty(self.schema_version, "schema_version")
        if not isinstance(self.payload, Mapping) or not self.payload:
            raise ValueError("payload must be a non-empty mapping")
        object.__setattr__(self, "payload", freeze_mapping(self.payload, "payload"))
        _require_hash(self.payload_sha256, "payload_sha256")


@dataclass(frozen=True, slots=True)
class InputArtifactRef:
    logical_path: str
    byte_length: int
    bytes_sha256: str

    def __post_init__(self) -> None:
        _validate_logical_path(self.logical_path)
        if isinstance(self.byte_length, bool) or self.byte_length < 0:
            raise ValueError("byte_length must be non-negative")
        _require_hash(self.bytes_sha256, "bytes_sha256")


@dataclass(frozen=True, slots=True)
class RuntimeConfigManifest:
    manifest_version: str
    components: tuple[RuntimeComponentConfig, ...]
    fixture_artifacts: tuple[InputArtifactRef, ...]
    recovery_horizon_days: int
    convergence_tolerance: str

    def __post_init__(self) -> None:
        require_non_empty(self.manifest_version, "manifest_version")
        _require_tuple(self.components, "components")
        _require_tuple(self.fixture_artifacts, "fixture_artifacts")
        component_ids = tuple(component.component_id for component in self.components)
        if len(component_ids) != len(set(component_ids)):
            raise ValueError("component IDs must be unique")
        if frozenset(component_ids) != REQUIRED_COMPONENT_IDS:
            raise ValueError("component IDs must exactly match the closed registry")
        paths = tuple(artifact.logical_path for artifact in self.fixture_artifacts)
        if len(paths) != len(set(paths)):
            raise ValueError("fixture artifact paths must be unique")
        if frozenset(paths) != REQUIRED_FIXTURE_PATHS:
            raise ValueError("fixture artifact paths must exactly match the closed registry")
        if isinstance(self.recovery_horizon_days, bool) or self.recovery_horizon_days < 1:
            raise ValueError("recovery_horizon_days must be positive")
        require_non_empty(self.convergence_tolerance, "convergence_tolerance")


@dataclass(frozen=True, slots=True)
class CertificationPlan:
    certification_id: str
    source_head: str
    persona_version: str
    runtime_config_manifest_sha256: str
    horizon_days: Literal[30, 90]
    started_at: datetime
    events: tuple[SimulationEvent, ...]
    checkpoint_interval: timedelta

    def __post_init__(self) -> None:
        require_non_empty(self.certification_id, "certification_id")
        _require_git_sha(self.source_head, "source_head")
        require_non_empty(self.persona_version, "persona_version")
        _require_hash(self.runtime_config_manifest_sha256, "runtime_config_manifest_sha256")
        if self.horizon_days not in (30, 90):
            raise ValueError("horizon_days must be exactly 30 or 90")
        _require_utc(self.started_at, "started_at")
        _require_tuple(self.events, "events")
        event_ids = tuple(event.event_id for event in self.events)
        if len(event_ids) != len(set(event_ids)):
            raise ValueError("event IDs must be unique")
        if any(event.at_offset > timedelta(days=self.horizon_days) for event in self.events):
            raise ValueError("events must not exceed horizon_days")
        if not timedelta(0) < self.checkpoint_interval <= timedelta(days=1):
            raise ValueError("checkpoint_interval must be positive and no larger than one day")


@dataclass(frozen=True, slots=True)
class DecisionAuthoritySnapshot:
    accepted_event_refs: tuple[str, ...]
    transition_refs: tuple[str, ...]
    canonical_state_refs: tuple[str, ...]
    candidate_intent_refs: tuple[str, ...]
    selected_intent_ref: str | None
    policy_result_ref: str | None
    checkpoint_recovery: str

    def __post_init__(self) -> None:
        for field_name in (
            "accepted_event_refs",
            "transition_refs",
            "canonical_state_refs",
            "candidate_intent_refs",
        ):
            _require_tuple(getattr(self, field_name), field_name)
            for value in getattr(self, field_name):
                require_non_empty(value, field_name)
        for value, field_name in (
            (self.selected_intent_ref, "selected_intent_ref"),
            (self.policy_result_ref, "policy_result_ref"),
        ):
            if value is not None:
                require_non_empty(value, field_name)
        require_non_empty(self.checkpoint_recovery, "checkpoint_recovery")


@dataclass(frozen=True, slots=True)
class DailyDecisionDigest:
    virtual_day: int
    canonical_state_hash: str
    pending_intent_hash: str
    transition_trace_hash: str
    policy_decision_hash: str
    checkpoint_recovery_hash: str

    def __post_init__(self) -> None:
        if isinstance(self.virtual_day, bool) or self.virtual_day < 0:
            raise ValueError("virtual_day must be non-negative")
        for field_name in (
            "canonical_state_hash",
            "pending_intent_hash",
            "transition_trace_hash",
            "policy_decision_hash",
            "checkpoint_recovery_hash",
        ):
            _require_hash(getattr(self, field_name), field_name)


@dataclass(frozen=True, slots=True)
class InvariantResult:
    code: str
    passed: bool
    observed: str
    expected: str
    evidence_refs: tuple[str, ...]

    def __post_init__(self) -> None:
        require_non_empty(self.code, "code")
        require_non_empty(self.observed, "observed")
        require_non_empty(self.expected, "expected")
        if not isinstance(self.passed, bool):
            raise ValueError("passed must be a bool")
        _require_tuple(self.evidence_refs, "evidence_refs")
        if not self.evidence_refs:
            raise ValueError("evidence_refs must not be empty")
        for ref in self.evidence_refs:
            require_non_empty(ref, "evidence_refs entries")


@dataclass(frozen=True, slots=True)
class CertificationReport:
    certification_id: str
    source_head: str
    input_sha256: str
    runtime_config_manifest_sha256: str
    virtual_horizon_days: int
    wall_clock_execution_seconds: float
    first_run_daily_digests: tuple[DailyDecisionDigest, ...]
    replay_daily_digests: tuple[DailyDecisionDigest, ...]
    invariants: tuple[InvariantResult, ...]
    certification_sha256: str

    def __post_init__(self) -> None:
        require_non_empty(self.certification_id, "certification_id")
        _require_git_sha(self.source_head, "source_head")
        for field_name in (
            "input_sha256",
            "runtime_config_manifest_sha256",
            "certification_sha256",
        ):
            _require_hash(getattr(self, field_name), field_name)
        if self.virtual_horizon_days not in (30, 90):
            raise ValueError("virtual_horizon_days must be exactly 30 or 90")
        if (
            isinstance(self.wall_clock_execution_seconds, bool)
            or not isinstance(self.wall_clock_execution_seconds, (int, float))
            or not isfinite(self.wall_clock_execution_seconds)
            or self.wall_clock_execution_seconds < 0
        ):
            raise ValueError("wall_clock_execution_seconds must be non-negative and finite")
        _require_tuple(self.first_run_daily_digests, "first_run_daily_digests")
        _require_tuple(self.replay_daily_digests, "replay_daily_digests")
        _require_tuple(self.invariants, "invariants")
        if len(self.first_run_daily_digests) != self.virtual_horizon_days:
            raise ValueError("first_run_daily_digests count must match virtual horizon")
        if len(self.replay_daily_digests) != self.virtual_horizon_days:
            raise ValueError("replay_daily_digests count must match virtual horizon")
        if tuple(item.virtual_day for item in self.first_run_daily_digests) != tuple(
            range(self.virtual_horizon_days)
        ):
            raise ValueError("first_run daily digest virtual_day values must be complete")
        if tuple(item.virtual_day for item in self.replay_daily_digests) != tuple(
            range(self.virtual_horizon_days)
        ):
            raise ValueError("replay daily digest virtual_day values must be complete")
        codes = tuple(item.code for item in self.invariants)
        if not codes:
            raise ValueError("invariants must not be empty")
        if len(codes) != len(set(codes)):
            raise ValueError("invariant codes must be unique")


@dataclass(frozen=True, slots=True)
class ArtifactManifest:
    logical_path: str
    byte_length: int
    bytes_sha256: str

    def __post_init__(self) -> None:
        _validate_logical_path(self.logical_path)
        if isinstance(self.byte_length, bool) or self.byte_length < 0:
            raise ValueError("byte_length must be non-negative")
        _require_hash(self.bytes_sha256, "bytes_sha256")


@dataclass(frozen=True, slots=True)
class FactIngestConfig:
    backend: str
    clock: str
    certification_channel: str
    certification_scope: Scope

    def __post_init__(self) -> None:
        require_non_empty(self.certification_channel, "certification_channel")
        if not isinstance(self.certification_scope, Scope):
            raise ValueError("certification_scope must be a Scope")


@dataclass(frozen=True, slots=True)
class EffectiveStateConfig:
    definitions_component: str
    state_backend: str


@dataclass(frozen=True, slots=True)
class HistoricalContextConfig:
    mode: str
    provider_mode: str
    budget: int


@dataclass(frozen=True, slots=True)
class IntentEngineConfig:
    rules: tuple[IntentRule, ...]
    runtime_id: str

    def __post_init__(self) -> None:
        _require_tuple(self.rules, "rules")


@dataclass(frozen=True, slots=True)
class IntentLifecycleConfig:
    backend: str


@dataclass(frozen=True, slots=True)
class ContextRendererConfig:
    config_component: str


@dataclass(frozen=True, slots=True)
class PreviousExpressionConfig:
    mode: str
    expression: PreviousExpression | None


@dataclass(frozen=True, slots=True)
class CheckpointPolicyConfig:
    interval: timedelta
    backend: str


@dataclass(frozen=True, slots=True)
class SemanticProviderConfig:
    mode: str
    minimum_confidence: float
    conflict_margin: float


@dataclass(frozen=True, slots=True)
class ReceiptRegistryConfig:
    mode: str


@dataclass(frozen=True, slots=True)
class SlowPlasticityConfig:
    """C10-B-W configuration for the slow-plasticity rolling window.

    Attributes:
        window_size: Maximum number of qualifying SLOW_ACCEPT contributions
            retained in the rolling window per (scope, dimension).
            Must be >= 1.
    """

    window_size: int

    def __post_init__(self) -> None:
        if self.window_size < 1:
            raise ValueError("slow_plasticity window_size must be >= 1")


@dataclass(frozen=True, slots=True)
class AppraisalProducerStrategyConfig:
    strategy: str
    model: str
    endpoint_url: str
    api_key_env: str
    timeout_s: float
    allowed_hosts: tuple[str, ...]

    def __post_init__(self) -> None:
        require_non_empty(self.strategy, "strategy")
        require_non_empty(self.model, "model")
        require_non_empty(self.endpoint_url, "endpoint_url")
        require_non_empty(self.api_key_env, "api_key_env")
        if (
            isinstance(self.timeout_s, bool)
            or not isinstance(self.timeout_s, (int, float))
            or not isfinite(self.timeout_s)
            or self.timeout_s <= 0
        ):
            raise ValueError("timeout_s must be positive and finite")
        _require_tuple(self.allowed_hosts, "allowed_hosts")
        for host in self.allowed_hosts:
            require_non_empty(host, "allowed_hosts entries")


@dataclass(frozen=True, slots=True)
class HomeostasisConfig:
    salience_floor_fast_apply: float
    salience_floor_slow_accept: float
    confidence_floor_slow: float

    def __post_init__(self) -> None:
        for field_name in (
            "salience_floor_fast_apply",
            "salience_floor_slow_accept",
            "confidence_floor_slow",
        ):
            value = getattr(self, field_name)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError(f"{field_name} must be numeric")
            if not isfinite(value) or not 0.0 <= float(value) <= 1.0:
                raise ValueError(f"{field_name} must be in [0, 1]")


@dataclass(frozen=True, slots=True)
class DecodedRuntimeConfig:
    state_definitions: StateDefinitionRegistry
    persona_profile: PersonaProfile
    fact_ingest: FactIngestConfig
    effective_state: EffectiveStateConfig
    situation: SituationBuilder
    emotional_effects: tuple[EventEffectRule, ...]
    historical_context: HistoricalContextConfig
    intent_engine: IntentEngineConfig
    intent_lifecycle: IntentLifecycleConfig
    action_policy: ActionPolicyConfig
    policy_resources: PolicyResources
    decision_context: DecisionContextConfig
    context_renderer: ContextRendererConfig
    expression_guard: ExpressionGuardConfig
    expression_coordinator: ExpressionCoordinatorConfig
    previous_expression: PreviousExpressionConfig
    checkpoint_policy: CheckpointPolicyConfig
    semantic_provider: SemanticProviderConfig
    receipt_registry: ReceiptRegistryConfig
    slow_plasticity: SlowPlasticityConfig
    appraisal_producer_strategy: AppraisalProducerStrategyConfig
    homeostasis: HomeostasisConfig

    def __post_init__(self) -> None:
        _require_tuple(self.emotional_effects, "emotional_effects")


@dataclass(frozen=True, slots=True)
class HorizonTemplate:
    certification_id: str
    persona_version: str
    horizon_days: Literal[30, 90]
    started_at: datetime
    events: tuple[SimulationEvent, ...]
    checkpoint_interval: timedelta

    def __post_init__(self) -> None:
        require_non_empty(self.certification_id, "certification_id")
        require_non_empty(self.persona_version, "persona_version")
        _require_utc(self.started_at, "started_at")
        _require_tuple(self.events, "events")
        if self.horizon_days not in (30, 90):
            raise ValueError("horizon_days must be exactly 30 or 90")
        event_ids = tuple(event.event_id for event in self.events)
        if len(event_ids) != len(set(event_ids)):
            raise ValueError("event IDs must be unique")
        if any(event.at_offset > timedelta(days=self.horizon_days) for event in self.events):
            raise ValueError("events must not exceed horizon_days")
        if not timedelta(0) < self.checkpoint_interval <= timedelta(days=1):
            raise ValueError("checkpoint_interval must be positive and no larger than one day")


@dataclass(frozen=True, slots=True)
class ModelSwapFixture:
    fixture_id: str
    responses: tuple[str, ...]

    def __post_init__(self) -> None:
        _require_tuple(self.responses, "responses")


@dataclass(frozen=True, slots=True)
class HistoryFixture:
    fixture_id: str
    retrieval_count: int
    bundle: HistoricalContextBundle


@dataclass(frozen=True, slots=True)
class DurableStoreModes:
    facts: str
    state: str
    intents: str
    checkpoints: str


@dataclass(frozen=True, slots=True)
class RestartFixture:
    fixture_id: str
    durable_store_modes: DurableStoreModes
    state_definitions: tuple[StateDefinition, ...]
    interactions: tuple[Interaction, ...]
    evidence: tuple[Evidence, ...]
    expected_observation: Observation
    states: tuple[RuntimeState, ...]
    state_transitions: tuple[StateTransition, ...]
    intent_history: tuple[Intent, ...]
    intent_transitions: tuple[IntentTransition, ...]
    checkpoint: TurnCheckpoint
    historical_context: HistoricalContextBundle

    def __post_init__(self) -> None:
        for field_name in (
            "state_definitions",
            "interactions",
            "evidence",
            "states",
            "state_transitions",
            "intent_history",
            "intent_transitions",
        ):
            _require_tuple(getattr(self, field_name), field_name)

        interaction_ids = tuple(item.interaction_id for item in self.interactions)
        if not interaction_ids or len(interaction_ids) != len(set(interaction_ids)):
            raise ValueError("restart interaction IDs must be non-empty and unique")
        if self.expected_observation.interaction_id not in interaction_ids:
            raise ValueError("expected_observation interaction_id must resolve to interactions")
        if self.checkpoint.interaction_id not in interaction_ids:
            raise ValueError("checkpoint interaction_id must resolve to interactions")

        evidence_ids = tuple(item.id for item in self.evidence)
        if len(evidence_ids) != len(set(evidence_ids)):
            raise ValueError("restart evidence IDs must be unique")
        if not set(self.expected_observation.evidence_refs) <= set(evidence_ids):
            raise ValueError("expected_observation evidence_refs must resolve to evidence")

        transition_ids = tuple(item.transition_id for item in self.state_transitions)
        if not transition_ids or len(transition_ids) != len(set(transition_ids)):
            raise ValueError("restart state transition IDs must be non-empty and unique")
        transitions_by_id = {
            transition.transition_id: transition for transition in self.state_transitions
        }
        if any(not set(state.transition_refs) <= set(transition_ids) for state in self.states):
            raise ValueError("state transition_refs must resolve to state_transitions")
        if any(
            transitions_by_id[transition_ref].to_state != state
            for state in self.states
            for transition_ref in state.transition_refs
        ):
            raise ValueError("state transition_refs must identify transitions to that state")


def _validate_logical_path(value: str) -> None:
    require_non_empty(value, "logical_path")
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or "\\" in value:
        raise ValueError("logical_path must be repository-relative")


def _mapping(
    payload: Mapping[str, object], expected: set[str], component_id: str
) -> Mapping[str, object]:
    if set(payload) != expected:
        raise ValueError(f"{component_id} payload keys must exactly match schema")
    return payload


def _object(value: object, expected: set[str], context: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or set(value) != expected:
        raise ValueError(f"{context} schema drift")
    return cast(Mapping[str, object], value)


def _array(value: object, context: str) -> list[object] | tuple[object, ...]:
    if not isinstance(value, (list, tuple)):
        raise ValueError(f"{context} schema requires an array")
    return value


def _string(value: object, context: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{context} must be a non-empty string")
    return value


def _optional_string(value: object, context: str) -> str | None:
    if value is None:
        return None
    return _string(value, context)


def _integer(value: object, context: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{context} must be an integer")
    return value


def _number(value: object, context: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not isfinite(value):
        raise ValueError(f"{context} must be a finite number")
    return float(value)


def _optional_number(value: object, context: str) -> float | None:
    if value is None:
        return None
    return _number(value, context)


def _unit_interval(value: object, context: str) -> float:
    number = _number(value, context)
    if not 0.0 <= number <= 1.0:
        raise ValueError(f"{context} must be in [0, 1]")
    return number


def _datetime(value: object, context: str) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise ValueError(f"{context} must be a UTC Z timestamp")
    try:
        parsed = datetime.fromisoformat(f"{value[:-1]}+00:00")
    except ValueError as error:
        raise ValueError(f"{context} must be a UTC Z timestamp") from error
    _require_utc(parsed, context)
    return parsed


def _optional_datetime(value: object, context: str) -> datetime | None:
    if value is None:
        return None
    return _datetime(value, context)


def _duration(value: object, context: str) -> timedelta:
    return timedelta(microseconds=_integer(value, context))


def _strings(value: object, context: str) -> tuple[str, ...]:
    return tuple(_string(item, f"{context} entries") for item in _array(value, context))


def _scope(value: object, context: str) -> Scope:
    raw = _object(
        value,
        {
            "domain",
            "user_id",
            "agent_id",
            "persona_id",
            "relationship_id",
            "world_id",
            "interaction_id",
        },
        context,
    )
    try:
        domain = ScopeDomain(_string(raw["domain"], f"{context}.domain"))
    except ValueError as error:
        raise ValueError(f"{context}.domain must be a ScopeDomain value") from error
    return Scope(
        domain=domain,
        user_id=_optional_string(raw["user_id"], f"{context}.user_id"),
        agent_id=_optional_string(raw["agent_id"], f"{context}.agent_id"),
        persona_id=_optional_string(raw["persona_id"], f"{context}.persona_id"),
        relationship_id=_optional_string(raw["relationship_id"], f"{context}.relationship_id"),
        world_id=_optional_string(raw["world_id"], f"{context}.world_id"),
        interaction_id=_optional_string(raw["interaction_id"], f"{context}.interaction_id"),
    )


def _sync(value: object, context: str) -> SyncFields:
    raw = _object(
        value,
        {"scope", "origin_runtime_id", "object_id", "version", "idempotency_key"},
        context,
    )
    return SyncFields(
        scope=_scope(raw["scope"], f"{context}.scope"),
        origin_runtime_id=_string(raw["origin_runtime_id"], f"{context}.origin_runtime_id"),
        object_id=_string(raw["object_id"], f"{context}.object_id"),
        version=_integer(raw["version"], f"{context}.version"),
        idempotency_key=_string(raw["idempotency_key"], f"{context}.idempotency_key"),
    )


def _state_definition(value: object, context: str) -> StateDefinition:
    raw = _object(
        value,
        {
            "key",
            "domain",
            "value_type",
            "dynamics_policy",
            "default_validity_policy",
            "bounds",
        },
        context,
    )
    bounds_raw = raw["bounds"]
    bounds: object | None
    if bounds_raw is None:
        bounds = None
    else:
        values = _array(bounds_raw, f"{context}.bounds")
        if len(values) != 2:
            raise ValueError(f"{context}.bounds schema requires two values")
        bounds = tuple(_number(item, f"{context}.bounds") for item in values)
    try:
        domain = StateDomain(_string(raw["domain"], f"{context}.domain"))
        value_type = StateValueType(_string(raw["value_type"], f"{context}.value_type"))
    except ValueError as error:
        raise ValueError(f"{context} enum value is invalid") from error
    return StateDefinition(
        key=_string(raw["key"], f"{context}.key"),
        domain=domain,
        value_type=value_type,
        dynamics_policy=_string(raw["dynamics_policy"], f"{context}.dynamics_policy"),
        default_validity_policy=_optional_string(
            raw["default_validity_policy"], f"{context}.default_validity_policy"
        ),
        bounds=bounds,
    )


def _pairs(value: object, context: str) -> tuple[tuple[str, float], ...]:
    pairs: list[tuple[str, float]] = []
    for index, item in enumerate(_array(value, context)):
        pair = _array(item, f"{context}[{index}]")
        if len(pair) != 2:
            raise ValueError(f"{context}[{index}] schema requires a pair")
        pairs.append(
            (
                _string(pair[0], f"{context}[{index}][0]"),
                _number(pair[1], f"{context}[{index}][1]"),
            )
        )
    return tuple(pairs)


def _dimension(value: object, context: str) -> AffectiveDimensionProfile:
    raw = _object(
        value,
        {
            "dimension",
            "baseline",
            "initial_value",
            "sensitivity",
            "recovery_rate",
            "ceiling",
            "floor",
            "growth_profile",
            "coupling_profile",
        },
        context,
    )
    return AffectiveDimensionProfile(
        dimension=_string(raw["dimension"], f"{context}.dimension"),
        baseline=_number(raw["baseline"], f"{context}.baseline"),
        initial_value=_number(raw["initial_value"], f"{context}.initial_value"),
        sensitivity=_number(raw["sensitivity"], f"{context}.sensitivity"),
        recovery_rate=_number(raw["recovery_rate"], f"{context}.recovery_rate"),
        ceiling=_number(raw["ceiling"], f"{context}.ceiling"),
        floor=_number(raw["floor"], f"{context}.floor"),
        growth_profile=_pairs(raw["growth_profile"], f"{context}.growth_profile"),
        coupling_profile=_pairs(raw["coupling_profile"], f"{context}.coupling_profile"),
    )


def _event_effect(value: object, context: str) -> EventEffectRule:
    if not isinstance(value, Mapping):
        raise ValueError(f"{context} schema drift")
    keys = set(value)
    base_keys = {
        "event_kind",
        "dimension",
        "base_amount",
        "history_amount_per_match",
        "history_amount_cap",
        "minimum_history_confidence",
    }
    long_keys = {"longitudinal_target_dimension", "longitudinal_proposed_value"}
    mode_keys = {"admission_mode"}
    admission_mode = "legacy_independent"
    if "admission_mode" in keys:
        admission_mode = _string(value["admission_mode"], f"{context}.admission_mode")
        keys -= mode_keys
    if keys == base_keys:
        raw = value
        long_dim = None
        long_val = None
    elif keys == (base_keys | long_keys):
        raw = value
        long_dim = _optional_string(
            raw["longitudinal_target_dimension"], f"{context}.longitudinal_target_dimension"
        )
        long_val = _optional_number(
            raw["longitudinal_proposed_value"], f"{context}.longitudinal_proposed_value"
        )
    else:
        raise ValueError(f"{context} schema drift")

    return EventEffectRule(
        event_kind=_string(raw["event_kind"], f"{context}.event_kind"),
        dimension=_string(raw["dimension"], f"{context}.dimension"),
        base_amount=_number(raw["base_amount"], f"{context}.base_amount"),
        history_amount_per_match=_number(
            raw["history_amount_per_match"], f"{context}.history_amount_per_match"
        ),
        history_amount_cap=_number(raw["history_amount_cap"], f"{context}.history_amount_cap"),
        minimum_history_confidence=_number(
            raw["minimum_history_confidence"], f"{context}.minimum_history_confidence"
        ),
        longitudinal_target_dimension=long_dim,
        longitudinal_proposed_value=long_val,
        admission_mode=admission_mode,
    )


def _intent_rule(value: object, context: str) -> IntentRule:
    raw = _object(
        value,
        {
            "rule_id",
            "kind",
            "base_strength",
            "dimension_weights",
            "event_kind",
            "event_bonus",
            "minimum_strength",
            "due_at_attribute",
            "expires_after",
            "reconsideration_policy",
        },
        context,
    )
    try:
        reconsideration = ReconsiderationPolicy(
            _string(raw["reconsideration_policy"], f"{context}.reconsideration_policy")
        )
    except ValueError as error:
        raise ValueError(f"{context}.reconsideration_policy enum value is invalid") from error
    return IntentRule(
        rule_id=_string(raw["rule_id"], f"{context}.rule_id"),
        kind=_string(raw["kind"], f"{context}.kind"),
        base_strength=_number(raw["base_strength"], f"{context}.base_strength"),
        dimension_weights=_pairs(raw["dimension_weights"], f"{context}.dimension_weights"),
        event_kind=_optional_string(raw["event_kind"], f"{context}.event_kind"),
        event_bonus=_number(raw["event_bonus"], f"{context}.event_bonus"),
        minimum_strength=_number(raw["minimum_strength"], f"{context}.minimum_strength"),
        due_at_attribute=_optional_string(raw["due_at_attribute"], f"{context}.due_at_attribute"),
        expires_after=(
            None
            if raw["expires_after"] is None
            else _duration(raw["expires_after"], f"{context}.expires_after")
        ),
        reconsideration_policy=reconsideration,
    )


def _policy_rule(value: object, context: str) -> IntentPolicyRule:
    raw = _object(
        value,
        {
            "intent_kind",
            "action_type",
            "proactive",
            "interrupts_active_conversation",
            "media_counter_fact",
            "media_limit",
            "required_resource",
        },
        context,
    )
    proactive = raw["proactive"]
    interrupts = raw["interrupts_active_conversation"]
    if not isinstance(proactive, bool) or not isinstance(interrupts, bool):
        raise ValueError(f"{context} boolean fields are invalid")
    media_limit = raw["media_limit"]
    if media_limit is not None:
        media_limit = _integer(media_limit, f"{context}.media_limit")
    return IntentPolicyRule(
        intent_kind=_string(raw["intent_kind"], f"{context}.intent_kind"),
        action_type=_string(raw["action_type"], f"{context}.action_type"),
        proactive=proactive,
        interrupts_active_conversation=interrupts,
        media_counter_fact=_optional_string(
            raw["media_counter_fact"], f"{context}.media_counter_fact"
        ),
        media_limit=media_limit,
        required_resource=_optional_string(
            raw["required_resource"], f"{context}.required_resource"
        ),
    )


def _previous_expression(value: object, context: str) -> PreviousExpression:
    raw = _object(
        value,
        {
            "expression_id",
            "scope",
            "origin_runtime_id",
            "action_type",
            "text",
            "receipt_ref",
            "delivery_status",
            "sent_at",
        },
        context,
    )
    try:
        status = DeliveryStatus(_string(raw["delivery_status"], f"{context}.delivery_status"))
    except ValueError as error:
        raise ValueError(f"{context}.delivery_status enum value is invalid") from error
    return PreviousExpression(
        expression_id=_string(raw["expression_id"], f"{context}.expression_id"),
        scope=_scope(raw["scope"], f"{context}.scope"),
        origin_runtime_id=_string(raw["origin_runtime_id"], f"{context}.origin_runtime_id"),
        action_type=_string(raw["action_type"], f"{context}.action_type"),
        text=_string(raw["text"], f"{context}.text"),
        receipt_ref=_string(raw["receipt_ref"], f"{context}.receipt_ref"),
        delivery_status=status,
        sent_at=_datetime(raw["sent_at"], f"{context}.sent_at"),
    )


def _state_definitions(payload: Mapping[str, object]) -> StateDefinitionRegistry:
    _mapping(payload, {"definitions"}, "state_definitions")
    definitions = tuple(
        _state_definition(value, f"state_definitions.definitions[{index}]")
        for index, value in enumerate(
            _array(payload["definitions"], "state_definitions.definitions")
        )
    )
    if not definitions:
        raise ValueError("state_definitions definitions must not be empty")
    return StateDefinitionRegistry(definitions)


def _persona(payload: Mapping[str, object]) -> PersonaProfile:
    _mapping(payload, {"persona_id", "version", "dimensions"}, "persona_profile")
    dimensions = tuple(
        _dimension(value, f"persona_profile.dimensions[{index}]")
        for index, value in enumerate(_array(payload["dimensions"], "persona_profile.dimensions"))
    )
    if not dimensions:
        raise ValueError("persona_profile dimensions must not be empty")
    return PersonaProfile(
        _string(payload["persona_id"], "persona_profile.persona_id"),
        dimensions,
        _integer(payload["version"], "persona_profile.version"),
    )


def _fact_ingest(payload: Mapping[str, object]) -> FactIngestConfig:
    _mapping(
        payload,
        {"backend", "clock", "certification_channel", "certification_scope"},
        "fact_ingest",
    )
    config = FactIngestConfig(
        _string(payload["backend"], "fact_ingest.backend"),
        _string(payload["clock"], "fact_ingest.clock"),
        _string(payload["certification_channel"], "fact_ingest.certification_channel"),
        _scope(payload["certification_scope"], "fact_ingest.certification_scope"),
    )
    if config.backend != "sqlite" or config.clock != "simulation":
        raise ValueError("fact_ingest must declare sqlite and simulation modes")
    return config


def _effective_state(payload: Mapping[str, object]) -> EffectiveStateConfig:
    _mapping(payload, {"definitions_component", "state_backend"}, "effective_state")
    config = EffectiveStateConfig(
        _string(payload["definitions_component"], "effective_state.definitions_component"),
        _string(payload["state_backend"], "effective_state.state_backend"),
    )
    if config != EffectiveStateConfig("state_definitions", "sqlite"):
        raise ValueError("effective_state must bind definitions and sqlite state backend")
    return config


def _situation(payload: Mapping[str, object]) -> SituationBuilder:
    _mapping(
        payload,
        {
            "runtime_id",
            "recently_awake_window",
            "conversation_idle_window",
            "interaction_recent_window",
        },
        "situation",
    )
    return SituationBuilder(
        runtime_id=_string(payload["runtime_id"], "situation.runtime_id"),
        recently_awake_window=_duration(
            payload["recently_awake_window"], "situation.recently_awake_window"
        ),
        conversation_idle_window=_duration(
            payload["conversation_idle_window"], "situation.conversation_idle_window"
        ),
        interaction_recent_window=_duration(
            payload["interaction_recent_window"], "situation.interaction_recent_window"
        ),
    )


def _effects(payload: Mapping[str, object]) -> tuple[EventEffectRule, ...]:
    _mapping(payload, {"rules"}, "emotional_effects")
    rules = tuple(
        _event_effect(value, f"emotional_effects.rules[{index}]")
        for index, value in enumerate(_array(payload["rules"], "emotional_effects.rules"))
    )
    if not rules:
        raise ValueError("emotional_effects rules must not be empty")
    return rules


def _history(payload: Mapping[str, object]) -> HistoricalContextConfig:
    _mapping(payload, {"mode", "provider_mode", "budget"}, "historical_context")
    config = HistoricalContextConfig(
        _string(payload["mode"], "historical_context.mode"),
        _string(payload["provider_mode"], "historical_context.provider_mode"),
        _integer(payload["budget"], "historical_context.budget"),
    )
    if config != HistoricalContextConfig("bounded_read_only", "manifest_fixture", 8):
        raise ValueError("historical_context must use the bounded read-only fixture mode")
    return config


def _intent_engine(payload: Mapping[str, object]) -> IntentEngineConfig:
    _mapping(payload, {"rules", "runtime_id"}, "intent_engine")
    rules = tuple(
        _intent_rule(value, f"intent_engine.rules[{index}]")
        for index, value in enumerate(_array(payload["rules"], "intent_engine.rules"))
    )
    if not rules:
        raise ValueError("intent_engine rules must not be empty")
    return IntentEngineConfig(rules, _string(payload["runtime_id"], "intent_engine.runtime_id"))


def _intent_lifecycle(payload: Mapping[str, object]) -> IntentLifecycleConfig:
    _mapping(payload, {"backend"}, "intent_lifecycle")
    config = IntentLifecycleConfig(_string(payload["backend"], "intent_lifecycle.backend"))
    if config.backend != "sqlite":
        raise ValueError("intent_lifecycle backend must be sqlite")
    return config


def _action_policy(payload: Mapping[str, object]) -> ActionPolicyConfig:
    _mapping(payload, {"rules", "proactive_cooldown"}, "action_policy")
    rules = tuple(
        _policy_rule(value, f"action_policy.rules[{index}]")
        for index, value in enumerate(_array(payload["rules"], "action_policy.rules"))
    )
    if not rules:
        raise ValueError("action_policy rules must not be empty")
    return ActionPolicyConfig(
        rules=rules,
        proactive_cooldown=_duration(
            payload["proactive_cooldown"], "action_policy.proactive_cooldown"
        ),
    )


def _resources(payload: Mapping[str, object]) -> PolicyResources:
    _mapping(payload, {"available_actions"}, "policy_resources")
    return PolicyResources(
        _strings(payload["available_actions"], "policy_resources.available_actions")
    )


def _context(payload: Mapping[str, object]) -> DecisionContextConfig:
    _mapping(
        payload,
        {
            "allowed_situation_facts",
            "affect_rules",
            "persona_style_constraints",
            "allowed_history_kinds",
            "max_history_items",
            "max_prior_expression_chars",
            "max_item_chars",
            "max_items",
            "max_render_chars",
        },
        "decision_context",
    )
    affect_rules = _array(payload["affect_rules"], "decision_context.affect_rules")
    if affect_rules:
        raise ValueError("decision_context affect_rules must mirror the G14 empty tuple")
    style = tuple(
        (
            _string(pair[0], "persona_style_constraints key"),
            _string(pair[1], "persona_style_constraints value"),
        )
        for pair in (
            _array(item, "decision_context.persona_style_constraints entry")
            for item in _array(
                payload["persona_style_constraints"],
                "decision_context.persona_style_constraints",
            )
        )
        if len(pair) == 2
    )
    if len(style) != len(
        _array(payload["persona_style_constraints"], "decision_context.persona_style_constraints")
    ):
        raise ValueError("decision_context persona_style_constraints schema drift")
    return DecisionContextConfig(
        allowed_situation_facts=_strings(
            payload["allowed_situation_facts"], "decision_context.allowed_situation_facts"
        ),
        affect_rules=(),
        persona_style_constraints=style,
        allowed_history_kinds=_strings(
            payload["allowed_history_kinds"], "decision_context.allowed_history_kinds"
        ),
        max_history_items=_integer(
            payload["max_history_items"], "decision_context.max_history_items"
        ),
        max_prior_expression_chars=_integer(
            payload["max_prior_expression_chars"], "decision_context.max_prior_expression_chars"
        ),
        max_item_chars=_integer(payload["max_item_chars"], "decision_context.max_item_chars"),
        max_items=_integer(payload["max_items"], "decision_context.max_items"),
        max_render_chars=_integer(payload["max_render_chars"], "decision_context.max_render_chars"),
    )


def _renderer(payload: Mapping[str, object]) -> ContextRendererConfig:
    _mapping(payload, {"config_component"}, "context_renderer")
    config = ContextRendererConfig(
        _string(payload["config_component"], "context_renderer.config_component")
    )
    if config.config_component != "decision_context":
        raise ValueError("context_renderer must bind decision_context")
    return config


def _guard(payload: Mapping[str, object]) -> ExpressionGuardConfig:
    _mapping(
        payload,
        {"prefix_length", "transport_markers", "banned_openings", "temporal_rules"},
        "expression_guard",
    )
    temporal_rules = _array(payload["temporal_rules"], "expression_guard.temporal_rules")
    if temporal_rules:
        raise ValueError("expression_guard temporal_rules must mirror the G14 empty tuple")
    return ExpressionGuardConfig(
        prefix_length=_integer(payload["prefix_length"], "expression_guard.prefix_length"),
        transport_markers=_strings(
            payload["transport_markers"], "expression_guard.transport_markers"
        ),
        banned_openings=_strings(payload["banned_openings"], "expression_guard.banned_openings"),
        temporal_rules=(),
    )


def _coordinator(payload: Mapping[str, object]) -> ExpressionCoordinatorConfig:
    _mapping(payload, {"max_rewrites"}, "expression_coordinator")
    return ExpressionCoordinatorConfig(
        _integer(payload["max_rewrites"], "expression_coordinator.max_rewrites")
    )


def _previous(payload: Mapping[str, object]) -> PreviousExpressionConfig:
    _mapping(payload, {"mode", "expression"}, "previous_expression")
    mode = _string(payload["mode"], "previous_expression.mode")
    if mode != "fixed" or payload["expression"] is None:
        raise ValueError("previous_expression must provide the fixed G14 value")
    return PreviousExpressionConfig(
        mode,
        _previous_expression(payload["expression"], "previous_expression.expression"),
    )


def _checkpoint(payload: Mapping[str, object]) -> CheckpointPolicyConfig:
    _mapping(payload, {"interval", "backend"}, "checkpoint_policy")
    config = CheckpointPolicyConfig(
        _duration(payload["interval"], "checkpoint_policy.interval"),
        _string(payload["backend"], "checkpoint_policy.backend"),
    )
    if not timedelta(0) < config.interval <= timedelta(days=1) or config.backend != "sqlite":
        raise ValueError("checkpoint_policy must use positive daily-or-less sqlite checkpoints")
    return config


def _semantic(payload: Mapping[str, object]) -> SemanticProviderConfig:
    _mapping(payload, {"mode", "minimum_confidence", "conflict_margin"}, "semantic_provider")
    config = SemanticProviderConfig(
        _string(payload["mode"], "semantic_provider.mode"),
        _number(payload["minimum_confidence"], "semantic_provider.minimum_confidence"),
        _number(payload["conflict_margin"], "semantic_provider.conflict_margin"),
    )
    # AUTHORITY (2026-09-05, owner): semantic_provider.mode accepts exactly
    # "disabled" | "enabled". "disabled" = provider absent by design;
    # "enabled" = production host MUST construct the existing provider via
    # create_semantic_provider(). Any other value (e.g. "model_backed") is
    # rejected — it mixed the capability switch with backend type.
    if config.mode not in ("disabled", "enabled"):
        raise ValueError("semantic_provider.mode must be 'disabled' or 'enabled'")
    if not (0 <= config.minimum_confidence <= 1 and 0 <= config.conflict_margin <= 1):
        raise ValueError("semantic_provider thresholds must be in [0, 1]")
    return config


def _receipts(payload: Mapping[str, object]) -> ReceiptRegistryConfig:
    _mapping(payload, {"mode"}, "receipt_registry")
    config = ReceiptRegistryConfig(_string(payload["mode"], "receipt_registry.mode"))
    if config.mode != "in_memory":
        raise ValueError("receipt_registry mode must be explicitly in_memory")
    return config


def _slow_plasticity(payload: Mapping[str, object]) -> SlowPlasticityConfig:
    _mapping(payload, {"window_size"}, "slow_plasticity")
    return SlowPlasticityConfig(
        window_size=_integer(payload["window_size"], "slow_plasticity.window_size"),
    )


def _appraisal_producer_strategy(
    payload: Mapping[str, object],
) -> AppraisalProducerStrategyConfig:
    _mapping(
        payload,
        {
            "strategy",
            "model",
            "endpoint_url",
            "api_key_env",
            "timeout_s",
            "allowed_hosts",
        },
        "appraisal_producer_strategy",
    )
    return AppraisalProducerStrategyConfig(
        strategy=_string(payload["strategy"], "appraisal_producer_strategy.strategy"),
        model=_string(payload["model"], "appraisal_producer_strategy.model"),
        endpoint_url=_string(
            payload["endpoint_url"], "appraisal_producer_strategy.endpoint_url"
        ),
        api_key_env=_string(
            payload["api_key_env"], "appraisal_producer_strategy.api_key_env"
        ),
        timeout_s=_number(payload["timeout_s"], "appraisal_producer_strategy.timeout_s"),
        allowed_hosts=_strings(
            payload["allowed_hosts"], "appraisal_producer_strategy.allowed_hosts"
        ),
    )


def _homeostasis(payload: Mapping[str, object]) -> HomeostasisConfig:
    _mapping(
        payload,
        {
            "salience_floor_fast_apply",
            "salience_floor_slow_accept",
            "confidence_floor_slow",
        },
        "homeostasis",
    )
    return HomeostasisConfig(
        salience_floor_fast_apply=_unit_interval(
            payload["salience_floor_fast_apply"], "homeostasis.salience_floor_fast_apply"
        ),
        salience_floor_slow_accept=_unit_interval(
            payload["salience_floor_slow_accept"], "homeostasis.salience_floor_slow_accept"
        ),
        confidence_floor_slow=_unit_interval(
            payload["confidence_floor_slow"], "homeostasis.confidence_floor_slow"
        ),
    )


DECODER_REGISTRY: dict[str, Callable[[Mapping[str, object]], object]] = {
    "state_definitions": _state_definitions,
    "persona_profile": _persona,
    "fact_ingest": _fact_ingest,
    "effective_state": _effective_state,
    "situation": _situation,
    "emotional_effects": _effects,
    "historical_context": _history,
    "intent_engine": _intent_engine,
    "intent_lifecycle": _intent_lifecycle,
    "action_policy": _action_policy,
    "policy_resources": _resources,
    "decision_context": _context,
    "context_renderer": _renderer,
    "expression_guard": _guard,
    "expression_coordinator": _coordinator,
    "previous_expression": _previous,
    "checkpoint_policy": _checkpoint,
    "semantic_provider": _semantic,
    "receipt_registry": _receipts,
    "slow_plasticity": _slow_plasticity,
    "appraisal_producer_strategy": _appraisal_producer_strategy,
    "homeostasis": _homeostasis,
}


def decode_component(component: RuntimeComponentConfig) -> object:
    """Verify payload bytes before handing an existing typed value to later composition."""
    from mind_runtime.validation.digest import canonical_json_bytes, sha256_bytes

    if component.component_id not in DECODER_REGISTRY:
        raise ValueError(f"unknown component ID: {component.component_id}")
    if component.schema_version != "v1":
        raise ValueError("unsupported component schema_version")
    if sha256_bytes(canonical_json_bytes(component.payload)) != component.payload_sha256:
        raise ValueError("component payload hash does not match canonical payload bytes")
    return DECODER_REGISTRY[component.component_id](component.payload)


def decode_runtime_manifest(manifest: RuntimeConfigManifest) -> DecodedRuntimeConfig:
    """Decode the full closed manifest without allowing generic mappings downstream."""
    if manifest.manifest_version != RUNTIME_MANIFEST_VERSION:
        raise ValueError("unsupported runtime manifest_version")
    decoded = {
        component.component_id: decode_component(component) for component in manifest.components
    }
    return DecodedRuntimeConfig(
        state_definitions=cast(StateDefinitionRegistry, decoded["state_definitions"]),
        persona_profile=cast(PersonaProfile, decoded["persona_profile"]),
        fact_ingest=cast(FactIngestConfig, decoded["fact_ingest"]),
        effective_state=cast(EffectiveStateConfig, decoded["effective_state"]),
        situation=cast(SituationBuilder, decoded["situation"]),
        emotional_effects=cast(tuple[EventEffectRule, ...], decoded["emotional_effects"]),
        historical_context=cast(HistoricalContextConfig, decoded["historical_context"]),
        intent_engine=cast(IntentEngineConfig, decoded["intent_engine"]),
        intent_lifecycle=cast(IntentLifecycleConfig, decoded["intent_lifecycle"]),
        action_policy=cast(ActionPolicyConfig, decoded["action_policy"]),
        policy_resources=cast(PolicyResources, decoded["policy_resources"]),
        decision_context=cast(DecisionContextConfig, decoded["decision_context"]),
        context_renderer=cast(ContextRendererConfig, decoded["context_renderer"]),
        expression_guard=cast(ExpressionGuardConfig, decoded["expression_guard"]),
        expression_coordinator=cast(ExpressionCoordinatorConfig, decoded["expression_coordinator"]),
        previous_expression=cast(PreviousExpressionConfig, decoded["previous_expression"]),
        checkpoint_policy=cast(CheckpointPolicyConfig, decoded["checkpoint_policy"]),
        semantic_provider=cast(SemanticProviderConfig, decoded["semantic_provider"]),
        receipt_registry=cast(ReceiptRegistryConfig, decoded["receipt_registry"]),
        slow_plasticity=cast(SlowPlasticityConfig, decoded["slow_plasticity"]),
        appraisal_producer_strategy=cast(
            AppraisalProducerStrategyConfig, decoded["appraisal_producer_strategy"]
        ),
        homeostasis=cast(HomeostasisConfig, decoded["homeostasis"]),
    )


def decode_runtime_config_manifest_bytes(data: bytes) -> RuntimeConfigManifest:
    """Strictly decode one already-bound UTF-8 manifest byte buffer."""
    if not isinstance(data, bytes):
        raise TypeError("runtime-config.json data must be bytes")
    try:
        raw = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("runtime-config.json must be valid UTF-8 JSON") from error
    if not isinstance(raw, dict) or set(raw) != {
        "manifest_version",
        "components",
        "fixture_artifacts",
        "recovery_horizon_days",
        "convergence_tolerance",
    }:
        raise ValueError("runtime-config.json schema drift")
    components_raw = raw["components"]
    artifacts_raw = raw["fixture_artifacts"]
    if not isinstance(components_raw, list) or not isinstance(artifacts_raw, list):
        raise ValueError("runtime-config.json components and fixture_artifacts must be lists")
    components: list[RuntimeComponentConfig] = []
    for item in components_raw:
        if (
            not isinstance(item, dict)
            or set(item) != {"component_id", "schema_version", "payload", "payload_sha256"}
            or not isinstance(item["payload"], dict)
        ):
            raise ValueError("runtime-config.json component schema drift")
        components.append(RuntimeComponentConfig(**item))
    artifacts: list[InputArtifactRef] = []
    for item in artifacts_raw:
        if not isinstance(item, dict) or set(item) != {
            "logical_path",
            "byte_length",
            "bytes_sha256",
        }:
            raise ValueError("runtime-config.json fixture artifact schema drift")
        artifacts.append(InputArtifactRef(**item))
    return RuntimeConfigManifest(
        manifest_version=raw["manifest_version"],
        components=tuple(components),
        fixture_artifacts=tuple(artifacts),
        recovery_horizon_days=raw["recovery_horizon_days"],
        convergence_tolerance=raw["convergence_tolerance"],
    )


def load_runtime_config_manifest(path: Path) -> RuntimeConfigManifest:
    """Read and strictly decode the only tracked manifest schema once."""
    try:
        data = path.read_bytes()
    except OSError as error:
        raise ValueError("runtime-config.json must be valid UTF-8 JSON") from error
    return decode_runtime_config_manifest_bytes(data)


def verify_fixture_artifacts(manifest: RuntimeConfigManifest, repository_root: Path) -> None:
    """Require every manifest-bound fixture to match its exact written bytes."""
    from mind_runtime.validation.digest import sha256_bytes

    for artifact in manifest.fixture_artifacts:
        path = repository_root / artifact.logical_path
        try:
            data = path.read_bytes()
        except OSError as error:
            raise ValueError(f"missing fixture artifact: {artifact.logical_path}") from error
        if len(data) != artifact.byte_length or sha256_bytes(data) != artifact.bytes_sha256:
            raise ValueError(
                f"fixture artifact bytes do not match manifest: {artifact.logical_path}"
            )


def _authority(value: object, context: str) -> Authority:
    raw = _object(value, {"scope", "level", "source_id"}, context)
    try:
        level = AuthorityLevel(_string(raw["level"], f"{context}.level"))
    except ValueError as error:
        raise ValueError(f"{context}.level enum value is invalid") from error
    return Authority(
        scope=_scope(raw["scope"], f"{context}.scope"),
        level=level,
        source_id=_optional_string(raw["source_id"], f"{context}.source_id"),
    )


def _evidence(value: object, context: str) -> Evidence:
    raw = _object(
        value,
        {
            "id",
            "source_type",
            "source_id",
            "authority_level",
            "occurred_at",
            "received_at",
            "payload",
            "scope",
            "origin_runtime_id",
            "authority",
            "sync",
        },
        context,
    )
    try:
        authority_level = AuthorityLevel(
            _string(raw["authority_level"], f"{context}.authority_level")
        )
    except ValueError as error:
        raise ValueError(f"{context}.authority_level enum value is invalid") from error
    return Evidence(
        id=_string(raw["id"], f"{context}.id"),
        source_type=_string(raw["source_type"], f"{context}.source_type"),
        source_id=_string(raw["source_id"], f"{context}.source_id"),
        authority_level=authority_level,
        occurred_at=_datetime(raw["occurred_at"], f"{context}.occurred_at"),
        received_at=_datetime(raw["received_at"], f"{context}.received_at"),
        payload=raw["payload"],
        scope=_scope(raw["scope"], f"{context}.scope"),
        origin_runtime_id=_string(raw["origin_runtime_id"], f"{context}.origin_runtime_id"),
        authority=_authority(raw["authority"], f"{context}.authority"),
        sync=_sync(raw["sync"], f"{context}.sync"),
    )


def _history_item(value: object, context: str) -> HistoricalContextItem:
    raw = _object(
        value,
        {
            "item_id",
            "scope",
            "external_id",
            "kind",
            "proposition",
            "source_refs",
            "confidence",
            "relevance_hint",
        },
        context,
    )
    return HistoricalContextItem(
        item_id=_string(raw["item_id"], f"{context}.item_id"),
        scope=_scope(raw["scope"], f"{context}.scope"),
        external_id=_string(raw["external_id"], f"{context}.external_id"),
        kind=_string(raw["kind"], f"{context}.kind"),
        proposition=_string(raw["proposition"], f"{context}.proposition"),
        source_refs=_strings(raw["source_refs"], f"{context}.source_refs"),
        confidence=(
            None
            if raw["confidence"] is None
            else _number(raw["confidence"], f"{context}.confidence")
        ),
        relevance_hint=(
            None
            if raw["relevance_hint"] is None
            else _number(raw["relevance_hint"], f"{context}.relevance_hint")
        ),
    )


def _pattern_summary(value: object, context: str) -> PatternMatchSummary:
    raw = _object(
        value,
        {
            "summary_id",
            "scope",
            "origin_runtime_id",
            "match_count",
            "first_seen_at",
            "last_seen_at",
            "matched_refs",
            "confidence",
        },
        context,
    )
    return PatternMatchSummary(
        summary_id=_string(raw["summary_id"], f"{context}.summary_id"),
        scope=_scope(raw["scope"], f"{context}.scope"),
        origin_runtime_id=_string(raw["origin_runtime_id"], f"{context}.origin_runtime_id"),
        match_count=_integer(raw["match_count"], f"{context}.match_count"),
        first_seen_at=_optional_datetime(raw["first_seen_at"], f"{context}.first_seen_at"),
        last_seen_at=_optional_datetime(raw["last_seen_at"], f"{context}.last_seen_at"),
        matched_refs=_strings(raw["matched_refs"], f"{context}.matched_refs"),
        confidence=_number(raw["confidence"], f"{context}.confidence"),
    )


def _history_items(value: object, context: str) -> tuple[HistoricalContextItem, ...]:
    return tuple(
        _history_item(item, f"{context}[{index}]")
        for index, item in enumerate(_array(value, context))
    )


def _history_bundle(value: object, context: str) -> HistoricalContextBundle:
    raw = _object(
        value,
        {
            "bundle_id",
            "scope",
            "origin_runtime_id",
            "episodes",
            "stable_facts",
            "relationship_events",
            "pattern_summaries",
            "source_refs",
            "provider_trace",
        },
        context,
    )
    return HistoricalContextBundle(
        bundle_id=_string(raw["bundle_id"], f"{context}.bundle_id"),
        scope=_scope(raw["scope"], f"{context}.scope"),
        origin_runtime_id=_string(raw["origin_runtime_id"], f"{context}.origin_runtime_id"),
        episodes=_history_items(raw["episodes"], f"{context}.episodes"),
        stable_facts=_history_items(raw["stable_facts"], f"{context}.stable_facts"),
        relationship_events=_history_items(
            raw["relationship_events"], f"{context}.relationship_events"
        ),
        pattern_summaries=tuple(
            _pattern_summary(item, f"{context}.pattern_summaries[{index}]")
            for index, item in enumerate(
                _array(raw["pattern_summaries"], f"{context}.pattern_summaries")
            )
        ),
        source_refs=_strings(raw["source_refs"], f"{context}.source_refs"),
        provider_trace=_string(raw["provider_trace"], f"{context}.provider_trace"),
    )


def _simulation_event(value: object, context: str) -> SimulationEvent:
    raw = _object(
        value,
        {"event_id", "at_offset", "evidence", "historical_context", "expected_path"},
        context,
    )
    history = raw["historical_context"]
    return SimulationEvent(
        event_id=_string(raw["event_id"], f"{context}.event_id"),
        at_offset=_duration(raw["at_offset"], f"{context}.at_offset"),
        evidence=tuple(
            _evidence(item, f"{context}.evidence[{index}]")
            for index, item in enumerate(_array(raw["evidence"], f"{context}.evidence"))
        ),
        historical_context=(
            None if history is None else _history_bundle(history, f"{context}.historical_context")
        ),
        expected_path=_string(raw["expected_path"], f"{context}.expected_path"),
    )


def _observation(value: object, context: str) -> Observation:
    raw = _object(
        value,
        {
            "id",
            "interaction_id",
            "scope",
            "type",
            "key",
            "value",
            "confidence",
            "observed_at",
            "evidence_refs",
            "origin_runtime_id",
            "sync",
        },
        context,
    )
    return Observation(
        id=_string(raw["id"], f"{context}.id"),
        interaction_id=_string(raw["interaction_id"], f"{context}.interaction_id"),
        scope=_scope(raw["scope"], f"{context}.scope"),
        type=_string(raw["type"], f"{context}.type"),
        key=_string(raw["key"], f"{context}.key"),
        value=raw["value"],
        confidence=_number(raw["confidence"], f"{context}.confidence"),
        observed_at=_datetime(raw["observed_at"], f"{context}.observed_at"),
        evidence_refs=_strings(raw["evidence_refs"], f"{context}.evidence_refs"),
        origin_runtime_id=_string(raw["origin_runtime_id"], f"{context}.origin_runtime_id"),
        sync=_sync(raw["sync"], f"{context}.sync"),
    )


def _interaction(value: object, context: str) -> Interaction:
    raw = _object(
        value,
        {
            "interaction_id",
            "scope",
            "channel",
            "session_id",
            "turn_id",
            "started_at",
            "committed_at",
            "status",
        },
        context,
    )
    try:
        status = InteractionStatus(_string(raw["status"], f"{context}.status"))
    except ValueError as error:
        raise ValueError(f"{context}.status enum value is invalid") from error
    return Interaction(
        interaction_id=_string(raw["interaction_id"], f"{context}.interaction_id"),
        scope=_scope(raw["scope"], f"{context}.scope"),
        channel=_string(raw["channel"], f"{context}.channel"),
        session_id=_string(raw["session_id"], f"{context}.session_id"),
        turn_id=_string(raw["turn_id"], f"{context}.turn_id"),
        started_at=_datetime(raw["started_at"], f"{context}.started_at"),
        committed_at=_optional_datetime(raw["committed_at"], f"{context}.committed_at"),
        status=status,
    )


def _runtime_state(value: object, context: str) -> RuntimeState:
    raw = _object(
        value,
        {
            "state_id",
            "scope",
            "dimension",
            "value",
            "status",
            "valid_from",
            "valid_until",
            "relevant_until",
            "last_observed_at",
            "evidence_refs",
            "transition_refs",
            "updated_at",
            "origin_runtime_id",
            "version",
            "sync",
        },
        context,
    )
    return RuntimeState(
        state_id=_string(raw["state_id"], f"{context}.state_id"),
        scope=_scope(raw["scope"], f"{context}.scope"),
        dimension=_string(raw["dimension"], f"{context}.dimension"),
        value=raw["value"],
        status=_string(raw["status"], f"{context}.status"),
        valid_from=_datetime(raw["valid_from"], f"{context}.valid_from"),
        valid_until=_optional_datetime(raw["valid_until"], f"{context}.valid_until"),
        relevant_until=_optional_datetime(raw["relevant_until"], f"{context}.relevant_until"),
        last_observed_at=_datetime(raw["last_observed_at"], f"{context}.last_observed_at"),
        evidence_refs=_strings(raw["evidence_refs"], f"{context}.evidence_refs"),
        transition_refs=_strings(raw["transition_refs"], f"{context}.transition_refs"),
        updated_at=_datetime(raw["updated_at"], f"{context}.updated_at"),
        origin_runtime_id=_string(raw["origin_runtime_id"], f"{context}.origin_runtime_id"),
        version=_integer(raw["version"], f"{context}.version"),
        sync=_sync(raw["sync"], f"{context}.sync"),
    )


def _state_transition(value: object, context: str) -> StateTransition:
    raw = _object(
        value,
        {
            "transition_id",
            "scope",
            "origin_runtime_id",
            "intent_id",
            "from_state",
            "to_state",
            "committed_at",
            "sync",
        },
        context,
    )
    return StateTransition(
        transition_id=_string(raw["transition_id"], f"{context}.transition_id"),
        scope=_scope(raw["scope"], f"{context}.scope"),
        origin_runtime_id=_string(raw["origin_runtime_id"], f"{context}.origin_runtime_id"),
        intent_id=_string(raw["intent_id"], f"{context}.intent_id"),
        from_state=_runtime_state(raw["from_state"], f"{context}.from_state"),
        to_state=_runtime_state(raw["to_state"], f"{context}.to_state"),
        committed_at=_datetime(raw["committed_at"], f"{context}.committed_at"),
        sync=_sync(raw["sync"], f"{context}.sync"),
    )


def _intent(value: object, context: str) -> Intent:
    raw = _object(
        value,
        {
            "intent_id",
            "scope",
            "origin_runtime_id",
            "kind",
            "strength",
            "earliest_at",
            "due_at",
            "expires_at",
            "reconsideration_policy",
            "cause_refs",
            "state_refs",
            "status",
            "sync",
        },
        context,
    )
    try:
        reconsideration = ReconsiderationPolicy(
            _string(raw["reconsideration_policy"], f"{context}.reconsideration_policy")
        )
        status = IntentStatus(_string(raw["status"], f"{context}.status"))
    except ValueError as error:
        raise ValueError(f"{context} enum value is invalid") from error
    return Intent(
        intent_id=_string(raw["intent_id"], f"{context}.intent_id"),
        scope=_scope(raw["scope"], f"{context}.scope"),
        origin_runtime_id=_string(raw["origin_runtime_id"], f"{context}.origin_runtime_id"),
        kind=_string(raw["kind"], f"{context}.kind"),
        strength=_number(raw["strength"], f"{context}.strength"),
        earliest_at=_optional_datetime(raw["earliest_at"], f"{context}.earliest_at"),
        due_at=_optional_datetime(raw["due_at"], f"{context}.due_at"),
        expires_at=_optional_datetime(raw["expires_at"], f"{context}.expires_at"),
        reconsideration_policy=reconsideration,
        cause_refs=_strings(raw["cause_refs"], f"{context}.cause_refs"),
        state_refs=_strings(raw["state_refs"], f"{context}.state_refs"),
        status=status,
        sync=_sync(raw["sync"], f"{context}.sync"),
    )


def _intent_transition(value: object, context: str) -> IntentTransition:
    raw = _object(
        value,
        {
            "transition_id",
            "scope",
            "origin_runtime_id",
            "intent_id",
            "from_status",
            "to_status",
            "reason_codes",
            "occurred_at",
            "version",
            "sync",
        },
        context,
    )
    try:
        from_status = IntentStatus(_string(raw["from_status"], f"{context}.from_status"))
        to_status = IntentStatus(_string(raw["to_status"], f"{context}.to_status"))
    except ValueError as error:
        raise ValueError(f"{context} status enum value is invalid") from error
    return IntentTransition(
        transition_id=_string(raw["transition_id"], f"{context}.transition_id"),
        scope=_scope(raw["scope"], f"{context}.scope"),
        origin_runtime_id=_string(raw["origin_runtime_id"], f"{context}.origin_runtime_id"),
        intent_id=_string(raw["intent_id"], f"{context}.intent_id"),
        from_status=from_status,
        to_status=to_status,
        reason_codes=_strings(raw["reason_codes"], f"{context}.reason_codes"),
        occurred_at=_datetime(raw["occurred_at"], f"{context}.occurred_at"),
        version=_integer(raw["version"], f"{context}.version"),
        sync=_sync(raw["sync"], f"{context}.sync"),
    )


def _checkpoint_record(value: object, context: str) -> TurnCheckpoint:
    raw = _object(
        value,
        {
            "checkpoint_id",
            "interaction_id",
            "scope",
            "origin_runtime_id",
            "stage",
            "base_state_version",
            "projection_ref",
            "action_id",
            "delivery_status",
            "checkpointed_at",
            "sync",
        },
        context,
    )
    try:
        stage = TurnStage(_string(raw["stage"], f"{context}.stage"))
        delivery_status = DeliveryStatus(
            _string(raw["delivery_status"], f"{context}.delivery_status")
        )
    except ValueError as error:
        raise ValueError(f"{context} enum value is invalid") from error
    return TurnCheckpoint(
        checkpoint_id=_string(raw["checkpoint_id"], f"{context}.checkpoint_id"),
        interaction_id=_string(raw["interaction_id"], f"{context}.interaction_id"),
        scope=_scope(raw["scope"], f"{context}.scope"),
        origin_runtime_id=_string(raw["origin_runtime_id"], f"{context}.origin_runtime_id"),
        stage=stage,
        base_state_version=_integer(raw["base_state_version"], f"{context}.base_state_version"),
        projection_ref=_string(raw["projection_ref"], f"{context}.projection_ref"),
        action_id=_optional_string(raw["action_id"], f"{context}.action_id"),
        delivery_status=delivery_status,
        checkpointed_at=_datetime(raw["checkpointed_at"], f"{context}.checkpointed_at"),
        sync=_sync(raw["sync"], f"{context}.sync"),
    )


def _load_json_object(path: Path, context: str) -> Mapping[str, object]:
    try:
        data = path.read_bytes()
    except OSError as error:
        raise ValueError(f"{context} must be valid UTF-8 JSON") from error
    return _decode_json_object_bytes(data, context)


def _decode_json_object_bytes(data: bytes, context: str) -> Mapping[str, object]:
    try:
        raw = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError(f"{context} must be valid UTF-8 JSON") from error
    if not isinstance(raw, Mapping):
        raise ValueError(f"{context} schema drift")
    return cast(Mapping[str, object], raw)


def decode_horizon_template_bytes(data: bytes) -> HorizonTemplate:
    """Strictly decode one already-bound UTF-8 horizon byte buffer."""
    raw = _object(
        _decode_json_object_bytes(data, "horizon fixture"),
        {
            "certification_id",
            "persona_version",
            "horizon_days",
            "started_at",
            "events",
            "checkpoint_interval",
        },
        "horizon fixture",
    )
    horizon_days = _integer(raw["horizon_days"], "horizon_days")
    if horizon_days not in (30, 90):
        raise ValueError("horizon_days must be exactly 30 or 90")
    return HorizonTemplate(
        certification_id=_string(raw["certification_id"], "certification_id"),
        persona_version=_string(raw["persona_version"], "persona_version"),
        horizon_days=cast(Literal[30, 90], horizon_days),
        started_at=_datetime(raw["started_at"], "started_at"),
        events=tuple(
            _simulation_event(item, f"events[{index}]")
            for index, item in enumerate(_array(raw["events"], "events"))
        ),
        checkpoint_interval=_duration(raw["checkpoint_interval"], "checkpoint_interval"),
    )


def load_horizon_template(path: Path) -> HorizonTemplate:
    """Read and strictly decode one immutable horizon template once."""
    try:
        data = path.read_bytes()
    except OSError as error:
        raise ValueError("horizon fixture must be valid UTF-8 JSON") from error
    return decode_horizon_template_bytes(data)


def load_model_swap_fixture(path: Path) -> ModelSwapFixture:
    """Decode the exact scripted one-call expression-provider fixture."""
    raw = _object(
        _load_json_object(path, "model-swap fixture"),
        {"fixture_id", "responses"},
        "model-swap fixture",
    )
    responses = _strings(raw["responses"], "model-swap responses")
    if len(responses) != 1:
        raise ValueError("model-swap responses must contain exactly one accepted prose value")
    return ModelSwapFixture(
        fixture_id=_string(raw["fixture_id"], "model-swap fixture_id"),
        responses=responses,
    )


def load_history_fixture(path: Path) -> HistoryFixture:
    """Decode the G27 item, summary association, and fixed retrieval count."""
    raw = _object(
        _load_json_object(path, "history fixture"),
        {"fixture_id", "retrieval_count", "bundle"},
        "history fixture",
    )
    fixture = HistoryFixture(
        fixture_id=_string(raw["fixture_id"], "history fixture_id"),
        retrieval_count=_integer(raw["retrieval_count"], "history retrieval_count"),
        bundle=_history_bundle(raw["bundle"], "history bundle"),
    )
    if fixture.retrieval_count != 3:
        raise ValueError("history retrieval_count must be exactly three")
    item_ids = {
        item.item_id
        for item in (
            fixture.bundle.episodes
            + fixture.bundle.stable_facts
            + fixture.bundle.relationship_events
        )
    }
    if not item_ids or any(
        not set(summary.matched_refs) <= item_ids for summary in fixture.bundle.pattern_summaries
    ):
        raise ValueError("history summary matched_refs must identify fixture items")
    return fixture


def load_restart_fixture(path: Path) -> RestartFixture:
    """Decode full G12 durable-plane seed records without receipt or Memory durability."""
    raw = _object(
        _load_json_object(path, "restart fixture"),
        {
            "fixture_id",
            "durable_store_modes",
            "state_definitions",
            "interactions",
            "evidence",
            "expected_observation",
            "states",
            "state_transitions",
            "intent_history",
            "intent_transitions",
            "checkpoint",
            "historical_context",
        },
        "restart fixture",
    )
    modes_raw = _object(
        raw["durable_store_modes"],
        {"facts", "state", "intents", "checkpoints"},
        "restart durable_store_modes",
    )
    modes = DurableStoreModes(
        _string(modes_raw["facts"], "restart facts mode"),
        _string(modes_raw["state"], "restart state mode"),
        _string(modes_raw["intents"], "restart intents mode"),
        _string(modes_raw["checkpoints"], "restart checkpoints mode"),
    )
    if modes != DurableStoreModes("sqlite", "sqlite", "sqlite", "sqlite"):
        raise ValueError("restart durable store modes must all be sqlite")
    return RestartFixture(
        fixture_id=_string(raw["fixture_id"], "restart fixture_id"),
        durable_store_modes=modes,
        state_definitions=tuple(
            _state_definition(item, f"restart state_definitions[{index}]")
            for index, item in enumerate(
                _array(raw["state_definitions"], "restart state_definitions")
            )
        ),
        interactions=tuple(
            _interaction(item, f"restart interactions[{index}]")
            for index, item in enumerate(_array(raw["interactions"], "restart interactions"))
        ),
        evidence=tuple(
            _evidence(item, f"restart evidence[{index}]")
            for index, item in enumerate(_array(raw["evidence"], "restart evidence"))
        ),
        expected_observation=_observation(
            raw["expected_observation"], "restart expected_observation"
        ),
        states=tuple(
            _runtime_state(item, f"restart states[{index}]")
            for index, item in enumerate(_array(raw["states"], "restart states"))
        ),
        state_transitions=tuple(
            _state_transition(item, f"restart state_transitions[{index}]")
            for index, item in enumerate(
                _array(raw["state_transitions"], "restart state_transitions")
            )
        ),
        intent_history=tuple(
            _intent(item, f"restart intent_history[{index}]")
            for index, item in enumerate(_array(raw["intent_history"], "restart intent_history"))
        ),
        intent_transitions=tuple(
            _intent_transition(item, f"restart intent_transitions[{index}]")
            for index, item in enumerate(
                _array(raw["intent_transitions"], "restart intent_transitions")
            )
        ),
        checkpoint=_checkpoint_record(raw["checkpoint"], "restart checkpoint"),
        historical_context=_history_bundle(raw["historical_context"], "restart historical_context"),
    )
