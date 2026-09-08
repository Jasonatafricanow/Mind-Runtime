# Separating Memory, Feeling, Understanding, and Reasoning

## Context

Once continuity became the target, a second problem appeared: “cognition” was
too broad a label. Memory, affect, learned longitudinal structure, current
reasoning, tools, and expression all influence an agent, but they do not have
the same lifecycle or authority.

## Initial Approach

A tempting integration is:

```text
MR emotional summary
  + LCE logical summary
  -> large prompt
  -> model
```

This looks like a unified cognition layer. It also feels easy to demo because
every subsystem can contribute text immediately.

## Failure / Limitation

The combined prompt does not actually integrate authority. It concatenates
multiple summaries and asks the model to decide what they mean now. The
distinction between remembered experience, long-term change, current inference,
and accepted runtime state becomes less visible, not more.

The opposite failure is also possible: if MR starts planning open-ended goals
or composing the final response, then the model becomes a thin I/O shell. That
would move current-turn cognition into the runtime and make the boundary harder
to inspect and replace.

## Alternatives

- One large “agent brain” that owns memory, emotion, planning, and expression.
- Independent summaries fused into a larger prompt.
- Explicit faculties with narrow contracts and different authority rules.

The first two preserve convenience at the cost of inspectability. The third
was selected because a boundary can be tested, rejected, and replaced without
turning every subsystem into a new hidden authority.

## Decision

The working decomposition is:

| Faculty | Responsibility |
| --- | --- |
| Memory | What was experienced and what evidence is available |
| C10 / affect runtime | How bounded long-term affect changes over time |
| LCE | What structure may be learned across time |
| Body / model | Current-turn reasoning, tools, and response expression |
| MR | Which runtime state is authorized to participate now |

MR exposes bounded reusable state. The Body performs current-turn inference.
This is not a claim that the faculties are biologically analogous; it is an
engineering boundary for ownership, persistence, and verification.

## Architectural Consequence

The public MR source separates canonical state, memory authority, deterministic
affect transitions, policy, expression bounds, persistence, and observation.
The LCE integration is one-way and optional. The runtime does not become an
open-ended reasoning engine, and the model does not gain authority merely by
producing a summary.

This also explains why `UNKNOWN` and failed or rejected proposals remain
visible. A faculty boundary is only useful if it can preserve non-acceptance
without silently converting it into a confident prompt fragment.

## Evidence

- [Architecture lock](../architecture/MR_ARCHITECTURE_LOCK_v1_1.md)
- [Bounded expression authority](../adr/0007-bound-expression-authority.md)
- [Atomic affect projection](../adr/0005-atomic-affect-vector-projection.md)
- [No self-authorizing feedback](../adr/0010-no-self-authorizing-feedback.md)
- [Optional LCE binding](../adr/0026-optional-lce-memory-substrate-binding.md)

## Current Status

The faculty boundaries are implemented as runtime contracts and adapters where
the public source claims them. Full faculty-level cognition and generalized
compiled understanding remain design/research work.
