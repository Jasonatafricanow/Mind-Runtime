# MR-W3-A-PERSONA-CONFIG-01 Audit Report

**Task**: `AGY-MR-W3-A-PERSONA-CONFIG-01`  
**Status**: `W3_A_READY_FOR_W3_B`  
**Date**: 2026-09-23  
**Worktree**: `C:\projects\mind-runtime-main-merge\.worktrees\mr-w3-a-persona-config-01`  
**Branch**: `w/mr-w3-a-persona-config-01`  
**Base Commit**: `fd857a3d78fe8788c622187d1d23498d6f9ecc74` (`W3_B0_FIX_SHA`)  
**Accepted Architecture Authority**: ADR-0028 (`6e3f9216c692a6f08b8e30dc2fd057a31d524500`)  
**W2 Baseline Authority**: `ee6b25d535ffc3e3b1e0f37c567ab5572049b0ea`  

---

## 1. Executive Summary

This task implements the first production slice of W3: **Persona Schema-2 and Behavioral Disposition Authority**.

It resolves strictly:
> "Who owns, how to represent, how to version, how to validate, and how to bind identity for an Agent's stable behavioral disposition."

Boundary constraints enforced:
- **No Surface Implementation**: No `SurfaceProjectionPort`, `SurfaceProjectionResult`, or formula evaluators were created.
- **No Intent Surface Scoring**: No scoring rules or bonuses were added.
- **No Expression Exposure**: No qualitative bundle exposure or provider rendering changes.
- **No Real-Agent Migration**: Existing real persona configs (`Kayla`, `Xiyue`) remain strictly schema 1 without `behavioral_disposition`.
- **W2 Semantic Invariants Preserved**: 100% preservation of `AcceptedAppraisal`, `AppraisalProjector`, `DynamicsEngine`, and W2 transaction/commit semantics.

---

## 2. Production Files Changed

1. `src/mind_runtime/contracts/affect.py`:
   - Added `DISPOSITION_TRAIT_NAMES = ("attachment_approach", "confrontation_readiness", "expressive_restraint", "expressive_warmth_bias")`.
   - Added immutable `BehavioralDisposition(Mapping[str, float])` value object with fail-closed bounds checking and mapping protocol.
2. `src/mind_runtime/contracts/__init__.py`:
   - Exported `BehavioralDisposition` and `DISPOSITION_TRAIT_NAMES`.
3. `src/mind_runtime/dynamics/persona.py`:
   - Implemented `canonical_surface_c14n` (MR-surface-c14n-1 canonical wire serializer) and `surface_digest`.
   - Implemented `compute_persona_content_digest` matching the frozen specification in candidate and reference fixtures (`PERSONA_A_DIGEST`, `PERSONA_B_DIGEST`, `REFERENCE_PERSONA_DIGEST`).
   - Extended `PersonaProfile` with `behavioral_disposition`, `schema_version`, `effective_content_digest`, `persona_content_digest`, `profile_version`, and `is_surface_eligible`.
4. `src/mind_runtime/persona_config.py`:
   - Separated serialization `schema_version` (1 or 2) from Persona content revision `profile_version` (positive integer).
   - Added `PersonaRegistry`, `_GLOBAL_PERSONA_REGISTRY`, `get_global_persona_registry()`, and `clear_persona_registry()`.
   - Extended `LoadedPersona` to expose `schema_version`, `effective_content_digest`, `behavioral_disposition`, and `is_surface_eligible`.
   - Updated `load_persona_profile` to validate schema 1 vs schema 2, enforce complete disposition blocks, and detect same-revision content conflicts.
5. `tests/surface/test_persona_disposition_boundary.py`:
   - Expanded test matrix from 10 to 33 tests, fully exercising all W3-A validation boundaries.

---

## 3. Architecture & Behavioral Specification

