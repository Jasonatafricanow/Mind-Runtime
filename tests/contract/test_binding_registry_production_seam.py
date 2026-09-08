"""Behavior-contract tests for MR-BINDING-REGISTRY-PRODUCTION-SEAM-V1 (W2-C.5).

Normative authority:
- TICKET: MR-BINDING-REGISTRY-PRODUCTION-SEAM-V1
- ADR-0021 (Multi-Binding Registry Authority)
- ADR-0020 (Runtime Identity Binding & Storage Isolation)
- docs/MR_BINDING_REGISTRY_PRODUCTION_SEAM_V1.md

Required tests (Ticket §17):
- A: uninitialized registry -> REGISTRY_UNINITIALIZED + zero writes
- B: corrupt registry -> REGISTRY_CORRUPT + zero writes
- C: explicit admin bootstrap -> initialize/register succeeds
- D: bootstrap requires explicit binding_id (rejects derived/empty)
- E: restart preserves binding_id
- F: normal reader startup never remints or repairs
- G: multi-production bindings enumerate correctly
- H: OW/read consumer gets only BindingRegistryReader surface
- I: writer/admin surface is not exposed by production read factory
- J: generic observation_window source contains no registry path logic
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from mind_runtime.binding_registry import (
    BindingDescriptor,
    BindingRegistryError,
    BindingRegistryReader,
    BindingRegistryWriter,
    RegistryFailureCode,
)
from mind_runtime.binding_registry_composition import (
    DEFAULT_LAB_REGISTRY_ROOT,
    DEFAULT_PRODUCTION_REGISTRY_ROOT,
    MR_BINDING_REGISTRY_DIR_ENV,
    BindingRegistryLocationProvider,
    bootstrap_production_registry,
    lab_registry_location,
    open_binding_registry_admin,
    open_production_binding_registry_reader,
    production_registry_location,
)
from mind_runtime.runtime_binding import (
    DEFAULT_PRODUCTION_ROOT,
    RuntimeBinding,
    RuntimeEnvironment,
)


# ===========================================================================
# 0. Location Authority Tests
# ===========================================================================


def test_location_provider_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    """Location provider respects upstream defaults when env is unset."""
    monkeypatch.delenv(MR_BINDING_REGISTRY_DIR_ENV, raising=False)

    prod_loc = production_registry_location()
    assert prod_loc == DEFAULT_PRODUCTION_REGISTRY_ROOT
    assert prod_loc == BindingRegistryLocationProvider.production_location()

    # Never inside individual binding namespace production/xiyue
    assert "production/xiyue" not in prod_loc.as_posix()
    assert "profiles/xiyue/runtime" not in prod_loc.as_posix()

    lab_loc = lab_registry_location()
    assert lab_loc == DEFAULT_LAB_REGISTRY_ROOT
    assert lab_loc == BindingRegistryLocationProvider.lab_location()

    named_lab = lab_registry_location("exp-1")
    assert named_lab == DEFAULT_LAB_REGISTRY_ROOT / "exp-1"


def test_location_provider_env_override(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Upstream MR_BINDING_REGISTRY_DIR overrides production location."""
    custom_dir = tmp_path / "custom_registry"
    monkeypatch.setenv(MR_BINDING_REGISTRY_DIR_ENV, str(custom_dir))

    assert production_registry_location() == custom_dir
    assert BindingRegistryLocationProvider.production_location() == custom_dir


# ===========================================================================
# Test A: Uninitialized Registry
# ===========================================================================


