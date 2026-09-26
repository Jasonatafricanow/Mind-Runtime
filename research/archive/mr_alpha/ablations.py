"""MR-ALPHA-AS1: Causal Ablation Matrix — AS-06.

Defines the five ablation arms and their wiring specifications.

Ablation arms
-------------
BASELINE      — synthetic slow writer + synthetic consumer (canonical harness run)
TREATMENT     — synthetic slow writer + synthetic consumer (same config; distinct trajectory)
WRITE_OFF     — no slow writer; consumption still fires; proves write-path necessity
CONSUME_OFF   — slow writes fire but are never consumed; proves consumption necessity
STATE_RESET   — slow writes fire then are rolled back to baseline; proves accumulation necessity

Each arm is exercised independently by AlphaRunner.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum, auto


class AblationArm(StrEnum):
    """Canonical causal-ablation arms for the Accumulated-State experiment."""

    # ── Core pair ────────────────────────────────────────────────────────────
    BASELINE = auto()   # Harness default: synthetic slow writer + consumer
    TREATMENT = auto()  # Harness treatment: same wiring as baseline

    # ── Causal gap demonstrations ────────────────────────────────────────────
    WRITE_OFF = auto()     # Slow writes disabled — proves the write path is necessary
    CONSUME_OFF = auto()   # Slow writes fire but are never consumed — proves consumption is necessary
    STATE_RESET = auto()   # Slow writes fire then are reset to baseline — proves accumulation is necessary

    @property
    def label(self) -> str:
        return self.name

    @property
    def description(self) -> str:
        descriptions = {
            AblationArm.BASELINE: "Synthetic slow writer + synthetic consumer (canonical)",
            AblationArm.TREATMENT: "Synthetic slow writer + synthetic consumer (treatment trajectory)",
            AblationArm.WRITE_OFF: "Slow writes disabled; consumption still fires",
            AblationArm.CONSUME_OFF: "Slow writes fire; consumption disabled",
            AblationArm.STATE_RESET: "Slow writes fire then are reset to baseline after trajectory",
        }
        return descriptions[self]


@dataclass(frozen=True)
class AblationSpec:
    """Immutable specification for one ablation arm.

    Passed to AlphaRunner so it can construct the correct orchestrator
    and post-trajectory actions for each arm.
    """

    arm: AblationArm
    trajectory_ref: str
    disable_slow_write: bool = field(default=False)
    disable_consumer: bool = field(default=False)
    reset_state_after_trajectory: bool = field(default=False)
    label: str = field(default="")

    def __post_init__(self) -> None:
        # Derive label from arm if not provided
        if not self.label:
            object.__setattr__(self, "label", self.arm.label)

    @staticmethod
    def default_suite(trajectory_ref: str) -> tuple[AblationSpec, ...]:
        """Standard five-arm suite used in the AS-08 protocol."""
        return (
            AblationSpec(
                arm=AblationArm.BASELINE,
                trajectory_ref=trajectory_ref,
                disable_slow_write=False,
                disable_consumer=False,
                reset_state_after_trajectory=False,
            ),
            AblationSpec(
                arm=AblationArm.TREATMENT,
                trajectory_ref=trajectory_ref,
                disable_slow_write=False,
                disable_consumer=False,
                reset_state_after_trajectory=False,
            ),
            AblationSpec(
                arm=AblationArm.WRITE_OFF,
                trajectory_ref=trajectory_ref,
                disable_slow_write=True,
                disable_consumer=False,
                reset_state_after_trajectory=False,
            ),
            AblationSpec(
                arm=AblationArm.CONSUME_OFF,
                trajectory_ref=trajectory_ref,
                disable_slow_write=False,
                disable_consumer=True,
                reset_state_after_trajectory=False,
            ),
            AblationSpec(
                arm=AblationArm.STATE_RESET,
                trajectory_ref=trajectory_ref,
                disable_slow_write=False,
                disable_consumer=False,
                reset_state_after_trajectory=True,
            ),
        )
