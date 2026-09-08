"""Frozen behavior-contract tests for Upstream BindingRegistry (W2-B / W2-C).

Normative authority: ADR-0021 (ACCEPTED at R1), docs/OW_PHASE02_W2B_BINDING_REGISTRY_CONTRACT.md.

Invariants under test:
- I1: Active identity is bijective: one active binding <-> one binding_id.
- I2: Store absent -> REGISTRY_UNINITIALIZED; store corrupt -> REGISTRY_CORRUPT;
      both perform zero writes; no automatic remint.
- I3: Default is explicit; 0 or 1 defaults; never inferred.
- I4: Environment admission is exact equality:
      PRODUCTION admits PRODUCTION only, LAB admits LAB only;
      PRODUCTION -> LAB denied, LAB -> PRODUCTION denied.
- I5: Ordering non-authoritative; call-visible order is not authority.
- I6: Unknown binding_id is terminal; no fallback.
- I7: Registry entry <-> namespace manifest divergence fails closed.
- I9: binding_id URL-safe grammar: ^[a-z0-9][a-z0-9-]{0,63}$.
- Writer / Admin:
  - initialize() on absent creates store; on existing store fails closed (REGISTRY_ALREADY_INITIALIZED).
  - register(binding, binding_id) accepts external authoritative id.
  - duplicate identity rejected (DUPLICATE_ACTIVE_IDENTITY).
  - duplicate id rejected (DUPLICATE_BINDING_ID).
  - set_default(new_id) atomically replaces prior default.
  - clear_default() unsets default.
  - restart preserves minted/registered IDs and default state.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from mind_runtime.binding_registry import (
    BindingDescriptor,
    BindingRegistry,
    BindingRegistryError,
    BindingRegistryReader,
    BindingRegistryWriter,
    DefaultBindingResult,
    NoDefaultReason,
    RegistryFailureCode,
    build_binding_registry,
)
from mind_runtime.runtime_binding import (
    RuntimeBinding,
    RuntimeEnvironment,
    bind_storage,
)


def _make_binding(
    *,
    namespace: str,
    environment: RuntimeEnvironment = RuntimeEnvironment.LAB,
    persona_id: str = "kayla_v0",
    agent_id: str = "test-agent",
    runtime_id: str | None = None,
) -> RuntimeBinding:
    return RuntimeBinding(
        persona_id=persona_id,
        agent_id=agent_id,
        runtime_id=runtime_id or f"rt-{namespace.replace('/', '-')}",
        storage_namespace=namespace,
        environment=environment,
    )


# ---------------------------------------------------------------------------
# Task 1: Failing contract tests against production factory
# ---------------------------------------------------------------------------


class TestBindingRegistryContract:
    def test_factory_creates_registry_implementing_reader_and_writer(
        self, tmp_path: Path
    ) -> None:
        registry = build_binding_registry(tmp_path / "registry")
        assert isinstance(registry.reader, BindingRegistryReader)
        assert isinstance(registry.writer, BindingRegistryWriter)

    def test_i2_absent_store_fails_closed_with_zero_writes(self, tmp_path: Path) -> None:
        store_dir = tmp_path / "absent_registry"
        registry = build_binding_registry(store_dir)

        # Reading from absent store raises REGISTRY_UNINITIALIZED
        with pytest.raises(BindingRegistryError) as exc_info:
            registry.reader.list_bindings(environment=RuntimeEnvironment.PRODUCTION)
        assert exc_info.value.code == RegistryFailureCode.REGISTRY_UNINITIALIZED

        with pytest.raises(BindingRegistryError) as exc_info:
            registry.reader.resolve_binding("xiyue-prod", environment=RuntimeEnvironment.PRODUCTION)
        assert exc_info.value.code == RegistryFailureCode.REGISTRY_UNINITIALIZED

        with pytest.raises(BindingRegistryError) as exc_info:
            registry.reader.default_binding(environment=RuntimeEnvironment.PRODUCTION)
        assert exc_info.value.code == RegistryFailureCode.REGISTRY_UNINITIALIZED

        # Zero writes performed: directory was not created or remains empty
        assert not store_dir.exists() or len(list(store_dir.iterdir())) == 0

    def test_i2_corrupt_store_fails_closed_with_zero_writes(self, tmp_path: Path) -> None:
        store_dir = tmp_path / "corrupt_registry"
        store_dir.mkdir(parents=True, exist_ok=True)
        corrupt_file = store_dir / "registry.json"
        corrupt_file.write_text("{{corrupt json-syntax!!", encoding="utf-8")
        before_bytes = corrupt_file.read_bytes()

        registry = build_binding_registry(store_dir)

        with pytest.raises(BindingRegistryError) as exc_info:
            registry.reader.list_bindings(environment=RuntimeEnvironment.PRODUCTION)
        assert exc_info.value.code == RegistryFailureCode.REGISTRY_CORRUPT

        with pytest.raises(BindingRegistryError) as exc_info:
            registry.reader.resolve_binding("xiyue-prod", environment=RuntimeEnvironment.PRODUCTION)
        assert exc_info.value.code == RegistryFailureCode.REGISTRY_CORRUPT

        with pytest.raises(BindingRegistryError) as exc_info:
            registry.reader.default_binding(environment=RuntimeEnvironment.PRODUCTION)
        assert exc_info.value.code == RegistryFailureCode.REGISTRY_CORRUPT

        # Zero writes performed: corrupt file untouched
        assert corrupt_file.read_bytes() == before_bytes

    def test_writer_initialize_safety(self, tmp_path: Path) -> None:
        store_dir = tmp_path / "init_registry"
        registry = build_binding_registry(store_dir)

        # First initialize succeeds
        registry.writer.initialize()
        # Reader now succeeds with empty list
        assert registry.reader.list_bindings(environment=RuntimeEnvironment.PRODUCTION) == ()

        # Second initialize fails closed
        with pytest.raises(BindingRegistryError) as exc_info:
            registry.writer.initialize()
        assert exc_info.value.code == RegistryFailureCode.REGISTRY_ALREADY_INITIALIZED

    def test_i9_grammar_validation(self, tmp_path: Path) -> None:
        store_dir = tmp_path / "grammar_registry"
        registry = build_binding_registry(store_dir)
        registry.writer.initialize()

        binding = _make_binding(namespace="exp-grammar")
        bind_storage(binding, lab_root=tmp_path / "lab")

        invalid_ids = [
            "",
            "-starts-with-dash",
            "UPPERCASE",
            "has_underscore",
            "has/slash",
            "has space",
            "a" * 65,  # > 64 chars
        ]
        for invalid_id in invalid_ids:
            with pytest.raises((BindingRegistryError, ValueError)):
                registry.writer.register(binding, invalid_id)

    def test_i1_first_explicit_registration_and_duplicate_checks(self, tmp_path: Path) -> None:
        store_dir = tmp_path / "dup_registry"
        registry = build_binding_registry(store_dir)
        registry.writer.initialize()

        lab_root = tmp_path / "lab"
        binding1 = _make_binding(namespace="exp-1")
        bind_storage(binding1, lab_root=lab_root)

        # First explicit registration succeeds
        desc = registry.writer.register(binding1, "binding-1")
        assert desc.binding_id == "binding-1"
        assert desc.environment == RuntimeEnvironment.LAB
        assert desc.agent_id == binding1.agent_id
        assert desc.runtime_id == binding1.runtime_id

        # Duplicate binding_id rejected
        binding2 = _make_binding(namespace="exp-2")
        bind_storage(binding2, lab_root=lab_root)
        with pytest.raises(BindingRegistryError) as exc_info:
            registry.writer.register(binding2, "binding-1")
        assert exc_info.value.code == RegistryFailureCode.DUPLICATE_BINDING_ID

        # Duplicate active identity rejected (same RuntimeBinding under new id)
        with pytest.raises(BindingRegistryError) as exc_info:
            registry.writer.register(binding1, "binding-other")
        assert exc_info.value.code == RegistryFailureCode.DUPLICATE_ACTIVE_IDENTITY

    def test_i4_exact_equality_environment_admission(self, tmp_path: Path) -> None:
        store_dir = tmp_path / "adm_registry"
        registry = build_binding_registry(store_dir)
        registry.writer.initialize()

        prod_root = tmp_path / "prod"
        prod_binding = _make_binding(
            namespace="production/xiyue",
            environment=RuntimeEnvironment.PRODUCTION,
            agent_id="hermes-xiyue",
            runtime_id="xiyue",
        )
        bind_storage(prod_binding, production_root=prod_root)
        registry.writer.register(prod_binding, "xiyue-prod")

        lab_root = tmp_path / "lab"
        lab_binding = _make_binding(
            namespace="exp-lab",
            environment=RuntimeEnvironment.LAB,
            agent_id="agent-lab",
            runtime_id="rt-lab",
        )
        bind_storage(lab_binding, lab_root=lab_root)
        registry.writer.register(lab_binding, "xiyue-lab")

        # PRODUCTION scope: admits ONLY PRODUCTION
        prod_list = registry.reader.list_bindings(environment=RuntimeEnvironment.PRODUCTION)
        assert len(prod_list) == 1
        assert prod_list[0].binding_id == "xiyue-prod"

        resolved_prod = registry.reader.resolve_binding(
            "xiyue-prod", environment=RuntimeEnvironment.PRODUCTION, production_root=prod_root
        )
        assert resolved_prod.storage_namespace == "production/xiyue"

        # PRODUCTION -> LAB denied
        with pytest.raises(BindingRegistryError) as exc_info:
            registry.reader.resolve_binding(
                "xiyue-lab", environment=RuntimeEnvironment.PRODUCTION, production_root=prod_root
            )
        assert exc_info.value.code == RegistryFailureCode.ADMISSION_DENIED

        # LAB scope: admits ONLY LAB
        lab_list = registry.reader.list_bindings(environment=RuntimeEnvironment.LAB)
        assert len(lab_list) == 1
        assert lab_list[0].binding_id == "xiyue-lab"

        resolved_lab = registry.reader.resolve_binding(
            "xiyue-lab", environment=RuntimeEnvironment.LAB, lab_root=lab_root
        )
        assert resolved_lab.storage_namespace == "exp-lab"

        # LAB -> PRODUCTION denied
        with pytest.raises(BindingRegistryError) as exc_info:
            registry.reader.resolve_binding(
                "xiyue-prod", environment=RuntimeEnvironment.LAB, lab_root=lab_root
            )
        assert exc_info.value.code == RegistryFailureCode.ADMISSION_DENIED

    def test_i3_default_declaration_and_atomic_replacement(self, tmp_path: Path) -> None:
        store_dir = tmp_path / "default_registry"
        registry = build_binding_registry(store_dir)
        registry.writer.initialize()

        lab_root = tmp_path / "lab"
        b1 = _make_binding(namespace="exp-def-1")
        b2 = _make_binding(namespace="exp-def-2")
        bind_storage(b1, lab_root=lab_root)
        bind_storage(b2, lab_root=lab_root)

        registry.writer.register(b1, "b-1")
        registry.writer.register(b2, "b-2")

        # Zero defaults declared -> NO_DEFAULT_BINDING
        res0 = registry.reader.default_binding(environment=RuntimeEnvironment.LAB)
        assert res0.status == "NO_DEFAULT_BINDING"
        assert res0.reason == NoDefaultReason.NO_DEFAULT_DECLARED

        # Set explicit default on b-1
        registry.writer.set_default("b-1")
        res1 = registry.reader.default_binding(environment=RuntimeEnvironment.LAB)
        assert res1.status == "DEFAULT_BINDING"
        assert res1.descriptor is not None
        assert res1.descriptor.binding_id == "b-1"
        assert res1.descriptor.environment == RuntimeEnvironment.LAB
        # Resolve descriptor.binding_id to exact registered RuntimeBinding
        resolved_1 = registry.reader.resolve_binding(
            res1.descriptor.binding_id, environment=RuntimeEnvironment.LAB, lab_root=lab_root
        )
        assert resolved_1 == b1

        # Atomic replacement: set b-2 as default unsets b-1
        registry.writer.set_default("b-2")
        res2 = registry.reader.default_binding(environment=RuntimeEnvironment.LAB)
        assert res2.status == "DEFAULT_BINDING"
        assert res2.descriptor is not None
        assert res2.descriptor.binding_id == "b-2"
        resolved_2 = registry.reader.resolve_binding(
            res2.descriptor.binding_id, environment=RuntimeEnvironment.LAB, lab_root=lab_root
        )
        assert resolved_2 == b2

        # Clear default
        registry.writer.clear_default(RuntimeEnvironment.LAB)
        res3 = registry.reader.default_binding(environment=RuntimeEnvironment.LAB)
        assert res3.status == "NO_DEFAULT_BINDING"
        assert res3.reason == NoDefaultReason.NO_DEFAULT_DECLARED

    def test_w2c_r1_default_binding_never_infers_sole_binding(self, tmp_path: Path) -> None:
        store_dir = tmp_path / "sole_binding_registry"
        registry = build_binding_registry(store_dir)
        registry.writer.initialize()

        lab_root = tmp_path / "lab"
        b_sole = _make_binding(namespace="exp-sole")
        bind_storage(b_sole, lab_root=lab_root)

        # Register exactly one binding without declaring default
        registry.writer.register(b_sole, "sole-id")

        # Must NEVER infer the sole binding as default
        res = registry.reader.default_binding(environment=RuntimeEnvironment.LAB)
        assert res.status == "NO_DEFAULT_BINDING"
        assert res.reason == NoDefaultReason.NO_DEFAULT_DECLARED
        assert res.descriptor is None

        # Once explicitly set, default_binding returns exact authoritative descriptor
        registry.writer.set_default("sole-id")
        res_set = registry.reader.default_binding(environment=RuntimeEnvironment.LAB)
        assert res_set.status == "DEFAULT_BINDING"
        assert res_set.descriptor is not None
        assert res_set.descriptor.binding_id == "sole-id"

        # Resolves through descriptor.binding_id to exact registered RuntimeBinding
        resolved = registry.reader.resolve_binding(
            res_set.descriptor.binding_id, environment=RuntimeEnvironment.LAB, lab_root=lab_root
        )
        assert resolved == b_sole

    def test_i6_unknown_binding_id_is_terminal(self, tmp_path: Path) -> None:
        store_dir = tmp_path / "unknown_registry"
        registry = build_binding_registry(store_dir)
        registry.writer.initialize()

        with pytest.raises(BindingRegistryError) as exc_info:
            registry.reader.resolve_binding("nonexistent-id", environment=RuntimeEnvironment.LAB)
        assert exc_info.value.code == RegistryFailureCode.BINDING_ID_UNKNOWN

    def test_i7_manifest_divergence_fails_closed(self, tmp_path: Path) -> None:
        store_dir = tmp_path / "diverge_registry"
        registry = build_binding_registry(store_dir)
        registry.writer.initialize()

        lab_root = tmp_path / "lab"
        binding = _make_binding(namespace="exp-div")
        bind_storage(binding, lab_root=lab_root)
        registry.writer.register(binding, "b-div")

        # Tamper with the namespace manifest
        manifest_path = lab_root / "exp-div" / "binding.json"
        manifest_data = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest_data["agent_id"] = "tampered-agent"
        manifest_path.write_text(json.dumps(manifest_data), encoding="utf-8")

        with pytest.raises(BindingRegistryError) as exc_info:
            registry.reader.resolve_binding("b-div", environment=RuntimeEnvironment.LAB, lab_root=lab_root)
        assert exc_info.value.code == RegistryFailureCode.IDENTITY_MANIFEST_DIVERGENCE

    def test_restart_preserves_registered_ids_and_no_remint(self, tmp_path: Path) -> None:
        store_dir = tmp_path / "restart_registry"
        registry1 = build_binding_registry(store_dir)
        registry1.writer.initialize()

        lab_root = tmp_path / "lab"
        b = _make_binding(namespace="exp-restart")
        bind_storage(b, lab_root=lab_root)
        registry1.writer.register(b, "b-stable")
        registry1.writer.set_default("b-stable")

        # Simulate restart by constructing a new registry instance on the same store
        registry2 = build_binding_registry(store_dir)
        desc_list = registry2.reader.list_bindings(environment=RuntimeEnvironment.LAB)
        assert len(desc_list) == 1
        assert desc_list[0].binding_id == "b-stable"

        default_res = registry2.reader.default_binding(
            environment=RuntimeEnvironment.LAB
        )
        assert default_res.status == "DEFAULT_BINDING"
        assert default_res.descriptor is not None
        assert default_res.descriptor.binding_id == "b-stable"
        resolved_after_restart = registry2.reader.resolve_binding(
            default_res.descriptor.binding_id, environment=RuntimeEnvironment.LAB, lab_root=lab_root
        )
        assert resolved_after_restart.storage_namespace == "exp-restart"

    def test_load_time_multiple_defaults_fails_closed(self, tmp_path: Path) -> None:
        store_dir = tmp_path / "multi_defaults"
        store_dir.mkdir(parents=True, exist_ok=True)
        (store_dir / "registry.json").write_text(
            json.dumps({
                "version": 1,
                "entries": [
                    {
                        "binding_id": "b-1",
                        "is_default": True,
                        "identity": {
                            "environment": "lab",
                            "persona_id": "p",
                            "agent_id": "a1",
                            "runtime_id": "r1",
                            "storage_namespace": "exp-1",
                        },
                    },
                    {
                        "binding_id": "b-2",
                        "is_default": True,
                        "identity": {
                            "environment": "lab",
                            "persona_id": "p",
                            "agent_id": "a2",
                            "runtime_id": "r2",
                            "storage_namespace": "exp-2",
                        },
                    },
                ],
            }),
            encoding="utf-8",
        )
        registry = build_binding_registry(store_dir)
        with pytest.raises(BindingRegistryError) as exc_info:
            registry.reader.list_bindings(environment=RuntimeEnvironment.LAB)
        assert exc_info.value.code == RegistryFailureCode.MULTIPLE_DEFAULTS

    def test_load_time_duplicate_binding_id_fails_closed(self, tmp_path: Path) -> None:
        store_dir = tmp_path / "dup_id_store"
        store_dir.mkdir(parents=True, exist_ok=True)
        (store_dir / "registry.json").write_text(
            json.dumps({
                "version": 1,
                "entries": [
                    {
                        "binding_id": "same-id",
                        "is_default": False,
                        "identity": {
                            "environment": "lab",
                            "persona_id": "p",
                            "agent_id": "a1",
                            "runtime_id": "r1",
                            "storage_namespace": "exp-1",
                        },
                    },
                    {
                        "binding_id": "same-id",
                        "is_default": False,
                        "identity": {
                            "environment": "lab",
                            "persona_id": "p",
                            "agent_id": "a2",
                            "runtime_id": "r2",
                            "storage_namespace": "exp-2",
                        },
                    },
                ],
            }),
            encoding="utf-8",
        )
        registry = build_binding_registry(store_dir)
        with pytest.raises(BindingRegistryError) as exc_info:
            registry.reader.list_bindings(environment=RuntimeEnvironment.LAB)
        assert exc_info.value.code == RegistryFailureCode.DUPLICATE_BINDING_ID

    def test_load_time_duplicate_active_identity_fails_closed(self, tmp_path: Path) -> None:
        store_dir = tmp_path / "dup_identity_store"
        store_dir.mkdir(parents=True, exist_ok=True)
        (store_dir / "registry.json").write_text(
            json.dumps({
                "version": 1,
                "entries": [
                    {
                        "binding_id": "id-1",
                        "is_default": False,
                        "identity": {
                            "environment": "lab",
                            "persona_id": "p",
                            "agent_id": "same-agent",
                            "runtime_id": "r1",
                            "storage_namespace": "exp-1",
                        },
                    },
                    {
                        "binding_id": "id-2",
                        "is_default": False,
                        "identity": {
                            "environment": "lab",
                            "persona_id": "p",
                            "agent_id": "same-agent",
                            "runtime_id": "r1",
                            "storage_namespace": "exp-1",
                        },
                    },
                ],
            }),
            encoding="utf-8",
        )
        registry = build_binding_registry(store_dir)
        with pytest.raises(BindingRegistryError) as exc_info:
            registry.reader.list_bindings(environment=RuntimeEnvironment.LAB)
        assert exc_info.value.code == RegistryFailureCode.DUPLICATE_ACTIVE_IDENTITY

    def test_i5_ordering_is_non_authoritative(self, tmp_path: Path) -> None:
        dir_a = tmp_path / "order_a"
        dir_b = tmp_path / "order_b"
        reg_a = build_binding_registry(dir_a)
        reg_b = build_binding_registry(dir_b)
        reg_a.writer.initialize()
        reg_b.writer.initialize()

        lab_root = tmp_path / "lab"
        b1 = _make_binding(namespace="exp-ord-1", agent_id="a1")
        b2 = _make_binding(namespace="exp-ord-2", agent_id="a2")
        bind_storage(b1, lab_root=lab_root)
        bind_storage(b2, lab_root=lab_root)

        # Register in order 1, 2
        reg_a.writer.register(b1, "b-1")
        reg_a.writer.register(b2, "b-2")

        # Register in order 2, 1
        reg_b.writer.register(b2, "b-2")
        reg_b.writer.register(b1, "b-1")

        list_a = reg_a.reader.list_bindings(environment=RuntimeEnvironment.LAB)
        list_b = reg_b.reader.list_bindings(environment=RuntimeEnvironment.LAB)

        # Set of descriptors is identical
        assert set(list_a) == set(list_b)

    # -----------------------------------------------------------------------
    # W2-C-R2 Proofs A-I: Environment-Scoped Default Authority
    # -----------------------------------------------------------------------

    def test_w2c_r2_proof_a_prod_and_lab_defaults_load_successfully(
        self, tmp_path: Path
    ) -> None:
        """Proof A: PRODUCTION default + LAB default load successfully side by side."""
        store_dir = tmp_path / "proof_a_store"
        store_dir.mkdir(parents=True, exist_ok=True)
        (store_dir / "registry.json").write_text(
            json.dumps({
                "version": 1,
                "entries": [
                    {
                        "binding_id": "b-prod",
                        "is_default": True,
                        "identity": {
                            "environment": "production",
                            "persona_id": "p-prod",
                            "agent_id": "a-prod",
                            "runtime_id": "r-prod",
                            "storage_namespace": "production/xiyue",
                        },
                    },
                    {
                        "binding_id": "b-lab",
                        "is_default": True,
                        "identity": {
                            "environment": "lab",
                            "persona_id": "p-lab",
                            "agent_id": "a-lab",
                            "runtime_id": "r-lab",
                            "storage_namespace": "exp-lab",
                        },
                    },
                ],
            }),
            encoding="utf-8",
        )
        registry = build_binding_registry(store_dir)
        # Both environments load without MULTIPLE_DEFAULTS
        prod_list = registry.reader.list_bindings(environment=RuntimeEnvironment.PRODUCTION)
        assert len(prod_list) == 1
        assert prod_list[0].binding_id == "b-prod"

        lab_list = registry.reader.list_bindings(environment=RuntimeEnvironment.LAB)
        assert len(lab_list) == 1
        assert lab_list[0].binding_id == "b-lab"

    def test_w2c_r2_proof_b_two_prod_defaults_fail_closed(
        self, tmp_path: Path
    ) -> None:
        """Proof B: Two PRODUCTION defaults fail closed with MULTIPLE_DEFAULTS."""
        store_dir = tmp_path / "proof_b_store"
        store_dir.mkdir(parents=True, exist_ok=True)
        (store_dir / "registry.json").write_text(
            json.dumps({
                "version": 1,
                "entries": [
                    {
                        "binding_id": "prod-1",
                        "is_default": True,
                        "identity": {
                            "environment": "production",
                            "persona_id": "p1",
                            "agent_id": "a1",
                            "runtime_id": "r1",
                            "storage_namespace": "production/p1",
                        },
                    },
                    {
                        "binding_id": "prod-2",
                        "is_default": True,
                        "identity": {
                            "environment": "production",
                            "persona_id": "p2",
                            "agent_id": "a2",
                            "runtime_id": "r2",
                            "storage_namespace": "production/p2",
                        },
                    },
                ],
            }),
            encoding="utf-8",
        )
        registry = build_binding_registry(store_dir)
        with pytest.raises(BindingRegistryError) as exc_info:
            registry.reader.list_bindings(environment=RuntimeEnvironment.PRODUCTION)
        assert exc_info.value.code == RegistryFailureCode.MULTIPLE_DEFAULTS

    def test_w2c_r2_proof_c_two_lab_defaults_fail_closed(
        self, tmp_path: Path
    ) -> None:
        """Proof C: Two LAB defaults fail closed with MULTIPLE_DEFAULTS."""
        store_dir = tmp_path / "proof_c_store"
        store_dir.mkdir(parents=True, exist_ok=True)
        (store_dir / "registry.json").write_text(
            json.dumps({
                "version": 1,
                "entries": [
                    {
                        "binding_id": "lab-1",
                        "is_default": True,
                        "identity": {
                            "environment": "lab",
                            "persona_id": "p1",
                            "agent_id": "a1",
                            "runtime_id": "r1",
                            "storage_namespace": "exp-1",
                        },
                    },
                    {
                        "binding_id": "lab-2",
                        "is_default": True,
                        "identity": {
                            "environment": "lab",
                            "persona_id": "p2",
                            "agent_id": "a2",
                            "runtime_id": "r2",
                            "storage_namespace": "exp-2",
                        },
                    },
                ],
            }),
            encoding="utf-8",
        )
        registry = build_binding_registry(store_dir)
        with pytest.raises(BindingRegistryError) as exc_info:
            registry.reader.list_bindings(environment=RuntimeEnvironment.LAB)
        assert exc_info.value.code == RegistryFailureCode.MULTIPLE_DEFAULTS

    def test_w2c_r2_proof_d_default_binding_prod_returns_only_prod_descriptor(
        self, tmp_path: Path
    ) -> None:
        """Proof D: default_binding(PRODUCTION) returns only PRODUCTION descriptor."""
        store_dir = tmp_path / "proof_d_store"
        store_dir.mkdir(parents=True, exist_ok=True)
        (store_dir / "registry.json").write_text(
            json.dumps({
                "version": 1,
                "entries": [
                    {
                        "binding_id": "prod-xiyue",
                        "is_default": True,
                        "identity": {
                            "environment": "production",
                            "persona_id": "p-prod",
                            "agent_id": "hermes-xiyue",
                            "runtime_id": "rt-xiyue",
                            "storage_namespace": "production/xiyue",
                        },
                    },
                    {
                        "binding_id": "lab-exp",
                        "is_default": True,
                        "identity": {
                            "environment": "lab",
                            "persona_id": "p-lab",
                            "agent_id": "agent-lab",
                            "runtime_id": "rt-lab",
                            "storage_namespace": "exp-lab",
                        },
                    },
                ],
            }),
            encoding="utf-8",
        )
        registry = build_binding_registry(store_dir)
        res = registry.reader.default_binding(environment=RuntimeEnvironment.PRODUCTION)
        assert res.status == "DEFAULT_BINDING"
        assert res.descriptor is not None
        assert res.descriptor.binding_id == "prod-xiyue"
        assert res.descriptor.environment == RuntimeEnvironment.PRODUCTION
        assert res.descriptor.agent_id == "hermes-xiyue"

    def test_w2c_r2_proof_e_default_binding_lab_returns_only_lab_descriptor(
        self, tmp_path: Path
    ) -> None:
        """Proof E: default_binding(LAB) returns only LAB descriptor."""
        store_dir = tmp_path / "proof_e_store"
        store_dir.mkdir(parents=True, exist_ok=True)
        (store_dir / "registry.json").write_text(
            json.dumps({
                "version": 1,
                "entries": [
                    {
                        "binding_id": "prod-xiyue",
                        "is_default": True,
                        "identity": {
                            "environment": "production",
                            "persona_id": "p-prod",
                            "agent_id": "hermes-xiyue",
                            "runtime_id": "rt-xiyue",
                            "storage_namespace": "production/xiyue",
                        },
                    },
                    {
                        "binding_id": "lab-exp",
                        "is_default": True,
                        "identity": {
                            "environment": "lab",
                            "persona_id": "p-lab",
                            "agent_id": "agent-lab",
                            "runtime_id": "rt-lab",
                            "storage_namespace": "exp-lab",
                        },
                    },
                ],
            }),
            encoding="utf-8",
        )
        registry = build_binding_registry(store_dir)
        res = registry.reader.default_binding(environment=RuntimeEnvironment.LAB)
        assert res.status == "DEFAULT_BINDING"
        assert res.descriptor is not None
        assert res.descriptor.binding_id == "lab-exp"
        assert res.descriptor.environment == RuntimeEnvironment.LAB
        assert res.descriptor.agent_id == "agent-lab"

    def test_w2c_r2_proof_f_set_default_prod_replaces_prod_only_lab_unchanged(
        self, tmp_path: Path
    ) -> None:
        """Proof F: set_default(PRODUCTION-B) replaces PRODUCTION-A only; LAB default remains unchanged."""
        store_dir = tmp_path / "proof_f_store"
        registry = build_binding_registry(store_dir)
        registry.writer.initialize()

        p_a = _make_binding(namespace="production/pa", environment=RuntimeEnvironment.PRODUCTION, agent_id="pa")
        p_b = _make_binding(namespace="production/pb", environment=RuntimeEnvironment.PRODUCTION, agent_id="pb")
        l_a = _make_binding(namespace="exp-la", environment=RuntimeEnvironment.LAB, agent_id="la")

        registry.writer.register(p_a, "prod-a")
        registry.writer.register(p_b, "prod-b")
        registry.writer.register(l_a, "lab-a")

        registry.writer.set_default("prod-a")
        registry.writer.set_default("lab-a")

        # Prior state: prod-a is default in PROD, lab-a is default in LAB
        assert registry.reader.default_binding(environment=RuntimeEnvironment.PRODUCTION).descriptor.binding_id == "prod-a"
        assert registry.reader.default_binding(environment=RuntimeEnvironment.LAB).descriptor.binding_id == "lab-a"

        # Action: set_default(prod-b)
        registry.writer.set_default("prod-b")

        # PROD default replaced by prod-b
        prod_res = registry.reader.default_binding(environment=RuntimeEnvironment.PRODUCTION)
        assert prod_res.status == "DEFAULT_BINDING"
        assert prod_res.descriptor.binding_id == "prod-b"

        # LAB default strictly unchanged
        lab_res = registry.reader.default_binding(environment=RuntimeEnvironment.LAB)
        assert lab_res.status == "DEFAULT_BINDING"
        assert lab_res.descriptor.binding_id == "lab-a"

    def test_w2c_r2_proof_g_set_default_lab_replaces_lab_only_prod_unchanged(
        self, tmp_path: Path
    ) -> None:
        """Proof G: set_default(LAB-B) replaces LAB-A only; PRODUCTION default remains unchanged."""
        store_dir = tmp_path / "proof_g_store"
        registry = build_binding_registry(store_dir)
        registry.writer.initialize()

        p_a = _make_binding(namespace="production/pa", environment=RuntimeEnvironment.PRODUCTION, agent_id="pa")
        l_a = _make_binding(namespace="exp-la", environment=RuntimeEnvironment.LAB, agent_id="la")
        l_b = _make_binding(namespace="exp-lb", environment=RuntimeEnvironment.LAB, agent_id="lb")

        registry.writer.register(p_a, "prod-a")
        registry.writer.register(l_a, "lab-a")
        registry.writer.register(l_b, "lab-b")

        registry.writer.set_default("prod-a")
        registry.writer.set_default("lab-a")

        # Action: set_default(lab-b)
        registry.writer.set_default("lab-b")

        # LAB default replaced by lab-b
        lab_res = registry.reader.default_binding(environment=RuntimeEnvironment.LAB)
        assert lab_res.status == "DEFAULT_BINDING"
        assert lab_res.descriptor.binding_id == "lab-b"

        # PRODUCTION default strictly unchanged
        prod_res = registry.reader.default_binding(environment=RuntimeEnvironment.PRODUCTION)
        assert prod_res.status == "DEFAULT_BINDING"
        assert prod_res.descriptor.binding_id == "prod-a"

    def test_w2c_r2_proof_h_clear_default_prod_does_not_clear_lab_default(
        self, tmp_path: Path
    ) -> None:
        """Proof H: clear_default(PRODUCTION) does not clear LAB default."""
        store_dir = tmp_path / "proof_h_store"
        registry = build_binding_registry(store_dir)
        registry.writer.initialize()

        p_a = _make_binding(namespace="production/pa", environment=RuntimeEnvironment.PRODUCTION, agent_id="pa")
        l_a = _make_binding(namespace="exp-la", environment=RuntimeEnvironment.LAB, agent_id="la")

        registry.writer.register(p_a, "prod-a")
        registry.writer.register(l_a, "lab-a")

        registry.writer.set_default("prod-a")
        registry.writer.set_default("lab-a")

        # Action: clear_default(PRODUCTION)
        registry.writer.clear_default(RuntimeEnvironment.PRODUCTION)

        # PROD default cleared
        prod_res = registry.reader.default_binding(environment=RuntimeEnvironment.PRODUCTION)
        assert prod_res.status == "NO_DEFAULT_BINDING"
        assert prod_res.reason == NoDefaultReason.NO_DEFAULT_DECLARED

        # LAB default strictly remains intact
        lab_res = registry.reader.default_binding(environment=RuntimeEnvironment.LAB)
        assert lab_res.status == "DEFAULT_BINDING"
        assert lab_res.descriptor.binding_id == "lab-a"

    def test_w2c_r2_proof_i_sole_binding_without_explicit_default_returns_no_default_binding(
        self, tmp_path: Path
    ) -> None:
        """Proof I: sole binding without explicit default still returns NO_DEFAULT_BINDING."""
        store_dir = tmp_path / "proof_i_store"
        registry = build_binding_registry(store_dir)
        registry.writer.initialize()

        p_sole = _make_binding(namespace="production/sole", environment=RuntimeEnvironment.PRODUCTION, agent_id="sole")

        registry.writer.register(p_sole, "sole-prod")

        # Exactly 1 binding exists in PRODUCTION, but no default declared
        res = registry.reader.default_binding(environment=RuntimeEnvironment.PRODUCTION)
        assert res.status == "NO_DEFAULT_BINDING"
        assert res.reason == NoDefaultReason.NO_DEFAULT_DECLARED
        assert res.descriptor is None

