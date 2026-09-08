# ADR-0018-R2: C10-B — Production Longitudinal Target Authority

**Authority:** C10-B
**Title:** Production Longitudinal Target — How production manifests register
longitudinal dimensions, how the upstream pipeline routes contributions to the
slow-plasticity writer, and how the first production dimension is frozen.
**Status:** READY FOR RE-REVIEW (R2)
**Date:** 2026-09-04
**Author:** ZCode
**Base:** `a4f7bb3`
**Revision:** R2 — five R1 review items addressed; replaces R1 of this ADR.

---

## Revision History

| Rev | Status | Summary |
|---|---|---|
| R0 | (superseded) | First draft. Self-labelled `ACCEPTED` (governance error); did not freeze a concrete first dimension; reused `base_amount` for two incompatible semantics; multiplied `proposed_value` by `confidence`; over-froze `semantic_provider.mode="disabled"` as a permanent invariant. |
| R1 | (superseded) | Five defects addressed (status corrected; dimension frozen; fields separated; confidence decoupled; `disabled` reframed as V1 operational). But: introduced "may carry either, neither, or both" for the longitudinal fields, leaving a silent-failure mode; final implementation checklist wrongly proposed "4 new EventEffectRule entries" (would re-create immediate-affect duplication); omitted the production activation prerequisite as a distinct operational gate. |
| R2 | READY FOR RE-REVIEW | All five R1 review items closed: `base_amount` remains required; longitudinal fields are pairwise (both absent or both present, partial pair → fail closed); existing four `EventEffectRule` entries are extended, not duplicated; LONG-7.1 production activation prerequisite added; V1 calibration values frozen as operational values (not architectural constants). |

---

## Context

The C10-BW rolling-window persistence layer (ADR-0017) is implemented and tested.
The infrastructure — `SlowPlasticityWriter`, `SqliteStateBackend` with
`slow_contribution_window`, `SlowPlasticityConfig(window_size=8)`,
`SalienceThresholdHomeostasisGate`, and the `CandidateStateDelta` seam in
`dynamics/ports.py` — is fully wired and exercised by the BW-R acceptance
tests. The production `runtime-config.json` carries `window_size=8` with the
canonical SHA256 payload hash.

However, no production manifest currently defines a longitudinal dimension with
`dynamics_policy = "accumulator"`. As a result, `SalienceThresholdHomeostasisGate.decide()`
is never called for a longitudinal dimension in production sessions, and the
slow-plasticity writer remains dormant.

R0 of this ADR attempted to authorize production activation but:

1. Did not actually freeze a concrete first dimension in the body (it only
   listed a generic mechanism).
2. Reused the existing `EventEffectRule.base_amount` field for two incompatible
   semantics (immediate affect delta AND longitudinal absolute target).
3. Multiplied `proposed_value` by `candidate.confidence`, conflating confidence
   (certainty of attribution) with absolute target.
4. Over-froze `semantic_provider.mode = "disabled"` as a permanent invariant
   rather than a V1 operational choice.

R2 below freezes the actual first production dimension, separates the two
amount fields, decouples confidence from the absolute target, and removes the
permanent `disabled` invariant.

---

## Decision

### LONG-1: Longitudinal Target Authority Marker

A dimension is longitudinal if and only if its `StateDefinition.dynamics_policy`
equals `"accumulator"`. This is the sole, unambiguous authority marker.

`dynamics_policy = "deterministic_affect"` (current production state) means the
DynamicsEngine governs the dimension exclusively. Switching to
`dynamics_policy = "accumulator"` transfers governance to the
`SalienceThresholdHomeostasisGate` + `SlowPlasticityWriter` pipeline. The
DynamicsEngine skips dimensions with `dynamics_policy = "accumulator"` for
affect dynamics. Immediate-salience pipeline still fires events targeting
that dimension, but those events produce contributions with salience authority;
only the gate's disposition (`SLOW_ACCEPT`) enters the ledger.

---

### LONG-2: First Production Longitudinal Dimension (FROZEN)

The first production longitudinal dimension is **explicitly, concretely frozen
by this ADR**:

| Field | Value |
|---|---|
| dimension | `agent.longitudinal.relationship_security` |
| scope | `ScopeKind.AGENT` (current persona/agent identity convention) |
| value_type | `CONTINUOUS` |
| bounds | `[0.0, 1.0]` |
| dynamics_policy | `accumulator` |
| writer | existing `SlowPlasticityWriter` / ADR-0017 |

Semantic definition (frozen):

- `0.0` = persistent expectation that the relationship is unreliable /
  unsafe / unlikely to hold.
- `1.0` = persistent expectation that the relationship is reliable /
  secure / likely to hold.

