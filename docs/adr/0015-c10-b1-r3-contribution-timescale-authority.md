# ADR-0015 — C10-B1-R3 Contribution Timescale Authority Contract

**Status:** ACCEPTED (pending independent review per C10-B1-R3 §18)
**Ticket:** C10-B1-R3
**Author:** ZCode
**Date:** 2026-09-02 (revised)
**Authority basis:**
- ADR-0017 (`e808ccf`) — ResolvedAppraisal → ordinary Impulse boundary
- ADR-C10-A1 (`1db6e74`) — three-layer plasticity + Homeostasis Gate authority
- C10-B1 (`6163b1f`) — HomeostasisGate Protocol + SalienceThresholdPolicy
- C10-B1-R1 (`199812f`) — authority-closure audit
- C10-B1-R2 (`3214b23`) — capability reframe; dual-axis model locked
- J8-E3-G4 (`cbb2ff1`) — appraisal rule contract frozen; H1–H25; H19/H20
- C10-B2 (`fe2656e`) — Persona Promotion Gate
- `docs/C10_B1_R3_CONTRIBUTION_TIMESCALE_CONTRACT.md` (companion spec)

---

## Context

The `C10-B1` Homeostasis Gate was implemented in `6163b1f` with a
correct protocol (`HomeostasisGate`, `SalienceThresholdPolicy`,
`SalienceThresholdConfig`) and a correct architectural skeleton. The
implementation was frozen before the contribution-timescale semantics
contract was written, leaving C10-B1 open with a single blocker:

> "What is the authority and semantics of each contribution kind in the
> dynamics result? What does the Gate own, and what must it leave
> untouched?"

C10-B1-R2 (`3214b23`) locked the dual-axis model:

```text
Dimension axis    = property of AffectiveDimensionProfile (recovery_rate,
                  sensitivity, floor, ceiling, baseline)
                  owned by Dynamics, never touched by Homeostasis

Contribution axis = property of the per-turn candidate (event, history,
                  appraisal, recovery, coupling)
                  owned by the Homeostasis Gate and its policy
```

R3 completes the contribution axis by answering all outstanding
semantics questions that R2 explicitly deferred.

**R3 is post-implementation semantic reconciliation.** It is not a
pre-implementation design exercise. The `6163b1f` implementation
exists. R3 freezes the authority/semantics/seam contract surface
against which that implementation will be conformance-audited. The
next ticket after R3 is **not** "C10-B1 Implementation" (from-scratch)
but rather **C10-B1 Conformance Audit** (KEEP / ADAPT / REPLACE of
the existing implementation).

---

## Decision

R3 freezes the following contracts.

### 1. Contribution Kind Taxonomy

Five contribution kinds, each with locked semantics:

```text
RECOVERY           time-driven return-to-baseline
                   policy-owned (ContinuousReturnToBaselinePolicy)
                   NOT a candidate for Homeostasis Gate

ORDINARY_IMPULSE   bounded event/history/appraisal impulse
                   configuration-owned rule base_amount
                   ELIGIBLE for Homeostasis Gate

SHOCK_IMPULSE      ORDINARY_IMPULSE with shock classification
                   bypasses ordinary damping only
                   never bypasses floor/ceiling clamp
                   never bypasses Persona Promotion Gate
                   NOT a separate state layer

COUPLING           derived consequence of an already-authorized
                   net transition; deterministic spread at configured
                   strength; NOT independently classified;
                   NOT independently gated; NOT re-routed through
                   the Gate (§4)

RELATIONSHIP_MOD   relationship-scope modifier via relationship_modifiers
                   param; currently UNWIRED (dormant contract per
                   ADR-C10-A1 §6.4); future wiring must route through
                   commit_turn
```

No production enum is added. The existing `source_kind` /
`source_ref` on `AssessmentContribution` carries this information.

### 2. Shock Authority (Split — Model C)

```text
FINAL SHOCK CLASSIFICATION AUTHORITY
= runtime-owned deterministic C10 policy boundary
= HomeostasisGate.decide(...)  (the Protocol boundary)
≠ SalienceThresholdPolicy       (a CANDIDATE implementation, not
                                 the boundary itself; subject to
                                 conformance audit after R3 ACCEPTED)
```

**Why the decoupling from SalienceThresholdPolicy:**
`SalienceThresholdPolicy` is the implementation shipped in `6163b1f`,
before the R3 semantic contract existed. R3 defines what shock /
salience / contribution class mean. Canonizing `SalienceThresholdPolicy`
as the canonical classifier in the same ticket that defines the contract
inverts the authority order: it lets implementation precede contract.
The correct order is: contract defines the boundary, implementation
conforms to it (or is flagged in the conformance audit).

