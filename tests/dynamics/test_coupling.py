"""D7.5 coupling and contribution trace tests."""

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from mind_runtime.contracts import AffectiveDimensionProfile
from mind_runtime.dynamics.engine import DynamicsEngine, Impulse
from mind_runtime.dynamics.persona import PersonaProfile

NOW = datetime(2026, 8, 22, 23, 0, tzinfo=UTC)


def make_profile(
    dimension: str,
    *,
    sensitivity: float = 0.6,
    ceiling: float = 1.0,
    floor: float = 0.0,
    coupling: tuple[tuple[str, float], ...] = (),
) -> AffectiveDimensionProfile:
    return AffectiveDimensionProfile(
        dimension=dimension,
        baseline=0.3,
        initial_value=0.3,
        sensitivity=sensitivity,
        recovery_rate=0.2,
        ceiling=ceiling,
        floor=floor,
        growth_profile=(),
        coupling_profile=coupling,
    )


def make_coupled_engine() -> DynamicsEngine:
    """anxiety couples into longing at 0.5 strength (source carries the profile)."""
    return DynamicsEngine(
        persona=PersonaProfile(
            persona_id="coupled",
            dimensions=(
                make_profile(
                    "agent.affect.anxiety",
                    sensitivity=1.0,
                    coupling=(("agent.affect.longing", 0.5),),
                ),
                make_profile("agent.affect.longing"),
            ),
        )
    )


def test_coupling_spreads_delta_to_target() -> None:
    engine = make_coupled_engine()
    result = engine.step(
        current={"agent.affect.anxiety": 0.3, "agent.affect.longing": 0.3},
        elapsed=timedelta(0),
        impulses=(Impulse("agent.affect.anxiety", 0.4),),  # anxiety 0.3 -> 0.7
    )
    assert result.value_for("agent.affect.anxiety") == pytest.approx(0.7)
    # longing += (0.7 - 0.3) * 0.5 = 0.2 -> 0.5
    assert result.value_for("agent.affect.longing") == pytest.approx(0.5)


def test_coupling_contribution_is_traced() -> None:
    engine = make_coupled_engine()
    result = engine.step(
        current={"agent.affect.anxiety": 0.3, "agent.affect.longing": 0.3},
        elapsed=timedelta(0),
        impulses=(Impulse("agent.affect.anxiety", 0.4),),
    )
    assert any(
        c.dimension == "agent.affect.longing"
        and c.source == "coupling:agent.affect.anxiety"
        and c.amount == pytest.approx(0.2)
        for c in result.contributions
    )


def test_coupling_never_pushes_out_of_bounds() -> None:
    engine = DynamicsEngine(
        persona=PersonaProfile(
            persona_id="clamped",
            dimensions=(
                make_profile(
                    "agent.affect.anxiety",
                    sensitivity=1.0,
                    coupling=(("agent.affect.longing", 1.0),),
                ),
                make_profile("agent.affect.longing", ceiling=0.4),
            ),
        )
    )
    result = engine.step(
        current={"agent.affect.anxiety": 0.3, "agent.affect.longing": 0.3},
        elapsed=timedelta(0),
        impulses=(Impulse("agent.affect.anxiety", 0.5),),  # anxiety -> 0.8
    )
    # longing would receive +0.5 but is clamped at its ceiling 0.4.
    assert result.value_for("agent.affect.longing") == 0.4


def test_coupling_with_zero_strength_is_ignored() -> None:
    engine = DynamicsEngine(
        persona=PersonaProfile(
            persona_id="zero",
            dimensions=(
                make_profile(
                    "agent.affect.anxiety",
                    sensitivity=1.0,
                    coupling=(("agent.affect.longing", 0.0),),
                ),
                make_profile("agent.affect.longing"),
            ),
        )
    )
    result = engine.step(
        current={"agent.affect.anxiety": 0.3, "agent.affect.longing": 0.3},
        elapsed=timedelta(0),
        impulses=(Impulse("agent.affect.anxiety", 0.4),),
    )
    assert result.value_for("agent.affect.longing") == pytest.approx(0.3)
    assert not any(c.source.startswith("coupling:") for c in result.contributions)


def test_coupling_to_unknown_dimension_is_ignored() -> None:
    engine = DynamicsEngine(
        persona=PersonaProfile(
            persona_id="ghost",
            dimensions=(
                make_profile(
                    "agent.affect.anxiety",
                    sensitivity=1.0,
                    coupling=(("agent.affect.missing", 1.0),),
                ),
            ),
        )
    )
    result = engine.step(
        current={"agent.affect.anxiety": 0.3},
        elapsed=timedelta(0),
        impulses=(Impulse("agent.affect.anxiety", 0.4),),
    )
    assert result.value_for("agent.affect.anxiety") == pytest.approx(0.7)
    assert result.value_for("agent.affect.missing") is None


def test_coupled_step_is_replayable_and_explainable() -> None:
    engine = make_coupled_engine()
    current = {"agent.affect.anxiety": 0.3, "agent.affect.longing": 0.3}
    kwargs: dict[str, Any] = {
        "current": current,
        "elapsed": timedelta(minutes=10),
        "impulses": (Impulse("agent.affect.anxiety", 0.2),),
    }
    first = engine.step(**kwargs)
    second = engine.step(**kwargs)
    assert first == second
    # Every contribution names its source; no silent increments.
    assert all(c.source for c in first.contributions)
