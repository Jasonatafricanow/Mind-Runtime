# MR-SURFACE-V1-GOLDEN-CONTRACT-02

Version: **2.0.0** · 2026-09-23 · **RED BY DESIGN** (specification & static vectors only; no production implementation).<br>
Authorities:
- Accepted Architecture: [ADR-0031](../adr/0031-single-surface-behavior-exposure.md) (`6e3f9216c692a6f08b8e30dc2fd057a31d524500`)
- Companion Architecture: [MR_W3_SURFACE_ARCHITECTURE_01.md](../architecture/MR_W3_SURFACE_ARCHITECTURE_01.md)
- Candidate Recipe: [MR_SURFACE_V1_CANDIDATE_RECIPE_01.md](MR_SURFACE_V1_CANDIDATE_RECIPE_01.md)
- Candidate Expression Map: [MR_SURFACE_V1_CANDIDATE_EXPRESSION_MAP_01.md](MR_SURFACE_V1_CANDIDATE_EXPRESSION_MAP_01.md)
- W2 Base Authority: `ee6b25d535ffc3e3b1e0f37c567ab5572049b0ea`

---

## Structure of Golden Authority

This contract structures Surface acceptance authority into three distinct, non-conflated layers:

```text
┌──────────────────────────────────────────────────────────┐
│ Layer A: Normative Architecture Invariants               │
│ - Independent of numerical recipe / calibration           │
│ - Five controls, exact roots, single port, lineage,       │
│   fail-closed, root-overlap rejection, provider isolation │
└────────────────────────────┬─────────────────────────────┘
                             │
┌────────────────────────────▼─────────────────────────────┐
│ Layer B: Candidate Conformance (CANDIDATE_RECIPE_V1)     │
│ - Bound to CANDIDATE_RECIPE_V1 + CANDIDATE_EXPRESSION_MAP│
│ - Statically frozen literal vectors (NO algorithmic test │
│   adapter calculation)                                   │
│ - Baseline, counterfactuals, root isolation, saturation  │
└────────────────────────────┬─────────────────────────────┘
                             │
┌────────────────────────────▼─────────────────────────────┐
│ Layer C: Historical Reference (surface-reference-v1)     │
│ - TEST_ONLY / REFERENCE_FIXTURE                          │
│ - Historical sanity checks; EXCLUDED from W3 authority   │
└──────────────────────────────────────────────────────────┘
```

---

## Layer A: Normative Architecture Invariants

These invariants hold universally across all future recipe revisions and calibration stages.

### A1. Exact Five Controls & Absent Deferred Vocabulary
1. Successful Surface evaluation produces **exactly five** finite scalar controls in `[0.0, 1.0]`:
   - `contact_seeking`
   - `initiative`
   - `confrontation`
   - `expressive_warmth`
   - `expressive_restraint`
2. `withdrawal` and `reassurance_seeking` are **ABSENT** from schema, rules, manifests, traces, and outputs. They are never `0.0`, `None`, or empty placeholders.

### A2. Exact Root Ownership & Typed Namespaces
1. Dynamics roots belong strictly to the `agent.affect.*` namespace and are validated against registered `StateDefinition` bounds and ownership.
2. Disposition roots belong strictly to the `persona.behavioral_disposition.*` namespace and are owned exclusively by `PersonaProfile`.
3. Every rule's lookup set must equal its declared manifest. Extra lookups or undeclared dependencies fail closed.
4. Unrelated valid Fast dimensions (e.g., `agent.affect.social_pull`) may be present in the Dynamics vector but must have zero effect on values or consumed dependency digests.

### A3. Single Pure Surface Authority
1. Exactly **one** `SurfaceProjectionPort` is composed for both user turn and cognitive tick.
2. Surface is a **derived view**, not canonical state. It has no independent database table, no write surface, and is recomputed deterministically on restart from canonical state and immutable config.
3. Surface evaluation is a **pure function**: zero I/O, zero model/LLM calls, zero clock reads, zero random generation, and zero mutation of input Dynamics or Persona.

### A4. Full-Vector Fail-Closed Semantics
1. Any invalidity (missing root, missing disposition block, nonfinite float, wrong owner/scope/runtime, stale projection, recipe/map digest mismatch) yields `{status: UNAVAILABLE, reasons: [code], controls: None}`.
2. No partial controls, no fallback to raw affect, no neutral defaults (`0.5`), and no reuse of previous stale Surface vectors.

