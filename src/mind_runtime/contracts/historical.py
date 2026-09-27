"""Provider-neutral historical context read contracts (MR-2)."""

from dataclasses import dataclass
from datetime import datetime

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


@dataclass(frozen=True, slots=True)
class EarlierPatternSummary:
    """Bounded summary of earlier covered appraisal pattern."""

    occurrence_count: int
    positive_count: int
    negative_count: int
    neutral_count: int
    covered_time_span_days: float
    predominant_valence: str
    first_occurrence_at: datetime | None = None
    last_occurrence_at: datetime | None = None
    is_empty: bool = False


@dataclass(frozen=True, slots=True)
class RecentSegmentSummary:
    """Bounded summary of recent appraisal segment and deviation status."""

    occurrence_count: int
    positive_count: int
    negative_count: int
    neutral_count: int
    predominant_valence: str
    consecutive_valence_streak: int = 0
    streak_valence: str = "neutral"
    has_recent_deviation: bool = False
    deviation_reason: str | None = None
    is_empty: bool = False


@dataclass(frozen=True, slots=True)
class RepairEvidenceSummary:
    """Bounded summary of verbal and behavioral repair evidence."""

    verbal_repair_count: int = 0
    behavioral_repair_count: int = 0
    has_verbal_repair: bool = False
    has_behavioral_repair: bool = False
    repair_assessment: str = "none"  # "none", "verbal_only", "behavioral_supported"
    details: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class AppraisalRevisionTrajectory:
    """Trajectory of appraisal revisions for a single canonical occurrence."""

    occurrence_id: str
    source_occurred_at: datetime
    revisions: tuple[object, ...]
    effective_appraisal: object
    has_reappraisal: bool
    initial_valence: str
    effective_valence: str


@dataclass(frozen=True, slots=True)
class LongitudinalQuery:
    """A bounded query for longitudinal appraisal history."""

    owner_scope: Scope
    relationship_id: str
    as_of: datetime
    max_records: int = 256
    recent_days: int = 7
    recent_since: datetime | None = None
    recent_window_days: int = 7
    min_earlier_occurrences: int = 3
    min_recent_occurrences: int = 1

    def __post_init__(self) -> None:
        require_non_empty(self.relationship_id, "relationship_id")
        if isinstance(self.max_records, bool) or self.max_records <= 0:
            raise ValueError("max_records must be positive")
        if isinstance(self.recent_days, bool) or self.recent_days < 0:
            raise ValueError("recent_days must be non-negative")
        if isinstance(self.recent_window_days, bool) or self.recent_window_days < 0:
            raise ValueError("recent_window_days must be non-negative")
        if isinstance(self.min_earlier_occurrences, bool) or self.min_earlier_occurrences < 0:
            raise ValueError("min_earlier_occurrences must be non-negative")
        if isinstance(self.min_recent_occurrences, bool) or self.min_recent_occurrences < 0:
            raise ValueError("min_recent_occurrences must be non-negative")


@dataclass(frozen=True, slots=True)
class LongitudinalView:
    """A derived, bounded read-time view over longitudinal appraisal history.

    Never stored as canonical state, never self-reinforcing.
    """

    total_record_count: int
    positive_count: int
    negative_count: int = 0
    neutral_count: int = 0
    covered_time_span_days: float = 0.0
    earlier_segment_count: int = 0
    recent_segment_count: int = 0
    earlier_predominant_valence: str = "neutral"
    recent_predominant_valence: str = "neutral"
    exceptions: tuple[object, ...] = ()
    is_empty: bool = False
    distinct_root_count: int = 0
    raw_record_count: int = 0
    earlier_pattern: EarlierPatternSummary | None = None
    recent_segment: RecentSegmentSummary | None = None
    repair_evidence: RepairEvidenceSummary | None = None
    revision_trajectories: tuple[AppraisalRevisionTrajectory, ...] = ()
    unresolved_record_count: int = 0
