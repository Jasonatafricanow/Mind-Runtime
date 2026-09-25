"""Frozen Reality Observation contract (MR-REALITY-OBSERVATION-CONTRACT-01).

Defines the five-value modality vocabulary, typed semantic time, and
effective window representations for evidence-backed reality propositions.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from mind_runtime.contracts.common import require_aware_utc


class ObservationModality(StrEnum):
    """Frozen five-value modality vocabulary (C1 / P0)."""

    ASSERTED = "asserted"
    PLANNED = "planned"
    TENTATIVE = "tentative"
    ESTIMATED = "estimated"
    INFERRED = "inferred"


class SemanticRelation(StrEnum):
    """Temporal relation to the reference instant."""

    CURRENT = "current"
    PAST = "past"
    FUTURE = "future"
    UNRESOLVED = "unresolved"


class SemanticPrecision(StrEnum):
    """Granularity of the stated proposition time."""

    INSTANT = "instant"
    DAY = "day"
    DAYPART = "daypart"
    RANGE = "range"
    UNRESOLVED = "unresolved"


class SemanticDaypart(StrEnum):
    """Frozen canonical daypart vocabulary for propositions."""

    MORNING = "morning"
    AFTERNOON = "afternoon"
    EVENING = "evening"
    NIGHT = "night"


class EffectiveWindowKind(StrEnum):
    """Domain effective window kind.

    Storage may use 'unresolved' as a persistence codec sentinel only;
    the domain enum contains exactly POINT, INTERVAL, and OPEN_INTERVAL.
    """

    POINT = "point"
    INTERVAL = "interval"
    OPEN_INTERVAL = "open_interval"


@dataclass(frozen=True, slots=True)
class SemanticTime:
    """Typed natural-language temporal interpretation."""

    relation: SemanticRelation = SemanticRelation.UNRESOLVED
    precision: SemanticPrecision = SemanticPrecision.UNRESOLVED
    daypart: SemanticDaypart | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.relation, SemanticRelation):
            try:
                object.__setattr__(self, "relation", SemanticRelation(self.relation))
            except ValueError as err:
                raise ValueError(f"invalid semantic relation: {self.relation}") from err

        if not isinstance(self.precision, SemanticPrecision):
            try:
                object.__setattr__(self, "precision", SemanticPrecision(self.precision))
            except ValueError as err:
                raise ValueError(f"invalid semantic precision: {self.precision}") from err

        if self.daypart is not None and not isinstance(self.daypart, SemanticDaypart):
            try:
                object.__setattr__(self, "daypart", SemanticDaypart(self.daypart))
            except ValueError as err:
                raise ValueError(f"invalid semantic daypart: {self.daypart}") from err

        if self.precision is SemanticPrecision.DAYPART:
            if self.daypart is None:
                raise ValueError("DAYPART precision requires daypart to be specified")
        elif self.daypart is not None:
            raise ValueError("non-DAYPART precision cannot have daypart specified")


@dataclass(frozen=True, slots=True)
class EffectiveWindow:
    """Deterministic, aware UTC bounds for proposition validity."""

    kind: EffectiveWindowKind
    start_at: datetime
    end_at: datetime | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.kind, EffectiveWindowKind):
            try:
                object.__setattr__(self, "kind", EffectiveWindowKind(self.kind))
            except ValueError as err:
                raise ValueError(f"invalid effective window kind: {self.kind}") from err

        require_aware_utc(self.start_at, "start_at")
        if self.end_at is not None:
            require_aware_utc(self.end_at, "end_at")

        if self.kind is EffectiveWindowKind.POINT:
            if self.end_at is not None:
                raise ValueError("POINT window cannot have end_at")
        elif self.kind is EffectiveWindowKind.OPEN_INTERVAL:
            if self.end_at is not None:
                raise ValueError("OPEN_INTERVAL window cannot have end_at")
        elif self.kind is EffectiveWindowKind.INTERVAL:
            if self.end_at is None:
                raise ValueError("INTERVAL window requires end_at")
            if self.start_at >= self.end_at:
                raise ValueError("INTERVAL window requires start_at < end_at")


__all__ = [
    "EffectiveWindow",
    "EffectiveWindowKind",
    "ObservationModality",
    "SemanticDaypart",
    "SemanticPrecision",
    "SemanticRelation",
    "SemanticTime",
]
