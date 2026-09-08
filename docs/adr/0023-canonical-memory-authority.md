# ADR-0023: Canonical Memory authority and durable projection intent

- Status: ACCEPTED for the bounded MR-MEM-1 assignment
- Date: 2026-09-07
- Authority: MR-MEM-1 / MR-MEM-1R; ADR-0020 and ADR-0022 remain unchanged.

## Decision

Evidence and its admitted Observation remain factual authority. MR admission
alone produces CommittedMemory, an immutable semantic record derived from that
authority. Memory neither replaces Evidence nor raises its authority level.
Extractor/model output is candidate material, never a commit permission.

One Runtime owns one physical storage namespace. The existing StoragePaths
exposes `root / "memory.sqlite"`, beside its binding manifest. PersonaProfile,
Body agents, vector providers, retrieval, and LCE do not own Memory. A record
carries the existing structured Scope (what it is about), origin_runtime_id
and SyncFields (origin/replay metadata). No deployment agent ID, binding path,
or storage namespace is added to the canonical contract. Scope's established
domain fields, including its lawful AGENT fields, round-trip without flattening.

MR derives memory_id from a versioned, length-unambiguous JSON identity of
runtime origin, full Scope, admitted source identity, and extractor candidate
identity. Provider refs, vectors, embedding IDs and retrieval ranks are absent.
An exact immutable payload replay is a no-op; conflicting payloads fail closed.
New records are ACTIVE. Lifecycle vocabulary also includes SUPERSEDED and
ARCHIVED, with a structural supersedes_memory_id; no emitter is implemented.

Admission is default OFF. The optional hook runs only after FactIngestService
successfully admits a durable factual pair. The admission service verifies the
exact Evidence and Observation against that same factual backend; merely
retaining rejected Evidence is insufficient. Every candidate must retain the
source Scope and a nonempty subset of the admitted source's evidence refs.
The first slice accepts only this single-source provenance set. It does not
read or convert a historical corpus.

Only NEW factual admission registers a durable extraction job. REPLAY may
resume an already registered job; it cannot register historical sources.
REPAIRED sources without a registered job are likewise excluded. Job identity,
commit timestamp and completed outcome survive restart, so extraction failure
can be retried without reinterpretation of completed jobs. A crash between the
facts transaction and job registration can leave a fact without Memory. This
ticket does not promise atomic facts-to-Memory delivery or infer historical
eligibility to fill that gap. Ordinary downstream Memory errors are logged by
exception type without content; the successful factual disposition still reaches
the orchestrator. Registered jobs remain retryable. Process-death exceptions
are not swallowed. Facts remain admitted if downstream Memory fails.

Canonical records, all projection intents for that admission, and job completion
commit in one stdlib sqlite3 transaction. Transactions serialize writers with
BEGIN IMMEDIATE; SQLite arbitrates immutable conflicts. This does not introduce
a new runtime lease or cross-process runtime ownership model.

The projection intent initially targets an unresolved provider-neutral route;
no embedding identity is fabricated. Future composition can name a route and
embedding identity in derived projection state. The injected writer must
implement idempotent upsert keyed by MR memory_id plus projection target.
The worker receives immutable Memory, records attempts/results, and has no
admission method. Failure or a crash after external upsert leaves retryable
intent; duplicate external execution is possible and requires writer idempotency.
Missing canonical rows fail closed. Provider references stay in projection state.

Derived projection state can be wiped and re-enqueued from canonical records.
Rebuild never updates/deletes canonical Memory or requires an old provider UUID.
Replacing providers changes only projection targets and results.

## Deferred

Historical backfill; supersession emitter policy; reinforcement/use-axis;
decay/deletion; embedding-model and provider/backend choice; actual vector
execution; shared retrieval (MR-MEM-2); HistoricalContext; LCE integration;
DELETE/tombstones, retry scheduling/backoff, permanent failures and dead letters.

## Verification

`tests/memory/` covers the MR-MEM-1 T1–T19 authority, persistence, replay,
fault injection, worker, rebuild and composition invariants without vector
dependencies. RuntimeBinding, host/composition and governance regression remain
required. Experimental memory-rebaseline-v1 is reference material only.
