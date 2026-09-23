# MR-W3-C-INTENT-INTEGRATION-01 Audit Report

**Task**: `AGY-MR-W3-C-INTENT-INTEGRATION-01`  
**Status**: `W3_C_READY_FOR_W3_D`  
**Date**: 2026-09-23  
**Worktree**: `C:\projects\mind-runtime-main-merge\.worktrees\mr-w3-c-intent-integration-01`  
**Branch**: `w/mr-w3-c-intent-integration-01`  
**Base Commit**: `702a22acbc8ba754302ee38bbbfce2ec8e0d946d` (`W3_B_FINAL_SHA`)  
**W3-A Base Commit**: `e4af8b0915a1cc8716321241ac7abe7a4792a70e`  
**Accepted Architecture Authority**: ADR-0028 (`6e3f9216c692a6f08b8e30dc2fd057a31d524500`)  
**Candidate Recipe Authority**: `surface-v1-candidate:2` (`4f37f46f89f6176fd5fefe0167ec7a81e341839f4fb9b98fa3cc348ddeaf9a55`)  

---

## 1. Executive Summary

This task implements the third production slice of W3: **Integrate Surface Into Intent Scoring Without Creating a Second Action Authority**.

It resolves strictly:
> "How authorized Surface projection results provide bounded behavioral bias into deterministic Intent candidate scoring and contribution tracing, while preserving ActionPolicy as the sole action permission and dispatch authority."

### Boundary Constraints Strictly Enforced
- **Zero Second Action Authority**: ActionPolicy remains the sole authority for scheduling, interruption, cooldown, media, and resource permission. High surface controls cannot bypass ActionPolicy denial (verified by `test_action_policy_denial_prevents_dispatch_despite_high_controls`).
- **No Direct Dynamics Root Overlap**: An Intent rule cannot score both direct dynamics dimension $R$ and surface control $U_i$ if $R \in U_i$ (verified by `validate_intent_rule_surface_overlap` and `test_intent_direct_root_and_surface_overlap_rejected`).
- **No Pairwise Surface Control Overlap**: An Intent rule cannot score multiple surface controls sharing underlying dynamics roots ($U_i \cap U_j = \emptyset$, verified by `test_intent_pairwise_surface_control_overlap_rejected`).
- **Ineligible Surface Control Rejection**: In `SURFACE_V1`, `expressive_warmth` and `expressive_restraint` are strictly expression-oriented controls and ineligible for Intent scoring; unknown controls are rejected (verified by `test_intent_ineligible_surface_control_rejected`).
- **Event Bonus Constraint**: In `SURFACE_V1`, surface-aware rules must declare `event_bonus == 0.0` to preserve clean attribution (verified by `test_intent_surface_rule_event_bonus_forbidden`).
- **Missing or Stale Surface Withholds Candidate**: When surface is missing, UNAVAILABLE, or has mismatched `origin_runtime_id`, `projection_id`, phase (`"projected"` required), or state versions, candidates are fail-closed withheld with `surface_unavailable` or `surface_stale_or_mismatch` traces.
- **Durable Linkage & Trace**: Admitted candidates include `surface_controls_ref` in `candidate.cause_refs` and score traces declare `surface_controls_ref`, `surface_dependency_digest`, `overlap_validation_ref`, and contributions with `kind="surface"`.
- **Identical Turn and Tick Wiring**: `TurnOrchestrator` and `CognitiveTicker` use the single composed helper `project_surface_for_cognition` to compute surface projections from authorized dynamics and disposition.
- **Contract Import DAG Maintained**: `src/mind_runtime/contracts/behavior.py` validates `SurfaceProjectionResult` without introducing AST import direction violations.
- **Zero Expression Provider Exposure**: W3-D (`tests/surface/test_expression_provider_boundary.py`) remains strictly untouched and RED BY DESIGN (4 failures).
- **Zero Non-Surface Regressions**: All 3,093 baseline tests pass green.

---

## 2. Production Files Created and Modified

1. `src/mind_runtime/intents/surface_validator.py` [NEW]:
   - Implements `validate_intent_rule_surface_overlap(rule)`:
     - Validates control eligibility (`ENABLED_CONTROLS` excluding `expressive_warmth`, `expressive_restraint`).
     - Rejects non-zero `event_bonus` for surface-aware rules.
     - Validates finite numeric weights.
     - Validates disjoint direct dynamics roots ($R \cap U_i = \emptyset$).
     - Validates pairwise disjoint surface control roots ($U_i \cap U_j = \emptyset$).
   - Implements `compute_rule_overlap_validation_ref(rule, candidate_recipe)`.

2. `src/mind_runtime/surface/recipe.py` & `src/mind_runtime/surface/__init__.py`:
   - Added `candidate_recipe()` returning normalized Candidate Recipe v2 with AST formulas and manifest.

3. `src/mind_runtime/contracts/intent.py`:
   - Updated `IntentScoreTrace` with optional fields:
     - `surface_controls_ref: str | None = None`
     - `surface_dependency_digest: str | None = None`
     - `overlap_validation_ref: str | None = None`

4. `src/mind_runtime/contracts/behavior.py`:
   - Added `surface: Any = None` to `IntentEngineInput` with runtime type verification ensuring instances are of type `SurfaceProjectionResult` while strictly respecting cross-module import direction.

