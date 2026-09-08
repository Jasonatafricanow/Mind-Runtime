"""DynamicsEngine: persona-driven affect dynamics with contribution trace.

The engine consumes current projected/canonical affect, elapsed time,
resolved appraisal impulses, the persona profile, relationship modifiers
(fixture/stub for now), and coupling. Every increment is explainable and
every proposed value is clamped to its dimension's floor/ceiling — coupling
can never push a dimension out of bounds (D7.5).

D7.3 covers the recovery path; D7.4 adds accumulator/event_only policies
(pluggable through the ``policies`` mapping); D7.5 adds coupling.
"""

import math
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import timedelta

from mind_runtime.contracts import AffectiveDimensionProfile, DynamicsPolicy
from mind_runtime.dynamics.persona import PersonaProfile
from mind_runtime.dynamics.policies import ContinuousReturnToBaselinePolicy


@dataclass(frozen=True)
class Impulse:
    """One appraisal-driven affect impulse on a dimension.

    Authority fields (salience, evidence_refs) live at the gate seam level,
    derived from the originating SemanticEventCandidate / SemanticAppraisal.
    Impulse itself carries only the event-fact: which dimension, how much.
    """

    dimension: str
    amount: float
    source_ref: str = "impulse"


@dataclass(frozen=True)
class Contribution:
    """One explainable increment: source, dimension, and amount.

    Authority fields (salience, evidence_refs) live at the gate seam level,
    derived from the originating SemanticEventCandidate / SemanticAppraisal.
    """

    dimension: str
    source: str
    amount: float


@dataclass(frozen=True)
class DynamicsResult:
    """Engine output: proposed values plus the explainable contribution trace."""

    proposed: tuple[tuple[str, float], ...]
    contributions: tuple[Contribution, ...]

    def value_for(self, dimension: str) -> float | None:
        for key, value in self.proposed:
            if key == dimension:
                return value
        return None


def _clamp(value: float, profile: AffectiveDimensionProfile) -> float:
    return max(profile.floor, min(profile.ceiling, value))


class DynamicsEngine:
    """Applies persona dynamics deterministically for one step."""

    def __init__(
        self,
        *,
        persona: PersonaProfile,
        policies: Mapping[str, DynamicsPolicy] | None = None,
    ) -> None:
        self._persona = persona
        self._policies = dict(policies or {})
        self._default_policy = ContinuousReturnToBaselinePolicy()

    @property
    def persona(self) -> PersonaProfile:
        return self._persona

    def step(
        self,
        *,
        current: Mapping[str, float],
        elapsed: timedelta,
        impulses: tuple[Impulse, ...] = (),
        relationship_modifiers: Mapping[str, float] | None = None,
    ) -> DynamicsResult:
        modifiers = relationship_modifiers or {}
        contributions: list[Contribution] = []
        proposed: dict[str, float] = {}

        # Per-dimension pass: recovery, impulses, modifiers, clamp.
        for dimension, profile in (
            (profile.dimension, profile) for profile in self._persona.dimensions
        ):
            current_value = current.get(dimension, profile.initial_value)
            policy = self._policies.get(dimension, self._default_policy)
            recovered = policy.apply(dimension, profile, current_value, elapsed)
            if not math.isclose(recovered, current_value):
                contributions.append(Contribution(dimension, "recovery", recovered - current_value))
            value = recovered

            for impulse in impulses:
                if impulse.dimension == dimension:
                    scaled = impulse.amount * profile.sensitivity
                    value += scaled
                    contributions.append(
                        Contribution(dimension, f"impulse:{impulse.source_ref}", scaled)
                    )

            modifier = modifiers.get(dimension)
            if modifier is not None:
                value += modifier
                contributions.append(Contribution(dimension, "relationship", modifier))

            proposed[dimension] = _clamp(value, profile)

        # Coupling pass (D7.5): each dimension's total delta spreads to its
        # coupled targets at the configured strength; every spread is traced
        # and the final clamp keeps all values inside floor/ceiling.
        coupling_deltas: list[tuple[str, float]] = []
        for dimension, profile in (
            (profile.dimension, profile) for profile in self._persona.dimensions
        ):
            before = current.get(dimension, profile.initial_value)
            delta = proposed[dimension] - before
            for target, strength in profile.coupling_profile:
                if strength == 0.0:
                    continue
                amount = delta * strength
                coupling_deltas.append((target, amount))
                contributions.append(Contribution(target, f"coupling:{dimension}", amount))
        for target, amount in coupling_deltas:
            if target in proposed:
                proposed[target] = proposed[target] + amount
        # Final clamp after coupling: coupling can never push out of bounds.
        for dimension, profile in (
            (profile.dimension, profile) for profile in self._persona.dimensions
        ):
            proposed[dimension] = _clamp(proposed[dimension], profile)

        return DynamicsResult(
            proposed=tuple(proposed.items()),
            contributions=tuple(contributions),
        )
