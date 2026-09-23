# MR-W3-D-EXPRESSION-HOST-01 Audit Report

**Task**: `AGY-MR-W3-D-EXPRESSION-HOST-01`  
**Status**: `W3_D_READY_FOR_W3_E`  
**Date**: 2026-09-23  
**Worktree**: `C:\projects\mind-runtime-main-merge\.worktrees\mr-w3-d-expression-host-01`  
**Branch**: `w/mr-w3-d-expression-host-01`  
**Base Commit**: `b35c584d39b31ff70684a4afa30f8f308d01ab5c` (`W3_C_FINAL_SHA`)  
**Accepted Architecture Authority**: ADR-0028 (`6e3f9216c692a6f08b8e30dc2fd057a31d524500`)  
**Surface Recipe Authority**: `surface-v1-candidate:2` (`4f37f46f89f6176fd5fefe0167ec7a81e341839f4fb9b98fa3cc348ddeaf9a55`)  
**Expression Map Authority**: `surface-v1-candidate-map:2` (`bba6794aeda7a1755f8c79ffe5c88bd100918e6bc979ea29b5aa009e958eddf3`)  

---

## 1. Executive Summary

This task implements the fourth and final implementation slice of W3: **Make Surface Actually Reach the Model Without Exposing Raw Internal State**.

It resolves strictly:
> "How permitted Intent / Action and the same authorized Surface projection result are compiled into qualitative guidance in DecisionContext, rendered deterministically, and exposed identically to internal expression providers and the external Host runtime, without leaking raw numbers, raw dynamics dimensions, persona traits, or internal digests."

### Boundary Constraints Strictly Enforced
- **Frozen Expression Map Authority**: Strictly consumes `surface-v1-candidate-map:2` with exact SHA-256 digest `bba6794aeda7a1755f8c79ffe5c88bd100918e6bc979ea29b5aa009e958eddf3`.
- **Three Qualitative Expression Controls**:
  - `confrontation` $\to$ `directness`
  - `expressive_warmth` $\to$ `warmth`
  - `expressive_restraint` $\to$ `restraint`
  - Control bands: `low` $[0.0, 0.33)$, `moderate` $[0.33, 0.66)$, `high` $[0.66, 1.0]$.
  - Excluded from expression guidance: `contact_seeking` and `initiative` (cognitive/action-level only).
- **Suppression of Raw Bands and Numeric Summaries in `SURFACE_V1`**:
  - Raw affect expression bands (`AffectExpressionRule` items under `internal_state-affect-*`) are completely suppressed.
  - Duplicate behavioral style constraints (`directness`, `warmth`, `restraint`, etc.) in `persona_style` are suppressed; non-behavioral persona constraints (formatting, persona tone markers) remain intact.
  - Host slow-state numeric summary (`slow: ...`) is omitted when qualitative surface guidance is present.
- **Lineage Verification on Surface Admission**: `DecisionContextCompiler.admit_surface_controls` verifies seven lineage invariants:
  1. `origin_runtime_id` match.
  2. `source_projection_id` match.
  3. `source_phase == "projected"`.
  4. `persona_id` match.
  5. Recipe identity (`surface-v1-candidate:2`) and digest match.
  6. State versions match projected dynamics states.
  7. Status is `AVAILABLE` and controls dictionary is non-empty.
- **Indivisible Essential Bundle Budget Protection**: Action + Policy constraints + Surface guidance form an atomic indivisible bundle. If essential items exceed character or item limits, `withhold_on_budget_overflow` returns `True` and halts dispatch rather than delivering partial or corrupted guidance.
- **Strict Information Isolation**: Verified by `verify_provider_information_isolation`:
  - Zero raw float/decimal numbers.
  - Zero raw dynamics dimensions (`valence`, `arousal`, `dominance`, `intimacy`, `curiosity`, `fatigue`, `attachment_security`, `trust`).
  - Zero raw persona traits (`attachment_approach`, `confrontation_readiness`, `expressive_restraint`, `expressive_warmth_bias`).
  - Zero excluded surface controls (`contact_seeking`, `initiative`).
  - Zero internal digests/hashes (`sha256`, `recipe_digest`, `dependency_digest`).
  - Zero raw slow numeric state values.
- **Provider and Host Parity**: Both the internal expression provider and the Host adapter (`render_bounded_context`) render identical qualitative guidance strings.
- **Retry Preservation and Trace Linkage**: Coordinator retries reuse the exact compiled `DecisionContext` without recompiling, and `ExpressionAttemptTrace` links `surface_controls_ref`, `expression_map_ref`, and `qualitative_guidance` tuples.
- **Zero Red Tests**: All 105 tests in `tests/surface/` pass GREEN (including 8 comprehensive provider boundary tests in `test_expression_provider_boundary.py`).
- **Zero Non-Surface Regressions**: Baseline test suite passes with zero regressions.

