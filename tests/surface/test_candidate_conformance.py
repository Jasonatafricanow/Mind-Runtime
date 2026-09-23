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
    # Verify Dynamics rows are strictly identical
    assert a["projected_dynamics"]["states"] == b["projected_dynamics"]["states"]

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


def test_candidate_saturation_upper(surface):
    """Layer B: Upper clamp saturation with unclamped > 1.0."""
    x = sample_candidate("persona-fixture-a")
    # Set all positive roots to 1.0, all negative roots to 0.0
    positive_roots = (
        "longing",
        "closeness_craving",
        "sharing_urge",
        "curiosity",
        "anger",
        "diligence_pressure",
    )
    for name in positive_roots:
        state(x, name)["value"] = 0.0 if name in ("anger", "sadness") else 1.0
    state(x, "anger")["value"] = 1.0  # anger is positive for confrontation
    state(x, "sadness")["value"] = 0.0

    trait(x, "attachment_approach", 1.0)
    trait(x, "confrontation_readiness", 1.0)
    trait(x, "expressive_restraint", 0.0)
    trait(x, "expressive_warmth_bias", 1.0)

    out = expect_ok(surface, x)
    # With restraint=0 and positive terms=1.0:
    # contact_seeking unclamped: 0.45*1 + 0.35*1 + 0.30*1 - 0.20*1 = 0.90 (in range)
    # confrontation unclamped: 0.70*1 + 0.40*1 - 0 = 1.10 -> clamped 1.0
    # expressive_restraint unclamped: 0.75*0 + 0.35*1 = 0.35
    assert out["values"]["confrontation"] == 1.0
    assert out["audit"]["confrontation"]["clamped"] is True
    assert out["audit"]["confrontation"]["unclamped"] == 1.10


def test_candidate_saturation_lower(surface):
    """Layer B: Lower clamp saturation with unclamped < 0.0."""
    x = sample_candidate("persona-fixture-a")
    # In confrontation: 0.70*anger + 0.40*readiness - 0.30*restraint
    # Set anger=0, readiness=0, restraint=1.0 -> 0 - 0.30 = -0.30 -> clamped to 0.0
    state(x, "anger")["value"] = 0.0
    trait(x, "confrontation_readiness", 0.0)
    trait(x, "expressive_restraint", 1.0)

    out = expect_ok(surface, x)
    assert out["values"]["confrontation"] == 0.0
    assert out["audit"]["confrontation"]["clamped"] is True
    assert out["audit"]["confrontation"]["unclamped"] == -0.30


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
