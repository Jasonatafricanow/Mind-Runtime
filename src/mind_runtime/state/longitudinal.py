"""C10-B-W longitudinal target registry authority.

This module is the **registry authority** for longitudinal dimensions.
It does NOT derive, infer, or guess targets.

Per `docs/C10_LONGITUDINAL_TARGET_ONTOLOGY_CONTRACT.md`:

  - Longitudinal dimension identity comes from explicit configuration.
  - The kernel is dimension-agnostic.
  - The writer consumes `target_dimension` verbatim.
  - Layer identity is carried by Gate authority + `dynamics_policy`,
    NOT by dimension-string inspection.

What this module does:

  - Defines the frozen `LONGITUDINAL_ACCUMULATOR` and
    `LONGITUDINAL_INDEFINITE` policy strings.
  - Defines `register_longitudinal_definition()`: explicit single-dim
    registration. Caller must specify the exact dimension key.
  - Defines `resolve_longitudinal_target()`: fail-closed lookup that
    verifies the dimension is registered AND its dynamics_policy is
    longitudinal. Returns the `StateDefinition` or raises `ValueError`.

What this module does NOT do (per ticket C10-BW-UPSTREAM-R):

  - Does NOT derive `agent.slow.X` from `agent.affect.X`.
  - Does NOT provide any affect-form fallback.
  - Does NOT auto-create longitudinal definitions from a persona's
    affect dimensions.
  - Does NOT provide prefix-stripping or suffix-reuse helpers.

Mapping authority belongs to configuration (the `EventEffectRule`
records `longitudinal_target_dimension` explicitly). The registry
only answers: "is this dimension already registered as longitudinal?"
"""

from __future__ import annotations

from mind_runtime.contracts import StateDefinition, StateDomain, StateValueType
from mind_runtime.state.definitions import StateDefinitionRegistry


# ============================================================================
# Frozen longitudinal policy vocabulary
# ============================================================================

LONGITUDINAL_ACCUMULATOR: str = "accumulator"
LONGITUDINAL_INDEFINITE: str = "indefinite"


def is_longitudinal_policy(dynamics_policy: str) -> bool:
    """ReturnTrue iff `dynamics_policy` marks a dimension as longitudinal."""
    return dynamics_policy == LONGITUDINAL_ACCUMULATOR


def require_longitudinal_policy(dynamics_policy: str, *, key: str) -> None:
    """Fail-closed assertion that a registered dimension is longitudinal."""
    if not is_longitudinal_policy(dynamics_policy):
        raise ValueError(
            f"dimension {key!r} has dynamics_policy={dynamics_policy!r}; "
            f"expected longitudinal policy {LONGITUDINAL_ACCUMULATOR!r}"
        )


# ============================================================================
# Explicit longitudinal registration
# ============================================================================


def register_longitudinal_definition(
    registry: StateDefinitionRegistry,
    *,
    key: str,
    bounds: tuple[float, float] = (0.0, 1.0),
) -> StateDefinition:
    """Register one explicit longitudinal StateDefinition.

    The caller must specify the exact dimension key. There is no
    automatic mapping from any other namespace.

    Returns the registered `StateDefinition`. If a definition is already
    registered with the same key, returns the existing definition
    (idempotent — production callers may re-register on restart).

    Raises `ValueError` if the existing registration has a different
    `dynamics_policy` (conflict detection; prevents accidental override).
    """
    from mind_runtime.contracts.common import require_non_empty

    require_non_empty(key, "key")
    existing = registry.get(key)
    if existing is not None:
        if existing.dynamics_policy != LONGITUDINAL_ACCUMULATOR:
            raise ValueError(
                f"dimension {key!r} already registered with "
                f"dynamics_policy={existing.dynamics_policy!r}; "
                f"conflicts with longitudinal policy {LONGITUDINAL_ACCUMULATOR!r}"
            )
        return existing

    definition = StateDefinition(
        key=key,
        domain=StateDomain.AGENT,
        value_type=StateValueType.SCALAR,
        dynamics_policy=LONGITUDINAL_ACCUMULATOR,
        default_validity_policy=LONGITUDINAL_INDEFINITE,
        bounds=bounds,
    )
    registry.register(definition)
    return definition


# ============================================================================
# Seam assertion
# ============================================================================


def resolve_longitudinal_target(
    registry: StateDefinitionRegistry,
    target_dimension: str,
) -> StateDefinition:
    """Resolve a target dimension via the registry and assert longitudinal.

    Fails closed if the dimension is unregistered or if its
    `dynamics_policy` is not longitudinal.

    Per ticket C10-BW-UPSTREAM-R §3:

        "B-W seam 只能执行:
         decision.candidate.target_dimension → registry lookup"

    No prefix replacement, no suffix reuse, no affect-form fallback,
    no default slow counterpart.

    Returns the `StateDefinition`. Raises `ValueError` on:
        - unregistered dimension
        - registered dimension with non-longitudinal dynamics_policy
    """
    definition = registry.get(target_dimension)
    if definition is None:
        raise ValueError(
            f"longitudinal target {target_dimension!r} is not registered in "
            f"StateDefinitionRegistry; cannot route into B-W writer"
        )
    require_longitudinal_policy(definition.dynamics_policy, key=target_dimension)
    return definition


__all__ = [
    "LONGITUDINAL_ACCUMULATOR",
    "LONGITUDINAL_INDEFINITE",
    "is_longitudinal_policy",
    "require_longitudinal_policy",
    "register_longitudinal_definition",
    "resolve_longitudinal_target",
]