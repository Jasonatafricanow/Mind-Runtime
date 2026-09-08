"""Affective dimension profile contract (baseline 4.6)."""

from dataclasses import dataclass

from mind_runtime.contracts.common import require_non_empty


@dataclass(frozen=True, slots=True)
class AffectiveDimensionProfile:
    """Trait-level parameters of one affect dimension; never carries current."""

    dimension: str
    baseline: float
    initial_value: float
    sensitivity: float
    recovery_rate: float
    ceiling: float
    floor: float
    growth_profile: tuple[tuple[str, float], ...]
    coupling_profile: tuple[tuple[str, float], ...]

    def __post_init__(self) -> None:
        require_non_empty(self.dimension, "dimension")
        for key, _value in self.growth_profile:
            require_non_empty(key, "growth_profile keys")
        for key, _value in self.coupling_profile:
            require_non_empty(key, "coupling_profile keys")
