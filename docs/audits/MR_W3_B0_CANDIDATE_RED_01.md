# MR-W3-B0-CANDIDATE-RED-01 Audit Report

- **Date**: 2026-09-23
- **Task**: AGY-MR-W3-B0-CANDIDATE-RED-01
- **Status**: **CONTRACT_AND_RED_FROZEN**
- **Verdict**: **W3_B0_READY_FOR_IMPLEMENTATION**

---

## 1. Authority & Base

| Authority Item | Value |
|---|---|
| Repository | `C:/projects/mind-runtime-main-merge` |
| Worktree | `.worktrees/mr-w3-b0-candidate-red-01` |
| Branch | `w/mr-w3-b0-candidate-red-01` |
| Base Architecture SHA | `6e3f9216c692a6f08b8e30dc2fd057a31d524500` (ADR-0028 accepted) |
| W2 Implementation Base SHA | `ee6b25d535ffc3e3b1e0f37c567ab5572049b0ea` |
| Production Changes | **None** (`src/mind_runtime/*` completely untouched) |

---

## 2. Historical Golden Recovery & Classification

Historical material recovered from `C:/projects/w/mr-surface-affect-goldens-01` is classified according to accepted architecture §14:

| Case Category | Historical Material | Disposition & Rationale |
|---|---|---|
| **KEEP** | Five-control vocabulary, exact direct root manifests, absent deferred controls (`withdrawal`, `reassurance_seeking`), counterfactual structure, missing-data rejection, determinism/no-I/O/no-mutation, projected vs committed lineage, abort/restart recomputation obligations. | Retained as normative Layer A architecture invariants in [MR_SURFACE_V1_GOLDEN_CONTRACT_02.md](../contracts/MR_SURFACE_V1_GOLDEN_CONTRACT_02.md). |
| **ADAPT** | G1–G14, G16–G17, G20 structural, lineage, and failure assertions. | Re-bound to the frozen candidate recipe (`CANDIDATE_RECIPE_V1`), candidate expression map (`CANDIDATE_EXPRESSION_MAP_V1`), W2 type contracts, and single turn/tick port. |
| **REFERENCE_ONLY** | `surface-reference-v1` arithmetic, binary64 digests, sample clamp trace, and sample tone bands. | Preserved strictly as Layer C historical reference fixture (`test_historical_reference.py`). Excluded from W3 certification authority. |
| **DELETE** | Claims treating reference arithmetic as calibrated psychology, assumptions of pre-existing schema-2 loader, or mock provider passes. | Eliminated from W3 candidate conformance contracts. |

---

## 3. Candidate Recipe Identity & Rationale

- **Contract**: [MR_SURFACE_V1_CANDIDATE_RECIPE_01.md](../contracts/MR_SURFACE_V1_CANDIDATE_RECIPE_01.md)
- **Recipe ID**: `surface-v1-candidate`
- **Revision**: `1`
- **Content Digest**: `6ae29e53568ca91a08a2140a05ede3e5a32f79cd1bad28e69d8f81b5c241d32a`
- **Status**: `SURFACE_V1_CANDIDATE` (implementation-authorized, NOT production-calibrated, NOT real-agent activation authority)
- **Calibration Status**: `UNREPORTED_CANDIDATE`
- **Serialization**: `MR-surface-c14n-1`

### Coefficient-Selection Rationale
The coefficients in `CANDIDATE_RECIPE_V1` are engineering candidate values selected for transparency, bounded behavior, and causal testability. They do **not** constitute empirical claims about human psychology or real-agent (Kayla/Xiyue) calibration.

### Exact Root Manifests & Formulas
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

### Directional Invariants Verified
1. $\frac{\partial \text{contact\_seeking}}{\partial P.\text{attachment\_approach}} = +0.30 \ge 0$
2. $\frac{\partial \text{confrontation}}{\partial P.\text{confrontation\_readiness}} = +0.40 \ge 0$
3. $\frac{\partial \text{expressive\_warmth}}{\partial P.\text{expressive\_warmth\_bias}} = +0.55 \ge 0$
4. $\frac{\partial \text{contact\_seeking}}{\partial P.\text{expressive\_restraint}} = -0.20 \le 0$
5. $\frac{\partial \text{confrontation}}{\partial P.\text{expressive\_restraint}} = -0.30 \le 0$
6. $\frac{\partial \text{expressive\_restraint}}{\partial P.\text{expressive\_restraint}} = +0.75 \ge 0$

---

## 4. Candidate Expression Map Identity

