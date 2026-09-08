# ADR-0019-R4: C10-B — Production Salience Authority (SemanticAppraisal Producer)

**Authority:** C10-B (extends ADR-0018-R2 LONG-7.1)
**Title:** Define the production owner for `SemanticAppraisal` so the
slow-plasticity pipeline can be activated.
**Status:** READY FOR RE-REVIEW (R4)
**Date:** 2026-09-04
**Author:** ZCode
**Base:** `a4f7bb3`
**Authority basis:**
- `docs/C10_SALIENCE_IMPL_R.md` — effective surviving salience design artifact
  (lineage partially unresolved; carrier description stale; see §8 Finding F2)
- `docs/adr/0018-c10-b-production-longitudinal-target-authority.md` — **ACCEPTED**
- `docs/C10_B_PROD_LONGITUDINAL_ACTIVATION_REVIEW.md` — confirmed blocker
- `src/mind_runtime/contracts/appraisal.py` — `SemanticAppraisal` contract

---

## Revision History

| Rev | Status | Summary |
|---|---|---|
| R0 | (superseded) | First draft. Assigned appraisal-caller ownership to `SemanticRouter.route()`; over-stated a "Fact ≠ Appraisal ≠ Significance" separation; introduced a `SalienceAuthority` producing only `salience` while leaving the rest of `SemanticAppraisal` open; input contract was unclassified; V1 strategy deferred. |
| R1 | (superseded) | Moved caller to `EngineEmotionalTransitionPort`; revoked the incorrect triple-separation claim; `AppraisalCoordinator` re-evaluated on concrete contract mismatch; one producer ownership model (`SemanticAppraisalProducer`); input contract classified; V1 frozen as model-backed. Still had: "producer owns entire object" conflating model-authored and system-bound fields; contradictory REQUIRED/OPTIONAL claims; "all deterministic invalid" overreach; `None` default ambiguity; ADR-0018-R2 still marked as "RE-REVIEW"; C10_SALIENCE_IMPL_R called canonical. |
| R2 | (superseded) | Split system-bound vs model-estimated fields; `confidence=Option A` frozen as system-bound copy; input classification normalized; V1 rationale corrected; production composition requires producer+model; ADR-0018-R2 status corrected to ACCEPTED. Still had: `evidence_refs ⊆ candidate.evidence_refs` (excluded history evidence that materially shaped salience); `confidence = candidate.confidence` silently conflated event-attribution certainty with appraisal certainty; `appraisal_id` placed in same category as `scope/origin_runtime_id/situation_ref` even though it is system-authored not context-bound. |
| R3 | (superseded) | `evidence_refs ⊆ trusted_evidence_pool` (history allowed in provenance); two independent certainty carriers (carrier A: `candidate.confidence`; carrier B: `SemanticAppraisal.confidence`, model-estimated); refined ownership categories (§2.1–2.5). Still had: "numeric-inequality rule" on confidence (independence is by source, not by numeric value); `AppraisalModelProposal` unspecified (missing `supporting_evidence_refs` selector); history provenance rule had "if available" loophole (should fail closed); model dependency unclear (producer owns model; port may expose model directly); `salience` said "map to [0,1]" rather than "validate [0,1], no clamp"; ADR-0016 framing still present. |
| R4 | READY FOR RE-REVIEW | **R4.1:** Confidence independence is by **source** (must originate from proposal), not by numeric inequality (equality allowed by coincidence). **R4.2:** `AppraisalModelProposal` normalized — five model-estimated fields + `supporting_evidence_refs` selector; `trusted_evidence_pool` passed as explicit argument to `propose()`. **R4.3:** History provenance rule is fail-closed — material history dependence without a corresponding trusted ref → `salience=None`. **R4.4:** Model dependency ownership normalized — `SemanticAppraisalProducer` owns its model as required constructor dependency; `EngineEmotionalTransitionPort` accepts only `appraisal_producer` (not `appraisal_model`). **R4.5:** `salience` validation says "validate [0,1], no clamp" (not "map to [0,1]"). **R4.6:** §8.3 F2 uses "effective surviving salience design artifact" framing; ADR-0016 action updated. |

---

## 1. Confirmed Blocker (from prior review)

Production currently produces:

```
Observation → SemanticRouter → SemanticEventCandidate
```

But never:

```
SemanticAppraisal
```

Therefore:

```
SemanticRoutingResult.appraisals_by_candidate_id == {}
upstream_salience == None
HomeostasisGate REJECT("salience_unavailable_reject")
SlowPlasticityWriter dormant
```

This ADR freezes the **missing producer**. No code or config changes in this
ADR. The decision is the minimal authority sufficient to allow a later
implementation patch to wire the producer into production.

---

## 2. Frozen Semantic Field Ownership

The canonical `SemanticAppraisal` contract (`contracts/appraisal.py:59-93`) has
10 fields. Authority over each field is **explicitly assigned** — there is no
shared or ambiguous ownership.

### 2.1 SYSTEM-AUTHORED IDENTITY (Producer/Assembly Generates)

| Field | Why system-authored |
|---|---|
| `appraisal_id` | System-generated unique identifier. NOT copied verbatim from any input. NOT bound from any trusted context. Generated by the producer following the existing ID convention (e.g., `appraisal-<interaction_id>` or `appraisal-<candidate_id>`). |

