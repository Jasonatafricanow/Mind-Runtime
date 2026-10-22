"""Read standalone MR-Mem through MR's existing historical-context boundary.

The host owns semantic acceptance and source invalidation. This adapter opens
no writer, runs no compiler and never turns retrieved text into MR evidence.
"""

from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from mind_runtime.contracts import Observation, Scope, Situation
from mind_runtime.contracts.historical import HistoricalContextBundle, HistoricalContextItem
from mind_runtime.memory.retrieval import DEFAULT_SURFACE_BUDGET, MemorySurfaceBudget
from mind_runtime.memory.retrieval_composition import _query_text

if TYPE_CHECKING:
    from mr_mem.integrations.line_read import LineContext


class MrMemHistoricalContext:
    def __init__(
        self, path: Path | str, *, budget: MemorySurfaceBudget = DEFAULT_SURFACE_BUDGET,
        line_root: Path | str | None = None,
    ) -> None:
        self.path = Path(path)
        if not self.path.is_absolute():
            raise ValueError("standalone MR-Mem path must be absolute")
        self.budget = budget
        self.line_root = None if line_root is None else Path(line_root)
        if self.line_root is not None and not self.line_root.is_absolute():
            raise ValueError("standalone MR-Mem Line root must be absolute")

    def read(
        self, *, interaction_id: str, context: Situation,
        observations: tuple[Observation, ...], scope: Scope, clock: datetime,
    ) -> HistoricalContextBundle | None:
        if context.scope != scope or any(o.scope != scope for o in observations):
            return None
        text = _query_text(interaction_id, observations)
        if not text.strip() or not self.budget.max_items or not self.budget.max_characters:
            return None
        # Optional dependency: legacy MR use does not import MR-Mem.
        from mr_mem import MemoryCore
        from mr_mem import Scope as MemScope
        from mr_mem import ScopeDomain as MemDomain
        from mr_mem.memory.product import MemorySurfacePolicy, SurfaceMode
        from mr_mem.memory.providers.bm25 import BM25RetrievalProvider
        from mr_mem.memory.retrieval import MemoryRetrievalQuery, MemoryRetrievalService
        from mr_mem.memory.retrieval import MemorySurfaceBudget as MemBudget

        fields = asdict(scope)
        fields["domain"] = MemDomain(scope.domain.value)
        mem_scope = MemScope(**fields)
        # A fresh snapshot sees new admissions/invalidation on the next turn.
        # Missing/corrupt storage raises: an enabled but broken reader is not empty memory.
        with MemoryCore(self.path, read_only=True) as core:
            policy = MemorySurfacePolicy()
            visible = tuple(
                m for m in core.load_all()
                if m.scope == mem_scope and m.known_at <= clock
                and m.provenance.source_refs
                and policy.evaluate(
                    m, core.products.attention(m.memory_id),
                    mode=SurfaceMode.AUTOMATIC, now=clock,
                ).allowed
            )
            reader = MemoryRetrievalService(
                store=core.canonical, provider=BM25RetrievalProvider(visible),
            )
            results = reader.search(
                MemoryRetrievalQuery(mem_scope, text, self.budget.max_items),
                budget=MemBudget(self.budget.max_items, self.budget.max_characters),
            )
            groups: tuple[LineContext, ...] = ()
            if self.line_root is not None:
                from mr_mem.integrations.line_read import LineContextReader

                visible_ids = {m.memory_id for m in visible}
                groups = LineContextReader(self.line_root).read(
                    scope=mem_scope,
                    ranks={r.memory.memory_id: i for i, r in enumerate(results, 1)},
                    store=core.canonical, knowledge_at=clock, now=clock,
                    budget=MemBudget(self.budget.max_items, self.budget.max_characters),
                    allowed=lambda m: m.memory_id in visible_ids,
                    # This boundary has no host-native timestamp metadata. Do not
                    # label an imported/unknown source time as a known message date.
                    evidence_time=lambda m: None,
                )
            covered = {mid for group in groups for mid in group.memory_ids}
            graph_items = tuple(
                HistoricalContextItem(
                    item_id=f"mr-mem:{group.item_id}", scope=scope,
                    external_id=group.item_id, kind="memory.line",
                    proposition=group.content, source_refs=group.source_keys,
                    confidence=None, relevance_hint=None,
                ) for group in groups
            )
            canonical_items = tuple(
                HistoricalContextItem(
                    item_id=f"mr-mem:{r.memory.memory_id}", scope=scope,
                    external_id=r.memory.memory_id, kind="memory.canonical",
                    proposition=r.memory.content,
                    source_refs=tuple(ref.source_key for ref in r.memory.provenance.source_refs),
                    confidence=None, relevance_hint=None,
                ) for r in results if r.memory.memory_id not in covered
            )
            selected = []
            remaining = self.budget.max_characters
            for item in (*graph_items, *canonical_items):
                if len(item.proposition) > remaining:
                    continue
                selected.append(item)
                remaining -= len(item.proposition)
                if len(selected) >= self.budget.max_items:
                    break
            items = tuple(selected)
        if not items:
            return None
        return HistoricalContextBundle(
            bundle_id=f"mr-mem-history:{interaction_id}", scope=scope,
            origin_runtime_id=context.origin_runtime_id, episodes=items,
            stable_facts=(), relationship_events=(), pattern_summaries=(),
            source_refs=tuple(sorted({ref for item in items for ref in item.source_refs})),
            provider_trace=("mr-mem-line-resolution" if groups else "mr-mem-canonical-resolution"),
        )
