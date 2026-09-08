"""Pattern query and match summary contracts (DECISION-030)."""

from dataclasses import dataclass
from datetime import datetime

from mind_runtime.contracts.common import require_aware_utc, require_non_empty
from mind_runtime.contracts.scope import Scope


@dataclass(frozen=True, slots=True)
class PatternQuery:
    """A provider-side pattern query; providers only return historical facts."""

    query_id: str
    scope: Scope
    origin_runtime_id: str
    signature: str
    time_window: str
    filters: tuple[tuple[str, str], ...]

    def __post_init__(self) -> None:
        require_non_empty(self.query_id, "query_id")
        require_non_empty(self.origin_runtime_id, "origin_runtime_id")
        require_non_empty(self.signature, "signature")
        require_non_empty(self.time_window, "time_window")
        for key, value in self.filters:
            require_non_empty(key, "filter keys")
            require_non_empty(value, "filter values")


@dataclass(frozen=True, slots=True)
class PatternMatchSummary:
    """Facts-only summary of pattern matches; no recurrence business rule."""

    summary_id: str
    scope: Scope
    origin_runtime_id: str
    match_count: int
    first_seen_at: datetime | None
    last_seen_at: datetime | None
    matched_refs: tuple[str, ...]
    confidence: float

    def __post_init__(self) -> None:
        require_non_empty(self.summary_id, "summary_id")
        require_non_empty(self.origin_runtime_id, "origin_runtime_id")
        if isinstance(self.match_count, bool) or self.match_count < 0:
            raise ValueError("match_count must be non-negative")
        if isinstance(self.confidence, bool) or not 0 <= self.confidence <= 1:
            raise ValueError("confidence must be in [0, 1]")
        for ref in self.matched_refs:
            require_non_empty(ref, "matched_refs entries")
        if self.first_seen_at is not None:
            require_aware_utc(self.first_seen_at, "first_seen_at")
        if self.last_seen_at is not None:
            require_aware_utc(self.last_seen_at, "last_seen_at")
