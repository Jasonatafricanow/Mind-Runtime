"""Mind Runtime Candidate Expression Map Authority.

Frozen under ADR-0028 and MR-SURFACE-V1-CANDIDATE-EXPRESSION-MAP-01.
Deterministic, versioned, immutable mapping from Surface controls into
bounded qualitative expression guidance.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
from typing import Any

CANDIDATE_RECIPE_ID = "surface-v1-candidate"
CANDIDATE_RECIPE_VERSION = 2
CANDIDATE_RECIPE_DIGEST = "4f37f46f89f6176fd5fefe0167ec7a81e341839f4fb9b98fa3cc348ddeaf9a55"

CANDIDATE_MAP_ID = "surface-v1-candidate-map"
CANDIDATE_MAP_VERSION = 2
CANDIDATE_MAP_DIGEST = "bba6794aeda7a1755f8c79ffe5c88bd100918e6bc979ea29b5aa009e958eddf3"

# Fail-closed reason codes
SURFACE_EXPRESSION_MAP_CONFLICT = "SURFACE_EXPRESSION_MAP_CONFLICT"
SURFACE_EXPRESSION_RECIPE_MISMATCH = "SURFACE_EXPRESSION_RECIPE_MISMATCH"
SURFACE_EXPRESSION_CONTROL_MISSING = "SURFACE_EXPRESSION_CONTROL_MISSING"
SURFACE_EXPRESSION_NONFINITE = "SURFACE_EXPRESSION_NONFINITE"
SURFACE_EXPRESSION_RANGE = "SURFACE_EXPRESSION_RANGE"

# Declared guidance mappings: guidance_dimension -> source_control
GUIDANCE_TO_CONTROL = {
    "directness": "confrontation",
    "restraint": "expressive_restraint",
    "warmth": "expressive_warmth",
}

CONTROL_TO_GUIDANCE = {v: k for k, v in GUIDANCE_TO_CONTROL.items()}


def canonical_surface_wire(value: Any) -> bytes:
    """MR-surface-c14n-1 canonical wire serializer."""

    def wire(x: Any) -> Any:
        if type(x) is float:
            if not math.isfinite(x):
                raise ValueError("nonfinite")
            return {"$f64": (0.0 if x == 0 else x).hex()}
        if x is None or type(x) in (str, bool, int):
            return x
        if type(x) in (list, tuple):
            return [wire(v) for v in x]
        if type(x) is dict and all(type(k) is str for k in x):
            return {k: wire(v) for k, v in x.items()}
        raise TypeError(type(x))

    return json.dumps(
        wire(value), sort_keys=True, ensure_ascii=True, separators=(",", ":"), allow_nan=False
    ).encode("ascii")


def compute_map_digest(domain: str, value: Any) -> str:
    content = domain.encode("ascii") + b"\n" + canonical_surface_wire(value)
    return hashlib.sha256(content).hexdigest()


def candidate_expression_map() -> dict[str, Any]:
    """Authoritative normalized candidate expression map v2."""
    return {
        "map_id": CANDIDATE_MAP_ID,
        "map_version": CANDIDATE_MAP_VERSION,
        "status": "SURFACE_V1_CANDIDATE",
        "supported_recipe_id": CANDIDATE_RECIPE_ID,
        "supported_recipe_version": CANDIDATE_RECIPE_VERSION,
        "supported_recipe_digest": CANDIDATE_RECIPE_DIGEST,
        "serialization": "MR-surface-c14n-1",
        "consumed_controls": ["confrontation", "expressive_restraint", "expressive_warmth"],
        "guidance_dimensions": {
            "directness": {
                "source_control": "confrontation",
                "bands": [
                    {"band": "low", "range": [0.0, 0.33]},
                    {"band": "moderate", "range": [0.33, 0.66]},
                    {"band": "high", "range": [0.66, 1.0]},
                ],
                "boundary_rule": "lower_closed_except_first_fully_closed_upper_closed",
            },
            "restraint": {
                "source_control": "expressive_restraint",
                "bands": [
                    {"band": "low", "range": [0.0, 0.33]},
                    {"band": "moderate", "range": [0.33, 0.66]},
                    {"band": "high", "range": [0.66, 1.0]},
                ],
                "boundary_rule": "lower_closed_except_first_fully_closed_upper_closed",
            },
            "warmth": {
                "source_control": "expressive_warmth",
                "bands": [
                    {"band": "low", "range": [0.0, 0.33]},
                    {"band": "moderate", "range": [0.33, 0.66]},
                    {"band": "high", "range": [0.66, 1.0]},
                ],
                "boundary_rule": "lower_closed_except_first_fully_closed_upper_closed",
            },
        },
    }


CANDIDATE_EXPRESSION_MAP_V2 = candidate_expression_map()


def normalized_expression_map(m: dict[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(m)
    result["consumed_controls"].sort()
    result["guidance_dimensions"] = {
        k: result["guidance_dimensions"][k] for k in sorted(result["guidance_dimensions"])
    }
    return result


def validate_expression_map(map_def: dict[str, Any]) -> None:
    """Validate that expression map conforms to the authoritative candidate map v2."""
    if (
        map_def.get("map_id") != CANDIDATE_MAP_ID
        or map_def.get("map_version") != CANDIDATE_MAP_VERSION
    ):
        raise ValueError(
            f"{SURFACE_EXPRESSION_MAP_CONFLICT}: map identity mismatch; "
            f"expected {CANDIDATE_MAP_ID}:{CANDIDATE_MAP_VERSION}, "
            f"got {map_def.get('map_id')}:{map_def.get('map_version')}"
        )

    norm = normalized_expression_map(map_def)
    digest_val = compute_map_digest("expression-map", norm)
    if digest_val != CANDIDATE_MAP_DIGEST:
        raise ValueError(
            f"{SURFACE_EXPRESSION_MAP_CONFLICT}: content digest mismatch; "
            f"expected {CANDIDATE_MAP_DIGEST}, got {digest_val}"
        )

    if (
        map_def.get("supported_recipe_id") != CANDIDATE_RECIPE_ID
        or map_def.get("supported_recipe_version") != CANDIDATE_RECIPE_VERSION
        or map_def.get("supported_recipe_digest") != CANDIDATE_RECIPE_DIGEST
    ):
        raise ValueError(
            f"{SURFACE_EXPRESSION_RECIPE_MISMATCH}: supported recipe mismatch; "
            f"expected {CANDIDATE_RECIPE_ID}:{CANDIDATE_RECIPE_VERSION} ({CANDIDATE_RECIPE_DIGEST})"
        )


def evaluate_control_band(value: float) -> str:
    """Map a scalar control value in [0.0, 1.0] into a qualitative band.

    Bands:
      low:      [0.00, 0.33)
      moderate: [0.33, 0.66)
      high:     [0.66, 1.00]
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{SURFACE_EXPRESSION_NONFINITE}: control value must be a numeric float")
    f_val = float(value)
    if not math.isfinite(f_val):
        raise ValueError(f"{SURFACE_EXPRESSION_NONFINITE}: control value must be finite")
    if f_val < 0.0 or f_val > 1.0:
        raise ValueError(f"{SURFACE_EXPRESSION_RANGE}: control value {f_val} outside [0.0, 1.0]")

    if f_val < 0.33:
        return "low"
    if f_val < 0.66:
        return "moderate"
    return "high"


