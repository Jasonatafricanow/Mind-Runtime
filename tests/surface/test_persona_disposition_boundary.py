"""W3-A Persona Profile Schema 2 & Behavioral Disposition Boundary Tests.

RED BY DESIGN: Schema 2 / behavioral_disposition loader is absent in W3-B0.
These assertions freeze the W3-A requirements:
- load_persona_profile accepts schema_version 2 / profile_version 2 with behavioral_disposition
- behavioral_disposition contains exactly the four declared roots:
  attachment_approach, confrontation_readiness, expressive_restraint, expressive_warmth_bias
- bounds validation: all traits must be finite floats in [0.0, 1.0]
- missing trait fails closed with PersonaProfileError
"""

import json
from pathlib import Path

import pytest

from mind_runtime.persona_config import PersonaProfileError, load_persona_profile


def _write_profile(tmp_path: Path, data: dict) -> Path:
    p = tmp_path / "test_persona.json"
    p.write_text(json.dumps(data), encoding="utf-8")
    return p


def _valid_schema2_data() -> dict:
    return {
        "schema_version": 2,
        "profile_version": 2,
        "persona_id": "persona-fixture-a",
        "dimensions": [
            {
                "dimension": "agent.affect.longing",
                "baseline": 0.0,
                "initial_value": 0.0,
                "sensitivity": 1.0,
                "recovery_rate": 0.0,
                "floor": 0.0,
                "ceiling": 1.0,
                "growth_profile": [],
                "coupling_profile": [],
            }
        ],
        "behavioral_disposition": {
            "attachment_approach": 0.50,
            "confrontation_readiness": 0.50,
            "expressive_restraint": 0.40,
            "expressive_warmth_bias": 0.50,
        },
    }


def test_load_persona_profile_schema_v2_with_behavioral_disposition(tmp_path):
    """W3-A: load_persona_profile loads schema 2 and exposes behavioral_disposition."""
    p = _write_profile(tmp_path, _valid_schema2_data())
    loaded = load_persona_profile(p)
    assert loaded.profile_version == 2
    assert hasattr(loaded, "behavioral_disposition") or hasattr(
        loaded.profile, "behavioral_disposition"
    )
    disposition = (
        getattr(loaded, "behavioral_disposition", None)
        or loaded.profile.behavioral_disposition
    )
    assert disposition == {
        "attachment_approach": 0.50,
        "confrontation_readiness": 0.50,
        "expressive_restraint": 0.40,
        "expressive_warmth_bias": 0.50,
    }


@pytest.mark.parametrize(
    "trait_name,bad_value",
    [
        ("attachment_approach", -0.01),
        ("attachment_approach", 1.01),
        ("confrontation_readiness", float("nan")),
        ("expressive_restraint", float("inf")),
        ("expressive_warmth_bias", "0.5"),
    ],
)
def test_persona_profile_disposition_bounds_validation(tmp_path, trait_name, bad_value):
    """W3-A: Out-of-bounds or nonfinite disposition trait raises PersonaProfileError."""
    data = _valid_schema2_data()
    data["behavioral_disposition"][trait_name] = bad_value
    p = _write_profile(tmp_path, data)
    with pytest.raises(PersonaProfileError, match=r"behavioral_disposition|disposition"):
        load_persona_profile(p)


@pytest.mark.parametrize(
    "missing_trait",
    [
        "attachment_approach",
        "confrontation_readiness",
        "expressive_restraint",
        "expressive_warmth_bias",
    ],
)
def test_persona_profile_missing_required_disposition_trait(tmp_path, missing_trait):
    """W3-A: Missing any required disposition trait raises PersonaProfileError."""
    data = _valid_schema2_data()
    del data["behavioral_disposition"][missing_trait]
    p = _write_profile(tmp_path, data)
    with pytest.raises(PersonaProfileError, match=r"behavioral_disposition|disposition"):
        load_persona_profile(p)
