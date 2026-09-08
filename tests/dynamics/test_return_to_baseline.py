"""D7.3 continuous_return_to_baseline tests: replayable exponential decay."""

import math
from datetime import UTC, datetime, timedelta

import pytest

from mind_runtime.contracts import AffectiveDimensionProfile
from mind_runtime.dynamics.engine import Contribution, DynamicsEngine, Impulse
from mind_runtime.dynamics.persona import PersonaProfile

NOW = datetime(2026, 8, 22, 21, 0, tzinfo=UTC)


def make_profile(
    dimension: str = "agent.affect.longing",
    *,
    baseline: float = 0.3,
    sensitivity: float = 0.6,
    recovery_rate: float = 0.2,
    ceiling: float = 1.0,
    floor: float = 0.0,
    initial: float = 0.3,
) -> AffectiveDimensionProfile:
    return AffectiveDimensionProfile(
        dimension=dimension,
        baseline=baseline,
        initial_value=initial,
        sensitivity=sensitivity,
        recovery_rate=recovery_rate,
        ceiling=ceiling,
        floor=floor,
        growth_profile=(),
        coupling_profile=(),
    )


def make_engine(*profiles: AffectiveDimensionProfile) -> DynamicsEngine:
    return DynamicsEngine(persona=PersonaProfile(persona_id="test", dimensions=profiles))


def test_decays_toward_baseline_exponentially() -> None:
    profile = make_profile(baseline=0.3, recovery_rate=0.2)
    engine = make_engine(profile)
    # Elevated value decays toward baseline after one hour.
    result = engine.step(
        current={"agent.affect.longing": 0.9},
        elapsed=timedelta(hours=1),
    )
    value = result.value_for("agent.affect.longing")
    assert value is not None
    expected = 0.3 + (0.9 - 0.3) * math.exp(-0.2 * 3600)
    assert value == pytest.approx(expected)


def test_no_time_no_change() -> None:
    engine = make_engine(make_profile())
    result = engine.step(
        current={"agent.affect.longing": 0.9},
        elapsed=timedelta(0),
    )
    assert result.value_for("agent.affect.longing") == pytest.approx(0.9)
    assert result.contributions == ()


def test_recovery_is_replayable_under_fake_clock() -> None:
    engine = make_engine(make_profile())
    first = engine.step(
        current={"agent.affect.longing": 0.8},
        elapsed=timedelta(minutes=30),
    )
    second = engine.step(
        current={"agent.affect.longing": 0.8},
        elapsed=timedelta(minutes=30),
    )
    assert first == second


def test_impulse_scaled_by_sensitivity_and_traced() -> None:
    engine = make_engine(make_profile(sensitivity=0.6))
    result = engine.step(
        current={"agent.affect.longing": 0.3},
        elapsed=timedelta(0),
        impulses=(Impulse("agent.affect.longing", 0.5, source_ref="e-1"),),
    )
    assert result.value_for("agent.affect.longing") == pytest.approx(0.3 + 0.5 * 0.6)
    assert Contribution("agent.affect.longing", "impulse:e-1", 0.3) in result.contributions


def test_impulse_is_clamped_to_ceiling() -> None:
    engine = make_engine(make_profile(ceiling=1.0, sensitivity=1.0))
    result = engine.step(
        current={"agent.affect.longing": 0.8},
        elapsed=timedelta(0),
        impulses=(Impulse("agent.affect.longing", 0.5),),
    )
    assert result.value_for("agent.affect.longing") == 1.0


def test_impulse_is_clamped_to_floor() -> None:
    engine = make_engine(make_profile(floor=0.0, sensitivity=1.0))
    result = engine.step(
        current={"agent.affect.longing": 0.1},
        elapsed=timedelta(0),
        impulses=(Impulse("agent.affect.longing", -0.5),),
    )
    assert result.value_for("agent.affect.longing") == 0.0


def test_unknown_dimension_uses_initial_value() -> None:
    engine = make_engine(make_profile(initial=0.3))
    result = engine.step(current={}, elapsed=timedelta(0))
    assert result.value_for("agent.affect.longing") == pytest.approx(0.3)


def test_relationship_modifier_traced() -> None:
    engine = make_engine(make_profile())
    result = engine.step(
        current={"agent.affect.longing": 0.3},
        elapsed=timedelta(0),
        relationship_modifiers={"agent.affect.longing": 0.1},
    )
    assert result.value_for("agent.affect.longing") == pytest.approx(0.4)
    assert Contribution("agent.affect.longing", "relationship", 0.1) in result.contributions


def test_different_sensitivity_different_impulse_result() -> None:
    """G7 core: the same impulse with different persona sensitivities diverges."""
    low = make_engine(make_profile(sensitivity=0.2))
    high = make_engine(make_profile(sensitivity=0.9))
    impulse = Impulse("agent.affect.longing", 1.0)
    low_value = low.step(current={}, elapsed=timedelta(0), impulses=(impulse,)).value_for(
        "agent.affect.longing"
    )
    high_value = high.step(current={}, elapsed=timedelta(0), impulses=(impulse,)).value_for(
        "agent.affect.longing"
    )
    assert low_value == pytest.approx(0.5)  # 0.3 + 1.0 * 0.2
    assert high_value == pytest.approx(1.0)  # 0.3 + 1.0 * 0.9, clamped at ceiling


def test_value_for_unknown_dimension_returns_none() -> None:
    engine = make_engine(make_profile())
    result = engine.step(current={}, elapsed=timedelta(0))
    assert result.value_for("agent.affect.missing") is None


def test_impulse_for_other_dimension_is_ignored() -> None:
    engine = make_engine(make_profile())
    result = engine.step(
        current={"agent.affect.longing": 0.3},
        elapsed=timedelta(0),
        impulses=(Impulse("agent.affect.anxiety", 0.9),),  # not in this persona
    )
    assert result.value_for("agent.affect.longing") == pytest.approx(0.3)
    assert all(contribution.source == "recovery" for contribution in result.contributions)
