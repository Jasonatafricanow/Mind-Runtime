"""Layer C: Historical Reference Fixture Tests (surface-reference-v1).

STATUS: TEST_ONLY / REFERENCE_FIXTURE.
EXCLUDED from W3 implementation certification authority.
Preserved strictly as historical baseline reference.
"""

from copy import deepcopy

import pytest

from tests.surface.spec_support import (
    digest,
    expect_ok,
    sample_reference,
    state,
    trait,
)


@pytest.mark.reference_only
def test_surface_reference_v1_all_controls_exact_binary64(surface):
    """Historical reference: exact binary64 values for surface-reference-v1."""
    expected = {
        "contact_seeking": "0x1.3d70a3d70a3d8p-1",
        "initiative": "0x1.999999999999ap-1",
        "confrontation": "0x1.78d4fdf3b645ap-5",
        "expressive_warmth": "0x1.1eb851eb851ecp-1",
        "expressive_restraint": "0x1.e147ae147ae15p-1",
    }
    out = expect_ok(surface, sample_reference())
    assert {k: v.hex() for k, v in out["values"].items()} == expected
    assert {k: v["unclamped"].hex() for k, v in out["audit"].items()} == expected
    assert all(not v["clamped"] for v in out["audit"].values())


@pytest.mark.reference_only
def test_surface_reference_v1_contact_inhibitory_terms(surface):
    """Historical reference: anger inhibition in contact_seeking."""
    x = sample_reference()
    state(x, "anger")["value"] = 0.8
    out = expect_ok(surface, x)
    assert out["values"]["contact_seeking"].hex() == "0x1.9652bd3c36113p-2"


@pytest.mark.reference_only
def test_surface_reference_v1_contact_fixture(surface):
    """Historical reference G1 + G18: attachment .2 -> .8 gives contact .62 -> .74."""
    a = sample_reference()
    b = deepcopy(a)
    trait(b, "attachment_approach", 0.8)
    before = digest("dynamics", a["projected_dynamics"]["states"])
    left, right = expect_ok(surface, a), expect_ok(surface, b)
    assert left["values"]["contact_seeking"] == pytest.approx(0.62, abs=1e-15, rel=0)
    assert right["values"]["contact_seeking"] == pytest.approx(0.74, abs=1e-15, rel=0)
    assert before == digest("dynamics", b["projected_dynamics"]["states"])
    assert before == digest("dynamics", a["projected_dynamics"]["states"])
    assert left["persona_content_digest"] != right["persona_content_digest"]
    assert left["controls_id"] != right["controls_id"]


@pytest.mark.reference_only
def test_g19_confrontation_restraint_fixture(surface):
    """Historical reference G19: confrontation restraint fixture."""
    a = sample_reference()
    state(a, "anger")["value"] = 0.8
    b = deepcopy(a)
    trait(b, "expressive_restraint", 0.2)
    x, y = expect_ok(surface, a), expect_ok(surface, b)
    assert x["values"]["confrontation"] == pytest.approx(0.3404, abs=1e-15, rel=0)
    assert y["values"]["confrontation"] == pytest.approx(0.6512, abs=1e-15, rel=0)
    assert x["values"]["expressive_restraint"] == pytest.approx(0.94, abs=1e-15, rel=0)


@pytest.mark.reference_only
@pytest.mark.parametrize(
    "bias,closeness,anger,sadness,raw,final",
    [(0.0, 0.0, 1.0, 1.0, -0.6, 0.0), (1.0, 1.0, 0.0, 0.0, 1.3, 1.0)],
)
def test_g15_clamp(surface, bias, closeness, anger, sadness, raw, final):
    """Historical reference G15: clamp fixture for warmth."""
    x = sample_reference()
    trait(x, "expressive_warmth_bias", bias)
    for name, value in [("closeness_craving", closeness), ("anger", anger), ("sadness", sadness)]:
        state(x, name)["value"] = value
    out = expect_ok(surface, x)
    assert out["values"]["expressive_warmth"] == final
    assert out["audit"]["expressive_warmth"]["unclamped"] == pytest.approx(raw, abs=1e-15, rel=0)
    assert out["audit"]["expressive_warmth"]["clamped"] is True