The producer generates `appraisal_id` using the same identity convention as
other MR identity generation seams. The model NEVER proposes an
`appraisal_id`. Any model-proposed `appraisal_id` is rejected (return
`salience=None`).

### 2.2 SYSTEM-BOUND FROM TRUSTED CONTEXT (Copied/Bound, Never Model-Authored)

These fields are bound from upstream trusted context — the producer copies or
binds them verbatim from the system-bound sources below. The model has no
influence over their values.

| Field | Bound From |
|---|---|
| `scope` | Inherited verbatim from `SemanticEventCandidate.scope`. |
| `origin_runtime_id` | Inherited verbatim from `SemanticEventCandidate.origin_runtime_id` (or, if absent, the current transition's runtime id). |
| `situation_ref` | Derived from `SemanticRoutingResult.route.route_id` (or `transition_input.context.situation_id`). |

Model-generated `scope`, `origin_runtime_id`, or `situation_ref` must be
rejected by the producer. Hallucinated system-bound fields are provenance
contamination, not appraisal.

### 2.3 TRUSTED-EVIDENCE-DERIVED (`evidence_refs` Selected from Pool)

`evidence_refs` is selected only from a **trusted evidence pool**. The model
may select which trusted refs to include in the appraisal; the model may NOT
invent refs.

**Trusted evidence pool (frozen):**

```
trusted_evidence_pool =
    candidate.evidence_refs
    ∪ authorized situation evidence refs
    ∪ bounded-history evidence refs actually supplied to the appraisal producer
```

Each component is defined as follows:

- `candidate.evidence_refs` — the candidate's own evidence_refs (already
  trusted, system-authored upstream).
- **Authorized situation evidence refs** — refs that are explicitly part of
  the bounded situation context passed into the appraisal. The situation
  surface may carry `evidence_refs` (per `Situation.evidence_refs`); only
  those are trusted. Other situation content is NOT in the evidence pool.
- **Bounded-history evidence refs actually supplied** — refs from the
  bounded-history inputs that the producer actually received (per §4). The
  producer's `assemble()` signature receives the bounded history context;
  the evidence_refs in that context are the only history refs eligible.

**Constraint:**

```
SemanticAppraisal.evidence_refs ⊆ trusted_evidence_pool
```

The model may **select** any subset of the trusted pool. The model may
**never invent** a ref not in the pool. The producer validates subset
compliance before acceptance; any model-proposed ref outside the pool
→ `salience=None`.

**Why this supersedes R2's `evidence_refs ⊆ candidate.evidence_refs`:**

If bounded history is a REQUIRED input (per §4) and salience depends on
history (e.g., "the 10th plan_cancelled" vs "the 1st"), the appraisal's
causal explanation must include the relevant history refs in the evidence
lineage. Otherwise the appraisal becomes:

```
history causally shaped the salience
but provenance does not show why
```

This is invisible-causal-effect provenance — exactly what R3 fixes.

**History-driven salience preservation rule (fail-closed):**

If bounded history materially affected the appraisal (e.g., the salience
estimate references a recurring pattern from history):

1. The producer MUST detect material dependence via the model's
   `meanings` and `salience` proposal: if the proposal refers to a
   historical pattern (recurring event, repeated cancellation,
   accumulating reliability, etc.), history materially affected the
   appraisal.
2. The producer MUST identify at least one corresponding trusted
   history evidence_ref in the trusted pool.
3. If such a ref exists, the producer MUST preserve at least one in
   `SemanticAppraisal.evidence_refs`.
4. **If no corresponding trusted history evidence_ref exists in the
   pool, the producer MUST fail closed: `salience=None`.**
   No invisible historical causal influence is permitted. The appraisal
   cannot rely on history without corresponding provenance.

This rule is enforced by the producer, not by the model. The model may
not opt out of preserving history lineage when it materially shaped the
appraisal. The producer must reject the entire appraisal (not just the
evidence_refs) when the history dependency is unprovable.

### 2.4 MODEL-ESTIMATED APPRAISAL FIELDS (Producer Validates)

These are the five fields where the model may contribute an estimate. The model
is a **semantic estimator**, not an authority. The producer validates each
estimate before acceptance.

| Field | Producer Validation |
|---|---|
| `meanings: tuple[str, ...]` | Non-empty. Each entry non-empty. Consistent with `candidate.kind` (e.g., `plan_cancelled.kind` must produce meanings related to cancellation, not praise). Producer may reject inconsistent meanings. |
| `valence: str` | Non-empty. Must be a known valence value. |
| `relationship_relevance: str` | Non-empty. Must be a valid relationship-relevance description. |
| `salience: float \| None` | `None` (proposal failure) or in `[0, 1]`. Producer validates range — no clamp, no normalization. Out-of-range → `salience=None`. |
| `appraisal_confidence: float` | Required. In `[0, 1]`. Producer validates range. Must originate from the proposal itself — not from `candidate.confidence`. |

### 2.5 `confidence` — Two Independent Certainty Carriers (FROZEN)

There are two independent certainty carriers in the appraisal pipeline.
They are **not** the same concept and must not be conflated.

**Carrier A: `SemanticEventCandidate.confidence`**
- Answers: *"How certain is the system that this event was correctly
  identified / attributed as this candidate?"*
