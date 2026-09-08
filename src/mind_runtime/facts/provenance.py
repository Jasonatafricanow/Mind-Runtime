"""Minimal provenance for the factual plane (D3.5)."""

from dataclasses import dataclass
from datetime import datetime

from mind_runtime.contracts import Evidence, Scope


@dataclass(frozen=True)
class ProvenanceEntry:
    """One auditable factual record: source times kept distinct."""

    interaction_id: str
    evidence_id: str
    scope: Scope
    source_ref: str
    occurred_at: datetime
    received_at: datetime


class ProvenanceRecorder:
    """Append-only provenance log; occurred_at vs received_at preserved.

    Idempotent per ``(scope, evidence_id)``: replaying an already-recorded
    event (e.g. after restart or on duplicate delivery) never appends a
    second entry, so the log stays a faithful one-entry-per-event audit
    trail.
    """

    def __init__(self) -> None:
        self._entries: list[ProvenanceEntry] = []
        self._seen: set[tuple[Scope, str]] = set()

    def record(self, evidence: Evidence, *, interaction_id: str) -> None:
        key = (evidence.scope, evidence.id)
        if key in self._seen:
            return
        self._seen.add(key)
        self._entries.append(
            ProvenanceEntry(
                interaction_id=interaction_id,
                evidence_id=evidence.id,
                scope=evidence.scope,
                source_ref=evidence.source_id,
                occurred_at=evidence.occurred_at,
                received_at=evidence.received_at,
            )
        )

    def entries(self, interaction_id: str) -> tuple[ProvenanceEntry, ...]:
        return tuple(entry for entry in self._entries if entry.interaction_id == interaction_id)

    def all(self) -> tuple[ProvenanceEntry, ...]:
        return tuple(self._entries)
