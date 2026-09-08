"""Dynamics policies (D7.3/D7.4).

Policies are pure per-dimension functions of
(profile, current_value, delta): deterministic under the injected clock,
never reading wall time.

- continuous_return_to_baseline: exponential decay toward the persona
  baseline — not a fixed per-hour increment (D7.3).
- accumulator: slow variables change only through events; time does not
  move them (D7.4).
- event_only: identity/relationship-status dimensions never change by
  time at all (D7.4).
"""

import math
from datetime import timedelta

from mind_runtime.contracts import AffectiveDimensionProfile


class ContinuousReturnToBaselinePolicy:
    """Exponential return to the persona baseline (D7.3)."""

    def apply(
        self,
        dimension: str,
        profile: AffectiveDimensionProfile,
        current_value: float,
        delta: timedelta,
    ) -> float:
        seconds = max(delta.total_seconds(), 0.0)
        decay = math.exp(-profile.recovery_rate * seconds)
        return profile.baseline + (current_value - profile.baseline) * decay


class AccumulatorPolicy:
    """Slow variables: time does not move them; events do (D7.4)."""

    def apply(
        self,
        dimension: str,
        profile: AffectiveDimensionProfile,
        current_value: float,
        delta: timedelta,
    ) -> float:
        return current_value


class EventOnlyPolicy:
    """Identity / relationship-status: no time-based change at all (D7.4)."""

    def apply(
        self,
        dimension: str,
        profile: AffectiveDimensionProfile,
        current_value: float,
        delta: timedelta,
    ) -> float:
        return current_value
