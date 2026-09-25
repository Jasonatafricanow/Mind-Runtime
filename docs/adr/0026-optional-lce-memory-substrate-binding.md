# ADR-0026: Optional LCE binding over canonical MR Memory

Status: Accepted; compatibility refreshed 2026-09-25

## Authority

MR canonical Memory is the factual authority. LCE owns derived longitudinal
cognition only: Baseline revisions and, in standalone V1, its Semantic Block /
structure / draft-cognition pipeline.

The MR adapter is verified against the current LCE source compatibility baseline:

```text
Jasonatafricanow/LCE-Longitudinal-Cognition-Engine
5894a2334943d9a12310992fedcc1932a473b3d2
lce-core 0.1.0
```

MR does not vendor LCE and does not allow LCE output to become Evidence,
Observation, Memory, State, Intent, Appraisal, Action, or reinforcement merely
because it was generated or repeatedly read.

## Canonical Memory read contract

`MrMemorySubstrateAdapter` implements LCE's external `MemorySubstratePort`.
The adapter accepts an explicit tuple of 1 to 100 distinct stable MR Memory IDs
and one composition-authorized structured Scope.

Every read:

- re-verifies the Runtime binding manifest;
- reads only the bound Runtime's canonical `memory.sqlite`;
- rejects the entire selection if any Memory is missing, outside Scope, or not
  ACTIVE;
- preserves stable Memory IDs and canonical content/provenance;
- exposes immutable empty retrieval metadata for explicit-ID reads.

Provider UUIDs, vector payload text, rankings, embeddings, Thread summaries and
LCE Baselines never replace canonical Memory content.

## Two explicit LCE paths

### Generic external-Memory consolidation

`open_lce_binding(..., consolidator=...)` preserves the original contract-first
LCE Core path:

```text
selected MR Memory IDs
-> canonical revalidation
-> caller-supplied SemanticConsolidatorPort
-> LCE Baseline revision
```

This remains useful when the caller deliberately wants LCE Core to reason over
an already-selected Memory set.

### Mature Thread handoff

`open_lce_thread_handoff(...)` is the no-model path for structure that was
already reasoned during normal interaction.

A mature Thread contains only:

```text
open question
bounded origin/current Memory support
already-reasoned working summary
maturity flag
```

It does not contain an append-only trajectory history and does not classify
PROGRESS/REVERSAL. The handoff revalidates every supporting MR Memory ID, then
supplies the existing Thread summary to LCE Core as a precomputed candidate.

The stable LCE lineage is:

```text
mr-thread:<thread_id>
```

Replaying the same mature Thread is subject to LCE's normalized semantic
equivalence and does not manufacture a new Baseline revision.

For this path the Thread itself is the upstream explicit working structure.
Creating another LCE Worktree only to rediscover the same already-formed
structure would duplicate reasoning. LCE Worktrees remain the draft/confirmation
mechanism for LCE's latent-discovery path.

## Accepted cognition readback

`open_lce_read_binding(...)` reads accepted Baseline HEADs without invoking a
model. Each Baseline's supporting MR Memory IDs are revalidated before the
understanding can be served.

When `build_memory_history(..., lce_enabled=True)` is used, applicable accepted
LCE cognition is placed ahead of ordinary raw Memory retrieval inside the same
bounded HistoricalContext budget. Raw Memory fills remaining capacity.

This implements the runtime rule:

> reuse accepted longitudinal understanding first; retrieve raw historical
> detail only as needed.

No read operation reinforces Memory or LCE support.

## Persistence and Scope isolation

LCE Baselines remain physically separate from canonical MR Memory:

```text
<runtime namespace>/memory.sqlite
<runtime namespace>/lce/<sha256(full structured Scope JSON)>/lce_baselines.sqlite
```

The Scope digest is deployment addressing only. It is not cognition, region
identity, or a second Scope ontology.

## Standalone LCE V1 boundary

Current LCE standalone V1 also contains:

```text
Raw Evidence
-> Semantic Block compiler
-> vector projection
-> cutoff snapshots
-> overlapping structure discovery
-> relation candidate
-> DraftRevision / Worktree
-> Baseline
-> accepted Understanding read
-> invalidation / rebuild / recovery
```

MR does **not** currently instantiate that full standalone runtime over copied
MR Memory. LCE's standalone `ReferenceMemoryStore` combines source-evidence and
derived-storage roles; copying canonical MR Memory into it would create a
second factual substrate.

A future latent-discovery integration must split:

```text
factual source / validity -> MR canonical Memory
derived Semantic Blocks / vectors / snapshots / drafts -> LCE-owned storage
```

before enabling the full V1 discovery path in MR production composition.

## Activation boundary

All LCE composition remains default OFF. Disabled composition performs no LCE
import and no LCE filesystem initialization.

Automatic Thread opening/maturity policy and full latent-discovery scheduling
remain separate product work. The presence of this adapter does not claim that
general-purpose longitudinal cognition is solved.
