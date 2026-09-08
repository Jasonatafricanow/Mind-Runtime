"""D7.6 kayla_v0 fixture and G7 golden driver tests."""

from datetime import UTC, datetime, timedelta

from mind_runtime.dynamics.engine import DynamicsEngine, Impulse
from mind_runtime.dynamics.kayla_v0 import kayla_v0_profile
from mind_runtime.dynamics.persona import PersonaProfile
from tests.golden.fixtures.common import make_persona

NOW = datetime(2026, 8, 22, 23, 30, tzinfo=UTC)


def test_kayla_v0_is_a_fixture_not_kernel_defaults() -> None:
    profile = kayla_v0_profile()
    assert profile.persona_id == "kayla_v0"
    assert profile.dimension_keys() == (
        "agent.affect.longing",
        "agent.affect.irritation",
        "agent.affect.anxiety",
        "agent.affect.excitement",
    )
    # Parameters are config-like values, not hard-coded kernel defaults:
    # the engine must be able to run with them replayably.
    engine = DynamicsEngine(persona=profile)
    result = engine.step(
        current={},
        elapsed=timedelta(hours=1),
        impulses=(Impulse("agent.affect.longing", 0.5),),
    )
    assert result.value_for("agent.affect.longing") is not None


def test_g7_same_impulse_different_sensitivity_different_transition() -> None:
    """G7 core: identical input, divergent persona sensitivity -> small vs large."""
    low_profile = make_persona(dimension="agent.trait.abandonment_sensitivity", sensitivity=0.2)
    high_profile = make_persona(
        dimension="agent.trait.abandonment_sensitivity_high", sensitivity=0.9
    )
    impulse = Impulse("agent.affect.anxiety", 0.5, source_ref="g7")

    def transition_size(sensitivity: float) -> str:
        # Test-side mapping: the trait sensitivity scales the anxiety impulse.
        from mind_runtime.contracts import AffectiveDimensionProfile

        anxiety = AffectiveDimensionProfile(
            dimension="agent.affect.anxiety",
            baseline=0.25,
            initial_value=0.25,
            sensitivity=sensitivity,
            recovery_rate=0.3,
            ceiling=1.0,
            floor=0.0,
            growth_profile=(),
            coupling_profile=(),
        )
        engine = DynamicsEngine(persona=PersonaProfile(persona_id="g7", dimensions=(anxiety,)))
        result = engine.step(
            current={"agent.affect.anxiety": 0.25},
            elapsed=timedelta(0),
            impulses=(impulse,),
        )
        value = result.value_for("agent.affect.anxiety")
        assert value is not None
        delta = value - 0.25
        return "large" if delta >= 0.25 else "small"

    assert transition_size(low_profile.sensitivity) == "small"
    assert transition_size(high_profile.sensitivity) == "large"
