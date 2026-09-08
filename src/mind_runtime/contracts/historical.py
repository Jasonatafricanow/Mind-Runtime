"""Provider-neutral historical context read contracts (MR-2)."""

from dataclasses import dataclass

from mind_runtime.contracts.common import require_non_empty
from mind_runtime.contracts.pattern import PatternMatchSummary, PatternQuery
from mind_runtime.contracts.scope import Scope


@dataclass(frozen=True, slots=True)
class HistoricalContextQuery:
    """A read-only bounded query for historical context."""

    query_id: str
    scope: Scope
    origin_runtime_id: str
    situation_hint: str | None
    query_text: str | None
    pattern_queries: tuple[PatternQuery, ...]
    budget: int

    def __post_init__(self) -> None:
        require_non_empty(self.query_id, "query_id")
        require_non_empty(self.origin_runtime_id, "origin_runtime_id")
        if self.situation_hint is not None:
            require_non_empty(self.situation_hint, "situation_hint")
        if self.query_text is not None:
            require_non_empty(self.query_text, "query_text")
        if isinstance(self.budget, bool) or self.budget < 0:
            raise ValueError("budget must be non-negative")


@dataclass(frozen=True, slots=True)
class HistoricalContextItem:
    """One read-only historical fact from a provider."""

    item_id: str
    scope: Scope
    external_id: str
    kind: str
    proposition: str
    source_refs: tuple[str, ...]
    confidence: float | None
    relevance_hint: float | None

    def __post_init__(self) -> None:
        require_non_empty(self.item_id, "item_id")
        require_non_empty(self.external_id, "external_id")
        require_non_empty(self.kind, "kind")
        require_non_empty(self.proposition, "proposition")
        for ref in self.source_refs:
            require_non_empty(ref, "source_refs entries")
        if self.confidence is not None and not 0 <= self.confidence <= 1:
            raise ValueError("confidence must be in [0, 1]")
        if self.relevance_hint is not None and not 0 <= self.relevance_hint <= 1:
            raise ValueError("relevance_hint must be in [0, 1]")


@dataclass(frozen=True, slots=True)
class HistoricalContextBundle:
    """A bounded, read-only bundle of historical context."""

    bundle_id: str
    scope: Scope
    origin_runtime_id: str
    episodes: tuple[HistoricalContextItem, ...]
    stable_facts: tuple[HistoricalContextItem, ...]
    relationship_events: tuple[HistoricalContextItem, ...]
    pattern_summaries: tuple[PatternMatchSummary, ...]
    source_refs: tuple[str, ...]
    provider_trace: str

    def __post_init__(self) -> None:
        require_non_empty(self.bundle_id, "bundle_id")
        require_non_empty(self.origin_runtime_id, "origin_runtime_id")
        require_non_empty(self.provider_trace, "provider_trace")
        for ref in self.source_refs:
            require_non_empty(ref, "source_refs entries")
