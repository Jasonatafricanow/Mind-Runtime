# Temporal Binding Audit — 2026-09-25

Verdict: SUPPORTED

## Scope

Validated the production MR -> LCE temporal read seam and the Path B
consolidation entry. This does not activate an autonomous sleep/idle scheduler
and does not make LCE a factual authority.

## Implemented

- read-only factual provenance access;
- separate Evidence/source chronology and proposition-valid Reality time;
- Memory source Observation and commit chronology;
- bounded preservation of multiple Reality Observations;
- knowledge-time cutoff enforcement;
- MR-owned reserved temporal context for LCE Path B;
- unchanged mature Thread -> LCE Path A no-model handoff.

## Deterministic verification

Issue #20 C1-C8 and Issue #21 T1-T6 are covered across
tests/lce_binding/test_temporal_authority.py plus the existing mature Thread
handoff test in tests/lce_binding/test_binding.py.

The suite verifies source occurrence distinct from commit time,
CURRENT/PAST/FUTURE/UNRESOLVED semantics, POINT/INTERVAL/OPEN_INTERVAL windows,
UNKNOWN preservation, deterministic restart ordering, cutoff safety,
late-arriving past knowledge, multiple support timestamps without a fabricated
proposition interval, non-retrospective completion, Path A no-model handoff,
and the real MR fact -> canonical Memory -> temporal view -> LCE Path B smoke.

## Remaining bounded ambiguity

Reality Observation observed_at is intentionally anchored to the original
Evidence.received_at rather than extractor processing time. This is the frozen
causal contract. A distinct processing timestamp would require a future
contract change if such audit semantics become necessary.

Default text-v1 Memory admission is single-Evidence today; multi-Evidence
provenance remains supported by the temporal read contract and is tested
without inventing an event interval.

## Explicit non-goals

No second factual Memory store, GraphRAG, new relation ontology, automatic idle
scheduler, all-pairs relation inference, or change to Thread -> LCE handoff.
