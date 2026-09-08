"""Canonical Memory projection onto the existing HistoricalContextPort."""

from collections.abc import Mapping
from datetime import datetime

from mind_runtime.contracts import Observation, Scope, Situation
from mind_runtime.contracts.historical import HistoricalContextBundle, HistoricalContextItem
from mind_runtime.memory.retrieval import (
    DEFAULT_SURFACE_BUDGET,
    MemoryRetrievalQuery,
    MemoryRetrievalService,
    MemorySurfaceBudget,
)


class MemoryHistoricalContextAdapter:
    def __init__(
        self,
        reader: MemoryRetrievalService,
        *,
        budget: MemorySurfaceBudget = DEFAULT_SURFACE_BUDGET,
    ) -> None:
        self._reader = reader
        self._budget = budget

    def read(
        self,
        *,
        interaction_id: str,
        context: Situation,
        observations: tuple[Observation, ...],
        scope: Scope,
        clock: datetime,
    ) -> HistoricalContextBundle | None:
        if context.scope != scope or any(o.scope != scope for o in observations):
            return None
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
        if not text.strip():
            return None
        results = self._reader.search(
            MemoryRetrievalQuery(scope, text, self._budget.max_items),
            budget=self._budget,
        )
        current_ids = {o.id for o in observations}
        current_refs = {ref for o in observations for ref in o.evidence_refs}
        current_refs.update(context.evidence_refs)
        items = []
        for result in results:
            memory = result.memory
            if memory.provenance.observation_id in current_ids or current_refs.intersection(
                memory.provenance.evidence_refs
            ):
                continue
            items.append(
                HistoricalContextItem(
                    item_id=f"memory:{memory.memory_id}",
                    scope=memory.scope,
                    external_id=memory.memory_id,
                    kind="memory.canonical",
                    proposition=memory.content,
                    source_refs=memory.provenance.evidence_refs,
                    confidence=None,
                    relevance_hint=None,
                )
            )
        if not items:
            return None
        return HistoricalContextBundle(
            bundle_id=f"memory-history:{interaction_id}",
            scope=scope,
            origin_runtime_id=context.origin_runtime_id,
            episodes=tuple(items),
            stable_facts=(),
            relationship_events=(),
            pattern_summaries=(),
            source_refs=tuple(sorted({ref for item in items for ref in item.source_refs})),
            provider_trace="canonical-memory-resolution",
        )
