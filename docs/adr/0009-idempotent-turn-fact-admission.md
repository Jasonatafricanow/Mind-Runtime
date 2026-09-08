# ADR-0009: Idempotent Turn Fact Admission (NEW / REPAIRED / REPLAY)

- **Date:** 2026-08-23
- **Status:** Draft — requires independent architecture/contract review before
  any production code

## Problem

The durable factual plane is idempotent at the store level, but the canonical
turn path is not. When the same authoritative Evidence is admitted again (a
replay), `TurnOrchestrator.ingest` unconditionally adds the returned
Observation to the current turn, the evidence refs, and the factual overlay.
The replayed Observation then reaches the EmotionalTransition input, the
factual reconcile, and the projection/commit path, producing a second event
impulse and a new State record after registered elapsed-time recovery. A
direct canonical probe showed: one additional Interaction, recovery
contribution `-0.14`, repeated-event contribution `+0.14`, and a changed
canonical State record.

This is the D11S.3 root cause: validation-side duplicate filtering
(`mind_runtime.validation.horizon`) currently hides the defect by skipping
`composition.apply_event` for repeats, so the green G26 result certifies a
validation workaround, not production idempotency.

## Previous Assumption

The D3 integration contract
(`tests/pipeline/test_fact_ingest_integration.py`) assumed that a replayed
Evidence must still appear in the current-turn view
(`test_ingest_replay_same_evidence_no_duplicate_observation` asserts
`len(orchestrator.observations) == 1` after a second Interaction). The
store-level idempotency (one durable Evidence/Observation row) was treated as
sufficient proof of replay safety. That assumption is wrong: store idempotency
does not stop the current-turn semantic path from consuming the replay.

## New Evidence

1. `FactIngestService.admit` computes whether Evidence and Observation are new
   but discards those booleans and always returns a newly constructed
   current-interaction Observation.
2. `TurnOrchestrator.ingest` consumes every returned Observation into
   `turn.observations`, `turn.evidence_refs`, and `factual_overlay` without
   regard to admission history.
3. The replayed Observation flows into `EmotionalTransitionInput.observations`
   and `_ingest_commit`, so a repeat produces a second impulse and a new
   State version.
4. ADR-0001 states duplicate events stay idempotent; the D3 design
   (`docs/superpowers/specs/2026-08-19-d3-fact-ingestion-design.md`) states a
   replayed Evidence cannot produce a duplicate Observation. The integration
   test above contradicts both.

## Decision

Make factual replay idempotent at the canonical turn boundary. Replaying the
same authoritative Evidence may retain an audit Interaction and must execute
registered elapsed-time recovery, but it cannot create a new current-turn
Observation, factual overlay entry, semantic candidate, event contribution,
State excitation, or causal trace.

This ADR supersedes the current-turn replay expectation in
`tests/pipeline/test_fact_ingest_integration.py`. That test's per-turn-view
assertion is replaced by contract tests that assert the opposite: replay adds
no Observation to the current turn.

### 1. Disposition matrix (frozen)

The factual plane returns exactly one disposition per admission, decided by
the durable backend, never inferred from context:

| Disposition | Durable condition | Current-turn behavior |
| --- | --- | --- |
| `NEW` | Evidence and derived Observation are newly admitted atomically | Consume the new Observation once (causal) |
| `REPAIRED` | Exact Evidence already exists (byte-identical) but its derived Observation is missing | Persist and consume the repaired Observation exactly once (causal, labeled repaired) |
| `REPLAY` | Exact Evidence and derived Observation already exist (byte-identical) | Return the existing authoritative Observation for audit; do not add it to the new turn (non-causal) |
| conflict | Same `(scope, id)` but different immutable bytes, or an impossible partial pair (Observation present without its Evidence) | Fail closed with `FactAdmissionConflictError`; never reinterpret as replay |

For `REPAIRED` and `REPLAY` the stored Evidence must be byte-identical to the
incoming Evidence. Any byte difference under the same `(scope, id)` is a
conflict and fails closed — including a stored Evidence that was persisted
alone by a rejected admission.

### 2. Causal identity binding for REPAIRED (frozen)

A repaired Observation keeps the original admission's causal identity, not the
repair attempt's:

- `Observation.interaction_id` is the durable original Evidence provenance
  Interaction ID (the `interaction_id` recorded on the Evidence row when it
  was first persisted).
- `Observation.observed_at` is the immutable `Evidence.received_at`.
- The repair turn consumes the repaired Observation exactly once and its trace
  entry labels it `fact_repaired`, retaining the original Evidence and
  Observation causal references.
- The repaired Observation is never rewritten as if it were first observed in
  the repair Interaction.

This binding is accepted here; it may only be changed by a future ADR, never
left to implementation choice.

### 3. Audit Interaction and turn continuation (frozen)

- For `REPLAY` the audit Interaction is retained and the turn continues. The
  turn runs without a new factual event so injected-Clock recovery, Intent
  lifecycle, ActionPolicy, and other legitimate no-new-fact behavior still
  execute.
- Suppressing the whole Interaction on replay is rejected: it hides
  elapsed-time behavior and weakens the audit trail.
- For `REPLAY`, `TurnOrchestrator.ingest` records a non-causal audit trace
  entry and returns the existing authoritative Observation, but does not place
  it in `turn.observations`, `turn.evidence_refs`, or `factual_overlay`, and
  therefore does not feed it into `EmotionalTransitionInput`, the factual
  reconcile, or the projection/commit path.
- Trace entries distinguish `fact_new`, `fact_repaired`, and `fact_replay`
  without treating replay as a new cause.

