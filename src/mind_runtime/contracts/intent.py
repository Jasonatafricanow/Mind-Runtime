"""Durable, reconsiderable cognitive Intent contracts (ADR-0004)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from mind_runtime.contracts.common import (
    SyncFields,
    require_aware_utc,
    require_non_empty,
    validate_sync_fields,
)
from mind_runtime.contracts.scope import Scope


class IntentStatus(StrEnum):
    """Lifecycle state of a cognitive Intent; terminal history is immutable."""

    CANDIDATE = "candidate"
    DEFERRED = "deferred"
    ALLOWED = "allowed"
    BLOCKED = "blocked"
    EXPIRED = "expired"
    COMPLETED = "completed"
    SUPERSEDED = "superseded"


class ReconsiderationPolicy(StrEnum):
    """The condition that may wake an Intent for a new policy decision."""

    ON_DUE = "on_due"
    ON_CONTEXT_CHANGE = "on_context_change"
    MANUAL = "manual"
    NEVER = "never"


@dataclass(frozen=True, slots=True)
class Intent:
    """A versioned candidate desire; never an action permission."""

    intent_id: str
    scope: Scope
    origin_runtime_id: str
    kind: str
    strength: float
    earliest_at: datetime | None
    due_at: datetime | None
    expires_at: datetime | None
    reconsideration_policy: ReconsiderationPolicy
    cause_refs: tuple[str, ...]
    state_refs: tuple[str, ...]
    status: IntentStatus
    sync: SyncFields
    surface_use: IntentScoreTrace | None = None

    def __post_init__(self) -> None:
        require_non_empty(self.intent_id, "intent_id")
        require_non_empty(self.origin_runtime_id, "origin_runtime_id")
        require_non_empty(self.kind, "kind")
        if isinstance(self.strength, bool) or not 0 <= self.strength <= 1:
            raise ValueError("strength must be in [0, 1]")
        if not isinstance(self.reconsideration_policy, ReconsiderationPolicy):
            raise ValueError("reconsideration_policy must be a ReconsiderationPolicy")
        if not isinstance(self.status, IntentStatus):
            raise ValueError("status must be an IntentStatus")
        schedule = tuple(
            value for value in (self.earliest_at, self.due_at, self.expires_at) if value is not None
        )
        for value in schedule:
            require_aware_utc(value, "intent schedule timestamps")
        if schedule != tuple(sorted(schedule)):
            raise ValueError("intent schedule must be earliest_at <= due_at <= expires_at")
        for ref in self.cause_refs:
            require_non_empty(ref, "cause_refs entries")
        for ref in self.state_refs:
            require_non_empty(ref, "state_refs entries")
        validate_sync_fields(
            self.sync,
            scope=self.scope,
            origin_runtime_id=self.origin_runtime_id,
            object_id=self.intent_id,
        )
        if self.surface_use is not None:
            if (
                not isinstance(self.surface_use, IntentScoreTrace)
                or not self.surface_use.admitted
                or self.surface_use.intent_id != self.intent_id
                or self.surface_use.scope != self.scope
                or self.surface_use.surface_controls_ref is None
            ):
                raise ValueError("Intent Surface-use evidence must match admitted Intent")

    def sync_fields(self) -> SyncFields:
        """Return the Intent synchronization identity."""

        return self.sync


@dataclass(frozen=True, slots=True)
class IntentScoreContribution:
    """One inspectable source contribution to an Intent score."""

    source_kind: str
    source_ref: str
    amount: float

    def __post_init__(self) -> None:
        require_non_empty(self.source_kind, "source_kind")
        require_non_empty(self.source_ref, "source_ref")
        if isinstance(self.amount, bool) or not isinstance(self.amount, (int, float)):
            raise ValueError("amount must be numeric")


@dataclass(frozen=True, slots=True)
class IntentScoreTrace:
    """Immutable explanation for one admitted or rejected Intent rule."""

    trace_id: str
    scope: Scope
    rule_id: str
    intent_id: str
    contributions: tuple[IntentScoreContribution, ...]
    unclamped_score: float
    final_strength: float
    admitted: bool
    reason_codes: tuple[str, ...]
    created_at: datetime
    surface_controls_ref: str | None = None
    surface_dependency_digest: str | None = None
    overlap_validation_ref: str | None = None
    surface_weights: tuple[tuple[str, float], ...] = ()
    surface_recipe_ref: str | None = None
    ruleset_ref: str | None = None

    def __post_init__(self) -> None:
        for value, name in (
            (self.trace_id, "trace_id"),
            (self.rule_id, "rule_id"),
            (self.intent_id, "intent_id"),
        ):
            require_non_empty(value, name)
        if isinstance(self.unclamped_score, bool) or not isinstance(
            self.unclamped_score, (int, float)
        ):
            raise ValueError("unclamped_score must be numeric")
        if isinstance(self.final_strength, bool) or not 0 <= self.final_strength <= 1:
            raise ValueError("final_strength must be in [0, 1]")
        if not isinstance(self.admitted, bool):
            raise ValueError("admitted must be a bool")
        for code in self.reason_codes:
            require_non_empty(code, "reason_codes entries")
        require_aware_utc(self.created_at, "created_at")
        if self.surface_controls_ref is not None:
            require_non_empty(self.surface_controls_ref, "surface_controls_ref")
        if self.surface_dependency_digest is not None:
            require_non_empty(self.surface_dependency_digest, "surface_dependency_digest")
        if self.overlap_validation_ref is not None:
            require_non_empty(self.overlap_validation_ref, "overlap_validation_ref")


@dataclass(frozen=True, slots=True)
class IntentEngineResult:
    """Ordered admitted candidates plus a trace for every evaluated rule."""

    candidates: tuple[Intent, ...]
    traces: tuple[IntentScoreTrace, ...]

    def __post_init__(self) -> None:
        candidate_ids: set[str] = set()
        for candidate in self.candidates:
            if candidate.intent_id in candidate_ids:
                raise ValueError("candidate intent ids must be unique")
            candidate_ids.add(candidate.intent_id)
        traces_by_intent = {trace.intent_id: trace for trace in self.traces}
        if not candidate_ids <= traces_by_intent.keys():
            raise ValueError("every candidate must have an intent score trace")
        for candidate in self.candidates:
            trace = traces_by_intent[candidate.intent_id]
            if not trace.admitted:
                raise ValueError("candidate intent score trace must be admitted")
            if trace.scope != candidate.scope:
                raise ValueError("candidate and intent score trace scope must match")
            if trace.final_strength != candidate.strength:
                raise ValueError("candidate and intent score trace strength must match")


@dataclass(frozen=True, slots=True)
class IntentTransition:
    """One append-only cognitive Intent lifecycle transition."""

    transition_id: str
    scope: Scope
    origin_runtime_id: str
    intent_id: str
    from_status: IntentStatus
    to_status: IntentStatus
    reason_codes: tuple[str, ...]
    occurred_at: datetime
    version: int
    sync: SyncFields

    def __post_init__(self) -> None:
        require_non_empty(self.transition_id, "transition_id")
        require_non_empty(self.origin_runtime_id, "origin_runtime_id")
        require_non_empty(self.intent_id, "intent_id")
        if not isinstance(self.from_status, IntentStatus) or not isinstance(
            self.to_status, IntentStatus
        ):
            raise ValueError("intent transition statuses must be IntentStatus")
        if self.from_status is self.to_status:
            raise ValueError("intent transition statuses must differ")
        if isinstance(self.version, bool) or self.version < 2:
            raise ValueError("intent transition version must be at least 2")
        for code in self.reason_codes:
            require_non_empty(code, "reason_codes entries")
        require_aware_utc(self.occurred_at, "occurred_at")
        validate_sync_fields(
            self.sync,
            scope=self.scope,
            origin_runtime_id=self.origin_runtime_id,
            object_id=self.transition_id,
        )
        if self.sync.version != self.version:
            raise ValueError("sync.version must match intent transition version")


@dataclass(frozen=True, slots=True)
class IntentWake:
    """A scheduler request to reconsider one due Intent, never execute it."""

    wake_id: str
    scope: Scope
    intent_id: str
    reason: str
    woken_at: datetime
    intent_version: int

    def __post_init__(self) -> None:
        require_non_empty(self.wake_id, "wake_id")
        require_non_empty(self.intent_id, "intent_id")
        require_non_empty(self.reason, "reason")
        if isinstance(self.intent_version, bool) or self.intent_version < 1:
            raise ValueError("intent_version must be at least 1")
        require_aware_utc(self.woken_at, "woken_at")
