"""Single Deterministic Surface Projection Authority.

Implements SurfaceProjectionPort according to ADR-0028.
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


class DeterministicSurfaceProjector:
    """Production Surface Projector.

    Evaluates Candidate Recipe v2 with authorized Dynamics snapshot and
    authorized PersonaProfile disposition. Fail-closed on any discrepancy.
    """

    def project(self, supplied: Mapping[str, Any]) -> SurfaceProjectionResult:
        """Execute single deterministic surface projection."""
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
