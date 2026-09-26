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

## Optional shared decision-model seam

A bounded decision model such as TypeSafe Jev, a locally hosted Laya model, or a
future specialized classifier is an optional optimization capability. It is not a
second semantic authority and is not a mandatory step in any core MR pipeline.

MR exposes one provider-neutral `DecisionModelPort` for this reusable capability.
Feature modules do not own provider clients or model credentials. Instead, each
feature projects its local bounded state into the shared BOOLEAN / CHOICE / SCORE
decision primitives and consumes only the returned judgment probabilities.

Conceptually:

```text
feature-owned state
    -> feature projection
    -> shared DecisionModelPort
    -> optional judgment result
    -> feature-owned policy

                    DecisionModelPort
                    /       |       \
             retrieval    Thread     LCE
             projection  projection  projection
```

The backend is configured once at composition time. Jev, Laya, or another backend
may replace each other without changing feature contracts.

The capability is parallel and fail-open:

- when no backend is configured, the original baseline pipeline runs unchanged;
- when a backend is unavailable, times out, or returns an invalid response, the
  original baseline pipeline runs unchanged;
- loss of decision compute may reduce quality or increase downstream reasoning cost,
  but must not make Memory, retrieval, Thread, LCE, Affect, or turn commit unavailable.

A decision model never receives mutation authority.

## Primary uses

### Retrieval reranking

The first production-shaped use is semantic reranking after normal retrieval and
canonical revalidation.

```text
BM25 / vector / RRF
    -> candidate Memory IDs
    -> canonical Scope/lifecycle/provenance validation
    -> optional decision rerank
    -> bounded context
```

The decision model judges current relevance. It does not decide whether evidence is
true, authorized, or canonical. Provider text cannot replace canonical Memory content
inside the decision projection.

### LCE reasoning-cost gate

LCE may cheaply discover a candidate structure before invoking an expensive
generative/reasoning consolidator. An optional decision projection may judge whether
that candidate is promising enough to justify the expensive reasoning call.

```text
local/cheap structure discovery
    -> candidate structure
    -> optional decision gate
    -> expensive LLM reasoning when useful
```

Without decision compute, the existing LCE policy proceeds normally. The gate is an
economic optimization, not a correctness dependency. The decision model does not
perform longitudinal synthesis itself and cannot accept a Baseline.

### Thread fuzzy identity resolution

Body/Host semantic understanding already owns the current-turn Thread signal. A
decision model must not repeat the question of whether the turn is a Thread event.

It may optionally assist only when MR already has a Thread signal but deterministic
exact/lexical matching is ambiguous about which existing OPEN Thread is the same
logical line. Without a decision backend, the existing matcher remains the baseline.

### Future bounded projections

Future Affect, Persona, tool-routing, or other features may reuse the same global
DecisionModelPort by adding a feature-specific projection. They must not create a
new model client, API key path, retry stack, or provider-specific contract merely
because the business question differs.

## Explicit non-uses

The decision model is not used for:

- canonical Memory admission or deciding whether raw/history-oriented Memory deserves
  to exist;
- semantic deletion or supersession of historical Memory merely because a newer fact
  exists;
- evidence authenticity, Scope authority, provenance validity, lifecycle validity,
  or temporal authority;
- Body/Host current-turn semantic understanding;
- LCE multi-hop longitudinal synthesis;
- time arithmetic, TTL/expiry, numeric Dynamics, slow-plasticity math;
- provider health, quota, credentials, retry authority, or other machine facts.

Canonical Memory remains history-oriented: preserve admitted facts and provenance,
then organize, retrieve, and interpret them at higher layers.

## Jev integration policy

If TypeSafe Jev is evaluated:

- use the same generic DecisionModelPort as every other backend;
- start in shadow or low-consequence reranking use;
- send only bounded, minimized candidate context;
- never send full Memory/LCE history merely because the context window permits it;
- keep canonical identifiers and authority inside MR;
- pin a concrete model version after thresholds are calibrated;
- a Jev failure must never break canonical Memory commit, retrieval, Thread, LCE,
  Affect, or turn commit;
- do not use Jev for the explicit non-uses above.

The first recommended experiment is canonical-Memory retrieval reranking, followed by
an LCE reasoning-cost gate. Thread fuzzy matching should be added only if the existing
deterministic matcher demonstrates a real error pattern.

Production enforcement requires measurements on MR's own traces rather than generic
benchmark scores.

## Current implementation status

The Body-owned ACTIVE semantic migration and the optional decision capability are
separate implementation tracks.

At the time of acceptance, the repository still contains legacy online semantic
provider wiring and a model-backed appraisal composition path. Those are implementation
debt relative to this decision. Their migration must separately:

1. expose a bounded Host/Body -> MR typed semantic/appraisal proposal seam;
2. remove automatic provider construction from ACTIVE TurnOrchestrator composition;
3. disable/remove certified production dependence on `MR_SEMANTIC_PROVIDER` and
   GLM/Zen credentials;
4. migrate model-backed appraisal parsing to Body-supplied bounded proposals rather
   than introducing another MR-owned online LLM;
5. retain any small-model code only behind explicit LAB/shadow/background modes;
6. update readiness/certification tests so an internal semantic provider is not a
   production-readiness requirement.

The optional decision-model track may be implemented independently because it does
not alter that ACTIVE semantic ownership boundary. It must remain removable and
must preserve the pre-existing baseline behavior when absent.