def map_surface_to_qualitative_guidance(
    surface: Any,
    map_def: dict[str, Any] | None = None,
) -> dict[str, str]:
    """Map Surface projection result into qualitative guidance bundle.

    Returns:
      {
        "directness": "low" | "moderate" | "high",
        "warmth": "low" | "moderate" | "high",
        "restraint": "low" | "moderate" | "high",
      }
    """
    effective_map = map_def or candidate_expression_map()
    validate_expression_map(effective_map)

    if hasattr(surface, "status") and hasattr(surface, "controls"):
        if surface.status != "AVAILABLE" or surface.controls is None:
            raise ValueError("Surface projection is not AVAILABLE")
        controls_block = surface.controls
    elif isinstance(surface, dict):
        if surface.get("status") != "AVAILABLE":
            raise ValueError("Surface projection is not AVAILABLE")
        controls_block = surface.get("controls")
        if not isinstance(controls_block, dict):
            raise ValueError("Surface controls block missing")
    else:
        raise TypeError("surface must be a SurfaceProjectionResult or dict")

    # Verify recipe binding in controls block matches expression map supported recipe
    recipe_id = controls_block.get("recipe_id")
    recipe_ver = controls_block.get("recipe_version")
    recipe_digest = controls_block.get("recipe_digest")
    if (
        recipe_id != effective_map["supported_recipe_id"]
        or recipe_ver != effective_map["supported_recipe_version"]
        or recipe_digest != effective_map["supported_recipe_digest"]
    ):
        raise ValueError(
            f"{SURFACE_EXPRESSION_RECIPE_MISMATCH}: surface recipe mismatch; "
            f"got {recipe_id}:{recipe_ver} ({recipe_digest}), "
            f"expected {effective_map['supported_recipe_id']}:"
            f"{effective_map['supported_recipe_version']}"
        )

    values = controls_block.get("values")
    from collections.abc import Mapping

    if not isinstance(values, Mapping):
        raise ValueError("controls values mapping missing")

    guidance: dict[str, str] = {}
    for guidance_dim in sorted(GUIDANCE_TO_CONTROL.keys()):
        control_name = GUIDANCE_TO_CONTROL[guidance_dim]
        if control_name not in values:
            raise ValueError(
                f"{SURFACE_EXPRESSION_CONTROL_MISSING}: control {control_name!r} missing"
            )
        raw_val = values[control_name]
        band = evaluate_control_band(raw_val)
        guidance[guidance_dim] = band

    return guidance