This dimension is NOT:

- current anxiety / irritation / longing / excitement (those are
  `agent.affect.*`, `dynamics_policy="deterministic_affect"`).
- a hard trust/no-trust boolean.
- a PersonaProfile mutation.

It is a longitudinal behavioral prior formed through repeated experience.
No recovery rate, no affect profile, no automatic alias to any `agent.affect.*`
dimension.

RELATIONSHIP scope is explicitly out of scope for V1 (per ticket §3). The
purpose here is minimal production activation and whole-chain assembly.

---

### LONG-3: EventEffectRule Authority Surface

The current `EventEffectRule` carries two conceptually different amount
fields. R2 freezes them as **independent, separately-decoded fields**:

| Field | Semantic | Range | Required |
|---|---|---|---|
| `base_amount` | signed immediate-affect delta | unbounded | **YES** — existing contract unchanged |
| `longitudinal_target_dimension` | longitudinal dimension name | valid dimension string | paired with `longitudinal_proposed_value` |
| `longitudinal_proposed_value` | absolute longitudinal target | `[0, 1]` | paired with `longitudinal_target_dimension` |

`base_amount` remains **required** in all production manifests (existing contract
unchanged). R2 does NOT change its cardinality.

R2 conceptually introduces two optional fields:
`longitudinal_target_dimension: str | None` and
`longitudinal_proposed_value: float | None`. They are **pairwise invariants**:

- **Both absent**: rule has no longitudinal dimension; immediate affect only.
- **Both present**: rule drives both immediate affect and longitudinal candidate.
- **`longitudinal_target_dimension` present, `longitudinal_proposed_value` absent**:
  invalid → manifest decoder fails closed.
- **`longitudinal_proposed_value` present, `longitudinal_target_dimension` absent**:
  invalid → manifest decoder fails closed.

This prevents the silent failure mode where a manifest appears to configure a
longitudinal target but the writer is never invoked in production.

The current `EventEffectRule.base_amount` semantics are NOT reused for
longitudinal contributions. Reusing a signed affect delta as an absolute
target is forbidden.

---

### LONG-4: EffectMapper Emission

The `EffectMapper` emits a longitudinal `Impulse` only when **both**
`longitudinal_target_dimension` and `longitudinal_proposed_value` are present
on the rule. Partial configuration (one present, one absent) fails at manifest
decoding time — not silently at emission time.

When both are present, the `EffectMapper` emits:

```
Impulse.dimension     = rule.longitudinal_target_dimension
Impulse.amount        = rule.longitudinal_proposed_value   # verbatim
Impulse.source_ref    = f"longitudinal:{candidate.candidate_id}"
```

The contribution seam reads `Impulse.amount` directly into
`CandidateStateDelta.proposed_value`. No transformation, no scaling,
no confidence multiplication.

This preserves the absolute-target semantics frozen in ADR-0017 §3:

```
proposed_value = longitudinal_proposed_value    # verbatim [0,1]
```

NOT:

```
proposed_value = base_amount                   # signed delta (wrong)
proposed_value = base_amount * confidence      # confidence-coupling (wrong)
proposed_value = sigmoid(base_amount)          # invented transform (wrong)
```

---

### LONG-5: Confidence Is a Separate Carrier

**Confidence does not numerically scale `proposed_value`.**

Confidence is upstream authority about the certainty of attribution. It is a
**separate carrier** from the absolute target. If the upstream source is
`0.5` confident, that information is propagated to the gate as
`CandidateStateDelta.confidence` and may influence the gate's threshold-based
disposition (e.g., below `confidence_floor_slow` → not SLOW_ACCEPT), but it
must not alter the absolute target value itself.

If `configured longitudinal_proposed_value = 0.8` and `confidence = 0.5`,
the gate sees `proposed_value = 0.8` and `confidence = 0.5`. It may reject
the contribution due to low confidence, but it does not record
`proposed_value = 0.4`.

This matches the three-axis separation frozen by the broader MR architecture:

```
confidence   = certainty of attribution
salience     = significance of the event for the agent
proposed_value = semantic target value
```

They are three independent carriers. None of them silently modifies another.

---

### LONG-6: Salience Authority

Salience authority for longitudinal contributions comes from
`SemanticAppraisal.salience` (per ADR-0016 and C10-SALIENCE-IMPL-R2).

The authority chain is:

```
SemanticEventCandidate
    → SemanticAppraisal.salience  [float | None, range 0..1]
    → MappedEffects.salience_by_source  (keyed by "longitudinal:{candidate_id}")
    → CandidateStateDelta.salience  (float | None)
    → SalienceThresholdHomeostasisGate.decide()
```

