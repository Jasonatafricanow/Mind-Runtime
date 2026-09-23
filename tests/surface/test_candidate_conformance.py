"""Layer B: Candidate Conformance Tests (CANDIDATE_RECIPE_V1).

RED BY DESIGN: Production Surface adapter is intentionally absent in W3-B0.
All test oracles are statically frozen literals (NO algorithmic derivation).
"""

import pytest

from tests.surface.spec_support import (
    BASELINE_CONTROLS_ID,
    CANDIDATE_RECIPE_DIGEST,
    MANIFEST,
    STATIC_BASELINE_CONTROLS,
    STATIC_PERSONA_COUNTERFACTUAL_CONTROLS,
    STATIC_ROOT_ISOLATION_CONTROLS,
    expect_error,
    expect_ok,
    sample_candidate,
    state,
    trait,
)


def test_candidate_baseline_static_vector(surface):
    """Layer B: Baseline static vector against CANDIDATE_RECIPE_V1."""
    x = sample_candidate("persona-fixture-a")
    out = expect_ok(surface, x)
    assert out["values"] == STATIC_BASELINE_CONTROLS
    assert out["controls_id"] == BASELINE_CONTROLS_ID
    assert out["recipe_digest"] == CANDIDATE_RECIPE_DIGEST
    for k in STATIC_BASELINE_CONTROLS:
        assert out["audit"][k]["unclamped"] == STATIC_BASELINE_CONTROLS[k]
        assert out["audit"][k]["clamped"] is False


def test_candidate_persona_counterfactual_static_vector(surface):
    """Layer B: Persona counterfactual holding Dynamics constant."""
    a = sample_candidate("persona-fixture-a")
    b = sample_candidate("persona-fixture-b")
    # Causal values are identical; owner lineage must follow the selected Persona.
    assert [(s["dimension"], s["value"], s["version"]) for s in a["projected_dynamics"]["states"]] == [
        (s["dimension"], s["value"], s["version"]) for s in b["projected_dynamics"]["states"]
    ]

    out_a = expect_ok(surface, a)
    out_b = expect_ok(surface, b)

    assert out_a["values"] == STATIC_BASELINE_CONTROLS
    assert out_b["values"] == STATIC_PERSONA_COUNTERFACTUAL_CONTROLS

    # Initiative has no persona root in V1 -> must be strictly identical
    assert out_b["values"]["initiative"] == out_a["values"]["initiative"]

    # All other 4 controls have persona roots -> must differ
    for k in ("contact_seeking", "confrontation", "expressive_warmth", "expressive_restraint"):
        assert out_b["values"][k] != out_a["values"][k]

    assert out_b["persona_content_digest"] != out_a["persona_content_digest"]
    assert out_b["controls_id"] != out_a["controls_id"]


@pytest.mark.parametrize("root_name", sorted(STATIC_ROOT_ISOLATION_CONTROLS))
def test_candidate_root_isolation_all_declared_roots(surface, root_name):
    """Layer B: Causal effectiveness and isolation of every declared root."""
    x = sample_candidate("persona-fixture-a")
    expected = STATIC_ROOT_ISOLATION_CONTROLS[root_name]

    # Mutate only this root by +0.20
    disposition_roots = (
        "attachment_approach",
        "confrontation_readiness",
        "expressive_restraint",
        "expressive_warmth_bias",
    )
    if root_name in disposition_roots:
        current = x["persona"]["content"]["behavioral_disposition"][root_name]
        trait(x, root_name, current + 0.20)
    else:
        current = state(x, root_name)["value"]
        state(x, root_name)["value"] = current + 0.20

    out = expect_ok(surface, x)
    assert out["values"] == expected


