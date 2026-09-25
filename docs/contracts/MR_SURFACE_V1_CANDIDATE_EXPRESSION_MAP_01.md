# MR-SURFACE-V1-CANDIDATE-EXPRESSION-MAP-01

Status: **SURFACE_V1_CANDIDATE**<br>
Lifecycle stage: **implementation-authorized**<br>
Calibration statement: **NOT production-calibrated**<br>
Activation statement: **NOT real-agent activation authority**<br>
Companion decision: [ADR-0031](../adr/0031-single-surface-behavior-exposure.md)<br>
Companion architecture: [MR_W3_SURFACE_ARCHITECTURE_01.md](../architecture/MR_W3_SURFACE_ARCHITECTURE_01.md)<br>
Companion recipe: [MR_SURFACE_V1_CANDIDATE_RECIPE_01.md](MR_SURFACE_V1_CANDIDATE_RECIPE_01.md)<br>

---

## 1. Admission History & Identity

### Admission History
- **Revision 1** (`content_digest: 00bb976c15ffee1759c2c4baa1640dc42ce5ebb9dfa061b581cbb6b0f1f1ac90`):<br>
  **SUPERSEDED**. Bound to Candidate Recipe Revision 1. Since Recipe Revision 1 was marked `INVALID_ADMISSION`, Expression Map Revision 1 is retired from W3 certification.
- **Revision 2** (Current Authoritative Revision):<br>
  Admitted under `MR-W3-B0-TARGETED-FIX-01`. Binds strictly to Candidate Recipe Revision 2.

### Current Identity (Revision 2)
- `map_id`: `surface-v1-candidate-map`
- `revision`: `2` (positive integer, immutable)
- `content_digest`: `bba6794aeda7a1755f8c79ffe5c88bd100918e6bc979ea29b5aa009e958eddf3`
- `supported_recipe_id`: `surface-v1-candidate`
- `supported_recipe_version`: `2`
- `supported_recipe_digest`: `4f37f46f89f6176fd5fefe0167ec7a81e341839f4fb9b98fa3cc348ddeaf9a55`
- `serialization`: `MR-surface-c14n-1`

### Immutability & Conflict Policy
1. This mapping specification is strictly immutable once admitted.
2. An evaluation presenting the same `(map_id, revision)` but a differing content digest **FAILS CLOSED** (`SURFACE_EXPRESSION_MAP_CONFLICT`).
3. An evaluation presenting an unsupported recipe ID, version, or digest **FAILS CLOSED** (`SURFACE_EXPRESSION_RECIPE_MISMATCH`).
4. Any change to cutoffs, bands, or qualitative vocabulary requires a new revision with its own distinct digest.

---

## 2. Consumed Controls and Vocabulary

The expression map consumes **strictly three** of the five Surface controls:
1. `confrontation`
2. `expressive_warmth`
3. `expressive_restraint`

`contact_seeking` and `initiative` are **EXCLUDED** from the expression map. In accordance with ADR-0031 §5 and §9, contact seeking and initiative reach the Body exclusively through selected Intent / action dispatch, never via duplicate provider expression instructions.

---

## 3. Qualitative Guidance Dimensions & Exact Boundary Behavior

Each consumed control maps monotonically into a three-level qualitative guidance band: `low`, `moderate`, `high`.

### Boundary Rule: Lower-Closed Half-Open Intervals (with closed endpoints)
- `[0.00, 0.33)` $\to$ `low`
- `[0.33, 0.66)` $\to$ `moderate`
- `[0.66, 1.00]` $\to$ `high`

### Exact Threshold Assignment
- Value `0.00`: `low`
- Value `0.33`: `moderate` (belongs to `moderate`, not `low`)
- Value `0.66`: `high` (belongs to `high`, not `moderate`)
- Value `1.00`: `high`

| Guidance Dimension | Source Surface Control | Band Intervals |
|---|---|---|
| `directness` | `confrontation` | `low` in `[0.00, 0.33)`<br>`moderate` in `[0.33, 0.66)`<br>`high` in `[0.66, 1.00]` |
| `warmth` | `expressive_warmth` | `low` in `[0.00, 0.33)`<br>`moderate` in `[0.33, 0.66)`<br>`high` in `[0.66, 1.00]` |
| `restraint` | `expressive_restraint` | `low` in `[0.00, 0.33)`<br>`moderate` in `[0.33, 0.66)`<br>`high` in `[0.66, 1.00]` |

---

## 4. Information Isolation & Provider Exposure Rules

1. **Deterministic & Bounded**: Guidance is strictly limited to the three declared guidance strings.
2. **No Fixed Phrases**: Guidance must never mandate specific prose phrases (e.g., prohibiting rules such as `warmth == 'high' -> "我想你了"`).
3. **No FACT Claims**: Qualitative guidance does not introduce cognitive facts or state beliefs.
4. **No Action Requests**: Qualitative guidance shapes prose style only; it cannot authorize or request actions.
5. **No Numeric Exposure**: The serialized segment forwarded to the LLM provider must contain **zero raw numeric floats**, zero raw Persona traits, zero raw Dynamics values, and zero diagnostic hashes.
6. **Mutually Exclusive with Legacy**: In `SURFACE_V1` mode, the compiler disables raw affect bands, duplicate behavioral persona style, and Host Slow numeric summaries.

---

## 5. Acceptance Vectors (Revision 2)

### Baseline Scenario (Baseline Controls from Candidate Recipe Revision 2)
- Input controls:
  - `confrontation`: `0.290`
  - `expressive_warmth`: `0.410`
  - `expressive_restraint`: `0.440`
- Expected Guidance Bundle:
  - `directness`: `low` (`0.290 < 0.33`)
  - `warmth`: `moderate` (`0.33 <= 0.410 < 0.66`)
  - `restraint`: `moderate` (`0.33 <= 0.440 < 0.66`)

### Persona Counterfactual Scenario (`persona-fixture-b`)
- Input controls:
  - `confrontation`: `0.500`
  - `expressive_warmth`: `0.575`
  - `expressive_restraint`: `0.215`
- Expected Guidance Bundle:
  - `directness`: `moderate` (`0.33 <= 0.500 < 0.66`)
  - `warmth`: `moderate` (`0.33 <= 0.575 < 0.66`)
  - `restraint`: `low` (`0.215 < 0.33`)

### Boundary Edge Cases
- `confrontation = 0.33` $\to$ `directness: moderate`
- `expressive_warmth = 0.66` $\to$ `warmth: high`
- `expressive_restraint = 0.00` $\to$ `restraint: low`
- `expressive_restraint = 1.00` $\to$ `restraint: high`
