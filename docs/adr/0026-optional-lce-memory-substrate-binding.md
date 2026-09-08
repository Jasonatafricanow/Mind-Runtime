# ADR-0026: Optional LCE canonical Memory substrate binding

Status: Accepted for MR-LCE-BIND-1

## Authority

MR base 0c387429bdef8baa25509ad50182ec16ae670f31 supplies ADR-0020 and
ADR-0022 through ADR-0025. LCE Core V0 is frozen at
d1eb5f63b427f216df0e38bde48eaff639546391. This decision authorizes one
optional composition adapter against its existing MemorySubstratePort.
It does not change LCE Core or the canonical Memory contract.

Memory owns the points. LCE owns Baseline revisions over caller-selected
points. Baselines never automatically become Evidence, Observation, Memory,
C10, Intent, Appraisal, or Action. Reading and consolidation never reinforce
canonical authority.

## Read contract

The MR adapter accepts an explicit tuple of 1 to 100 distinct stable Memory
IDs and one composition-authorized structured Scope. It verifies the bound
Runtime manifest and reads only that Runtime's canonical Memory SQLite.
Any missing row, unequal Scope, or lifecycle other than ACTIVE rejects the
entire request before returning any views. Duplicate IDs are rejected;
request order is preserved. These checks apply even to IDs selected by
previously validated semantic retrieval.

MemoryItemView maps memory_id and content directly from CommittedMemory,
and source_refs from provenance.evidence_refs. Explicit-ID reads provide an
empty immutable retrieval_metadata mapping. Provider content, identifiers,
rankings, and embeddings have no authority here. No vector or embedding
dependency is needed to resolve explicit IDs.

## Composition and persistence

LCE is an optional separately installed package from the frozen source;
MR does not vendor or import it in default production composition. Explicit
enabled composition requires an injected consolidator. Disabled composition
returns no integration before imports or filesystem access.

StoragePaths exposes an LCE root within the existing Runtime namespace.
Each authorized structured Scope gets a separate physical directory under
that root, addressed by SHA-256 of its full canonical scope JSON. This
prevents Baseline history for the same opaque region_id crossing Scope
boundaries. The digest is deployment addressing only, never LCE cognition,
region identity, or a second Scope ontology. RuntimeBinding fields are not
inserted into Memory views or Baseline content. LCE stores its own SQLite
database; MR canonical databases remain read-only to this integration.

region_id remains caller-supplied opaque LCE lineage identity. No cluster,
topic, Scope, Agent, provider, or Runtime-to-region discovery policy is
introduced. Frozen LCE normalized-string equivalence and revisions remain
unchanged.

## Deferred and disabled

Production Memory admission, semantic retrieval, and LCE invocation remain
OFF by default. Historical backfill, supersession emitters, reinforcement,
reverse authority, STRUCTURE-06, topology discovery, Hot Start, and embedding
quality certification are excluded. BGE-small-en is not certified for
Chinese/Xiyue. The fact-commit-before-Memory-job-registration crash gap
remains a PRE-PRODUCTION-ACTIVATION BLOCKER.
