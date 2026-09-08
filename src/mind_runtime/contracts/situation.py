"""Situation contract: an interpretation of the current fact combination."""

from dataclasses import dataclass
from datetime import datetime

from mind_runtime.contracts.common import require_aware_utc, require_non_empty
from mind_runtime.contracts.historical import HistoricalContextBundle
from mind_runtime.contracts.scope import Scope


@dataclass(frozen=True, slots=True)
class Situation:
    """A time-point interpretation of current facts; never a persisted fact."""

    situation_id: str
    scope: Scope
    origin_runtime_id: str
    derived_facts: tuple[tuple[str, str], ...]
    effective_state_ref: str
    observed_at: datetime
    historical_context: HistoricalContextBundle | None
    persona_id: str | None
    relationship_ids: tuple[str, ...]
    evidence_refs: tuple[str, ...]

    def __post_init__(self) -> None:
        require_non_empty(self.situation_id, "situation_id")
        require_non_empty(self.origin_runtime_id, "origin_runtime_id")
        require_non_empty(self.effective_state_ref, "effective_state_ref")
        for key, value in self.derived_facts:
            require_non_empty(key, "derived_fact keys")
            require_non_empty(value, "derived_fact values")
        if self.persona_id is not None:
            require_non_empty(self.persona_id, "persona_id")
        for relationship_id in self.relationship_ids:
            require_non_empty(relationship_id, "relationship_ids entries")
        for ref in self.evidence_refs:
            require_non_empty(ref, "evidence_refs entries")
        require_aware_utc(self.observed_at, "observed_at")
