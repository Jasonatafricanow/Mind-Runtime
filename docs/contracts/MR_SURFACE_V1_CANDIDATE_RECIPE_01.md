# MR-SURFACE-V1-CANDIDATE-RECIPE-01

Status: **SURFACE_V1_CANDIDATE**<br>
Lifecycle stage: **implementation-authorized**<br>
Calibration statement: **NOT production-calibrated**<br>
Activation statement: **NOT real-agent activation authority**<br>
Companion decision: [ADR-0031](../adr/0031-single-surface-behavior-exposure.md)<br>
Companion architecture: [MR_W3_SURFACE_ARCHITECTURE_01.md](../architecture/MR_W3_SURFACE_ARCHITECTURE_01.md)<br>
Companion expression map: [MR_SURFACE_V1_CANDIDATE_EXPRESSION_MAP_01.md](MR_SURFACE_V1_CANDIDATE_EXPRESSION_MAP_01.md)<br>

---

## 1. Admission History & Identity

### Admission History
- **Revision 1** (`content_digest: 6ae29e53568ca91a08a2140a05ede3e5a32f79cd1bad28e69d8f81b5c241d32a`):<br>
  **INVALID_ADMISSION / NEVER_CERTIFIED**.<br>
  *Reason*: Declared formula and frozen acceptance vectors were inconsistent due to manual calculation discrepancies in initial vector transcription. Preserved for audit trail; never admitted for production or W3 certification.
- **Revision 2** (Current Authoritative Candidate Revision):<br>
  Admitted under `MR-W3-B0-TARGETED-FIX-01`. All acceptance vectors independently recalculated and verified directly from the authoritative declarative graph.

### Current Identity (Revision 2)
- `recipe_id`: `surface-v1-candidate`
- `revision`: `2` (integer positive, immutable)
- `content_digest`: `4f37f46f89f6176fd5fefe0167ec7a81e341839f4fb9b98fa3cc348ddeaf9a55`
- `projector_id`: `surface-affect`
- `projector_version`: `1`
- `status`: `SURFACE_V1_CANDIDATE`
- `calibration_status`: `UNREPORTED_CANDIDATE`
- `serialization`: `MR-surface-c14n-1`

### Immutability & Conflict Policy
1. This recipe specification is strictly immutable once admitted.
2. An evaluation presenting the same `(recipe_id, revision)` but a differing content digest **FAILS CLOSED** immediately (`SURFACE_RECIPE_CONTENT_CONFLICT`).
3. Any behavioral modification (changing coefficients, graph edges, clamp boundaries, or roots) requires minting a new revision (e.g., `revision: 3`) with its own distinct content digest. No in-place mutation is permitted.

---

## 2. Design Principles & Non-Calibration Rationale

1. **Not Psychological Modeling**: This candidate recipe is an engineering target designed to establish a deterministic, transparent, and auditable runtime seam. It does **not** make empirical claims about human psychology, cognitive science, or the final emotional behavior of Kayla, Xiyue, or any other real persona.
2. **Formula Design Principles**:
   - **Simple**: Bounded affine combinations with explicit outer clamp.
   - **Transparent**: Statically inspectable AST with no opaque subroutines or lookups.
   - **Finite & Deterministic**: Strict IEEE-754 binary64 arithmetic; left-to-right evaluation; no floating-point reassociation or FMA.
   - **Causal Testability**: Every declared root has an observable, non-zero causal effect in non-saturated test fixtures.
   - **Prohibited Primitives**: No LLM, no callback, no I/O, no clock access, no random generator, no hidden state, no control-to-control dependency, and no undeclared lookups.

---

## 3. Exact Root Manifest

The enabled vocabulary consists of exactly five controls. `withdrawal` and `reassurance_seeking` are **ABSENT** from schema, rules, manifests, and outputs (never null or zero).

