"""Persona trait/profile models (D7.1).

The frozen rule: Trait != Current State. A persona profile carries trait
parameters only (baseline, initial_value, floor, ceiling, sensitivity,
recovery_rate, coupling); the current value of an affect dimension lives
exclusively in runtime/projected state, never in the profile.
"""

from dataclasses import dataclass

from mind_runtime.contracts import AffectiveDimensionProfile


@dataclass(frozen=True)
class PersonaProfile:
    """A named container of trait dimensions (no current values)."""

    persona_id: str
    dimensions: tuple[AffectiveDimensionProfile, ...]
    version: int = 1

    def __post_init__(self) -> None:
        if not self.persona_id.strip():
            raise ValueError("persona_id must be non-empty")
        if isinstance(self.version, bool) or self.version < 1:
            raise ValueError("version must be at least 1")
        seen: set[str] = set()
        for profile in self.dimensions:
            if profile.dimension in seen:
                raise ValueError(f"duplicate dimension {profile.dimension!r} in persona")
            seen.add(profile.dimension)

    def for_dimension(self, dimension: str) -> AffectiveDimensionProfile | None:
        for profile in self.dimensions:
            if profile.dimension == dimension:
                return profile
        return None

    def require_dimension(self, dimension: str) -> AffectiveDimensionProfile:
        profile = self.for_dimension(dimension)
        if profile is None:
            raise ValueError(f"persona {self.persona_id!r} has no dimension {dimension!r}")
        return profile

    def dimension_keys(self) -> tuple[str, ...]:
        return tuple(profile.dimension for profile in self.dimensions)
