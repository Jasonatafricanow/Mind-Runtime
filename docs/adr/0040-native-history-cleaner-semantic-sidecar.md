# ADR-0040: Native history cleaner and semantic sidecar

Status: Accepted for issues #51 and #49, under MR-Mem ADR-0001 at fbf96dd.

Native Hermes history remains raw authority. The historical processing path is
native SourceRef -> structural hard filter -> one host semantic pass returning
DROP/KEEP/DEFER fragments -> direct MR-Mem semantic admission. No factual-pair
admission or raw transcript copying precedes compilation.

Host-generated fragment IDs bind exact immutable source slices. Unknown IDs,
model offsets, altered quotes, incomplete coverage and conflicting frozen
results reject the whole proposal. JSON decoding is the only escape decoding.
Proposal attempts append; accepted results and stage receipts are durable.
Thread/LCE retries consume accepted canonical semantic IDs without another
semantic model pass. Occurrence time orders native history stably; knowledge time
records when semantics were admitted.

Natural language is never structurally dropped by coding/test keywords.
Machine role and proven empty tool-call envelopes may be dropped. Assistant
text is context only and cannot establish user facts. DEFER is explicit and
may be retried with a bounded, separately identified context window.

The locally unpublished curation path at 6e10dcc is not a base for production:
its quote-range repair, destructive unescape and proposal replacement are
superseded by this source-first path. Its stable source ordering is retained.
Full-history rollout requires real-sample semantic and LCE conformance evidence.
