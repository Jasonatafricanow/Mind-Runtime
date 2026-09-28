# Optional MR to LCE binding

MR keeps canonical Memory authority. LCE remains a separately installed
longitudinal-cognition module and owns only derived cognition such as Baseline
revisions. The current integration supports four bounded operations over one factual
authority:

```text
selected MR Memory -> generic LCE Core consolidation

mature MR Thread
  -> PrecomputedDraftInput / LCE Worktree
  -> accepted Baseline
  -> retire active Thread

canonical MR Memory
  -> grouped read-only LCE RawEvidence view
  -> SemanticBlock / vectors / Path B
  -> decentralized evidence convergence
  -> Line / Worktree / Baseline

accepted Path A + Path B Baselines
  -> bounded MR HistoricalContext readback
```

See ADR-0026 and `docs/architecture/MEMORY_ARCHITECTURE_V1.md`.

## Verified optional dependency

The compatibility baseline used by this integration is:

```text
Jasonatafricanow/LCE-Longitudinal-Cognition-Engine
commit aff149256bc6b8323a795c8811bb877356baaa2c
package lce-core 0.1.0
```

LCE is not a default MR dependency and is not vendored. A deployment that
enables the integration should install and verify that source revision, for
example:

```powershell
python -m pip install "git+https://github.com/Jasonatafricanow/LCE-Longitudinal-Cognition-Engine.git@aff149256bc6b8323a795c8811bb877356baaa2c"
```

Disabled composition does not import LCE or initialize its storage.

## Canonical Memory adapter

`MrMemorySubstrateAdapter(binding, authorized_scope, ...)` implements LCE's
external `MemorySubstratePort`.

It accepts 1–100 distinct stable MR Memory IDs and rejects the entire selection
if any ID is unknown, outside the authorized Scope, or not ACTIVE. Scope is
supplied by trusted composition; it is never inferred from the selected IDs.

Returned `MemoryItemView` values use canonical MR content and Evidence
provenance. Provider text, vector UUIDs, similarity scores, embeddings, Thread
summaries and LCE output do not become factual Memory.

## Generic LCE Core path

Use `open_lce_binding` when the caller has deliberately selected canonical
Memory and wants a supplied `SemanticConsolidatorPort` to form or revise a
Baseline:

```python
from mind_runtime.integrations.lce import open_lce_binding

session = open_lce_binding(
    binding,
    authorized_scope,
    enabled=True,
    consolidator=consolidator,
)
assert session is not None

with session:
    result = session.core.consolidate(region_id, memory_ids)
    history = session.core.get_history(region_id)
```

The adapter revalidates every Memory ID before LCE receives it.

## Mature Thread projection upgrade

A mature MR Thread is already an online-reasoned, bounded temporary projection.
Do not send it through another discovery/model pass merely to reconstruct the
same relation.

`open_lce_thread_handoff` performs a no-model handoff:

```python
from mind_runtime.integrations.lce import open_lce_thread_handoff

session = open_lce_thread_handoff(
    binding,
    authorized_scope,
    enabled=True,
)
assert session is not None

with session:
    result = session.handoff_thread(thread)
```

The handoff requires:

- a non-abandoned Thread;
- `mature=True`;
- a non-empty `working_summary`;
- current-valid canonical MR support.

The Thread carries bounded `origin_memory_ids` and
`current_support_ids`. LCE re-resolves those IDs from canonical MR Memory,
stages the already-reasoned summary through its current
`PrecomputedDraftInput -> CognitionWorktree -> Baseline` path, and stores the
accepted cognition under the stable lineage:

```text
mr-thread:<thread_id>
```

Replaying an unchanged mature Thread does not create a new semantic revision.
Thread does not own PROGRESS/REVERSAL history; longitudinal revision authority
belongs to LCE.

The normal Memory composition can wire
`LceThreadProjectionCompiler` into `ThreadAutoUpdateService`. When
`lce_enabled=True`, a mature Thread is compiled after the canonical turn
commit. Once LCE returns an accepted Baseline identity, MR deletes the
temporary Thread projection. The Baseline region and supporting canonical
Memory IDs retain lineage, so no duplicate Thread copy is needed.

If compilation is disabled or fails, the Thread remains available. A derived
projection failure never rolls back canonical Memory.

## Accepted cognition readback

`open_lce_read_binding` exposes current accepted Baseline HEADs without
invoking a model. It returns no session when no LCE Baseline database exists,
so a read-only product path does not create an empty cognition store.

Before an accepted understanding is returned, all supporting MR Memory IDs are
revalidated against canonical Scope/lifecycle state.

The regular history composition can consume this directly:

```python
history = build_memory_history(
    binding,
    provider=retrieval_provider,
    lce_enabled=True,
)
```

