# Audit Record: MR-INITIATIVE-ADMISSION-GATE-V1-01

**Task ID**: `MR-INITIATIVE-ADMISSION-GATE-V1-01`  
**Task Type**: `ARCHITECTURE-BOUND IMPLEMENTATION`  
**Executor**: AGY  
**Base SHA**: `9b46d663ae9d8595357c16b2e71b12ae6ec017d8`  
**Branch**: `w/mr-initiative-admission-gate-v1-01`  
**ADR Authority**: `docs/adr/0030-bounded-intent-engine-initiative-admission-gate.md`  
**Architecture Decision**: `MR_INITIATIVE_ADMISSION_GATE_ARCHITECTURE_DECISION_V1.md`  
**Date**: 2026-09-25  

---

## 1. Executive Summary

This implementation closes the primary consumer path for `agent.affect.sadness` / `Surface.initiative` by implementing a bounded, independent post-domain-scoring admission gate in `DeterministicIntentEngine` for proactive motives:

$$\text{Dynamics root} \longrightarrow \text{Domain Intent strength} \longrightarrow \text{Surface.initiative admission gate} \longrightarrow \text{Admitted candidate} \longrightarrow \text{ActionPolicy} \longrightarrow \text{Downstream lifecycle}$$

The implementation respects all non-negotiable architectural boundaries:
- **Zero Alteration of Domain Strength**: `sharing_urge` and `curiosity` direct roots exclusively compute domain motivation strength; `Surface.initiative` acts solely as an independent admission gate, never contributing score amounts, ranking multipliers, or prompt guidance.
- **Fail-Closed Lineage Validation**: Rejects unadmitted motives upon missing surface (`surface_unavailable`), malformed/tampered surface controls (`surface_invalid`), or stale/mismatched execution lineage (`surface_stale_or_mismatch`).
- **Conditional Overlap Policy (`ROOT_OVERLAP_POLICY=CONDITIONAL`)**: Independent admission threshold inspection is permitted on gated rules (`minimum_initiative`), while direct score contributions (`surface_control_weights`) remain strictly rejected.
- **100% Backward Compatibility**: Wire ruleset reference calculation and SQLite JSON persistence remain byte-identical when `minimum_initiative` / `surface_admission` is `None`.
- **Zero Perturbation of Excluded Components**: Candidate Recipe v2, Expression Map v2, ActionPolicy, CognitiveTicker, Host, and the certified production manifest (`certification/d11s/inputs/runtime-config.json`) remain untouched.

---

## 2. Invariant & Architecture Verification

| Category | Invariant / Boundary | Implementation & Evidence | Result |
|---|---|---|:---:|
| **Causal Order** | Domain scoring before gate | `engine._evaluate_rule` computes unclamped/clamped domain score first; gate only evaluates if domain threshold is met. | **PASS** |
| **Domain Score Preservation** | Identical score across gate verdicts | Traces record identical `final_strength` and `unclamped_score` across gate pass, below-threshold, and lineage failures. | **PASS** |
| **No Score Contribution** | Zero initiative amount in contributions | `trace.contributions` contains base, dimension, and event entries; zero surface or initiative contributions are added. | **PASS** |
| **Gate Scope** | Restricted to proactive motives | `IntentRule.__post_init__` strictly permits `minimum_initiative` only for `spontaneous_share` (sharing_urge root) and `proactive_inquiry` (curiosity root). Rejects `reach_out`, `scheduled_follow_up`, etc. | **PASS** |
| **Root Overlap Policy** | `ROOT_OVERLAP_POLICY = CONDITIONAL` | Gated rules require empty `surface_control_weights`. Non-gated rules continue standard overlap validation. | **PASS** |
| **Lineage Validation** | Fail-closed security boundary | Validates `surface.status == AVAILABLE`, recipe digest, dependencies manifest, finite values, and lineage via `validate_projected_surface`. | **PASS** |
| **Persistence Compatibility** | Exact byte-identity on legacy records | `_surface_use_to_json` omits `"surface_admission"` when None; `rules_wire` omits `minimum_initiative` when None. | **PASS** |
| **Downstream Isolation** | Gate rejection suppresses lifecycle | Engine emits `candidates=()`, preventing candidate emission, lifecycle service admission, ActionPolicy evaluation, and WakeSignals. | **PASS** |
| **Audit Seam Reuse** | `REJECTED_TRACE_AUDIT_SEAM = REUSED` | TraceRecorder and orchestrator turn trace chains record `initiative_gate_rejected` alongside existing engine audit traces. | **PASS** |

