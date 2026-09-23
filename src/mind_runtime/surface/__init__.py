"""Mind Runtime Surface Package.

Frozen under ADR-0028.
Single deterministic Surface projection authority.
"""

from __future__ import annotations

from mind_runtime.contracts.surface import (
    DEFERRED_CONTROLS,
    ENABLED_CONTROLS,
    SURFACE_INELIGIBLE_PERSONA,
    SURFACE_MISSING_STATE,
    SURFACE_NONFINITE,
    SURFACE_NUMERIC_TYPE,
    SURFACE_PERSONA_CONTENT_MISMATCH,
    SURFACE_RANGE,
    SURFACE_RECIPE_CONTENT_CONFLICT,
    SURFACE_RECIPE_UNSUPPORTED,
    SURFACE_SCHEMA_MISMATCH,
    SurfaceControl,
    SurfaceProjectionPort,
    SurfaceProjectionResult,
    SurfaceProjectionStatus,
)
from mind_runtime.surface.adapter import SurfaceProductionAdapter
from mind_runtime.surface.cognition import project_surface_for_cognition
from mind_runtime.surface.evaluator import eval_ast, extract_ast_lookups, validate_ast_primitives
from mind_runtime.surface.expression_map import (
    CANDIDATE_EXPRESSION_MAP_V2,
    CANDIDATE_MAP_DIGEST,
    CANDIDATE_MAP_ID,
    CANDIDATE_MAP_VERSION,
    candidate_expression_map,
    evaluate_control_band,
    map_surface_to_qualitative_guidance,
    normalized_expression_map,
    validate_expression_map,
)
from mind_runtime.surface.projector import DeterministicSurfaceProjector
from mind_runtime.surface.recipe import (
    CANDIDATE_RECIPE_DIGEST,
    CANDIDATE_RECIPE_ID,
    CANDIDATE_RECIPE_VERSION,
    MANIFEST,
    candidate_recipe,
    dependency_payload,
    normalized_persona_content,
    normalized_recipe,
    validate_candidate_recipe,
)

__all__ = [
    "CANDIDATE_EXPRESSION_MAP_V2",
    "CANDIDATE_MAP_DIGEST",
    "CANDIDATE_MAP_ID",
    "CANDIDATE_MAP_VERSION",
    "CANDIDATE_RECIPE_DIGEST",
    "CANDIDATE_RECIPE_ID",
    "CANDIDATE_RECIPE_VERSION",
    "DEFERRED_CONTROLS",
    "DeterministicSurfaceProjector",
    "ENABLED_CONTROLS",
    "MANIFEST",
    "candidate_expression_map",
    "candidate_recipe",
    "evaluate_control_band",
    "map_surface_to_qualitative_guidance",
    "normalized_expression_map",
    "project_surface_for_cognition",
    "SURFACE_INELIGIBLE_PERSONA",
    "SURFACE_MISSING_STATE",
    "SURFACE_NONFINITE",
    "SURFACE_NUMERIC_TYPE",
    "SURFACE_PERSONA_CONTENT_MISMATCH",
    "SURFACE_RANGE",
    "SURFACE_RECIPE_CONTENT_CONFLICT",
    "SURFACE_RECIPE_UNSUPPORTED",
    "SURFACE_SCHEMA_MISMATCH",
    "SurfaceControl",
    "SurfaceProductionAdapter",
    "SurfaceProjectionPort",
    "SurfaceProjectionResult",
    "SurfaceProjectionStatus",
    "dependency_payload",
    "eval_ast",
    "extract_ast_lookups",
    "normalized_persona_content",
    "normalized_recipe",
    "validate_ast_primitives",
    "validate_candidate_recipe",
    "validate_expression_map",
]
