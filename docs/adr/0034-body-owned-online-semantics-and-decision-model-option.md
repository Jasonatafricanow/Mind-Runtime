# ADR-0034: Body-owned online semantics and optional decision-model backends

- Status: ACCEPTED
- Date: 2026-09-26
- Clarifies: ADR-0027 and the Host/MR authority boundary
- Does not supersede: deterministic Dynamics, StateBar/Reality authority, canonical Memory authority, or LCE lineage authority

## Decision

Normal interactive cognition must not require a model call owned by Mind Runtime to understand the current user message.

The online ownership boundary is:

```text
user message
    -> Body / Host LLM semantic understanding
    -> bounded typed proposals
       + Reality/State proposal for the current-state owner
       + semantic/appraisal proposal for MR
       + optional Memory/LCE hints
    -> each runtime owner validates and consumes only its own bounded view
    -> MR deterministic state evolution / Intent / Policy / DecisionContext
    -> Body realizes the final response
```

The shared semantic understanding is not a new canonical object, database, bus, or
authority layer. It is a producer-side interpretation that is projected into
consumer-specific contracts. Reality, MR, Memory and LCE retain their own admission
and authority rules.

In ACTIVE interactive mode, MR must not construct or call GLM, Zen, DeepSeek, or
another internal semantic model merely because Body/Host semantics were absent.
Missing or invalid Body-supplied semantic proposals fail closed or degrade through
the explicitly defined non-semantic path; they do not silently authorize a second
online semantic interpreter inside MR.

Existing `SemanticCandidateProvider` implementations and model-backed semantic
experiments are therefore not online authority. They may remain as research,
compatibility, LAB, shadow, or future migration fixtures until removed or relocated.

## Small-model boundary

Small language models remain useful only as optional, bounded background compute,
for example during INTROSPECTIVE / DAYDREAM / SLEEP / DREAM or other nearline/idle
processing.

Permitted roles include:

- clustering or organizing already admitted history;
- proposing candidate links or summaries for later validation;
- preparing latent-discovery candidates for LCE;
- low-cost shadow comparisons.

They remain stateless proposal tools. They do not own facts, current state, Affect,
Persona, Memory, LCE Baseline acceptance, or action authority. Background output is
candidate-only unless admitted by the relevant runtime owner.

## Optional decision-model seam

A decision model such as TypeSafe Jev may be added later as a replaceable backend for
bounded semantic judgments that sit between deterministic retrieval/rules and full
reasoning.

MR must depend on a provider-neutral decision contract (for example a
`DecisionModelPort` / System-One-style port), not on Jev-specific APIs.

Candidate uses, in priority order:

1. Thread candidate fit / continuation matching after local retrieval.
2. Memory or accepted-cognition reranking after BM25/vector/RRF candidate discovery.
3. LCE wake gating: whether a new delta materially changes an accepted longitudinal
   understanding enough to justify full reasoning.
4. Memory consolidation judgments such as duplicate / supersedes / add / unrelated.
5. Other bounded routing or verification questions where code owns the final policy.

A decision model is not a replacement for Body semantic understanding or LCE
multi-hop reasoning. It returns judgments/probabilities only; deterministic runtime
policy owns thresholds and mutation.

## Jev integration policy

If TypeSafe Jev is evaluated:

- start in shadow mode;
- send only bounded, minimized candidate context;
- never send full Memory/LCE history merely because the context window permits it;
- keep canonical identifiers and authority inside MR;
- pin a concrete model version after thresholds are calibrated;
- a Jev failure must never break canonical Memory commit or turn commit;
- do not use Jev for time arithmetic, TTL/expiry, numeric Dynamics, slow-plasticity
  math, provider health/quota, or LCE longitudinal synthesis.

The first recommended experiment is Thread semantic matching, followed by an LCE
wake gate. Production enforcement requires measurements on MR's own traces rather
than generic benchmark scores.

## Current implementation status

This ADR freezes the target boundary and the optional decision-model direction.

At the time of acceptance, the repository still contains legacy online semantic
provider wiring and a model-backed appraisal composition path. Those are implementation
debt relative to this decision, not the target architecture. The migration must
separately:

1. expose a bounded Host/Body -> MR typed semantic/appraisal proposal seam;
2. remove automatic provider construction from ACTIVE TurnOrchestrator composition;
3. disable/remove certified production dependence on `MR_SEMANTIC_PROVIDER` and
   GLM/Zen credentials;
4. migrate model-backed appraisal parsing to Body-supplied bounded proposals rather
   than introducing another MR-owned online LLM;
5. retain any small-model code only behind explicit LAB/shadow/background modes;
6. update readiness/certification tests so an internal semantic provider is not a
   production-readiness requirement.

No Jev runtime wiring is authorized by this ADR. It records the replaceable option
and the boundary it must respect.
