"""kayla_v0 compatibility profile (D7.6).

Fixture-only parameters: this profile exists for compatibility tests and
golden scenarios; its numbers are NOT kernel defaults and must never leak
into the core schema. Real parameters land in config/fixtures.
"""

from mind_runtime.contracts import AffectiveDimensionProfile
from mind_runtime.dynamics.persona import PersonaProfile


def _dimension(
    dimension: str,
    *,
    baseline: float,
    sensitivity: float,
    recovery_rate: float,
    coupling: tuple[tuple[str, float], ...] = (),
) -> AffectiveDimensionProfile:
    return AffectiveDimensionProfile(
        dimension=dimension,
        baseline=baseline,
        initial_value=baseline,
        sensitivity=sensitivity,
        recovery_rate=recovery_rate,
        ceiling=1.0,
        floor=0.0,
        growth_profile=(),
        coupling_profile=coupling,
    )


def kayla_v0_profile() -> PersonaProfile:
    """Kayla compatibility profile (test fixture only, not kernel defaults)."""
    return PersonaProfile(
        persona_id="kayla_v0",
        dimensions=(
            _dimension("agent.affect.longing", baseline=0.30, sensitivity=0.8, recovery_rate=0.15),
            _dimension(
                "agent.affect.irritation", baseline=0.20, sensitivity=0.6, recovery_rate=0.25
            ),
            _dimension("agent.affect.anxiety", baseline=0.25, sensitivity=0.7, recovery_rate=0.30),
            _dimension(
                "agent.affect.excitement", baseline=0.30, sensitivity=0.9, recovery_rate=0.40
            ),
        ),
    )
