"""Legacy D11 DTOs — read-only migration boundary.

These are AUDIT / READ-ONLY data transfer objects produced by
LegacyD11Reader. They are deliberately NOT canonical MR contracts
(Evidence / Observation / RuntimeState) because:

  * legacy rows carry no real MR Authority / Scope / SyncFields;
  * forging those on legacy rows would invent false authority.

Per migration dispatch (MIG-1 §14) the semantic split is:

  LegacyEventRecord      — one shadow_events row (real message evidence)
  LegacyAffectAnnotation — one shadow_affect row (old affective label)
  LegacyStateSnapshot    — one shadow_states row (old state snapshot)
  LegacySourceRef        — stable provenance identity for a legacy row

These DTOs are immutable (frozen dataclasses). They are produced only
by the read-only reader and never written back to any legacy DB.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


def _parse_ts(value: str | None) -> datetime | None:
    """Parse an ISO-8601 legacy timestamp to aware UTC (or None)."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


@dataclass(frozen=True, slots=True)
class LegacySourceRef:
    """Stable provenance identity for one legacy row.

    Follows the dispatch idempotency-key shape:
        d11:<db>:<table>:<legacy_primary_key>
    """

    db: str  # e.g. "shadow.db"
    table: str  # e.g. "shadow_events"
    legacy_pk: int  # content_id (canonical cross-db join key)

    @property
    def idempotency_key(self) -> str:
        return f"d11:{self.db}:{self.table}:{self.legacy_pk}"


@dataclass(frozen=True, slots=True)
class LegacyEventRecord:
    """One shadow_events row — a real (redacted) message evidence.

    `redacted_text` is ALREADY redacted by the legacy pipeline; it must
    be re-validated before any canonical use (MIG-2), never re-invented.
    """

    source: LegacySourceRef
    content_id: int
    event_id: int
    ts: datetime | None  # ingest/write time (UTC)
    event_ts: datetime | None  # real event time when present (2.9% of rows)
    user_hash: str | None
    session_hash: str | None
    channel: str | None
    sender: str | None
    trigger: str | None
    source_domain: str | None
    redacted_text: str | None

    @property
    def effective_timestamp(self) -> datetime | None:
        """Preferred event timestamp: event_ts when present, else ts.

        NOTE: for 8/26 backfill rows (ts == ingest time), neither is the
        exact original message time — MIG-2 may reverse-lookup Hermes
        state.db when exact time matters.
        """
        return self.event_ts or self.ts


@dataclass(frozen=True, slots=True)
class LegacyAffectAnnotation:
    """One shadow_affect row — old affective label, NOT new-MR authority.

    dimension/confidence reflect how the OLD system interpreted the event.
    They must never be imported as new MR affect values (REBUILD class).
    """

    source: LegacySourceRef
    content_id: int
    affect_id: int
    ts: datetime | None
    session_hash: str | None
    channel: str | None
    sender: str | None
    dimension: str | None
    confidence: float | None


@dataclass(frozen=True, slots=True)
class LegacyStateSnapshot:
    """One shadow_states row — old state snapshot, NOT MR RuntimeState.

    category/key/value reflect old state tracking and must be REBUILT
    from canonical evidence in MIG-4, never copied as current truth.
    """

    source: LegacySourceRef
    content_id: int
    state_id: int
    ts: datetime | None
    session_hash: str | None
    category: str | None
    key: str | None
    value: str | None
    valid_until: datetime | None