def test_candidate_per_control_saturation_upper(surface):
    """Layer B: Upper clamp saturation for each control (unclamped >= 1.0, clamped == True)."""
    # 1. contact_seeking: longing=1, closeness=1, attachment=1, anger=0, restraint=0 -> 1.10 -> 1.0
    x = sample_candidate("persona-fixture-a")
    state(x, "longing")["value"] = 1.0
    state(x, "closeness_craving")["value"] = 1.0
    state(x, "anger")["value"] = 0.0
    trait(x, "attachment_approach", 1.0)
    trait(x, "expressive_restraint", 0.0)
    out = expect_ok(surface, x)
    assert out["values"]["contact_seeking"] == 1.0
    assert out["audit"]["contact_seeking"]["clamped"] is True
    assert out["audit"]["contact_seeking"]["unclamped"] == 1.10

    # 2. initiative: sharing=1, curiosity=1, sadness=0 -> 1.10 -> 1.0
    x = sample_candidate("persona-fixture-a")
    state(x, "sharing_urge")["value"] = 1.0
    state(x, "curiosity")["value"] = 1.0
    state(x, "sadness")["value"] = 0.0
    out = expect_ok(surface, x)
    assert out["values"]["initiative"] == 1.0
    assert out["audit"]["initiative"]["clamped"] is True
    assert out["audit"]["initiative"]["unclamped"] == 1.10

    # 3. confrontation: anger=1, readiness=1, restraint=0 -> 1.10 -> 1.0
    x = sample_candidate("persona-fixture-a")
    state(x, "anger")["value"] = 1.0
    trait(x, "confrontation_readiness", 1.0)
    trait(x, "expressive_restraint", 0.0)
    out = expect_ok(surface, x)
    assert out["values"]["confrontation"] == 1.0
    assert out["audit"]["confrontation"]["clamped"] is True
    assert out["audit"]["confrontation"]["unclamped"] == 1.10

    # 4. expressive_warmth: warmth_bias=1, closeness=1, anger=0, sadness=0 -> 1.05 -> 1.0
    x = sample_candidate("persona-fixture-a")
    state(x, "closeness_craving")["value"] = 1.0
    state(x, "anger")["value"] = 0.0
    state(x, "sadness")["value"] = 0.0
    trait(x, "expressive_warmth_bias", 1.0)
    out = expect_ok(surface, x)
    assert out["values"]["expressive_warmth"] == 1.0
    assert out["audit"]["expressive_warmth"]["clamped"] is True
    assert out["audit"]["expressive_warmth"]["unclamped"] == 1.05

    # 5. expressive_restraint: restraint=1, diligence=1 -> 1.10 -> 1.0
    x = sample_candidate("persona-fixture-a")
    state(x, "diligence_pressure")["value"] = 1.0
    trait(x, "expressive_restraint", 1.0)
    out = expect_ok(surface, x)
    assert out["values"]["expressive_restraint"] == 1.0
    assert out["audit"]["expressive_restraint"]["clamped"] is True
    assert out["audit"]["expressive_restraint"]["unclamped"] == 1.10


