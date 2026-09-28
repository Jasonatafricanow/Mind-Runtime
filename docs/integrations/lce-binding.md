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

sleep/daydream/dream LCE discovery
  -> opaque Inspiration Material
  -> proactive-consumer candidate
```

See ADR-0026 and `docs/architecture/MEMORY_ARCHITECTURE_V1.md`.

## Verified optional dependency

The compatibility baseline used by this integration is:

```text
Jasonatafricanow/LCE-Longitudinal-Cognition-Engine
commit 9edf4eb94c4eaef5b833b0f608f0895a58e05230
package lce-core 0.1.0
```

LCE is not a default MR dependency and is not vendored. A deployment that
enables the integration should install and verify that source revision, for
example:

```powershell
python -m pip install "git+https://github.com/Jasonatafricanow/LCE-Longitudinal-Cognition-Engine.git@9edf4eb94c4eaef5b833b0f608f0895a58e05230"
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

MR currently exposes canonical Memory's **current** lifecycle state but does not
persist a general timestamped Memory-lifecycle transition ledger. The external
source adapter therefore intentionally does not fabricate an
`evidence_valid_at(cutoff)` history. LCE's `ProjectionSubstrate` uses its
documented conservative current-state fallback for historical source validity.
`known_at` and logical occurrence remain explicit; exact replay of a past
Memory validity transition requires future MR lifecycle-history authority.

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
    # sleep/dream latent-discovery pass
    session.sync_all()
    session.bootstrap_trajectory(
        knowledge_cutoff=cutoff,
    )
```

The default production role is **sleep/dream latent discovery**, not
"every new Memory -> Path B". Online explicit logical structure is already
owned by Thread and reaches LCE through Path A.

`sync_memory_ids(...)` remains available for explicit repair, replay,
laboratory work and bounded operator-driven catch-up. Its existence does not
make per-Memory Path B processing the default MR production scheduler.

The sleep/dream scheduler should select bounded unresolved material and avoid a
nightly full-history recomputation.

## Inspiration Material downstream seam

Current LCE also exposes a proactive-consumption product distinct from accepted
historical understanding.

MR intentionally preserves the narrow LCE public seam:

```text
LceInspirationMaterial {
    material_id
    content
}
```

The MR adapter does **not** expose:

- association vs extension kind;
- Line or branch identity;
- SemanticBlock IDs;
- Raw-Evidence closure;
- convergence profiles;
- interpreter traces.

Those remain LCE implementation details.

A sleep/daydream/dream worker may use the projection session as:

```python
trajectory = session.bootstrap_trajectory(
    knowledge_cutoff=cutoff,
)
session.discover_inspiration(
    knowledge_cutoff=cutoff,
    trajectory_result=trajectory,
)

materials = session.inspiration_materials(limit=4)
```

The first discovery family is a cautious possible association: several existing
observations may be related and are offered as reflection material rather than
accepted fact.

The second family takes an already-supported Line prefix such as
`A -> B -> C` and asks an injected bounded inspiration interpreter for a
speculative `D?`. LCE itself keeps the supported prefix and speculative
extension separate before compiling them into self-contained material.

After a downstream proactive consumer uses or discards the item, it can call
`consume_inspiration(material_id)` or `dismiss_inspiration(material_id)`.
The opaque ID is enough; the consumer never needs LCE topology/provenance.

This seam provides **message material**, not send authority. Persona initiative,
Intent scheduling, ActionPolicy, cooldowns and final Body wording remain outside
LCE.

## Automatic background Inspiration wiring

MR now has a bounded background worker around the LCE projection session:

```text
canonical MR Memory
    -> LceInspirationBackgroundWorker
    -> sync only canonical Memory IDs not yet checkpointed
    -> DAYDREAM / DREAM Path-B discovery
    -> LCE Inspiration queue
```

The worker persists only execution progress in
`background_inspiration.sqlite`; factual authority remains canonical MR
Memory and derived cognition remains in LCE stores.

An explicitly enabled cognitive tick runs the background pass before the normal
proactive Intent evaluation:

```text
scheduled cognitive tick
    -> background LCE pass (DAYDREAM by default; DREAM may be selected explicitly)
    -> pending InspirationMaterial
    -> normal IntentEngine
    -> Persona initiative admission where the Intent rule requires it
    -> ActionPolicy
    -> WakeSignal
