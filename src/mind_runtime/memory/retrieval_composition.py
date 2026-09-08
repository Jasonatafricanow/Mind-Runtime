"""Opt-in read composition within an already established Runtime namespace."""

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from mind_runtime.contracts import Observation, Scope, Situation
from mind_runtime.contracts.historical import HistoricalContextBundle
from mind_runtime.emotional_transition.history import NullHistoricalContext
from mind_runtime.memory.history import MemoryHistoricalContextAdapter
from mind_runtime.memory.retrieval import (
    DEFAULT_SURFACE_BUDGET,
    MemoryRetrievalService,
    MemorySurfaceBudget,
    NullRetrievalProvider,
    RetrievalProvider,
)
from mind_runtime.memory.store import CanonicalMemoryStore
from mind_runtime.pipeline.ports import HistoricalContextPort
from mind_runtime.runtime_binding import (
    BindingManifestMismatchError,
    RuntimeBinding,
    StoragePaths,
    resolve_storage_paths,
)


@dataclass(frozen=True)
class _BoundMemoryHistory:
    binding: RuntimeBinding
    paths: StoragePaths
    provider: RetrievalProvider
    budget: MemorySurfaceBudget

    def read(
        self,
        *,
        interaction_id: str,
        context: Situation,
        observations: tuple[Observation, ...],
        scope: Scope,
        clock: datetime,
    ) -> HistoricalContextBundle | None:
        try:
            manifest = json.loads(self.paths.binding_manifest.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise BindingManifestMismatchError(
                "retrieval requires an existing binding manifest"
            ) from exc
        if not isinstance(manifest, dict) or any(
            manifest.get(key) != value for key, value in self.binding.manifest_identity().items()
        ):
            raise BindingManifestMismatchError("retrieval binding manifest mismatch")
        store = CanonicalMemoryStore(self.paths.memory_db, read_only=True)
        try:
            return MemoryHistoricalContextAdapter(
                MemoryRetrievalService(store=store, provider=self.provider),
                budget=self.budget,
            ).read(
                interaction_id=interaction_id,
                context=context,
                observations=observations,
                scope=scope,
                clock=clock,
            )
        finally:
            store.close()


def build_memory_history(
    binding: RuntimeBinding,
    *,
    provider: RetrievalProvider | None = None,
    budget: MemorySurfaceBudget = DEFAULT_SURFACE_BUDGET,
    production_root: Path | str | None = None,
    lab_root: Path | str | None = None,
) -> HistoricalContextPort:
    """No provider means no contribution and no filesystem access."""
    if provider is None or isinstance(provider, NullRetrievalProvider):
        return NullHistoricalContext()
    paths = resolve_storage_paths(binding, production_root=production_root, lab_root=lab_root)
    return _BoundMemoryHistory(binding, paths, provider, budget)
