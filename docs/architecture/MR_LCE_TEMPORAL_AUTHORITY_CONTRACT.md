# MR -> LCE Temporal Authority Contract

Status: production binding contract

## Purpose

LCE may consume MR temporal authority, but it may not reconstruct or invent time
that MR already owns. The transport is read-only and grants no write authority
over MR Memory, Evidence, Observation, State, or Thread.

## Two time axes

Knowledge/source chronology preserves Evidence source occurrence, Evidence
receipt, source Observation time, and canonical Memory commit time.

Proposition-valid time remains owned by Reality Observation semantic time and
effective windows.

Evidence source occurrence is not renamed to proposition event time and is
never used to fabricate an effective interval.

A Memory may be supported by more than one Reality Observation. The binding
therefore transports a bounded tuple of proposition views rather than
collapsing them into one guessed timestamp or interval.

## Historical cutoff

A selected Memory is visible at cutoff Tc only if MR knowledge is available by
Tc. The cutoff uses received/observed/commit chronology.

A FUTURE proposition already known before Tc remains visible before its
effective window begins. A late-arriving fact about an earlier date is not
backdated into a cutoff before MR received and committed it.

Unknown temporal fields remain unknown.

## Path A

Mature Thread -> LCE Baseline remains a precomputed no-model handoff. Temporal
binding does not cause relation rediscovery.

## Path B

MR injects the reserved context key mr.temporal_memory_views.v1 into the
existing LCE consolidator context while LCE still receives canonical
MemoryItemView objects from MR. The context contains only MR-authoritative read
views; LCE owns derived cognition, not a second factual store.

## Failure behavior

The binding fails closed when selected Memory is unavailable or out of Scope,
its source Observation or Evidence cannot be resolved, provenance disagrees,
temporal Observation fanout exceeds the bounded limit, a cutoff predates
knowledge availability, or a caller attempts to spoof the reserved context.