---

## 2. Production Files Created and Modified

1. `src/mind_runtime/expression/expression_map.py` [NEW]:
   - Frozen map authority constant: `CANDIDATE_MAP_ID = "surface-v1-candidate-map"`, `CANDIDATE_MAP_VERSION = 2`, `CANDIDATE_MAP_DIGEST = "bba6794aeda7a1755f8c79ffe5c88bd100918e6bc979ea29b5aa009e958eddf3"`.
   - `evaluate_control_band(value: float) -> str`: Maps float to `"low"`, `"moderate"`, or `"high"`.
   - `map_surface_to_qualitative_guidance(surface: Any) -> dict[str, str]`: Maps `confrontation` $\to$ `directness`, `expressive_warmth` $\to$ `warmth`, `expressive_restraint` $\to$ `restraint`.

2. `src/mind_runtime/surface/expression_map.py` [NEW] & `src/mind_runtime/surface/__init__.py`:
   - Clean re-export of expression map constants and functions preserving the AST architectural import DAG.

3. `src/mind_runtime/contracts/expression.py`:
   - Added `ExpressionContextKind.SURFACE_GUIDANCE` and `ExpressionContextKind.SURFACE_CONTROL`.
   - Added `ExpressionMode` enum (`LEGACY`, `SURFACE_V1`).
   - Extended `ExpressionAttemptTrace` with optional fields:
     - `surface_controls_ref: str | None = None`
     - `expression_map_ref: str | None = None`
     - `qualitative_guidance: tuple[tuple[str, str], ...] = ()`

4. `src/mind_runtime/expression/context.py`:
   - Added `mode: str = "LEGACY"` to `DecisionContextConfig`.
   - Added `surface: Any = None` and `mode: str | None = None` to `DecisionContextCompilerInput`.
   - Implemented `admit_surface_controls(surface, compiler_input)` with 7 lineage validation checks.
   - Implemented `withhold_on_budget_overflow(items, config, mode)`.
   - Implemented `compile_surface_v1(...)` convenience entry point.
   - In `DecisionContextCompiler.compile()`:
     - Conditionally suppresses affect rules and slow-state numeric items in `SURFACE_V1` mode.
     - Filters out redundant behavioral style constraints while retaining non-behavioral ones.
     - Adds `SURFACE_GUIDANCE` context items as essential priority 5 items.
     - Uses essential kind sets that include `SURFACE_GUIDANCE` when calculating budgets.

5. `src/mind_runtime/expression/renderer.py`:
   - Updated `_SECTION_ORDER`, `_SECTION_LABEL`, `_TRUSTED_KINDS`, `_ESSENTIAL_KINDS` to include `SURFACE_GUIDANCE`.
   - Implemented `render_surface_bundle` and `format_surface_guidance`.
   - Implemented `verify_provider_information_isolation(rendered_text)` with strict checks against traits, dynamics dimensions, excluded controls, slow numbers, hashes, and raw float patterns.

6. `src/mind_runtime/expression/coordinator.py`:
   - In `_attempt`: Extracts surface references and qualitative guidance from `context.items` into `ExpressionAttemptTrace`.

7. `src/mind_runtime/host/runtime_adapter.py`:
   - In `_bounded_context`: Detects qualitative surface guidance, suppresses raw slow numeric summaries, and renders qualitative guidance string matching provider guidance.

8. `src/mind_runtime/pipeline/orchestrator.py`:
   - Forwards `turn.surface` and compiler mode into `DecisionContextCompilerInput` when invoking expression.

9. `tests/surface/test_expression_provider_boundary.py`:
   - Completed all 8 comprehensive boundary tests:
     1. `test_surface_candidate_map_digest`: Exact binary SHA-256 match.
     2. `test_surface_v1_disables_raw_affect_bands_and_slow_numeric_summary`: Affect suppression and non-behavioral style retention.
     3. `test_surface_qualitative_bundle_visible_at_actual_provider_bytes`: Low/moderate/high bands at provider boundary.
     4. `test_provider_context_contains_no_raw_numbers_or_digests`: Information isolation proof.
     5. `test_essential_bundle_overflow_withholds_provider_dispatch`: Fail-closed budget overflow.
     6. `test_lineage_mismatch_withholds_surface_admission`: Lineage validation failures.
     7. `test_coordinator_retry_preserves_surface_and_records_trace`: Context reuse and trace linkage across retries.
     8. `test_host_adapter_parity_and_isolation`: Internal provider vs host adapter parity.

