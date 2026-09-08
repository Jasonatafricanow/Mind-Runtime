"""Dynamics policy protocol (D1.5 freezes the contract only)."""

from datetime import timedelta
from typing import Protocol, runtime_checkable

from mind_runtime.contracts.affect import AffectiveDimensionProfile


@runtime_checkable
class DynamicsPolicy(Protocol):
    """A pure per-dimension state dynamics function."""

    def apply(
        self,
        dimension: str,
        profile: AffectiveDimensionProfile,
        current_value: float,
        delta: timedelta,
    ) -> float:
        """Return the next value for the dimension after `delta`."""
        ...