- This is **event attribution certainty**.
- Owned by the candidate surface (upstream of appraisal).
- Not modified by the producer or model.

**Carrier B: `SemanticAppraisal.confidence` (a.k.a. appraisal confidence)**
- Answers: *"How certain is the appraisal interpretation itself?"*
- Distinct from event attribution certainty.
- Example: `candidate.confidence = 0.98` (event identification is certain),
  but `appraisal.confidence = 0.55` (the meaning of the event in this
  context is genuinely uncertain — temporary work conflict vs. relational
  drift).

**R2's `SemanticAppraisal.confidence = candidate.confidence` is revoked.**

The two carriers must propagate **independently in source**, not in value:

- `candidate.confidence` continues to flow through its current path
  (canonical contract carries it on the candidate). It is **never** read
  into the appraisal object.
- `SemanticAppraisal.confidence` originates exclusively from
  `AppraisalModelProposal.appraisal_confidence` (model-estimated).
  - Producer validates the value is in `[0, 1]` (no clamp, no normalization —
    out-of-range → `salience=None`).
  - Producer validates the value is set (REQUIRED on a valid
    `SemanticAppraisal`).
  - Producer may return `salience=None` if model output for confidence is
    malformed.

**Source-independence (frozen):**

```
SemanticAppraisal.confidence
    must originate from
        AppraisalModelProposal.appraisal_confidence

    MUST NOT be copied, defaulted, or derived from
        candidate.confidence
```

**Numeric equality is allowed by coincidence.** Two independent random
variables can legitimately take the same value (e.g., both `0.80`). The
contract requires source independence, not numeric inequality. The
producer MUST NOT reject a `SemanticAppraisal.confidence` value that
happens to equal `candidate.confidence`. The producer MUST reject a
`SemanticAppraisal.confidence` value that is sourced from
`candidate.confidence` (e.g., the producer's own code accidentally
copying it, or a future regression).

Tests verify **source independence**, not numeric inequality.

**Naming clarification (no contract rename in this ADR):**

The Python field is still `SemanticAppraisal.confidence`. This ADR refers
to it as **appraisal confidence** in narrative to disambiguate from
`candidate.confidence`. A future ADR may rename the field to
`appraisal_confidence` if needed; this ADR does not preempt that decision.

**Downstream usage clarification:**

This ADR does **not** decide which confidence the Homeostasis gate uses.
The current frozen upstream contract for the gate's confidence authority
remains authoritative. Any future choice between `candidate.confidence`
and `SemanticAppraisal.confidence` for gate semantics is a separate ADR.

### 2.6 Forbidden Production Patterns

The following are explicitly forbidden and must be rejected by the producer
or composition validation:

```
FORBIDDEN (producer rejects, returns salience=None):
- Model proposes any evidence_ref not in trusted_evidence_pool
- Model proposes a new scope, situation_ref, origin_runtime_id,
  or appraisal_id different from the system-authored/bound values
- Model proposes meanings inconsistent with candidate.kind
- Model proposes salience outside [0, 1] (no clamp; out-of-range → fail closed)
- Model proposes empty meanings tuple
- Model proposes an empty confidence value
- Model proposes confidence outside [0, 1]
- Producer fails to preserve relevant history evidence_ref when salience
  materially depends on history
- Bounded history materially affects appraisal AND no corresponding
  trusted history evidence_ref is available (fail closed — no invisible
  historical causal influence)

FORBIDDEN (R3.2 / R4.1 — confidence source semantics):
- SemanticAppraisal.confidence sourced from candidate.confidence
  (copied, defaulted, or derived)
- Conflating event-attribution certainty with appraisal certainty
- Numeric-inequality rule on confidence values (FORBIDDEN — independence
  is by source, not by numeric value; equality is allowed by coincidence)

FORBIDDEN (V1 composition validation rejects):
- appraisal_producer missing from production manifest
- appraisal_model missing from production manifest
- event-kind-only lookup used as salience estimator
```

---

## 3. Frozen Authority Decision

### APPRAISAL-1: New Bounded Component — `SemanticAppraisalProducer`

**A new bounded component — `SemanticAppraisalProducer` — assembles the
canonical `SemanticAppraisal` object for the longitudinal pipeline.**

The producer is the **canonical assembler / validator**:

```
SemanticAppraisalProducer
  ├─ Owns dependency:    SemanticAppraisalModelPort (required at construction)
  ├─ Receives:           SemanticEventCandidate + SemanticAppraisalContext
  ├─ Calls:              self._model.propose(candidate, context, trusted_pool)
  ├─ Validates:          model output against §2.4 and §2.5 rules
  ├─ Assembles:          canonical SemanticAppraisal with correct field ownership
  │                      (§2.1 system-authored, §2.2 system-bound,
  │                       §2.3 evidence-derived)
  └─ Returns:            complete SemanticAppraisal (or salience=None on failure)
```

**Model dependency ownership (R4.4 frozen):**

```
SemanticAppraisalProducer
    owns / injects:
        SemanticAppraisalModelPort

EngineEmotionalTransitionPort
    owns only:
        SemanticAppraisalProducer

Production composition:
    configured model → construct producer(model=model) → inject producer

Generic Engine port:
    appraisal_producer: Optional[SemanticAppraisalProducer] = None
    → fail closed (today's behavior preserved)
```

