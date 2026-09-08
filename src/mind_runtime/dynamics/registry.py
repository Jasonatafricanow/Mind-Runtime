"""Dynamic dimension registry (D7.2).

The kernel never fixes the dimension set to 12 (or any number): 5/12/20/
custom sets are configuration registered here, never core defaults.
"""

from dataclasses import dataclass

from mind_runtime.contracts import AffectiveDimensionProfile


@dataclass(frozen=True)
class DimensionSet:
    """One named, configurable set of affect dimensions."""

    name: str
    dimensions: tuple[AffectiveDimensionProfile, ...]

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("dimension set name must be non-empty")
        seen: set[str] = set()
        for profile in self.dimensions:
            if profile.dimension in seen:
                raise ValueError(f"duplicate dimension {profile.dimension!r} in set")
            seen.add(profile.dimension)


class DynamicDimensionRegistry:
    """Named dimension sets (5/12/20/custom); unknown sets fail closed."""

    def __init__(self) -> None:
        self._sets: dict[str, DimensionSet] = {}

    def register(self, dimension_set: DimensionSet) -> None:
        if dimension_set.name in self._sets:
            raise ValueError(f"dimension set already registered: {dimension_set.name}")
        self._sets[dimension_set.name] = dimension_set

    def get(self, name: str) -> DimensionSet | None:
        return self._sets.get(name)

    def require(self, name: str) -> DimensionSet:
        dimension_set = self._sets.get(name)
        if dimension_set is None:
            raise ValueError(f"no dimension set registered: {name!r}")
        return dimension_set

    def names(self) -> tuple[str, ...]:
        return tuple(self._sets.keys())
