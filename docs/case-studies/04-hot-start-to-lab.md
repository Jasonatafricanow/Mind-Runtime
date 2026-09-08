# Hot Start Became an Experiment, Not Another Pipeline

## Context

Hot Start was an attractive product question: after a small amount of new
interaction, can an agent recover useful long-term orientation without
re-reading and re-interpreting its entire history?

## Initial Approach

The early implementation direction was a custom harness that simulated the MR
pipeline, imported a corpus, ran a provider, and produced a result for a Hot
Start evaluation.

That is a reasonable way to get a first signal. It is also easy for the
harness to become a second production system.

## Failure / Limitation

If each research question creates its own runner, isolated storage convention,
model adapter, and corpus loader, then the project accumulates duplicate
pipelines. A Hot Start result can then depend on harness behaviour rather than
on the boundary it is meant to evaluate.

The long-term risk is architectural drift: research code starts writing
production state, or production code starts carrying experimental assumptions
because the two paths were never clearly separated.

## Alternatives

- Keep a bespoke Hot Start harness and extend it for every new experiment.
- Put Hot Start directly into the production runtime pipeline.
- Make the lab reusable and run Hot Start as its first experiment.

The third option was selected. It preserves a shared runner, isolated storage,
corpus import, model adapters, and reproducibility controls without turning any
one experiment into a new MR authority.

## Decision

The boundary is:

```text
MR Lab
  -> reusable experimental infrastructure

Hot Start
  -> one experiment running on that infrastructure
```

Research products must not mutate production Xiyue state. A lab run can
produce evidence, candidate structures, and review artifacts, but it cannot
silently promote any of them into canonical runtime cognition.

## Architectural Consequence

MR remains responsible for runtime authority and production persistence. The
lab can vary corpus, provider, cutoff, and evaluation policy while keeping
storage and execution isolated. The same boundary supports later experiments
such as trajectory or compiled-cognition probes without adding a new shadow
production pipeline for each one.

## Evidence

- [MR runtime/LCE integration boundary](../integrations/lce-binding.md)
- [Optional LCE binding exclusions](../adr/0026-optional-lce-memory-substrate-binding.md)
- [LCE research surface](https://github.com/Jasonatafricanow/LCE-Longitudinal-Cognition-Engine/tree/master/research)

The public record intentionally does not include private corpora or provider
logs. The claim here is an infrastructure and authority decision, not a
quantitative Hot Start benchmark.

## Current Status

The production/research boundary is accepted. Hot Start, compiled cognition,
and longitudinal compilation remain experiment/research concerns rather than
current MR runtime features.
