"""Shared fail-closed validation of a derived Surface consumer boundary."""

from __future__ import annotations

from collections.abc import Mapping
from math import isfinite

from mind_runtime.contracts.projection import ProjectedMindState
from mind_runtime.contracts.surface import SurfaceProjectionResult
from mind_runtime.dynamics.persona import surface_digest
from mind_runtime.surface.recipe import (
    ALL_DECLARED_DYNAMICS_ROOTS,
    CANDIDATE_RECIPE_DIGEST,
    CANDIDATE_RECIPE_ID,
    CANDIDATE_RECIPE_VERSION,
    MANIFEST,
)


def _scope_wire(scope: object) -> dict[str, object]:
    domain = getattr(scope, "domain", None)
    return {
        "domain": domain.value if domain is not None and hasattr(domain, "value") else None,
        "agent_id": getattr(scope, "agent_id", None),
        "persona_id": getattr(scope, "persona_id", None),
        "user_id": getattr(scope, "user_id", None),
        "relationship_id": getattr(scope, "relationship_id", None),
        "world_id": getattr(scope, "world_id", None),
        "interaction_id": getattr(scope, "interaction_id", None),
    }


def validate_projected_surface(
    surface: SurfaceProjectionResult,
    *,
    projected: ProjectedMindState,
    runtime_id: str,
    interaction_or_tick_ref: str,
    persona_id: str | None,
    persona_version: int | None,
    persona_content_digest: str | None,
) -> bool:
    """Validate typed identity and consumed roots; never evaluate recipe here."""
    if type(surface) is not SurfaceProjectionResult or surface.status != "AVAILABLE":
        return False
    controls = surface.controls
    if not isinstance(controls, Mapping):
        return False
    if (
        not persona_id or type(persona_version) is not int
        or not persona_content_digest
        or projected.origin_runtime_id != runtime_id
        or controls.get("runtime_id") != runtime_id
        or controls.get("scope") != _scope_wire(projected.scope)
        or controls.get("owner") != {
            "owner_runtime_id": runtime_id,
            "owner_persona_id": persona_id,
        }
        or controls.get("interaction_or_tick_ref") != interaction_or_tick_ref
        or controls.get("persona_id") != persona_id
        or controls.get("persona_version") != persona_version
        or controls.get("persona_content_digest") != persona_content_digest
        or controls.get("source_projection_id") != projected.projection_id
        or controls.get("source_phase") != "projected"
        or controls.get("recipe_id") != CANDIDATE_RECIPE_ID
        or controls.get("recipe_version") != CANDIDATE_RECIPE_VERSION
        or controls.get("recipe_digest") != CANDIDATE_RECIPE_DIGEST
        or controls.get("dependencies_by_control") != MANIFEST
        or controls.get("derived_only") is not True
        or controls.get("canonical") is not False
    ):
        return False
    values = controls.get("values")
    if not isinstance(values, Mapping) or set(values) != set(MANIFEST):
        return False
    if any(type(value) is not float or not isfinite(value) or not 0 <= value <= 1
           for value in values.values()):
        return False
    semantic = {key: value for key, value in controls.items()
                if key not in ("controls_id", "evaluation_ref")}
    try:
        if controls.get("controls_id") != "surface:" + surface_digest("controls", semantic):
            return False
        actual_sources = controls.get("source_states")
        if not isinstance(actual_sources, (list, tuple)):
            return False
        roots = {state.dimension: state for state in projected.projected_states
                 if state.dimension in ALL_DECLARED_DYNAMICS_ROOTS}
        if set(roots) != set(ALL_DECLARED_DYNAMICS_ROOTS):
            return False
        expected_sources = [
            {
                "dimension": name,
                "state_id": roots[name].state_id,
                "version": roots[name].version,
                "value_digest": surface_digest("state-value", roots[name].value),
            }
            for name in ALL_DECLARED_DYNAMICS_ROOTS
        ]
        if actual_sources != expected_sources:
            return False
        if any(state.origin_runtime_id != runtime_id or state.scope != projected.scope
               for state in roots.values()):
            return False
    except (TypeError, ValueError, KeyError):
        return False
    return True
