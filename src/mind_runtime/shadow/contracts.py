"""Shared contracts for the shadow execution slice.

Exports:
  ShadowRecordStore     — Protocol for audit persistence
  InMemoryShadowRecordStore — in-memory reference implementation
  ShadowSnapshot        — immutable audit snapshot of shadow cognition
  ShadowRunRecord      — durable audit record for one shadow run
  ShadowRunResult      — result returned to caller (zero authority)
  ShadowStatus         — StrEnum: COMPLETED / FAILED / ABORTED
  ShadowModeDisabled   — raised when execute() called without shadow enabled
  ShadowRunError       — unexpected error during shadow run
  ShadowPersistenceError — audit persistence failed (after cognitive discard)
  HostOutcome          — audit input from Host (action_taken, type, ref)
  ComparisonResult     — deterministic comparison result (no LLM judge)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Protocol

from mind_runtime.contracts import (
    ActionReceipt,
    DecisionContext,
    ExpressionOutcome,
    Intent,
    Observation,
    ProjectedMindState,
    Situation,
)


# ── Status enum ────────────────────────────────────────────────────────────────


class ShadowStatus(StrEnum):
    """Status of a shadow run lifecycle."""

    COMPLETED = "completed"  # Shadow cognition safely exited cognitive authority.
    FAILED = "failed"  # Unexpected exception; was forced to abort.
    ABORTED = "aborted"  # Deliberate abort (e.g. guard block, comparison failure).


# ── Persistence seam ──────────────────────────────────────────────────────────


class ShadowRecordStore(Protocol):
    """Audit persistence port for shadow run records.

    Consumers implement this to persist ShadowRunRecords durably.
    The store is responsible for idempotency (same shadow_run_id = same record).
    """

    def save(self, record: ShadowRunRecord) -> None:
        """Persist a shadow run record.

        Implementations MUST be idempotent: saving the same record twice
        (same shadow_run_id) must not raise or create duplicates.
        """
        ...

    def get(self, shadow_run_id: str) -> ShadowRunRecord | None:
        """Retrieve a record by shadow_run_id, or None if not found."""
        ...

    def all(self) -> list[ShadowRunRecord]:
        """Return all records."""
        ...


class InMemoryShadowRecordStore:
    """In-memory store for tests and as a reference implementation."""

    def __init__(self) -> None:
        self._records: dict[str, ShadowRunRecord] = {}

    def save(self, record: ShadowRunRecord) -> None:
        self._records[record.shadow_run_id] = record

    def get(self, shadow_run_id: str) -> ShadowRunRecord | None:
        return self._records.get(shadow_run_id)

    def all(self) -> list[ShadowRunRecord]:
        return list(self._records.values())


# ── Snapshot types ────────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class ShadowSnapshot:
    """Immutable snapshot of shadow cognition state, captured before abort.

    This is audit-only data — it has zero cognitive authority and cannot
    be used to promote a projection or commit a turn.
    """

    interaction_id: str
    situation: Situation | None
    projected: ProjectedMindState | None
    intent: Intent | None
    expression_outcome: ExpressionOutcome | None
    action_receipt: ActionReceipt | None
    observations: tuple[Observation, ...]
    decision_context: DecisionContext | None
    captured_at: datetime


# ── Host-vs-MR comparison seam ─────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class HostOutcome:
    """Minimal input representing the Host's actual decision/action.

    This is an AUDIT INPUT only. The SafeShadowRunner never treats this
    as cognitive authority. Text is NOT copied by default — use stable
    refs / digests / categorical properties.
    """

    host_action_taken: bool
    host_action_type: str | None = None  # e.g. "text", "media", "defer", "ignore"
    host_expression_ref: str | None = None  # stable ref, not copied text


@dataclass(frozen=True, slots=True)
class ComparisonResult:
    """Deterministic categorical comparison between MR shadow and Host.

    No LLM judge, no semantic similarity, no "who is better" scoring.
    """

    comparable: bool = False  # True only when both sides have comparable data.
    action_presence_match: bool | None = None
    action_type_match: bool | None = None
    policy_divergence: bool | None = None


# ── ShadowRunRecord ───────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class ShadowRunRecord:
    """Durable audit record for one shadow run.

    This record has ZERO cognitive authority. It cannot be Evidence,
    Observation, Intent, or any committable projection type.

    shadow_run_id identity: bound to source interaction/event identity
    AND runtime semantic version/config identity. Not interaction_id alone.
    """

    shadow_run_id: str
    scope: str  # serialised Scope string for audit convenience
    source_interaction_id: str
    source_event_ref: str | None  # optional external event reference
    runtime_config_digest: str  # hash of runtime config that produced this run
    started_at: datetime
    completed_at: datetime
    status: ShadowStatus

    # MR shadow outcome (refs/summaries only — no deep cognitive copies)
    mr_situation_summary: str | None = None
    mr_intent_type: str | None = None
    mr_policy_decision: str | None = None
    mr_policy_reason_codes: tuple[str, ...] = ()
    mr_expression_ref: str | None = None  # stable ref, not copied text
    mr_would_send: bool | None = None

    # Host side (optional audit input — never copied text)
    host_outcome: HostOutcome | None = None

    # Comparison result
    comparison: ComparisonResult | None = None

    # Failure info
    failure_stage: str | None = None
    failure_reason: str | None = None

    # Audit metadata
    captured_snapshot: ShadowSnapshot | None = field(default=None, repr=False)
    # NOTE: captured_snapshot is NOT cognitive state. It is audit-only shadow data.
    # It MUST NOT be usable to reconstruct or promote a projection.


# ── Shadow run result (returned to caller — never a committable handle) ───────


@dataclass(frozen=True, slots=True)
class ShadowRunResult:
    """Result returned to the caller of SafeShadowRunner.

    This object has ZERO cognitive authority. The caller cannot use it to
    commit a turn, promote a projection, or write to canonical state.
    """

    shadow_run_id: str
    status: ShadowStatus
    snapshot: ShadowSnapshot | None
    comparison: ComparisonResult | None
    failure_reason: str | None

    @property
    def succeeded(self) -> bool:
        return self.status == ShadowStatus.COMPLETED


# ── exceptions ────────────────────────────────────────────────────────────────


class ShadowError(Exception):
    """Base exception for SafeShadowRunner errors."""

    pass


class ShadowModeDisabled(ShadowError):
    """Raised when shadow execution is called but shadow mode is disabled."""

    pass


class ShadowRunError(ShadowError):
    """Raised when the shadow run fails unexpectedly."""

    pass


class ShadowPersistenceError(ShadowError):
    """Raised when audit record persistence fails (after successful cognitive discard).

    The cognitive projection has already been safely discarded.
    This error indicates the audit trail is incomplete.
    """

    pass
