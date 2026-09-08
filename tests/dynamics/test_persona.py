"""D7.1 persona profile tests: traits never carry current state."""

from datetime import UTC, datetime

import pytest

from mind_runtime.contracts import AffectiveDimensionProfile
from mind_runtime.dynamics.persona import PersonaProfile

NOW = datetime(2026, 8, 22, 20, 0, tzinfo=UTC)


def make_dimension(
    dimension: str = "agent.affect.longing",
    *,
    sensitivity: float = 0.6,
    baseline: float = 0.3,
) -> AffectiveDimensionProfile:
    return AffectiveDimensionProfile(
        dimension=dimension,
        baseline=baseline,
        initial_value=baseline,
        sensitivity=sensitivity,
        recovery_rate=0.2,
        ceiling=1.0,
        floor=0.0,
        growth_profile=(("growth", 0.05),),
        coupling_profile=(),
    )


def make_persona(*dimensions: AffectiveDimensionProfile) -> PersonaProfile:
    return PersonaProfile(persona_id="kayla", dimensions=dimensions)


def test_profile_carries_only_trait_parameters() -> None:
    profile = make_dimension()
    persona = make_persona(profile)
    assert persona.persona_id == "kayla"
    assert persona.version == 1
    assert persona.dimension_keys() == ("agent.affect.longing",)
    loaded = persona.require_dimension("agent.affect.longing")
    assert loaded is profile
    # Trait values only: baseline/initial/sensitivity/recovery/bounds/coupling.
    assert loaded.baseline == 0.3
    assert loaded.initial_value == 0.3
    assert loaded.sensitivity == 0.6
    assert loaded.recovery_rate == 0.2
    assert loaded.ceiling == 1.0
    assert loaded.floor == 0.0
    # The D1 contract has no current-value field at all.
    assert not hasattr(profile, "current_value")
    assert not hasattr(persona, "current_values")


def test_for_dimension_unknown_returns_none() -> None:
    persona = make_persona(make_dimension())
    assert persona.for_dimension("agent.affect.irritation") is None
    with pytest.raises(ValueError, match="no dimension"):
        persona.require_dimension("agent.affect.irritation")


def test_persona_rejects_duplicate_dimensions() -> None:
    with pytest.raises(ValueError, match="duplicate"):
        make_persona(make_dimension(), make_dimension())


def test_persona_rejects_empty_id() -> None:
    with pytest.raises(ValueError, match="non-empty"):
        PersonaProfile(persona_id="", dimensions=())


def test_persona_rejects_non_positive_version() -> None:
    with pytest.raises(ValueError, match="version"):
        PersonaProfile(persona_id="kayla", dimensions=(), version=0)


def test_multi_dimension_persona() -> None:
    persona = make_persona(
        make_dimension("agent.affect.longing"),
        make_dimension("agent.affect.irritation"),
        make_dimension("agent.affect.anxiety"),
    )
    assert len(persona.dimension_keys()) == 3
    assert persona.for_dimension("agent.affect.anxiety") is not None
