# ADR-0012: Live production source loop — separate acquisition cursor from cognition processing state

- **Date:** 2026-08-27
- **Status:** Accepted

## Problem

The D11L daemon synced Hermes messages into the shadow store but never fed
production cognition (the C2 disconnect). Wiring `process_pending()` into
`daemon.one_pass()` must not re-introduce an implicit coupling where the
Hermes sync cursor doubles as the runtime's cognition progress marker: a
message whose source persistence succeeded can still crash before
canonical admission, and one committed AFTER canonical promotion can crash
before any local marker write. Conflating the two cursors loses or
double-processes exactly in those windows.

Two smaller decisions ride along:

1. `shadow_events.ts` stores ingestion-persistence time, not the original
   message time; historical replays sourced from shadow rows would
   otherwise misreport occurred-at as just-now (violating the C2 time
   contract, L4).
2. The C2 bridge ledger is in-memory per instance; assistant-role messages
   would be re-blocked every pass forever unless BLOCKED is remembered.

## Previous Assumption

The Hermes sync cursor and the shadow `content_id` watermark were treated
as sufficient progress state; shadow `ts` doubled as event time; no
durable notion of "this source row completed production processing"
existed beyond reading code intent.

## New Evidence

- Crash Window A/B are reachable structurally: acquisition (sqlite insert
  + cursor advance, shadow/sync.py) and admission (FactIngestService
  transactional pair, facts/service.py) are separate databases and
  separate transactions by design (ADR-0009); nothing made them atomic.
- `shadow_events` is written by `run_backfill` with `ts=datetime.now()`;
  the original epoch lives only in `HermesEvent.ts` and is discarded at
  insert (shadow/backfill.py, pre-C2.10 rows).
- Blocked sources are derivable NOWHERE durably today: blocked outcomes
  never reach Evidence (validator refuses before retention… actually they
  refuse BEFORE the persist-on-reject path because the bridge refuses
  pre-turn), so a poisoned assistant row is invisible to restart logic.

## Decision

1. **Cursor separation.** The Hermes acquisition cursor (sync_state,
   advanced by sync/backfill) stays the ONLY acquisition progress marker.
   Production progress is DERIVED, never duplicated for successes:
   - PROCESSED ⇔ the admission pair exists in the durable factual plane
     AND the canonical plane holds the turn's projection (detected via
     canonical lineage referencing the evidence id, or the frozen D2S
     `projected-<interaction>` state-id convention — the two existing
     transition ports);
   - ADMITTED-UNCOMMITTED ⇔ admission pair present, projection absent
     (e.g. cognition aborted after ingest): converges on the next pass by
     reprocessing through the bridge in REPLAY mode, which completes the
     missing projection idempotently;
   - FAILED_RETRYABLE ⇔ a runtime exception during processing: the row is
     left untouched and retried next pass;
   - BLOCKED ⇔ authority-refused sources recorded once in a minimal,
     dedicated state store (`blocked_records(source_record_id PK, reason,
     decided_at)` in its own SQLite file) — created lazily by the loop,
     deleted never;
   - loop pass counters report COGNITIVE outcomes: a pass counts as
     processed iff the durable canonical fingerprint changed for that
     record's lifecycle (first commit OR aborted-projection convergence),
     never merely because a fact admission said replayed.
   No second copy of source rows exists anywhere; the source store remains
   `shadow.db`.

2. **Original event time preserved.** `shadow_events` gains a nullable
   `event_ts` column (additive ALTER for existing DBs, included in the
   CREATE for fresh ones). `run_backfill` fills it from
   `HermesEvent.ts`. The production loop maps
   `occurred_at = event_ts`; legacy rows with NULL fall back to the
   persisted `ts` AND surface `reason_code="occurred_fallback_persisted"`
   instead of silently pretending recency. Consumers selecting named
   columns are unaffected; rotation semantics (`ts`) unchanged.

3. **Ordering.** Pending selection orders by `(ts ASC, content_id ASC)` —
   the source store's frozen deterministic order, tie-broken by the stable
   message PK. Timestamp-only ordering is explicitly rejected (C0.5
   lesson).

4. **Mode.** Pending-loop processing is ALWAYS `AdmissionMode.LIVE`
   (first-time canonical processing of newly acquired increments).
   REPLAY remains reserved for reprocessing an identity known to have
   been admitted (idempotent convergence in Crash Window B / manual
   replay), never for "it came from shadow storage".

5. **Layered failure isolation.** acquisition (sync) ⊥ production
   cognition (bridge/orchestrator/facts/state) ⊥ legacy derived metrics
   (learn/states/snapshot). Each may fail independently; no layer rolls
   back another, and production never REQUIRES a legacy heuristic to
   succeed first.

6. **Gate.** The daemon invokes the loop only when
   `MIND_RUNTIME_PRODUCTION_INGEST` is truthy (fail-closed default off),
   matching the D11L gate philosophy. When disabled, daemon behavior is
   byte-for-byte the pre-C2.10 flow.

## Rejected Alternatives

- **Use FactBackend as the BLOCKED store too:** poisoning writes must not
  enter the authoritative factual plane (they were refused by authority —
  recording them as Evidence-adjacent rows would blur ADR-0009 audits);
  a separate operational ledger keeps authorities clean.
- **Reuse bridge's in-memory ledger across passes:** dies with the
  process; cannot satisfy Crash Window recovery.
- **Rewrite shadow `ts` into event time:** breaks 30-day rotation
  arithmetic and every existing consumer.
- **Defer NULL-legacy rows for manual curation:** the private instance has
  months of such rows; blocking them would stall the whole queue.

## Affected Contracts

none at the kernel level. Shadow-store additive column + a new operational
state file + daemon sequencing only. Frozen protected categories
(observation/state/memory semantics, replication, projection boundaries)
untouched; C2 evidence/authority/idempotency contracts reused verbatim.

## Migration

Existing shadow DBs gain `event_ts=NULL` via lazy ALTER on next
init/store; their loop processing uses the flagged persisted-time
fallback. Rollback: stop setting `MIND_RUNTIME_PRODUCTION_INGEST`; the
column and store remain inert.

## Acceptance Tests

`tests/shadow/test_runtime_loop.py` DL1–DL10 (plus gate/ordering checks),
executed against the real sync/backfill path, real bridge, real
TurnOrchestrator, and durable SQLite facts/state stores; official coverage
gate stays at 100%.
