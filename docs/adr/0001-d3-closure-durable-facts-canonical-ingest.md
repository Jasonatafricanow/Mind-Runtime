# ADR-0001: D3 Closure — restore the frozen durable persistence baseline and canonical ingest integration

- **Date:** 2026-08-21
- **Status:** Accepted

## Problem

The frozen V0.1.4 D3 baseline requires durable append-only persistence for
the first batch of tables (`interactions`, `evidence`, `observations`) and
an ingest path that is replayable, idempotent, and fail-closed. The D3
implementation draft (`docs/superpowers/specs/2026-08-19-d3-fact-ingestion-design.md`)
silently changed this to in-memory stores ("persistence port later; no DB")
without an ADR, and the canonical `TurnOrchestrator.ingest()` kept
constructing `Observation` directly, bypassing the factual plane's
authority, ownership, idempotency, and provenance gates. An independent
audit (2026-08-21) found D3 completion overstated: `READY FOR D4: NO`.

## Previous Assumption

- The V0.1.4 baseline's "持久化" (persistence) wording could be satisfied
  later without changing D3's completion claim.
- A test-side adapter running the gates was sufficient evidence of D3
  correctness even though the production pipeline bypassed the gates.

## New Evidence

- `src/mind_runtime/facts/store.py` and `coordinator.py` used only in-process
  `dict`/`list`; a restart lost Evidence, Observation, provenance, and
  idempotency history.
- `src/mind_runtime/pipeline/orchestrator.py::ingest` constructed
  `Observation` directly and never called `FactIngestService`, so G8/G11
  green proved the service correct, not the canonical turn pipeline.
- `StubDynamics` read wall-clock time (`datetime.now(UTC)`) instead of the
  injected `Clock`.

## Decision

Execute a D3 closure batch (D3.C1–D3.C6) that restores the frozen baseline
without changing any D1 contract or the V0.1.4 baseline documents:

1. **Canonical ingest integration (D3.C1).** `TurnOrchestrator` consumes a
   `FactIngestPort` (default: `FactIngestService`) and delegates every
   `ingest()`; direct `Observation` construction is removed. No second
   pipeline exists.
2. **Durable fact store (D3.C2).** New `SqliteFactBackend` (stdlib SQLite,
   zero runtime deps) keeps exactly the first-batch tables
   `interactions` / `evidence` / `observations`. Rows are append-only with
   `(scope, id)` primary-key idempotency; an admitted Evidence + Observation
   pair is written in one transaction; rejected Evidence is persisted alone
   so the audit trail survives restart. `FactIngestService` and
   `InteractionCoordinator` seed from and write through the backend.
   `ProvenanceRecorder` is idempotent per `(scope, evidence_id)`.
3. **Restart/replay semantics (D3.C3).** Evidence, Observation, and
   provenance survive restart; duplicate events stay idempotent; crash
   windows (evidence without observation) heal by idempotent replay.
4. **Golden boundary closure (D3.C4).** G9 and G15 are split into staged
   contracts: G9a (ordering info) and G15a (cross-persona ingest
   fail-closed) are green on the factual plane; G9b (D4 anti-rollback) and
   G15b (D5 replication) stay xfail with their owners.
5. **Clock/hygiene closure (D3.C5).** `StubDynamics` takes the injected
   `Clock`; leftover pytest temp dirs are removed and gitignored.

## Rejected Alternatives

- **Keep in-memory stores and write an ADR to defer persistence.** Rejected:
  restart, provenance, idempotency history, and replay foundations are the
  same invariant group; D4/D5 would build on a false base and the rework
  cost would exceed the current one.
- **Wire only the test adapter into the golden tests.** Rejected: it would
  leave the production `ingest()` path bypassing the gates.
- **Use a heavier persistence stack (file-per-row, custom format).** Rejected:
  SQLite gives tables matching the frozen "数据表首批" names, transactions,
  and durability with zero runtime dependencies.

## Affected Contracts

No protected contract category changes: `Observation`, `Scope`/Authority/
Ownership, state, and replication semantics are untouched. Additive API
surface only:

- `FactIngestPort` (new port) and `FactIngestService.admit` now requires
  `interaction_id`.
- `InteractionCoordinator.get_interaction` (read API).
- `SqliteFactBackend` / `FactBackend` (new durable backend).
- Golden harness: staged fixtures G9a/G15a added; the owner matrix grows
  from 18 to 20 scenarios; `FactIngestPipeline` gains an optional
  `writing_runtime` pin for staged scenarios.

## Migration

Existing in-memory usage keeps working (backend is optional). No data
migration exists yet because no durable data existed before this ADR. New
deployments configure a backend path; `":memory:"` is valid for ephemeral
runs. Rollback: revert the closure commits; the previous in-memory behavior
returns.

## Acceptance Tests

- `tests/pipeline/test_fact_ingest_integration.py` — canonical ingest runs
  authority/ownership/idempotency/provenance (assistant evidence rejected,
  cross-persona write fail-closed, replay no duplicate).
- `tests/facts/test_persistence.py` — three-table schema, round-trips,
  primary-key idempotency, atomic admission pair.
- `tests/facts/test_service_persistence.py` and
  `tests/pipeline/test_fact_ingest_restart.py` — restart survival, idempotent
  replay, crash-window healing, rejected-evidence audit trail.
- `tests/facts/test_coordinator_persistence.py` — interaction lifecycle
  survives restart and stays fail-closed.
- Golden: G8/G11/G9a/G15a green; 16 xfail with owners
  (`tests/golden/test_golden_g6_g10.py`, `test_golden_g11_g16.py`).
- Full quality gate: `pytest` green, `ruff check`, `ruff format --check`,
  `mypy --strict`, coverage 100%, clean worktree.