If salience is `None`, the gate rejects the contribution (never `SLOW_ACCEPT`,
never `FAST_APPLY`). No unanchored slow-state mutation is permitted.

---

### LONG-7: V1 Salience Provisioning (Operational, NOT Permanent)

For the V1 production path, salience is provisioned as follows:

```
semantic_provider.mode = "disabled"
+ authoritative host-provided SemanticAppraisal.salience
```

This is a **V1 operational calibration**, NOT a permanent architectural
invariant. R2 explicitly does NOT freeze `semantic_provider.mode != "disabled"`
as invalid.

Requirement for V1:

- The host/runtime path **must** provide authoritative
  `SemanticAppraisal.salience` upstream of the EmotionalTransition pipeline.
  This may be via host context, fixture, or direct provider call.
- If the host cannot supply authoritative salience, **production longitudinal
  activation is BLOCKED**. This is the precise blocker condition.
- Future revisions MAY enable `semantic_provider.mode != "disabled"` if a
  semantic-provider path is designed to populate `SemanticAppraisal.salience`
  with equivalent authority.

#### LONG-7.1: Production Activation Prerequisite (Operational Gate)

Before B Acceptance, the implementation patch must **prove** that the current
production host/runtime path actually supplies authoritative
`SemanticAppraisal.salience`. The authority layer (this ADR) is sufficient,
but the operational gate is not satisfied by assumption.

Verification path:

1. Trace the production host/runtime call sequence.
2. Locate the upstream component responsible for producing
   `SemanticAppraisal` (or its direct equivalent) before the
   `EmotionalTransition` pipeline.
3. Confirm that a non-None `salience` is present in the
   `MappedEffects.salience_by_source` map under the longitudinal source key
   for a representative production event.

If any of these steps fails or cannot be confirmed from the current code:

```
BLOCKED — PRODUCTION HOST DOES NOT SUPPLY LONGITUDINAL SALIENCE
```

Do NOT fake salience in the production manifest to bypass this gate.

---

### LONG-8: Authorized Event Mappings (Semantic + V1 Calibration)

The following event-kind → longitudinal-dimension mappings are authorized
semantically by this ADR:

```
plan_confirmed  → agent.longitudinal.relationship_security  (positive evidence)
warm_reunion    → agent.longitudinal.relationship_security  (positive evidence)
plan_cancelled  → agent.longitudinal.relationship_security  (negative evidence)
harsh_message   → agent.longitudinal.relationship_security  (negative evidence)
```

These mappings are semantic. The V1 operational calibration values for
`longitudinal_proposed_value` on the four existing production
`EventEffectRule` entries are frozen **as operational values, not as
architectural constants**:

| event_kind | longitudinal_target_dimension | longitudinal_proposed_value |
|---|---|---|
| `plan_confirmed` | `agent.longitudinal.relationship_security` | `0.80` |
| `warm_reunion`   | `agent.longitudinal.relationship_security` | `0.90` |
| `plan_cancelled` | `agent.longitudinal.relationship_security` | `0.30` |
| `harsh_message`  | `agent.longitudinal.relationship_security` | `0.20` |

These values may be revised in future operational patches without amending
this ADR. They are not "personality truth"; they are the Alpha V1 calibration
chosen so the rolling-window writer has enough variance to be exercised.

These four rules are implemented by **extending the existing four production
`EventEffectRule` entries** (not by adding four new rules). Each existing
rule keeps its current `dimension` + `base_amount` (which drives the immediate
affect path) and gains the new paired longitudinal fields. One event rule,
two emission paths.

---

### LONG-9: Decoder Patch Surface (Conceptual)

The `_event_effect()` decoder in `validation/contracts.py:790-814` currently
rejects any field not in its hardcoded `expected` set. R2 conceptually
requires the decoder to accept (both optional, both `None` if absent; paired
per LONG-3 invariant):

- `longitudinal_target_dimension: str | None`
- `longitudinal_proposed_value: float | None` (must be in `[0, 1]` if supplied)

This is a minimal, non-breaking decoder extension (the field is optional;
manifests without it continue to work; manifests with it are validated against
the documented type/range constraints).

---

### LONG-10: ADR-0017 §3 (proposed_value absolute) Supersedes Prior Delta Semantics

ADR-0017 §3 defines `proposed_value` as an absolute affect level. This
supersedes any implicit assumption in prior design documents that
`base_amount` or `Impulse.amount` could be a delta for longitudinal purposes.

Any future contribution source that emits a `CandidateStateDelta` for a
`dynamics_policy="accumulator"` dimension **must** supply `proposed_value`
as the absolute target affect level. Supplying a delta is a contract
violation.

---

