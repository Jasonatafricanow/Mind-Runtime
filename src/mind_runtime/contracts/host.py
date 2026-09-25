"""HI-1: Generic Host Integration Contract.

This module freezes the PUBLIC Host-facing product contract. The contract
is intentionally thin: an Agent Host (Hermes, OpenClaw, anything) sees
only "I had an interaction, please MR it" and never sees MR's internal
seams (AppraisalResultSourcePort, ResolvedAppraisal, Impulse,
DynamicsEngine, Memory admission, etc.).

Frozen surface (HI-1):
  * HostTurnRequest
  * HostTurnResult
  * HostCommitRequest
  * HostCommitReceipt
  * HostAbortRequest
  * HostAbortReceipt
  * HostInspectRequest
  * HostInspectResult
  * HostStatus (StrEnum: OK / DEGRADED / ABSTAINED / FAILED)
  * HostTurnStatus (StrEnum: BEGIN / PROCESSING / COMMITTED / ABORTED / FAILED)

The contract is a Host-facing surface only. It is NOT a substitute for
the production MR types. Internal types (DecisionContext, ExpressionOutcome,
ProjectedMindState, AssessmentTrace, etc.) are reachable ONLY through
`HostInspectResult` references, not through HostTurnResult fields.

Do NOT extend this module without re-running an independent contract
review.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum

from mind_runtime.contracts.common import require_non_empty
from mind_runtime.contracts.scope import Scope

# ---------------------------------------------------------------------------
# Status enums
# ---------------------------------------------------------------------------


class HostStatus(StrEnum):
    """Outcome category for a single Host operation.

    The Host must treat these as opaque categories; the production pipeline
    has finer-grained internals that are reachable only through inspect().
    """

    OK = "ok"
    DEGRADED = "degraded"
    ABSTAINED = "abstained"
    FAILED = "failed"
    # The Host replayed a turn that is already terminal (committed or
    # aborted). The adapter returns the previous terminal result without
    # re-entering the cognition pipeline. This is the Host-level
    # idempotency contract for network retries, crash recovery, and
    # at-least-once delivery.
    ALREADY_PROCESSED = "already_processed"


class HostTurnStatus(StrEnum):
    """Host-visible turn lifecycle status.

    Mirrors the production TurnState but exposes only what a Host needs to
    decide "can I commit / abort / inspect this turn?".
    """

    BEGIN = "begin"
    PROCESSING = "processing"
    COMMITTED = "committed"
    ABORTED = "aborted"
    FAILED = "failed"
    # The interaction_id is already terminal; no further lifecycle work.
    ALREADY_PROCESSED = "already_processed"


# ---------------------------------------------------------------------------
# Request types
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class HostTurnRequest:
    """PUBLIC. What a Host passes to begin a turn.

    Fields are deliberately narrow. A Host cannot supply:
      * numeric affect deltas
      * final affect values
      * shock / salience / urgency / timescale
      * persona mutation
      * memory authority results
      * appraisal results
    """

    interaction_id: str
    runtime_id: str
    scope: Scope
    occurred_at: datetime
    user_message: str
    channel: str = "default"
    session_id: str | None = None
    host_metadata: tuple[tuple[str, str], ...] = ()

    def __post_init__(self) -> None:
        require_non_empty(self.interaction_id, "interaction_id")
        require_non_empty(self.runtime_id, "runtime_id")
        require_non_empty(self.user_message, "user_message")
        require_non_empty(self.channel, "channel")
        if self.occurred_at.tzinfo is None or self.occurred_at.utcoffset() is None:
            raise ValueError("occurred_at must be aware (have tzinfo)")
        # session_id may be None (some Hosts do not have a session concept)
        if self.session_id is not None:
            require_non_empty(self.session_id, "session_id")


@dataclass(frozen=True, slots=True)
class HostCommitRequest:
    """PUBLIC. The Host's intent to commit a turn.

    The Host only identifies the turn. Authority, validation, and
    transactional semantics live in the production pipeline.
    """

    turn_id: str
    interaction_id: str

    def __post_init__(self) -> None:
        require_non_empty(self.turn_id, "turn_id")
        require_non_empty(self.interaction_id, "interaction_id")


@dataclass(frozen=True, slots=True)
class HostProviderProseRequest:
    """Host submits provider prose to MR Guard before external message send."""

    turn_id: str
    interaction_id: str
    prose: str

    def __post_init__(self) -> None:
        require_non_empty(self.turn_id, "turn_id")
        require_non_empty(self.interaction_id, "interaction_id")
        require_non_empty(self.prose, "prose")


@dataclass(frozen=True, slots=True)
class HostProviderProseResult:
    interaction_id: str
    status: HostStatus
    reason_codes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        require_non_empty(self.interaction_id, "interaction_id")
        if not isinstance(self.status, HostStatus):
            raise ValueError("status must be HostStatus")


@dataclass(frozen=True, slots=True)
class HostAbortRequest:
    """PUBLIC. The Host's intent to abort a turn.

    Abort is a Host-visible decision: the cognitive projection is
    discarded, but ingested facts remain durable (D5.3, G13b).
    """

    turn_id: str
    interaction_id: str
    reason: str = "host_abort"

    def __post_init__(self) -> None:
        require_non_empty(self.turn_id, "turn_id")
        require_non_empty(self.interaction_id, "interaction_id")
        require_non_empty(self.reason, "reason")


@dataclass(frozen=True, slots=True)
class HostInspectRequest:
    """PUBLIC. Read-only inspection of a turn's lifecycle.

    inspect() must never write, never queue, never trigger side effects.
    It is OW's correlation entry point.
    """

    interaction_id: str
    turn_id: str | None = None
    include_trace: bool = False
    include_decision_context: bool = True
    include_projection: bool = False

    def __post_init__(self) -> None:
        require_non_empty(self.interaction_id, "interaction_id")
        if self.turn_id is not None:
            require_non_empty(self.turn_id, "turn_id")


# ---------------------------------------------------------------------------
# Result / receipt types
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class HostDecisionContext:
    """PUBLIC. The bounded, Host-consumable context for a turn.

    This is the *usable* context a Host (Hermes) needs to compile the
    next reply LLM input. It is NOT an opaque reference. The fields
    are human-readable summaries, never numeric affect, never raw
    internal objects.

    Two separate concerns, two separate handles:
      - `bounded_context: HostDecisionContext` — the Host uses this
        to drive the reply LLM.
      - `decision_context_ref: str` — OW uses this for correlation
        with the trace.
      - `debug_ref: str` — explicit trace access; separate from OW.

    The Host must not parse these strings as schema. They are
    human-readable summaries, suitable for prompt injection.
    """

    intent_summary: str
    emotional_state: str
    situation_summary: str
    action_taken: str | None
    next_steps: str | None
    cognitive_meaning: str | None = None
    provider_envelope_text: str | None = None

    def __post_init__(self) -> None:
        require_non_empty(self.intent_summary, "intent_summary")
        require_non_empty(self.emotional_state, "emotional_state")
        require_non_empty(self.situation_summary, "situation_summary")
        if self.action_taken is not None:
            require_non_empty(self.action_taken, "action_taken")
        if self.next_steps is not None:
            require_non_empty(self.next_steps, "next_steps")
        if self.cognitive_meaning is not None:
            require_non_empty(self.cognitive_meaning, "cognitive_meaning")
        if self.provider_envelope_text is not None:
            require_non_empty(self.provider_envelope_text, "provider_envelope_text")


@dataclass(frozen=True, slots=True)
class HostTurnResult:
    """PUBLIC. What a Host gets back from begin_turn / run_turn.

    Field boundary:
      - `bounded_context`: usable context for the Host's next LLM input
      - `decision_context_ref`: OW correlation handle
      - `debug_ref`: explicit trace access

    Deliberately does NOT include numeric affect, AppraisalResult,
    ProjectedMindState, AssessmentTrace, or any other MR internal object.
    """

    turn_id: str
    interaction_id: str
    status: HostTurnStatus
    outcome: HostStatus
    bounded_context: HostDecisionContext | None
    decision_context_ref: str | None
    expression_ref: str | None
    debug_ref: str
    reason_codes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        require_non_empty(self.turn_id, "turn_id")
        require_non_empty(self.interaction_id, "interaction_id")
        if not isinstance(self.status, HostTurnStatus):
            raise ValueError("status must be a HostTurnStatus")
        if not isinstance(self.outcome, HostStatus):
            raise ValueError("outcome must be a HostStatus")
        require_non_empty(self.debug_ref, "debug_ref")
        for code in self.reason_codes:
            require_non_empty(code, "reason_codes entries")


@dataclass(frozen=True, slots=True)
class HostCommitReceipt:
    """PUBLIC. Receipt returned by commit_turn.

    A receipt is an authoritative answer to "did this turn durably
    commit?". It carries refs, not payloads.
    """

    turn_id: str
    interaction_id: str
    status: HostStatus
    committed_at: datetime
    projected_state_refs: tuple[str, ...] = ()
    commit_marker_ref: str | None = None
    reason_codes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        require_non_empty(self.turn_id, "turn_id")
        require_non_empty(self.interaction_id, "interaction_id")
        if not isinstance(self.status, HostStatus):
            raise ValueError("status must be a HostStatus")
        if self.committed_at.tzinfo is None or self.committed_at.utcoffset() is None:
            raise ValueError("committed_at must be aware (have tzinfo)")
        for ref in self.projected_state_refs:
            require_non_empty(ref, "projected_state_refs entries")
        if self.commit_marker_ref is not None:
            require_non_empty(self.commit_marker_ref, "commit_marker_ref")
        for code in self.reason_codes:
            require_non_empty(code, "reason_codes entries")


@dataclass(frozen=True, slots=True)
class HostAbortReceipt:
    """PUBLIC. Receipt returned by abort_turn.

    Abort preserves durable facts (G13b) but discards the cognitive
    projection. A Host gets a receipt describing the boundary.
    """

    turn_id: str
    interaction_id: str
    status: HostStatus
    aborted_at: datetime
    ingested_facts_retained: bool
    reason_codes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        require_non_empty(self.turn_id, "turn_id")
        require_non_empty(self.interaction_id, "interaction_id")
        if not isinstance(self.status, HostStatus):
            raise ValueError("status must be a HostStatus")
        if self.aborted_at.tzinfo is None or self.aborted_at.utcoffset() is None:
            raise ValueError("aborted_at must be aware (have tzinfo)")
        if not isinstance(self.ingested_facts_retained, bool):
            raise ValueError("ingested_facts_retained must be a bool")
        for code in self.reason_codes:
            require_non_empty(code, "reason_codes entries")


@dataclass(frozen=True, slots=True)
class HostInspectResult:
    """PUBLIC. Read-only inspection payload.

    Carries refs only; the actual payload is read through the production
    pipeline's read accessors. This keeps the Host contract stable.
    """

    interaction_id: str
    turn_id: str | None
    turn_status: HostTurnStatus
    decision_context_ref: str | None
    situation_ref: str | None
    expression_ref: str | None
    projection_ref: str | None
    trace: tuple[tuple[str, str, str | None, str], ...] = field(default_factory=tuple)
    recovery_decision: str | None = None

    def __post_init__(self) -> None:
        require_non_empty(self.interaction_id, "interaction_id")
        if self.turn_id is not None:
            require_non_empty(self.turn_id, "turn_id")
        if not isinstance(self.turn_status, HostTurnStatus):
            raise ValueError("turn_status must be a HostTurnStatus")
        for ref in (
            self.decision_context_ref,
            self.situation_ref,
            self.expression_ref,
            self.projection_ref,
        ):
            if ref is not None:
                require_non_empty(ref, "ref")


# ---------------------------------------------------------------------------
# Public visibility classification
# ---------------------------------------------------------------------------

# PUBLIC: HostTurnRequest, HostTurnResult, HostCommitRequest, HostCommitReceipt,
#         HostAbortRequest, HostAbortReceipt, HostInspectRequest, HostInspectResult,
#         HostStatus, HostTurnStatus, MindRuntimeHostPort
#
# INTERNAL MR SEAM (NOT exported through this contract, reachable only through
# the production pipeline and inspect() refs):
#   - AppraisalResultSourcePort
#   - ResolvedAppraisal
#   - AppraisalAffectDecision
#   - Impulse
#   - DynamicsEngine
#   - DecisionContext (the rich object; only `decision_context_ref` is PUBLIC)
#   - ExpressionOutcome (the rich object; only `expression_ref` is PUBLIC)
#   - ProjectedMindState (the rich object; only `projection_ref` is PUBLIC)
#   - AssessmentTrace (the rich object; only `decision_context_ref` is PUBLIC)
#   - Memory admission internals
#   - Semantic provider (composition-time only)
#
# DEBUG: HostInspectResult.trace and HostInspectResult.recovery_decision are
#        debug aids. They are public for OW correlation but never affect
#        production flow.
