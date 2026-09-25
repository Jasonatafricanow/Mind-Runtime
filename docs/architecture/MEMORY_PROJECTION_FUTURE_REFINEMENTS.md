# Memory Projection Future Refinements

Status: deferred implementation plan  
Date: 2026-09-26  
Depends on: ADR-0033

This document records implementation refinements that are intentionally not
required to close the current Memory projection framework.

The architecture is already fixed:

```text
canonical Memory
    -> temporary Thread projection
    -> accepted LCE Baseline projection

unstructured canonical Memory
    -> future idle/sleep/dream LCE discovery
    -> Worktree
    -> accepted LCE Baseline
```

The items below tune efficiency and recall. They do not redefine ownership.

## 1. Thread wake-up quality

Before selecting a permanent matching strategy, build an executable benchmark
for end-to-end Thread wake-up.

Measure separately:

- semantic signal recall: did the turn propose that an existing line may have
  changed?
- retrieval recall@K: did the correct active Thread enter the candidate set?
- assignment accuracy: was the correct candidate selected?
- false-merge rate: was an unrelated event incorrectly attached to a Thread?

Candidate retrieval may later combine lexical, embedding, entity/topic, and
recency signals. No one provider becomes authority.

Do not tune a single lexical threshold and treat it as architecture.

## 2. Thread active-set size and expiry

Do not freeze an arbitrary capacity or TTL before lifecycle telemetry exists.

Collect:

- concurrent active Thread count distribution;
- time from Thread creation to next independent support;
- time from creation to compilation;
- percentage of Threads that never receive new support;
- percentage later recovered from Memory/LCE after expiry.

Use those distributions to set active-set bounds and inactivity expiry.

Expiry removes only the temporary Thread projection. Canonical Memory remains.

## 3. Context exposure budget

Thread existence does not imply prompt inclusion.

Future context policy should keep total stored Threads separate from the number
of Threads exposed to one model call. A cheap candidate stage should select a
very small relevant set, if any.

The Memory composition boundary remains the only outward historical-context
authority.

## 4. Idle / sleep / dream LCE discovery

Implement the already-frozen Path B scheduler as a separate discovery policy.

Its job is to choose bounded neighborhoods of canonical Memory that have not
already been adequately represented by accepted Baselines or recently compiled
Thread projections.

Candidate neighborhood construction may use temporal adjacency, semantic
similarity, shared entities/domains, and existing derived topology.

The scheduler must avoid full-history recomputation and must not recreate a
second factual Memory store.

## 5. Raw Evidence fallback and falsification

Normal cognition should prefer higher-level accepted projections and canonical
Memory.

Evidence/raw text should be read when needed for:

- provenance audit;
- contradiction or falsification of a projection;
- extraction/rebuild;
- retrieval fallback;
- migration/recovery.

A future falsification path should be able to trace:

```text
Baseline
-> supporting Memory IDs
-> Observation / Evidence
-> original source payload
```

without turning raw history into routine prompt context.

## 6. LCE replaceability

Keep LCE Core substrate-agnostic.

Standalone research may continue to use LCE-native source stores. Embedded MR
composition must replace factual source ownership with the MR
`MemorySubstratePort` while preserving LCE-owned derived artifacts.

Upgrade acceptance should be based on adapter compatibility and contract tests,
not manual copying or synchronization of Memory content.

## Non-goals

This plan does not authorize:

- a permanent Thread history;
- a second factual LCE Memory store inside MR;
- all open Threads being inserted into every prompt;
- fixed TTL/capacity values without evidence;
- mandatory full-history sleep passes;
- topology or vector indexes becoming factual authority.
