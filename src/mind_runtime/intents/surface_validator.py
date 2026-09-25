"""Validation of Intent rules against Surface overlap and eligibility rules (W3-C).

Frozen under ADR-0028 and MR_SURFACE_V1_GOLDEN_CONTRACT_02:
1. Eligible Intent surface controls: contact_seeking, initiative, confrontation.
2. Ineligible (expression-only) controls: expressive_warmth, expressive_restraint (and any unknown).
3. Surface-aware rules must declare event_bonus == 0.0.
4. Direct dynamics roots R and surface transitive roots U must not overlap: R ∩ U_i = ∅.
5. Scored surface controls must not share roots pairwise: U_i ∩ U_j = ∅ for i ≠ j.
"""

from __future__ import annotations

import math
import hashlib
import json
from collections.abc import Mapping
from typing import Any

from mind_runtime.surface.recipe import (
    CANDIDATE_RECIPE_DIGEST,
    CANDIDATE_RECIPE_ID,
    CANDIDATE_RECIPE_VERSION,
    MANIFEST,
)

ELIGIBLE_INTENT_SURFACE_CONTROLS = frozenset(
    {"contact_seeking", "initiative", "confrontation"}
)
INELIGIBLE_INTENT_SURFACE_CONTROLS = frozenset(
    {"expressive_warmth", "expressive_restraint"}
)


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
    controls = tuple(getattr(rule, "surface_control_weights"))
    direct = tuple(getattr(rule, "dimension_weights"))
    payload = {
        "rule_id": rule.rule_id,
        "direct_roots": sorted(name for name, _ in direct),
        "surface_roots": {
            name: sorted(get_control_transitive_roots(name)) for name, _ in controls
        },
    }
    digest = hashlib.sha256(json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
    ).encode("utf-8")).hexdigest()
    return f"overlap-valid:{digest}"


def validate_initiative_gate_rule(rule: Any) -> None:
    """Validate that an initiative-gated rule strictly adheres to the frozen V1 shape."""
    min_init = (
        rule.get("minimum_initiative")
        if isinstance(rule, Mapping)
        else getattr(rule, "minimum_initiative", None)
    )
    if min_init is None:
        return

    if isinstance(min_init, bool) or not isinstance(min_init, (int, float)) or not math.isfinite(min_init):
        raise ValueError("minimum_initiative must be a finite numeric value, not bool")
    min_val = float(min_init)
    if not 0.0 < min_val <= 1.0:
        raise ValueError("minimum_initiative must be in (0, 1]")

    kind = rule.get("kind") if isinstance(rule, Mapping) else getattr(rule, "kind", None)
    if kind not in ("spontaneous_share", "proactive_inquiry"):
        raise ValueError(
            f"minimum_initiative is only supported for 'spontaneous_share' and 'proactive_inquiry', got {kind!r}"
        )

    scw = (
        rule.get("surface_control_weights", ())
        if isinstance(rule, Mapping)
        else getattr(rule, "surface_control_weights", ())
    )
    if scw and len(scw) > 0:
        raise ValueError("surface_control_weights must be empty for initiative-gated rule")

    event_kind = rule.get("event_kind") if isinstance(rule, Mapping) else getattr(rule, "event_kind", None)
    if event_kind is not None:
        raise ValueError("event_kind must be None for initiative-gated rule")

    event_bonus = rule.get("event_bonus", 0.0) if isinstance(rule, Mapping) else getattr(rule, "event_bonus", 0.0)
    if (
        isinstance(event_bonus, bool)
        or not isinstance(event_bonus, (int, float))
        or not math.isfinite(event_bonus)
        or float(event_bonus) != 0.0
    ):
        raise ValueError("event_bonus must be 0.0 for initiative-gated rule")

    due_at = rule.get("due_at_attribute") if isinstance(rule, Mapping) else getattr(rule, "due_at_attribute", None)
    if due_at is not None:
        raise ValueError("due_at_attribute must be None for initiative-gated rule")

    dw = (
        rule.get("dimension_weights", ())
        if isinstance(rule, Mapping)
        else getattr(rule, "dimension_weights", ())
    )
    dw_items = list(dw.items()) if isinstance(dw, Mapping) else list(dw)

    expected_root = (
        "agent.affect.sharing_urge" if kind == "spontaneous_share" else "agent.affect.curiosity"
    )
    if len(dw_items) != 1:
        raise ValueError(
            f"initiative-gated rule for {kind!r} must have exactly one direct root: {expected_root!r}"
        )
    dim_name, dim_weight = dw_items[0]
    if dim_name != expected_root:
        raise ValueError(
            f"initiative-gated rule for {kind!r} must have direct root {expected_root!r}, got {dim_name!r}"
        )
    if isinstance(dim_weight, bool) or not isinstance(dim_weight, (int, float)) or not math.isfinite(dim_weight):
        raise ValueError("direct root weight must be finite numeric")
    if float(dim_weight) <= 0:
        raise ValueError("direct root weight must be positive")


def admission_validation_reference(rule: Any) -> str:
    """Bind the admitted initiative gate declaration to the exact frozen root graph and recipe."""
    validate_initiative_gate_rule(rule)
    rule_id = rule.get("rule_id") if isinstance(rule, Mapping) else getattr(rule, "rule_id")
    kind = rule.get("kind") if isinstance(rule, Mapping) else getattr(rule, "kind")
    min_init = (
        rule.get("minimum_initiative")
        if isinstance(rule, Mapping)
        else getattr(rule, "minimum_initiative")
    )
    dw = (
        rule.get("dimension_weights", ())
        if isinstance(rule, Mapping)
        else getattr(rule, "dimension_weights", ())
    )
    dw_items = list(dw.items()) if isinstance(dw, Mapping) else list(dw)
    direct_roots = sorted(name for name, _ in dw_items)

    payload = {
        "rule_id": rule_id,
        "kind": kind,
        "direct_roots": direct_roots,
        "control": "initiative",
        "comparator": "gte",
        "minimum_initiative": float(min_init),
        "recipe_id": CANDIDATE_RECIPE_ID,
        "recipe_version": CANDIDATE_RECIPE_VERSION,
        "recipe_digest": CANDIDATE_RECIPE_DIGEST,
        "initiative_transitive_roots": sorted(MANIFEST.get("initiative", {}).get("dynamics", [])),
    }
    digest = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    ).hexdigest()
    return f"initiative-gate-valid:{digest}"


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
        if isinstance(dim_weight, bool) or not isinstance(dim_weight, (int, float)) or not math.isfinite(dim_weight):
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
