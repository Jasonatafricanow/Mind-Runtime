"""Immutable semantic observation contract."""

from dataclasses import dataclass
from datetime import datetime

from mind_runtime.contracts.common import (
    SyncFields,
    freeze_refs,
    freeze_value,
    require_aware_utc,
    require_non_empty,
    validate_sync_fields,
)
from mind_runtime.contracts.reality import (
    EffectiveWindow,
    ObservationModality,
    SemanticPrecision,
    SemanticRelation,
    SemanticTime,
)
from mind_runtime.contracts.scope import Scope

_DEFAULT_SEMANTIC_TIME = SemanticTime(
    relation=SemanticRelation.UNRESOLVED,
    precision=SemanticPrecision.UNRESOLVED,
    daypart=None,
)


@dataclass(frozen=True, slots=True)
class Observation:
    """An immutable evidence-backed interpretation that can be synchronized."""

    id: str
    interaction_id: str
    scope: Scope
    type: str
    key: str
    value: object
    confidence: float
    observed_at: datetime
    evidence_refs: tuple[str, ...]
    origin_runtime_id: str
    sync: SyncFields
    modality: ObservationModality = ObservationModality.ASSERTED
    semantic_time: SemanticTime = _DEFAULT_SEMANTIC_TIME
    effective_window: EffectiveWindow | None = None

    def __post_init__(self) -> None:
        for field_name in (
            "id",
            "interaction_id",
            "origin_runtime_id",
            "type",
            "key",
        ):
            require_non_empty(getattr(self, field_name), field_name)
        if (
            isinstance(self.confidence, bool)
            or not isinstance(self.confidence, (int, float))
            or not 0 <= self.confidence <= 1
        ):
            raise ValueError("confidence must be in [0, 1]")
        require_aware_utc(self.observed_at, "observed_at")
        object.__setattr__(self, "value", freeze_value(self.value, "value"))
        object.__setattr__(self, "evidence_refs", freeze_refs(self.evidence_refs, "evidence_refs"))
        validate_sync_fields(
            self.sync,
            scope=self.scope,
            origin_runtime_id=self.origin_runtime_id,
            object_id=self.id,
        )

        if not isinstance(self.modality, ObservationModality):
            try:
                object.__setattr__(self, "modality", ObservationModality(self.modality))
            except ValueError as err:
                raise ValueError(f"invalid observation modality: {self.modality}") from err

        if not isinstance(self.semantic_time, SemanticTime):
            raise ValueError("semantic_time must be a SemanticTime instance")

        if self.effective_window is not None:
            if not isinstance(self.effective_window, EffectiveWindow):
                raise ValueError("effective_window must be an EffectiveWindow instance or None")
            if (
                self.semantic_time.relation is SemanticRelation.UNRESOLVED
                or self.semantic_time.precision is SemanticPrecision.UNRESOLVED
            ):
                raise ValueError(
                    "UNRESOLVED temporal semantics cannot have absolute effective window bounds"
                )

    def sync_fields(self) -> SyncFields:
        """Return the observation synchronization identity."""

        return self.sync