def test_a_uninitialized_registry_fails_closed_zero_writes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A. Uninitialized registry -> REGISTRY_UNINITIALIZED + zero writes."""
    store_dir = tmp_path / "absent_registry"
    monkeypatch.setenv(MR_BINDING_REGISTRY_DIR_ENV, str(store_dir))

    with pytest.raises(BindingRegistryError) as exc_info:
        open_production_binding_registry_reader()

    assert exc_info.value.code == RegistryFailureCode.REGISTRY_UNINITIALIZED

    # Must perform zero writes: store file and directory must not be created
    assert not (store_dir / "registry.json").exists()


# ===========================================================================
# Test B: Corrupt Registry
# ===========================================================================


def test_b_corrupt_registry_fails_closed_zero_writes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """B. Corrupt registry -> REGISTRY_CORRUPT + zero writes."""
    store_dir = tmp_path / "corrupt_registry"
    store_dir.mkdir(parents=True)
    store_file = store_dir / "registry.json"
    corrupt_content = "{ invalid json content: 123"
    store_file.write_text(corrupt_content, encoding="utf-8")

    monkeypatch.setenv(MR_BINDING_REGISTRY_DIR_ENV, str(store_dir))

    with pytest.raises(BindingRegistryError) as exc_info:
        open_production_binding_registry_reader()

    assert exc_info.value.code == RegistryFailureCode.REGISTRY_CORRUPT

    # Must perform zero writes: file content unmodified
    assert store_file.read_text(encoding="utf-8") == corrupt_content


# ===========================================================================
# Test C: Explicit Admin Bootstrap
# ===========================================================================


def test_c_explicit_admin_bootstrap_succeeds(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """C. Explicit admin bootstrap -> initialize/register succeeds and persists."""
    store_dir = tmp_path / "bootstrap_registry"
    monkeypatch.setenv(MR_BINDING_REGISTRY_DIR_ENV, str(store_dir))

    desc = bootstrap_production_registry(
        binding_id="production-xiyue",
        is_default=True,
        persona_id="kayla_v0",
    )

    assert isinstance(desc, BindingDescriptor)
    assert desc.binding_id == "production-xiyue"
    assert desc.environment == RuntimeEnvironment.PRODUCTION
    assert desc.agent_id == "hermes-xiyue"
    assert desc.runtime_id == "xiyue"

    # Store file exists on disk
    store_file = store_dir / "registry.json"
    assert store_file.is_file()

    # Read port opens cleanly and resolves the bootstrapped binding
    reader = open_production_binding_registry_reader()
    bindings = reader.list_bindings(environment=RuntimeEnvironment.PRODUCTION)
    assert len(bindings) == 1
    assert bindings[0] == desc

    default_res = reader.default_binding(
        environment=RuntimeEnvironment.PRODUCTION,
        production_root=DEFAULT_PRODUCTION_ROOT,
    )
    assert default_res.status == "DEFAULT_BINDING"
    assert default_res.descriptor == desc


# ===========================================================================
# Test D: Bootstrap Requires Explicit binding_id
# ===========================================================================


@pytest.mark.parametrize("invalid_id", ["", "   ", "UPPERCASE", "with spaces", "invalid/slash", None])
def test_d_bootstrap_requires_explicit_binding_id(
    invalid_id: str | None, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """D. Bootstrap requires explicit binding_id (rejects derived/empty/malformed)."""
    store_dir = tmp_path / "invalid_id_registry"
    monkeypatch.setenv(MR_BINDING_REGISTRY_DIR_ENV, str(store_dir))

    with pytest.raises((BindingRegistryError, ValueError)):
        bootstrap_production_registry(
            binding_id=invalid_id,  # type: ignore[arg-type]
            persona_id="kayla_v0",
        )

    # Zero writes
    assert not (store_dir / "registry.json").exists()


# ===========================================================================
# Test E: Restart Preserves binding_id
# ===========================================================================


def test_e_restart_preserves_binding_id(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """E. Restart preserves binding_id without reminting or reconstruction."""
    store_dir = tmp_path / "restart_registry"
    monkeypatch.setenv(MR_BINDING_REGISTRY_DIR_ENV, str(store_dir))

    minted_id = "explicit-prod-001"
    desc1 = bootstrap_production_registry(
        binding_id=minted_id,
        is_default=True,
        persona_id="kayla_v0",
    )
    assert desc1.binding_id == minted_id

    # Simulate fresh process restart by creating a new reader instance
    reader2 = open_production_binding_registry_reader()
    default2 = reader2.default_binding(
        environment=RuntimeEnvironment.PRODUCTION,
        production_root=DEFAULT_PRODUCTION_ROOT,
    )
    assert default2.status == "DEFAULT_BINDING"
    assert default2.descriptor is not None
    assert default2.descriptor.binding_id == minted_id
    assert default2.descriptor == desc1

    resolved2 = reader2.resolve_binding(
        minted_id,
        environment=RuntimeEnvironment.PRODUCTION,
        production_root=DEFAULT_PRODUCTION_ROOT,
    )
    assert resolved2.persona_id == "kayla_v0"
    assert resolved2.agent_id == "hermes-xiyue"
    assert resolved2.runtime_id == "xiyue"
    assert resolved2.storage_namespace == "production/xiyue"


# ===========================================================================
# Test F: Normal Reader Startup Never Remints or Repairs
# ===========================================================================


def test_f_normal_reader_startup_never_remints_or_repairs(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """F. Normal reader startup never remints, repairs, or writes."""
    store_dir = tmp_path / "no_remint_registry"
    monkeypatch.setenv(MR_BINDING_REGISTRY_DIR_ENV, str(store_dir))

    bootstrap_production_registry(
        binding_id="immutable-id-123",
        is_default=True,
        persona_id="kayla_v0",
    )
    store_file = store_dir / "registry.json"
    content_before = store_file.read_text(encoding="utf-8")
    mtime_before = store_file.stat().st_mtime_ns

    # Reader open
    reader = open_production_binding_registry_reader()
    _ = reader.list_bindings(environment=RuntimeEnvironment.PRODUCTION)
    _ = reader.default_binding(
        environment=RuntimeEnvironment.PRODUCTION,
        production_root=DEFAULT_PRODUCTION_ROOT,
    )

    # Content and mtime must remain identical (zero mutation)
    content_after = store_file.read_text(encoding="utf-8")
    mtime_after = store_file.stat().st_mtime_ns

    assert content_after == content_before
    assert mtime_after == mtime_before


# ===========================================================================
# Test G: Multi-Production Bindings Enumerate Correctly
# ===========================================================================


def test_g_multi_production_bindings_enumerate_correctly(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """G. Two production bindings enumerate correctly without single-binding bias."""
    store_dir = tmp_path / "multi_prod_registry"
    monkeypatch.setenv(MR_BINDING_REGISTRY_DIR_ENV, str(store_dir))

    admin = open_binding_registry_admin(store_dir=store_dir)
    admin.initialize()

    binding_a = RuntimeBinding(
        persona_id="kayla_v0",
        agent_id="hermes-agent-a",
        runtime_id="runtime-a",
        storage_namespace="production/xiyue",
        environment=RuntimeEnvironment.PRODUCTION,
    )
    binding_b = RuntimeBinding(
        persona_id="kayla_v0",
        agent_id="hermes-agent-b",
        runtime_id="runtime-b",
        storage_namespace="production/xiyue",
        environment=RuntimeEnvironment.PRODUCTION,
    )

    desc_a = admin.register(binding_a, binding_id="binding-a")
    desc_b = admin.register(binding_b, binding_id="binding-b")

    reader = open_production_binding_registry_reader()
    listed = reader.list_bindings(environment=RuntimeEnvironment.PRODUCTION)

    listed_ids = {d.binding_id for d in listed}
    assert listed_ids == {"binding-a", "binding-b"}
    assert desc_a in listed
    assert desc_b in listed


# ===========================================================================
# Test H: OW/Read Consumer Gets Only BindingRegistryReader Surface
# ===========================================================================


def test_h_read_consumer_gets_only_reader_surface(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """H. Read consumer receives strictly BindingRegistryReader surface."""
    store_dir = tmp_path / "reader_surface_registry"
    monkeypatch.setenv(MR_BINDING_REGISTRY_DIR_ENV, str(store_dir))

    bootstrap_production_registry(
        binding_id="surface-test-prod",
        persona_id="kayla_v0",
    )

    reader = open_production_binding_registry_reader()

    assert isinstance(reader, BindingRegistryReader)
    assert callable(getattr(reader, "list_bindings", None))
    assert callable(getattr(reader, "resolve_binding", None))
    assert callable(getattr(reader, "default_binding", None))


# ===========================================================================
# Test I: Writer/Admin Surface Not Exposed by Read Factory
# ===========================================================================


def test_i_writer_admin_surface_not_exposed_by_read_factory(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """I. Writer/admin surface is not exposed on reader returned by read factory."""
    store_dir = tmp_path / "no_writer_surface_registry"
    monkeypatch.setenv(MR_BINDING_REGISTRY_DIR_ENV, str(store_dir))

    bootstrap_production_registry(
        binding_id="security-test-prod",
        persona_id="kayla_v0",
    )

    reader = open_production_binding_registry_reader()

    assert not isinstance(reader, BindingRegistryWriter)
    assert not hasattr(reader, "initialize")
    assert not hasattr(reader, "register")
    assert not hasattr(reader, "set_default")
    assert not hasattr(reader, "clear_default")
    assert not hasattr(reader, "writer")


# ===========================================================================
# Test J: Generic Observation Window Source Contains No Registry Path Logic
# ===========================================================================


def test_j_observation_window_contains_no_registry_path_logic() -> None:
    """J. Generic observation_window source contains no registry path or write logic."""
    ow_src = Path(__file__).resolve().parents[2] / "src" / "observation_window"
    assert ow_src.is_dir(), f"Observation window source directory not found: {ow_src}"

    forbidden_patterns = [
        "MR_BINDING_REGISTRY_DIR",
        "build_binding_registry",
        "open_binding_registry_admin",
        "bootstrap_production_registry",
        ".initialize(",
        ".set_default(",
        ".clear_default(",
    ]

    violations: list[str] = []
    for py_file in ow_src.rglob("*.py"):
        text = py_file.read_text(encoding="utf-8")
        for pattern in forbidden_patterns:
            if pattern in text:
                violations.append(f"{py_file.name}: contains forbidden {pattern!r}")

    assert not violations, "Observation Window violates registry authority boundary:\n" + "\n".join(violations)
