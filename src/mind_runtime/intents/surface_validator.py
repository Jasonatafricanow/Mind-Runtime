"""Validation of Intent rules against Surface overlap and eligibility rules (W3-C).

Frozen under ADR-0031 and MR_SURFACE_V1_GOLDEN_CONTRACT_02:
1. Eligible Intent surface controls: contact_seeking, initiative, confrontation.
2. Ineligible (expression-only) controls: expressive_warmth, expressive_restraint (and any unknown).
3. Surface-aware rules must declare event_bonus == 0.0.
4. Direct dynamics roots R and surface transitive roots U must not overlap: R ∩ U_i = ∅.
5. Scored surface controls must not share roots pairwise: U_i ∩ U_j = ∅ for i ≠ j.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping
from typing import Any

from mind_runtime.surface.recipe import MANIFEST

ELIGIBLE_INTENT_SURFACE_CONTROLS = frozenset({"contact_seeking", "initiative", "confrontation"})
INELIGIBLE_INTENT_SURFACE_CONTROLS = frozenset({"expressive_warmth", "expressive_restraint"})


def get_control_transitive_roots(control_id: str) -> set[str]:
    """Return all transitive dynamics and disposition roots for a surface control."""
    entry = MANIFEST.get(control_id)
    if not entry:
        return set()
    roots = set(entry.get("dynamics", []))
    roots.update(entry.get("disposition", []))
    return roots


def overlap_validation_reference(rule: Any) -> str:
    """Bind the admitted causal declaration to the exact frozen root graph."""
    validate_intent_rule_surface_overlap(rule)
    controls = tuple(rule.surface_control_weights)
    direct = tuple(rule.dimension_weights)
    payload = {
        "rule_id": rule.rule_id,
        "direct_roots": sorted(name for name, _ in direct),
        "surface_roots": {name: sorted(get_control_transitive_roots(name)) for name, _ in controls},
    }
    digest = hashlib.sha256(
        json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        ).encode("utf-8")
    ).hexdigest()
    return f"overlap-valid:{digest}"


def validate_intent_rule_surface_overlap(rule: Any) -> None:
    """Validate that an Intent rule obeys Surface boundaries and non-overlap constraints.

    Raises:
        ValueError("SURFACE_CONTROL_INELIGIBLE"): if an expression-only or unknown control is used.
        ValueError("SURFACE_WEIGHT_INVALID"): if a control weight is non-numeric or non-finite.
        ValueError("SURFACE_EVENT_BONUS_FORBIDDEN"): if a surface-aware rule has event_bonus != 0.
        ValueError("ROOT_OVERLAP"): if direct roots overlap with surface roots (R ∩ U != ∅)
            or surface controls share roots pairwise (U_i ∩ U_j != ∅).
    """
    # Extract surface_control_weights
    scw_raw = (
        rule.get("surface_control_weights", ())
        if isinstance(rule, Mapping)
        else getattr(rule, "surface_control_weights", ())
    )
    if isinstance(scw_raw, Mapping):
        scw_items = list(scw_raw.items())
    elif isinstance(scw_raw, (list, tuple)):
        scw_items = list(scw_raw)
    else:
        raise ValueError("SURFACE_CONTROL_INVALID: declarations must be pairs")

    # If no surface controls, nothing to validate for surface boundary
    if not scw_items:
        return

    # Extract direct_dynamics_weights / dimension_weights
    ddw_raw = (
        rule.get("direct_dynamics_weights", rule.get("dimension_weights", ()))
        if isinstance(rule, Mapping)
        else getattr(
            rule,
            "direct_dynamics_weights",
            getattr(rule, "dimension_weights", ()),
        )
    )
    if isinstance(ddw_raw, Mapping):
        ddw_items = list(ddw_raw.items())
    elif isinstance(ddw_raw, (list, tuple)):
        ddw_items = list(ddw_raw)
    else:
        raise ValueError("DIRECT_WEIGHT_INVALID: declarations must be pairs")

    # Extract event_bonus
    eb_raw = (
        rule.get("event_bonus", 0.0)
        if isinstance(rule, Mapping)
        else getattr(rule, "event_bonus", 0.0)
    )

    # 1. Eligibility and numeric validity check
    seen_controls: set[str] = set()
    declared_controls: list[str] = []
    for item in scw_items:
        if isinstance(item, (list, tuple)) and len(item) == 2:
            c_name, weight = item
        else:
            raise ValueError(f"SURFACE_CONTROL_INVALID: invalid weight pair {item!r}")

        if not isinstance(c_name, str) or not c_name:
            raise ValueError("SURFACE_CONTROL_INVALID: control name must be a non-empty string")

        if c_name in seen_controls:
            raise ValueError(f"SURFACE_CONTROL_INVALID: duplicate control {c_name!r}")
        seen_controls.add(c_name)

        if c_name not in ELIGIBLE_INTENT_SURFACE_CONTROLS:
            raise ValueError(
                f"SURFACE_CONTROL_INELIGIBLE: control {c_name!r} is ineligible for Intent scoring"
            )

        if (
            isinstance(weight, bool)
            or not isinstance(weight, (int, float))
            or not math.isfinite(weight)
        ):
            raise ValueError(
                f"SURFACE_WEIGHT_INVALID: weight for {c_name!r} must be a finite numeric value"
            )

        # Declaration creates a causal path even when this revision's
        # numerical coefficient is zero. Admission must see every root.
        declared_controls.append(c_name)

    # 2. Event bonus check
    # In SURFACE_V1, Surface-aware rules must have event_bonus == 0.0
    if (
        isinstance(eb_raw, bool)
        or not isinstance(eb_raw, (int, float))
        or not math.isfinite(eb_raw)
    ):
        raise ValueError("event_bonus must be a finite numeric value")
    if float(eb_raw) != 0.0:
        raise ValueError(
            "SURFACE_EVENT_BONUS_FORBIDDEN: Surface-aware rules must declare event_bonus == 0.0"
        )

    # 3. Direct dynamics roots R
    declared_direct_roots: set[str] = set()
    for item in ddw_items:
        if isinstance(item, (list, tuple)) and len(item) == 2:
            dim_name, dim_weight = item
        else:
            raise ValueError("DIRECT_WEIGHT_INVALID: invalid direct root pair")
        if (
            isinstance(dim_weight, bool)
            or not isinstance(dim_weight, (int, float))
            or not math.isfinite(dim_weight)
        ):
            raise ValueError("DIRECT_WEIGHT_INVALID: direct root weight must be finite numeric")
        if not isinstance(dim_name, str) or not dim_name:
            raise ValueError("DIRECT_WEIGHT_INVALID: direct root name must be nonempty")
        declared_direct_roots.add(dim_name)
        if not dim_name.startswith("agent.affect."):
            declared_direct_roots.add(f"agent.affect.{dim_name}")
        else:
            declared_direct_roots.add(dim_name.removeprefix("agent.affect."))

    # 4. Check R ∩ U_i = ∅
    for c_name in declared_controls:
        u_roots = get_control_transitive_roots(c_name)
        overlap = set()
        for r in declared_direct_roots:
            if r in u_roots or f"agent.affect.{r}" in u_roots:
                overlap.add(r)
        if overlap:
            raise ValueError(
                f"ROOT_OVERLAP: Direct dynamics roots {sorted(overlap)} overlap with "
                f"transitive roots of surface control {c_name!r}"
            )

    # 5. Check U_i ∩ U_j = ∅ for i ≠ j
    for i in range(len(declared_controls)):
        for j in range(i + 1, len(declared_controls)):
            c1 = declared_controls[i]
            c2 = declared_controls[j]
            shared = get_control_transitive_roots(c1) & get_control_transitive_roots(c2)
            if shared:
                raise ValueError(
                    f"ROOT_OVERLAP: Surface controls {c1!r} and {c2!r} share roots {sorted(shared)}"
                )
