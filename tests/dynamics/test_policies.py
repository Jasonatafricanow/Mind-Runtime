"""D7.4 policy boundary tests: accumulator and event_only stay put by time."""

from datetime import UTC, datetime, timedelta

from mind_runtime.contracts import AffectiveDimensionProfile
from mind_runtime.dynamics.policies import AccumulatorPolicy, EventOnlyPolicy

NOW = datetime(2026, 8, 22, 22, 0, tzinfo=UTC)


def make_profile(dimension: str = "relationship.trust") -> AffectiveDimensionProfile:
    return AffectiveDimensionProfile(
        dimension=dimension,
        baseline=0.5,
        initial_value=0.5,
        sensitivity=0.3,
        recovery_rate=0.05,
        ceiling=1.0,
        floor=0.0,
        growth_profile=(),
        coupling_profile=(),
    )


def test_accumulator_time_does_not_move_value() -> None:
    """Slow variables change only through events; time never moves them."""
    policy = AccumulatorPolicy()
    profile = make_profile()
    value = policy.apply("relationship.trust", profile, 0.7, timedelta(hours=24))
    assert value == 0.7


def test_event_only_time_never_changes_value() -> None:
    """Identity / relationship-status cannot change by time at all."""
    policy = EventOnlyPolicy()
    profile = make_profile()
    value = policy.apply("relationship.trust", profile, 0.4, timedelta(days=365))
    assert value == 0.4
