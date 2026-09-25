"""Persistent Persona pins must fail closed on corrupt or ambiguous bindings."""

from __future__ import annotations

import json

import pytest

from mind_runtime.binding_registry import (
    BindingDescriptor,
    BindingRegistry,
    BindingRegistryError,
    RegistryFailureCode,
)
from mind_runtime.persona_publication import PersonaRevisionRef, ReplayUnavailable
from mind_runtime.runtime_binding import RuntimeBinding, RuntimeEnvironment


def _registry(tmp_path):
    store = tmp_path / "registry.json"
    registry = BindingRegistry(store)
    registry.initialize()
    binding = RuntimeBinding(
        persona_id="persona-a",
        agent_id="agent-a",
        runtime_id="runtime-a",
        storage_namespace="lab/runtime-a",
        environment=RuntimeEnvironment.LAB,
    )
    registry.writer.register(binding, "binding-a")
    return registry, store


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("binding_id", "BAD ID"),
        ("environment", "lab"),
        ("agent_id", ""),
        ("runtime_id", ""),
    ],
)
def test_binding_descriptor_rejects_corrupt_identity(field, value):
    fields = {
        "binding_id": "binding-a",
        "environment": RuntimeEnvironment.LAB,
        "agent_id": "agent-a",
        "runtime_id": "runtime-a",
    }
    fields[field] = value
    with pytest.raises(BindingRegistryError, match="REGISTRY_CORRUPT"):
        BindingDescriptor(**fields)


def test_registry_error_normalizes_unknown_external_code():
    assert BindingRegistryError("NOT_A_CODE").code is RegistryFailureCode.REGISTRY_CORRUPT
    assert BindingRegistryError("ADMISSION_DENIED").code is RegistryFailureCode.ADMISSION_DENIED


@pytest.mark.parametrize(
    "pin",
    [
        "mutable-alias",
        {"persona_id": "persona-a"},
        {"persona_id": "persona-a", "profile_version": 2, "effective_content_digest": "invalid"},
        {"persona_id": "other", "profile_version": 2, "effective_content_digest": "a" * 64},
    ],
)
def test_registry_rejects_corrupt_persisted_persona_pin(tmp_path, pin):
    registry, store = _registry(tmp_path)
    wire = json.loads(store.read_text(encoding="utf-8"))
    wire["entries"][0]["persona_revision_ref"] = pin
    store.write_text(json.dumps(wire), encoding="utf-8")
    with pytest.raises(BindingRegistryError, match="REGISTRY_CORRUPT"):
        registry.reader.list_bindings(environment=RuntimeEnvironment.LAB)


def test_persona_resolution_requires_pin_and_exact_environment(tmp_path):
    registry, _store = _registry(tmp_path)
    with pytest.raises(ReplayUnavailable, match="REPLAY_UNAVAILABLE"):
        registry.reader.resolve_persona_revision("binding-a", environment=RuntimeEnvironment.LAB)
    with pytest.raises(BindingRegistryError, match="ADMISSION_DENIED"):
        registry.reader.resolve_persona_revision(
            "binding-a", environment=RuntimeEnvironment.PRODUCTION
        )
    with pytest.raises(BindingRegistryError, match="BINDING_ID_UNKNOWN"):
        registry.reader.resolve_persona_revision("unknown", environment=RuntimeEnvironment.LAB)
    ref = PersonaRevisionRef("persona-a", 2, "a" * 64)
    assert registry.writer.pin_persona_revision("binding-a", ref) == ref
    assert (
        registry.reader.resolve_persona_revision("binding-a", environment=RuntimeEnvironment.LAB)
        == ref
    )


def test_registry_rejects_unknown_default_and_environment_in_store(tmp_path):
    registry, store = _registry(tmp_path)
    with pytest.raises(BindingRegistryError, match="BINDING_ID_UNKNOWN"):
        registry.writer.set_default("unknown")
    wire = json.loads(store.read_text(encoding="utf-8"))
    wire["entries"][0]["identity"]["environment"] = "unrecognized"
    store.write_text(json.dumps(wire), encoding="utf-8")
    with pytest.raises(BindingRegistryError, match="REGISTRY_CORRUPT"):
        registry.reader.list_bindings(environment=RuntimeEnvironment.LAB)
    with pytest.raises(BindingRegistryError, match="REGISTRY_CORRUPT"):
        registry.reader.resolve_binding(
            "binding-a",
            environment=RuntimeEnvironment.LAB,
            lab_root=tmp_path / "lab",
        )