---

## 3. Verification & Gate Evidence

### 3.1 Targeted W3-D Expression Host Boundary Suite (8 Tests)
```
C:\Python314\python.exe -m pytest tests/surface/test_expression_provider_boundary.py -v
============================== 8 passed in 0.20s ===============================
```
- `test_surface_candidate_map_digest` PASSED
- `test_surface_v1_disables_raw_affect_bands_and_slow_numeric_summary` PASSED
- `test_surface_qualitative_bundle_visible_at_actual_provider_bytes` PASSED
- `test_provider_context_contains_no_raw_numbers_or_digests` PASSED
- `test_essential_bundle_overflow_withholds_provider_dispatch` PASSED
- `test_lineage_mismatch_withholds_surface_admission` PASSED
- `test_coordinator_retry_preserves_surface_and_records_trace` PASSED
- `test_host_adapter_parity_and_isolation` PASSED

### 3.2 Full `tests/surface` Suite (105 Tests)
```
C:\Python314\python.exe -m pytest tests/surface -v
============================= 105 passed in 1.27s =============================
```
- **105 Passed / 0 Failed**:
  - 33 W3-A Persona disposition tests: PASSED.
  - 41 W3-B Surface projection tests: PASSED.
  - 10 W3-C Intent Surface boundary tests: PASSED.
  - 8 W3-D Expression provider boundary tests: PASSED.
  - 8 fixture integrity tests: PASSED.
  - 5 historical reference tests: PASSED.

### 3.3 Expression Subsystem Suite (107 Tests)
```
C:\Python314\python.exe -m pytest tests/expression -v
============================= 107 passed in 1.43s =============================
```
- All compiler, coordinator, guards, slow-state, and renderer tests pass cleanly.

### 3.4 Host Integration Suite (302 Tests)
```
C:\Python314\python.exe -m pytest tests/host -v
======================= 302 passed in 72.73s (0:01:12) ========================
```
- All host adapter, runtime binding, and context rendering tests pass cleanly.

### 3.5 Full Non-Surface Baseline Regression Suite (3,093 Tests)
```
C:\Python314\python.exe -m pytest tests --ignore=tests/surface -q --tb=short
3093 passed, 11 skipped, 4 deselected, 1 xfailed in 481.72s (0:08:01)
```
- Zero regressions across the entire repository.

### 3.6 Static Analysis and Linting
```
C:\Python314\python.exe -m ruff check src/mind_runtime/expression/ src/mind_runtime/surface/ src/mind_runtime/host/ tests/surface/test_expression_provider_boundary.py
All checks passed!
```

---

## 4. Stop Conditions Checklist

| Condition | Verified | Details |
|---|---|---|
| Frozen map authority consumed strictly | Yes | `surface-v1-candidate-map:2` (`bba6794aeda7a1755f8c79ffe5c88bd100918e6bc979ea29b5aa009e958eddf3`) |
| 3 qualitative controls mapped | Yes | `directness`, `warmth`, `restraint` with low/moderate/high bands |
| Action-level controls excluded | Yes | `contact_seeking` and `initiative` never reach provider text |
| Raw affect bands suppressed | Yes | Suppressed under `SURFACE_V1` mode |
| Duplicate persona style suppressed | Yes | Behavioral styles filtered; non-behavioral styles preserved |
| Numeric slow summaries suppressed | Yes | Host slow numeric summary omitted when qualitative guidance is present |
| Seven lineage checks enforced | Yes | Runtime ID, projection ID, phase, persona, recipe, state versions, availability |
| Indivisible essential bundle | Yes | Budget overflow fails closed without partial dispatch |
| Information isolation guaranteed | Yes | Verified zero raw numbers, dynamics dimensions, traits, or hashes in provider text |
| Provider and Host parity | Yes | Both surfaces render identical qualitative guidance |
| Retries preserve compiled context | Yes | Reuses existing context; populates trace with refs and guidance |
| Zero red tests in `tests/surface` | Yes | 105 passed, 0 failed |
| Baseline regression suite clean | Yes | Zero regressions across existing test suite |

---

## 5. Final Recommendation

All requirements of `AGY-MR-W3-D-EXPRESSION-HOST-01` are fully satisfied and rigorously verified.
The worktree is clean and ready for W3-E (the final validation and closure slice of W3).

**Verdict**: `W3_D_READY_FOR_W3_E`