| Control ID | Dynamics Roots (`agent.affect.*`) | Persona Disposition Roots (`persona.behavioral_disposition.*`) |
|---|---|---|
| `contact_seeking` | `longing`, `closeness_craving`, `anger` | `attachment_approach`, `expressive_restraint` |
| `initiative` | `curiosity`, `sadness`, `sharing_urge` | *(none / empty list)* |
| `confrontation` | `anger` | `confrontation_readiness`, `expressive_restraint` |
| `expressive_warmth` | `anger`, `closeness_craving`, `sadness` | `expressive_warmth_bias` |
| `expressive_restraint` | `diligence_pressure` | `expressive_restraint` |

No root may be added or removed without a new architecture decision record (ADR).

---

## 4. Exact Expression Formulas & AST Graph

All formulas evaluate within `clamp(expression, 0.0, 1.0)`.

```text
D = agent.affect.
P = persona.behavioral_disposition.

contact_seeking = clamp(
    (((0.45 * D.longing + 0.35 * D.closeness_craving) + 0.30 * P.attachment_approach)
     - 0.20 * D.anger) - 0.20 * P.expressive_restraint,
    0.0, 1.0
)

initiative = clamp(
    (0.60 * D.sharing_urge + 0.50 * D.curiosity) - 0.25 * D.sadness,
    0.0, 1.0
)

confrontation = clamp(
    (0.70 * D.anger + 0.40 * P.confrontation_readiness) - 0.30 * P.expressive_restraint,
    0.0, 1.0
)

expressive_warmth = clamp(
    ((0.55 * P.expressive_warmth_bias + 0.50 * D.closeness_craving)
     - 0.25 * D.anger) - 0.20 * D.sadness,
    0.0, 1.0
)

expressive_restraint = clamp(
    0.75 * P.expressive_restraint + 0.35 * D.diligence_pressure,
    0.0, 1.0
)
```

---

## 5. Directional Invariants

Within non-saturated intervals (where clamp boundaries `0.0` and `1.0` are not active):

1. **Attachment Approach**: $\frac{\partial \text{contact\_seeking}}{\partial P.\text{attachment\_approach}} = +0.30 \ge 0$.<br>
   *Increasing attachment_approach must not decrease contact_seeking.*
2. **Confrontation Readiness**: $\frac{\partial \text{confrontation}}{\partial P.\text{confrontation\_readiness}} = +0.40 \ge 0$.<br>
   *Increasing confrontation_readiness must not decrease confrontation.*
3. **Expressive Warmth Bias**: $\frac{\partial \text{expressive\_warmth}}{\partial P.\text{expressive\_warmth\_bias}} = +0.55 \ge 0$.<br>
   *Increasing expressive_warmth_bias must not decrease expressive_warmth.*
4. **Trait Expressive Restraint on Contact**: $\frac{\partial \text{contact\_seeking}}{\partial P.\text{expressive\_restraint}} = -0.20 \le 0$.<br>
   *Increasing trait expressive_restraint must not increase contact_seeking.*
5. **Trait Expressive Restraint on Confrontation**: $\frac{\partial \text{confrontation}}{\partial P.\text{expressive\_restraint}} = -0.30 \le 0$.<br>
   *Increasing trait expressive_restraint must not increase confrontation.*
6. **Trait Expressive Restraint on Control Restraint**: $\frac{\partial \text{expressive\_restraint}}{\partial P.\text{expressive\_restraint}} = +0.75 \ge 0$.<br>
   *Increasing trait expressive_restraint must not decrease control expressive_restraint.*

---

## 6. Static Acceptance Vectors (Revision 2)

### Baseline Scenario (`persona-fixture-a` + baseline dynamics)
- **Persona Traits**:
  - `attachment_approach`: `0.50`
  - `confrontation_readiness`: `0.50`
  - `expressive_restraint`: `0.40`
  - `expressive_warmth_bias`: `0.50`
- **Dynamics Values**:
  - `longing`: `0.70`
  - `closeness_craving`: `0.50`
  - `anger`: `0.30`
  - `sharing_urge`: `0.60`
  - `curiosity`: `0.50`
  - `sadness`: `0.20`
  - `diligence_pressure`: `0.40`
  - `social_pull`: `0.20` (unrelated fast state)
- **Expected Controls**:
  - `contact_seeking`: `0.500`
  - `initiative`: `0.560`
  - `confrontation`: `0.290`
  - `expressive_warmth`: `0.410`
  - `expressive_restraint`: `0.440`
