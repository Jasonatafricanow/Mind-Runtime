"""Mind Runtime Candidate Expression Map Authority (Surface Re-export).

Frozen under ADR-0031 and MR-SURFACE-V1-CANDIDATE-EXPRESSION-MAP-01.
Re-exports from mind_runtime.expression.expression_map.
"""

from __future__ import annotations

from mind_runtime.expression.expression_map import (
    CANDIDATE_EXPRESSION_MAP_V2,
    CANDIDATE_MAP_DIGEST,
    CANDIDATE_MAP_ID,
    CANDIDATE_MAP_VERSION,
    CANDIDATE_RECIPE_DIGEST,
    CANDIDATE_RECIPE_ID,
    CANDIDATE_RECIPE_VERSION,
    CONTROL_TO_GUIDANCE,
    GUIDANCE_TO_CONTROL,
    SURFACE_EXPRESSION_CONTROL_MISSING,
    SURFACE_EXPRESSION_MAP_CONFLICT,
    SURFACE_EXPRESSION_NONFINITE,
    SURFACE_EXPRESSION_RANGE,
    SURFACE_EXPRESSION_RECIPE_MISMATCH,
    candidate_expression_map,
    canonical_surface_wire,
    compute_map_digest,
    evaluate_control_band,
    map_surface_to_qualitative_guidance,
    normalized_expression_map,
    validate_expression_map,
)

__all__ = [
    "CANDIDATE_EXPRESSION_MAP_V2",
    "CANDIDATE_MAP_DIGEST",
    "CANDIDATE_MAP_ID",
    "CANDIDATE_MAP_VERSION",
    "CANDIDATE_RECIPE_DIGEST",
    "CANDIDATE_RECIPE_ID",
    "CANDIDATE_RECIPE_VERSION",
    "CONTROL_TO_GUIDANCE",
    "GUIDANCE_TO_CONTROL",
    "SURFACE_EXPRESSION_CONTROL_MISSING",
    "SURFACE_EXPRESSION_MAP_CONFLICT",
    "SURFACE_EXPRESSION_NONFINITE",
    "SURFACE_EXPRESSION_RANGE",
    "SURFACE_EXPRESSION_RECIPE_MISMATCH",
    "candidate_expression_map",
    "canonical_surface_wire",
    "compute_map_digest",
    "evaluate_control_band",
    "map_surface_to_qualitative_guidance",
    "normalized_expression_map",
    "validate_expression_map",
]
