"""Hermes/shadow source -> production Evidence adapter (C2).

This is the ONE integration seam between the private chat source and the
canonical runtime:

    Hermes / shadow source record
      ↓ adapter (this module)
    Existing Production Contracts (Evidence / Interaction)
      ↓
    Existing TurnOrchestrator (FactIngestService admission, one lifecycle)

Deliberately NOT here: any learning semantics, any second orchestrator, any
direct state/affect writes. sync/backfill keep owning reading, paging,
cursors, and shadow-store persistence; this module only TRANSLATES a stable
source record into production contracts and drives the standard lifecycle
begin_turn -> ingest -> run -> commit_turn (abort on downstream failure so
the fact plane survives while the projection is discarded, D5/G13b).

Identity: evidence id derives from the stable Hermes message PK
(``hermes:<message id>``), never from a content hash — the same source
message sync-twice/replay-once admits exactly once (ADR-0009 dispositions).

Time: ``Evidence.occurred_at`` always carries the ORIGINAL event timestamp;
``received_at`` is the processing-time clock reading. Historical replays
never masquerade as just-happened events.

Modes: LIVE / BACKFILL / REPLAY are processing metadata only — all three
flow through the same adapter, the same admission gate, and the same
runtime; no alternative cognition path exists.

Assistant-role records are NOT admissible user-state evidence (the
production AuthorityValidator owns that rule, facts/validators.py). The
bridge refuses them up front and never lowers the gate for history
completeness (G8 lineage: assistant output cannot self-authorize facts).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum

from mind_runtime.contracts import (
    Authority,
    AuthorityLevel,
    Evidence,
    Interaction,
    InteractionStatus,
    Scope,
    ScopeDomain,
    SyncFields,
)
from mind_runtime.pipeline.orchestrator import TurnOrchestrator
from mind_runtime.providers.clock import Clock
from mind_runtime.shadow.sources.hermes import HermesEvent

SOURCE_NAME = "hermes"

_USER_ROLE = "user"


class AdmissionMode(StrEnum):
    """Why this record is being processed right now (metadata only)."""

    LIVE = "live"
    BACKFILL = "backfill"
    REPLAY = "replay"


@dataclass(frozen=True)
class SourceRecord:
    """A normalized, role-tagged record from the private chat source."""

    source_record_id: str
    role: str
    text: str
    occurred_at: datetime
    channel: str
    session_id: str
    # ADR-0012: True when the original event time was unavailable in the
    # persisted source row and the row's persistence time had to stand in.
    # The loop surfaces this as an explicit reason code instead of
    # silently pretending recency.
    occurred_fallback: bool = False

    @classmethod
    def from_hermes_event(cls, event: HermesEvent) -> SourceRecord:
        """Map one read-only Hermes adapter event (stable message PK kept)."""
        return cls(
            source_record_id=str(event.content_id),
            role=event.meta.sender,
            text=event.text,
            occurred_at=datetime.fromtimestamp(event.ts, tz=UTC),
            channel=event.meta.channel,
            session_id=event.meta.session,
        )

    @classmethod
    def from_shadow_row(
        cls,
        *,
        content_id: int,
        sender: str,
        text: str,
        event_ts: datetime | None,
        persisted_ts: datetime,
        channel: str,
        session_hash: str,
    ) -> tuple[SourceRecord, bool]:
        """Map one shadow_events row (ADR-0012).

        Returns the record plus the occurred_fallback flag. The session
        identity is the store's hashed session key — stable and private by
        construction; the content is the ALREADY credential-gated row text
        (ADR-0011 ingestion semantics), so secrets never reach canonical
        cognition through this path.
        """
        fallback = event_ts is None
        return (
            cls(
                source_record_id=str(content_id),
                role=sender,
                text=text,
                occurred_at=event_ts or persisted_ts,
                channel=channel,
                session_id=session_hash,
                occurred_fallback=fallback,
            ),
            fallback,
        )


@dataclass(frozen=True)
class BridgeOutcome:
    """Per-record processing ledger entry (C2.9 trace fields)."""

    mode: AdmissionMode
    source_record_id: str
    evidence_id: str
    interaction_id: str
    scope_user_id: str
    disposition: str | None
    stage: str
    blocked_reason: str | None
    projection_committed: bool
    downstream_evidence_refs: tuple[str, ...]
    reason_codes: tuple[str, ...]


@dataclass(frozen=True)
class _CanonicalFingerprint:
    """Order-insensitive canonical identity: (state_id, version) multiset."""

    fingerprint: tuple[tuple[str, int], ...]


def _canonical_fingerprint(orchestrator: TurnOrchestrator) -> _CanonicalFingerprint:
    states = tuple(sorted((state.state_id, state.version) for state in orchestrator.canonical))
    return _CanonicalFingerprint(states)


class HermesProductionBridge:
    """Adapt Hermes/shadow records and drive the one canonical lifecycle."""

    def __init__(
        self,
        orchestrator: TurnOrchestrator,
        *,
        clock: Clock,
        origin_runtime_id: str,
        user_id: str,
    ) -> None:
        self._orchestrator = orchestrator
        self._clock = clock
        self._origin_runtime_id = origin_runtime_id
        self._user_id = user_id
        self._ledger: list[BridgeOutcome] = []

    @property
    def scope(self) -> Scope:
        return Scope(domain=ScopeDomain.USER, user_id=self._user_id)

    @property
    def outcomes(self) -> tuple[BridgeOutcome, ...]:
        """Ledger of every record this bridge processed, in order."""
        return tuple(self._ledger)

    # ── adapter ────────────────────────────────────────────────────────────

    def evidence_id_for(self, record: SourceRecord) -> str:
        """Stable cross-run identity from the SOURCE PK, not the content."""
        return f"{SOURCE_NAME}:{record.source_record_id}"

    def to_evidence(self, record: SourceRecord, *, received_at: datetime) -> Evidence:
        """Translate one record into the production contract.

        source_type follows the production authority vocabulary
        (facts/validators.py): only ``user_message`` is authority-capable;
        ``assistant_message`` is internally-derived and will be rejected by
        the admission gate — the converter must stay truthful about roles.
        """
        evidence_id = self.evidence_id_for(record)
        scope = self.scope
        source_type = "user_message" if record.role == _USER_ROLE else "assistant_message"
        return Evidence(
            id=evidence_id,
            source_type=source_type,
            source_id=record.source_record_id,
            authority_level=AuthorityLevel.OBSERVED,
            occurred_at=record.occurred_at,
            received_at=received_at,
            payload={"text": record.text},
            scope=scope,
            origin_runtime_id=self._origin_runtime_id,
            authority=Authority(
                scope=scope,
                level=AuthorityLevel.OBSERVED,
                source_id=record.source_record_id,
            ),
            sync=SyncFields(
                scope,
                self._origin_runtime_id,
                evidence_id,
                1,
                f"idem-{evidence_id}",
            ),
        )

    def interaction_for(self, record: SourceRecord) -> Interaction:
        """One admissible source record == one lifecycle unit.

        Contract evidence: Interaction is the single-turn causal index
        (contracts/interaction.py) carrying its own channel/session
        identity; the orchestrator requires exactly one per
        begin_turn..commit window and imposes no pairing/grouping rule, so
        records are not artificially grouped.
        """
        return Interaction(
            interaction_id=f"{SOURCE_NAME}-{record.source_record_id}",
            scope=self.scope,
            channel=record.channel,
            session_id=record.session_id,
            turn_id=record.source_record_id,
            started_at=self._clock.now(),
            committed_at=None,
            status=InteractionStatus.OPEN,
        )

    # ── driver ─────────────────────────────────────────────────────────────

    def _admission_disposition(self, interaction_id: str) -> str:
        """Read the admission outcome from the production trace ledger.

        The disposition is decided by the factual plane (ADR-0009) and
        recorded by the orchestrator's own TraceRecorder as
        ``outcome='fact_<disposition>'``; reusing that entry keeps a single
        source of truth instead of inferring from store diffs.
        """
        ingest_entries = [
            entry
            for entry in self._orchestrator.trace.trace(interaction_id)
            if entry.stage == "ingest"
        ]
        last = ingest_entries[-1]
        prefix = "fact_"
        return last.outcome[len(prefix) :] if last.outcome.startswith(prefix) else last.outcome

    def process(
        self, record: SourceRecord, *, mode: AdmissionMode = AdmissionMode.LIVE
    ) -> BridgeOutcome:
        """Run one record through the canonical lifecycle (idempotent).

        Assistant-role records are refused before any turn is built: they
        are not authoritative user-state evidence, replaying history must
        not let them self-authorize facts (production AuthorityValidator
        owns the same rule for anything that reaches admission).
        """
        evidence_id = self.evidence_id_for(record)
        interaction_id = f"{SOURCE_NAME}-{record.source_record_id}"

        if record.role != _USER_ROLE:
            outcome = BridgeOutcome(
                mode=mode,
                source_record_id=record.source_record_id,
                evidence_id=evidence_id,
                interaction_id=interaction_id,
                scope_user_id=self._user_id,
                disposition=None,
                stage="blocked",
                blocked_reason=f"source type '{record.role}_message' cannot become a user fact",
                projection_committed=False,
                downstream_evidence_refs=(),
                reason_codes=("authority_not_user_fact",),
            )
            self._ledger.append(outcome)
            return outcome

        evidence = self.to_evidence(record, received_at=self._clock.now())
        interaction = self.interaction_for(record)
        before = _canonical_fingerprint(self._orchestrator)

        self._orchestrator.begin_turn(interaction)
        self._orchestrator.ingest(evidence)
        try:
            self._orchestrator.run()
            self._orchestrator.commit_turn()
        except Exception:
            # D5/G13b: the fact plane already survived ingest-commit; the
            # uncommitted projection must be discarded, never half-promoted.
            self._orchestrator.abort_turn()
            raise

        after = _canonical_fingerprint(self._orchestrator)
        disposition = self._admission_disposition(interaction_id)
        projection_committed = after.fingerprint != before.fingerprint and disposition != "replay"
        outcome = BridgeOutcome(
            mode=mode,
            source_record_id=record.source_record_id,
            evidence_id=evidence_id,
            interaction_id=interaction_id,
            scope_user_id=self._user_id,
            disposition=disposition,
            stage="committed",
            blocked_reason=None,
            projection_committed=projection_committed,
            downstream_evidence_refs=tuple(
                ref
                for observation in self._orchestrator.observations
                for ref in observation.evidence_refs
            ),
            reason_codes=(
                f"admission_{disposition}",
                f"mode_{mode.value}",
            ),
        )
        self._ledger.append(outcome)
        return outcome

    def process_many(
        self,
        records: tuple[SourceRecord, ...] | list[SourceRecord],
        *,
        mode: AdmissionMode,
    ) -> tuple[BridgeOutcome, ...]:
        """Batch convenience with identical per-record canonical semantics."""
        return tuple(self.process(record, mode=mode) for record in records)
