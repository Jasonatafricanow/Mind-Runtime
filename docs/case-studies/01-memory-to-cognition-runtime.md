# From Memory Retrieval to a Cognition Runtime

## Context

The first question was familiar: how can an agent remember a person across
time? The obvious answer is to retain history, retrieve relevant fragments,
extract useful variables, and place them into the next prompt.

That pattern is useful. It can improve recall and reduce the amount of raw
history sent to a model. It does not, by itself, establish continuity of
understanding.

## Initial Approach

The initial mental model was:

```text
history
  -> retrieval
  -> extracted variables
  -> prompt
  -> model interpretation
```

Adding provenance, filters, summaries, and better retrieval makes this loop
more disciplined. The final authority still remains implicit if every turn
asks the model to reconstruct the meaning of the entire past again.

## Failure / Limitation

The architectural limitation was not simply that retrieval could miss a
document. The stronger problem was repeated reconstruction. A model can see
the same history and produce a different interpretation, or mistake a
retrieved candidate for an already accepted state. The system then becomes a
variable extractor and increasingly sophisticated prompt builder rather than a
runtime that carries forward authorized understanding.

This also creates an unstable success criterion. More retrieved context may
increase apparent recall while increasing model variance, repeated reasoning,
and opportunities for self-reinforcement.

## Alternatives

Three directions were considered:

1. Improve retrieval and prompt assembly while keeping interpretation as the
   only continuity mechanism.
2. Persist every model interpretation as if it were canonical cognition.
3. Separate evidence, interpretation, canonical state, and projection, then
   let a bounded runtime carry forward accepted state and explicit uncertainty.

The second option was rejected because model output cannot authorize itself.
The first was retained as a useful capability, but not as the definition of
continuity.

## Decision

Mind Runtime treats persistent cognition as a governed runtime-state problem.
The target loop becomes:

```text
existing authorized state + new evidence / delta
  -> bounded revision
  -> durable state and projection
```

The runtime owns identity, admission, persistence, lifecycle, provenance,
authority boundaries, and observation. Models still perform bounded inference
and expression.

The optimization objective is not “put more history in the prompt.” It is to
reduce repeated reasoning, reduce unnecessary historical reconstruction,
preserve accepted understanding, and preserve uncertainty when the evidence is
incomplete.

## Architectural Consequence

This decision produced explicit seams for evidence, memory, state, admission,
retrieval, projection, expression, persistence, telemetry, and read-only
observation. It also made `UNKNOWN`, `PARTIAL`, `ROUGH`, and `REVISABLE` valid
states rather than schema failures.

The boundary is intentionally incomplete. `Compiled Cognition`, a general
effective-cognition view, and committed cognition head selection remain
research directions rather than current MR authority.

## Evidence

- [MR README: problem definition and design principles](../../README.md)
- [Architecture lock](../architecture/MR_ARCHITECTURE_LOCK_v1_1.md)
- [Design philosophy](../design-philosophy.md)
- [Canonical Memory authority](../adr/0023-canonical-memory-authority.md)
- [Shared retrieval read seam](../adr/0024-shared-memory-retrieval-read-seam.md)

## Current Status

The authority and persistence boundaries are implemented and covered by the
public source tree. The stronger claim that MR already contains a compiled,
model-independent cognition layer is deliberately not made.