### 3.1 `BehavioralDisposition` Production Value Object
- **Ownership**: Owned exclusively by `PersonaProfile`.
- **Fields**: Exactly four declared roots:
  - `attachment_approach`
  - `confrontation_readiness`
  - `expressive_restraint`
  - `expressive_warmth_bias`
- **Bounds & Type Rules**:
  - Each trait must be a finite float in `[0.0, 1.0]`.
  - Non-bool: `bool` instances (`True`, `False`) are strictly rejected (`PersonaProfileError` / `ValueError`).
  - Strict rejection of `None`, non-numeric (`"0.5"`), NaN, `+inf`, `-inf`, `< 0.0`, and `> 1.0`.
- **Immutability & Access**:
  - `@dataclass(frozen=True, slots=True, eq=False)` subclassing `collections.abc.Mapping[str, float]`.
  - Typed field access: `disp.attachment_approach`.
  - Dict-like subscript read: `disp["attachment_approach"]`.
  - Equality with dictionaries/mappings: `disp == {"attachment_approach": 0.50, ...}` evaluates to `True`.
  - Item mutation (`disp["key"] = val`) raises `TypeError`.
  - Attribute mutation (`disp.key = val`) raises `FrozenInstanceError` / `AttributeError`.

### 3.2 Schema Version vs. Persona Revision Split
- `schema_version`: Serialization / file format version.
  - Absent: Decoded as legacy schema 1.
  - Explicit: Supported values are `1` and `2`. Unrecognized versions (e.g. `3`, `99`) fail closed with `PersonaProfileError`.
- `profile_version` / persona revision: Immutable content revision of the persona itself.
  - Must be a positive integer (`int >= 1`, non-bool).

### 3.3 Legacy Schema 1 Compatibility
- Schema 1 personas:
  - `behavioral_disposition` is absent (`None`).
  - Supplying `behavioral_disposition` under schema 1 is rejected with `PersonaProfileError`.
  - Schema 1 personas remain 100% operational for existing W2 and Dynamics workflows (e.g. `kayla.json`).
  - No default disposition values (e.g. `0.5`) are inferred or patched.
  - Schema 1 personas are strictly **not eligible** for Surface V1 (`is_surface_eligible == False`).

### 3.4 Explicit Schema 2 Requirements
- `schema_version == 2` requires:
  - `profile_version >= 1`.
  - Complete 4-trait `behavioral_disposition` block.
  - Strict fail-closed validation: partial blocks, missing keys, null values, and unknown extra keys (e.g. `attachment_anxiety`, `introversion`) reject with `PersonaProfileError`.

### 3.5 Persona Identity & Effective Content Digest
- Lineage requires: `persona_id`, `schema_version`, `profile_version`, and `effective_content_digest`.
- Serialized using `MR-surface-c14n-1` canonical wire format:
  - IEEE-754 binary64 floats serialized as `{"$f64": hex}`.
  - Ordered JSON dictionary keys (`separators=(",", ":")`).
  - Dimension list sorted lexicographically by dimension name.
  - Dimension growth and coupling pairs sorted by target name.
- Invariance: Canonical digest is invariant to file key ordering or dimension list permutation.
- Match verification: Digest matches frozen Golden fixtures (`PERSONA_A_DIGEST`, `PERSONA_B_DIGEST`, `REFERENCE_PERSONA_DIGEST`).

### 3.6 Same-ID + Revision Conflict Mechanism
- Authority: `PersonaRegistry` in `src/mind_runtime/persona_config.py`.
- Conflict Scope: Process-level / runtime composition registry.
- Rule:
  ```text
  same persona_id + same profile_version + same digest -> IDEMPOTENT (OK)
  same persona_id + same profile_version + different digest -> PersonaProfileError (CONFLICT)
  ```
- Prevents silent redefinition of a published persona revision.

