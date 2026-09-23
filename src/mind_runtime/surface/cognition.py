"""Surface projection integration for turn orchestration and cognitive ticker (W3-C).

Integrates the single SurfaceProjectionPort into TurnOrchestrator and CognitiveTicker
without bypassing ActionPolicy or creating a second personality authority.
"""

from __future__ import annotations

from typing import Any

from mind_runtime.contracts.projection import ProjectedMindState
from mind_runtime.contracts.scope import Scope
from mind_runtime.contracts.common import SyncFields
from mind_runtime.contracts.surface import (
    SurfaceProjectionPort,
    SurfaceProjectionResult,
)
from mind_runtime.dynamics.persona import PersonaProfile, surface_digest
from mind_runtime.surface.recipe import candidate_recipe, normalized_recipe


def recompute_committed_surface(
    *,
    surface_port: SurfaceProjectionPort,
    persona_publication: "PersonaConfigPublicationRepository",
    persona_revision_ref: "PersonaRevisionRef",
    state_backend: "SqliteStateBackend",
    commit_markers: "SqliteCommitMarkerStore",
    interaction_id: str,
    interaction_scope: Scope,
    runtime_id: str,
) -> SurfaceProjectionResult:
    """Derive COMMITTED Surface from a real persisted commit and exact Persona.

    Neither Surface nor a test snapshot is persisted. Missing historical
    Persona/state/commit material fails closed before the projector runs.
    """
    from mind_runtime.persona_publication import (
        PersonaConfigPublicationRepository, PersonaRevisionRef, ReplayUnavailable,
    )
    from mind_runtime.state.persistence import SqliteCommitMarkerStore, SqliteStateBackend
    from mind_runtime.surface.recipe import ALL_DECLARED_DYNAMICS_ROOTS

    if not isinstance(persona_publication, PersonaConfigPublicationRepository):
        raise TypeError("persona_publication must be an immutable publication repository")
    if not isinstance(persona_revision_ref, PersonaRevisionRef):
        raise TypeError("persona_revision_ref must be exact")
    if not isinstance(state_backend, SqliteStateBackend) or not isinstance(commit_markers, SqliteCommitMarkerStore):
        raise TypeError("canonical SQLite state and commit authorities are required")
    try:
        ids = commit_markers.committed_state_ids(
            interaction_id=interaction_id, scope=interaction_scope,
        )
    except (ValueError, TypeError) as exc:
        raise ReplayUnavailable("REPLAY_UNAVAILABLE: canonical commit marker malformed") from exc
    if ids is None:
        raise ReplayUnavailable("REPLAY_UNAVAILABLE: canonical commit marker missing")
    persona = persona_publication.resolve(persona_revision_ref).profile
    all_states = state_backend.load_states()
    selected = []
    for state_id in ids:
        matches = [state for state in all_states if (
            state.state_id == state_id
            and state.origin_runtime_id == runtime_id
            and state.scope.persona_id == persona.persona_id
        )]
        if len(matches) != 1:
            raise ReplayUnavailable("REPLAY_UNAVAILABLE: committed state missing or ambiguous")
        selected.append(matches[0])
    committed_states = tuple(selected)
    dimensions = {state.dimension for state in committed_states}
    if not set(ALL_DECLARED_DYNAMICS_ROOTS).issubset(dimensions):
        raise ReplayUnavailable("REPLAY_UNAVAILABLE: committed Dynamics roots incomplete")
    if (
        any(state.origin_runtime_id != runtime_id for state in committed_states)
        or len({state.scope for state in committed_states}) != 1
    ):
        raise ReplayUnavailable("REPLAY_UNAVAILABLE: committed owner mismatch")
    scope = committed_states[0].scope
    if scope.persona_id != persona.persona_id:
        raise ReplayUnavailable("REPLAY_UNAVAILABLE: committed Persona owner mismatch")
    projection_id = f"committed:{interaction_id}"
    projected = ProjectedMindState(
        projection_id=projection_id,
        scope=scope,
        origin_runtime_id=runtime_id,
        projected_states=committed_states,
        sync=SyncFields(scope, runtime_id, projection_id, 1, f"idem-{projection_id}"),
        committed=True,
    )
    result = project_surface_for_cognition(
        surface_port=surface_port, persona=persona, projected=projected,
        runtime_id=runtime_id, scope=scope,
        interaction_or_tick_ref=f"interaction:{interaction_id}",
    )
    if result is None or result.status != "AVAILABLE":
        raise ReplayUnavailable("REPLAY_UNAVAILABLE: committed Surface recomputation unavailable")
    return result


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
            "bounds": [
                persona.require_dimension(s.dimension).floor,
                persona.require_dimension(s.dimension).ceiling,
            ] if persona.for_dimension(s.dimension) is not None else None,
            "value_type": "scalar",
            "runtime_id": s.origin_runtime_id,
            "scope": _scope_to_dict(s.scope),
            "owner": {
                "owner_runtime_id": s.origin_runtime_id,
                "owner_persona_id": s.scope.persona_id,
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
            "source_phase": "committed" if projected.committed else "projected",
            "runtime_id": projected.origin_runtime_id,
            "interaction_or_tick_ref": interaction_or_tick_ref,
            "scope": _scope_to_dict(projected.scope),
            "owner": {
                "owner_runtime_id": projected.origin_runtime_id,
                "owner_persona_id": projected.scope.persona_id,
            },
            "persona_binding": {
                "persona_id": persona.persona_id,
                "persona_version": persona.version,
                "persona_content_digest": persona.persona_content_digest,
            },
            "states": states,
        },
        "recipe": recipe,
        "recipe_bindings": [{
            "recipe_id": recipe["recipe_id"],
            "recipe_version": recipe["recipe_version"],
            "recipe_digest": surface_digest("recipe", normalized_recipe(recipe)),
        }],
    }

    return surface_port.project(supplied)
