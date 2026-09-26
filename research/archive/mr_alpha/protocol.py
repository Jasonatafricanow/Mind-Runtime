"""MR-ALPHA-AS1: Accumulated-State Causal Alpha Platform — AS-00 Protocol Freeze.

This module defines the frozen experimental protocol for the Accumulated-State
Causal Alpha Platform.  All thresholds, criteria, and structural choices are
made before seeing any harness results and are never mutated during execution.

Evidence mode
-------------
EVIDENCE_MODE = HARNESS_VALIDATION_ONLY
Results through this module do NOT constitute MR Alpha evidence.
Only when the production consumption seam (C) is merged and AS-09/AS-10 run
with real SlowPlasticityWriter + real IntentEngine consumer does
EVIDENCE_MODE become "production".
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

# Public re-exports so harness code imports from one canonical place.
from tests.mr_alpha.ablations import AblationArm

__all__ = [
    "AlphaProtocol",
    "AlphaScoreCriteria",
    "EVIDENCE_MODE",
    "PROTOCOL_VERSION",
]

PROTOCOL_VERSION = "alpha-v1"
EVIDENCE_MODE: Literal["harness_validation", "production"] = "harness_validation"


@dataclass(frozen=True)
class AlphaScoreCriteria:
    """Frozen PASS thresholds — immutable after AS-00."""

    # M — Mutation
    min_meaningful_appraisals: int = 3
    min_slow_candidates: int = 1
    min_accepted_writes: int = 1
    min_accumulated_delta: float = 0.001

    # P — Persistence
    state_survives_boundary: bool = True
    provenance_preserved: bool = True

    # C — Consumption (synthetic consumer call count in harness mode)
    min_consumer_invocations: int = 1
    slow_state_read_by_consumer: bool = True

    # B — Behavioral consequence
    behavioral_divergence_threshold: float = 0.01

    # Signal density
    min_signal_density_ratio: float = 0.05


@dataclass(frozen=True)
class AlphaProtocol:
    """Frozen experimental protocol for MR-ALPHA-AS1 AS-00.

    Once written (AS-00 commit) this dataclass MUST NOT be modified.
    To change any parameter, create a new protocol version (alpha-v2, etc.)
    and re-run the experiment from scratch.
    """

    # Metadata
    version: str = field(default=PROTOCOL_VERSION)
    agent_id: str = "mr-alpha-as1"
    model: str = "alpha-harness-v1"

    # Fixture references
    initial_state_ref: str = "alpha-v1-baseline"
    probe_suite_ref: str = "fixed-v1"
    trajectory_version: str = "alpha-v1"

    # Experimental arms to execute
    arms: tuple[AblationArm, ...] = field(default_factory=lambda: tuple(AblationArm))

    # PASS/FAIL thresholds
    score_criteria: AlphaScoreCriteria = field(default_factory=AlphaScoreCriteria)

    # Evidence mode — harness only until C is merged
    evidence_mode: Literal["harness_validation", "production"] = field(
        default=EVIDENCE_MODE
    )

    # Schema version — bump on breaking structural change
    _protocol_version: int = field(default=1, repr=False)

    def __post_init__(self) -> None:
        if self._protocol_version != 1:
            raise ValueError(
                f"AlphaProtocol._protocol_version must be 1; got {self._protocol_version}. "
                "Create a new protocol version instead of backporting changes."
            )
        # Verify arms is the complete set without duplicates
        seen: set[AblationArm] = set()
        for arm in self.arms:
            if arm in seen:
                raise ValueError(f"Duplicate AblationArm in protocol: {arm}")
            seen.add(arm)

    @property
    def is_harness_validation(self) -> bool:
        """True if evidence mode is harness-only (default for AS-00..AS-08)."""
        return self.evidence_mode == "harness_validation"
