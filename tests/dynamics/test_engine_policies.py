"""D7.4 engine dispatch tests: accumulator/event_only policies wired by dimension."""

from datetime import UTC, datetime, timedelta

from mind_runtime.contracts import AffectiveDimensionProfile
from mind_runtime.dynamics.engine import DynamicsEngine, Impulse
from mind_runtime.dynamics.persona import PersonaProfile
from mind_runtime.dynamics.policies import AccumulatorPolicy, EventOnlyPolicy

NOW = datetime(2026, 8, 22, 22, 30, tzinfo=UTC)


def make_profile(
    dimension: str,
    *,
    baseline: float = 0.3,
    sensitivity: float = 0.6,
) -> AffectiveDimensionProfile:
    return AffectiveDimensionProfile(
        dimension=dimension,
        baseline=baseline,
        initial_value=baseline,
        sensitivity=sensitivity,
        recovery_rate=0.2,
        ceiling=1.0,
        floor=0.0,
        growth_profile=(),
        coupling_profile=(),
    )


def make_mixed_engine() -> DynamicsEngine:
    """longing: continuous; trust: accumulator; status: event_only."""
    return DynamicsEngine(
        persona=PersonaProfile(
            persona_id="mixed",
            dimensions=(
                make_profile("agent.affect.longing"),
                make_profile("relationship.trust"),
                make_profile("relationship.status"),
            ),
        ),
        policies={
            "relationship.trust": AccumulatorPolicy(),
            "relationship.status": EventOnlyPolicy(),
        },
    )


def test_accumulator_dimension_ignores_elapsed_time() -> None:
    engine = make_mixed_engine()
    result = engine.step(
        current={
            "agent.affect.longing": 0.9,
            "relationship.trust": 0.7,
            "relationship.status": 0.4,
        },
        elapsed=timedelta(hours=24),
    )
    # Longing decays; trust and status are untouched by time.
    longing = result.value_for("agent.affect.longing")
    assert longing is not None
    assert longing < 0.9
    assert result.value_for("relationship.trust") == 0.7
    assert result.value_for("relationship.status") == 0.4
    sources = {contribution.source for contribution in result.contributions}
    assert sources == {"recovery"}


def test_impulse_still_moves_accumulator_and_event_only_dimensions() -> None:
    """Events (impulses) move slow and event-only dimensions; time does not."""
    engine = make_mixed_engine()
    result = engine.step(
        current={
            "relationship.trust": 0.5,
            "relationship.status": 0.4,
        },
        elapsed=timedelta(hours=24),
        impulses=(
            Impulse("relationship.trust", 0.2, source_ref="e-1"),
            Impulse("relationship.status", 0.3, source_ref="e-2"),
        ),
    )
    assert result.value_for("relationship.trust") == 0.5 + 0.2 * 0.6
    assert result.value_for("relationship.status") == 0.4 + 0.3 * 0.6


def test_accumulator_recovery_never_recorded() -> None:
    """No spurious recovery contribution for time-immune dimensions."""
    engine = make_mixed_engine()
    result = engine.step(
        current={"relationship.trust": 0.9},
        elapsed=timedelta(hours=1),
    )
    assert result.value_for("relationship.trust") == 0.9
    assert result.contributions == ()


def test_mixed_step_is_replayable() -> None:
    engine = make_mixed_engine()
    current = {
        "agent.affect.longing": 0.9,
        "relationship.trust": 0.7,
        "relationship.status": 0.4,
    }
    first = engine.step(current=current, elapsed=timedelta(hours=2))
    second = engine.step(current=current, elapsed=timedelta(hours=2))
    assert first == second
