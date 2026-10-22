# MR / MR-Mem assembly

[中文](assembly.zh-CN.md)

The existing production composition is `xiyue.mr_seam.get_mr_adapter` →
`default_adapter` → `build_runtime_stack` → `TurnOrchestrator`. Keep this one
pipeline. Host delivery remains outside MR; admission owns canonical writes.

Standalone MR-Mem now supplies the existing `HistoricalContextPort` before
appraisal. Previously the native semantic writer used a standalone database,
while MR's default history composition still selected legacy Memory storage.

```text
host-owned source → accepted compiler output → MR-Mem admission → canonical SQLite
                                                               ↓ read only
MR host request → facts → situation + historical context → appraisal → projection
                                                                    ↓
                                                  host delivery → commit / abort
```

Set `MR_MEM_READ_ENABLED=true` and `MR_MEM_CANONICAL_DB` to an absolute standalone
canonical path (`<MR-Mem data_dir>/memory.sqlite`). This enables reading without
enabling `SEMANTIC_DELTA_V1_ENABLED`. The latter also selects this reader when
explicitly enabled; this change does not endorse its experimental compiler.
Supply `MR_USER_ID` (or the factory's `user_id`) consistently with the writer.

`default_adapter(mr_mem_db=..., user_id=...)` provides the same composition for
host code. The root initializes a new empty sidecar; existing files are opened
read-only and checked, never migrated from a native conversation database.
Legacy `memory_enabled`, retrieval-provider, LCE and inspiration composition cannot
be combined with this path. In the Hermes seam the legacy memory writer is disabled;
legacy LCE flags reject composition instead of reading an incompatible schema.

Every turn opens a fresh read-only MR-Mem snapshot. Scope, active lifecycle,
attention suppression, known-at cutoff, source provenance and context budget
are enforced. The host must still propagate source edits/deletions through
MR-Mem's `invalidate_source`; this reader does not watch native databases.
An enabled reader's storage failure is an error, not an empty successful result.

Algorithm ports remain `SemanticCandidateProvider` and
`SemanticAppraisalProducer(model=SemanticAppraisalModelPort)`. Provider configuration
and a successful turn do not certify algorithm quality. Existing production
readiness gates remain in force. Deterministic turn defaults are test scaffolding.
Model inference quality is not certified by this read adapter.

Canonical-only reading supports MR-Mem `0685a8a2498cc828c8d500be6f4673e53fa6dc24`.
Line reading requires the paired development revision pinned in the host CI workflow.
Use `xiyue/tests/test_mr_mem_history.py` and the existing semantic host integration
suite to verify admission → read → commit/replay and failure isolation. No live
model, personal host deployment or algorithm-quality certification is implied.

This is an implementation of the existing historical-context boundary, not a new
external-memory authority gate (ADR-0013). Retrieval never becomes MR Evidence or
direct canonical-state authority; the sidecar is the sole semantic-memory writer.

To read the existing tree graph, also set the absolute `MR_MEM_LINE_ROOT` to the
MR-Mem data directory's `lce_tree` folder. The same shared neighbourhood reader
used by AML supplies `memory.line` historical context. Scope, known-at and MR
automatic attention/lifecycle rules apply to every expanded step; graphs do not
bypass suppression. See [the Line integration contract](assembly-line-context.md).
