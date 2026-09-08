# ADR-0025: Optional semantic vector provider

- Status: ACCEPTED for the bounded MR-MEM-3 assignment
- Date: 2026-09-07
- Base: 02dcdf2c3695948753a5df10e694d97afdea319b
- Authority: MR-MEM-3 ticket; canonical ADR-0020/0022/0023/0024 unchanged

## Decision

First optional implementation: Qdrant Client 1.19.0 local persistent mode with
explicit dense vectors; FastEmbed 0.8.0 / ONNX for actual pretrained embeddings.
This selects an initial working configuration, not a permanent/default backend
or model. No LLM, extraction, inference-driven Memory management or mem0 API is
in the projection/retrieval path. Default production admission/retrieval remain OFF.

The exact production base has fixed-revision projection targets, but no concrete
EmbeddingIdentity type. Forward-port the experimental four-field semantics
(provider, model_id, dimension, revision) into derived embedding contracts.
Never add these fields to CommittedMemory. FastEmbed's identity includes its
implementation version and a verified digest of locally provisioned model files.
Runtime code loads local files only; it cannot silently download another revision.
Canonical content is embedded without rewriting; query embedding uses the same
model and preprocessing. Invalid dimension/nonfinite/zero vectors fail closed.

A derived target deterministically binds backend/schema revision and full
EmbeddingIdentity. Stable provider UUIDs derive from Runtime isolation key,
target and MR memory_id. They are never reverse-promoted into canonical IDs.
Payload retains mr_memory_id, full Scope serialization, namespace key and full
embedding identity/target. Retrieval checks these fields and UUID consistency,
then emits only IDs and scores to MR-MEM-2 canonical resolution.

Provider files live below RuntimeBinding-resolved StoragePaths.semantic_index_root;
each target has a separate local Qdrant directory. The existing binding manifest
must already match before opening provider storage. Runtime keys reflect physical
hosting identity only, not Agent ownership or cognition. Collection metadata and
vector geometry must match the requested namespace/target/embedding configuration.
The embedding writer, read-only RetrievalProvider, and explicit derived-index
maintenance capabilities remain separate. Queue database paths must match the
index's binding-resolved canonical database before worker construction/rebuild.
The writer also resolves each supplied Memory against that bound canonical store;
caller-supplied Memory content alone is not sufficient projection authority.
Reading never creates a missing index.
Qdrant local mode holds one process/client lock per directory; the composed owner
shares its client between writer and reader and closes it explicitly. No scheduler
or multi-process redesign is introduced.

ProjectionQueue gains optional target filtering before LIMIT; worker forwards
that filter. Existing defaults and unassigned durable intents remain unchanged.
Explicit target rebuild can reset completed intents for that target only in one
SQLite transaction. Ordinary ensure-enqueued rebuild remains idempotent. Writers
reject mismatched targets rather than interpreting an old intent with a new model.
Creating target intents from canonical Memory is derived index reconstruction,
not historical fact-to-Memory backfill. Local target reset commits before provider
wipe/create, so failure leaves durable retry work. Projection writers may recreate
a missing derived collection for those pending intents; readers cannot. Canonical
rows are never touched. Wipe explicitly deletes all points before dropping the
collection: Qdrant local delete_collection uses best-effort directory removal,
which can retain an open SQLite file on Windows. Logical deletion is verified
before dropping collection metadata, so recreated collections cannot revive points.
Retrying a successful remote upsert after local completion failure uses the same
point UUID and replaces the same logical point.

No configuration means Null/disabled. Missing optional package, missing index/model,
provider runtime failure and a successful empty search remain distinguishable.
Dependency imports occur only on explicit provider construction. No production
Xiyue data is read or vectorized by this ticket; tests use disposable bindings.

## Bounded provider comparison and future space access

- mem0 2.0.19: inspected installed add(infer=False) and _create_memory. The latter
  generates uuid4; the experimental adapter explicitly tolerated duplicate points.
  That cannot satisfy MR-MEM-3 retry identity without extra state/coordination.
- Direct Qdrant 1.19.0: already present; explicit stable-ID upsert, persistent local
  mode, payload filters, vectors returned by retrieve/scroll, and numeric scores.
  Selected for the smallest existing backend with these primitives.
- A custom NumPy/SQLite cosine store: possible, but would introduce a new vector
  engine and persistence maintenance despite an available tested backend. Rejected.

Qdrant retrieve(ids, with_vectors=True) supplies a bounded vector matrix; numeric
query_points can use vectors or point IDs for neighborhoods. Tests demonstrate
native bounded vector access. Future Lab can also re-embed canonical IDs into a
different space. No LCE API is added and there is no Top-K-only lock-in.

Primary references (also checked against the installed API/source):
[Qdrant points](https://qdrant.tech/documentation/concepts/points/),
[FastEmbed](https://qdrant.github.io/fastembed/).

## Deferred activation gates

The MR-MEM-1 fact commit to Memory job registration gap remains a
PRE-PRODUCTION-ACTIVATION BLOCKER. Historical backfill, supersession emitter,
reinforcement/use-axis, LCE binding, structural analysis and production activation
are not implemented. STRUCTURE-06 remains parallel research, not a dependency.
