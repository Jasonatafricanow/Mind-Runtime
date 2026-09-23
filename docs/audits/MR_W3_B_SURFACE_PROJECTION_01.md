# MR-W3-B-SURFACE-PROJECTION-01 Audit Report

**Task**: `AGY-MR-W3-B-SURFACE-PROJECTION-01`  
**Status**: `W3_B_READY_FOR_W3_C`  
**Date**: 2026-09-23  
**Worktree**: `C:\projects\mind-runtime-main-merge\.worktrees\mr-w3-b-surface-projection-01`  
**Branch**: `w/mr-w3-b-surface-projection-01`  
**Base Commit**: `e4af8b0915a1cc8716321241ac7abe7a4792a70e` (`W3_A_FINAL_SHA`)  
**Accepted Architecture Authority**: ADR-0028 (`6e3f9216c692a6f08b8e30dc2fd057a31d524500`)  
**Candidate Recipe Authority**: `surface-v1-candidate:2` (`4f37f46f89f6176fd5fefe0167ec7a81e341839f4fb9b98fa3cc348ddeaf9a55`)  

---

## 1. Executive Summary

This task implements the second production slice of W3: **The Single Deterministic Surface Projection Authority**.

It resolves strictly:
> "How authorized Dynamics state + authorized Persona disposition + admitted Candidate recipe v2 are projected deterministically into a single derived, non-canonical, typed Surface control vector."

### Boundary Constraints Strictly Enforced
- **Zero Candidate Recipe Modification**: Recipe `surface-v1-candidate:2` formulas and coefficients are strictly frozen. Digest `4f37f46f89f6176fd5fefe0167ec7a81e341839f4fb9b98fa3cc348ddeaf9a55` is verified.
- **Pure Derived State**: `derived_only = True`, `canonical = False`. Zero surface tables or persistent records are written to SQLite or canonical persistence.
- **Isolated Deterministic Recomputation**: Turn restarts recompute Surface from scratch across process boundaries without surface state reads or writes.
- **Single Composed Port**: `TurnOrchestrator` and `CognitiveTicker` share the single composed `SurfaceProjectionPort`. Neither re-steps Dynamics nor computes separate personality values.
- **Preserved Downstream RED Gate**: W3-C (Intent Surface scoring) and W3-D (Expression qualitative exposure) remain strictly untouched and RED by design.
- **Zero Real-Agent Mutation**: No trait or configuration changes for real agents (`Kayla`, `Xiyue`).

---

## 2. Production Files Created and Modified

1. `src/mind_runtime/contracts/surface.py`:
   - Defined `SurfaceProjectionStatus` (`StrEnum`: `AVAILABLE`, `UNAVAILABLE`).
   - Defined `SurfaceControl` (`StrEnum`: `contact_seeking`, `initiative`, `confrontation`, `expressive_warmth`, `expressive_restraint`).
   - Defined `ENABLED_CONTROLS` and `DEFERRED_CONTROLS`.
   - Defined fail-closed reason codes (`SURFACE_MISSING_STATE`, `SURFACE_NUMERIC_TYPE`, `SURFACE_NONFINITE`, `SURFACE_RANGE`, `SURFACE_RECIPE_CONTENT_CONFLICT`, `SURFACE_PERSONA_CONTENT_MISMATCH`, `SURFACE_INELIGIBLE_PERSONA`, `SURFACE_SCHEMA_MISMATCH`, `SURFACE_RECIPE_UNSUPPORTED`).
   - Implemented `SurfaceProjectionResult` (subclass of `dict[str, Any]` supporting dictionary equality/indexing, key iteration, and attribute access).
   - Defined `SurfaceProjectionPort` runtime-checkable protocol.

2. `src/mind_runtime/contracts/__init__.py`:
   - Exported typed surface contracts, result types, enums, control constants, and reason codes.

3. `src/mind_runtime/surface/evaluator.py`:
   - Pure, closed AST evaluator supporting only declared primitives: `const`, `lookup`, `add`, `sub`, `mul`, `clamp`.
   - Enforces zero `eval()`, zero lambdas, and zero external I/O or dependencies.
   - Provides `extract_ast_lookups` and `validate_ast_primitives`.

4. `src/mind_runtime/surface/recipe.py`:
   - Declares frozen candidate recipe v2 constants (`CANDIDATE_RECIPE_ID`, `CANDIDATE_RECIPE_VERSION`, `CANDIDATE_RECIPE_DIGEST`).
   - Defines static `MANIFEST` mapping controls to their required dynamics and disposition roots.
   - Provides `normalized_recipe`, `normalized_persona_content`, and `dependency_payload` for deterministic MR-surface-c14n-1 hashing.
   - Implements `validate_candidate_recipe` verifying identity, content digest, AST primitives, and exact manifest lookup set equality.

5. `src/mind_runtime/surface/projector.py`:
   - Implements `DeterministicSurfaceProjector` conforming to `SurfaceProjectionPort`.
   - Enforces fail-closed validation order: Recipe validation -> Persona validation -> Dynamics presence -> Numeric scalar validation (Type -> Nonfinite -> Range).
   - Rounds unclamped AST outputs and clamped final values to 3 decimal places.
   - Computes complete lineage: `source_states`, `dependency_digest`, `dependency_digests_by_control`, `recipe_digest`, and stable `controls_id` (`"surface:" + digest("controls", semantic)`).
   - Ensures evaluation does not mutate caller input structures.

