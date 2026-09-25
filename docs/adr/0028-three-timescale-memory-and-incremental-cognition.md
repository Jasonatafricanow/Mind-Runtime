# ADR-0028: Three-timescale memory ownership and incremental cognition

- Status: ACCEPTED
- Date: 2026-09-25
- Canonical explanation: `docs/architecture/MEMORY_ARCHITECTURE_V1.md`
- Base decisions: ADR-0023 through ADR-0026 remain in force.

## Decision

The memory stack is one closed loop with three cognitive timescales, not three competing memory databases.

1. **StateBar owns explicit short-lived current state.**
2. **MR Memory owns durable remembered history plus bounded explicit medium-term open structures.**
3. **LCE owns longitudinal compiled cognition over those historical assets.**

The key runtime principle is incremental reasoning:

> once a relation has already been validly reasoned and represented as accepted cognition, later processing continues from that result instead of recomputing the same logic from raw Memory.

## StateBar boundary

StateBar answers "what still holds now?"

Semantic expiry means a state is no longer current. MR must not duplicate StateBar as a second short-term TODO/state engine.

If a StateBar event later deserves durable remembrance, it enters the normal Evidence -> Observation -> Memory path.

## MR Memory boundary

Canonical Memory answers "what happened?"

Memory product state may govern foreground visibility, explicit reinforcement and whether an explicit medium-horizon line is still open. Those derived objects do not gain factual authority.

Memory decay changes foreground attention, not historical truth.

Retrieval is read-only and is not reinforcement.

An explicit open structure/Thread is a bounded product object over canonical Memory support. It is not a second history store and it is not the longitudinal interpretation engine.

The target Thread model is therefore bounded: stable identity, open question, status, origin/current bounded support, optional already-reasoned working summary, explicit maturity, and update time. Full longitudinal history remains in canonical Memory.

## LCE boundary

LCE answers "what has this history already been understood to mean?"

LCE has two legitimate input paths:

### Direct path

When an explicit medium-term structure has already been reasoned online, that reusable structure should be supplied to LCE without waiting for a sleep/idle rediscovery pass.

The direct handoff does not bypass provenance or canonical-support validation. A
mature Thread has already completed the explicit online working-structure stage,
so the handoff must not create a second Worktree merely to rediscover the same
relation. MR supplies the already-reasoned summary and stable Memory support;
LCE revalidates support and advances the Baseline lineage only when its
equivalence/revision rules permit it.

### Discovery path

Unstructured historical Memory may later be processed by LCE in nearline/sleep/idle mode to discover relations that were not explicit online.

Sleep/idle is therefore a discovery opportunity, not a mandatory full-history recomputation pass.

## Worktree / Baseline semantics

LCE Baseline lineage is the durable accepted-cognition mechanism. Worktree is
the draft/confirmation mechanism for relations discovered inside LCE. A mature
MR Thread is already the bounded draft structure for the explicit online path.

Conceptually:

```text
latent/unstructured history
-> candidate understanding in LCE Worktree
-> accepted Baseline revision

already-reasoned mature Thread
-> canonical support revalidation
-> accepted Baseline revision

Baseline HEAD + new evidence
-> future cognition
```

A later branch starts from the current accepted understanding. Settled history does not need to be semantically rebuilt on every turn.

## Surfacing

Ordinary semantic retrieval remains useful for supporting Memory.

However, where an applicable accepted LCE Baseline already exists, the preferred historical context is the compiled current understanding plus only the raw Memory details needed for the current turn.

A single vector rank or age-decay score must not replace an already-compiled longitudinal logic line.

## Authority

- StateBar extraction/model output cannot directly authorize canonical current state.
- Memory extractor/provider output cannot directly authorize canonical Memory.
- retrieval/provider rank cannot become factual authority or reinforcement.
- Thread state cannot become Evidence.
- Worktree is draft cognition.
- Baseline is accepted derived cognition, not factual Evidence.
- repeated reading or model repetition cannot self-authorize.
- explicit user correction has authority over model interpretation of the user's own subjective meaning.

## No second memory store or parallel bus

MR canonical Memory remains the shared durable asset substrate.

LCE may persist derived Semantic Blocks, Worktrees, Baseline revisions and indexes, but those are cognition artifacts rather than a second factual Memory authority.

Thread does not require a parallel MR-to-LCE transport ontology. Stable canonical Memory identities and provenance remain the support seam.

## Current implementation note

The architecture is frozen and the explicit online loop is now wired:

- canonical MR Memory, hybrid retrieval, vector projection and optional LCE binding exist;
- Thread is bounded and no longer carries PROGRESS/REVERSAL or append-only trajectory history;
- mature Thread -> LCE Baseline handoff is implemented without a second semantic-model pass;
- accepted LCE Baselines can be preferred in MR HistoricalContext, with raw Memory filling the remaining bounded budget;
- LCE standalone V1 still owns Semantic Blocks, local structure discovery, Worktrees, invalidation and accepted reads for its latent-discovery path.

Automatic Thread maintenance is now part of the committed turn path. It
reuses the accepted semantic event already produced for that turn, resolves its
references back to ACTIVE canonical Memory, and updates the bounded Thread only
after successful turn commit. No second model call is introduced for Thread
classification, and an aborted/replayed turn does not create a second update.

The production latent-discovery seam now keeps MR as the sole factual source:
LCE receives canonical Memory views plus a bounded MR-owned temporal context.
Evidence/source chronology is kept distinct from proposition-valid
semantic/effective time, and historical cutoffs are based on when MR could know
the Memory rather than whether a proposition was PAST or FUTURE.

Autonomous idle/nearline neighborhood discovery remains an optional scheduling
policy, not a missing factual or temporal authority path.

## Consequence

Future memory projects should be evaluated by the function they provide—current state, durable memory, retrieval, surfacing, open-line tracking, longitudinal discovery, compiled cognition, or write reliability—rather than used as a reason to invent another memory layer.