5. `src/mind_runtime/intents/engine.py`:
   - Added `surface_control_weights: tuple[tuple[str, float], ...] = ()` to `IntentRule` with post-init validation calling `validate_intent_rule_surface_overlap`.
   - Updated `DeterministicIntentEngine._evaluate_rule`:
     - Detects surface-aware rules.
     - Enforces fail-closed candidate withholding on missing/unavailable surface (`surface_unavailable`).
     - Enforces fail-closed candidate withholding on runtime ID, projection ID, phase, or state version mismatches (`surface_stale_or_mismatch`).
     - Computes bounded surface score contributions: `IntentScoreContribution(kind="surface", dimension=control, amount=weight * val)`.
     - Populates trace metadata (`surface_controls_ref`, `surface_dependency_digest`, `overlap_validation_ref`).
     - Appends `surface_controls_ref` to `candidate.cause_refs`.

6. `src/mind_runtime/surface/cognition.py` [NEW]:
   - Implements `project_surface_for_cognition`:
     - Adapts `ScopeDomain` enums to canonical string mappings for deterministic hashing.
     - Evaluates surface projection via `SurfaceProjectionPort` given persona profile and projected dynamics states.

7. `src/mind_runtime/pipeline/orchestrator.py`:
   - Updated `_Turn` with `surface: SurfaceProjectionResult | None = None`.
   - Updated `TurnOrchestrator.run()` to project surface via `project_surface_for_cognition` and pass it to `IntentEngineInput`.

8. `src/mind_runtime/cognition/tick.py`:
   - Updated `CognitiveTicker.tick()` to project surface via `project_surface_for_cognition` and pass it to `IntentEngineInput`.

9. `tests/surface/test_intent_surface_boundary.py`:
   - Completed all 10 boundary tests covering root overlap rejection, pairwise overlap rejection, ineligible control rejection, event bonus rejection, ActionPolicy denial preservation, tendency scoring and trace emission, missing/unavailable withholding, stale/substituted withholding, bare dict rejection, and turn/tick consistency.

---

## 3. Verification & Gate Evidence

### 3.1 Targeted W3-C Intent Surface Suite (10 Tests)
```
C:\Python314\python.exe -m pytest tests/surface/test_intent_surface_boundary.py -v
============================= 10 passed in 0.15s ==============================
```
- `test_intent_direct_root_and_surface_overlap_rejected` PASSED
- `test_intent_pairwise_surface_control_overlap_rejected` PASSED
- `test_intent_ineligible_surface_control_rejected` PASSED
- `test_intent_surface_rule_event_bonus_forbidden` PASSED
- `test_action_policy_denial_prevents_dispatch_despite_high_controls` PASSED
- `test_surface_aware_rule_scores_tendency_and_emits_trace` PASSED
- `test_missing_or_unavailable_surface_withholds_candidate` PASSED
- `test_stale_or_substituted_surface_withholds_candidate` PASSED
- `test_intent_engine_input_rejects_bare_dict_surface` PASSED
- `test_turn_and_tick_surface_projection_consistency` PASSED

### 3.2 Full `tests/surface` Suite (101 Tests)
```
C:\Python314\python.exe -m pytest tests/surface -q --tb=short
4 failed, 97 passed in 1.40s
```
- **97 Passed**:
  - 33 W3-A Persona disposition tests: PASSED.
  - 41 W3-B Surface projection tests: PASSED.
  - 10 W3-C Intent Surface boundary tests: PASSED.
  - 8 fixture integrity tests: PASSED.
  - 5 historical reference tests: PASSED.
- **4 Failed (Strictly RED BY DESIGN for W3-D)**:
  - `test_surface_v1_disables_raw_affect_bands_and_slow_numeric_summary`
  - `test_surface_qualitative_bundle_visible_at_actual_provider_bytes`
  - `test_provider_context_contains_no_raw_numbers_or_digests`
  - `test_essential_bundle_overflow_withholds_provider_dispatch`

### 3.3 Full Non-Surface Baseline Regression Suite (3,093 Tests)
```
C:\Python314\python.exe -m pytest tests --ignore=tests/surface -q --tb=short
3093 passed, 11 skipped, 4 deselected, 1 xfailed in 433.14s (0:07:13)
```
- **Zero regressions** across all existing kernel features, contract import direction, commit boundaries, and certification gates.

### 3.4 Static Analysis and Linting
```
C:\Python314\python.exe -m ruff check src/mind_runtime/intents/ src/mind_runtime/surface/
All checks passed!
```

---

## 4. Stop Conditions Checklist

| Condition | Verified | Details |
|---|---|---|
| No second Action authority created | Yes | ActionPolicy denial strictly halts dispatch despite high surface controls |
| No double-counting / overlap allowed | Yes | Enforces $R \cap U_i = \emptyset$ and $U_i \cap U_j = \emptyset$ |
| Ineligible controls rejected | Yes | `expressive_warmth` and `expressive_restraint` rejected in intent scoring |
| Surface-aware event bonus forbidden | Yes | `event_bonus == 0.0` strictly enforced |
| Missing/stale surface fails closed | Yes | Candidate withheld with `surface_unavailable` / `surface_stale_or_mismatch` |
| Durable lineage attached | Yes | `candidate.cause_refs` and traces contain stable surface references |
| Turn and tick consistency | Yes | Single composed projection logic used across pipeline and ticker |
| Contract import DAG preserved | Yes | `tests/contract/test_import_direction.py` passes 100% |
| No modification of Candidate Recipe v2 | Yes | Recipe ID, version, digest, AST formulas strictly preserved |
| No Expression / Provider exposure | Yes | 4 W3-D tests remain RED BY DESIGN |
| No real agent activation/migration | Yes | Real agents (`Kayla`, `Xiyue`) remain untouched |

---

## 5. Final Verdict

```text
W3_C_READY_FOR_W3_D
```