- **All controls are within `(0.0, 1.0)`**: `unclamped == value`, `clamped == false`.

### Persona Counterfactual Scenario (`persona-fixture-b`)
- **Persona Traits**:
  - `attachment_approach`: `0.80`
  - `confrontation_readiness`: `0.80`
  - `expressive_restraint`: `0.10`
  - `expressive_warmth_bias`: `0.80`
- **Same Dynamics, Affect Scope, Owner, and Runtime as Baseline**
- **Expected Controls**:
  - `contact_seeking`: `0.650` (changed)
  - `initiative`: `0.560` (strictly unchanged; no persona root in V1)
  - `confrontation`: `0.500` (changed)
  - `expressive_warmth`: `0.575` (changed)
  - `expressive_restraint`: `0.215` (changed)

### Root Isolation Static Vectors (delta +0.20 from Baseline)
- `anger` (+0.20): `contact_seeking=0.460`, `confrontation=0.430`, `expressive_warmth=0.360`; others unchanged.
- `attachment_approach` (+0.20): `contact_seeking=0.560`; others unchanged.
- `closeness_craving` (+0.20): `contact_seeking=0.570`, `expressive_warmth=0.510`; others unchanged.
- `confrontation_readiness` (+0.20): `confrontation=0.370`; others unchanged.
- `curiosity` (+0.20): `initiative=0.660`; others unchanged.
- `diligence_pressure` (+0.20): `expressive_restraint=0.510`; others unchanged.
- `expressive_restraint` (trait +0.20): `contact_seeking=0.460`, `confrontation=0.230`, `expressive_restraint=0.590`; others unchanged.
- `expressive_warmth_bias` (+0.20): `expressive_warmth=0.520`; others unchanged.
- `longing` (+0.20): `contact_seeking=0.590`; others unchanged.
- `sadness` (+0.20): `initiative=0.510`, `expressive_warmth=0.370`; others unchanged.
- `sharing_urge` (+0.20): `initiative=0.680`; others unchanged.

### Per-Control Admissible Saturation Fixtures
Rather than asserting an impossible simultaneous 5-control saturation, each control has an admissible fixture driving it to its upper or lower bound:

1. **`contact_seeking`**:
   - Upper: `longing=1.0, closeness_craving=1.0, attachment_approach=1.0, anger=0.0, expressive_restraint=0.0` $\to$ unclamped `1.10`, clamped `1.0`.
   - Lower: `longing=0.0, closeness_craving=0.0, attachment_approach=0.0, anger=1.0, expressive_restraint=1.0` $\to$ unclamped `-0.40`, clamped `0.0`.
2. **`initiative`**:
   - Upper: `sharing_urge=1.0, curiosity=1.0, sadness=0.0` $\to$ unclamped `1.10`, clamped `1.0`.
   - Lower: `sharing_urge=0.0, curiosity=0.0, sadness=1.0` $\to$ unclamped `-0.25`, clamped `0.0`.
3. **`confrontation`**:
   - Upper: `anger=1.0, confrontation_readiness=1.0, expressive_restraint=0.0` $\to$ unclamped `1.10`, clamped `1.0`.
   - Lower: `anger=0.0, confrontation_readiness=0.0, expressive_restraint=1.0` $\to$ unclamped `-0.30`, clamped `0.0`.
4. **`expressive_warmth`**:
   - Upper: `expressive_warmth_bias=1.0, closeness_craving=1.0, anger=0.0, sadness=0.0` $\to$ unclamped `1.05`, clamped `1.0`.
   - Lower: `expressive_warmth_bias=0.0, closeness_craving=0.0, anger=1.0, sadness=1.0` $\to$ unclamped `-0.45`, clamped `0.0`.
5. **`expressive_restraint`**:
   - Upper: `expressive_restraint=1.0, diligence_pressure=1.0` $\to$ unclamped `1.10`, clamped `1.0`.
   - Lower: `expressive_restraint=0.0, diligence_pressure=0.0` $\to$ unclamped `0.00`, clamped `0.0` (`clamped=False`).
