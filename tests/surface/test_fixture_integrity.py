"""GREEN checks of specification data, static vectors, and digests only.

These tests assert contract self-consistency and fixture integrity without evaluating Surface.
"""

import pytest

from tests.surface.spec_support import (
    CANDIDATE_MAP_DIGEST,
    CANDIDATE_RECIPE_DIGEST,
    CANDIDATE_RECIPE_ID,
    CANDIDATE_RECIPE_VERSION,
    DEFERRED,
    DEP_A_DIGEST,
    ENABLED,
    MANIFEST,
    PERSONA_A_DIGEST,
    PERSONA_B_DIGEST,
    REFERENCE_DEP_DIGEST,
    REFERENCE_PERSONA_DIGEST,
    REFERENCE_RECIPE_DIGEST,
    STATIC_BASELINE_CONTROLS,
    STATIC_PERSONA_COUNTERFACTUAL_CONTROLS,
    STATIC_ROOT_ISOLATION_CONTROLS,
    candidate_expression_map,
    candidate_recipe,
    canonical,
    dependency_payload,
    digest,
    normalized_expression_map,
    normalized_persona_content,
    normalized_recipe,
    reference_recipe,
    sample_candidate,
    sample_reference,
)


def _extract_ast_roots(node):
    opcode, *args = node
    if opcode == "const":
        assert len(args) == 1 and type(args[0]) is float
        return set()
    if opcode == "lookup":
        assert len(args) == 1 and type(args[0]) is str
        return {args[0]}
    assert opcode in {"add", "sub", "mul", "clamp"}
    assert len(args) == (3 if opcode == "clamp" else 2)
    return set().union(*(_extract_ast_roots(arg) for arg in args))


def test_candidate_ast_exact_roots_and_allowed_primitives():
    r = candidate_recipe()
    rules = r["rules"]
    assert [rule["control_id"] for rule in rules] == ENABLED
    assert not set(DEFERRED) & set(MANIFEST)
    assert r["status"] == "SURFACE_V1_CANDIDATE"
    assert r["calibration_status"] == "UNREPORTED_CANDIDATE"
    for rule in rules:
        manifest = MANIFEST[rule["control_id"]]
        expected_roots = set(manifest["dynamics"] + manifest["disposition"])
        assert _extract_ast_roots(rule["formula"]) == expected_roots
        assert rule["formula"][0] == "clamp"
        assert rule["formula"][2] == ["const", 0.0]
        assert rule["formula"][3] == ["const", 1.0]


def test_candidate_expression_map_integrity():
    m = candidate_expression_map()
    assert m["status"] == "SURFACE_V1_CANDIDATE"
    assert m["supported_recipe_id"] == CANDIDATE_RECIPE_ID
    assert m["supported_recipe_version"] == CANDIDATE_RECIPE_VERSION
    assert m["supported_recipe_digest"] == CANDIDATE_RECIPE_DIGEST
    assert sorted(m["consumed_controls"]) == [
        "confrontation",
        "expressive_restraint",
        "expressive_warmth",
    ]
    assert "contact_seeking" not in m["consumed_controls"]
    assert "initiative" not in m["consumed_controls"]

    dims = m["guidance_dimensions"]
    assert set(dims) == {"directness", "restraint", "warmth"}
    for _dim_name, cfg in dims.items():
        bands = cfg["bands"]
        assert [b["band"] for b in bands] == ["low", "moderate", "high"]
        assert bands[0]["range"] == [0.0, 0.33]
        assert bands[1]["range"] == [0.33, 0.66]
        assert bands[2]["range"] == [0.66, 1.0]


def test_canonical_literal_bytes():
    assert canonical({"z": -0.0, "a": [1, 0.5]}) == (
        b'{"a":[1,{"$f64":"0x1.0000000000000p-1"}],"z":{"$f64":"0x0.0p+0"}}'
    )
    assert canonical({"a": 0.5, "b": 1}) == canonical({"b": 1, "a": 0.5})
    assert canonical(-0.0) == canonical(0.0)
    assert canonical(1) != canonical(1.0)  # identity integers != typed scalar floats
    for invalid in (float("nan"), float("inf"), -float("inf")):
        with pytest.raises(ValueError):
            canonical(invalid)


