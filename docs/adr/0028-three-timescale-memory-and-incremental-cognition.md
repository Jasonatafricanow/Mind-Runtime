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

The target Thread model is therefore minimal: stable identity, open question, status, origin/current bounded support and update time. Full longitudinal history remains in canonical Memory.

## LCE boundary

LCE answers "what has this history already been understood to mean?"

LCE has two legitimate input paths:

### Direct path

When an explicit medium-term structure has already been reasoned online, that reusable structure should be supplied to LCE without waiting for a sleep/idle rediscovery pass.

The direct handoff does not bypass provenance or promotion rules. It avoids duplicate semantic inference while preserving canonical Memory support.

### Discovery path

Unstructured historical Memory may later be processed by LCE in nearline/sleep/idle mode to discover relations that were not explicit online.

Sleep/idle is therefore a discovery opportunity, not a mandatory full-history recomputation pass.

## Worktree / Baseline semantics

LCE's Worktree/Baseline lineage is the durable cognition mechanism.

Conceptually:

```text
canonical Memory history
-> candidate understanding in CognitionWorktree
-> accepted Baseline revision
-> current Baseline HEAD
-> future cognition continues from that HEAD plus new evidence
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

The architecture is frozen ahead of full wiring.

At the time of this ADR:

- canonical MR Memory, retrieval, vector projection and optional LCE binding exist;
- LCE implements Semantic Blocks, CognitionWorktree, Baseline lineage, invalidation and accepted reads;
- MR has initial MemoryAttention and Thread primitives;
- direct explicit-structure -> LCE handoff is not yet implemented;
- MR Thread currently carries a richer appendable event model than the frozen target and should converge toward a bounded open-structure representation;
- compiled LCE Baseline is not yet the primary historical-context path in MR.

These are implementation gaps, not open architecture questions.

## Consequence

Future memory projects should be evaluated by the function they provide—current state, durable memory, retrieval, surfacing, open-line tracking, longitudinal discovery, compiled cognition, or write reliability—rather than used as a reason to invent another memory layer.