6. `src/mind_runtime/surface/adapter.py`:
   - Implements `SurfaceProductionAdapter` satisfying `SurfaceSpecAdapter`.
   - Provides `forbidden_call_targets` declaring all required isolation categories (`provider`, `clock`, `random`, `network`, `database`, `file`).
   - Implements `abort_probe` verifying that aborted projections produce `source_phase = "projected"`, `canonical = False`, and 0 state/surface publications.
   - Implements `restart_probe` spawning an isolated child subprocess verifying identical recomputed bytes, reconstructed input identity, and 0 surface reads/writes.

7. `src/mind_runtime/surface/__init__.py`:
   - Exports all public Surface symbols and authorities.

8. `src/mind_runtime/pipeline/orchestrator.py`:
   - Added `surface_projection_port: SurfaceProjectionPort | None = None` class attribute and `__init__` constructor parameter.

9. `src/mind_runtime/cognition/tick.py`:
   - Added `surface_projection_port: SurfaceProjectionPort | None = None` class attribute and `__init__` constructor parameter, automatically defaulting to `orchestrator.surface_projection_port` when not explicitly supplied.

10. `tests/surface/conftest.py`:
    - Updated `surface` fixture to return `SurfaceProductionAdapter()`.

---

## 3. Verification & Gate Evidence

### 3.1 Targeted W3-B Surface Suite (41 Tests)
```
python -m pytest tests/surface/test_turn_tick_surface_boundary.py tests/surface/test_candidate_conformance.py tests/surface/test_normative_architecture.py -v
============================= 41 passed in 1.49s ==============================
```
- **Turn & Tick Port Boundary**: `test_turn_orchestrator_and_cognitive_ticker_share_single_surface_port` PASSED.
- **Candidate Conformance (32 Tests)**:
  - Baseline static vector against `STATIC_BASELINE_CONTROLS`: PASSED (`controls_id = "surface:f819caec79ce592566c67b25112d7d801ebe1a08bd8a8594f424fa898995ca60"`).
  - Counterfactual test holding Dynamics constant: PASSED.
  - Root isolation across all 11 declared roots: PASSED.
  - Per-control upper and lower clamp saturation: PASSED.
  - Fail-closed missing root dynamics validation: PASSED.
  - Fail-closed numeric validation (`nan`, `inf`, `-inf`, `True`, `-0.01`, `1.01`, `"0.5"`, `None`): PASSED.
  - Fail-closed recipe content conflict rejection: PASSED.
  - Fail-closed persona content mismatch rejection: PASSED.
- **Normative Architecture (8 Tests)**:
  - Exact 5 controls, deferred absent: PASSED.
  - Pure derived state with external traps (zero I/O, clock, random, network, DB): PASSED.
  - Zero input mutation: PASSED.
  - Determinism under input reordering and caller `evaluation_ref` isolation: PASSED.
  - Phase lineage (`PROJECTED` vs `COMMITTED` distinct `controls_id`, both `canonical = False`): PASSED.
  - Restart recomputation probe with subprocess PID separation and 0 surface tables: PASSED.
  - Aborted projection isolation (0 publications, 0 writes): PASSED.
  - Unrelated fast dimension (`social_pull`) isolation: PASSED.

### 3.2 Full `tests/surface` Suite (96 Tests)
```
python -m pytest tests/surface -q --tb=short
8 failed, 88 passed in 2.10s
```
- **88 Passed**:
  - 33 W3-A Persona disposition tests: PASSED.
  - 41 W3-B Surface projection tests: PASSED.
  - 8 fixture integrity tests: PASSED.
  - 5 historical reference tests: PASSED.
  - 1 action policy denial test: PASSED.
- **8 Failed (Strictly RED BY DESIGN)**:
  - 4 tests in `test_intent_surface_boundary.py` (W3-C Intent Surface scoring).
  - 4 tests in `test_expression_provider_boundary.py` (W3-D Expression provider exposure).

### 3.3 Full Non-Surface Baseline Regression Suite (3,093 Tests)
```
python -m pytest tests --ignore=tests/surface -q --tb=short
3093 passed, 11 skipped, 4 deselected, 1 xfailed in 558.60s (0:09:18)
```
**Zero regressions across all existing features and delivery gates.**

---

## 4. Stop Conditions Checklist

| Condition | Verified | Details |
|---|---|---|
| No modification of W2 final semantics | Yes | All 3,093 baseline tests green |
| No auto-filling default disposition for schema-1 | Yes | Schema-1 personas remain ineligible |
| No changes to candidate v2 numbers/AST | Yes | Exact formula evaluated verbatim |
| No persistent Surface DB tables created | Yes | `derived_only = True`, `canonical = False` |
| No separate personality derivation in Ticker | Yes | Ticker shares orchestrator port |
| No real agent activation/migration | Yes | Kayla/Xiyue untouched |
| No leakage into W3-C or W3-D | Yes | 8 tests remain RED by design |

---

## 5. Final Verdict

```text
W3_B_READY_FOR_W3_C
```