**Three-model evaluation:**

| Aspect | Model A (Pure semantic) | Model B (Pure numeric) | Model C (Split — frozen) |
|---|---|---|---|
| Who proposes | LLM | configuration | LLM + configuration + runtime |
| Who classifies | LLM | configuration | runtime boundary |
| Bypass authority | LLM owns it (FORBIDDEN by ADR-0017 + J8-E3 H20) | config owns it (under-discriminates: large pleasantry → shock; identity betrayal → no shock) | runtime boundary owns it, subject to H6 evidence + config rule eligibility + confidence asymmetry |
| Compliance | violates H20 | compatible but insufficient | compatible |

**Split authority steps:**

```text
Step 1  LLM proposes via typed attribute
         (salience_class ∈ {ordinary, notable, shock_candidate}
          or shock_candidate ∈ {true, false})
         PROPOSAL ONLY, not classification

Step 2  Configuration gates
         (EventEffectRule / AppraisalAffectRule carries
          shock_eligible: bool; must be true for any shock
          classification to be valid)

Step 3  Runtime classifies
         (HomeostasisGate.decide receives:
            semantic_proposal, numeric_effect_size,
            provider_confidence, evidence_refs,
            runtime_applicability)
         Returns HomeostasisDisposition ∈ {FAST_APPLY, SLOW_ACCEPT, ...}
         FAST_APPLY on a SHOCK_IMPULSE = bypass ordinary damping
         FAST_APPLY on an ORDINARY_IMPULSE = apply full amount, no damping
```

**Veto rules (any single veto flips disposition to FAST_ONLY or REJECT):**

```text
V1: evidence_refs is empty           → REJECT for any SLOW_* (H6)
V2: provider_confidence < 0.5        → REJECT for any SLOW_*
V3: runtime_applicability != APPLICABLE → REJECT
V4: |base_amount| > MAX_SAFE_AMPLITUDE → clamp is still applied
    (never bypassed by SHOCK_IMPULSE)
```

**Confidence asymmetry (frozen — R3-F2):**

The LLM/proposal/provider may emit a `provider_confidence`. This value
enters the composite salience function ONLY as a lower bound / veto,
never as an amplifier:

```text
Provider confidence MAY:
    - lower trust in the candidate
    - cause abstention
    - fail closed (REJECT)
    - prevent shock promotion (Veto Rule V2)
    - reduce salience composite

Provider confidence MUST NOT:
    - increase semantic salience
    - increase numeric effect
    - promote ORDINARY → SHOCK
    - independently authorize bypass

Mathematical constraint:
    ∂ shock_classification_authority / ∂ provider_confidence ≤ 0
```

**Bypass boundaries (hard — B1..B4):**

```text
B1: SHOCK_IMPULSE MAY bypass ordinary damping
B2: SHOCK_IMPULSE MAY NOT bypass floor/ceiling clamp
B3: SHOCK_IMPULSE MAY NOT bypass the Homeostasis Gate itself
B4: SHOCK_IMPULSE MAY NOT mutate PersonaProfile / baseline /
    recovery_rate directly
```

### 3. Homeostasis Eligibility Matrix

| Kind | Gate-eligible | Damped | Rejected | Bypass ordinary damping | Clamped |
|---|---|---|---|---|---|
| RECOVERY | NO | NO | NO | N/A | final value clamped (Dynamics) |
| ORDINARY_IMPULSE | YES | FAST_ONLY / SLOW_DAMP | REJECT | NO | final value clamped |
| SHOCK_IMPULSE | YES | NO (damping bypassed) | REJECT | YES (ordinary damping only) | final value clamped (never bypassed) |
| COUPLING | NO | NO | NO | N/A | spread clamped (inherits upstream authorization) |
| RELATIONSHIP_MOD | NO | NO | NO | N/A | same as ORDINARY_IMPULSE |

### 4. Coupling — Derived, Not Independent (frozen — R3-F4)

The earlier "coupling inherits upstream policy" phrasing was directionally
correct but structurally ambiguous when a single dimension's net
transition is the result of multiple upstream contributions of different
policy classes.

R3 freezes the mechanically unambiguous alternative:

```text
Step 1  RECOVERY          (computed unconditionally)
Step 2  ORDINARY_IMPULSE  (gate.disposition per impulse)
Step 3  SHOCK_IMPULSE     (gate.disposition per impulse)
Step 4  Coupling          (derived from Steps 1+2+3 net;
                           configured strength per coupling_profile;
                           no second gate; no independent shock
                           classification)
Step 5  Absolute clamp     (floor/ceiling; owned by Dynamics)

Coupling does not receive a Homeostasis disposition.
Coupling does not enter the Gate a second time.
Coupling does not produce AssessmentTrace.contributions that
    re-route through the Gate.
The coupling Contribution in DynamicsResult is recorded in the
trace as audit evidence only.
```

Frozen corollary: **Coupling is not a candidate, not a policy object,
and not a second decision point.** It is a deterministic spread of an
already-authorized net transition. The absolute clamp still applies.

### 5. Salience Contract

Salience is a **configuration-owned composite input** that combines
four distinct quantities:

```text
salience = f(
    semantic_importance,    # contribution +1
    numeric_effect_size,    # contribution +1
    provider_confidence,    # contribution -1 only (veto floor, R3-F2)
    runtime_applicability  # contribution +1
)
```

Salience is **not** any single one of these quantities. It is
**not** `abs(delta)`, provider confidence, or semantic importance
alone. Provider confidence enters only as a lower bound / veto
(R3-F2).

The LLM is allowed to emit a `salience_class` / `shock_candidate`
proposal; it is **not** allowed to emit a numeric salience value,
bypass directive, final value, or shock classification directly.

### 6. Grief / Long-Duration Edge Case

```text
Slow recovery + fast event transition are independent axes.

A dimension with recovery_rate = 0.001 (slow):
    CAN transition from 0.1 to 0.9 in a single turn
    (if an ORDINARY_IMPULSE or SHOCK_IMPULSE is matched)
    AND will then decay back to baseline slowly (τ ≈ 1000 time units)

The dual-axis model handles this correctly.
No "grief" production type is needed.
```

The longitudinal accumulation of grief (many ordinary events over months)
is handled by the future slow-state writer (C10-B-W), not by the
per-turn Gate.

### 7. Final Seam

```text
Seam B  (contribution-aware, inside the single combined Dynamics call)

EngineEmotionalTransitionPort.materialize_projection
    → DynamicsEngine.step              (one combined call, H15)
    → produces DynamicsResult.contributions
    → for each Contribution (engine-internal, NOT AssessmentTrace):
         if source_kind == "recovery"  → pass through (not gated)
         if source_kind == "coupling"  → pass through (derived from
                                          already-authorized net,
                                          R3-F4; NOT re-gated)
         otherwise                     → HomeostasisGate.decide(candidate)
                                        (receives CandidateStateDelta,
                                         NOT AssessmentTrace; R3-F5)
    → record HomeostasisDecision in AssessmentTrace
    → canonical write path
```

Seam B is the only seam that satisfies all requirements:
per-contribution gating, per-dimension gating, coupling no double-damping,
J8-E3 H15 preservation, provenance preservation, RECOVERY passthrough,
ORDINARY/SHOCK distinction.

### 8. Pre-Gate Input vs. Post-Decision Trace (frozen — R3-F5)

R3 distinguishes the two data surfaces around the Gate:

```text
ENGINE-INTERNAL (pre-gate input):
    DynamicsResult.contributions   (tuple[Contribution, ...])
    each Contribution has:
        dimension : str
        source    : str          (e.g. "recovery",
                                  "impulse:event:<id>",
                                  "impulse:history:<id>",
                                  "impulse:appraisal:<id>:<r>:<s>",
                                  "relationship",
                                  "coupling:<donor_dimension>")
        amount    : float

    The Gate's input surface is the engine-internal Contribution,
    translated to CandidateStateDelta, NOT the port-emitted
    AssessmentContribution. The Gate runs before any trace is finalized.

PORT-EMITTED (post-decision audit evidence):
    AssessmentTrace.contributions  (tuple[AssessmentContribution, ...])
    each AssessmentContribution has:
        dimension, source_kind, source_ref, amount, confidence,
        applied, reason_code

    AssessmentTrace is the audit output. It records the Gate's
    decisions alongside the raw contribution data. It is NOT
    the input to the Gate.
```

If the existing 6163b1f implementation reads `AssessmentTrace` as its
input, that is a **structural inversion** flagged in the conformance
audit for the ADAPT or REPLACE branch.

---

## Consequences

### Positive

- C10-B1-R3 closes the only remaining blocker for C10-B1.
- The Homeostasis Gate's authority boundary is now precise and
  auditable.
