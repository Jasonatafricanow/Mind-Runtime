# Model Variance Changed the Definition of Success

## Context

One architectural question could not be answered from contracts alone: if the
foundation model changes, what should remain stable?

In comparable host/runtime situations, model choice can change retrieval
initiative, tool use, context interpretation, and response quality. That is an
engineering observation, not a claim about a private conversation or a public
benchmark.

## Initial Approach

It was tempting to treat MR as the component that should make different models
behave the same. If durable state is working, perhaps a weak and a strong model
should produce nearly identical outcomes.

## Failure / Limitation

That standard confuses inference capability with continuity. Models remain
responsible for reasoning, tool selection, and expression. A runtime cannot
remove every difference between models without becoming the reasoning engine it
was designed not to be.

The useful question is not whether all model variance disappears. It is which
variance is unnecessary reconstruction caused by missing runtime state or
implicit authority.

## Alternatives

- Require model interchangeability at the response level.
- Put more model-specific prompt instructions into MR until outputs converge.
- Preserve durable state and authority while treating model variance as an
  explicit capability boundary.

The third option was chosen. It is more modest, but it is testable and keeps
MR replaceable as a runtime boundary.

## Decision

The responsibilities are:

| Layer | Responsibility |
| --- | --- |
| Model | Current-turn inference, tools, and expression |
| MR | Durable state, identity, admission, authority, and continuity |
| LCE | Longitudinal learned structure and compilation research |

MR succeeds when it reduces unnecessary reconstruction, preserves accepted
state, narrows free reinterpretation, and makes identity/context boundaries
stable. It does not succeed by making unlike models identical.

## Architectural Consequence

This decision protects explicit state and read seams from becoming giant
model-specific prompts. It also gives evaluation a sharper question: did the
runtime preserve authorized context and uncertainty, or did the model have to
rebuild everything from fragments again?

The public README therefore describes reduced model dependence as a direction,
not as complete model independence.

## Evidence

- [MR README: model replacement principle](../../README.md)
- [Architecture lock](../architecture/MR_ARCHITECTURE_LOCK_v1_1.md)
- [Bounded expression authority](../adr/0007-bound-expression-authority.md)

No private dialogue, provider log, or fabricated benchmark is included in this
case study. The evidence is the explicit responsibility split and the runtime
contracts that preserve it.

## Current Status

The responsibility boundary is implemented. Quantifying model-variance
reduction across providers remains an evaluation problem and is not claimed as
closed by this repository.
