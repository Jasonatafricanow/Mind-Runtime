"""Provider-neutral, bounded, read-only historical context assembly."""

from collections.abc import Mapping
from dataclasses import replace
from datetime import datetime, timedelta
from typing import Any, Protocol, runtime_checkable

from mind_runtime.contracts import (
    HistoricalContextBundle,
    HistoricalContextItem,
    HistoricalContextQuery,
    LongitudinalQuery,
    LongitudinalView,
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


def derive_longitudinal_view(
    records: tuple[object, ...] | list[object],
    query: LongitudinalQuery,
    now: datetime,
) -> LongitudinalView:
    """Derive a bounded, read-time longitudinal view over accepted appraisals.

    Read-only derivation: never mutates, reinforces, or writes back to memory.
    """
    matched: list[Any] = []
    for r in records:
        rel_id = (
            getattr(getattr(r, "resolved_relationship_scope", None), "relationship_id", None)
            or getattr(getattr(r, "resolved_relationship_scope", None), "user_id", None)
            or getattr(getattr(r, "source_scope", None), "relationship_id", None)
            or getattr(getattr(r, "source_scope", None), "user_id", None)
        )
        if rel_id == query.relationship_id:
            matched.append(r)

    if not matched:
        return LongitudinalView(
            total_record_count=0,
            positive_count=0,
            negative_count=0,
            neutral_count=0,
            covered_time_span_days=0.0,
            earlier_segment_count=0,
            recent_segment_count=0,
            earlier_predominant_valence="neutral",
            recent_predominant_valence="neutral",
            exceptions=(),
            is_empty=True,
            distinct_root_count=0,
            raw_record_count=0,
        )

    raw_record_count = len(matched)

    # Deduplicate by root occurrence identity to ensure:
    # 1) Same-root re-summary / revision does not increase occurrence count (P1).
    # 2) Old valid reference replay does not create a new occurrence (P2).
    # Root occurrence identity is taken from source_refs[0] if present, else source_occurrence_id.
    grouped_by_root: dict[str, list[Any]] = {}
    for r in matched:
        root_key = ""
        refs = getattr(r, "source_refs", None)
        if refs and len(refs) > 0 and refs[0]:
            root_key = str(refs[0])
        elif getattr(r, "source_occurrence_id", None):
            root_key = str(r.source_occurrence_id)
        else:
            root_key = str(
                getattr(r, "appraisal_id", None)
                or getattr(r, "candidate_id", None)
                or getattr(r, "acceptance_id", None)
                or id(r)
            )
        grouped_by_root.setdefault(root_key, []).append(r)

    # For each root group, select the latest revision by (assessed_at, source_occurred_at, acceptance_id)
    deduped: list[Any] = []
    for group in grouped_by_root.values():
        latest_r = max(
            group,
            key=lambda rec: (
                getattr(rec, "assessed_at", now),
                getattr(rec, "source_occurred_at", now),
                getattr(rec, "acceptance_id", ""),
            ),
        )
        deduped.append(latest_r)

    deduped.sort(key=lambda r: getattr(r, "source_occurred_at", now))
    if len(deduped) > query.max_records:
        deduped = deduped[-query.max_records:]

    total_count = len(deduped)
    distinct_root_count = len(deduped)
    pos_count = sum(1 for r in deduped if getattr(r, "valence", "") == "positive")
    neg_count = sum(1 for r in deduped if getattr(r, "valence", "") == "negative")
    neu_count = sum(1 for r in deduped if getattr(r, "valence", "") not in ("positive", "negative"))

    earliest = getattr(deduped[0], "source_occurred_at", now)
    latest = getattr(deduped[-1], "source_occurred_at", now)
    time_span_days = max(0.0, (latest - earliest).total_seconds() / 86400.0)

    recent_cutoff = now - timedelta(days=query.recent_days)
    earlier = [r for r in deduped if getattr(r, "source_occurred_at", now) <= recent_cutoff]
    recent = [r for r in deduped if getattr(r, "source_occurred_at", now) > recent_cutoff]

    def _predominant_valence(recs: list[Any]) -> str:
        if not recs:
            return "neutral"
        counts = {"positive": 0, "negative": 0, "neutral": 0}
        for r in recs:
            v = getattr(r, "valence", "neutral")
            if v in counts:
                counts[v] += 1
            else:
                counts["neutral"] += 1
        return max(
            counts.keys(),
            key=lambda k: (counts[k], 1 if k == "positive" else (0 if k == "neutral" else -1)),
        )

    earlier_predominant = _predominant_valence(earlier) if earlier else _predominant_valence(deduped)
    recent_predominant = _predominant_valence(recent) if recent else earlier_predominant

    exceptions = tuple(r for r in recent if getattr(r, "valence", "") != earlier_predominant)

    return LongitudinalView(
        total_record_count=total_count,
        positive_count=pos_count,
        negative_count=neg_count,
        neutral_count=neu_count,
        covered_time_span_days=time_span_days,
        earlier_segment_count=len(earlier),
        recent_segment_count=len(recent),
        earlier_predominant_valence=earlier_predominant,
        recent_predominant_valence=recent_predominant,
        exceptions=exceptions,
        is_empty=False,
        distinct_root_count=distinct_root_count,
        raw_record_count=raw_record_count,
    )