### 4. Interface (frozen)

The factual plane owns the disposition; validation never detects duplicates.

```python
class FactAdmissionDisposition(StrEnum):
    NEW = "new"
    REPAIRED = "repaired"
    REPLAY = "replay"


@dataclass(frozen=True, slots=True)
class FactAdmissionResult:
    observation: Observation
    disposition: FactAdmissionDisposition
```

- `FactIngestPort.admit(...)` returns `FactAdmissionResult`.
- `TurnOrchestrator.ingest` continues returning the authoritative
  `Observation` for compatibility; it mutates the current-turn
  Observation/evidence/overlay inputs only for `NEW` and `REPAIRED`.
- Disposition is never inferred from schedule IDs, Interaction IDs, payload
  text, validation fixtures, or Dynamics output.

### 5. Atomic arbitration (frozen)

SQLite disposition is decided atomically by the backend transaction, not by a
service instance's preloaded cache. Two services with stale caches cannot both
report `NEW` or `REPAIRED` for the same authority pair:

- The backend write is the arbiter: exactly one concurrent writer wins; every
  loser observes the backend-authoritative stored pair and returns `REPLAY`
  with the stored Observation. The byte-identical check per section 1 applies
  first: if the backend-authoritative stored Evidence differs from the
  incoming Evidence's immutable bytes, the loser fails closed instead of
  returning `REPLAY`.
- A result where both instances report `NEW`/`REPAIRED` is a failure even when
  final row counts happen to be one.
- A freshly constructed current-interaction Observation never masquerades as
  the existing authoritative Observation on `REPLAY`.

### 6. Failure modes preserved

- Assistant Evidence and wrong-owner Evidence still fail closed with the
  existing `AuthorityError` / `OwnershipError` and the rejected-evidence
  audit rule is preserved (Evidence persisted alone, Observation never
  admitted).

## Rejected Alternatives

- **Validation-layer duplicate detection/suppression.** Rejected: it makes
  first run, replay, and control trajectories tautologically equal and
  certifies a workaround instead of production idempotency. It also created
  two competing identities (`(Scope, Evidence.id)` in validation vs
  `sync.idempotency_key` in the pure invariant). Idempotency ownership never
  moves into `mind_runtime.validation.horizon`, `HorizonRunner`, or any
  Golden adapter — the factual plane owns it exclusively.
- **Suppressing the whole replay Interaction.** Rejected: hides registered
  elapsed-time recovery and weakens the audit trail.
- **Inferring disposition from schedule IDs, Interaction IDs, payload text,
  fixtures, or Dynamics output.** Rejected: none of these are admission
  history; they cannot decide idempotency.
- **Service-cache arbitration (first cache hit wins).** Rejected: stale
  caches over one backend would let two instances both report `NEW` or
  `REPAIRED`; only the backend transaction is authoritative.
- **Repairing an Observation-without-Evidence partial pair.** Rejected: it is
  an impossible partial state under atomic admission; healing it would
  fabricate Evidence history.

## Affected Contracts

Protected categories touched by this ADR (explicitly authorized):

1. **Observation semantics** — the current-turn consumption of a replayed
   Observation changes: replay no longer adds an Observation to the turn.
2. **TurnProjection/commit boundary** — a replay turn projects no new factual
   state and commits no replay-caused State.
3. **EmotionalTransition trace** — replay contributes no event impulse and
   records a non-causal `fact_replay` audit step.
4. **Dynamics** — replay produces no State excitation; registered recovery
   still executes and may produce its registered recovery-caused
   transition/version.

Explicitly unchanged: no State formula, threshold, Persona, Policy,
Expression, Memory, or validation rule changes. `FactIngestPort.admit`'s
return type changes from `Observation` to `FactAdmissionResult` (additive
information; `TurnOrchestrator.ingest`'s signature is unchanged).

## Migration

- No schema change. `SqliteFactBackend` gains an exact stored-entry lookup
  for `(scope, id)` on Evidence and Observation (read-only; the backend stays
  append-only, never a mutable repository).
- Behavior change applies to replay turns only: `NEW` and `REPAIRED` turns
  behave as before (repair now additionally binds original provenance
  identity and `observed_at = Evidence.received_at`).
- Rollback: revert the production W commits; the pre-ADR behavior (replay
  consumes a duplicate Observation) returns.

## Acceptance Tests

- Phase 1 (factual plane): first admission `NEW` + one durable pair; identical
  in-memory replay `REPLAY` with original Observation identity and no store
  growth; identical replay after SQLite restart `REPLAY`; existing
  byte-identical Evidence with missing Observation `REPAIRED` exactly once
  then `REPLAY`; two stale-cache service instances over one backend stay
  idempotent with exactly one winner and exactly one durable pair; assistant /
  wrong-owner fail closed with audit retained; same `(scope, id)` different
  bytes fails closed; impossible partial pairs fail closed atomically.
- Phase 2 (canonical turn): second Interaction with identical Evidence is
  retained for audit; replay adds nothing to `turn.observations`,
  `turn.evidence_refs`, or `factual_overlay`; replay produces no semantic
  candidate, event impulse, Evidence-linked EmotionalTransition contribution,
  replay/event-caused StateTransition, or State version; registered recovery
  still executes in the replay Interaction; repaired Observation consumed once
  and causal once; trace distinguishes `fact_new` / `fact_repaired` /
  `fact_replay`.
- Full gates: focused + full pytest, Ruff, format, strict mypy, 100%
  statement/branch coverage, `git diff --check`, clean worktree; exactly the
  five strict xfails G12/G25/G26/G27/G28.
