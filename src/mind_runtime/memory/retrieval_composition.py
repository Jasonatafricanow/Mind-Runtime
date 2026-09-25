"""Opt-in historical-context composition over MR Memory and accepted LCE cognition."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from mind_runtime.contracts import Observation, Scope, Situation
from mind_runtime.contracts.historical import HistoricalContextBundle, HistoricalContextItem
from mind_runtime.emotional_transition.history import NullHistoricalContext
from mind_runtime.integrations.lce import open_lce_read_binding
from mind_runtime.memory.history import MemoryHistoricalContextAdapter
from mind_runtime.memory.product import MemoryProductStore
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


def _query_text(interaction_id: str, observations: tuple[Observation, ...]) -> str:
    text = ""
    for observation in observations:
        if (
            observation.interaction_id != interaction_id
            or observation.type != "factual"
            or observation.key != "user_message.observed"
            or not isinstance(observation.value, Mapping)
        ):
            continue
        value = observation.value.get("text")
        if isinstance(value, str):
            text += ("\n" if text else "") + value[: 4096 - len(text)]
            text = text[:4096]
        if len(text) == 4096:
            break
    return text


def _merge_bundles(
    *,
    interaction_id: str,
    scope: Scope,
    origin_runtime_id: str,
    budget: MemorySurfaceBudget,
    lce: HistoricalContextBundle | None,
    memory: HistoricalContextBundle | None,
) -> HistoricalContextBundle | None:
    if lce is None and memory is None:
        return None

    # Compiled cognition is preferred. Raw Memory fills the remaining bounded
    # budget instead of forcing the model to reconstruct an already accepted
    # longitudinal line again.
    candidates: list[HistoricalContextItem] = []
    for bundle in (lce, memory):
        if bundle is None:
            continue
        candidates.extend(bundle.episodes)
        candidates.extend(bundle.stable_facts)
        candidates.extend(bundle.relationship_events)

    selected: list[HistoricalContextItem] = []
    seen: set[str] = set()
    remaining = budget.max_characters
    for item in candidates:
        if item.item_id in seen or len(item.proposition) > remaining:
            continue
        seen.add(item.item_id)
        selected.append(item)
        remaining -= len(item.proposition)
        if len(selected) >= budget.max_items:
            break
    if not selected:
        return None

    source_refs = tuple(sorted({ref for item in selected for ref in item.source_refs}))
    traces = tuple(
        bundle.provider_trace
        for bundle in (lce, memory)
        if bundle is not None
    )
    return HistoricalContextBundle(
        bundle_id=f"memory+lce-history:{interaction_id}",
        scope=scope,
        origin_runtime_id=origin_runtime_id,
        episodes=tuple(selected),
        stable_facts=(),
        relationship_events=(),
        pattern_summaries=(),
        source_refs=source_refs,
        provider_trace="+".join(traces),
    )


@dataclass(frozen=True)
class _BoundMemoryHistory:
    binding: RuntimeBinding
    paths: StoragePaths
    provider: RetrievalProvider | None
    budget: MemorySurfaceBudget
    lce_enabled: bool
    production_root: Path | str | None
    lab_root: Path | str | None

    def _verify_manifest(self) -> None:
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

    def _memory_bundle(
        self,
        *,
        interaction_id: str,
        context: Situation,
        observations: tuple[Observation, ...],
        scope: Scope,
        clock: datetime,
    ) -> HistoricalContextBundle | None:
        if self.provider is None or isinstance(self.provider, NullRetrievalProvider):
            return None
        store = CanonicalMemoryStore(self.paths.memory_db, read_only=True)
        product = MemoryProductStore(self.paths.memory_db, store, read_only=True)
        try:
            return MemoryHistoricalContextAdapter(
                MemoryRetrievalService(store=store, provider=self.provider),
                budget=self.budget,
                product=product,
            ).read(
                interaction_id=interaction_id,
                context=context,
                observations=observations,
                scope=scope,
                clock=clock,
            )
        finally:
            product.close()
            store.close()

    def _lce_bundle(
        self,
        *,
        interaction_id: str,
        context: Situation,
        observations: tuple[Observation, ...],
        scope: Scope,
    ) -> HistoricalContextBundle | None:
        if not self.lce_enabled:
            return None
        text = _query_text(interaction_id, observations)
        if not text.strip():
            return None
        reader = open_lce_read_binding(
            self.binding,
            scope,
            enabled=True,
            production_root=self.production_root,
            lab_root=self.lab_root,
        )
        if reader is None:
            return None
        with reader:
            views = reader.accepted_understandings(text, limit=self.budget.max_items)
        if not views:
            return None
        items = tuple(
            HistoricalContextItem(
                item_id=f"lce:{view.baseline_id}",
                scope=scope,
                external_id=view.baseline_id,
                kind="lce.accepted_understanding",
                proposition=view.content,
                source_refs=(view.baseline_id, *view.source_refs),
                confidence=None,
                relevance_hint=view.relevance,
            )
            for view in views
        )
        return HistoricalContextBundle(
            bundle_id=f"lce-history:{interaction_id}",
            scope=scope,
            origin_runtime_id=context.origin_runtime_id,
            episodes=items,
            stable_facts=(),
            relationship_events=(),
            pattern_summaries=(),
            source_refs=tuple(sorted({ref for item in items for ref in item.source_refs})),
            provider_trace="lce-accepted-baseline",
        )

    def read(
        self,
        *,
        interaction_id: str,
        context: Situation,
        observations: tuple[Observation, ...],
        scope: Scope,
        clock: datetime,
    ) -> HistoricalContextBundle | None:
        if context.scope != scope or any(
            observation.scope != scope for observation in observations
        ):
            return None
        self._verify_manifest()
        lce = self._lce_bundle(
            interaction_id=interaction_id,
            context=context,
            observations=observations,
            scope=scope,
        )
        memory = self._memory_bundle(
            interaction_id=interaction_id,
            context=context,
            observations=observations,
            scope=scope,
            clock=clock,
        )
        return _merge_bundles(
            interaction_id=interaction_id,
            scope=scope,
            origin_runtime_id=context.origin_runtime_id,
            budget=self.budget,
            lce=lce,
            memory=memory,
        )


def build_memory_history(
    binding: RuntimeBinding,
    *,
    provider: RetrievalProvider | None = None,
    budget: MemorySurfaceBudget = DEFAULT_SURFACE_BUDGET,
    lce_enabled: bool = False,
    production_root: Path | str | None = None,
    lab_root: Path | str | None = None,
) -> HistoricalContextPort:
    """Expose the Memory subsystem's single outward historical-context boundary.

    Accepted compiled cognition is preferred; canonical Memory retrieval fills
    the remaining bounded budget. Thread remains an internal temporary
    projection and is not dumped wholesale into model context.
    """
    if type(lce_enabled) is not bool:
        raise TypeError("lce_enabled must be bool")
    if (provider is None or isinstance(provider, NullRetrievalProvider)) and not lce_enabled:
        return NullHistoricalContext()
    paths = resolve_storage_paths(binding, production_root=production_root, lab_root=lab_root)
    return _BoundMemoryHistory(
        binding,
        paths,
        provider,
        budget,
        lce_enabled,
        production_root,
        lab_root,
    )
