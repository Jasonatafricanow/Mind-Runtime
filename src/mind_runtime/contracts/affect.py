"""Affective dimension profile contract (baseline 4.6)."""

import math
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from typing import cast

from mind_runtime.contracts.common import require_non_empty

DISPOSITION_TRAIT_NAMES: tuple[str, ...] = (
    "attachment_approach",
    "confrontation_readiness",
    "expressive_restraint",
    "expressive_warmth_bias",
)


@dataclass(frozen=True, slots=True, eq=False)
class BehavioralDisposition(Mapping[str, float]):
    """Immutable behavioral disposition traits (V1).

    Owned exclusively by PersonaProfile. Contains exactly the four declared roots:
    attachment_approach, confrontation_readiness, expressive_restraint, expressive_warmth_bias.
    Every trait must be a finite float in [0.0, 1.0].
    """

    attachment_approach: float
    confrontation_readiness: float
    expressive_restraint: float
    expressive_warmth_bias: float

    def __post_init__(self) -> None:
        for name in DISPOSITION_TRAIT_NAMES:
            val = getattr(self, name)
            if val is None or isinstance(val, bool) or not isinstance(val, (int, float)):
                raise ValueError(
                    f"disposition trait {name!r} must be a number, got {val!r}"
                )
            fval = float(val)
            if not math.isfinite(fval):
                raise ValueError(
                    f"disposition trait {name!r} must be finite, got {fval}"
                )
            if not (0.0 <= fval <= 1.0):
                raise ValueError(
                    f"disposition trait {name!r} must be in [0.0, 1.0], got {fval}"
                )
            if type(val) is not float:
                object.__setattr__(self, name, fval)

    def __getitem__(self, key: str) -> float:
        if key in DISPOSITION_TRAIT_NAMES:
            return cast(float, getattr(self, key))
        raise KeyError(key)

    def __iter__(self) -> Iterator[str]:
        yield from DISPOSITION_TRAIT_NAMES

    def __len__(self) -> int:
        return 4

    def __eq__(self, other: object) -> bool:
        if isinstance(other, Mapping):
            if len(self) != len(other):
                return False
            return all(k in other and self[k] == other[k] for k in self)
        return False

    def __hash__(self) -> int:
        return hash(
            (
                self.attachment_approach,
                self.confrontation_readiness,
                self.expressive_restraint,
                self.expressive_warmth_bias,
            )
        )

    def to_dict(self) -> dict[str, float]:
        return {name: getattr(self, name) for name in DISPOSITION_TRAIT_NAMES}


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
