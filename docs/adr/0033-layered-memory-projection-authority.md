# ADR-0033: Layered Memory projections under one Memory authority

- Status: ACCEPTED
- Date: 2026-09-26
- Supersedes: no prior ADR; clarifies ADR-0026 and ADR-0028
- Canonical explanation: `docs/architecture/MEMORY_ARCHITECTURE_V1.md`

## Decision

MR Memory is one logical subsystem with one factual authority and multiple
derived projections.

The storage hierarchy is conceptual rather than a requirement that every
artifact live in one physical database:

```text
raw text / Evidence / Observation
        -> canonical Memory
        -> temporary Thread projection
        -> accepted LCE Baseline projection
```

Canonical Memory is the durable factual substrate. Thread and LCE do not own
copies of factual history. They reference stable canonical Memory identities
and may persist only derived cognition needed for their own lifecycle.

## Thread boundary

Thread is a short-lived online logical projection over canonical Memory.

Its purpose is to retain already-reasoned but not-yet-compiled structure from
normal turns so the same suspected line does not need to be rediscovered from
raw history on every turn.

Thread is not a second medium-term history store and is not a permanent
longitudinal interpretation layer.

Thread maturity is derived authority, not a caller-owned boolean. A Thread
requires canonical support from at least two distinct admitted interaction
identities before it may become mature. Multiple Memory candidates produced
from one interaction still count as one supporting event.

When a mature Thread is successfully compiled into an accepted LCE Baseline,
the higher-level projection supersedes it and MR deletes the temporary Thread
row. Durable lineage remains in LCE's stable `mr-thread:<thread_id>` Baseline
region plus supporting canonical Memory IDs. Canonical Memory and Evidence
remain unchanged.

A failed or unavailable LCE compilation must not roll back factual Memory or
delete the Thread projection.

## LCE boundary

LCE owns stable longitudinal cognition, not factual history.

Path A consumes already-reasoned Thread projections without asking a model to
rediscover the same relation.

Path B performs latent discovery over canonical Memory during sleep/dream
processing for relations that were not formed online. Thread is the normal
online upstream product for explicit logical lines; Path B is not a duplicate
per-Memory online reasoning pass.

Both paths terminate in the same Baseline lineage. They must not create a
second factual substrate.

## Read authority

Consumers outside the Memory subsystem do not independently coordinate raw
Memory, Thread, and LCE stores.

The Memory composition boundary owns historical-context output. It may prefer
accepted Baseline cognition, use active Thread projections where appropriate,
retrieve canonical Memory detail as needed, and descend to Evidence/raw text
only for provenance, contradiction/falsification, rebuild, or retrieval
fallback.

The exact selection/ranking policy remains replaceable. The authority boundary
does not depend on one retrieval algorithm.

## Physical storage

Logical unification does not require physical co-location.

It is valid for canonical Memory, LCE derived artifacts, and vector indexes to
use different physical stores as long as:

- MR canonical Memory remains the sole factual authority;
- derived stores reference stable Memory IDs instead of copying authoritative
  Memory rows;
- projection failure cannot block or roll back factual commit;
- derived projections are rebuildable;
- outside consumers read through the Memory composition boundary rather than
  joining internal stores directly.

This keeps standalone LCE replaceable: LCE Core may use its native substrate in
the research repository and use the MR external-Memory adapter when embedded.

## Consequences

The live logical products are intentionally sparse:

- StateBar: current-state authority outside the durable Memory hierarchy;
- canonical Memory: durable historical facts;
- Thread: temporary unresolved online projection;
- LCE Baseline: accepted compiled longitudinal projection;
- retrieval/vector state: rebuildable indexes.

Once a Baseline covers a mature Thread, maintaining both as active logical
products is forbidden. The system should carry the accepted higher-level
projection forward and retain lower-level facts only as provenance and
fallback.

## 2026-09-28 implementation addendum

The architecture above is now implemented against the current LCE external
projection seam.

Path A no longer bypasses LCE's current draft lifecycle. Mature Threads are
staged as `PrecomputedDraftInput`, persisted as an LCE Worktree, and then
promoted into the shared per-Scope Baseline store without a second model call.

Path B now composes:

```text
MR canonical Memory
  -> read-only grouped canonical source adapter
  -> LCE ProjectionSubstrate
  -> LCE-owned derived projection state
  -> SemanticBlock / vector / Path B trajectory
  -> decentralized evidence convergence
  -> Line / Worktree / Baseline
```

The grouped source adapter preserves MR's factual-support independence rule:
multiple Memory rows from one admitted interaction form one LCE source authority
unit. This prevents extractor fanout from becoming multiple independent support
votes.

No canonical MR Memory row is copied into an LCE Raw Evidence table. LCE's
derived projection database contains no `raw_evidence` table; source reads are
delegated back to MR. Path A and Path B share the same Baseline store but keep
their support representations explicit.

The remaining integration work is to bind the existing sleep/dream lifecycle
to bounded Path B discovery. This is scheduling/composition work, not a missing
authority or cognition algorithm. A generic per-Memory Path B hook is explicitly
not the default production policy because Thread already owns online explicit
structure.

## 2026-09-28 correction boundary clarification

Accepted LCE cognition is durable but not irrevocable.

A Baseline/Line/relation may be historically recorded and later rejected as a
derived reasoning error while its supporting canonical Memory remains factually
valid. The current cognition view must then retire/rebuild the invalid derived
relation and may roll back to the last still-supported structure.

Historical retention and current validity are different authorities:

```text
old cognition remains auditable
    !=
old cognition remains usable now
```

An explicit derived correction belongs to the cognition layer. It must not
delete canonical Memory, and once persisted it should prevent the same unchanged
support from recreating the same rejected relation during later sleep/dream
discovery unless new authorized evidence reopens the question.
