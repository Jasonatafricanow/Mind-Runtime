"""MR-ALPHA-AS1: Harness conftest helpers — registration of longitudinal
dimensions and seeded evidence trajectories.

The orchestrator's slow-plasticity seam is fail-closed:
`resolve_longitudinal_target` raises if a decision's target dimension is
not registered as longitudinal. To exercise the synthetic slow-state path
without modifying production semantics, the harness pre-registers a fixed
set of dimensions matching the synthetic emotional-transition's targets.

This module is harness-only.  It is NOT production code.
"""

from __future__ import annotations

from mind_runtime.state.definitions import StateDefinitionRegistry
from mind_runtime.state.longitudinal import register_longitudinal_definition

__all__ = ["build_harness_definitions", "HARNESS_LONGITUDINAL_DIMENSIONS"]

# Dimensions the harness emotional transition targets.
# These are the *fast* (agent.affect.*) dimensions whose accumulation the
# synthetic slow writer maps to agent.slow.* via its own internal prefix
# substitution (see SyntheticSlowStateAdapter.accept()).
HARNESS_LONGITUDINAL_DIMENSIONS: tuple[str, ...] = (
    "agent.affect.anxiety",
    "agent.affect.affiliation",
    "agent.affect.agency",
    "agent.affect.confidence",
)


def build_harness_definitions() -> StateDefinitionRegistry:
    """Build a StateDefinitionRegistry with all harness longitudinal dims.

    Returns a fresh registry each call (caller owns it).
    """
    registry = StateDefinitionRegistry()
    for dim in HARNESS_LONGITUDINAL_DIMENSIONS:
        register_longitudinal_definition(registry, key=dim, bounds=(0.0, 1.0))
    return registry