- **Contract**: [MR_SURFACE_V1_CANDIDATE_EXPRESSION_MAP_01.md](../contracts/MR_SURFACE_V1_CANDIDATE_EXPRESSION_MAP_01.md)
- **Map ID**: `surface-v1-candidate-map`
- **Revision**: `1`
- **Content Digest**: `00bb976c15ffee1759c2c4baa1640dc42ce5ebb9dfa061b581cbb6b0f1f1ac90`
- **Supported Recipe**: `surface-v1-candidate:1`
- **Consumed Controls**: `confrontation`, `expressive_restraint`, `expressive_warmth` (`contact_seeking` and `initiative` excluded).
- **Bands**:
  - `[0.00, 0.33)` $\to$ `low`
  - `[0.33, 0.66)` $\to$ `moderate`
  - `[0.66, 1.00]` $\to$ `high`

---

## 5. Static Acceptance Vectors (No Algorithmic Oracles)

### Baseline (`persona-fixture-a` + baseline dynamics)
- Expected values:
  - `contact_seeking`: `0.365`
  - `initiative`: `0.405`
  - `confrontation`: `0.200`
  - `expressive_warmth`: `0.235`
  - `expressive_restraint`: `0.340`
- Controls ID: `surface:d08bb9968ba7edf2e47be6045916993b13ab1a40ed16186b5838511f6b49d0fb`
- Expression bundle: `directness: low`, `warmth: low`, `restraint: moderate`.

### Persona Counterfactual (`persona-fixture-b`)
- Expected values:
  - `contact_seeking`: `0.470`
  - `initiative`: `0.405` (strictly unchanged; no persona root)
  - `confrontation`: `0.365`
  - `expressive_warmth`: `0.340`
  - `expressive_restraint`: `0.160`
- Expression bundle: `directness: moderate`, `warmth: moderate`, `restraint: low`.

### Root Isolation Static Expectations (delta +0.20)
Every root alters only its declared dependent controls while leaving independent controls at baseline values.

---

## 6. Test Suite Execution & Status

### Summary
- **Total Tests**: 62
- **GREEN NOW**: 6 passed (`test_fixture_integrity.py`)
- **RED BY DESIGN**: 56 failed (production seams intentionally absent)
- **Lint**: `python -m ruff check tests/surface` passed with 0 errors.

### Test Categories
1. `test_fixture_integrity.py`: **6 passed** (AST root completeness, canonical byte encoding, recipe/map/persona digests, static vector self-consistency).
2. `test_candidate_conformance.py`: **32 failed** (RED: missing Surface projection adapter).
3. `test_normative_architecture.py`: **8 failed** (RED: missing Surface adapter, restart probe, abort probe).
4. `test_historical_reference.py`: **6 failed** (RED: missing Surface adapter for historical reference).
5. `test_intent_surface_boundary.py`: **5 failed** (RED: missing Intent Surface validator, policy integration).
6. `test_expression_provider_boundary.py`: **4 failed** (RED: missing ExpressionCompiler SURFACE_V1 admission, renderer bundle).
7. `test_turn_tick_surface_boundary.py`: **1 failed** (RED: TurnOrchestrator and CognitiveTicker missing `surface_projection_port` seam).

---

## 7. Implementation Readiness Matrix

| Slice | RED Contract Ready? | Missing Production Seam |
|---|---|---|
| **W3-A** (Persona Config) | **YES** | PersonaProfile schema-2 loader, immutable 4-trait behavioral disposition block (`attachment_approach`, `confrontation_readiness`, `expressive_restraint`, `expressive_warmth_bias`), schema/revision split. |
| **W3-B** (Pure Surface) | **YES** | `SurfaceProjectionPort`, `SurfaceProjectionInput/Result` types, deterministic candidate recipe evaluator, `MR-surface-c14n-1` output digest generator, restart recomputation. |
| **W3-C** (Intent Boundary) | **YES** | IntentRule Surface control input, composition overlap validator ($R \cap U \to$ reject, $U_1 \cap U_2 \to$ reject), `event_bonus == 0` check, score-use trace linkage, ActionPolicy DENY enforcement. |
| **W3-D** (Expression Boundary) | **YES** | DecisionContextCompiler `SURFACE_V1` mode (disabling raw affect bands, style, and Slow summary), DeterministicContextRenderer qualitative bundle, provider information isolation, essential bundle budget overflow withholding. |

---

## 8. Final Verdict

**W3_B0_READY_FOR_IMPLEMENTATION**  
All contracts, candidate recipe, expression map, static vectors, and RED test assertions are completely frozen and committed. Subsequent work can open W3-A or W3-B directly.
