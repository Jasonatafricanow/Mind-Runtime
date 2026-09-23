"""Frozen Candidate Recipe v2 definitions and manifest validation.

Frozen under ADR-0028:
recipe_id: surface-v1-candidate
revision: 2
digest: 4f37f46f89f6176fd5fefe0167ec7a81e341839f4fb9b98fa3cc348ddeaf9a55
"""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from typing import Any

from mind_runtime.dynamics.persona import surface_digest
from mind_runtime.surface.evaluator import (
    D_PREFIX,
    P_PREFIX,
    extract_ast_lookups,
    validate_ast_primitives,
)

CANDIDATE_RECIPE_ID = "surface-v1-candidate"
CANDIDATE_RECIPE_VERSION = 2
CANDIDATE_RECIPE_DIGEST = (
    "4f37f46f89f6176fd5fefe0167ec7a81e341839f4fb9b98fa3cc348ddeaf9a55"
)

MANIFEST: dict[str, dict[str, list[str]]] = {
    "contact_seeking": {
        "dynamics": [D_PREFIX + n for n in ("anger", "closeness_craving", "longing")],
        "disposition": [
            P_PREFIX + n for n in ("attachment_approach", "expressive_restraint")
        ],
    },
    "initiative": {
        "dynamics": [D_PREFIX + n for n in ("curiosity", "sadness", "sharing_urge")],
        "disposition": [],
    },
    "confrontation": {
        "dynamics": [D_PREFIX + "anger"],
        "disposition": [
            P_PREFIX + n for n in ("confrontation_readiness", "expressive_restraint")
        ],
    },
    "expressive_warmth": {
        "dynamics": [D_PREFIX + n for n in ("anger", "closeness_craving", "sadness")],
        "disposition": [P_PREFIX + "expressive_warmth_bias"],
    },
    "expressive_restraint": {
        "dynamics": [D_PREFIX + "diligence_pressure"],
        "disposition": [P_PREFIX + "expressive_restraint"],
    },
}

ENABLED = sorted(MANIFEST)
DEFERRED = ["reassurance_seeking", "withdrawal"]
ALL_DECLARED_DYNAMICS_ROOTS = sorted({d for m in MANIFEST.values() for d in m["dynamics"]})


def normalized_recipe(r: dict[str, Any]) -> dict[str, Any]:
    """Normalize recipe rules and manifest for deterministic serialization."""
    result = deepcopy(r)
    result["rules"].sort(key=lambda rule: rule["control_id"])
    for manifest in result["dependency_manifest"].values():
        manifest["dynamics"].sort()
        manifest["disposition"].sort()
    return result


def normalized_persona_content(content: dict[str, Any]) -> dict[str, Any]:
    """Normalize persona content for deterministic canonical serialization."""
    result = deepcopy(content)
    result["dimensions"].sort(key=lambda item: item["dimension"])
    for dimension in result["dimensions"]:
        for pairs in ("growth_profile", "coupling_profile"):
            dimension[pairs].sort(key=lambda pair: pair[0])
    return result


def dependency_payload(x: Mapping[str, Any]) -> dict[str, Any]:
    """Build the canonical dependency payload for dependency digest computation."""
    states = {s["dimension"]: s for s in x["projected_dynamics"]["states"]}
    traits = x["persona"]["content"]["behavioral_disposition"]
    return {
        k: {
            "dynamics": [
                {
                    f: states[d][f]
                    for f in (
                        "dimension",
                        "state_id",
                        "version",
                        "value",
                        "bounds",
                        "value_type",
                    )
                }
                for d in sorted(m["dynamics"])
            ],
            "disposition": [
                [p, traits[p.removeprefix(P_PREFIX)]] for p in sorted(m["disposition"])
            ],
        }
        for k, m in sorted(MANIFEST.items())
    }


def validate_candidate_recipe(recipe: dict[str, Any]) -> tuple[bool, str | None]:
    """Verify recipe identity, digest, primitives, and manifest equality."""
    if (
        recipe.get("recipe_id") != CANDIDATE_RECIPE_ID
        or recipe.get("recipe_version") != CANDIDATE_RECIPE_VERSION
    ):
        return False, "SURFACE_RECIPE_UNSUPPORTED"

    norm = normalized_recipe(recipe)
    computed_digest = surface_digest("recipe", norm)
    if computed_digest != CANDIDATE_RECIPE_DIGEST:
        return False, "SURFACE_RECIPE_CONTENT_CONFLICT"

    # Validate rules
    rules = norm.get("rules", [])
    if len(rules) != len(ENABLED):
        return False, "SURFACE_RECIPE_CONTENT_CONFLICT"

    for rule in rules:
        control_id = rule.get("control_id")
        if control_id not in MANIFEST:
            return False, "SURFACE_RECIPE_CONTENT_CONFLICT"
        formula = rule.get("formula")
        if not validate_ast_primitives(formula):
            return False, "SURFACE_RECIPE_CONTENT_CONFLICT"

        # Check lookups match manifest
        lookups = extract_ast_lookups(formula)
        expected_lookups = set(MANIFEST[control_id]["dynamics"]) | set(
            MANIFEST[control_id]["disposition"]
        )
        if lookups != expected_lookups:
            return False, "SURFACE_RECIPE_CONTENT_CONFLICT"

    return True, None
