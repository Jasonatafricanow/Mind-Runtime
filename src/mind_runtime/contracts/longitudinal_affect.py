"""Read-time longitudinal affect contracts.

This module is intentionally read-only. It summarizes accepted subjective
appraisal history without creating facts, Memory records, Slow state, or LCE
cognition.
"""

from dataclasses import dataclass
from datetime import datetime

from mind_runtime.contracts.common import require_aware_utc, require_non_empty
from mind_runtime.contracts.scope import Scope


@dataclass(frozen=True, slots=True)
class LongitudinalAffectRecord:
    """Normalized accepted appraisal history used by the longitudinal reader."""

    record_id: str
    relationship_id: str
    source_occurrence_id: str | None
    source_refs: tuple[str, ...]
    source_occurred_at: datetime
    assessed_at: datetime
    valence: str
    verbal_repair_signal: bool = False
    behavioral_repair_signal: bool = False

    def __post_init__(self) -> None:
        require_non_empty(self.record_id, "record_id")
        require_non_empty(self.relationship_id, "relationship_id")
        if self.source_occurrence_id is not None:
            require_non_empty(self.source_occurrence_id, "source_occurrence_id")
        for ref in self.source_refs:
            require_non_empty(ref, "source_refs entries")
        require_aware_utc(self.source_occurred_at, "source_occurred_at")
        require_aware_utc(self.assessed_at, "assessed_at")
        require_non_empty(self.valence, "valence")


@dataclass(frozen=True, slots=True)
class LongitudinalAffectQuery:
    """Bounded query over one relationship's accepted appraisal history."""

    owner_scope: Scope
    relationship_id: str
    as_of: datetime
    max_occurrences: int = 256
    recent_window_days: int = 7
    recent_since: datetime | None = None
    min_earlier_occurrences: int = 3
    min_recent_occurrences: int = 1

    def __post_init__(self) -> None:
        require_non_empty(self.relationship_id, "relationship_id")
        require_aware_utc(self.as_of, "as_of")
        if self.recent_since is not None:
            require_aware_utc(self.recent_since, "recent_since")
        for field_name in (
            "max_occurrences",
            "recent_window_days",
            "min_earlier_occurrences",
            "min_recent_occurrences",
        ):
            value = getattr(self, field_name)
            if isinstance(value, bool) or not isinstance(value, int):
                raise ValueError(f"{field_name} must be an integer")
        if self.max_occurrences <= 0:
            raise ValueError("max_occurrences must be positive")
        if self.recent_window_days < 0:
            raise ValueError("recent_window_days must be non-negative")
        if self.min_earlier_occurrences < 0:
            raise ValueError("min_earlier_occurrences must be non-negative")
        if self.min_recent_occurrences < 0:
            raise ValueError("min_recent_occurrences must be non-negative")


@dataclass(frozen=True, slots=True)
class EarlierAffectPattern:
    occurrence_count: int
    positive_count: int
    negative_count: int
    neutral_count: int
    covered_time_span_days: float
    predominant_valence: str
    first_occurrence_at: datetime | None = None
    last_occurrence_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class RecentAffectSegment:
    occurrence_count: int
    positive_count: int
    negative_count: int
    neutral_count: int
    predominant_valence: str
    consecutive_valence_streak: int
    streak_valence: str
    has_recent_deviation: bool
    deviation_reason: str | None


@dataclass(frozen=True, slots=True)
class AffectRepairEvidence:
    verbal_repair_count: int = 0
    behavioral_repair_count: int = 0
    has_verbal_repair: bool = False
    has_behavioral_repair: bool = False
    repair_assessment: str = "none"


@dataclass(frozen=True, slots=True)
class AffectRevisionTrajectory:
    occurrence_id: str
    source_occurred_at: datetime
    revisions: tuple[LongitudinalAffectRecord, ...]
    effective_record: LongitudinalAffectRecord
    has_reappraisal: bool
    initial_valence: str
    effective_valence: str


@dataclass(frozen=True, slots=True)
class LongitudinalAffectView:
    """Derived read-time affect structure; never canonical or self-reinforcing."""

    relationship_id: str
    total_occurrence_count: int
    raw_record_count: int
    unresolved_record_count: int
    positive_count: int
    negative_count: int
    neutral_count: int
    covered_time_span_days: float
    earlier_pattern: EarlierAffectPattern
    recent_segment: RecentAffectSegment
    repair_evidence: AffectRepairEvidence
    revision_trajectories: tuple[AffectRevisionTrajectory, ...]
    is_empty: bool = False


@dataclass(frozen=True, slots=True)
class LongitudinalAffectCondition:
    """Bounded provider-visible projection derived from LongitudinalAffectView."""

    text: str
    is_omitted: bool
    omission_reason: str | None
    coverage_summary: str
