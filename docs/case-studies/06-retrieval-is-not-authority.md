# Retrieval Is Useful, but Retrieval Is Not Authority

## Context

Retrieval is valuable because it can find relevant evidence quickly. The
danger appears when relevance is mistaken for truth, or when a model's own
interpretation is written back and later retrieved as if repetition increased
its authority.

## Initial Approach

A common loop is:

```text
retrieve memory
  -> model interprets it
  -> store interpretation
  -> retrieve interpretation later
  -> treat retrieval as evidence
```

This is convenient and can look coherent in a short demo.

## Failure / Limitation

Similarity, recency, frequency, and clustering are discovery signals. They do
not prove that a candidate is canonical state. Repeated model output is also
not additional evidence. If the loop is allowed to authorize itself, the
system can create a self-reinforcement cycle while appearing to improve
memory.

The failure is epistemic and architectural at the same time: the discovery
layer silently gains authority it was never granted.

## Alternatives

- Let the highest-scoring retrieval result become the current truth.
- Let the model promote its own interpretation through repeated use.
- Keep Evidence, Candidate, Interpretation, Canonical State, and Projection as
  separate objects with explicit promotion rules.

The third option is the accepted boundary.

## Decision

The governing rules are:

> Authority is explicit.

> Model output cannot authorize itself.

Retrieval providers may supply relevance or IDs. Canonical storage decides
content, scope, lifecycle, and authority. Unknown, rejected, or ambiguous
material remains visible as such and fails closed where the contract requires
it.

## Architectural Consequence

MR exposes a bounded memory/context read seam. Optional vector providers remain
replaceable and cannot become an authority domain merely by ranking candidates.
The LCE research surface follows the same rule: semantic neighbourhoods and
regions are inspectable candidates, not canonical cognition.

This rule also prevents a future “effective cognition” design from being
smuggled into production by a retrieval helper. Such a design needs its own
accepted authority contract.

## Evidence

- [Canonical Memory authority](../adr/0023-canonical-memory-authority.md)
- [Shared Memory retrieval read seam](../adr/0024-shared-memory-retrieval-read-seam.md)
- [Optional semantic vector provider](../adr/0025-optional-semantic-vector-provider.md)
- [No self-authorizing feedback](../adr/0010-no-self-authorizing-feedback.md)
- [LCE external substrate boundary](https://github.com/Jasonatafricanow/LCE-Longitudinal-Cognition-Engine/blob/master/docs/research/external-substrate-vs-lce-core.md)

## Current Status

The authority separation and bounded retrieval seam are implemented. A general
committed cognition lineage/effective-head resolver is not claimed as a current
MR feature.
