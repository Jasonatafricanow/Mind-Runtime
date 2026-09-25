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

from mind_runtime.contracts import BehavioralDisposition
from mind_runtime.persona_config import (
    PersonaProfileError,
    clear_persona_registry,
    load_persona_profile,
)


@pytest.fixture(autouse=True)
def _reset_registry():
    clear_persona_registry()
    yield
    clear_persona_registry()


def _write_profile(tmp_path: Path, data: dict, filename: str = "test_persona.json") -> Path:
    p = tmp_path / filename
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
    assert loaded.schema_version == 2
    assert hasattr(loaded, "behavioral_disposition") or hasattr(
        loaded.profile, "behavioral_disposition"
    )
    disposition = (
        getattr(loaded, "behavioral_disposition", None) or loaded.profile.behavioral_disposition
    )
    assert disposition == {
        "attachment_approach": 0.50,
        "confrontation_readiness": 0.50,
        "expressive_restraint": 0.40,
        "expressive_warmth_bias": 0.50,
    }
    assert loaded.is_surface_eligible is True
    assert loaded.profile.is_surface_eligible is True
    assert bool(loaded.effective_content_digest)
    assert loaded.persona_content_digest == loaded.effective_content_digest


@pytest.mark.parametrize(
    "trait_name,bad_value",
    [
        ("attachment_approach", -0.01),
        ("attachment_approach", 1.01),
        ("confrontation_readiness", float("nan")),
        ("expressive_restraint", float("inf")),
        ("expressive_restraint", -float("inf")),
        ("expressive_warmth_bias", "0.5"),
        ("attachment_approach", None),
        ("confrontation_readiness", True),
        ("expressive_warmth_bias", False),
    ],
)
def test_persona_profile_disposition_bounds_validation(tmp_path, trait_name, bad_value):
    """Reject invalid behavioral disposition trait values."""
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


@pytest.mark.parametrize(
    "unknown_key",
    [
        "attachment_anxiety",
        "introversion",
        "jealousy",
        "extra_field",
    ],
)
def test_persona_profile_disposition_unknown_key_rejected(tmp_path, unknown_key):
    """W3-A: Unknown trait keys in behavioral_disposition fail closed."""
    data = _valid_schema2_data()
    data["behavioral_disposition"][unknown_key] = 0.50
    p = _write_profile(tmp_path, data)
    with pytest.raises(PersonaProfileError, match=r"behavioral_disposition|disposition"):
        load_persona_profile(p)


def test_persona_profile_schema_1_legacy_compatibility(tmp_path):
    """W3-A: Absent schema_version decodes as legacy schema 1 without disposition."""
    data = _valid_schema2_data()
    del data["schema_version"]
    del data["behavioral_disposition"]
    data["profile_version"] = 1
    p = _write_profile(tmp_path, data)
    loaded = load_persona_profile(p)
    assert loaded.schema_version == 1
    assert loaded.profile_version == 1
    assert loaded.behavioral_disposition is None
    assert loaded.profile.behavioral_disposition is None
    # Schema 1 is NEVER eligible for Surface V1
    assert loaded.is_surface_eligible is False
    assert loaded.profile.is_surface_eligible is False


def test_persona_profile_schema_1_rejects_behavioral_disposition(tmp_path):
    """W3-A: Explicit or implicit schema 1 rejects presence of behavioral_disposition."""
    data = _valid_schema2_data()
    data["schema_version"] = 1
    p = _write_profile(tmp_path, data)
    with pytest.raises(PersonaProfileError, match=r"schema 1"):
        load_persona_profile(p)


def test_persona_profile_schema_2_requires_disposition_block(tmp_path):
    """W3-A: Schema 2 without behavioral_disposition fails closed."""
    data = _valid_schema2_data()
    del data["behavioral_disposition"]
    p = _write_profile(tmp_path, data)
    with pytest.raises(PersonaProfileError, match=r"behavioral_disposition|disposition"):
        load_persona_profile(p)


