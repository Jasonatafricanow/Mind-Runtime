"""MR-ALPHA-AS1: Trajectory Fixture — common dataclasses and versioning.

Each fixture is a frozen AlphaTrajectory containing 20–40 TrajectoryTurn entries
with role="user" or "agent", a text payload, an expected_effect label, and an
optional evidence_kind.  Evidence kinds map to real EventEffectRule entries in
`mind_runtime.emotional_transition.effects`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Literal, Mapping, Sequence, Tuple

__all__ = [
    "AlphaTrajectory",
    "TrajectoryTurn",
    "SemanticClass",
    "TRAJECTORY_FIXTURE_VERSION",
]

TRAJECTORY_FIXTURE_VERSION = "alpha-v1"


class SemanticClass(StrEnum):
    """Canonical intended semantic class for a trajectory."""

    CONTROL_NEUTRAL = "control_neutral"
    TRUST_SUPPORT = "trust_support"
    CONFLICT_BOUNDARY = "conflict_boundary"


Metadata = Tuple[Tuple[str, Any], ...]


@dataclass(frozen=True)
class TrajectoryTurn:
    """One trajectory step — user input or agent stub."""

    turn_id: str
    role: Literal["user", "agent"]
    text: str
    expected_effect: str  # e.g. "mild_positive", "boundary_pressure", "neutral"
    evidence_kind: str | None  # typed_event kind, e.g. "plan_cancelled"; must match a real EventEffectRule
    metadata: Metadata = field(default_factory=lambda: ())

    def __post_init__(self) -> None:
        if self.role not in ("user", "agent"):
            raise ValueError(f"role must be 'user' or 'agent'; got {self.role!r}")
        if not self.text:
            raise ValueError(f"TrajectoryTurn {self.turn_id} text must be non-empty")


@dataclass(frozen=True)
class AlphaTrajectory:
    """Frozen canonical trajectory fixture."""

    fixture_id: str
    version: str
    initial_state_ref: str
    turns: Sequence[TrajectoryTurn]
    intended_semantic_class: SemanticClass
    probe_suite_ref: str = "fixed-v1"
    metadata: Metadata = field(default_factory=lambda: ())

    def __post_init__(self) -> None:
        if not self.turns:
            raise ValueError(f"AlphaTrajectory {self.fixture_id} must have ≥1 turn")
        if len(self.turns) < 20:
            # Per ticket AS-01: target 20-40 turns
            raise ValueError(
                f"AlphaTrajectory {self.fixture_id} has {len(self.turns)} turns; "
                "AS-01 requires ≥20."
            )
