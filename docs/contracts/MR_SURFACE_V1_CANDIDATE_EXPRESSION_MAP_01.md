# MR-SURFACE-V1-CANDIDATE-EXPRESSION-MAP-01

Status: **SURFACE_V1_CANDIDATE**  
Lifecycle stage: **implementation-authorized**  
Calibration statement: **NOT production-calibrated**  
Activation statement: **NOT real-agent activation authority**  
Companion decision: [ADR-0028](../adr/0028-single-surface-behavior-exposure.md)  
Companion architecture: [MR_W3_SURFACE_ARCHITECTURE_01.md](../architecture/MR_W3_SURFACE_ARCHITECTURE_01.md)  
Companion recipe: [MR_SURFACE_V1_CANDIDATE_RECIPE_01.md](MR_SURFACE_V1_CANDIDATE_RECIPE_01.md)  

---

## 1. Identity and Binding

- `map_id`: `surface-v1-candidate-map`
- `revision`: `1` (positive integer, immutable)
- `content_digest`: `00bb976c15ffee1759c2c4baa1640dc42ce5ebb9dfa061b581cbb6b0f1f1ac90`
- `supported_recipe_id`: `surface-v1-candidate`
- `supported_recipe_version`: `1`
- `supported_recipe_digest`: `6ae29e53568ca91a08a2140a05ede3e5a32f79cd1bad28e69d8f81b5c241d32a`
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

`contact_seeking` and `initiative` are **EXCLUDED** from the expression map. In accordance with ADR-0028 §5 and §9, contact seeking and initiative reach the Body exclusively through selected Intent / action dispatch, never via duplicate provider expression instructions.

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

## 5. Acceptance Vectors

### Baseline Scenario (Baseline Controls from Candidate Recipe)
- Input controls:
  - `confrontation`: `0.200`
  - `expressive_warmth`: `0.235`
  - `expressive_restraint`: `0.340`
- Expected Guidance Bundle:
  - `directness`: `low` (`0.200 < 0.33`)
  - `warmth`: `low` (`0.235 < 0.33`)
  - `restraint`: `moderate` (`0.33 <= 0.340 < 0.66`)

### Persona Counterfactual Scenario (`persona-fixture-b`)
- Input controls:
  - `confrontation`: `0.365`
  - `expressive_warmth`: `0.340`
  - `expressive_restraint`: `0.160`
- Expected Guidance Bundle:
  - `directness`: `moderate` (`0.33 <= 0.365 < 0.66`)
  - `warmth`: `moderate` (`0.33 <= 0.340 < 0.66`)
  - `restraint`: `low` (`0.160 < 0.33`)

### Boundary Edge Cases
- `confrontation = 0.33` $\to$ `directness: moderate`
- `expressive_warmth = 0.66` $\to$ `warmth: high`
- `expressive_restraint = 0.00` $\to$ `restraint: low`
- `expressive_restraint = 1.00` $\to$ `restraint: high`