### 3.7 Surface Structural Eligibility Seam
- Typed seam property: `profile.is_surface_eligible` (and `loaded.is_surface_eligible`).
- Returns `True` iff:
  1. `schema_version == 2`
  2. `behavioral_disposition is not None` and valid `BehavioralDisposition`
  3. `version >= 1`
  4. `effective_content_digest` is present and non-empty.
- Note: Structural eligibility indicates schema conformance for future W3-B consumption; it does **not** activate Surface for any production agent.

---

## 4. Test Verification & Suite Shape

### 4.1 W3-A Targeted Tests (`tests/surface/test_persona_disposition_boundary.py`)
All 33 boundary tests passed:
- `test_load_persona_profile_schema_v2_with_behavioral_disposition` [PASSED]
- `test_persona_profile_disposition_bounds_validation` (9 parametrized cases: `-0.01`, `1.01`, `nan`, `inf`, `-inf`, `"0.5"`, `None`, `True`, `False`) [PASSED]
- `test_persona_profile_missing_required_disposition_trait` (4 parametrized cases) [PASSED]
- `test_persona_profile_disposition_unknown_key_rejected` (4 parametrized cases) [PASSED]
- `test_persona_profile_schema_1_legacy_compatibility` [PASSED]
- `test_persona_profile_schema_1_rejects_behavioral_disposition` [PASSED]
- `test_persona_profile_schema_2_requires_disposition_block` [PASSED]
- `test_persona_profile_unsupported_schema_version_rejected` (4 parametrized cases) [PASSED]
- `test_persona_profile_invalid_revision_rejected` (5 parametrized cases) [PASSED]
- `test_persona_profile_same_id_revision_different_content_conflict` [PASSED]
- `test_persona_profile_stable_canonical_digest` [PASSED]
- `test_persona_profile_disposition_immutability` [PASSED]

### 4.2 Existing Persona Tests
- `tests/dynamics/test_persona.py`: 6 passed [PASSED]
- `tests/shadow/test_persona_production.py`: 41 passed [PASSED]

### 4.3 Surface Suite Expected Shape (`python -m pytest tests/surface -q --tb=short`)
- **Passed**: 47
  - `GREEN_B0`: 14 passed (`test_fixture_integrity.py`: 7, `test_historical_reference.py`: 7)
  - `GREEN_W3_A`: 33 passed (`test_persona_disposition_boundary.py`: 33)
- **Failed**: 49 (RED BY DESIGN, awaiting W3-B/C/D)
  - `RED_W3_B`: 41 failed (`test_candidate_conformance.py`: 32, `test_normative_architecture.py`: 8, `test_turn_tick_surface_boundary.py`: 1)
  - `RED_W3_C`: 4 failed (`test_intent_surface_boundary.py`: 4)
  - `RED_W3_D`: 4 failed (`test_expression_provider_boundary.py`: 4)

### 4.4 Non-Surface Full Regression Suite (`python -m pytest tests --ignore=tests/surface -q --tb=short`)
- **Pre-Implementation Baseline**: 3093 passed, 11 skipped, 4 deselected, 1 xfailed (475.38s)
- **Post-Implementation Result**: 3093 passed, 11 skipped, 4 deselected, 1 xfailed (469.75s)
- **Regressions**: **0**

---

## 5. Non-Negotiable Invariant Confirmation

1. [x] Mind Runtime is not an upgraded Xinchao product.
2. [x] PersonaProfile is the sole owner of stable BehavioralDisposition; no secondary persona authority was created.
3. [x] Trait != Current State: Disposition traits never carry dynamic runtime values.
4. [x] No automatic inference, guessing, or role card parsing was introduced for disposition traits.
5. [x] No real agent persona configs were mutated.
6. [x] Legacy schema 1 continues to work for W2 without modification and without auto-filled traits.
7. [x] Conflict detection stops identical (ID, revision) with different content.
8. [x] W2 appraisal, projection journal, dynamics gain, and transaction/commit boundaries remain completely untouched.

---

## 6. Final Verdict

`W3_A_READY_FOR_W3_B`
