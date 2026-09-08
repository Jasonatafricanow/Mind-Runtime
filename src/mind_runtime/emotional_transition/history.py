"""Provider-neutral, bounded, read-only historical context assembly."""

from collections.abc import Mapping
from dataclasses import replace
from datetime import datetime
from typing import Protocol, runtime_checkable

from mind_runtime.contracts import (
    HistoricalContextBundle,
    HistoricalContextItem,
    HistoricalContextQuery,
    Observation,
    PatternMatchSummary,
    PatternQuery,
    Scope,
    ScopeDomain,
    Situation,
)


class HistoryProviderUnavailable(RuntimeError):
    """A declared availability failure; current-turn logic may continue."""


@runtime_checkable
class HistoricalContextProvider(Protocol):
    """Query-only provider surface; no touch/reinforce/write operations."""

    def query(self, query: HistoricalContextQuery) -> HistoricalContextBundle:
        """Return immutable historical facts for one bounded query."""
        ...


class NullHistoricalContext:
    """Deterministic no-history path."""

    def read(
        self,
        *,
        interaction_id: str,
        context: Situation,
        observations: tuple[Observation, ...],
        scope: Scope,
        clock: datetime,
    ) -> HistoricalContextBundle | None:
        del interaction_id, context, observations, scope, clock
        return None


class BoundedHistoricalContextAdapter:
    """Validate, deduplicate, and clip facts returned by a query-only provider."""

    def __init__(self, *, provider: HistoricalContextProvider, budget: int) -> None:
        if isinstance(budget, bool) or budget < 0:
            raise ValueError("budget must be non-negative")
        self._provider = provider
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
        del clock
        if context.scope != scope:
            raise ValueError("context scope must match history read scope")
        if any(observation.scope != scope for observation in observations):
            raise ValueError("observation scope must match history read scope")
        query = HistoricalContextQuery(
            query_id=f"history-query-{interaction_id}",
            scope=scope,
            origin_runtime_id=context.origin_runtime_id,
            situation_hint=context.situation_id,
            query_text=None,
            pattern_queries=tuple(
                PatternQuery(
                    query_id=f"pattern-{interaction_id}-{index}",
                    scope=scope,
                    origin_runtime_id=context.origin_runtime_id,
                    signature=signature,
                    time_window="all",
                    filters=(),
                )
                for index, signature in enumerate(self._typed_signatures(observations), start=1)
            ),
            budget=self._budget,
        )
        try:
            bundle = self._provider.query(query)
        except HistoryProviderUnavailable:
            return None
        return self._bounded_copy(bundle, scope=scope)

    @staticmethod
    def _typed_signatures(observations: tuple[Observation, ...]) -> tuple[str, ...]:
        signatures: set[str] = set()
        for observation in observations:
            if observation.key != "typed_event.observed" or not isinstance(
                observation.value, Mapping
            ):
                continue
            kind = observation.value.get("kind")
            if isinstance(kind, str) and kind.strip():
                signatures.add(kind)
        return tuple(sorted(signatures))

    def _bounded_copy(
        self, bundle: HistoricalContextBundle, *, scope: Scope
    ) -> HistoricalContextBundle:
        if bundle.scope != scope:
            raise ValueError("historical bundle scope must match read scope")
        categorized: tuple[tuple[str, HistoricalContextItem], ...] = tuple(
            (category, item)
            for category, items in (
                ("episodes", bundle.episodes),
                ("stable_facts", bundle.stable_facts),
                ("relationship_events", bundle.relationship_events),
            )
            for item in items
        )
        for _category, item in categorized:
            if item.scope != scope:
                raise ValueError("historical item scope must match read scope")
        for summary in bundle.pattern_summaries:
            if summary.scope != scope:
                raise ValueError("pattern summary scope must match read scope")
        self._validate_relationship_provenance(bundle, scope=scope)

        selected: list[tuple[str, HistoricalContextItem]] = []
        seen_items: set[str] = set()
        for category, item in sorted(categorized, key=lambda entry: entry[1].item_id):
            if item.item_id in seen_items:
                continue
            seen_items.add(item.item_id)
            if len(selected) >= self._budget:
                continue
            selected.append((category, item))

        remaining = self._budget - len(selected)
        selected_relationship_ids = {
            item.item_id for category, item in selected if category == "relationship_events"
        }
        selected_summaries: list[PatternMatchSummary] = []
        seen_summaries: set[str] = set()
        for summary in sorted(bundle.pattern_summaries, key=lambda entry: entry.summary_id):
            if summary.summary_id in seen_summaries:
                continue
            seen_summaries.add(summary.summary_id)
            if (
                scope.domain is ScopeDomain.RELATIONSHIP
                and not set(summary.matched_refs) <= selected_relationship_ids
            ):
                continue
            if len(selected_summaries) >= remaining:
                continue
            selected_summaries.append(
                replace(summary, matched_refs=tuple(dict.fromkeys(summary.matched_refs)))
            )

        return HistoricalContextBundle(
            bundle_id=bundle.bundle_id,
            scope=bundle.scope,
            origin_runtime_id=bundle.origin_runtime_id,
            episodes=tuple(item for category, item in selected if category == "episodes"),
            stable_facts=tuple(item for category, item in selected if category == "stable_facts"),
            relationship_events=tuple(
                item for category, item in selected if category == "relationship_events"
            ),
            pattern_summaries=tuple(selected_summaries),
            source_refs=tuple(sorted(set(bundle.source_refs))),
            provider_trace=bundle.provider_trace,
        )

    @staticmethod
    def _validate_relationship_provenance(
        bundle: HistoricalContextBundle,
        *,
        scope: Scope,
    ) -> None:
        if bundle.relationship_events and scope.domain is not ScopeDomain.RELATIONSHIP:
            raise ValueError("relationship_events require relationship scope")
        if scope.domain is not ScopeDomain.RELATIONSHIP:
            return
        relationship_ids = {item.item_id for item in bundle.relationship_events}
        for item in bundle.relationship_events:
            if not item.source_refs:
                raise ValueError("private relationship items require source refs")
        for summary in bundle.pattern_summaries:
            if not summary.matched_refs:
                raise ValueError("relationship summaries require matched refs")
            if not set(summary.matched_refs) <= relationship_ids:
                raise ValueError(
                    "relationship summary refs must resolve to selected relationship items"
                )
