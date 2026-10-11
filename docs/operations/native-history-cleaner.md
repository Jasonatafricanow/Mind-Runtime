# Native historical cleaner (#51)

Install `.[history-sidecar]`. The dependency is pinned to the reviewed MR-Mem
SourceRef boundary PR; no internal model is created.

Composition supplies:

- a read-only HermesSourceStore with explicit native user ownership or a bounded
  allowlist of userless sessions;
- a host SemanticCleaner implementing one structured pass over SourceFragments;
- SemanticAdmissionService backed by the same MemoryCore and scoped source reader;
- versioned downstream consumers, for example `thread:v1` and `lce:v1`.

Read native records in timestamp/id order. Process each through
`HistoricalSemanticPipeline.process`. The pipeline records source cursor/version,
compiler version, disposition, accepted semantic output and per-memory consumption
receipts. Producer failures/invalid proposals append to proposal history.
An accepted result is frozen before any canonical admission or downstream work.
Restarting with the same record reuses the accepted result and retries only
missing stage receipts. Consumers must be idempotent if a crash occurs between
their own commit and the receipt write.

DROP and DEFER never enter canonical semantic memory or downstream consumers.
For DEFER, provide at most 8 current scoped source fragments/4096 characters as
context on a later call. Only previously deferred fragments are sent for fresh
interpretation; accepted KEEP/DROP results remain frozen.

The provider must return the exact `native-cleaner-v1` shape validated by
`validate_proposal`. It must cover every host fragment ID once. KEEP includes
subject, holder, polarity, modality, temporal_scope and kind. Thread signals may
come from that same pass. Quotes, guessed ranges and unknown fields are rejected;
paths retain literal backslashes. Assistant content is context-only.

The prior local history-import/curation pipeline is superseded and is not imported
or automatically activated by this module. No production gateway or full-history
worker is enabled in this change. Normal-turn integration and incremental
edit/delete reconciliation remain issue #49, after LCE algorithm conformance.

## Bounded real-source evidence

A read-only replay of one actual Hermes session covered 153 native records.
79 machine records/envelopes were structurally dropped. Semantic processing
classified 400 fragments: 393 DROP, 4 KEEP, 3 DEFER. Four local semantic records
were admitted. The same records replayed with zero extra Cleaner calls and no
additional canonical records.

Semantic proposals were reviewed and frozen by the current Codex host for this
bounded sample; this is not evidence of a configured production Body provider.
Source snapshot digest:
`aa6f0aed02ec948e63ae5a8dbc28be237c78cd8c82108b9ecb923c2964954f1a`.
Private transcript, native user/session identities and proposals are not published.
The sample establishes the mechanism and local semantic reduction; broader
semantic quality and production model behavior remain unverified.
