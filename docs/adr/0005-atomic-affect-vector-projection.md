# ADR-0005: Commit one emotional transition as an atomic affect vector

- **Date:** 2026-08-22
- **Status:** Accepted for D8 implementation

## Problem

ADR-0004 compressed the cognitive path into one deterministic emotional
transition. D7R correctly records the complete `DynamicsEngine.state_after`
vector in `AssessmentTrace`, but the migrated `ProjectedMindState` still owns
only one `RuntimeState`. `EngineEmotionalTransitionPort` consequently selects
`result.proposed[0]` for projection and commit.

That mismatch becomes a correctness failure as soon as D8 applies a typed
event. A cancellation can update `agent.affect.anxiety` while the first Persona
dimension is `agent.affect.longing`; the trace reports the anxiety transition,
but commit silently keeps only longing. Recovery and coupling changes to other
dimensions are lost in the same way.

## Previous Assumption

The D1/D5 single-state projection envelope was sufficient while the walking
skeleton projected one stub dimension. D7R preserved it to keep the topology
migration bounded before real D8 event effects existed.

## New Evidence

- `DynamicsEngine.step` returns every configured Persona dimension.
- D7 coupling can change a second dimension during the same engine step.
- D8 must integrate elapsed-time recovery and event effects exactly once.
- A trace that contains uncommittable state is not a trustworthy causal record.

## Decision

One D8 emotional transition produces one non-empty, immutable affect vector:

```text
ProjectedMindState {
    projection_id
    scope
    projected_states: tuple[RuntimeState, ...]
    committed
}
```

Every member has the same projection Scope and a unique dimension. The vector
is ordered by the fixed Persona profile so replay is stable. D5 validates
staleness once and then commits or aborts the complete vector. Durable state
and any materialized `TransitionIntent` records are written for every member;
partial success is forbidden.

`EmotionalTransitionInput.current_affect` carries the immutable current
`RuntimeState` records, not detached `(dimension, value)` pairs. The engine
still receives a numeric mapping, while the transition port retains the exact
per-dimension version and `updated_at` lineage required to compute elapsed time
and create the next durable version deterministically.

Agent-owned transition intents may use the exact agent/persona projection
Scope. `TurnProjection` accepts that exception only when the intent Scope
equals the vector Scope. Other cross-Scope intents remain invalid.

`AssessmentTrace.state_after` must equal the projected vector values exactly.
Rejected semantic candidates remain trace contributions with `applied=false`;
they never enter the vector as an affect impulse.

## Preserved Boundaries

- Projected State is not Canonical State.
- Ingest-committed factual state still survives cognitive abort.
- Optimistic staleness validation, checkpoint, receipt, reconcile, and replay
  semantics remain D5-owned.
- Persona traits remain separate from current affect.
- Scope and Ownership checks remain fail closed.
- ActionPolicy and Intent lifecycle remain outside this ADR and outside D8.

## Rejected Alternatives

### Commit only the primary event dimension

Rejected because elapsed recovery and coupling can legitimately update other
dimensions. Silently dropping those changes makes replay depend on which
dimension happened to be selected.

### Create one independently committable projection per dimension

Rejected because a crash or conflict could commit half of one emotional step.
The causal trace would then describe a state that never existed canonically.

### Store the whole vector as an opaque value in one RuntimeState

Rejected because it discards the existing per-dimension State lineage,
validation, query, and configuration boundaries.

## Migration

Replace the singular `projected_state` field with `projected_states`. Existing
walking-skeleton stubs emit a one-element vector. Replace detached
`current_affect` values with current `RuntimeState` records. The migration
occurs before D8 production mappings or production data exist, so no stored
canonical data rewrite is required.

## Acceptance Tests

- Empty, duplicate-dimension, or mixed-Scope vectors fail closed.
- Two projected affect dimensions commit and persist together.
- Aborting the same vector changes neither canonical dimension.
- Coupled/recovered state recorded in the trace is present in the projection.
- D3-D7 regression, replay, checkpoint, receipt, replication, static, and
  coverage gates remain green.
