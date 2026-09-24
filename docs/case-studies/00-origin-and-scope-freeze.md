# Origin and Scope Freeze: How MR Avoided Becoming a Second Agent OS

## Note on Source

This document is a **retrospective reconstruction**, written after the fact
from memory, not a contemporaneous record. The early commit history that
would have shown this process directly was superseded during a repository
reset (`establish sanitized canonical MR baseline`, 2026-09-08) and is not
preserved in the public source tree.

The dates and artifacts listed under **Evidence** are still verifiable. The
causal narrative connecting them is not fully reconstructable from public Git
history and should be read as explanatory context constrained by surviving
evidence, not as primary contemporaneous evidence.

## Context

MR did not begin as an attempt to define a runtime-authority boundary. It
began as a much more ordinary idea: an emotion/memory harness that could sit
in front of a model and let interactions accumulate into something that
carried over between sessions. This is a common shape in the community —
memory store plus retrieval plus a prompt template, often assembled from
existing off-the-shelf pieces.

## Initial Approach

The early build followed that common shape closely. Store interactions,
retrieve relevant ones, summarize them into the prompt. It worked well enough
to be usable, and it was not architecturally distinct from the many similar
harness projects already circulating publicly.

## Failure / Limitation

The limitation did not appear as a bug. It appeared as scope creep during
normal development. Making the harness more capable kept surfacing questions
that a simple retrieval loop could not answer on its own — how to judge
whether a pattern across many past interactions was real rather than
coincidental, how to keep that judgment from being silently reprocessed and
reinterpreted every session, how to let that research happen without every
experiment being a change to the thing already in production use.

Chasing those questions inside the same codebase had a second-order effect:
each answer pulled in more responsibility — planning, longer-horizon
reasoning, more of what an agent needs to operate end to end. Left
unchecked, the natural endpoint of that trajectory was not a bounded runtime;
it was a second, informally designed Agent OS.

## Alternatives

- Keep pushing the longitudinal/structural questions into the same
  repository, since the harness was already the container for them.
- Set the harder questions aside and ship the harness as-is.
- Extract the longitudinal-structure question into its own project with its
  own authority, and separately decide what MR itself was and was not for.

The first was the path already being taken by default, and it is the one
that produced the scope creep described above. The second would have avoided
the creep but abandoned a genuinely interesting research question. The third
required two separate decisions rather than one, which is slower, but keeps
either decision from being made implicitly by momentum.

## Decision

In the reconstructed sequence, the longitudinal-structure work was separated
into what became LCE (see [why LCE is separate](03-why-lce-is-separate.md)).
That extraction did not by itself define MR. MR's own scope was separately
frozen: MR is not a generic cognitive runtime, not an agent framework, and
not a second Agent OS. What MR owns is narrower — which state is authorized
to participate in cognition now, not open-ended reasoning, planning, or tool
orchestration.

## Architectural Consequence

The freeze is recorded as a versioned artifact rather than an informal
understanding: [`MR_ARCHITECTURE_LOCK_v1_1.md`](../architecture/MR_ARCHITECTURE_LOCK_v1_1.md),
which explicitly states what MR is not, and which supersedes an earlier,
less formal boundary document. The faculty separation described in
[02](02-faculty-boundaries.md) and the authority split described in
[03](03-why-lce-is-separate.md) both depend on this boundary being explicit.
Without it, longitudinal research could continue to expand MR's ownership
instead of remaining on the other side of a contract.

## Evidence

- [Architecture lock, Freeze Date 2026-09-01](../architecture/MR_ARCHITECTURE_LOCK_v1_1.md)
- [Why LCE is separate](03-why-lce-is-separate.md)
- [Faculty boundaries](02-faculty-boundaries.md)
- [LCE Core repository](https://github.com/Jasonatafricanow/LCE-Longitudinal-Cognition-Engine) —
  earliest public commit 2026-09-06, two days before MR's sanitized public
  baseline on 2026-09-08. This verifies that LCE existed as an independent
  public repository before the current MR public history begins; it does **not**
  establish the exact extraction date relative to the 2026-09-01 architecture
  freeze.

## Current Status

The scope freeze is implemented and enforced by the current source tree and
the faculty/authority boundaries described in the other case studies. The
pre-reset development sequence itself is not reconstructable from MR's public
Git history. This document preserves the retrospective account while keeping
that evidence boundary explicit.