- J8-E3 H15 (single Dynamics call), H19/H20 (no timescale/salience
  on rule surface), H23 (provenance) are all preserved.
- The grief edge case is resolved without a "grief" production type.
- The shock contract avoids both the pure-semantic trap (LLM owns bypass)
  and the pure-numeric trap (magnitude-threshold classification).
- The confidence asymmetry is explicitly frozen, preventing provider
  confidence from becoming an indirect bypass authority.
- The decoupling from `SalienceThresholdPolicy` (R3-F3) preserves the
  correct authority order: contract defines the boundary, implementation
  conforms to it.
- The coupling rewrite (R3-F4) eliminates the structural ambiguity of
  "which upstream policy" in multi-contribution scenarios.
- The pre-gate/post-decision distinction (R3-F5) prevents the structural
  inversion of using audit artifacts as gate inputs.
- The dual-axis model is now complete and consistent with all prior
  ADR decisions (ADR-0017, ADR-0010, ADR-C10-A1, ADR-0014).

### Negative / Trade-offs

- The contribution taxonomy (5 kinds) is frozen but not implemented
  as production enums. Consumers of `AssessmentTrace.contributions`
  must interpret `source_kind` strings directly. This is consistent
  with the existing code but may require a future ADR if a new
  contribution source is added.
- The `relationship_modifiers` wiring is explicitly deferred. The
  dormant contract in ADR-C10-A1 §6.4 is re-confirmed.
- The `transition_class` field on `CandidateStateDelta` is a
  conditional future addition (OI-1). The C10-B1 conformance audit
  may flag its absence.
- The slow-state writer (C10-B-W) is not in scope. Multi-turn
  aggregation semantics are deferred to a future ADR.
- `SalienceThresholdPolicy` is **not** canonized as the R3-compliant
  shock classifier. The conformance audit must verify whether the
  existing 6163b1f implementation conforms before any policy
  implementation can be treated as authoritative.

### Pending

- C10-B1-R3 requires independent protected-contract review per §18
  of the companion spec. Reviewer checklist includes both original
  10 questions and 9 R3-F governance checks (G1..G9).
- C10-B1 status changes from `OPEN / BLOCKED on R3` to
  `READY_FOR_EXISTING_B1_CONFORMANCE_AUDIT` only after ACCEPTED
  review.
- The conformance audit (C10-B1-CA / C10-B1-R4) determines whether
  the existing `6163b1f` implementation KEEP / ADAPT / REPLACE
  under the R3 contract surface.

### ADR-0015 §Consequences addendum — C10-B-W Closure (2026-09-03, RETRACTED, SUPERSEDED)

> ⚠️ **RETRACTED — SUPERSEDED.**
> The original closure at `docs/C10_BW_MINIMAL_CONTRACT_CLOSURE.md`
> committed implementation laundering. It was retracted by
> `docs/C10_BW_CONTRACT_CLOSURE_CORRECTION.md`, which itself returned
> BLOCKED.
>
> The BLOCKED verdict has now been retracted by
> `docs/C10_LONGITUDINAL_TARGET_ONTOLOGY_CONTRACT.md` (C10-BW-ONTO),
> which establishes that:
>
> - The `StateDefinition` registry is the authoritative ontology root
>   (per ADR-C10-A1 §1.4: kernel is dimension-agnostic).
> - Dimension identity is configuration-owned.
> - The writer consumes `CandidateStateDelta.target_dimension`
>   verbatim; no string transformation.
>
> Three formalization gaps (F1, F2, F3) remain for upstream /
> configuration work but do not block the writer contract.
>
> SalienceThresholdPolicy conformance (R3 §5, R3-F2) remains deferred
> to C10-B1-CA regardless.

---

## References

- [ADR-0017](.worktrees/j8-e3-appraisal-affect-impulse-clean/docs/adr/0017-resolved-appraisal-to-ordinary-affect-impulse.md) — ResolvedAppraisal to ordinary Impulse
- `ADR-C10-A1` — three-layer plasticity + Homeostasis Gate authority
- `docs/C10_B1_R3_CONTRIBUTION_TIMESCALE_CONTRACT.md` — full spec
- `src/mind_runtime/homeostasis/contracts.py` — HomeostasisDisposition
- `src/mind_runtime/homeostasis/policy.py` — SalienceThresholdPolicy
  (candidate implementation, not canonized)
- `src/mind_runtime/dynamics/engine.py` — Contribution sources
- `src/mind_runtime/contracts/emotional_transition.py` — AssessmentContribution
