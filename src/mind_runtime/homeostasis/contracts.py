"""State update policy contracts.

Ported from `6163b1f` (`w/c9-w1-closed-clean`) and adapted to the
C10-B-W production wiring. Per ADR-C10-A1 §1.1 / §2.1 / §2.3 / §3 / §7
and C10-B1-R3 §15.1, the Gate decides whether a candidate state delta
(produced by the dynamics engine after a single event / observation) is
allowed to:

  - displace Fast State (current_affect) directly
  - enter Slow-State candidacy (slow learned state, durable)
  - be damped, fast-only'd, or rejected

This module defines the minimal contract surface:
  - CandidateStateDelta: a per-dimension candidate value, with provenance
  - StateUpdateDecision: per-dimension verdict, with reason code
  - StateUpdatePolicy: the protocol that turns candidates into decisions

Numerical thresholds (salience, confidence, etc.) are NOT frozen here.
They are configuration-loaded via the policy implementation that
satisfies the protocol.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from mind_runtime.contracts.common import (
    require_aware_utc,
    require_non_empty,
)
from mind_runtime.contracts.scope import Scope


# ============================================================================
# Disposition / decision vocabulary
# ============================================================================


class StateUpdateDisposition(StrEnum):
    """Per-dimension verdict produced by the Homeostasis Gate.

    The five values are the full vocabulary required by ADR-C10-A1 §2.1.
    Other disposition names would either collapse Fast/Slow semantics
    (forbidden by §1.2) or add an implicit semantic that requires its
    own ADR.

    FAST_APPLY    — fast-state displacement is allowed (current_affect)
    FAST_ONLY     — only fast-state changes; candidate is recorded but
                    NOT promoted to slow state
    SLOW_ACCEPT   — slow-state mutation is allowed (with provenance);
                    the slow-plasticity writer (C10-B-W) may consume this
    SLOW_DAMP     — slow-state candidate is recorded but damped (not
                    promoted to canonical slow state)
    REJECT        — neither fast nor slow state changes; candidate is
                    recorded for audit only
    """

    FAST_APPLY = "fast_apply"
    FAST_ONLY = "fast_only"
    SLOW_ACCEPT = "slow_accept"
    SLOW_DAMP = "slow_damp"
    REJECT = "reject"


# ============================================================================
# CandidateStateDelta — per-dimension candidate value with provenance
# ============================================================================


@dataclass(frozen=True, slots=True)
class CandidateStateDelta:
    """One candidate state delta for one dimension.

    Produced by the dynamics engine after an event/observation has been
    applied. Captured BEFORE the canonical state is written so the
    Homeostasis Gate can decide its disposition.

    Per ADR-C10-A1 §3.1, the candidate MUST carry the full audit trail
    so a future debugger can answer "why did this slow value change?".
    """

    target_dimension: str
    proposed_value: float
    scope: Scope
    evidence_refs: tuple[str, ...]
    salience: float | None
    confidence: float
    source_event_ref: str | None
    observed_at: object  # datetime, but kept loose to avoid import cycle

    def __post_init__(self) -> None:
        require_non_empty(self.target_dimension, "target_dimension")
        # Per C10-SALIENCE-IMPL-R2: salience is float | None.
        # None = unavailable / not appraised. 0.0 = authoritative: negligible.
        # Both are valid; 0.0 < val < 1.0 also valid.
        if self.salience is not None:
            if isinstance(self.salience, bool) or not isinstance(self.salience, (int, float)):
                raise ValueError("salience must be a number")
            if not 0.0 <= float(self.salience) <= 1.0:
                raise ValueError("salience must be in [0, 1] or None")
        if isinstance(self.confidence, bool) or not isinstance(
            self.confidence, (int, float)
        ):
            raise ValueError("confidence must be a number")
        if not 0.0 <= float(self.confidence) <= 1.0:
            raise ValueError("confidence must be in [0, 1]")
        if not isinstance(self.scope, Scope):
            raise ValueError("scope must be a Scope")
        require_aware_utc(self.observed_at, "observed_at")
        # evidence_refs is required for any SLOW_* disposition (H6).
        # We do NOT enforce this here — the Gate policy decides whether
        # the absence of evidence_refs justifies REJECT.


# ============================================================================
# StateUpdateDecision — per-dimension verdict with reason code
# ============================================================================


@dataclass(frozen=True, slots=True)
class StateUpdateDecision:
    """Per-dimension verdict for a single CandidateStateDelta.

    Carries the full audit trail per ADR-C10-A1 §3.1 and §7-H7:
      - candidate (the input that was decided)
      - prior state value (what the state was before)
      - decision (the disposition)
      - reason code (a short string for trace / debug)
      - timestamp
    """

    candidate: CandidateStateDelta
    prior_value: float | None
    decision: StateUpdateDisposition
    reason_code: str
    decided_at: object  # datetime

    def __post_init__(self) -> None:
        if not isinstance(self.candidate, CandidateStateDelta):
            raise ValueError("candidate must be a CandidateStateDelta")
        if not isinstance(self.decision, StateUpdateDisposition):
            raise ValueError("decision must be a StateUpdateDisposition")
        require_non_empty(self.reason_code, "reason_code")
        require_aware_utc(self.decided_at, "decided_at")


# ============================================================================
# StateUpdatePolicy — the authority seam protocol
# ============================================================================


class StateUpdatePolicy(Protocol):
    """The authority seam that turns candidate state deltas into decisions.

    Per ADR-C10-A1 §2.1, this protocol is the only place where Fast vs
    Slow routing is decided. Implementations may use any policy
    (configuration-loaded) but must satisfy the contract:
      - ordinary / noisy events cannot directly mutate Slow State (H1)
      - verified high-salience events may immediately displace Fast
        State and may form a Slow candidate, but Slow mutation still
        requires Homeostasis authority (H3)
      - no implicit drift: Persona mutation is not this gate's concern
        (deferred to C10-B2)

    The protocol is shape-only. Numerical thresholds, salience
    classification, and Slow-candidate accumulation are policy-specific
    and live in implementations of this protocol.
    """

    def decide(
        self,
        candidate: CandidateStateDelta,
        prior_value: float | None,
    ) -> StateUpdateDecision:
        """Decide the disposition for one candidate state delta."""
        ...

    def decide_batch(
        self,
        candidates: tuple[tuple[CandidateStateDelta, float | None], ...],
    ) -> tuple[StateUpdateDecision, ...]:
        """Decide dispositions for a batch of candidates.

        Default implementations can iterate decide() per item. Concrete
        implementations may exploit cross-candidate reasoning.
        """
        ...


__all__ = [
    "CandidateStateDelta",
    "StateUpdateDecision",
    "StateUpdateDisposition",
    "StateUpdatePolicy",
]

# Backward-compatible names retained for existing callers and historical ADRs.
HomeostasisDisposition = StateUpdateDisposition
HomeostasisDecision = StateUpdateDecision
HomeostasisGate = StateUpdatePolicy