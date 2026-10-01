# Native semantic memory runtime

This is the opt-in composition for issues #51 and #49, governed by ADR-0040.
It uses the accepted MR-Mem and LCE commits pinned by the `native-memory`
extra. It does not activate a Hermes profile or discover production databases.

## Composition and ownership

The host constructs its one `MemoryCore`, scoped `NativeSourceStore`,
`SemanticCleaner`, UTC clock and `NativeMemoryRuntime`. The cleaner returns
the strict `native-cleaner-v1` contract. The host must supply a real, versioned
semantic block embedder. A bounded LCE interpreter is optional; without one,
Path B may produce structural candidates but cannot invent mature prose.
Path A uses the already accepted Thread summary and exact selected semantic
states without a second semantic model pass.

`NativeMemoryRuntime` binds a derived-state root to the canonical store path,
scope and origin runtime. Reusing it with a different binding fails closed.
Native raw stays in the source store. MR-Mem stores accepted semantic content,
attributes and SourceRefs. Receipt recovery stores source pointers and fragment
IDs, not source bodies. The LCE compatibility source view is explicitly labeled
metadata; it contains no native transcript and is not a second raw store.

## Host hooks

After a normal native turn commits, call `runtime.process(record)`. Use the
same method for a source edit supplied by the host's native change stream.
Call `runtime.reconcile_sources()` after source edits/deletions to invalidate
canonical dependents and rebuild affected LCE projections. Freshness checks
already omit stale semantics and baselines before reconciliation runs.

Pass `native_history=runtime` to the existing `build_memory_history` composition
and use its `HistoricalContextPort` during the next Context Assembly. Enabling
legacy memory readers alongside this path is rejected. The runtime reads
source-fresh, already accepted semantics, active Threads and accepted LCE
understandings within the existing item/character budget. This bounded reader
does not implement issue #4's three-way RAG fusion.

Before enabling these hooks in an actual Hermes profile, disable the old raw
copy/curation worker and its duplicate retrieval path. The host retains ownership
of `MemoryCore` and the native source; `runtime.close()` closes its derived
projection stores and receipt connection only.

## Bounded warm start and recovery

`runtime.warm_start(source, limit=100)` performs one page:

1. Check accepted SourceRefs for edits/deletions.
2. Fetch exact native pointers for incomplete receipts, verify the receipt and
   context identity, and retry only missing accepted-semantic/consumer stages.
3. Read at most `limit` new records after the durable occurrence-time/record-ID
   cursor. Advance only after successful processing of each record.
4. Run explicit trajectory bootstrap for the resulting accepted point set.

The caller controls further pages. No full-history loop is enabled here.
Replay reuses frozen KEEP/DROP outcomes. New bounded context may resolve only
DEFER fragments. Rejected proposals append to history and cannot replace an
accepted proposal. Thread handoff receipts prevent retired Threads from being
recreated by old support; genuinely new source events may start a new Thread.

The append cursor does not discover backdated inserts or edits to previously
dropped records. The host must deliver those native changes explicitly. Native
deletion, unavailable recovery pointers or changed source versions fail closed;
the runtime does not repair them by borrowing another quote or rescanning raw.

## Evidence and rollout gates

Fixture tests cover native commit/hot start/next-context composition, restart
after a projection failure, source edits/deletions, forged projection content,
rejection, root binding and whole-item budgets. Fixture vectors establish
mechanics only. LCE's separate conformance suite establishes Path A/B structural
behavior with controlled inputs.

A bounded real Hermes session has been cleaned using frozen host-reviewed
semantic proposals: 153 records, 79 structural drops, 393 semantic DROP,
4 KEEP, 3 DEFER and 4 canonical memories. These disposition counts are fragment
counts after structural filtering. Replay made no additional cleaner calls.
This is not live production-model or real-embedding Path B acceptance.

Production activation and full-history bootstrap remain gated on the repository
quality checks, configured production providers, and real-history Thread/LCE
funnel review. RAG fusion and AML adaptation follow those gates.
