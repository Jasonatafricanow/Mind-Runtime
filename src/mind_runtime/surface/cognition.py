"""Surface projection integration for turn orchestration and cognitive ticker (W3-C).

Integrates the single SurfaceProjectionPort into TurnOrchestrator and CognitiveTicker
without bypassing ActionPolicy or creating a second personality authority.
"""

from __future__ import annotations

from typing import Any

from mind_runtime.contracts.projection import ProjectedMindState
from mind_runtime.contracts.scope import Scope
from mind_runtime.contracts.surface import (
    SurfaceProjectionPort,
    SurfaceProjectionResult,
)
from mind_runtime.dynamics.persona import PersonaProfile
from mind_runtime.surface.recipe import candidate_recipe


def project_surface_for_cognition(
    *,
    surface_port: SurfaceProjectionPort | None,
    persona: PersonaProfile | None,
    projected: ProjectedMindState,
    runtime_id: str,
    scope: Scope,
    interaction_or_tick_ref: str,
    recipe: dict[str, Any] | None = None,
) -> SurfaceProjectionResult | None:
    """Project Surface for turn or tick if port and persona are available and eligible."""
    if surface_port is None or persona is None:
        return None
    if not persona.is_surface_eligible:
        return None

    if recipe is None:
        recipe = candidate_recipe()

    def _scope_to_dict(sc: Scope | Any) -> dict[str, Any]:
        domain = getattr(sc, "domain", None)
        return {
            "domain": domain.value if hasattr(domain, "value") else str(domain) if domain else None,
            "agent_id": getattr(sc, "agent_id", None),
            "persona_id": getattr(sc, "persona_id", None),
            "user_id": getattr(sc, "user_id", None),
            "relationship_id": getattr(sc, "relationship_id", None),
            "world_id": getattr(sc, "world_id", None),
            "interaction_id": getattr(sc, "interaction_id", None),
        }

    scope_dict = _scope_to_dict(scope)

    states = [
        {
            "dimension": s.dimension,
            "state_id": s.state_id,
            "version": s.version,
            "value": s.value,
            "bounds": [0.0, 1.0],
            "value_type": "scalar",
            "runtime_id": runtime_id,
            "scope": _scope_to_dict(s.scope),
            "owner": {
                "owner_runtime_id": runtime_id,
                "owner_persona_id": persona.persona_id,
            },
        }
        for s in projected.projected_states
    ]

    content = {
        "schema_version": persona.schema_version,
        "profile_version": persona.version,
        "persona_id": persona.persona_id,
        "dimensions": [
            {
                "dimension": d.dimension,
                "baseline": d.baseline,
                "initial_value": d.initial_value,
                "sensitivity": d.sensitivity,
                "recovery_rate": d.recovery_rate,
                "floor": d.floor,
                "ceiling": d.ceiling,
                "growth_profile": [[k, v] for k, v in d.growth_profile],
                "coupling_profile": [[k, v] for k, v in d.coupling_profile],
            }
            for d in persona.dimensions
        ],
        "behavioral_disposition": {
            "attachment_approach": float(
                persona.behavioral_disposition["attachment_approach"]
            ),
            "confrontation_readiness": float(
                persona.behavioral_disposition["confrontation_readiness"]
            ),
            "expressive_restraint": float(
                persona.behavioral_disposition["expressive_restraint"]
            ),
            "expressive_warmth_bias": float(
                persona.behavioral_disposition["expressive_warmth_bias"]
            ),
        }
        if persona.behavioral_disposition is not None
        else {},
    }

    supplied = {
        "runtime_id": runtime_id,
        "scope": scope_dict,
        "owner": {
            "owner_runtime_id": runtime_id,
            "owner_persona_id": persona.persona_id,
        },
        "interaction_or_tick_ref": interaction_or_tick_ref,
        "evaluation_ref": f"eval:{interaction_or_tick_ref}",
        "expected_source_projection_id": projected.projection_id,
        "persona": {
            "persona_id": persona.persona_id,
            "persona_version": persona.version,
            "persona_content_digest": persona.persona_content_digest,
            "content": content,
        },
        "projected_dynamics": {
            "source_projection_id": projected.projection_id,
            "source_phase": "projected",
            "runtime_id": runtime_id,
            "interaction_or_tick_ref": interaction_or_tick_ref,
            "scope": scope_dict,
            "owner": {
                "owner_runtime_id": runtime_id,
                "owner_persona_id": persona.persona_id,
            },
            "states": states,
        },
        "recipe": recipe,
        "recipe_bindings": [],
    }

    return surface_port.project(supplied)
