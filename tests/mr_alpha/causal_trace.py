"""MR-ALPHA-AS1: Causal Trace — AS-03.

Captures the per-turn causal chain (Evidence → Appraisal → Homeostasis →
SlowWrite → Consumer) so the scorer can compute accumulated_delta and
prove provenance.  Entries are append-only and frozen.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Literal, Sequence

__all__ = [
    "CausalTrace",
    "CausalTraceEntry",
    "CausalStepKind",
    "CausalEvidenceRef",
]

# ── Step kinds ────────────────────────────────────────────────────────────────


class CausalStepKind(StrEnum):
    """The canonical causal chain steps recorded per turn."""

    # Input boundary
    EVIDENCE_INGESTED = "evidence_ingested"       # Evidence entered the turn
    EVIDENCE_DEFERRED = "evidence_deferred"       # C9-W1B deferred path
    EVIDENCE_REPLAYED = "evidence_replayed"        # Idempotent replay from FDO

    # Appraisal
    APPRAISAL_FIRED = "appraisal_fired"           # SemanticEventCandidate produced
    APPRAISAL_ACCEPTED = "appraisal_accepted"     # Passed through appraisal router
    APPRAISAL_REJECTED = "appraisal_rejected"     # Dropped by appraisal router

    # Homeostasis gate
    HOMEOSTASIS_CANDIDATE = "homeostasis_candidate"   # HomeostasisDecision created
    HOMEOSTASIS_SLOW_ACCEPT = "homeostasis_slow_accept"  # SLOW_ACCEPT disposition
    HOMEOSTASIS_FAST_ONLY = "homeostasis_fast_only"   # FAST_ONLY disposition
    HOMEOSTASIS_REJECTED = "homeostasis_rejected"    # REJECTED disposition

    # Slow accumulation
    SLOW_WRITE_FLUSHED = "slow_write_flushed"       # SlowPlasticityWriter.flush() called
    SLOW_WRITE_DISABLED = "slow_write_disabled"     # WRITE_OFF ablation arm

    # Consumer
    CONSUMER_INVOKED = "consumer_invoked"           # IntentEnginePort.evaluate() called
    CONSUMER_READ_SLOW = "consumer_read_slow"        # Consumer read agent.slow.* dimensions
    CONSUMER_DISABLED = "consumer_disabled"          # CONSUME_OFF ablation arm

    # Orchestrator lifecycle
    TURN_BEGAN = "turn_began"
    TURN_COMMITTED = "turn_committed"
    TURN_ABORTED = "turn_aborted"
    TRAJECTORY_COMPLETED = "trajectory_completed"


# ── Evidence ref ─────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class CausalEvidenceRef:
    """Minimal reference to a typed evidence object stored in the orchestrator."""

    evidence_id: str
    typed_event_kind: str | None  # from SemanticEventCandidate.kind; None for non-semantic
    source_type: str
    scope_domain: str


# ── Trace entry ──────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class CausalTraceEntry:
    """One immutable causal-step entry for one turn."""

    # Identity
    interaction_id: str
    turn_index: int
    turn_id: str
    step: CausalStepKind
    at: datetime

    # Causal provenance
    evidence_refs: tuple[str, ...]  # upstream evidence IDs this step depended on
    causal_chain: tuple[str, ...]   # ordered step IDs forming the causal path to here

    # Semantic payload
    payload: object  # step-specific data (e.g. candidate JSON, accumulated value)

    def __post_init__(self) -> None:
        if self.turn_index < 0:
            raise ValueError("turn_index must be non-negative")
        if not self.causal_chain:
            raise ValueError("causal_chain must be non-empty")


# ── CausalTrace ──────────────────────────────────────────────────────────────


class CausalTrace:
    """Append-only causal trace accumulated over the full trajectory.

    Thread-safe for single-threaded harness use.
    """

    def __init__(self, trajectory_id: str) -> None:
        self._trajectory_id = trajectory_id
        self._entries: list[CausalTraceEntry] = []
        self._step_counter = 0  # monotic counter for causal_chain ordering

    def record(
        self,
        interaction_id: str,
        turn_index: int,
        turn_id: str,
        step: CausalStepKind,
        *,
        evidence_refs: Sequence[str] = (),
        payload: object = None,
        at: datetime,
    ) -> None:
        self._step_counter += 1
        # Build causal chain from previous entries in this turn
        prior_in_turn = tuple(
            e.causal_chain[-1]
            for e in self._entries
            if e.interaction_id == interaction_id
        )
        chain_tail = prior_in_turn[-1] if prior_in_turn else ""
        causal_chain = (chain_tail, f"s{self._step_counter}") if chain_tail else (f"s{self._step_counter}",)
        entry = CausalTraceEntry(
            interaction_id=interaction_id,
            turn_index=turn_index,
            turn_id=turn_id,
            step=step,
            at=at,
            evidence_refs=tuple(evidence_refs),
            causal_chain=causal_chain,
            payload=payload,
        )
        self._entries.append(entry)

    def entries(self, interaction_id: str | None = None) -> tuple[CausalTraceEntry, ...]:
        """Return all entries, optionally filtered by interaction_id."""
        if interaction_id is None:
            return tuple(self._entries)
        return tuple(e for e in self._entries if e.interaction_id == interaction_id)

    @property
    def trajectory_id(self) -> str:
        return self._trajectory_id

    def step_count(self) -> int:
        return self._step_counter

    def summary(self) -> dict[str, int]:
        """Count entries per step kind — useful for scorer."""
        counts: dict[str, int] = {}
        for e in self._entries:
            counts[e.step.value] = counts.get(e.step.value, 0) + 1
        return counts
