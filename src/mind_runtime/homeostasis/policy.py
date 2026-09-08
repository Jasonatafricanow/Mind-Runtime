"""MR-C10-B-W: SalienceThresholdPolicy — default Homeostasis Gate policy.

Ported from `6163b1f` and wired into the C10-B-W production path.
This is the DEFAULT policy. The numerical thresholds are loaded from
configuration per ADR-C10-A1 §10.

Policy semantics (H1 + H3):

  H1 (ordinary / noisy):
    - low salience, low confidence
    - disposition: FAST_ONLY (fast effect may occur) or REJECT
    - Slow mutation: NEVER (no SLOW_ACCEPT for low-salience single events)

  H3 (verified high-salience):
    - high salience (≥ configured floor), high confidence
    - disposition: FAST_APPLY (immediate Fast displacement)
    - AND/OR SLOW_ACCEPT (Slow mutation permitted but Gate decided)
    - Slow mutation is allowed but the Gate decides each candidate
      individually — no implicit "all slow dimensions accept on shock"

Configuration contract:
  - alpha_config.salience_floor_fast_apply: float   (default 0.7)
  - alpha_config.salience_floor_slow_accept: float  (default 0.85)
  - alpha_config.confidence_floor_slow: float       (default 0.8)

These are placeholder values for testing. The test fixtures override
the configuration per-test. No value is frozen as an architecture constant.

The policy does NOT include Persona mutation logic. Persona Promotion is
deferred to C10-B2. The Gate only distinguishes Fast vs Slow.

C10-B1-R3 additions:
  - H6 (no evidence → no SLOW_*) preserved
  - R3-F2 confidence asymmetry preserved (confidence can veto, never promote)
  - This is a CANDIDATE implementation per R3-F3; the runtime boundary
    is the HomeostasisGate Protocol, not this concrete policy.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Protocol

from mind_runtime.contracts.common import require_non_empty
from mind_runtime.homeostasis.contracts import (
    CandidateStateDelta,
    HomeostasisDecision,
    HomeostasisDisposition,
    HomeostasisGate,
)


# ============================================================================
# Configuration protocol — alpha-supplied
# ============================================================================


class SalienceThresholdConfig(Protocol):
    """Configuration for the default SalienceThresholdPolicy.

    The values are alpha-supplied. The protocol captures the shape;
    implementations load from any config source.
    """

    @property
    def salience_floor_fast_apply(self) -> float:
        """Minimum salience for FAST_APPLY disposition."""

    @property
    def salience_floor_slow_accept(self) -> float:
        """Minimum salience for SLOW_ACCEPT disposition."""

    @property
    def confidence_floor_slow(self) -> float:
        """Minimum confidence for any SLOW_* disposition."""


@dataclass(frozen=True, slots=True)
class FixedSalienceThresholdConfig:
    """A simple fixed-value config for tests and for alpha's first run.

    No values are frozen in the contract. This is a convenience
    container; production wiring should load from `alpha.config` per
    ADR-C10-A1 §10.
    """

    salience_floor_fast_apply: float = 0.7
    salience_floor_slow_accept: float = 0.85
    confidence_floor_slow: float = 0.8

    def __post_init__(self) -> None:
        for field_name, value in (
            ("salience_floor_fast_apply", self.salience_floor_fast_apply),
            ("salience_floor_slow_accept", self.salience_floor_slow_accept),
            ("confidence_floor_slow", self.confidence_floor_slow),
        ):
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError(f"{field_name} must be a number")
            if not 0.0 <= float(value) <= 1.0:
                raise ValueError(f"{field_name} must be in [0, 1]")


# ============================================================================
# Clock protocol (for testability)
# ============================================================================


class _Clock(Protocol):
    def now(self) -> datetime: ...


def _default_clock() -> _Clock:
    """Real clock. Tests inject FakeClock."""

    class _RealClock:
        def now(self) -> datetime:
            return datetime.now(UTC)

    return _RealClock()


# ============================================================================
# SalienceThresholdPolicy — the default Homeostasis Gate implementation
# ============================================================================


@dataclass(frozen=True, slots=True)
class SalienceThresholdPolicy:
    """The default Homeostasis Gate policy.

    Uses salience + confidence thresholds to decide Fast vs Slow
    disposition per candidate. No implicit drift; no Persona mutation;
    no batch cross-candidate reasoning.

    C10-B1-R3 status: CANDIDATE implementation (R3-F3). The runtime
    boundary is the HomeostasisGate Protocol. Subject to conformance
    audit.
    """

    config: SalienceThresholdConfig
    clock: _Clock = field(default_factory=_default_clock)

    def decide(
        self,
        candidate: CandidateStateDelta,
        prior_value: float | None,
    ) -> HomeostasisDecision:
        salience: float | None = candidate.salience
        confidence = float(candidate.confidence)
        fast_floor = float(self.config.salience_floor_fast_apply)
        slow_floor = float(self.config.salience_floor_slow_accept)
        slow_conf = float(self.config.confidence_floor_slow)
        no_evidence = len(candidate.evidence_refs) == 0

        # Per C10-SALIENCE-IMPL-R2: unavailable salience (None) is NEVER
        # SLOW_ACCEPT, NEVER FAST_APPLY. It can only be REJECTED.
        # Salience=None means "not appraised" — the gate cannot authorize
        # any mutation on missing authority.
        if salience is None:
            return HomeostasisDecision(
                candidate=candidate,
                prior_value=prior_value,
                decision=HomeostasisDisposition.REJECT,
                reason_code="salience_unavailable_reject",
                decided_at=self.clock.now(),
            )

        salience = float(salience)

        # H6: no self-authorizing feedback.
        # H3 R1: high-salience verified events may enter Slow-State
        # candidacy, BUT only when they have proper evidence provenance.
        # A candidate that has nothing anchoring it cannot be promoted to
        # Slow state — regardless of how high its salience is. This is the
        # H6 self-authorizing feedback prohibition in action.
        if no_evidence:
            # Without evidence, the candidate is NEVER SLOW_ACCEPT or
            # SLOW_DAMP. It may still be FAST_APPLY (if salience is high
            # enough) or be REJECTED.
            if salience >= fast_floor:
                return HomeostasisDecision(
                    candidate=candidate,
                    prior_value=prior_value,
                    decision=HomeostasisDisposition.FAST_APPLY,
                    reason_code="no_evidence_fast_only_authorized",
                    decided_at=self.clock.now(),
                )
            return HomeostasisDecision(
                candidate=candidate,
                prior_value=prior_value,
                decision=HomeostasisDisposition.REJECT,
                reason_code="no_evidence_reject",
                decided_at=self.clock.now(),
            )

        # H1: ordinary / noisy cannot directly mutate Slow.
        if salience < slow_floor or confidence < slow_conf:
            # Below the Slow-mutation thresholds. Fast may still apply if
            # salience is high enough; otherwise the candidate is rejected.
            if salience >= fast_floor:
                return HomeostasisDecision(
                    candidate=candidate,
                    prior_value=prior_value,
                    decision=HomeostasisDisposition.FAST_APPLY,
                    reason_code="fast_apply_below_slow_thresholds",
                    decided_at=self.clock.now(),
                )
            return HomeostasisDecision(
                candidate=candidate,
                prior_value=prior_value,
                decision=HomeostasisDisposition.FAST_ONLY,
                reason_code="low_salience_low_confidence_fast_only",
                decided_at=self.clock.now(),
            )

        # H3: high-salience verified event may both displace Fast and
        # enter Slow candidacy. The Gate decides each separately.
        if confidence >= slow_conf:
            return HomeostasisDecision(
                candidate=candidate,
                prior_value=prior_value,
                decision=HomeostasisDisposition.SLOW_ACCEPT,
                reason_code="high_salience_high_confidence_slow_accept",
                decided_at=self.clock.now(),
            )

        # Defensive: if salience passes slow_floor but confidence
        # doesn't, we damp the slow mutation.
        return HomeostasisDecision(
            candidate=candidate,
            prior_value=prior_value,
            decision=HomeostasisDisposition.SLOW_DAMP,
            reason_code="high_salience_low_confidence_slow_damp",
            decided_at=self.clock.now(),
        )

    def decide_batch(
        self,
        candidates: tuple[tuple[CandidateStateDelta, float | None], ...],
    ) -> tuple[HomeostasisDecision, ...]:
        return tuple(self.decide(c, p) for c, p in candidates)


__all__ = [
    "SalienceThresholdConfig",
    "FixedSalienceThresholdConfig",
    "SalienceThresholdPolicy",
]