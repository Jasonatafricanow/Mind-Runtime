"""Upstream Production Binding Registry Composition & Administration (W2-C.5).

Normative authority:
- TICKET: MR-BINDING-REGISTRY-PRODUCTION-SEAM-V1
- ADR-0021 (Multi-Binding Registry Authority)
- ADR-0020 (Runtime Identity Binding & Storage Isolation)
- docs/MR_BINDING_REGISTRY_PRODUCTION_SEAM_V1.md

This module owns:
1. Production registry location authority and configuration resolution.
2. Read-only production reader factory for consumers (Observation Window).
3. Upstream administrative writer factory.
4. Explicit administrative bootstrap workflow for first production registration.

Non-negotiable boundaries:
- Observation Window must NEVER choose, calculate, or interpret registry store paths.
- Normal runtime/OW startup must NEVER auto-initialize, repair, or remint bindings.
- Reader factory fails closed (REGISTRY_UNINITIALIZED / REGISTRY_CORRUPT) with zero writes.
- Writer/admin surface is NEVER exposed to read-only consumers.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

from mind_runtime.binding_registry import (
    BindingDescriptor,
    BindingRegistryError,
    BindingRegistryReader,
    BindingRegistryWriter,
    RegistryFailureCode,
    build_binding_registry,
)
from mind_runtime.runtime_binding import (
    RuntimeBinding,
    RuntimeEnvironment,
    discover_production_binding,
)

__all__ = [
    "MR_BINDING_REGISTRY_DIR_ENV",
    "DEFAULT_PRODUCTION_REGISTRY_ROOT",
    "DEFAULT_LAB_REGISTRY_ROOT",
    "BindingRegistryLocationProvider",
    "production_registry_location",
    "lab_registry_location",
    "open_production_binding_registry_reader",
    "open_binding_registry_admin",
    "bootstrap_production_registry",
]

MR_BINDING_REGISTRY_DIR_ENV = "MR_BINDING_REGISTRY_DIR"

# Global registry store roots — above individual binding namespaces
DEFAULT_PRODUCTION_REGISTRY_ROOT = Path.home() / ".mind-runtime" / "registry"
DEFAULT_LAB_REGISTRY_ROOT = Path.home() / ".mind-runtime" / "lab" / "registry"

_BINDING_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")


# ---------------------------------------------------------------------------
# Location Authority
# ---------------------------------------------------------------------------


def production_registry_location() -> Path:
    """Resolve the authoritative production registry store location.

    Precedence:
      1. Upstream MR_BINDING_REGISTRY_DIR environment variable
      2. Upstream default: ~/.mind-runtime/registry
    """
    env_val = os.environ.get(MR_BINDING_REGISTRY_DIR_ENV)
    if env_val and env_val.strip():
        return Path(env_val.strip())
    return DEFAULT_PRODUCTION_REGISTRY_ROOT


def lab_registry_location(name: str | None = None) -> Path:
    """Resolve the authoritative LAB registry store location."""
    env_val = os.environ.get("MR_LAB_BINDING_REGISTRY_DIR")
    base = Path(env_val.strip()) if env_val and env_val.strip() else DEFAULT_LAB_REGISTRY_ROOT
    if name and name.strip():
        return base / name.strip()
    return base


class BindingRegistryLocationProvider:
    """Authoritative location provider for Mind Runtime binding registries."""

    @staticmethod
    def production_location() -> Path:
        return production_registry_location()

    @staticmethod
    def lab_location(name: str | None = None) -> Path:
        return lab_registry_location(name=name)


# ---------------------------------------------------------------------------
# Production Read Factory
# ---------------------------------------------------------------------------


def open_production_binding_registry_reader(
    registry_dir: Path | str | None = None,
) -> BindingRegistryReader:
    """Open the upstream production BindingRegistry in read-only mode.

    Fails closed immediately if the store is absent (REGISTRY_UNINITIALIZED)
    or corrupt (REGISTRY_CORRUPT).

    Guarantees:
      - zero writes to disk
      - zero automatic initializations
      - zero repairs or re-mints
      - returns strictly the BindingRegistryReader surface (no writer methods)
    """
    if registry_dir is None:
        registry_dir = production_registry_location()

    registry = build_binding_registry(registry_dir)

    # Eager fail-closed check: verify store exists and is valid without mutating anything
    registry._load_store()

    return registry.reader


# ---------------------------------------------------------------------------
# Admin / Writer Factory
# ---------------------------------------------------------------------------


def open_binding_registry_admin(
    store_dir: Path | str | None = None,
) -> BindingRegistryWriter:
    """Open the upstream BindingRegistry writer / administrative port.

    This is an upstream-only administrative seam and must NEVER be exposed
    to Observation Window or normal read-only runtime loops.
    """
    if store_dir is None:
        store_dir = production_registry_location()

    registry = build_binding_registry(store_dir)
    return registry.writer


# ---------------------------------------------------------------------------
# First Production Bootstrap
# ---------------------------------------------------------------------------


def bootstrap_production_registry(
    *,
    binding_id: str,
    is_default: bool = True,
    persona_id: str = "kayla_v0",
    binding: RuntimeBinding | None = None,
    binding_ref: str | Path | None = None,
    registry_dir: Path | str | None = None,
) -> BindingDescriptor:
    """Explicit administrative workflow for first production bootstrap.

    Sequence:
      1. validate explicit administrative binding_id
      2. open admin writer
      3. initialize() store (fails if already initialized)
      4. obtain authoritative production RuntimeBinding
      5. register(binding, binding_id)
      6. if is_default: set_default(binding_id)
      7. return BindingDescriptor

    Forbidden:
      - automatic invocation during normal gateway/OW boot
      - deriving binding_id from persona_id, agent_id, runtime_id, etc.
    """
    if not isinstance(binding_id, str) or not binding_id.strip():
        raise BindingRegistryError(
            RegistryFailureCode.REGISTRY_CORRUPT,
            "explicit binding_id must be a non-empty string",
        )
    if not _BINDING_ID_RE.match(binding_id):
        raise BindingRegistryError(
            RegistryFailureCode.REGISTRY_CORRUPT,
            f"explicit binding_id must match ^[a-z0-9][a-z0-9-]{{0,63}}$, got {binding_id!r}",
        )

    if registry_dir is None:
        registry_dir = production_registry_location()

    admin = open_binding_registry_admin(store_dir=registry_dir)
    admin.initialize()

    if binding is None:
        binding = discover_production_binding(
            persona_id=persona_id,
            binding_ref=binding_ref,
        )

    if binding.environment is not RuntimeEnvironment.PRODUCTION:
        raise BindingRegistryError(
            RegistryFailureCode.ADMISSION_DENIED,
            f"bootstrap_production_registry requires a PRODUCTION binding, got {binding.environment.value!r}",
        )

    descriptor = admin.register(binding, binding_id=binding_id)
    if is_default:
        admin.set_default(binding_id)

    return descriptor