## Consequences

### Positive

- The first production longitudinal dimension is **explicitly frozen** by name
  and semantic definition. Activation is no longer blocked by missing authority.
- The two amount fields are independent. Reusing `base_amount` is impossible
  by construction.
- Confidence, salience, and absolute target are three independent carriers.
  No silent cross-contamination.
- `semantic_provider.mode="disabled"` is documented as V1 operational, not a
  permanent invariant. Future provider activation is not foreclosed.

### Negative

- The `EventEffectRule` contract gains a new field
  (`longitudinal_proposed_value`) and the decoder must be extended. This is
  bounded and non-breaking.
- The V1 production host must supply authoritative `SemanticAppraisal.salience`
  upstream. If it cannot, production longitudinal activation is BLOCKED.
  (This is the precise blocker condition, not an unspecified "missing
  semantic authority".)

### Open Questions (Resolved by R1/R2)

| OQ | R0/R1 question | Resolution |
|---|---|---|
| OQ-1 | What is the dimension name? | R1 FROZEN: `agent.longitudinal.relationship_security` |
| OQ-2 | Should signed deltas be reused for absolute targets? | R1: NO. Independent fields. |
| OQ-3 | Should `base_amount` be reused, or a new field added? | R1: NEW FIELD. `longitudinal_proposed_value: float \| None`. R2: `base_amount` remains required. |
| OQ-4 | Does confidence scale `proposed_value`? | R1: NO. Confidence, salience, and target are independent carriers. |
| OQ-5 | Can one field be present without the other? | R2: NO — paired invariant. Partial pair → fail closed. |
| OQ-6 | Is "4 new entries" correct? | R2: NO — extend existing four. One event rule, two emission paths. |
| OQ-7 | What are the actual V1 calibration values? | R2: frozen as operational values in LONG-8. |
| OQ-8 | Who verifies host-path salience authority? | R2: LONG-7.1 operational gate — must be proved before B Acceptance. |

---

## Required Implementation After Acceptance (Out of ADR Scope)

This ADR is authority-only. The following are **not** in scope of this
decision but are listed for downstream tracking:

1. Production `StateDefinition` registration:
   `agent.longitudinal.relationship_security` with `dynamics_policy="accumulator"`.
2. `EventEffectRule` contract extension:
   add `longitudinal_target_dimension: str | None` and
   `longitudinal_proposed_value: float | None` as paired fields.
   `base_amount` remains required (existing contract unchanged).
3. `_event_effect()` decoder extension:
   accept the two new optional fields, validate paired presence
   (both present or both absent; partial pair → fail closed), and validate
   `longitudinal_proposed_value ∈ [0, 1]` when present.
4. `EffectMapper` emission update:
   use `longitudinal_proposed_value` verbatim as `Impulse.amount` for
   longitudinal targets. Do not multiply by confidence.
5. Manifest entries:
   extend the **existing four** `EventEffectRule` entries
   (`plan_confirmed`, `warm_reunion`, `plan_cancelled`, `harsh_message`)
   with the paired longitudinal fields and the V1 calibration values
   (LONG-8). Do NOT add four new rules.
6. Tests:
   - decoder accepts the new fields and rejects partial pairs;
   - EffectMapper emits the absolute target verbatim;
   - confidence does not scale `proposed_value`;
   - first production dimension reaches the slow-plasticity writer end-to-end.
7. Host path activation gate (LONG-7.1):
   prove current host/runtime supplies authoritative
   `SemanticAppraisal.salience`. If absent, BLOCKED with the documented
   blocker string.

---

## References

- ADR-0017: `docs/adr/0017-c10-b-w-slow-plasticity-accumulation-authority.md`
- ADR-0016: salience authority for appraisal
- `docs/C10_BW_ROLLING_WINDOW_PERSISTENCE_REPORT.md` — production patch verification
- `src/mind_runtime/slow_plasticity/writer.py` — canonical writer
- `src/mind_runtime/state/persistence.py` — `SqliteStateBackend` + DDL
- `src/mind_runtime/validation/contracts.py:790-814` — `_event_effect` decoder
- `src/mind_runtime/validation/contracts.py:438-451` — `SlowPlasticityConfig`
- `src/mind_runtime/emotional_transition/effects.py:25-43,179-200` —
  `EventEffectRule.longitudinal_target_dimension` and `EffectMapper` emission
- `src/mind_runtime/dynamics/ports.py:430-491` — `ContributionSeam` gate seam
- `src/mind_runtime/homeostasis/policy.py:144-228` — `SalienceThresholdGate.decide()`
- `src/mind_runtime/contracts/appraisal.py:60-100` — `SemanticAppraisal.salience`
