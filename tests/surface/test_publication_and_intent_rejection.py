"""Reject malformed Persona pins and Intent Surface causal declarations."""

from __future__ import annotations

import json
from copy import deepcopy
from types import SimpleNamespace

import pytest

from mind_runtime.binding_registry import BindingRegistry, BindingRegistryError
from mind_runtime.intents.surface_validator import (
    get_control_transitive_roots,
    validate_intent_rule_surface_overlap,
)
from mind_runtime.persona_publication import (
    PersonaConfigPublicationRepository,
    PersonaPublicationError,
    PersonaRevisionConflict,
    PersonaRevisionRef,
)
from mind_runtime.runtime_binding import RuntimeBinding, RuntimeEnvironment
from tests.surface.test_persona_publication import _profile, _write


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("persona_id", ""),
        ("persona_id", None),
        ("profile_version", 0),
        ("profile_version", True),
        ("effective_content_digest", "ABC"),
        ("effective_content_digest", None),
    ],
)
def test_exact_persona_reference_rejects_invalid_identity(field, value):
    identity = {
        "persona_id": "persona-a",
        "profile_version": 2,
        "effective_content_digest": "a" * 64,
    }
    identity[field] = value
    with pytest.raises(ValueError):
        PersonaRevisionRef(**identity)


def test_publication_rejects_corrupt_or_replaced_artifact(tmp_path):
    source = _write(tmp_path / "author.json", _profile(0.2))
    repo = PersonaConfigPublicationRepository(tmp_path / "published")
    ref = repo.publish(source)
    artifact = repo.artifact_path(ref)
    artifact.chmod(0o666)
    artifact.write_text("not-json", encoding="utf-8")
    with pytest.raises(PersonaPublicationError, match="PERSONA_ARTIFACT_INVALID"):
        repo.resolve(ref)

    artifact.write_text(json.dumps(_profile(0.8)), encoding="utf-8")
    with pytest.raises(PersonaRevisionConflict, match="PERSONA_REVISION_CONFLICT"):
        repo.resolve(ref)


def test_publication_rejects_ineligible_profile_and_bad_reference(tmp_path):
    repo = PersonaConfigPublicationRepository(tmp_path / "published")
    with pytest.raises(TypeError):
        repo.artifact_path("mutable-alias")
    source = _profile(0.2)
    source["schema_version"] = 1
    source.pop("behavioral_disposition")
    path = _write(tmp_path / "legacy.json", source)
    with pytest.raises(PersonaPublicationError, match="PERSONA_PUBLICATION_INELIGIBLE"):
        repo.publish(path)
    assert not list(repo.root.glob(".persona-publish-*"))


def test_registry_persona_pin_rejects_wrong_identity_and_unknown_binding(tmp_path):
    registry = BindingRegistry(tmp_path / "bindings")
    registry.initialize()
    binding = RuntimeBinding(
        persona_id="persona-a",
        agent_id="agent-a",
        runtime_id="runtime-a",
        storage_namespace="lab/runtime-a",
        environment=RuntimeEnvironment.LAB,
    )
    registry.register(binding, "binding-a")
    good = PersonaRevisionRef("persona-a", 2, "a" * 64)
    wrong = PersonaRevisionRef("persona-b", 2, "a" * 64)
    with pytest.raises(TypeError):
        registry.pin_persona_revision("binding-a", "mutable-alias")
    with pytest.raises(BindingRegistryError, match="ADMISSION_DENIED"):
        registry.pin_persona_revision("binding-a", wrong)
    with pytest.raises(BindingRegistryError, match="BINDING_ID_UNKNOWN"):
        registry.pin_persona_revision("unknown", good)
    assert registry.pin_persona_revision("binding-a", good) == good
    assert registry.pin_persona_revision("binding-a", good) == good


def _surface_rule():
    return {
        "kind": "reach_out",
        "surface_control_weights": {"contact_seeking": 0.4},
        "direct_dynamics_weights": {},
        "event_bonus": 0.0,
    }


@pytest.mark.parametrize(
    ("field", "value", "reason"),
    [
        ("surface_control_weights", "contact_seeking", "SURFACE_CONTROL_INVALID"),
        (
            "surface_control_weights",
            [("contact_seeking", 0.2), ("contact_seeking", 0.3)],
            "duplicate",
        ),
        ("surface_control_weights", [(None, 0.2)], "control name"),
        ("surface_control_weights", [("contact_seeking", True)], "SURFACE_WEIGHT_INVALID"),
        ("surface_control_weights", [("contact_seeking", float("nan"))], "SURFACE_WEIGHT_INVALID"),
        ("surface_control_weights", [("unknown", 0.2)], "SURFACE_CONTROL_INELIGIBLE"),
        ("surface_control_weights", ["bad-pair"], "SURFACE_CONTROL_INVALID"),
        ("direct_dynamics_weights", "longing", "DIRECT_WEIGHT_INVALID"),
        ("direct_dynamics_weights", ["bad-pair"], "DIRECT_WEIGHT_INVALID"),
        ("direct_dynamics_weights", [("unrelated", True)], "DIRECT_WEIGHT_INVALID"),
        ("direct_dynamics_weights", [(None, 0.2)], "DIRECT_WEIGHT_INVALID"),
        ("event_bonus", True, "finite numeric"),
        ("event_bonus", float("inf"), "finite numeric"),
        ("event_bonus", 0.1, "SURFACE_EVENT_BONUS_FORBIDDEN"),
    ],
)
def test_intent_surface_rule_rejects_unreviewed_declarations(field, value, reason):
    rule = _surface_rule()
    rule[field] = value
    with pytest.raises(ValueError, match=reason):
        validate_intent_rule_surface_overlap(rule)


def test_intent_surface_rule_accepts_disjoint_direct_root_and_object_form():
    rule = _surface_rule()
    rule["direct_dynamics_weights"] = {"social_pull": 0.2}
    validate_intent_rule_surface_overlap(rule)
    assert get_control_transitive_roots("unknown") == set()
    assert "agent.affect.longing" in get_control_transitive_roots("contact_seeking")
    object_rule = SimpleNamespace(
        surface_control_weights=(("initiative", 0.2),),
        dimension_weights=(("agent.affect.anger", 0.1),),
        event_bonus=0.0,
    )
    validate_intent_rule_surface_overlap(object_rule)
    duplicate = deepcopy(rule)
    duplicate["direct_dynamics_weights"] = {"agent.affect.longing": 0.0}
    with pytest.raises(ValueError, match="ROOT_OVERLAP"):
        validate_intent_rule_surface_overlap(duplicate)


def test_surface_validator_ignores_legacy_rule_with_no_surface_controls():
    validate_intent_rule_surface_overlap({"surface_control_weights": (), "event_bonus": 0.5})
