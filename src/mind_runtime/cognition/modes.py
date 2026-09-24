"""Cognitive execution modes contract (MR-COGNITIVE-MODES-V0-CONTRACT-01).

Cognitive modes define when and what kind of cognition runs.
They do not define emotion, personality, truth, or action authority.

This module freezes the concept layer for cognitive modes. It deliberately
implements no transition policy, no background daemon, no worker, and no
numeric thresholds.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType

# ---------------------------------------------------------------------------
# Canonical Planned Keys & Legacy Boundaries (Reference only - no thresholds)
# ---------------------------------------------------------------------------

PLANNED_FATIGUE_STATE_KEY: str = "agent.affect.fatigue"
"""Canonical planned affect key for fatigue pressure signal.
Fatigue is NOT a CognitiveMode; it is a runtime state/pressure signal that may
later influence mode selection. Thresholds and accumulation rates are NOT implemented.
"""

LEGACY_INTROSPECTIVE_PULL_KEY: str = "agent.affect.introspective_pull"
"""Legacy affect dimension key preserved untouched for backward compatibility.
agent.affect.introspective_pull != CognitiveMode.INTROSPECTIVE.
The former is an affect/runtime dimension; the latter is a cognitive execution mode.
"""

# ---------------------------------------------------------------------------
# Non-Implemented Topology Status Markers
# ---------------------------------------------------------------------------

MODE_CONTROLLER_STATUS: str = "NOT_IMPLEMENTED"
TRANSITION_POLICY_STATUS: str = "NOT_IMPLEMENTED"
BACKGROUND_LCE_STATUS: str = "NOT_IMPLEMENTED"

# ---------------------------------------------------------------------------
# Non-Negotiable Authority Invariants
# ---------------------------------------------------------------------------

COGNITIVE_MODE_AUTHORITY_INVARIANTS: tuple[str, ...] = (
    "1. Cognitive mode does not create external-action authority.",
    "2. Any outbound action still requires Intent -> ActionPolicy -> normal Body / Delivery path.",
    "3. Background thought is not Evidence.",
    "4. Dream output is not canonical memory.",
    "5. Daydream output is not canonical memory.",
    "6. Introspection output is not canonical identity.",
    "7. Sleep does not automatically mutate Slow state.",
    (\n        "8. LCE remains a future consumer/provider of derived cognition, not the authority "\n        "for runtime mode switching."\n    ),
    "9. CognitiveMode is runtime orchestration state, not a personality dimension.",
    (\n        "10. No raw mode metadata must be exposed to provider unless a future bounded "\n        "consumer explicitly requires it."\n    ),
)


class CognitiveMode(StrEnum):
    """Execution modes governing what kind of cognitive processing may run.

    These are COGNITIVE EXECUTION MODES.
    They are NOT affect dimensions, Persona traits, Surface controls,
    or prompt style labels.
    """

    ACTIVE = "active"
    INTROSPECTIVE = "introspective"
    DAYDREAM = "daydream"
    SLEEP = "sleep"
    DREAM = "dream"


@dataclass(frozen=True, slots=True)
class CognitiveModeSpec:
    """Immutable specification of a cognitive execution mode.

    Contains no numeric thresholds, probabilities, or decay parameters.
    """

    mode: CognitiveMode
    purpose: str
    interactive: bool
    background_processing: bool
    outbound_allowed_by_mode: bool
    interruptible: bool
    parent_mode: CognitiveMode | None = None
    candidate_output_only: bool = False
    future_consumers: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.mode, CognitiveMode):
            raise TypeError(f"mode must be a CognitiveMode instance, got {type(self.mode)}")
        if not isinstance(self.purpose, str) or not self.purpose.strip():
            raise ValueError("purpose must be a non-empty string")
        if not isinstance(self.interactive, bool):
            raise TypeError("interactive must be a bool")
        if not isinstance(self.background_processing, bool):
            raise TypeError("background_processing must be a bool")
        if not isinstance(self.outbound_allowed_by_mode, bool):
            raise TypeError("outbound_allowed_by_mode must be a bool")
        if not isinstance(self.interruptible, bool):
            raise TypeError("interruptible must be a bool")
        if self.parent_mode is not None and not isinstance(self.parent_mode, CognitiveMode):
            raise TypeError("parent_mode must be None or a CognitiveMode instance")
        if not isinstance(self.candidate_output_only, bool):
            raise TypeError("candidate_output_only must be a bool")
        if not isinstance(self.future_consumers, tuple):
            raise TypeError("future_consumers must be a tuple")
        for consumer in self.future_consumers:
            if not isinstance(consumer, str) or not consumer.strip():
                raise ValueError("future_consumers entries must be non-empty strings")

        # Invariant validations
        if self.mode is CognitiveMode.DREAM and self.parent_mode is not CognitiveMode.SLEEP:
            raise ValueError("DREAM mode must have SLEEP as parent_mode")
        if (
            self.mode in (
                CognitiveMode.SLEEP,
                CognitiveMode.DREAM,
                CognitiveMode.INTROSPECTIVE,
                CognitiveMode.DAYDREAM,
            )
            and self.outbound_allowed_by_mode
        ):
            raise ValueError(f"{self.mode} must not authorize outbound action directly")
        if (
            self.mode in (
                CognitiveMode.INTROSPECTIVE,
                CognitiveMode.DAYDREAM,
                CognitiveMode.SLEEP,
                CognitiveMode.DREAM,
            )
            and not self.candidate_output_only
        ):
            raise ValueError(f"{self.mode} output must be candidate-only")

    @property
    def future_consumer(self) -> tuple[str, ...]:
        """Alias for future_consumers identifiers."""
        return self.future_consumers


COGNITIVE_MODE_V0_REGISTRY: MappingProxyType[CognitiveMode, CognitiveModeSpec] = MappingProxyType(
    {
        CognitiveMode.ACTIVE: CognitiveModeSpec(
            mode=CognitiveMode.ACTIVE,
            purpose=(
                "Normal online cognition processing inbound interaction and clock ticks through "
                "Dynamics, Intent, ActionPolicy, and Body."
            ),
            interactive=True,
            background_processing=False,
            outbound_allowed_by_mode=True,
            interruptible=True,
            parent_mode=None,
            candidate_output_only=False,
            future_consumers=(
                "online_turn_pipeline",
                "cognitive_ticker",
                "intent_engine",
                "action_policy",
                "body",
            ),
        ),
        CognitiveMode.INTROSPECTIVE: CognitiveModeSpec(
            mode=CognitiveMode.INTROSPECTIVE,
            purpose=(
                "Structured internal reflection for self-review, unresolved thought processing, "
                "recent experience reflection, and future LCE/compiled-cognition preparation."
            ),
            interactive=False,
            background_processing=True,
            outbound_allowed_by_mode=False,
            interruptible=True,
            parent_mode=None,
            candidate_output_only=True,
            future_consumers=(
                "lce",
                "compiled_cognition",
                "introspection_worker",
            ),
        ),
        CognitiveMode.DAYDREAM: CognitiveModeSpec(
            mode=CognitiveMode.DAYDREAM,
            purpose=(
                "Lightweight idle cognition for loose association, spontaneous recollection, "
                "low-cost background thought, and opportunistic semantic linking."
            ),
            interactive=False,
            background_processing=True,
            outbound_allowed_by_mode=False,
            interruptible=True,
            parent_mode=None,
            candidate_output_only=True,
            future_consumers=(
                "associative_memory",
                "daydream_worker",
                "lce",
            ),
        ),
        CognitiveMode.SLEEP: CognitiveModeSpec(
            mode=CognitiveMode.SLEEP,
            purpose=(
                "Deep offline cognitive-rest mode suppressing ordinary proactive activity to "
                "provide future processing windows for affect consolidation, slow-state "\n                "maintenance, "
                "memory consolidation, LCE consolidation, and trajectory cleanup."
            ),
            interactive=False,
            background_processing=True,
            outbound_allowed_by_mode=False,
            interruptible=True,
            parent_mode=None,
            candidate_output_only=True,
            future_consumers=(
                "affect_consolidation",
                "slow_state_maintenance",
                "memory_consolidation",
                "lce_consolidation",
                "trajectory_cleanup",
            ),
        ),
        CognitiveMode.DREAM: CognitiveModeSpec(
            mode=CognitiveMode.DREAM,
            purpose=(
                "Sleep-associated loose-association processing mode for cross-memory/"\n                "cross-semantic "
                "candidate generation and future LCE/cognition discovery."
            ),
            interactive=False,
            background_processing=True,
            outbound_allowed_by_mode=False,
            interruptible=True,
            parent_mode=CognitiveMode.SLEEP,
            candidate_output_only=True,
            future_consumers=(
                "lce",
                "cognition_discovery",
                "cross_memory_association",
            ),
        ),
    }
)


def get_cognitive_mode_spec(mode: CognitiveMode | str) -> CognitiveModeSpec:
    """Retrieve immutable specification for a cognitive mode by enum or string."""
    if isinstance(mode, str):
        try:
            mode = CognitiveMode(mode.lower())
        except ValueError:
            try:
                mode = CognitiveMode[mode.upper()]
            except KeyError:
                raise KeyError(f"Unknown cognitive mode: {mode}") from None
    if mode not in COGNITIVE_MODE_V0_REGISTRY:
        raise KeyError(f"Cognitive mode not registered: {mode}")
    return COGNITIVE_MODE_V0_REGISTRY[mode]
