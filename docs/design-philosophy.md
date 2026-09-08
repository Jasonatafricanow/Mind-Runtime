# Why Mind Runtime Exists

The original problem was not memory.

The problem was continuity.

A model can remember that a conversation happened and still fail to continue
from the understanding that conversation produced.

If every new inference begins by retrieving historical fragments and asking a
language model to understand them again, then the system has memory, but it
does not yet have persistent cognition.

Mind Runtime is an attempt to make that boundary explicit. It is not a claim
that the current implementation has solved persistent cognition. It is a
runtime and governance foundation for asking the question in a way that can be
tested, inspected, rejected, and recovered.

## 1. Memory is not understanding

**Problem.** A record that an event occurred is not the same thing as a
durable representation of what the system learned from it.

**Failure mode.** A retrieval layer returns fragments, and the next model call
reconstructs a different interpretation each time. The system appears to
remember while its behavior has no stable continuation.

**MR design consequence.** Evidence, observation, state, projection, memory,
and expression use separate contracts and lifecycle boundaries. Historical
context is an input to a bounded runtime path, not automatically canonical
state.

**Current status.** `IMPLEMENTED` for the current evidence/state/memory
separation and its tests. A complete theory of understanding remains outside
the current runtime.

## 2. Understanding is not authority

**Problem.** A plausible interpretation is not automatically allowed to
change the state that future turns consume.

**Failure mode.** Model output, a retrieval result, or a convenience default
quietly becomes a durable fact or policy decision.

**MR design consequence.** Authority is explicit in contracts, scope,
admission, persistence, and commit boundaries. Model providers produce bounded
semantic candidates; they do not own final numeric state, persona, policy, or
runtime identity.

**Current status.** `IMPLEMENTED` for the current process and pipeline
contracts. Cross-process authority is explicitly unsupported.

## 3. Retrieval is not belief

**Problem.** Retrieval optimizes relevance, not truth, validity, or lifecycle.

**Failure mode.** Similarity or recency is mistaken for authority, or an old
and superseded item is treated as current because it was easy to retrieve.

**MR design consequence.** Retrieval providers sit behind a read seam. The
canonical store and state resolver decide what is admitted, visible, scoped,
and authoritative.

**Current status.** `IMPLEMENTED` for the canonical Memory store, bounded
retrieval/context seam, and optional vector providers. A compiled cognition
head resolver is not implemented.

## 4. Repetition is not evidence

**Problem.** Repeatedly seeing the same assertion can make it look more
credible without adding independent evidence.

**Failure mode.** A model repeats its own earlier conclusion, the system
stores the repetition, and future retrieval amplifies it as if it were new
evidence.

**MR design consequence.** Provenance, source authority, idempotent admission,
causal trace, and bounded historical context are part of the runtime path.
Repeated model output cannot self-authorize a state transition.

**Current status.** `IMPLEMENTED` for current admission and trace contracts;
the broader long-horizon semantics remain an ongoing research concern.

## 5. Model output cannot authorize itself

**Problem.** The component that proposes an interpretation should not be the
component that grants it durable authority.

**Failure mode.** A provider response is written directly into canonical
state, persona, affect, memory, or policy without an independent contract or
commit boundary.

**MR design consequence.** MR keeps provider inputs typed and bounded,
separates projection from canonical state, and admits durable changes through
runtime-owned services and explicit commit/abort behavior.

**Current status.** `IMPLEMENTED` for the current pipeline, expression
guards, state persistence, and provider boundaries. This does not make every
future provider safe by default; new providers require their own review.

## 6. Time changes meaning

**Problem.** A statement's meaning and validity can change as later evidence,
events, and lifecycle transitions arrive.

**Failure mode.** A delayed event rolls state backward, an expired state is
treated as active, or a current projection is confused with a historical
record.

**MR design consequence.** Occurred time and received time are distinct;
validity and relevance are distinct; lifecycle transitions are explicit; and
restart/replay tests exercise delayed and terminal cases.

**Current status.** `IMPLEMENTED` for the current state lifecycle, validity,
relevance, and restart/replay contracts. It is not a claim that all temporal
semantics of human understanding are solved.

## 7. Supersession is not deletion

**Problem.** Replacing a conclusion by deleting its predecessor destroys the
lineage needed to explain why the current state exists.

**Failure mode.** A system keeps only the newest row or picks a maximum
version without preserving transition, evidence, or authority context.

**MR design consequence.** Current MR state uses durable transitions,
provenance, and explicit lifecycle values such as `SUPERSEDED`. Historical
records remain inspectable where the current plane supports them.

**Current status.** `IMPLEMENTED` for the current state/transition model;
committed cognition lineage and a generalized effective-head model remain
`RESEARCH/DESIGN`.

## 8. Unknown is a valid cognitive state

**Problem.** Systems often turn missing, conflicting, or ambiguous information
into a convenient default.

**Failure mode.** An absent binding, unavailable provider, or conflicting
state is silently replaced by the latest, default, or most familiar value.

**MR design consequence.** Binding discovery, scope checks, provider failures,
and uncertain recovery paths fail closed or abstain rather than creating new
authority.

**Current status.** `IMPLEMENTED` for the current binding, admission,
provider, and recovery contracts. It is a runtime behavior, not a claim about
the internal experience of an agent.

## 9. Persistent cognition requires governance

**Problem.** Durable state without inspection, provenance, rollback, and
operational ownership becomes an opaque second model.

**Failure mode.** A system cannot explain which source wrote a state, which
binding it belongs to, whether a restart changed its identity, or whether a
projection was committed.

**MR design consequence.** Runtime identity, physical storage namespaces,
admission, SQLite persistence, telemetry, causal tracing, restart checks, and
read-only Observation Window inspection are first-class boundaries.

**Current status.** `IMPLEMENTED` for the current runtime and deterministic
certification surfaces. Live operations, deployment topology, and external
provider governance require environment-specific gates.

## 10. The model is replaceable; durable cognition should be less model-dependent

**Problem.** If every change of model requires rebuilding the entire history
of understanding, continuity is coupled to one provider's behavior.

**Failure mode.** A model swap changes not only expression quality but the
identity, lifecycle, and authority of the durable state.

**MR design consequence.** MR stores typed, inspectable state and traces, keeps
provider output bounded, and uses deterministic runtime contracts wherever the
current product slice permits. Model-swap certification tests measure what is
preserved.

**Current status.** `IMPLEMENTED` as a tested design direction for the current
runtime planes. It is not full model independence, and Compiled Cognition is
not implemented.

## The boundary between MR and LCE

Mind Runtime and LCE are separate projects.

MR owns the runtime question:

> What state is authorized to participate in cognition now?

LCE owns the research question:

> What longitudinal structure may exist across this history?

MR may bind an optional external LCE adapter, but LCE Core is not part of this
repository. An external structure, candidate, or research result becomes MR
state only through an explicitly reviewed MR-side contract.

## What remains open

Compiled Cognition, Effective Cognition, Cognitive Trajectory, Cognitive
Frontier, committed lineage, and generalized supersession are ongoing
research/design directions. They must not be inferred from the existence of
the current Memory, slow-state, or LCE adapter code. The current repository
keeps those boundaries visible so future work can extend them without silently
changing runtime authority.