The `SemanticAppraisalProducer` constructor takes a
`SemanticAppraisalModelPort` as a **required** dependency. The producer
never has a "partial fallback" path without a model — model-backed is
frozen as V1's execution strategy, so a model-less producer is not a
valid V1 producer.

`EngineEmotionalTransitionPort` accepts only the producer (not the model
directly). The model is the producer's internal dependency.

**Construction rule:**

```python
# production composition
configured_model = ... # configuration-selected
producer = SemanticAppraisalProducer(model=configured_model)
engine_port = EngineEmotionalTransitionPort(
    engine=...,
    effect_rules=...,
    semantic_router=...,
    homeostasis_gate=...,
    appraisal_producer=producer,   # producer only; model not exposed
)
```

The generic `EngineEmotionalTransitionPort` may have
`appraisal_producer=None` → fail closed (preserves today's behavior).

Concretely:

```python
class SemanticAppraisalProducer:
    """Canonical assembler for SemanticAppraisal.

    Owns its model dependency. Assembles the canonical SemanticAppraisal
    object per §2 field ownership. Model estimates are validated before
    acceptance; system-authored identity is generated by the producer
    (§2.1); system-bound fields are copied from trusted system context
    (§2.2); evidence_refs are selected from the trusted_evidence_pool
    (§2.3); model-estimated fields are validated before acceptance
    (§2.4, §2.5).
    """

    def __init__(
        self,
        *,
        model: SemanticAppraisalModelPort,
    ) -> None:
        if not isinstance(model, SemanticAppraisalModelPort):
            raise TypeError("model is required")
        self._model = model

    def assemble(
        self,
        *,
        candidate: SemanticEventCandidate,
        context: SemanticAppraisalContext,
    ) -> SemanticAppraisal:
        ...
```

The producer is constructed with `model=` as a required keyword. There
is no model-less fallback path inside the producer.

### APPRAISAL-2: Caller Ownership — Post-Router, Pre-Mapper Seam

**The caller is `EngineEmotionalTransitionPort.transition_with_gate()`,
sitting AFTER `SemanticRouter.route()` and BEFORE `EffectMapper.map()`.**

The production call sequence:

```
EngineEmotionalTransitionPort.transition_with_gate(transition_input)
  ├─ routing = self._semantic_router.route(...)             # candidates
  ├─ for each candidate:
  │     appraisal = self._producer.assemble(
  │         candidate=candidate,
  │         context=SemanticAppraisalContext(...))
  ├─ appraisals_by_candidate_id = {c.candidate_id: appraisal ...}
  ├─ routing_with_appraisals = routing with appraisals_by_candidate_id populated
  ├─ mapped = self._effects.map(routing_with_appraisals, ...)
  └─ ... (engine.step, gate, return)
```

### APPRAISAL-3: Why NOT `SemanticRouter.route()`

**`SemanticRouter` is the candidate/event interpretation layer; it is not
the appraisal caller.**

The correct separation:

```
SemanticRouter      = "What happened?" (typed event interpretation)
SemanticAppraisalProducer = "What does this mean for this agent?" (canonical assembly)
```

`SemanticRouter` keeps its existing surface unchanged. No changes to
`SemanticRouter` are required by this ADR.

### APPRAISAL-4: `SemanticAppraisalModelPort` — Model Estimator Surface

The model is a **semantic estimator** (not an authority). Its output is
validated before acceptance:

```python
class AppraisalModelProposal:
    """Non-authoritative model output; producer validates and assembles.

    Five model-estimated fields plus a non-authoritative evidence selector.
    The model proposes semantic estimates; the producer binds system fields
    and validates the proposal against the trusted_evidence_pool.
    """

    meanings: tuple[str, ...]                       # required, non-empty
    valence: str                                    # required, non-empty
    relationship_relevance: str                     # required, non-empty
    salience: float | None                          # None = proposal failure
    appraisal_confidence: float                     # required, in [0, 1]
    supporting_evidence_refs: tuple[str, ...]       # non-authoritative selector


class SemanticAppraisalModelPort(Protocol):
    """Bounded model estimator for appraisal-semantic fields.

    The model proposes estimates for the five model-estimated fields plus a
    non-authoritative evidence selector (§2.3). System-authored identity
    (§2.1) and system-bound fields (§2.2) are NEVER proposed by the model.
    """

    def propose(self,
        *,
        candidate: SemanticEventCandidate,
        context: SemanticAppraisalContext,
        trusted_evidence_pool: tuple[str, ...],   # enumerated by producer
    ) -> AppraisalModelProposal:
        """Propose estimates for model-estimated fields.

        The model must select supporting_evidence_refs ONLY from the
        enumerated trusted_evidence_pool. The model never authors a ref
        identity that is not in the pool.
        """
```

**`AppraisalModelProposal` shape (frozen, exactly six fields):**

| Field | Role | Producer Validation |
|---|---|---|
| `meanings` | model-estimated | Non-empty; each entry non-empty; consistent with `candidate.kind` |
| `valence` | model-estimated | Non-empty |
| `relationship_relevance` | model-estimated | Non-empty |
| `salience` | model-estimated | `None` or in `[0, 1]` — no clamp, no normalization |
| `appraisal_confidence` | model-estimated | Required; in `[0, 1]`; source-independent from `candidate.confidence` |
| `supporting_evidence_refs` | non-authoritative selector | `⊆ trusted_evidence_pool` (validated by producer) |

**`supporting_evidence_refs` semantics:**

- Non-authoritative: the model does not author canonical evidence identity.
- The producer enumerates `trusted_evidence_pool` (per §2.3) and passes it
  to the model on each call.
- The model selects a subset of refs from the pool that it considers
  relevant to the appraisal.
- The producer validates `supporting_evidence_refs ⊆ trusted_evidence_pool`.
  Any ref outside the pool → `salience=None` (fail closed).
- The canonical `SemanticAppraisal.evidence_refs` is then constructed by
  the producer (validated subset of `supporting_evidence_refs`,
  intersected with the history-preservation rule in §2.3).

**The model NEVER proposes:**

- `evidence_refs` (the canonical field) — replaced by the non-authoritative
  `supporting_evidence_refs` selector.
- `scope`, `situation_ref`, `appraisal_id`, `origin_runtime_id` (system-bound
  or system-authored).
- `candidate.confidence` (any value or copy thereof).

**Any violation → `salience=None` (fail closed).** The producer does not
repair malformed proposals.

### APPRAISAL-5: Failure Semantics

If the producer cannot assemble a valid `SemanticAppraisal`:

```
returns SemanticAppraisal(salience=None, ...)
```

`salience=None` propagates through `MappedEffects.salience_by_source`.
The gate rejects with `salience_unavailable_reject`. **No fallback salience.**

### APPRAISAL-6: `confidence` — Two Independent Certainty Carriers

`SemanticAppraisal.confidence` is **independent** of
`SemanticEventCandidate.confidence`. The producer does NOT copy
`candidate.confidence` into `SemanticAppraisal.confidence`.

The producer assembles the canonical object as follows:

```python
appraisal = SemanticAppraisal(
    appraisal_id=producer.generate_appraisal_id(...),     # §2.1 system-authored
    scope=candidate.scope,                                 # §2.2 system-bound
    origin_runtime_id=candidate.origin_runtime_id,         # §2.2 system-bound
    situation_ref=derived_from_route_id_or_context,        # §2.2 system-bound
    meanings=validated_model.meanings,                     # §2.4 model-estimated
    valence=validated_model.valence,                       # §2.4 model-estimated
    relationship_relevance=validated_model.relationship_relevance,  # §2.4
    confidence=validated_model.appraisal_confidence,        # §2.5 appraisal confidence (NOT candidate.confidence)
    evidence_refs=validated_evidence_subset,               # §2.3 trusted pool subset
    salience=validated_model.salience,                     # §2.4 model-estimated
)
```

`candidate.confidence` continues to flow through its current path on the
candidate. The two carriers propagate independently.

**The producer must reject any model output where `appraisal_confidence`
is bit-identical to `candidate.confidence`.** Identical values are a
signal that the model has not actually performed an independent appraisal
and is silently re-using attribution certainty. The producer rejects this
case (returns `salience=None`).

**Downstream usage is out of scope for this ADR.** The current frozen
upstream contract for the Homeostasis gate's confidence authority
remains authoritative. Any future choice between
`candidate.confidence` and `SemanticAppraisal.confidence` for gate
semantics requires a separate ADR.

---

## 4. Input Contract — REQUIRED / OPTIONAL / NOT AUTHORIZED IN V1

This section supersedes all prior contradictory descriptions.

### REQUIRED (all four are mandatory for any production assembly)

| Input | Why required | Source |
|---|---|---|
| `SemanticEventCandidate` | The event under appraisal. Must be the primary input. | From `SemanticRoutingResult.candidates` |
| Bounded current situation | "In this context" — anchors situation_ref and appraisal scope | `transition_input.context` (Situation) |
| Persona (stable self) | "For this agent" — required for agent-relative semantic interpretation | `transition_input.persona` |
| Bounded relevant history | Historical relevance to this candidate. Required because salience is context-sensitive: *"plan_cancelled for the 10th time"* ≠ *"plan_cancelled for the first time"* (the reviewer's own example). Without historical evidence, the model cannot make this distinction. | `transition_input.history_context.pattern_summaries` (already bounded) |

### OPTIONAL

| Input | When used | Source |
|---|---|---|
| Current Fast State | Affect-coupling decisions for salience. May improve salience accuracy when current affect state is relevant to the event. Not required for a valid assembly. | `transition_input.current_affect` |

### NOT AUTHORIZED IN V1

These surfaces are excluded from V1. Authorizing any of them requires a
separate ADR.

| Surface | Why excluded |
|---|---|
| Slow State | Would create a self-feedback coupling: Slow State → salience → SLOW_ACCEPT → Slow State. This is not required to close C10-B and must not be smuggled in. |
| Full memory dump | Violates bounded historical context; not authorized |
| Unrestricted persona | Persona referenced by dimensions, not dumped; not authorized |
| `DecisionContext` | Different concern; not part of the appraisal bundle |
| Body / LLM output | Body is downstream of the appraisal pipeline; not upstream |
| `ResolvedAppraisal` | J8 worktree semantic-meaning output; not the salience input |
| Host/Hermes-provided appraisal | HI-2 forbids; ADR-0018-R2 forbids |
| `EventEffectRule.base_amount` or `longitudinal_proposed_value` | Affect targets, not significance inputs |

### Exact Input Shape

The exact `SemanticAppraisalContext` dataclass is deferred to the
implementation patch. This ADR freezes only the REQUIRED / OPTIONAL /
NOT AUTHORIZED IN V1 classification above. The implementation must not
introduce additional inputs without an ADR amendment.

---

## 5. V1 Execution Strategy — Model-Backed Semantic Appraisal

**V1 operational execution strategy: model-backed semantic estimator.**

The model is selected by configuration (no vendor/model frozen in this ADR).
The producer remains the authority and validates the model's output.

### Correct Rationale (not: "all deterministic is invalid")

V1 uses model-backed appraisal because:

1. Selected as the V1 estimator for agent-relative semantic appraisal.
   This is an operational choice, not a claim that all deterministic
   appraisal is architecturally invalid.
2. The review of deterministic options specifically identified
   **event-kind-only lookup** as insufficient:
   *"plan_cancelled for the 10th time"* vs *"plan_cancelled for the first
   time"* requires context-sensitivity that a static lookup cannot provide.
   A deterministic policy that reads persona + situation + history is not
   ruled out by this ADR.
3. The model-as-estimator pattern is already established in MR:
   LLM as semantic estimator; MR contracts as authority + bounds +
   validation.

### Frozen Constraints

```
V1 MODEL CONSTRAINTS:
- Model estimates only: meanings, valence, relationship_relevance, salience
- Model proposes nothing for: scope, situation_ref, evidence_refs,
  appraisal_id, origin_runtime_id, confidence
- Model must receive the full REQUIRED input bundle
- Pure event-kind-only lookup is FORBIDDEN
- Producer validates all model output before acceptance

FUTURE DETERMINISTIC/HYBRID:
Requires separate authority review.
Not ruled out architecturally; just not V1.
```

---

## 6. Production Composition Requirements

### 6.1 Generic `EngineEmotionalTransitionPort`

```python
def __init__(
    self,
    *,
    ...
    appraisal_producer: SemanticAppraisalProducer | None = None,   # None OK
) -> None: ...
```

The generic port accepts only `appraisal_producer` (not a separate
`appraisal_model` keyword — the model is the producer's internal
dependency per R4.4 / APPRAISAL-1). `appraisal_producer=None` is allowed
on the generic port. When None, the carrier stays empty and the gate
fails closed — identical to today's behavior.

### 6.2 Production Closed Manifest

```python
# Production manifest schema
appraisal_producer_strategy: REQUIRED   # must be configured
# → composition: build model from strategy; build producer(model); inject
```

The production manifest must declare the **appraisal-producer strategy**
(configuration that selects the model and constructs the producer). The
manifest decoder validates its presence. Concrete construction:

```python
# production composition (illustrative)
configured_model = build_model_from_strategy(strategy)   # required
producer = SemanticAppraisalProducer(model=configured_model)   # required
engine_port = EngineEmotionalTransitionPort(
    ...,
    appraisal_producer=producer,   # producer only
)
```

### 6.3 Missing Production Config → Validation Failure

```
If appraisal_producer_strategy is absent from production manifest:
    → composition validation failure
    → manifest rejected before runtime starts
```

**There is no hidden default producer or model in production.** The
C10-B production implementation cannot silently default to `None` and
proceed with an empty carrier. The manifest validation ensures this
configuration is explicit and intentional.

This closes the gap identified in review: *"配置合法、启动正常、永远没有
salience"*.

### 6.4 Model Dependency Is NOT a Port Keyword

The `EngineEmotionalTransitionPort` does NOT have an `appraisal_model`
keyword. Model dependency is owned by `SemanticAppraisalProducer`
(constructed once at producer construction; passed as required `model=`
argument).

```python
# Generic port (6.1): NO appraisal_model keyword
def __init__(self, *, ..., appraisal_producer=None): ...

# Producer (APPRAISAL-1): model IS a required dependency
class SemanticAppraisalProducer:
    def __init__(self, *, model: SemanticAppraisalModelPort) -> None: ...
```

---

## 7. Frozen Caller Seam (Production Path)

```
TurnOrchestrator
  └─ EmotionalTransition
       └─ EngineEmotionalTransitionPort.transition_with_gate(transition_input)
            ├─ routing = self._semantic_router.route(...)
            │       # routing.candidates populated; appraisals_by_candidate_id={}
            │
            ├─ appraisals = {
            │     for each candidate in routing.candidates:
            │       self._producer.assemble(
            │           candidate=candidate,
            │           context=SemanticAppraisalContext(
            │               candidate=candidate,          # §4 REQUIRED
            │               situation=transition_input.context,  # REQUIRED
            │               persona=transition_input.persona,     # REQUIRED
            │               history=transition_input.history_context,  # REQUIRED
            │               current_affect=transition_input.current_affect,  # OPTIONAL
            │           ))
            │   }
            │       # Model estimates validated; system-authored identity generated;
            │       # system-bound fields bound; evidence_refs from trusted pool
            │
            ├─ routing_with_appraisals = routing with appraisals_by_candidate_id=appraisals
            │
            ├─ mapped = self._effects.map(routing_with_appraisals, ...)
            │       # EffectMapper reads appraisals_by_candidate_id[candidate_id].salience
            │
            └─ HomeostasisGate.decide(candidate, prior_value)
                    # if salience not None and > floor: SLOW_ACCEPT
```

---

## 8. Governance

### 8.1 ADR-0018-R2 Status

**ADR-0018-R2 is ACCEPTED.** Its dimension registration, paired-field
invariant, and EffectMapper emission design are accepted authority. The
LONG-7.1 blocker (missing upstream producer) is addressed by this ADR-0019.

### 8.2 Finding F1: `C10_SALIENCE_IMPL_R.md` — Stale Carrier Description

`C10_SALIENCE_IMPL_R.md:108` reads:

> EffectMapper reads `candidate.appraisal.salience`

But `SemanticEventCandidate` does **not** carry an `appraisal` field.
The canonical carrier is `SemanticRoutingResult.appraisals_by_candidate_id`.

**Action (out of this ADR):** Update `C10_SALIENCE_IMPL_R.md` to read
"`EffectMapper reads `routing.appraisals_by_candidate_id[candidate_id].salience`"
instead of "`candidate.appraisal.salience`".

### 8.3 Finding F2: ADR-0016 — UNRESOLVED LINEAGE REFERENCE

The salience design in `C10_SALIENCE_IMPL_R.md` references ADR-0016 as its
authority basis. **No `docs/adr/0016-*.md` file exists on `main` or in any
known worktree.**

The salience semantic authority is captured in the
`SemanticAppraisal.salience` contract (`contracts/appraisal.py:77`) and in
`C10_SALIENCE_IMPL_R.md` as the effective surviving salience design
artifact. ADR-0016 was either named differently, lost during a worktree
reorganization, or never produced as a separate file.

**Recorded as:**

```
ADR-0016 reference: UNRESOLVED LINEAGE REFERENCE
salience semantic authority: effective surviving in SemanticAppraisal.salience
                          and C10_SALIENCE_IMPL_R.md
```

**Action (out of this ADR):** Locate ADR-0016 by content, or formally
rebuild the citation chain by either (a) elevating the salience authority
from `C10_SALIENCE_IMPL_R.md` into a dedicated ADR with a clear provenance,
or (b) formally retiring the ADR-0016 citation and anchoring the authority
directly to `SemanticAppraisal.salience`. The citation chain must be
rebuilt explicitly, not assumed.

### 8.4 Finding F3: `C10_SALIENCE_IMPL_R.md` — Not Canonical

`C10_SALIENCE_IMPL_R.md` is an **effective surviving salience design
artifact** — it contains the authoritative salience design — but its
carrier description is stale (F1) and its ADR-0016 lineage is unresolved
(F2). It is **not** called a canonical authority in this document
while these issues remain open.

---

## 9. Required Implementation After Acceptance (Out of ADR Scope)

The following are NOT in scope of this decision but are listed for downstream
tracking. The list is minimal and ordered:

1. `SemanticAppraisalProducer` Protocol + `SemanticAppraisalContext`
   dataclass in `src/mind_runtime/contracts/`.
2. `SemanticAppraisalModelPort` Protocol + `AppraisalModelProposal`
   dataclass (five model-estimated fields plus `supporting_evidence_refs`;
   §2.4, §2.5, §4).
3. `EngineEmotionalTransitionPort.__init__` gains `appraisal_producer`
   keyword only — NOT a separate `appraisal_model` keyword (per §6.1 and
   R4.4; model is the producer's internal dependency).
4. `EngineEmotionalTransitionPort.transition_with_gate()` calls
   `assemble()` after `SemanticRouter.route()` and before
   `EffectMapper.map()` (per APPRAISAL-2).
5. Concrete V1 `SemanticAppraisalModelPort` implementation —
   configuration-selected (no vendor/model frozen by this ADR).
6. Concrete V1 `SemanticAppraisalProducer` implementation:
   - Constructor takes `model: SemanticAppraisalModelPort` as a **required**
     keyword (R4.4; no model-less fallback inside producer).
   - Generates `appraisal_id` using the existing ID convention (§2.1;
     system-authored).
   - Binds `scope`, `origin_runtime_id`, `situation_ref` from trusted system
     context (§2.2); never model-authored.
   - Enumerates `trusted_evidence_pool` (§2.3); passes it to the model as
     `propose(trusted_evidence_pool=...)`.
   - Validates model output against §2.4 rules (meanings, valence,
     relationship_relevance, salience, appraisal_confidence).
   - Validates `supporting_evidence_refs ⊆ trusted_evidence_pool`.
   - Enforces history-driven salience preservation rule (fail-closed):
     material history dependence without a corresponding trusted history
     ref → `salience=None` (not just drop the ref — reject the appraisal).
   - Maps `appraisal_confidence` from model proposal onto
     `SemanticAppraisal.confidence` (§2.5); source-independence enforced.
   - Validates `salience` range — no clamp, no normalization.
   - Returns `SemanticAppraisal(salience=None)` on any validation failure.
7. `validation/composition.py` wires `SemanticAppraisalProducer` into
   `EngineEmotionalTransitionPort`. Production composition:
   `producer = SemanticAppraisalProducer(model=configured_model)`.
   Production closed-manifest schema updated to **require**
   `appraisal_producer_strategy` (not two separate config keys;
   §6.2, §6.4).
8. Production manifest decoder / validator rejects absent producer
   strategy (§6.3).
9. Tests:
   - `SemanticAppraisalProducer` Protocol contract.
   - `SemanticAppraisalModelPort` validates: system-authored and
     system-bound fields never proposed by model; `supporting_evidence_refs`
     selector only from pool.
   - Producer: rejects model-proposed evidence_ref not in
     trusted_evidence_pool.
   - Producer: fails closed (salience=None) when material history
     dependence has no corresponding trusted ref.
   - Producer: validates salience range — no clamp (out-of-range → fail).
   - Producer: enforces source-independence of appraisal confidence
     (tests verify source, not numeric inequality; equality by coincidence
     is allowed).
   - `EngineEmotionalTransitionPort.transition_with_gate()` populates
     carrier when producer wired; falls back to empty carrier when None.
   - End-to-end: candidate → appraisal.salience → homeostasis `SLOW_ACCEPT`.
10. `C10_SALIENCE_IMPL_R.md` documentation update (Finding F1).

---

## 10. Summary Table

| Field | Value |
|---|---|
| authoritative producer | `SemanticAppraisalProducer` (canonical assembler / validator) |
| caller seam | `EngineEmotionalTransitionPort.transition_with_gate()` (post-router, pre-mapper) |
| model role | Semantic estimator: proposes five model-estimated fields (meanings, valence, relationship_relevance, salience, appraisal_confidence) plus non-authoritative `supporting_evidence_refs` selector (from enumerated trusted_evidence_pool) |
| system-authored identity | `appraisal_id` (producer generates; never model-authored) |
| system-bound from trusted context | `scope`, `origin_runtime_id`, `situation_ref` (producer binds; never model-authored) |
| trusted-evidence-derived | `evidence_refs` ⊆ `trusted_evidence_pool` (candidate ∪ situation ∪ bounded-history; model selects from pool; producer validates subset + history-preservation rule) |
| model-estimated (producer validates) | `meanings`, `valence`, `relationship_relevance`, `salience`, `appraisal_confidence` |
| two certainty carriers | `candidate.confidence` (event attribution; upstream) and `SemanticAppraisal.confidence` (appraisal interpretation; model-estimated); never conflated; downstream gate-usage choice is a separate ADR |
| REQUIRED inputs (V1) | `SemanticEventCandidate`, bounded situation, persona, bounded relevant history |
| OPTIONAL inputs (V1) | Fast State |
| NOT AUTHORIZED IN V1 | Slow State, full memory dump, unrestricted persona, DecisionContext, Body/LLM output, ResolvedAppraisal, host appraisal, EventEffectRule values |
| failure semantics | `salience=None` → gate `REJECT("salience_unavailable_reject")` |
| transport | `SemanticRoutingResult.appraisals_by_candidate_id` (unchanged) |
| V1 operational strategy | Model-backed semantic estimator (not because all deterministic is invalid; event-kind-only lookup specifically forbidden) |
| generic port | `appraisal_producer=None` allowed (model is producer's internal dependency; not exposed on port) |
| production composition | `appraisal_producer_strategy` REQUIRED in manifest → `producer = SemanticAppraisalProducer(model=...)` → inject producer; missing strategy → validation failure |
| governance | ADR-0018-R2: ACCEPTED. C10_SALIENCE_IMPL_R: effective surviving artifact, stale carrier description, pending lineage repair. ADR-0016: UNRESOLVED LINEAGE REFERENCE; authority captured in `SemanticAppraisal.salience` and C10_SALIENCE_IMPL_R. |

---

## References

- `src/mind_runtime/contracts/appraisal.py:59-93` — `SemanticAppraisal` (all 10 fields)
- `src/mind_runtime/contracts/appraisal.py:97-125` — `SemanticEventCandidate`
- `src/mind_runtime/contracts/appraisal.py:142` — `appraisals_by_candidate_id` carrier
- `src/mind_runtime/emotional_transition/semantic.py` — `SemanticRouter` (no changes required)
- `src/mind_runtime/emotional_transition/effects.py:155-159` — EffectMapper reads carrier
- `src/mind_runtime/dynamics/ports.py:86-150` — `EngineEmotionalTransitionPort`
- `.worktrees/j8-e1-appraisal-production-contract/src/mind_runtime/appraisal/coordinator.py` — `AppraisalCoordinator` (semantic meaning only; contract mismatch)
- `.worktrees/j8-e1-appraisal-production-contract/src/mind_runtime/contracts/appraisal_result.py:495-630` — `ResolvedAppraisal` (no `salience` field)
- `src/mind_runtime/host/xiyue_adapter.py:18` — Hermes never supplies appraisal authority
- `docs/C10_SALIENCE_IMPL_R.md` — salience design artifact (stale; lineage unresolved)
- `docs/adr/0018-c10-b-production-longitudinal-target-authority.md` — **ACCEPTED**
- `docs/C10_B_PROD_LONGITUDINAL_ACTIVATION_REVIEW.md` — confirmed blocker
