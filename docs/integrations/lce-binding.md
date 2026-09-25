# Optional MR to LCE binding

MR keeps canonical Memory authority. LCE remains a separately installed
longitudinal-cognition module and owns only derived cognition such as Baseline
revisions. The current integration supports three distinct paths:

```text
selected MR Memory -> LCE Core consolidation
mature MR Thread   -> no-model LCE Baseline handoff
accepted Baseline  -> bounded MR HistoricalContext readback
```

See ADR-0026 and `docs/architecture/MEMORY_ARCHITECTURE_V1.md`.

## Verified optional dependency

The compatibility baseline used by this integration is:

```text
Jasonatafricanow/LCE-Longitudinal-Cognition-Engine
commit 5894a2334943d9a12310992fedcc1932a473b3d2
package lce-core 0.1.0
```

LCE is not a default MR dependency and is not vendored. A deployment that
enables the integration should install and verify that source revision, for
example:

```powershell
python -m pip install "git+https://github.com/Jasonatafricanow/LCE-Longitudinal-Cognition-Engine.git@5894a2334943d9a12310992fedcc1932a473b3d2"
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

## Mature Thread handoff

A mature MR Thread is already an online-reasoned, bounded medium-term working
structure. Do not send it through another discovery/model pass merely to
reconstruct the same relation.

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
`current_support_ids`. LCE re-resolves those IDs from canonical MR Memory and
stores the accepted cognition under the stable lineage:

```text
mr-thread:<thread_id>
```

Replaying an unchanged mature Thread does not create a new semantic revision.
Thread does not own PROGRESS/REVERSAL history; longitudinal revision authority
belongs to LCE.

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

When applicable accepted cognition exists, it is placed before raw Memory
retrieval inside the same bounded HistoricalContext budget. Raw Memory fills
remaining capacity.

This is the consumption rule:

```text
accepted compiled understanding
        +
only the raw Memory detail still needed
        ->
current turn context
```

Reading does not reinforce either Memory or cognition.

## Persistence and restart

Per-Scope LCE Baselines remain physically separate from MR canonical Memory:

```text
<runtime namespace>/memory.sqlite
<runtime namespace>/lce/<sha256(full structured Scope JSON)>/lce_baselines.sqlite
```

The Scope digest is deployment addressing, not a cognitive identity. Reopening
the same Runtime and Scope restores the same Baseline HEAD/history.

## Relation to standalone LCE V1

The current LCE repository also includes a standalone V1 pipeline:

```text
Raw Evidence
-> Semantic Block
-> vector projection
-> cutoff snapshots
-> overlapping structure discovery
-> relation candidate
-> DraftRevision / Worktree
-> Baseline
-> AcceptedUnderstandingReadAPI
```

MR does not currently copy canonical Memory into LCE's standalone
`ReferenceMemoryStore`. That store owns both source evidence and derived
artifacts for standalone operation; duplicating MR facts there would create a
second factual authority.

A future latent-discovery adapter must keep the ownership split:

```text
source content / validity
    -> MR canonical Memory

Semantic Blocks / vectors / snapshots / drafts
    -> LCE-owned derived storage
```

The mature-Thread path does not need that discovery pipeline because the
structure was already formed online.

## Verification

MR's integration tests cover:

- canonical content/provenance mapping;
- Scope and lifecycle rejection;
- durable Baseline restart;
- no reverse MR authority;
- mature Thread handoff and replay;
- accepted cognition readback;
- default-OFF/no-dependency behavior.

Run:

```bash
python -m pytest tests/lce_binding tests/memory_retrieval -q
```

The full MR CI additionally runs clean-install, Ruff-baseline, mypy and the
complete pytest/coverage suite.

## Activation boundary

LCE remains opt-in. `default_adapter(..., lce_enabled=False)` is the default.

Automatic Thread formation/maturity policy and full latent-discovery scheduling
are separate runtime work. Enabling the binding does not grant LCE factual
write authority and does not claim that general longitudinal cognition is a
solved problem.