def test_candidate_per_control_saturation_lower(surface):
    """Layer B: Lower clamp saturation for each control (unclamped <= 0.0)."""
    # 1. contact_seeking: longing=0, closeness=0, attachment=0, anger=1, restraint=1 -> -0.40 -> 0.0
    x = sample_candidate("persona-fixture-a")
    state(x, "longing")["value"] = 0.0
    state(x, "closeness_craving")["value"] = 0.0
    state(x, "anger")["value"] = 1.0
    trait(x, "attachment_approach", 0.0)
    trait(x, "expressive_restraint", 1.0)
    out = expect_ok(surface, x)
    assert out["values"]["contact_seeking"] == 0.0
    assert out["audit"]["contact_seeking"]["clamped"] is True
    assert out["audit"]["contact_seeking"]["unclamped"] == -0.40

    # 2. initiative: sharing=0, curiosity=0, sadness=1 -> -0.25 -> 0.0
    x = sample_candidate("persona-fixture-a")
    state(x, "sharing_urge")["value"] = 0.0
    state(x, "curiosity")["value"] = 0.0
    state(x, "sadness")["value"] = 1.0
    out = expect_ok(surface, x)
    assert out["values"]["initiative"] == 0.0
    assert out["audit"]["initiative"]["clamped"] is True
    assert out["audit"]["initiative"]["unclamped"] == -0.25

    # 3. confrontation: anger=0, readiness=0, restraint=1 -> -0.30 -> 0.0
    x = sample_candidate("persona-fixture-a")
    state(x, "anger")["value"] = 0.0
    trait(x, "confrontation_readiness", 0.0)
    trait(x, "expressive_restraint", 1.0)
    out = expect_ok(surface, x)
    assert out["values"]["confrontation"] == 0.0
    assert out["audit"]["confrontation"]["clamped"] is True
    assert out["audit"]["confrontation"]["unclamped"] == -0.30

    # 4. expressive_warmth: warmth_bias=0, closeness=0, anger=1, sadness=1 -> -0.45 -> 0.0
    x = sample_candidate("persona-fixture-a")
    state(x, "closeness_craving")["value"] = 0.0
    state(x, "anger")["value"] = 1.0
    state(x, "sadness")["value"] = 1.0
    trait(x, "expressive_warmth_bias", 0.0)
    out = expect_ok(surface, x)
    assert out["values"]["expressive_warmth"] == 0.0
    assert out["audit"]["expressive_warmth"]["clamped"] is True
    assert out["audit"]["expressive_warmth"]["unclamped"] == -0.45

    # 5. expressive_restraint: restraint=0, diligence=0 -> 0.00 -> 0.0 (clamped == False)
    x = sample_candidate("persona-fixture-a")
    state(x, "diligence_pressure")["value"] = 0.0
    trait(x, "expressive_restraint", 0.0)
    out = expect_ok(surface, x)
    assert out["values"]["expressive_restraint"] == 0.0
    assert out["audit"]["expressive_restraint"]["clamped"] is False
    assert out["audit"]["expressive_restraint"]["unclamped"] == 0.00


@pytest.mark.parametrize("dimension", sorted({d for m in MANIFEST.values() for d in m["dynamics"]}))
def test_candidate_fail_closed_missing_root(surface, dimension):
    """Layer B: Missing any declared root fails closed with SURFACE_MISSING_STATE."""
    x = sample_candidate("persona-fixture-a")
    x["projected_dynamics"]["states"] = [
        s for s in x["projected_dynamics"]["states"] if s["dimension"] != dimension
    ]
    expect_error(surface, x, "SURFACE_MISSING_STATE")


@pytest.mark.parametrize(
    "value,code",
    [
        (float("nan"), "SURFACE_NONFINITE"),
        (float("inf"), "SURFACE_NONFINITE"),
        (-float("inf"), "SURFACE_NONFINITE"),
        (True, "SURFACE_NUMERIC_TYPE"),
        (-0.01, "SURFACE_RANGE"),
        (1.01, "SURFACE_RANGE"),
        ("0.5", "SURFACE_NUMERIC_TYPE"),
        (None, "SURFACE_NUMERIC_TYPE"),
    ],
)
def test_candidate_fail_closed_numeric_validation(surface, value, code):
    """Layer B: Invalid numeric scalar in state or trait fails closed."""
    x = sample_candidate("persona-fixture-a")
    state(x, "anger")["value"] = value
    expect_error(surface, x, code)


def test_candidate_fail_closed_recipe_content_conflict(surface):
    """Layer B: Modifying formula without changing revision fails closed."""
    x = sample_candidate("persona-fixture-a")
    # Mutate coefficient of expressive_restraint from 0.75 to 0.85
    rule = next(r for r in x["recipe"]["rules"] if r["control_id"] == "expressive_restraint")
    rule["formula"][1][1][1][1] = 0.85
    expect_error(surface, x, "SURFACE_RECIPE_CONTENT_CONFLICT")


def test_candidate_fail_closed_persona_content_conflict(surface):
    """Layer B: Modifying trait without recomputing digest fails closed."""
    x = sample_candidate("persona-fixture-a")
    x["persona"]["content"]["behavioral_disposition"]["attachment_approach"] = 0.99
    # Do NOT call bind_persona -> digest mismatch
    expect_error(surface, x, "SURFACE_PERSONA_CONTENT_MISMATCH")
