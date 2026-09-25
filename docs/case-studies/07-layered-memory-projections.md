# One Memory Subsystem, Multiple Projection Levels

## Context

The memory stack originally risked being described as three cooperating
systems: canonical Memory, Thread, and LCE. That framing was operationally
tempting because each component has different code and may use different
persistence.

It was also misleading.

The same historical assets were being interpreted at different levels of
abstraction. Treating those levels as independent stores would create
synchronization work and make the same logical relation live in more than one
place.

## Failure / Limitation

Consider an online sequence:

```text
want to replace a computer
-> price is too high
-> postpone the purchase
```

The turn-time model has already paid the inference cost to notice that these
events belong together.

If Thread keeps that relation indefinitely while LCE later rebuilds the same
logic from raw Memory, the system maintains two logical products and pays for
the same reasoning twice.

The opposite failure is to push every weak clue directly into LCE, making the
longitudinal layer responsible for tentative short-range continuity.

## Decision

MR now treats durable memory as one logical subsystem with layered projections:

```text
raw source / Evidence / Observation
        -> canonical Memory
        -> temporary Thread projection
        -> accepted LCE Baseline projection
```

Canonical Memory remains the factual substrate.

Thread is a temporary cache for already-reasoned online structure that may
still develop. It is allowed to disappear without deleting history.

LCE Baseline is the stable compiled representation. Once a mature Thread is
successfully compiled into an accepted Baseline, MR deletes the temporary
Thread projection. LCE's stable region identity and supporting Memory IDs keep
lineage, so the same logical product is not stored twice.

Unstructured history follows a separate path:

```text
canonical Memory
-> future idle / sleep / dream topology discovery
-> LCE Worktree
-> accepted Baseline
```

Both paths converge on the same Baseline concept.

## Engineering Shape

Logical unification does not mean one physical database.

MR may keep canonical Memory in SQLite, LCE Baselines in a separate derived
store, and vectors in another index. The invariant is that only canonical
Memory owns factual history. Higher layers reference stable Memory IDs and are
rebuildable.

This also makes LCE replaceable. The standalone LCE project can evolve its own
research substrate, topology and compilation algorithms. Embedded MR uses the
same LCE Core with an external Memory adapter instead of copying factual
history.

The outward boundary is similarly singular: host/model code asks the Memory
composition layer for historical context. It does not coordinate Memory,
Thread and LCE stores itself.

## Why This Matters

The design reduces repeated inference in two directions.

Online continuity reuses Thread output instead of repeatedly waking LCE to
compare every tentative clue against history.

Offline LCE work can spend its budget on the harder problem: discovering
relations that online reasoning never made explicit.

The result is a sparse hierarchy: raw history stays available for provenance,
falsification and fallback; temporary logic disappears when unused or
compiled; accepted Baselines carry forward the logic that is worth retaining.

## Evidence

- [Memory Architecture V1](../architecture/MEMORY_ARCHITECTURE_V1.md)
- [Layered Memory projection authority](../adr/0033-layered-memory-projection-authority.md)
- [Three-timescale Memory ADR](../adr/0028-three-timescale-memory-and-incremental-cognition.md)
- [Optional LCE substrate binding](../adr/0026-optional-lce-memory-substrate-binding.md)
- [Deferred projection refinements](../architecture/MEMORY_PROJECTION_FUTURE_REFINEMENTS.md)

## Current Status

The production framework supports automatic mature-Thread compilation when LCE
is explicitly enabled. Accepted Baseline identity retires the lower-level
Thread from the active working set; failed/disabled compilation leaves it
intact. The outward Memory history composer can also surface one bounded,
currently relevant active Thread projection without exposing the whole Thread
working set.

Thread wake-up quality, expiry/capacity policy, context exposure policy, and
idle/sleep/dream discovery scheduling are intentionally deferred refinements,
not unresolved ownership questions.