@pytest.mark.parametrize("bad_schema", [3, 99, "2", -1])
def test_persona_profile_unsupported_schema_version_rejected(tmp_path, bad_schema):
    """W3-A: Unknown or non-integer schema_version is rejected."""
    data = _valid_schema2_data()
    data["schema_version"] = bad_schema
    p = _write_profile(tmp_path, data)
    with pytest.raises(PersonaProfileError, match=r"unsupported schema_version"):
        load_persona_profile(p)


@pytest.mark.parametrize("bad_revision", [0, -1, True, False, "1"])
def test_persona_profile_invalid_revision_rejected(tmp_path, bad_revision):
    """W3-A: Profile revision must be a positive integer."""
    data = _valid_schema2_data()
    data["profile_version"] = bad_revision
    p = _write_profile(tmp_path, data)
    with pytest.raises(PersonaProfileError, match=r"profile_version"):
        load_persona_profile(p)


def test_persona_profile_same_id_revision_different_content_conflict(tmp_path):
    """W3-A: Same persona_id + same revision + different content fails closed as conflict."""
    data_a = _valid_schema2_data()
    data_a["persona_id"] = "conflict-persona"
    data_a["profile_version"] = 3
    data_a["behavioral_disposition"]["attachment_approach"] = 0.30
    p_a = _write_profile(tmp_path, data_a, "persona_a.json")
    loaded_a = load_persona_profile(p_a)
    assert loaded_a.persona_id == "conflict-persona"

    # Same content again should succeed (idempotent reload)
    loaded_a_again = load_persona_profile(p_a)
    assert loaded_a_again.effective_content_digest == loaded_a.effective_content_digest

    # Different content under same persona_id + revision must reject
    data_b = _valid_schema2_data()
    data_b["persona_id"] = "conflict-persona"
    data_b["profile_version"] = 3
    data_b["behavioral_disposition"]["attachment_approach"] = 0.90  # mutated content!
    p_b = _write_profile(tmp_path, data_b, "persona_b.json")
    with pytest.raises(PersonaProfileError, match=r"conflict"):
        load_persona_profile(p_b)


def test_persona_profile_stable_canonical_digest(tmp_path):
    """W3-A: Field ordering does not alter canonical content digest."""
    data1 = _valid_schema2_data()
    # Add second dimension
    data1["dimensions"].append(
        {
            "dimension": "agent.affect.anger",
            "baseline": 0.1,
            "initial_value": 0.1,
            "sensitivity": 0.8,
            "recovery_rate": 0.05,
            "floor": 0.0,
            "ceiling": 1.0,
            "growth_profile": [],
            "coupling_profile": [],
        }
    )
    p1 = _write_profile(tmp_path, data1, "p1.json")
    loaded1 = load_persona_profile(p1)

    # Reorder top-level keys, reverse dimensions list, reorder disposition keys
    clear_persona_registry()
    data2 = {
        "behavioral_disposition": {
            "expressive_warmth_bias": 0.50,
            "expressive_restraint": 0.40,
            "confrontation_readiness": 0.50,
            "attachment_approach": 0.50,
        },
        "persona_id": "persona-fixture-a",
        "dimensions": list(reversed(data1["dimensions"])),
        "profile_version": 2,
        "schema_version": 2,
    }
    p2 = _write_profile(tmp_path, data2, "p2.json")
    loaded2 = load_persona_profile(p2)

    assert loaded1.effective_content_digest == loaded2.effective_content_digest
    assert len(loaded1.effective_content_digest) == 64


def test_persona_profile_disposition_immutability(tmp_path):
    """W3-A: BehavioralDisposition is an immutable value object; consumer mutations reject."""
    p = _write_profile(tmp_path, _valid_schema2_data())
    loaded = load_persona_profile(p)
    disp = loaded.profile.behavioral_disposition
    assert isinstance(disp, BehavioralDisposition)

    # Typed attribute read works
    assert disp.attachment_approach == 0.50
    # Dict-like read works
    assert disp["attachment_approach"] == 0.50

    # Item mutation is rejected
    with pytest.raises(TypeError):
        disp["attachment_approach"] = 0.99

    # Attribute mutation is rejected
    with pytest.raises((AttributeError, Exception)):
        disp.attachment_approach = 0.99
