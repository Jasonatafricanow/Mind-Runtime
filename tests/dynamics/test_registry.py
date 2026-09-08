"""D7.2 dynamic dimension registry tests: 5/12/20/custom sets are config."""

import pytest

from mind_runtime.contracts import AffectiveDimensionProfile
from mind_runtime.dynamics.registry import DimensionSet, DynamicDimensionRegistry


def make_dimension(dimension: str) -> AffectiveDimensionProfile:
    return AffectiveDimensionProfile(
        dimension=dimension,
        baseline=0.3,
        initial_value=0.3,
        sensitivity=0.6,
        recovery_rate=0.2,
        ceiling=1.0,
        floor=0.0,
        growth_profile=(),
        coupling_profile=(),
    )


def make_set(name: str, count: int) -> DimensionSet:
    return DimensionSet(
        name=name,
        dimensions=tuple(make_dimension(f"agent.affect.dim{i}") for i in range(count)),
    )


def test_five_and_twelve_dimension_sets_are_config_not_kernel() -> None:
    registry = DynamicDimensionRegistry()
    registry.register(make_set("five", 5))
    registry.register(make_set("twelve", 12))
    assert registry.names() == ("five", "twelve")
    assert len(registry.require("five").dimensions) == 5
    assert len(registry.require("twelve").dimensions) == 12


def test_custom_dimension_set() -> None:
    registry = DynamicDimensionRegistry()
    custom = DimensionSet(
        name="custom_v0",
        dimensions=(
            make_dimension("agent.affect.longing"),
            make_dimension("agent.affect.anxiety"),
            make_dimension("relationship.trust"),
        ),
    )
    registry.register(custom)
    assert registry.get("custom_v0") is custom


def test_duplicate_set_name_fails_closed() -> None:
    registry = DynamicDimensionRegistry()
    registry.register(make_set("five", 5))
    with pytest.raises(ValueError, match="already registered"):
        registry.register(make_set("five", 5))


def test_unknown_set_fails_closed() -> None:
    registry = DynamicDimensionRegistry()
    assert registry.get("missing") is None
    with pytest.raises(ValueError, match="no dimension set"):
        registry.require("missing")


def test_dimension_set_rejects_duplicates_and_empty_name() -> None:
    with pytest.raises(ValueError, match="duplicate"):
        DimensionSet(name="dup", dimensions=(make_dimension("a"), make_dimension("a")))
    with pytest.raises(ValueError, match="non-empty"):
        DimensionSet(name="", dimensions=())


def test_registry_is_deterministic_for_replay() -> None:
    registry = DynamicDimensionRegistry()
    registry.register(make_set("twelve", 12))
    registry.register(make_set("five", 5))
    first = registry.require("twelve")
    second = registry.require("twelve")
    assert first == second
    assert registry.names() == ("twelve", "five")