def test_candidate_recipe_and_persona_digests():
    r = candidate_recipe()
    assert digest("recipe", normalized_recipe(r)) == CANDIDATE_RECIPE_DIGEST

    m = candidate_expression_map()
    assert digest("expression-map", normalized_expression_map(m)) == CANDIDATE_MAP_DIGEST

    x_a = sample_candidate("persona-fixture-a")
    assert x_a["recipe_bindings"][0]["recipe_digest"] == CANDIDATE_RECIPE_DIGEST
    assert (
        digest("persona", normalized_persona_content(x_a["persona"]["content"]))
        == PERSONA_A_DIGEST
    )
    assert digest("dependencies", dependency_payload(x_a)) == DEP_A_DIGEST

    x_b = sample_candidate("persona-fixture-b")
    assert (
        digest("persona", normalized_persona_content(x_b["persona"]["content"]))
        == PERSONA_B_DIGEST
    )


def test_reference_fixture_digests():
    ref_r = reference_recipe()
    assert digest("recipe", normalized_recipe(ref_r)) == REFERENCE_RECIPE_DIGEST

    ref_x = sample_reference()
    assert (
        digest("persona", normalized_persona_content(ref_x["persona"]["content"]))
        == REFERENCE_PERSONA_DIGEST
    )
    assert digest("dependencies", dependency_payload(ref_x)) == REFERENCE_DEP_DIGEST


def test_static_vectors_self_consistency():
    # 1. Baseline vectors
    assert sorted(STATIC_BASELINE_CONTROLS) == ENABLED
    for _k, v in STATIC_BASELINE_CONTROLS.items():
        assert 0.0 <= v <= 1.0

    # 2. Persona counterfactual
    assert sorted(STATIC_PERSONA_COUNTERFACTUAL_CONTROLS) == ENABLED
    assert (
        STATIC_PERSONA_COUNTERFACTUAL_CONTROLS["initiative"]
        == STATIC_BASELINE_CONTROLS["initiative"]
    )
    for k in ("contact_seeking", "confrontation", "expressive_warmth", "expressive_restraint"):
        assert STATIC_PERSONA_COUNTERFACTUAL_CONTROLS[k] != STATIC_BASELINE_CONTROLS[k]

    # 3. Root isolation consistency
    all_roots = {
        root
        for m in MANIFEST.values()
        for root in [r.split(".")[-1] for r in m["dynamics"] + m["disposition"]]
    }
    assert set(STATIC_ROOT_ISOLATION_CONTROLS) == all_roots

    for root_short, expected_map in STATIC_ROOT_ISOLATION_CONTROLS.items():
        assert sorted(expected_map) == ENABLED
        # find which controls declare this root
        declared_controls = {
            ctrl
            for ctrl, m in MANIFEST.items()
            if any(r.endswith("." + root_short) for r in m["dynamics"] + m["disposition"])
        }
        for ctrl in ENABLED:
            if ctrl in declared_controls:
                assert expected_map[ctrl] != STATIC_BASELINE_CONTROLS[ctrl], (
                    f"Root {root_short} must change dependent control {ctrl}"
                )
            else:
                assert expected_map[ctrl] == STATIC_BASELINE_CONTROLS[ctrl], (
                    f"Root {root_short} must NOT change independent control {ctrl}"
                )

    # 4. Directional invariants on static vectors
    # attachment_approach up -> contact_seeking up
    assert (
        STATIC_ROOT_ISOLATION_CONTROLS["attachment_approach"]["contact_seeking"]
        > STATIC_BASELINE_CONTROLS["contact_seeking"]
    )
    # confrontation_readiness up -> confrontation up
    assert (
        STATIC_ROOT_ISOLATION_CONTROLS["confrontation_readiness"]["confrontation"]
        > STATIC_BASELINE_CONTROLS["confrontation"]
    )
    # expressive_warmth_bias up -> expressive_warmth up
    assert (
        STATIC_ROOT_ISOLATION_CONTROLS["expressive_warmth_bias"]["expressive_warmth"]
        > STATIC_BASELINE_CONTROLS["expressive_warmth"]
    )
    # trait expressive_restraint up -> contact_seeking down
    assert (
        STATIC_ROOT_ISOLATION_CONTROLS["expressive_restraint"]["contact_seeking"]
        < STATIC_BASELINE_CONTROLS["contact_seeking"]
    )
    # trait expressive_restraint up -> confrontation down
    assert (
        STATIC_ROOT_ISOLATION_CONTROLS["expressive_restraint"]["confrontation"]
        < STATIC_BASELINE_CONTROLS["confrontation"]
    )
    # trait expressive_restraint up -> control expressive_restraint up
    assert (
        STATIC_ROOT_ISOLATION_CONTROLS["expressive_restraint"]["expressive_restraint"]
        > STATIC_BASELINE_CONTROLS["expressive_restraint"]
    )