When applicable accepted cognition exists, it is placed before ordinary
canonical Memory retrieval inside the same bounded HistoricalContext budget.
Canonical Memory fills remaining capacity. Evidence/raw source text is not a
routine context source; it remains available through provenance for audit,
falsification, rebuild, and fallback.

This is the consumption rule:

```text
accepted compiled understanding
        +
only the raw Memory detail still needed
        ->
current turn context
```

Reading does not reinforce either Memory or cognition.

## Path B latent projection over MR canonical Memory

`open_lce_projection_binding` binds the current LCE projection runtime without
creating a second factual store.

The source side is `MrLceCanonicalSourceAdapter`. It exposes canonical MR
Memory as read-only grouped LCE `RawEvidence` views. Several Memory rows
extracted from the same admitted interaction remain **one** source authority
unit, so one turn cannot manufacture several independent votes in LCE's
decentralized convergence layer.

The projection side is LCE-owned:

```text
MR canonical Memory / Fact provenance
        |
        v
read-only grouped source adapter
        |
        v
ProjectionSubstrate
        |
        +--> LCE Semantic Blocks
        +--> vectors / snapshots
        +--> Path B Lines / authority ledger
        +--> Worktrees / Baselines
```

The derived SQLite projection store contains no `raw_evidence` table. Source
content, lifecycle and Scope remain MR-owned.

Current LCE Path B preserves the authority split:

```text
similarity / mutual-kNN = candidate proposal
Raw-grounded convergence = persistent identity authority
```

Repeated derived views cannot create new factual support. Transitively
overlapping Raw closures collapse into one evidence component; candidate
profiles remain multidimensional and Pareto-incomparable candidates stay
`UNRESOLVED`.

Example:

```python
from mind_runtime.integrations.lce_projection import (
    open_lce_projection_binding,
)

session = open_lce_projection_binding(
    binding,
    authorized_scope,
    enabled=True,
)
assert session is not None

with session:
    session.sync_all()                 # slow/batch catch-up
    # or:
    session.sync_memory_ids(ids)       # nearline new canonical Memory
    session.bootstrap_trajectory(
        knowledge_cutoff=cutoff,
    )
```

Scheduling remains a composition policy. Binding Path B does not require MR to
run a nightly full-history recomputation.

## Persistence and restart

Per-Scope LCE derived cognition remains physically separate from MR canonical
Memory:

```text
<runtime namespace>/memory.sqlite
<runtime namespace>/lce/<scope-hash>/
    baselines/lce_baselines.sqlite
    worktrees/
    projection_state/projection_state.sqlite
    lines/
    structures/
    authority/
```

The Scope digest is deployment addressing, not a cognitive identity. Reopening
the same Runtime and Scope restores the same Baseline HEAD/history.

## Relation to standalone LCE

MR still does not vendor LCE or copy canonical Memory into LCE's standalone
`ReferenceMemoryStore`.

Instead it now uses LCE's explicit external-source architecture:

```text
CanonicalEvidenceSourcePort -> MR read-only source adapter
DerivedProjectionStatePort  -> LCE-owned SQLite projection state
ProjectionSubstrate         -> composition between them
LceProjectionCore           -> current Path B runtime
```

The same LCE algorithms can therefore run standalone or embedded while factual
ownership changes only at the source adapter boundary.

The mature-Thread path remains separate because its semantic relation has
already been reasoned online; forcing it through latent discovery would pay the
same inference cost twice. Both Path A and Path B use the same per-Scope
Baseline store and outward accepted-cognition read boundary.

## Verification

MR's integration tests cover:

- canonical content/provenance mapping;
- Scope and lifecycle rejection;
- durable Baseline restart;
- no reverse MR authority;
- mature Thread handoff through current LCE draft lineage and replay;
- grouped Path B source authority (one interaction cannot multiply votes);
- derived-only Path B persistence with no copied Raw Evidence table;
- Path B restart/replay over canonical MR Memory;
- accepted cognition readback across Path A and Path B;
- default-OFF/no-dependency behavior.

Run:

```bash
python -m pytest tests/lce_binding tests/memory_retrieval -q
```

The full MR CI additionally runs clean-install, Ruff-baseline, mypy and the
complete pytest/coverage suite.

## Activation boundary

LCE remains opt-in. `default_adapter(..., lce_enabled=False)` is the default.

Thread formation/maturity remains a bounded online projection policy; its
future wake-up, capacity and TTL refinements are recorded separately.
Idle/sleep/dream **scheduling policy** remains deferred, but the latent Path B
runtime it would invoke is now bound.

Enabling either path does not grant LCE factual write authority. LCE may persist
derived cognition and rebuildable projection state only.