```

Only Intent kinds that already carry `minimum_initiative` are eligible to
reserve Inspiration Material in the production composition. This preserves the
existing authority direction: the material can supply **what to think/say
about**, but it cannot manufacture the desire or permission to contact the
user.

Once a proactive Wake has passed policy, the ticker may reserve one material
and place only the public two-field object into the authoritative wake context:

```text
material_id
content
```

The DecisionContext compiler converts it to an essential
`INSPIRATION` context item. The provider renderer treats it as
`UNTRUSTED_DATA`; internal Line/branch/provenance state remains hidden.

Lifecycle is tied to the existing proactive delivery path:

```text
Guard REJECT      -> release reservation
delivery ABORT    -> release reservation
REWRITE           -> keep reservation for the same wake
delivery COMMIT   -> consume Inspiration Material
```

A successful external delivery is therefore the consumption boundary. Merely
discovering, reserving, rendering, or guarding the material does not consume it.

The worker is incremental. It checkpoints processed canonical Memory IDs and
does not run a full Path-B bootstrap on every clock tick when neither canonical
Memory nor the discovery version changed. Background derived-cognition failures
are fail-soft relative to the existing proactive ticker; they do not roll back
canonical Memory or create alternate factual state.

The production Xiyue composition remains opt-in. Setting
`MR_LCE_INSPIRATION_ENABLED=true` enables the Inspiration binding and also
requires/enables the underlying Memory and LCE composition. The feature still
depends on the existing proactive cognitive-tick scheduler; it does not create
a second outbound scheduler or bypass Host/Body/Guard/Delivery.

## Derived-cognition correction boundary

Accepted LCE cognition is reusable, but it is not infallible.

If factual MR Memory remains valid while LCE has inferred a wrong relation, an
authorized correction may invalidate the **derived relation** without deleting
the supporting Memory.

Required behavior:

```text
valid canonical Memory
    -> wrong LCE relation
    -> explicit correction
    -> relation removed from current usable cognition
    -> dependent derived structure revalidated/rebuilt
    -> current cognition may roll back
    -> rejected historical revision remains auditable
```

Historical visibility and current validity are separate.

A correction should persist strongly enough that an unchanged later sleep/dream
bootstrap does not immediately recreate the same rejected relation. That
persistent relation-level negative-constraint ledger is an LCE control-plane
follow-up; MR must not emulate it by deleting or mutating factual Memory.

## Persistence and restart

Per-Scope LCE derived cognition remains physically separate from MR canonical
Memory:

```text
<runtime namespace>/memory.sqlite
<runtime namespace>/lce/<scope-hash>/
    baselines/lce_baselines.sqlite
    worktrees/
    projection_state/projection_state.sqlite
    inspiration/inspiration.sqlite
    background_inspiration.sqlite
    lines/
        authority/
    structures/
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
- narrow Inspiration Material read/consume seam;
- incremental background catch-up and replay checkpointing;
- post-policy material reservation;
- release-on-reject/abort and consume-on-delivery-commit lifecycle;
- default-OFF/no-dependency behavior.

Run:

```bash
python -m pytest tests/lce_binding tests/memory_retrieval -q
```

The full MR CI additionally runs clean-install, Ruff-baseline, mypy and the
complete pytest/coverage suite.

## Activation boundary

LCE remains opt-in. `default_adapter(..., lce_enabled=False)` is the default.

Thread formation/maturity remains the bounded online projection policy for
explicit logical lines; its future wake-up, capacity and TTL refinements are
recorded separately. Path B is the sleep/dream latent-discovery consumer for history that did not
become an explicit mature Thread. The bounded background invocation worker is
now wired into the cognitive-tick composition. What remains deliberately
unimplemented is an autonomous CognitiveModeController that decides
ACTIVE↔DAYDREAM↔SLEEP↔DREAM from fatigue/circadian state.

Enabling either path does not grant LCE factual write authority. LCE may persist
derived cognition and rebuildable projection state only.
