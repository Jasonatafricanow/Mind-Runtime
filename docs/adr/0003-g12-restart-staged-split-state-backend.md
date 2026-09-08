# ADR-0003: G12 restart staged split and canonical persistence wiring (D5.8)

- **Date:** 2026-08-23
- **Status:** Accepted

## Problem

The D5/D7 delivery review (2026-08-23) found a P1 blocker: D5 was declared
closed while its golden G12 (owner matrix binding `MR-D5`) stayed a strict
xfail and canonical state had no restart path. The D5 report excluded
"canonical persistence through the durable state backend" as a deployment
wiring choice, but the D2 owner matrix binds G12 to MR-D5, so closing D5
without a D5-owned green restart contract is inconsistent. `SqliteStateBackend`
existed but was not connected to the UnitOfWork commit path or the
orchestrator startup.

## Previous Assumption

- Canonical persistence could be deferred to the deployment layer while D5
  (which owns G12 in the frozen owner matrix) is closed on the strength of
  the D5.4 checkpoint/receipt recovery tests alone.
- G12's composite semantics (state + memory + relationship + pending
  writeback consistent after restart) could keep the single `MR-D5` owner
  binding.

## New Evidence

- `src/mind_runtime/state/persistence.py` defines `StateBackend` +
  `SqliteStateBackend` (append-only `states` / `state_transitions` /
  `state_definitions`), but `src/mind_runtime/pipeline/orchestrator.py`
  only accepted an in-memory `canonical_snapshot`; no orchestrator code
  loaded from or saved through the backend, so a restart lost canonical
  state even though facts, checkpoints, and receipts were durable.
- The golden output still contained `G12 - MR-D5 not implemented`, and no
  staged scenario existed for the D5-owned restart part (unlike G9/G15/G16,
  which were split when their owners closed).

## Decision

Execute the D5.8 closure:

1. **StateBackend wiring.** `TurnOrchestrator` accepts an optional
   `state_backend` (mutually exclusive with `canonical_snapshot`, fail
   closed). At startup it loads canonical state from the backend, keeping
   the highest version per (scope, dimension) — the durable table is
   append-only. `_ingest_commit` persists the reconciled effective states
   and every transition with its referenced states (superseded intermediate
   records are not part of the effective set but must resolve on load).
   `commit_turn` persists the promoted projected state, plus a materialized
   transition when the projection carried a real turn_commit intent.
2. **G12 staged split (golden matrix change, staged-scenario precedent
   G9a/G15a/G16a).** New staged fixture **G12a** (owner `MR-D5`) covers the
   D5-owned contract: committed canonical state survives restart through
   the durable backend (`restart.consistent=true`). G12 keeps the composite
   restart story (memory / relationship / pending writeback) and is
   re-owned to **MR-D11** (Kayla E2E / product-slice acceptance), the
   earliest in-sequence gate that can verify the composite story; the
   Memory-writeback portion itself remains outside the continuous backlog
   (MR-4) per the repository README and is re-evaluated at D11.
3. **Golden coverage.** `StateBackendPipeline` runs the real orchestrator
   over a durable SQLite backend, commits a turn, restarts on the same
   backend, and asserts canonical restoration. `test_golden_g12a` is green;
   `test_golden_g12` stays xfail with `MR-D11 not implemented`.

## Rejected Alternatives

- **Implement the full composite G12 in D5.** Rejected: its semantics span
  Memory (MR-4, outside the continuous backlog), relationship state, and
  pending writeback — none of which exist in D5; faking them would violate
  the "no later-gate implementation" scope discipline.
- **Keep G12 bound to MR-D5 and close D5 anyway.** Rejected: that is the
  inconsistency the review flagged; every closed gate must have its
  owned restart contract green.
- **Wire the backend only into the golden pipeline, not the orchestrator.**
  Rejected: restart correctness must live in the canonical pipeline, not in
  test-side glue (same reasoning as ADR-0001's canonical ingest closure).

## Affected Contracts

No protected contract category changed. Additive surface only:

- `TurnOrchestrator(state_backend=...)` (new optional parameter;
  `canonical_snapshot` and `state_backend` are mutually exclusive).
- Orchestrator behavior: with a backend, ingest-committed facts and
  turn-committed projections are persisted through it, and canonical is
  restored from it at startup.
- Golden harness: staged fixture G12a added; the owner matrix grows from 21
  to 22 scenarios; G12 re-owned from MR-D5 to MR-D11.

## Migration

Existing in-memory usage keeps working (backend is optional). Deployments
that previously passed `canonical_snapshot` keep it; deployments that want
durable canonical state pass `state_backend` instead. Rollback: revert the
D5.8 commits; in-memory behavior returns and G12a goes back to xfail.

## Acceptance Tests

- `tests/pipeline/test_state_backend.py` — startup load (highest version
  per scope+dimension), backend/snapshot conflict fail-closed, ingest
  persist (states + transitions with referenced states), commit persist
  (projected state + materialized turn_commit transition), abort persists
  only ingested facts, restart recovers canonical, committed agent affect
  survives restart.
- Golden: `test_golden_g12a` green via `StateBackendPipeline`; `test_golden_g12`
  xfail with `MR-D11 not implemented`; owner matrix audit green (22
  scenarios, owners incl. MR-D11).
- Full quality gate: `pytest` green, `ruff check`, `ruff format --check`,
  `mypy --strict`, coverage 100%, clean worktree.
