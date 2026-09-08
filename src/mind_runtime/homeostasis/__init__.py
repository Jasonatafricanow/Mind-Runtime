"""MR-C10-B-W: Homeostasis Gate package.

Per ADR-C10-A1: this package owns the Fast vs Slow state routing
authority. The C10-B-W slow-plasticity writer consumes SLOW_ACCEPT
decisions from this gate.

Public contract surface:
  - CandidateStateDelta
  - HomeostasisDecision
  - HomeostasisDisposition
  - HomeostasisGate
  - SalienceThresholdPolicy (default policy implementation)

Numerical thresholds (salience floor, confidence floor, etc.) are NOT
frozen in this package. They are configuration-owned per AGENTS.md §2
(kernel stays dimension-agnostic) and ADR-C10-A1 §10.

Authority note: The HomeostasisGate Protocol is the runtime authority seam.
Per C10-B1-R3, SalienceThresholdPolicy is a CANDIDATE implementation, not
canonized. The Protocol boundary is what B-W depends on.
"""

from mind_runtime.homeostasis.contracts import (
    CandidateStateDelta,
    HomeostasisDecision,
    HomeostasisDisposition,
    HomeostasisGate,
)

__all__ = [
    "CandidateStateDelta",
    "HomeostasisDecision",
    "HomeostasisDisposition",
    "HomeostasisGate",
]
