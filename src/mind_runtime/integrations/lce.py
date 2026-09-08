"""One-way canonical Memory read binding to frozen LCE Core V0 (ADR-0026)."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import TYPE_CHECKING

from mind_runtime.contracts import Scope
from mind_runtime.memory.contracts import MemoryLifecycle
from mind_runtime.memory.store import CanonicalMemoryStore, scope_json
from mind_runtime.runtime_binding import (
    BindingManifestMismatchError,
    RuntimeBinding,
    StoragePaths,
    resolve_storage_paths,
)

if TYPE_CHECKING:
    from lce.contracts.consolidation import SemanticConsolidatorPort
    from lce.contracts.external_memory import MemoryItemView
    from lce.core.engine import LceCore
    from lce.store.sqlite_store import SqliteBaselineStore

MAX_SELECTED_MEMORIES = 100


class MemorySelectionError(ValueError):
    """The entire selected set is unavailable or unauthorized; no partial views."""


class LceIntegrationUnavailable(RuntimeError):
    """The explicitly enabled optional LCE dependency is unavailable."""


def _verify_binding(binding: RuntimeBinding, paths: StoragePaths) -> None:
    try:
        manifest = json.loads(paths.binding_manifest.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise BindingManifestMismatchError("LCE requires an existing Runtime manifest") from exc
    if not isinstance(manifest, dict) or any(
        manifest.get(key) != value for key, value in binding.manifest_identity().items()
    ):
        raise BindingManifestMismatchError("LCE Runtime manifest mismatch")


@dataclass(frozen=True, init=False)
class MrMemorySubstrateAdapter:
    """Composition-authorized Scope, resolved only against its bound Runtime.

    Scope authorization is supplied by the trusted composition owner, never
    inferred from a selected ID or provider. Connections are read-only and
    short-lived so reconstructed processes do not depend on cached Memory.
    """

    binding: RuntimeBinding
    scope: Scope
    _paths: StoragePaths

    def __init__(
        self,
        binding: RuntimeBinding,
        scope: Scope,
        *,
        production_root: Path | str | None = None,
        lab_root: Path | str | None = None,
    ) -> None:
        if not isinstance(scope, Scope):
            raise TypeError("scope must be a structured Scope")
        paths = resolve_storage_paths(binding, production_root=production_root, lab_root=lab_root)
        object.__setattr__(self, "binding", binding)
        object.__setattr__(self, "scope", scope)
        object.__setattr__(self, "_paths", paths)

    def get_by_ids(self, memory_ids: tuple[str, ...]) -> tuple[MemoryItemView, ...]:
        if not isinstance(memory_ids, tuple) or not 1 <= len(memory_ids) <= MAX_SELECTED_MEMORIES:
            raise MemorySelectionError("expected a tuple of 1 to 100 stable Memory IDs")
        if any(not isinstance(mid, str) or not mid.strip() for mid in memory_ids):
            raise MemorySelectionError("each Memory ID must be a non-empty string")
        if len(set(memory_ids)) != len(memory_ids):
            raise MemorySelectionError("duplicate Memory IDs are not permitted")
        _verify_binding(self.binding, self._paths)
        store = CanonicalMemoryStore(self._paths.memory_db, read_only=True)
        try:
            memories = tuple(store.get(mid) for mid in memory_ids)
        finally:
            store.close()
        if any(
            m is None or m.scope != self.scope or m.lifecycle is not MemoryLifecycle.ACTIVE
            for m in memories
        ):
            raise MemorySelectionError("selected Memory set contains unavailable or ineligible IDs")
        try:
            from lce.contracts.external_memory import MemoryItemView
        except ImportError as exc:
            raise LceIntegrationUnavailable("install the frozen optional lce-core package") from exc
        return tuple(
            MemoryItemView(m.memory_id, m.content, m.provenance.evidence_refs, MappingProxyType({}))
            for m in memories
            if m is not None
        )


@dataclass(frozen=True)
class LceBindingSession:
    """Owns only the LCE connection. Core retains its frozen public API."""

    core: LceCore
    _store: SqliteBaselineStore

    @property
    def db_path(self) -> Path:
        return self._store.db_path

    def close(self) -> None:
        self._store.close()

    def __enter__(self) -> LceBindingSession:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()


def open_lce_binding(
    binding: RuntimeBinding,
    scope: Scope,
    *,
    enabled: bool = False,
    consolidator: SemanticConsolidatorPort | None = None,
    production_root: Path | str | None = None,
    lab_root: Path | str | None = None,
) -> LceBindingSession | None:
    """Default OFF, including filesystem access and optional dependency imports."""
    if type(enabled) is not bool:
        raise TypeError("enabled must be bool")
    if not enabled:
        return None
    if consolidator is None:
        raise ValueError("enabled LCE binding requires an explicitly injected consolidator")
    adapter = MrMemorySubstrateAdapter(
        binding,
        scope,
        production_root=production_root,
        lab_root=lab_root,
    )
    _verify_binding(binding, adapter._paths)
    # Prove canonical storage already exists before creating any LCE persistence.
    CanonicalMemoryStore(adapter._paths.memory_db, read_only=True).close()
    try:
        from lce.core.engine import LceCore
        from lce.store.sqlite_store import SqliteBaselineStore
    except ImportError as exc:
        raise LceIntegrationUnavailable("install the frozen optional lce-core package") from exc
    scope_address = hashlib.sha256(scope_json(scope).encode("utf-8")).hexdigest()
    store = SqliteBaselineStore(adapter._paths.lce_root / scope_address)
    try:
        core = LceCore(memory_substrate=adapter, baseline_store=store, consolidator=consolidator)
        return LceBindingSession(core, store)
    except BaseException:
        store.close()
        raise
