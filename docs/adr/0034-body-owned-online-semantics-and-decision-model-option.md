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

## 2026-09-27 correction: open semantics and one Body inference

The ACTIVE Body contract is not a finite event taxonomy. Natural-language
meaning remains open-ended. The Body may optionally attach an event hint for
legacy/LAB consumers, but ACTIVE Affect must not require or branch on that hint.

One normal Body inference produces both:

- the user-visible reply; and
- a hidden semantic sidecar for runtime consumers.

MR must not trigger a second semantic/model inference for the current message.
The Host may use provider-native metadata when available; a tagged structured
sidecar is the portable fallback. In both cases the model is invoked once.

The MR sidecar uses open meanings plus sparse bounded appraisal factors. These
factors describe causal properties such as separation, threat, uncertainty,
obstruction, opportunity or relationship relevance. They are not affect
deltas. The Body cannot write current Affect or choose target affect
dimensions.

The ACTIVE causal direction is therefore:

```text
previous committed MR context
    -> one Body inference
       -> user-visible reply
       -> open semantic/appraisal sidecar
    -> MR validates authority/evidence
    -> MR deterministic appraisal-factor projection
    -> Dynamics / Intent / Policy / canonical update
```

Current-turn canonical updates affect subsequent continuity and proactive
behavior. The current natural-language reply is already generated from the
Body's immediate understanding plus the previous committed MR context; MR does
not buy a second model call merely to regenerate that same reply.

Legacy `SemanticEventCandidate -> EventEffectRule(event_kind)` mapping remains
available for replay/LAB compatibility. It is not the ACTIVE Body affect
algorithm.

## Current implementation status

The ACTIVE online semantic cutover uses the Body-owned single-pass path:

1. Host/Body supplies versioned `BodySemanticFrame` items containing open
   meanings and sparse appraisal factors.
2. The Host adapter binds MR-owned Scope, runtime identity, and admitted
   Evidence. Body cannot author those authority fields or affect deltas.
3. Internally, the existing semantic candidate/appraisal records remain as
   compatibility carriers for journal/lineage, but Body frames use the fixed
   internal kind `__body_semantic__`; optional event hints are metadata only.
4. Accepted Body appraisal factors are projected into bounded Affect impulses by
   MR's deterministic causal recipe. EventEffectRule is not consulted for that
   ACTIVE path.
5. `TurnOrchestrator` no longer auto-constructs a semantic provider from
   process environment.
6. ACTIVE Xiyue/certification composition does not require GLM/Zen or a
   model-backed appraisal provider.
7. The durable appraisal journal/application-receipt path remains in MR because
   MR still owns validation, Dynamics application and commit.
8. Legacy semantic/provider and event-rule implementations remain for
   LAB/shadow/replay compatibility only.

The Host must obtain the sidecar from the same Body inference that generates the
reply. Missing/invalid sidecar data degrades to no semantic affect contribution;
MR does not silently invoke another online model.

The optional decision-model capability remains independent and fail-open; its
presence or absence does not change this semantic ownership boundary.

