"""Single Deterministic Surface Projection Authority.

Implements SurfaceProjectionPort according to ADR-0031.
Produces typed, derived, non-canonical SurfaceProjectionResult.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from copy import deepcopy
from typing import Any

from mind_runtime.contracts.surface import (
    SURFACE_INELIGIBLE_PERSONA,
    SURFACE_MISSING_STATE,
    SURFACE_NONFINITE,
    SURFACE_NUMERIC_TYPE,
    SURFACE_PERSONA_CONTENT_MISMATCH,
    SURFACE_RANGE,
    SURFACE_SCHEMA_MISMATCH,
    SurfaceProjectionResult,
    SurfaceProjectionStatus,
)
from mind_runtime.dynamics.persona import surface_digest
from mind_runtime.surface.evaluator import eval_ast
from mind_runtime.surface.recipe import (
    ALL_DECLARED_DYNAMICS_ROOTS,
    MANIFEST,
    dependency_payload,
    normalized_persona_content,
    normalized_recipe,
    validate_candidate_recipe,
)


def _authority_failure(
    supplied: Mapping[str, Any], recipe: Mapping[str, Any],
    persona: Mapping[str, Any], content: Mapping[str, Any],
    projected: Mapping[str, Any], states: list[Any],
) -> str | None:
    """Validate the orchestration binding before evaluating any recipe root."""
    runtime = supplied.get("runtime_id")
    scope = supplied.get("scope")
    owner = supplied.get("owner")
    ref = supplied.get("interaction_or_tick_ref")
    if not isinstance(runtime, str) or not runtime or not isinstance(ref, str) or not ref:
        return "SURFACE_LINEAGE_MISMATCH"
    if not isinstance(scope, Mapping) or not isinstance(owner, Mapping):
        return "SURFACE_LINEAGE_MISMATCH"
    if scope.get("domain") != "agent" or not isinstance(scope.get("persona_id"), str):
        return "SURFACE_SCOPE_MISMATCH"
    pid = persona.get("persona_id")
    version = persona.get("persona_version")
    digest = persona.get("persona_content_digest")
    if (
        not isinstance(pid, str) or not pid or type(version) is not int or version < 1
        or scope.get("persona_id") != pid
        or owner.get("owner_persona_id") != pid
        or owner.get("owner_runtime_id") != runtime
        or content.get("persona_id") != pid
        or content.get("profile_version") != version
        or not isinstance(digest, str) or not digest
    ):
        return "SURFACE_PERSONA_BINDING_MISMATCH"
    if (
        projected.get("runtime_id") != runtime
        or projected.get("scope") != scope
        or projected.get("owner") != owner
        or projected.get("interaction_or_tick_ref") != ref
    ):
        return "SURFACE_LINEAGE_MISMATCH"
    source_id = projected.get("source_projection_id")
    if (
        not isinstance(source_id, str) or not source_id
        or supplied.get("expected_source_projection_id") != source_id
    ):
        return "SURFACE_SOURCE_PROJECTION_MISMATCH"
    if projected.get("source_phase") not in ("projected", "committed"):
        return "SURFACE_SOURCE_PHASE_INVALID"
    if projected.get("persona_binding") != {
        "persona_id": pid, "persona_version": version,
        "persona_content_digest": digest,
    }:
        return "SURFACE_PERSONA_BINDING_MISMATCH"
    expected_recipe = {
        "recipe_id": recipe.get("recipe_id"),
        "recipe_version": recipe.get("recipe_version"),
        "recipe_digest": surface_digest("recipe", normalized_recipe(dict(recipe))),
    }
    if supplied.get("recipe_bindings") != [expected_recipe]:
        return "SURFACE_RECIPE_BINDING_MISMATCH"
    dimensions = content.get("dimensions")
    if not isinstance(dimensions, list):
        return "SURFACE_STATE_DEFINITION_MISMATCH"
    definitions = {
        d.get("dimension"): d for d in dimensions if isinstance(d, Mapping)
    }
    if len(definitions) != len(dimensions) or not isinstance(states, list):
        return "SURFACE_STATE_DEFINITION_MISMATCH"
    seen: set[str] = set()
    for state in states:
        if not isinstance(state, Mapping):
            return "SURFACE_STATE_AUTHORITY_MISMATCH"
        dimension = state.get("dimension")
        if not isinstance(dimension, str) or dimension in seen:
            return "SURFACE_STATE_AUTHORITY_MISMATCH"
        seen.add(dimension)
        definition = definitions.get(dimension)
        if not isinstance(definition, Mapping):
            return "SURFACE_STATE_DEFINITION_MISMATCH"
        if (
            not isinstance(state.get("state_id"), str) or not state["state_id"]
            or type(state.get("version")) is not int or state["version"] < 1
            or state.get("runtime_id") != runtime
            or state.get("scope") != scope
            or state.get("owner") != owner
        ):
            return "SURFACE_STATE_AUTHORITY_MISMATCH"
        if (
            state.get("value_type") != "scalar"
            or state.get("bounds") != [definition.get("floor"), definition.get("ceiling")]
        ):
            return "SURFACE_STATE_DEFINITION_MISMATCH"
    return None


class DeterministicSurfaceProjector:
    """Production Surface Projector.

    Evaluates Candidate Recipe v2 with authorized Dynamics snapshot and
    authorized PersonaProfile disposition. Fail-closed on any discrepancy.
    """

    def project(self, supplied: Mapping[str, Any]) -> SurfaceProjectionResult:
        """Execute one deterministic projection, failing closed on malformed input."""
        if not isinstance(supplied, Mapping):
            return SurfaceProjectionResult(
                status=SurfaceProjectionStatus.UNAVAILABLE,
                reasons=[SURFACE_SCHEMA_MISMATCH], controls=None,
            )
        try:
            return self._project_checked(supplied)
        except (KeyError, TypeError, ValueError, AttributeError, OverflowError):
            return SurfaceProjectionResult(
                status=SurfaceProjectionStatus.UNAVAILABLE,
                reasons=[SURFACE_SCHEMA_MISMATCH], controls=None,
            )

    def _project_checked(self, supplied: Mapping[str, Any]) -> SurfaceProjectionResult:
        recipe = supplied.get("recipe")
        if not isinstance(recipe, Mapping):
            return SurfaceProjectionResult(
                status=SurfaceProjectionStatus.UNAVAILABLE,
                reasons=["SURFACE_RECIPE_UNSUPPORTED"],
                controls=None,
            )

        recipe_ok, recipe_err = validate_candidate_recipe(dict(recipe))
        if not recipe_ok:
            return SurfaceProjectionResult(
                status=SurfaceProjectionStatus.UNAVAILABLE,
                reasons=[recipe_err or "SURFACE_RECIPE_CONTENT_CONFLICT"],
                controls=None,
            )

        # Persona validation
        persona = supplied.get("persona")
        if not isinstance(persona, Mapping):
            return SurfaceProjectionResult(
                status=SurfaceProjectionStatus.UNAVAILABLE,
                reasons=[SURFACE_INELIGIBLE_PERSONA],
                controls=None,
            )

        content = persona.get("content")
        if not isinstance(content, Mapping):
            return SurfaceProjectionResult(
                status=SurfaceProjectionStatus.UNAVAILABLE,
                reasons=[SURFACE_INELIGIBLE_PERSONA],
                controls=None,
            )

        if content.get("schema_version") != 2:
            return SurfaceProjectionResult(
                status=SurfaceProjectionStatus.UNAVAILABLE,
                reasons=[SURFACE_INELIGIBLE_PERSONA],
                controls=None,
            )

        disposition = content.get("behavioral_disposition")
        if not isinstance(disposition, Mapping):
            return SurfaceProjectionResult(
                status=SurfaceProjectionStatus.UNAVAILABLE,
                reasons=[SURFACE_INELIGIBLE_PERSONA],
                controls=None,
            )

        # Check persona content digest
        norm_content = normalized_persona_content(dict(content))
        expected_persona_digest = surface_digest("persona", norm_content)
        if persona.get("persona_content_digest") != expected_persona_digest:
            return SurfaceProjectionResult(
                status=SurfaceProjectionStatus.UNAVAILABLE,
                reasons=[SURFACE_PERSONA_CONTENT_MISMATCH],
                controls=None,
            )

        # Projected dynamics validation
        projected_dynamics = supplied.get("projected_dynamics")
        if not isinstance(projected_dynamics, Mapping):
            return SurfaceProjectionResult(
                status=SurfaceProjectionStatus.UNAVAILABLE,
                reasons=[SURFACE_MISSING_STATE],
                controls=None,
            )

        states_list = projected_dynamics.get("states", [])
        failure = _authority_failure(
            supplied, recipe, persona, content, projected_dynamics, states_list
        )
        if failure is not None:
            return SurfaceProjectionResult(
                status=SurfaceProjectionStatus.UNAVAILABLE,
                reasons=[failure], controls=None,
            )
        states_by_dim = {
            s["dimension"]: s for s in states_list if isinstance(s, Mapping) and "dimension" in s
        }

        # Check all declared dynamics roots
        for d in ALL_DECLARED_DYNAMICS_ROOTS:
            if d not in states_by_dim:
                return SurfaceProjectionResult(
                    status=SurfaceProjectionStatus.UNAVAILABLE,
                    reasons=[SURFACE_MISSING_STATE],
                    controls=None,
                )

        # Numeric validation on dynamics states
        for d in ALL_DECLARED_DYNAMICS_ROOTS:
            val = states_by_dim[d].get("value")
            if isinstance(val, bool) or val is None or not isinstance(val, (int, float)):
                return SurfaceProjectionResult(
                    status=SurfaceProjectionStatus.UNAVAILABLE,
                    reasons=[SURFACE_NUMERIC_TYPE],
                    controls=None,
                )
            if math.isnan(val) or math.isinf(val):
                return SurfaceProjectionResult(
                    status=SurfaceProjectionStatus.UNAVAILABLE,
                    reasons=[SURFACE_NONFINITE],
                    controls=None,
                )
            if val < 0.0 or val > 1.0:
                return SurfaceProjectionResult(
                    status=SurfaceProjectionStatus.UNAVAILABLE,
                    reasons=[SURFACE_RANGE],
                    controls=None,
                )

        # Numeric validation on disposition traits
        required_traits = (
            "attachment_approach",
            "confrontation_readiness",
            "expressive_restraint",
            "expressive_warmth_bias",
        )
        for trait_name in required_traits:
            if trait_name not in disposition:
                return SurfaceProjectionResult(
                    status=SurfaceProjectionStatus.UNAVAILABLE,
                    reasons=[SURFACE_INELIGIBLE_PERSONA],
                    controls=None,
                )
            t_val = disposition[trait_name]
            if isinstance(t_val, bool) or t_val is None or not isinstance(t_val, (int, float)):
                return SurfaceProjectionResult(
                    status=SurfaceProjectionStatus.UNAVAILABLE,
                    reasons=[SURFACE_NUMERIC_TYPE],
                    controls=None,
                )
            if math.isnan(t_val) or math.isinf(t_val):
                return SurfaceProjectionResult(
                    status=SurfaceProjectionStatus.UNAVAILABLE,
                    reasons=[SURFACE_NONFINITE],
                    controls=None,
                )
            if t_val < 0.0 or t_val > 1.0:
                return SurfaceProjectionResult(
                    status=SurfaceProjectionStatus.UNAVAILABLE,
                    reasons=[SURFACE_RANGE],
                    controls=None,
                )

        # AST Evaluation
        norm_r = normalized_recipe(dict(recipe))
        values: dict[str, float] = {}
        audit: dict[str, dict[str, Any]] = {}
        for rule in norm_r["rules"]:
            k = rule["control_id"]
            formula = rule["formula"]
            raw = round(eval_ast(formula[1], states_by_dim, disposition), 9)
            lo = eval_ast(formula[2], states_by_dim, disposition)
            hi = eval_ast(formula[3], states_by_dim, disposition)
            clamped = raw < lo or raw > hi
            val = max(lo, min(hi, raw))
            if val == 0.0:
                val = 0.0
            values[k] = round(val, 3)
            audit[k] = {"unclamped": round(raw, 3), "clamped": clamped}

        # Build lineage and digests
        payload = dependency_payload(supplied)
        source_states = [
            {
                "dimension": d,
                "state_id": states_by_dim[d]["state_id"],
                "version": states_by_dim[d]["version"],
                "value_digest": surface_digest("state-value", states_by_dim[d]["value"]),
            }
            for d in ALL_DECLARED_DYNAMICS_ROOTS
        ]

        out: dict[str, Any] = {
            "controls_id": "",
            "runtime_id": supplied["runtime_id"],
            "scope": supplied["scope"],
            "owner": supplied["owner"],
            "interaction_or_tick_ref": supplied["interaction_or_tick_ref"],
            "persona_id": persona["persona_id"],
            "persona_version": persona["persona_version"],
            "persona_content_digest": persona["persona_content_digest"],
            "source_projection_id": projected_dynamics["source_projection_id"],
            "source_phase": projected_dynamics["source_phase"],
            "source_states": source_states,
            "projector_id": recipe["projector_id"],
            "projector_version": recipe["projector_version"],
            "recipe_id": recipe["recipe_id"],
            "recipe_version": recipe["recipe_version"],
            "recipe_digest": surface_digest("recipe", norm_r),
            "dependency_digest": surface_digest("dependencies", payload),
            "dependency_digests_by_control": {
                k: surface_digest("control-dependencies", v) for k, v in payload.items()
            },
            "values": values,
            "dependencies_by_control": deepcopy(MANIFEST),
            "evaluation_ref": supplied["evaluation_ref"],
            "audit": audit,
            "derived_only": True,
            "canonical": False,
        }
        semantic = {
            k: v for k, v in out.items() if k not in ("controls_id", "evaluation_ref")
        }
        out["controls_id"] = "surface:" + surface_digest("controls", semantic)

        return SurfaceProjectionResult(
            status=SurfaceProjectionStatus.AVAILABLE,
            reasons=[],
            controls=out,
        )
