# ADR-0029: Hybrid Memory retrieval with BM25, dense vectors, RRF and optional HyDE

- Status: ACCEPTED
- Date: 2026-09-25
- Authority: extends ADR-0024/0025; canonical Memory authority is unchanged

## Decision

MR may compose multiple derived discovery arms behind the existing
`RetrievalProvider` seam:

```text
canonical Memory
      |
      +--> lexical BM25 snapshot
      |
      +--> dense semantic provider
                 |
                 +----> Reciprocal Rank Fusion
                              |
                              v
                     stable memory_id candidates
                              |
                              v
                    canonical MR revalidation
```

BM25 and dense retrieval are complementary candidate generators. Their raw
scores are deliberately not normalized against each other. Reciprocal Rank
Fusion combines rank positions, so provider-specific score scales do not become
an implicit authority contract.

HyDE is an optional query-expansion layer. A model may generate a short
hypothetical memory passage from the query; the original-query and expanded-query
rankings are then fused. Generated HyDE text is retrieval material only. It is
never Memory, Evidence, an answer, or factual authority.

## Lexical provider

The initial BM25 provider is an immutable, dependency-free snapshot built from
canonical `CommittedMemory` values.

It:

- indexes only ACTIVE Memory;
- isolates results by exact MR Scope;
- NFKC/case-folds Latin and numeric text;
- indexes CJK runs as the full run plus character bigrams;
- can be discarded and rebuilt from canonical Memory;
- has no canonical write capability.

The snapshot intentionally avoids creating a second persistent memory store.
If scale later requires a persistent lexical index, that index remains derived
projection state with the same authority boundary.

## Fusion

`HybridRRFProvider` requires explicitly named retrieval arms.

Initial policy:

- RRF constant: 60;
- per-arm candidate window: 4x requested output, capped by the existing query
  maximum;
- duplicate IDs inside one arm contribute once;
- deterministic tie breaking;
- a configured arm failure fails the hybrid provider closed.

The candidate-window multiplier and RRF constant are retrieval policy, not
epistemic semantics. They may later be tuned by benchmark evidence.

## HyDE

`PromptHyDEExpander` is model-agnostic. Composition supplies the completion
call; MR supplies only the bounded prompt adapter.

The preferred product policy is **HyDE as search fallback, not an always-on
stage**. `HyDEFallbackProvider` first runs the normal retrieval path. If that
path returns at least the configured minimum number of unique candidates, no
LLM expansion is called. If recall is sparse, HyDE generates one supplemental
query and the original and supplemental rankings are fused with RRF.

The initial fallback threshold is three candidates, capped by the requested
query limit. This threshold is retrieval policy, not an epistemic rule, and may
be changed by composition.

If the primary retrieval call itself fails, the failure remains explicit. If
primary retrieval succeeds but the optional HyDE expansion/supplemental search
fails, the successful primary results are returned unchanged. The fallback
therefore cannot make an otherwise usable cheap search unavailable.

`HyDEAugmentedProvider` remains available for explicit always-on experiments,
but it is not the preferred default composition.

HyDE never writes Memory and never reinforces retrieved Memory.

## Authority

The canonical read sequence is unchanged:

```text
BM25 / dense / HyDE / RRF
        |
        v
memory_id + transient ranking metadata
        |
        v
CanonicalMemoryStore.get(memory_id)
        |
        +--> exact Scope
        +--> ACTIVE lifecycle
        +--> canonical content/provenance
```

Provider text, generated HyDE text, vector UUIDs, lexical scores, vector scores,
RRF scores and provider refs are non-authoritative.

## Relation to product attention and LCE

Hybrid retrieval answers:

> Which historical assets are plausible candidates for this query?

It does not answer:

- whether a Memory should automatically enter foreground attention now;
- whether an explicit medium-term line is still open;
- what the longitudinal history has already been understood to mean.

Those remain the responsibilities of Memory product surfacing/open structures
and LCE compiled cognition in `docs/architecture/MEMORY_ARCHITECTURE_V1.md`.

If accepted compiled cognition already captures the relevant logic line, raw
retrieval is supporting detail rather than a reason to recompute that logic.

## Evaluation boundary

No claim is made that hybrid retrieval beats dense-only retrieval until measured
on representative data.

The intended ablation is:

```text
A  BM25
B  Dense
C  BM25 + Dense + RRF
D  BM25 + Dense + RRF + HyDE
```

Measure at least bounded-K recall/hit rate, ranking quality, latency, and HyDE
model cost. LoCoMo/AML-style replay is appropriate for retrieval quality.
Separate LCE evaluation remains required for compiled longitudinal cognition.

This ADR freezes the seam and authority model, not a benchmark winner.