---

## 3. Preserved Authority Hashes & Digests

- **Candidate Recipe v2 ID**: `surface-v1-candidate` (Version 2)
- **Candidate Recipe v2 Digest**: `4f37f46f89f6176fd5fefe0167ec7a81e341839f4fb9b98fa3cc348ddeaf9a55`
- **Candidate Expression Map v2 ID**: `surface-v1-candidate-map` (Version 2)
- **Candidate Expression Map v2 Digest**: `bba6794aeda7a1755f8c79ffe5c88bd100918e6bc979ea29b5aa009e958eddf3`
- **Certified Manifest**: `certification/d11s/inputs/runtime-config.json` (0 modifications, git diff empty)

---

## 4. Verification Test Results

### 4.1 Dedicated Gate Test Suite (`tests/intents/test_initiative_admission_gate.py`)
- **Total Dedicated Tests**: 31
- **Passed**: 31
- **Failed**: 0
- **Duration**: 1.12s
- **Coverage**:
  - Section 23: `TestSection23IntentRuleContract` (7 tests)
  - Section 24: `TestSection24DomainScorePreservation` (2 tests)
  - Section 25: `TestSection25GateMechanics` (1 test)
  - Section 26: `TestSection26CrossControlAdmission` (2 tests)
  - Section 27: `TestSection27LineageFailClosed` (12 tests)
  - Section 28: `TestSection28ExcludedIntents` (2 tests)
  - Section 29: `TestSection29TurnAndTick` (1 test)
  - Section 30: `TestSection30PersistenceAndRulesetRef` (3 tests)
  - Section 12: `TestSection12ConfigDecoding` (1 test)

### 4.2 Targeted Regression Suite
- **Suites**: `tests/intents/test_engine.py`, `tests/surface/test_intent_surface_boundary.py`, `tests/intents/test_sharing_urge_proactive_share.py`, `tests/intents/test_curiosity_proactive_inquiry.py`, `tests/intents/test_longing_proactive_contact.py`, `tests/surface/test_anger_boundary_confrontation.py`, `tests/surface/test_sadness_initiative_suppression.py`, `tests/intents/test_persistence.py`, `tests/cognition/`, `tests/pipeline/`, `tests/runtime_config/`
- **Passed**: 560
- **Failed**: 0
- **Duration**: 72.24s

### 4.3 Core Test Suite
- **Command**: `python -m pytest --ignore=tests/memory_vector -q`
- **Passed**: 3432
- **Skipped**: 7
- **Deselected**: 4
- **Xfailed**: 1 (G28 live-shadow certified baseline expectation)
- **Failed**: 0
- **Duration**: 466.74s

---

## 5. Audit Keys & Final Verdict

```text
TASK_ID=MR-INITIATIVE-ADMISSION-GATE-V1-01
TASK_TYPE=ARCHITECTURE-BOUND IMPLEMENTATION
BASE_SHA=9b46d663ae9d8595357c16b2e71b12ae6ec017d8
BRANCH=w/mr-initiative-admission-gate-v1-01
ADR=docs/adr/0030-bounded-intent-engine-initiative-admission-gate.md
ROOT_OVERLAP_POLICY=CONDITIONAL
REJECTED_TRACE_AUDIT_SEAM=REUSED
INITIATIVE_GATE_CALIBRATION_STATUS=PROVISIONAL
INITIATIVE_GATE_PRODUCTION_ACTIVATION=BLOCKED_BY_CONFIG
FINAL_VERDICT=INITIATIVE_ADMISSION_GATE_V1_READY_CONFIG_PENDING
```
