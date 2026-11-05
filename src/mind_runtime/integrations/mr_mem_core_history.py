"""Current MR-Mem Search consumed through the existing HistoricalContextPort.

The core owns ranking and Line/stretch/raw rendering. MR applies only its final
context budget. Result locators identify derived readout, never raw Evidence.
"""

from __future__ import annotations

import hashlib
from datetime import datetime
from urllib.parse import quote

from mind_runtime.contracts import Observation, Scope, ScopeDomain, Situation
from mind_runtime.contracts.historical import HistoricalContextBundle, HistoricalContextItem
from mind_runtime.integrations.mr_mem_core import MrMemClient
from mind_runtime.memory.retrieval import DEFAULT_SURFACE_BUDGET, MemorySurfaceBudget
from mind_runtime.memory.retrieval_composition import _query_text


class MrMemCoreHistory:
    def __init__(self, client: MrMemClient, *,
                 budget: MemorySurfaceBudget = DEFAULT_SURFACE_BUDGET) -> None:
        self.client, self.budget = client, budget
        origin = hashlib.sha256(client.base_url.rstrip("/").encode()).hexdigest()[:16]
        self.prefix = f"mr-mem:{origin}:{quote(client.user_id, safe='')}:result:"

    def read(self, *, interaction_id: str, context: Situation,
             observations: tuple[Observation, ...], scope: Scope,
             clock: datetime) -> HistoricalContextBundle | None:
        if (scope != Scope(ScopeDomain.USER, user_id=self.client.user_id)
                or context.scope != scope or any(o.scope != scope for o in observations)):
            return None
        text = _query_text(interaction_id, observations)
        if not text.strip() or not self.budget.max_items or not self.budget.max_characters:
            return None
        result = self.client.search(text, top_k=min(self.budget.max_items, 100))
        remaining, seen, selected = self.budget.max_characters, set(), []
        for rank, row in enumerate(result["data"]):
            key, content = row["id"], row["content"]
            if key in seen or not content.strip() or len(content) > remaining:
                continue
            locator = self.prefix + quote(key, safe="")
            selected.append(HistoricalContextItem(
                item_id=self.prefix + f"{rank:03d}:" + quote(key, safe=""),
                scope=scope, external_id=key,
                kind="memory.mr_mem_projection", proposition=content,
                source_refs=(locator,), confidence=None, relevance_hint=None,
            ))
            seen.add(key)
            remaining -= len(content)
            if len(selected) >= self.budget.max_items:
                break
        if not selected:
            return None
        items = tuple(selected)
        return HistoricalContextBundle(
            bundle_id=f"mr-mem-core-history:{interaction_id}", scope=scope,
            origin_runtime_id=context.origin_runtime_id, episodes=items,
            stable_facts=(), relationship_events=(), pattern_summaries=(),
            source_refs=tuple(i.source_refs[0] for i in items),
            provider_trace="mr-mem-core-search:current-projection",
        )
