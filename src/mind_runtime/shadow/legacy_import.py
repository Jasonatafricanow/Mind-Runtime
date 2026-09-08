"""MIG-2 — D11 legacy shadow_events direct import into the new MR factual plane.

This is a THIN importer per migration dispatch MIG-2:

  * reuses MIG-1 LegacyD11Reader (read-only) for the source;
  * reuses the production FactIngestService.admit() path (no direct SQL
    into internal tables, no second admission pipeline);
  * maps each shadow_events row to an Evidence and lets the real ingest
    gate decide Observation formation / rejection;
  * is idempotent via the (scope, id) primary key — re-running imports
    zero duplicates;
  * NEVER imports shadow_affect / shadow_states (legacy derived values
    must not pollute the new MR), and NEVER replays Dynamics.

Field mapping (per dispatch §4 / §5):

  content_id     -> evidence.id = "d11-ev-<content_id>"
  redacted_text  -> payload["text"]
  channel        -> payload["channel"]
  sender         -> payload["sender"]  (user/agent)
  source_domain  -> payload["source_domain"]
  ts             -> payload["ingestion_ts"] (honest: this is ingest time)
  event_ts       -> occurred_at when present, else ts (payload["time_source"] marks which)
  session_hash   -> payload["session_hash"]
  user_hash      -> payload["user_hash"]
  provenance     -> payload["legacy_provenance"] = {
                     source="d11-shadow", database="shadow.db",
                     table="shadow_events", content_id=<id> }

Sender mapping:
  user  -> source_type "user_message"  (authority-capable -> may form Observation)
  agent -> source_type "assistant_message" (internally derived -> rejected for
          user-fact admission, evidence-only, per production AuthorityValidator)

Authoritative contract notes:
  * occurred_at / received_at are aware UTC (enforced by Evidence contract).
  * When event_ts is missing, occurred_at falls back to ts and the payload
    records time_source="ts" so nobody mistakes ingestion time for event time.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from mind_runtime.contracts import (
    Authority,
    AuthorityLevel,
    Evidence,
    Scope,
    ScopeDomain,
    SyncFields,
)
from mind_runtime.facts import FactIngestService, SqliteFactBackend
from mind_runtime.providers.clock import Clock
from mind_runtime.shadow.legacy_reader import DEFAULT_EVENTS_DB, LegacyD11Reader

# Default new-MR production factual DB (runtime_loop default location).
DEFAULT_FACTS_DB = (
    Path.home() / ".hermes" / "profiles" / "xiyue" / "runtime" / "facts.sqlite"
)

_SENDER_TO_SOURCE_TYPE = {
    "user": "user_message",
    "agent": "assistant_message",
}


class SystemClock:
    """Production wall-clock (aware UTC)."""

    def now(self) -> datetime:
        return datetime.now(UTC)


@dataclass(frozen=True, slots=True)
class ImportCounts:
    """Counters for one import run (dispatch §12 acceptance numbers)."""

    read: int = 0
    imported: int = 0
    duplicates: int = 0
    invalid: int = 0
    evidence_new: int = 0
    observation_new: int = 0
    evidence_rejected: int = 0

    def as_dict(self) -> dict[str, int]:
        return {
            "read": self.read,
            "imported": self.imported,
            "duplicates": self.duplicates,
            "invalid": self.invalid,
            "evidence_new": self.evidence_new,
            "observation_new": self.observation_new,
            "evidence_rejected": self.evidence_rejected,
        }


def build_evidence(record, *, scope: Scope, origin_runtime_id: str) -> Evidence:
    """Map one LegacyEventRecord to an MR Evidence (deterministic).

    `record` is a LegacyEventRecord from legacy_dto.
    """
    event_ts = record.event_ts
    occurred = event_ts if event_ts is not None else record.ts
    if occurred is None:
        # Legacy rows always carry ts (NOT NULL), so this is unreachable;
        # kept as a guard against malformed rows.
        occurred = datetime(1970, 1, 1, tzinfo=UTC)

    evidence_id = f"d11-ev-{record.content_id}"
    sender = record.sender or "user"
    source_type = _SENDER_TO_SOURCE_TYPE.get(sender, "user_message")

    payload = {
        "text": record.redacted_text or "",
        "channel": record.channel,
        "sender": sender,
        "source_domain": record.source_domain,
        "ingestion_ts": record.ts.isoformat() if record.ts else None,
        "time_source": "event_ts" if event_ts is not None else "ts",
        "session_hash": record.session_hash,
        "user_hash": record.user_hash,
        "legacy_provenance": {
            "source": "d11-shadow",
            "database": "shadow.db",
            "table": "shadow_events",
            "content_id": record.content_id,
        },
    }

    authority_level = (
        AuthorityLevel.VERIFIED if source_type == "user_message" else AuthorityLevel.OBSERVED
    )

    return Evidence(
        id=evidence_id,
        scope=scope,
        origin_runtime_id=origin_runtime_id,
        source_type=source_type,
        source_id=f"d11-shadow:{record.content_id}",
        authority_level=authority_level,
        authority=Authority(scope=scope, level=authority_level, source_id=f"d11-shadow:{record.content_id}"),
        occurred_at=occurred,
        received_at=record.ts if record.ts is not None else occurred,
        payload=payload,
        sync=SyncFields(
            scope,
            origin_runtime_id,
            evidence_id,
            1,
            f"idem-d11-ev-{record.content_id}",
        ),
    )


def import_legacy_events(
    *,
    facts_db: str | Path = DEFAULT_FACTS_DB,
    origin_runtime_id: str = "kayla",
    user_id: str = "user",
    persona_id: str | None = None,
    batch_size: int = 500,
    limit: int | None = None,
    clock: Clock | None = None,
    legacy_events_db: str | Path | None = None,
    progress: bool = False,
) -> ImportCounts:
    """Import shadow_events into the MR factual plane via production ingest.

    Idempotent: re-running yields zero new rows.

    ``legacy_events_db`` overrides the source shadow.db path (for tests /
    alternate profiles). When None, the default profile shadow.db is used.
    """
    clock = clock or SystemClock()
    counts = ImportCounts()

    backend = SqliteFactBackend(facts_db)
    try:
        service = FactIngestService(clock=clock, backend=backend)
        reader = LegacyD11Reader(
            events_db=legacy_events_db if legacy_events_db is not None else DEFAULT_EVENTS_DB
        )
        scope = Scope(domain=ScopeDomain.USER, user_id=user_id)

        for record in reader.scan_events():
            if limit is not None and counts.read >= limit:
                break
            counts = _import_one(
                service, record, scope=scope,
                origin_runtime_id=origin_runtime_id, persona_id=persona_id,
                counts=counts,
            )
            if progress and counts.read % batch_size == 0:
                print(f"  read={counts.read} imported={counts.imported} dup={counts.duplicates}")
        return counts
    finally:
        backend.close()


def _import_one(
    service: FactIngestService,
    record,
    *,
    scope: Scope,
    origin_runtime_id: str,
    persona_id: str | None,
    counts: ImportCounts,
) -> ImportCounts:
    counts = ImportCounts(
        read=counts.read + 1,
        imported=counts.imported,
        duplicates=counts.duplicates,
        invalid=counts.invalid,
        evidence_new=counts.evidence_new,
        observation_new=counts.observation_new,
        evidence_rejected=counts.evidence_rejected,
    )
    try:
        evidence = build_evidence(record, scope=scope, origin_runtime_id=origin_runtime_id)
    except Exception:
        counts = ImportCounts(
            read=counts.read, imported=counts.imported, duplicates=counts.duplicates,
            invalid=counts.invalid + 1, evidence_new=counts.evidence_new,
            observation_new=counts.observation_new, evidence_rejected=counts.evidence_rejected,
        )
        return counts

    # shadow_affect / shadow_states are NEVER admitted here (dispatch §7/§8).
    from mind_runtime.facts import AuthorityError, OwnershipError, FactAdmissionConflictError

    try:
        result = service.admit(
            evidence,
            interaction_id=f"d11-interaction-{record.content_id}",
            writing_runtime=origin_runtime_id,
            writing_persona_id=persona_id,
        )
    except (AuthorityError, OwnershipError):
        # Rejected evidence is still persisted alone by the service (audit trail);
        # count as evidence-only (rejected for observation formation). This is
        # NOT a new imported canonical row for MIG-2 acceptance purposes, so it
        # does not increment `imported` (avoids double-counting on re-runs).
        counts = ImportCounts(
            read=counts.read, imported=counts.imported, duplicates=counts.duplicates,
            invalid=counts.invalid, evidence_new=counts.evidence_new,
            observation_new=counts.observation_new, evidence_rejected=counts.evidence_rejected + 1,
        )
        return counts
    except FactAdmissionConflictError:
        counts = ImportCounts(
            read=counts.read, imported=counts.imported, duplicates=counts.duplicates,
            invalid=counts.invalid + 1, evidence_new=counts.evidence_new,
            observation_new=counts.observation_new, evidence_rejected=counts.evidence_rejected,
        )
        return counts

    from mind_runtime.facts import FactAdmissionDisposition

    disposition = result.disposition
    if disposition is FactAdmissionDisposition.NEW:
        counts = ImportCounts(
            read=counts.read, imported=counts.imported + 1, duplicates=counts.duplicates,
            invalid=counts.invalid, evidence_new=counts.evidence_new + 1,
            observation_new=counts.observation_new + 1,
            evidence_rejected=counts.evidence_rejected,
        )
    elif disposition is FactAdmissionDisposition.REPLAY:
        counts = ImportCounts(
            read=counts.read, imported=counts.imported, duplicates=counts.duplicates + 1,
            invalid=counts.invalid, evidence_new=counts.evidence_new,
            observation_new=counts.observation_new, evidence_rejected=counts.evidence_rejected,
        )
    elif disposition is FactAdmissionDisposition.REPAIRED:
        counts = ImportCounts(
            read=counts.read, imported=counts.imported + 1, duplicates=counts.duplicates,
            invalid=counts.invalid, evidence_new=counts.evidence_new,
            observation_new=counts.observation_new + 1,
            evidence_rejected=counts.evidence_rejected,
        )
    return counts