### A5. Determinism & Lineage
1. Output lineage records: `runtime_id`, affect `scope`, `owner`, `interaction_or_tick_ref`, source `projection_id`, source `phase` (`PROJECTED` vs `COMMITTED`), `persona_id`, `persona_version`, `persona_content_digest`, `recipe_id`, `recipe_version`, `recipe_digest`, consumed per-root state IDs/versions/value digests, and `dependency_digest`.
2. Identical valid inputs produce identical output bytes, numbers, and `controls_id`.
3. Changing source phase (`PROJECTED` to `COMMITTED`) changes `controls_id` even if numbers are identical.
4. Projected Surface remains tagged `PROJECTED`; turn abort never commits or publishes it as canonical.

### A6. Intent Boundary & Overlap Rejection
1. IntentEngine may consume `contact_seeking`, `initiative`, and `confrontation` only.
2. Composition validation rejects any scored IntentRule if:
   - $R \cap U_i \ne \emptyset$ (direct Dynamics roots intersect the transitive roots of any selected Surface control).
   - $U_i \cap U_j \ne \emptyset$ for $i \ne j$ (selected Surface controls share any Dynamics or Persona root, e.g., direct `longing` + `contact_seeking`, or `contact_seeking` + `confrontation` sharing `anger`).
3. In `SURFACE_V1`, Surface-aware rules must have `event_bonus = 0`.
4. Surface controls provide tendencies only; `ActionPolicy` alone grants action permission. High `contact_seeking` or `initiative` cannot bypass Policy `DENY`.

### A7. Expression & Provider Information Isolation
1. In `SURFACE_V1`, `DecisionContextCompiler` admits `confrontation`, `expressive_warmth`, and `expressive_restraint` only after Policy `ALLOW`.
2. Raw affect bands, duplicate behavioral persona style, and Host Slow numeric summaries are disabled.
3. The renderer maps admitted controls into bounded qualitative guidance via the versioned expression map.
4. Provider text must never expose raw Surface floats, raw Persona traits, raw Dynamics values, or internal digests.
5. Selected permitted action + Policy constraints + Surface expression bundle form an **essential bundle**. If prompt budget cannot fit this essential bundle, provider dispatch is withheld.

---

## Layer B: Candidate Conformance (`CANDIDATE_RECIPE_V1` Revision 2)

Bound strictly to `surface-v1-candidate:2` and `surface-v1-candidate-map:2`.<br>
**Hard Rule**: All test oracles are statically frozen literals. Tests must **never** compute expected values via a copy of the production formula.

### B1. Baseline Static Vector
- **Persona**: `persona-fixture-a` (`attachment_approach=0.50`, `confrontation_readiness=0.50`, `expressive_restraint=0.40`, `expressive_warmth_bias=0.50`)
- **Dynamics**: `longing=0.70`, `closeness_craving=0.50`, `anger=0.30`, `sharing_urge=0.60`, `curiosity=0.50`, `sadness=0.20`, `diligence_pressure=0.40`, `social_pull=0.20`
- **Expected Controls**:
  ```python
  {
      "contact_seeking": 0.500,
      "initiative": 0.560,
      "confrontation": 0.290,
      "expressive_warmth": 0.410,
      "expressive_restraint": 0.440,
  }
  ```
- **Audit**: All controls have `unclamped == value` and `clamped == False`.
- **Expression Guidance**:
  - `directness`: `low` (`0.290 < 0.33`)
  - `warmth`: `moderate` (`0.33 <= 0.410 < 0.66`)
  - `restraint`: `moderate` (`0.33 <= 0.440 < 0.66`)

### B2. Persona Counterfactual Static Vector
- **Persona**: `persona-fixture-b` (`attachment_approach=0.80`, `confrontation_readiness=0.80`, `expressive_restraint=0.10`, `expressive_warmth_bias=0.80`)
- **Dynamics**: Same as Baseline
- **Expected Controls**:
  ```python
  {
      "contact_seeking": 0.650,
      "initiative": 0.560,      # Strictly unchanged: initiative has no persona root
      "confrontation": 0.500,
      "expressive_warmth": 0.575,
      "expressive_restraint": 0.215,
  }
  ```
- **Expression Guidance**:
  - `directness`: `moderate` (`0.33 <= 0.500 < 0.66`)
  - `warmth`: `moderate` (`0.33 <= 0.575 < 0.66`)
  - `restraint`: `low` (`0.215 < 0.33`)

### B3. Root Isolation Static Vectors
Varying each declared root by `+0.20` from baseline must change **only** its declared dependent controls:

| Root Changed (`+0.20`) | Intended Affected Controls & Static Expected Values | Unaffected Controls (remain at baseline) |
|---|---|---|
| `longing` (`0.70 -> 0.90`) | `contact_seeking`: `0.590` | `initiative=0.560`, `confrontation=0.290`, `warmth=0.410`, `restraint=0.440` |
| `closeness_craving` (`0.50 -> 0.70`) | `contact_seeking`: `0.570`<br>`expressive_warmth`: `0.510` | `initiative=0.560`, `confrontation=0.290`, `restraint=0.440` |
| `anger` (`0.30 -> 0.50`) | `contact_seeking`: `0.460`<br>`confrontation`: `0.430`<br>`expressive_warmth`: `0.360` | `initiative=0.560`, `restraint=0.440` |
| `attachment_approach` (`0.50 -> 0.70`) | `contact_seeking`: `0.560` | `initiative=0.560`, `confrontation=0.290`, `warmth=0.410`, `restraint=0.440` |
| `expressive_restraint` (trait) (`0.40 -> 0.60`) | `contact_seeking`: `0.460`<br>`confrontation`: `0.230`<br>`expressive_restraint`: `0.590` | `initiative=0.560`, `warmth=0.410` |
| `sharing_urge` (`0.60 -> 0.80`) | `initiative`: `0.680` | `contact=0.500`, `confrontation=0.290`, `warmth=0.410`, `restraint=0.440` |
| `curiosity` (`0.50 -> 0.70`) | `initiative`: `0.660` | `contact=0.500`, `confrontation=0.290`, `warmth=0.410`, `restraint=0.440` |
| `sadness` (`0.20 -> 0.40`) | `initiative`: `0.510`<br>`expressive_warmth`: `0.370` | `contact=0.500`, `confrontation=0.290`, `restraint=0.440` |
| `confrontation_readiness` (`0.50 -> 0.70`) | `confrontation`: `0.370` | `contact=0.500`, `initiative=0.560`, `warmth=0.410`, `restraint=0.440` |
| `expressive_warmth_bias` (`0.50 -> 0.70`) | `expressive_warmth`: `0.520` | `contact=0.500`, `initiative=0.560`, `confrontation=0.290`, `restraint=0.440` |
| `diligence_pressure` (`0.40 -> 0.60`) | `expressive_restraint`: `0.510` | `contact=0.500`, `initiative=0.560`, `confrontation=0.290`, `warmth=0.410` |

### B4. Per-Control Admissible Saturation Static Vectors
Simultaneous 5-control saturation is inadmissible because `anger` exerts opposite sign on `confrontation` (+0.70) versus `contact_seeking` (-0.20) and `expressive_warmth` (-0.25). Each control is certified against an admissible per-control saturation fixture:

1. **`contact_seeking`**:
   - Upper (`longing=1.0, closeness_craving=1.0, attachment_approach=1.0, anger=0.0, expressive_restraint=0.0`): unclamped `1.10`, clamped `1.000` (`clamped == True`).
   - Lower (`longing=0.0, closeness_craving=0.0, attachment_approach=0.0, anger=1.0, expressive_restraint=1.0`): unclamped `-0.40`, clamped `0.000` (`clamped == True`).
2. **`initiative`**:
   - Upper (`sharing_urge=1.0, curiosity=1.0, sadness=0.0`): unclamped `1.10`, clamped `1.000` (`clamped == True`).
   - Lower (`sharing_urge=0.0, curiosity=0.0, sadness=1.0`): unclamped `-0.25`, clamped `0.000` (`clamped == True`).
3. **`confrontation`**:
   - Upper (`anger=1.0, confrontation_readiness=1.0, expressive_restraint=0.0`): unclamped `1.10`, clamped `1.000` (`clamped == True`).
   - Lower (`anger=0.0, confrontation_readiness=0.0, expressive_restraint=1.0`): unclamped `-0.30`, clamped `0.000` (`clamped == True`).
4. **`expressive_warmth`**:
   - Upper (`expressive_warmth_bias=1.0, closeness_craving=1.0, anger=0.0, sadness=0.0`): unclamped `1.05`, clamped `1.000` (`clamped == True`).
   - Lower (`expressive_warmth_bias=0.0, closeness_craving=0.0, anger=1.0, sadness=1.0`): unclamped `-0.45`, clamped `0.000` (`clamped == True`).
5. **`expressive_restraint`**:
   - Upper (`expressive_restraint=1.0, diligence_pressure=1.0`): unclamped `1.10`, clamped `1.000` (`clamped == True`).
   - Lower (`expressive_restraint=0.0, diligence_pressure=0.0`): unclamped `0.00`, clamped `0.000` (`clamped == False`).

---

## Layer C: Historical Reference (`surface-reference-v1`)

The historical reference fixture arithmetic (`surface-reference-v1`, `recipe_digest: 3ef6d193cbb8a72167fe12889a747ca007c58deb17f8d2c90e25c9215c124f30`) is preserved strictly as `REFERENCE_FIXTURE` under `tests/surface/test_historical_reference.py`.

1. It is **TEST_ONLY** and explicitly excluded from W3 implementation certification.
2. It serves as historical regression evidence that earlier prototype arithmetic remains reproducible in fixture isolation.
3. It must never be used as production or candidate authority.
