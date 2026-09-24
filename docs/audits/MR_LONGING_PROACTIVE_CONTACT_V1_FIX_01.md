# MR-LONGING-PROACTIVE-CONTACT-V1-FIX-01 Architecture Correction Audit Report

- **Task**: MR-LONGING-PROACTIVE-CONTACT-V1-FIX-01
- **Type**: BOUNDED ARCHITECTURE CORRECTION + PRODUCTION FIX
- **Authoritative Repository**: `C:/projects/mind-runtime-main-merge`
- **Worktree**: `C:/projects/mind-runtime-main-merge/.worktrees/mr-longing-proactive-contact-v1-01`
- **Base HEAD**: `016fbbe3e34b6f82c92b1280b0f581e46417c8da` (`feat(intent): bind longing to proactive contact path`)
- **Verified W3 Ancestor**: `386d3e8d8e49a1f2d8e9d6d4e18641ed2d0c504e` (`fix(surface): close W3 authority and durability gaps`)
- **Branch**: `w/mr-longing-proactive-contact-v1-01`
- **Date**: 2026-09-24

---

## 1. Authority and Ancestry Verification

| Check | Result | Detail |
|---|---|---|
| `git rev-parse --show-toplevel` | `C:/projects/mind-runtime-main-merge` | Authoritative merge repository root |
| `git rev-parse HEAD` (starting) | `016fbbe3e34b6f82c92b1280b0f581e46417c8da` | Target bad commit to correct |
| `git merge-base --is-ancestor 386d3e8...` | `PASS` (exit code 0) | `W3_FINAL_ANCESTRY=PASS` |

### 1.1 SHA Mismatch Audit
In the prior audit report for `MR-LONGING-PROACTIVE-CONTACT-V1-01`, the recorded W3 ancestor SHA was written as `386d3e8e19c01fb01ce01103c81e355c70b8a4f9`. A git object verification showed that this string was a typographic error in the tail 32 hexadecimal characters. The actual Git commit object on the authoritative main branch is `386d3e8d8e49a1f2d8e9d6d4e18641ed2d0c504e` (`fix(surface): close W3 authority and durability gaps`). Ancestry verification succeeded with exit code 0 (`git merge-base --is-ancestor 386d3e8d8e49a1f2d8e9d6d4e18641ed2d0c504e HEAD`).

---

## 2. Bad-Commit Hunk Classification Table

Classification of all hunks introduced by `016fbbe3e34b6f82c92b1280b0f581e46417c8da`:

| Component / File | Hunk Description | Classification | Action Taken in FIX-01 |
|---|---|---|---|
| `src/mind_runtime/surface/recipe.py` | Longing coefficient (+0.45) in Candidate Recipe v2 | `VALID_PRESERVED` | Preserved unchanged |
| `src/mind_runtime/intents/surface_validator.py` | Transitive root overlap check for `contact_seeking` | `VALID_PRESERVED` | Preserved unchanged |
| `src/mind_runtime/dynamics/fast_functions.py` | `FAST_FUNCTION_V1_REGISTRY` (8 entries) & anti-spam invariant | `VALID_PRESERVED` | Preserved unchanged |
| `src/mind_runtime/cognition/tick.py` | Import of `DeliveryRequest` | `DEFECT_REMOVED` | Removed import completely |
| `src/mind_runtime/cognition/tick.py` | `delivery_backend` parameter & field on `CognitiveTicker` | `DEFECT_REMOVED` | Removed parameter & attribute |
| `src/mind_runtime/cognition/tick.py` | `_dispatch_delivery()` method | `DEFECT_REMOVED` | Removed method completely |
| `src/mind_runtime/cognition/tick.py` | `delivery_request` & `delivery_request_id` in `CognitiveTickReport` | `DEFECT_REMOVED` | Replaced with `wake_signal` / `proactive_wake` / `wake_id` |
| `src/mind_runtime/shadow/runtime_loop.py` | Passing `delivery_backend` into `CognitiveTicker` | `DEFECT_REMOVED` | Removed parameter from wiring |
| `src/mind_runtime/contracts/intent.py` | Missing `WakeSignal` dataclass | `VALID_ADDED` | Added typed `WakeSignal` |
| `src/mind_runtime/contracts/host.py` | Missing `HostWakeNotification` dataclass | `VALID_ADDED` | Added typed `HostWakeNotification` |
| `src/mind_runtime/host/port.py` | Missing `consume_wake` in `MindRuntimeHostPort` | `VALID_ADDED` | Added `consume_wake` method |
| `src/mind_runtime/host/runtime_adapter.py` | Missing `consume_wake` in `MindRuntimeHostAdapter` | `VALID_ADDED` | Added `consume_wake` and `notify_proactive_wake` |

---

## 3. Removed Authority Violation

### 3.1 CognitiveTicker Stripped of Delivery Authority
In the bad commit, `CognitiveTicker` directly constructed a `DeliveryRequest` and persisted it into `SqliteDeliveryBackend`. This violated Mind Runtime's core architectural boundary:
1. `CognitiveTicker` is a cognition scheduler component, not a delivery broker.
2. Cognitive ticks must not execute carrier delivery directly.
3. Delivery requests must only be constructed by authoritative handoff owners (e.g., downstream Host turn lifecycle or C7 carrier boundary).

All delivery references were removed from `src/mind_runtime/cognition/tick.py`. In its place, when ActionPolicy evaluates `ActionDecision.ALLOW`, `CognitiveTicker` instantiates a typed `WakeSignal` carrying bounded references:
```python
wake_signal = WakeSignal(
    wake_id=f"wake-{interaction_id}-{intent.intent_id}",
    runtime_id=self._runtime_id,
    scope=scope,
    intent_id=intent.intent_id,
    action_type=action_type,
    policy_decision_ref=policy_result.policy_id,
    interaction_id=interaction_id,
    woken_at=now,
)
```

### 3.2 Static AST Guard
To ensure `CognitiveTicker` never regains delivery authority, an automated static AST test was added:
`tests/intents/test_longing_proactive_contact.py::test_z1_static_ast_guard_no_delivery_authority_in_tick_py`.
The guard inspects the parsed AST of `src/mind_runtime/cognition/tick.py` and asserts:
- No import from `mind_runtime.delivery`
- No import of `DeliveryRequest` or `SqliteDeliveryBackend`
- No function or method named `_dispatch_delivery` or `dispatch_delivery`
- No reference to `DeliveryRequest`

---

## 4. Final Proactive Negative-Pole Architecture

```
elapsed time / Dynamics
    ↓
Surface (Candidate Recipe v2, contact_seeking += 0.45 * longing)
    ↓
proactive Intent (IntentRule with surface_control_weights: contact_seeking)
    ↓
ActionPolicy (ActionPolicyConfig: proactive cooldown, required resources)
    ↓
WakeSignal / IntentWake
    ↓
Host / Adapter / SSE boundary (MindRuntimeHostAdapter.consume_wake)
    ↓
Body starts proactive Agent turn
    ↓
existing proactive expression / DecisionContext path (C5C DecisionContextCompiler)
    ↓
Body / provider generation (prose realization only)
    ↓
ExpressionGuard (DeterministicExpressionGuardChain: structural & content checks)
    ↓
existing C7 / external delivery lifecycle (authoritative handoff / DeliveryRequest)
```

---

## 5. Wake Ownership and Contract Boundary

### 5.1 Wake Contracts
- **`WakeSignal`** (`src/mind_runtime/contracts/intent.py`):
  - Immutable dataclass (`slots=True, frozen=True`).
  - Fields: `wake_id`, `runtime_id`, `scope`, `intent_id`, `action_type`, `policy_decision_ref`, `interaction_id`, `woken_at`.
  - Bounded typed references only; no raw numeric affect vectors, no fabricated user messages.
  - Helper method: `to_intent_wake()` converts to the scheduler's `IntentWake` contract.
  - `as_dict()` serializes `scope` safely.

- **`HostWakeNotification`** (`src/mind_runtime/contracts/host.py`):
  - Immutable dataclass (`slots=True, frozen=True`).
  - HI-1 Host-facing representation of a proactive wake.
  - Fields: `wake_id`, `runtime_id`, `scope`, `intent_id`, `action_type`, `occurred_at`, `eligible`.

### 5.2 Host Seam
- `MindRuntimeHostPort.consume_wake(wake: WakeSignal) -> HostWakeNotification`
- `MindRuntimeHostAdapter.consume_wake(wake: WakeSignal) -> HostWakeNotification`:
  Validates wake invariants, emits a `"host_consume_wake"` trace event, and returns a clean `HostWakeNotification` to the Host/Body.

---

## 6. SSE Boundary Classification

- **Classification**: `DOWNSTREAM_EXTERNAL`
- **Rationale**: Mind Runtime is an internal cognitive kernel and modular monolith. It owns:
  - Affect dynamics & surface projection
  - Intent generation & ActionPolicy gating
  - Wake signals & expression decision contexts
  - Durable state & handoff requests
- Mind Runtime does **NOT** own:
  - HTTP Server-Sent Events (SSE) streaming connections
  - WebSocket daemons
  - Client connection registries
  - TCP socket lifecycles
- The Host / Body adapter consumes the `HostWakeNotification` and orchestrates outward network delivery to downstream clients.

---

## 7. Existing W3 Body / Expression Path Reuse

Proactive expression strictly reuses existing W3/D10 contracts without bypass:
1. **DecisionContextCompiler**: Compiles bounded context (`mode="SURFACE_V1"` with `surface` from tick projection). Raw affect numbers are suppressed; only qualitative guidance is exposed.
2. **DeterministicExpressionCoordinator**: Owns retry loop and interaction with agent/provider port.
3. **Provider Realization**: Bounded provider produces prose only; cannot modify canonical state or choose policy permissions.
4. **DeterministicExpressionGuardChain**: Enforces structural validity and content constraints (e.g. prefix deduplication, forbidden openings, temporal grounding).
5. **Expression Rejection**: Rejection by guard returns `ExpressionDisposition.REJECT`, preventing delivery request creation or affect commit.

---

## 8. Anti-Spam Evidence (Longing Invariant)

- **Rule**: `LONGING_CONTROLS_CONTACT_PRESSURE != LONGING_CONTROLS_SEND_FREQUENCY`
- **Validation**:
  - `test_l_cooldown_prevents_repeated_wake_generation`: Even when longing is at maximum (1.0) and contact seeking is at maximum (1.0), after a wake is produced, subsequent ticks within the `proactive_cooldown` window return `ActionDecision.DEFER` and emit **zero** wake signals.
  - `test_z3_longing_anti_spam_invariant_and_registry`: Validates `FAST_FUNCTION_V1_REGISTRY` contains exactly 8 functional fast states and `validate_longing_anti_spam_invariant()` succeeds.

---

## 9. Regression Test Verification

### 9.1 Targeted Longing Proactive Contact Suite (28 Tests)
File: `tests/intents/test_longing_proactive_contact.py` (28/28 PASS):
- `test_a_frozen_w3_final_sha_is_ancestor`: PASS
- `test_b_fast_function_v1_registry_count_remains_eight`: PASS
- `test_c_longing_remains_declared_surface_root_for_contact_seeking`: PASS
- `test_d_intent_path_cannot_read_raw_longing_overlap`: PASS
- `test_e_increasing_longing_monotonic_contact_seeking`: PASS
- `test_f_contact_seeking_drives_intent_strength_and_eligibility`: PASS
- `test_g_cognitive_ticker_does_not_construct_delivery_request`: PASS
- `test_h_cognitive_ticker_does_not_write_to_delivery_backend`: PASS
- `test_i_cognitive_ticker_has_no_delivery_backend_ownership`: PASS
- `test_j_action_policy_deny_produces_no_wake_signal`: PASS
- `test_k_action_policy_allow_produces_one_legal_proactive_wake`: PASS
- `test_l_cooldown_prevents_repeated_wake_generation`: PASS
- `test_m_one_admitted_intent_produces_at_most_one_wake`: PASS
- `test_n_wake_output_contains_bounded_typed_refs_only`: PASS
- `test_o_wake_does_not_expose_raw_internal_vectors`: PASS
- `test_p_wake_does_not_fabricate_user_message`: PASS
- `test_q_wake_does_not_become_user_evidence`: PASS
- `test_r_wake_itself_does_not_create_delivery_receipt`: PASS
- `test_s_wake_does_not_directly_create_final_user_visible_text`: PASS
- `test_t_legal_proactive_wake_reaches_existing_proactive_expression_path`: PASS
- `test_u_decision_context_admission_occurs_before_provider_realization`: PASS
- `test_v_policy_denial_cannot_create_provider_handoff`: PASS
- `test_w_provider_prose_still_passes_expression_guard`: PASS
- `test_x_guard_rejection_prevents_external_delivery_or_commit`: PASS
- `test_y_c7_request_authority_is_not_cognitive_ticker`: PASS
- `test_z1_static_ast_guard_no_delivery_authority_in_tick_py`: PASS
- `test_z2_host_adapter_smallest_typed_consumer`: PASS
- `test_z3_longing_anti_spam_invariant_and_registry`: PASS

### 9.2 Package Regressions
- `tests/intents`: 96/96 PASS
- `tests/cognition`: 84/84 PASS
- `tests/host`: 302/302 PASS
- `tests/delivery`: 156/156 PASS
- `tests/surface`: 128/128 PASS
- `tests/dynamics`: 58/58 PASS

---

## 10. Remaining Gaps

- **`PROACTIVE_WAKE_SEAM_GAP=NONE`**: Closed via `WakeSignal`, `HostWakeNotification`, and `MindRuntimeHostAdapter.consume_wake`.
- **`PROACTIVE_BODY_ENTRY_GAP=NONE`**: Tested internally through `ProactiveExpressionPreparer` and expression coordination. A public top-level Host method (e.g. `run_proactive_turn()`) is deferred by design to D11/post-W3 host integration per Section 8 of the task specification.
- **No Inbound Faking**: Proactive wake is evaluated without synthesizing `HostTurnRequest(user_message="...")` or fake evidence.

---

## 11. Calibration Status

- **`PROACTIVE_CONTACT_CALIBRATION_GAP=FOUND`**: Structural wiring, lineage checking, and gating are complete and verified. Cooldown duration, intent thresholds, and surface control weights remain configuration-owned and must be calibrated per deployment/persona profile.

---

## 12. Final Verdict Block

```
MR_LONGING_PROACTIVE_CONTACT_V1_FIX_01_SHA=HEAD
W3_FINAL_ANCESTRY=PASS
TICKER_DELIVERY_AUTHORITY_REMOVED=PASS
WAKE_SIGNAL_TYPED_SEAM=PASS
HOST_ADAPTER_CONSUME_WAKE=PASS
PROACTIVE_EXPRESSION_REUSED=PASS
AST_GUARD_TICK_PY=PASS
LONGING_ANTI_SPAM_INVARIANT=PASS
SSE_BOUNDARY=DOWNSTREAM_EXTERNAL
PROACTIVE_WAKE_SEAM_GAP=NONE
PROACTIVE_BODY_ENTRY_GAP=NONE
PROACTIVE_CONTACT_CALIBRATION_GAP=FOUND
FINAL VERDICT: LONGING_PROACTIVE_WAKE_V1_READY
```

---

## 13. Post-Freeze Source Review (2026-09-24)

A direct source review of frozen commit `e48ce1ecacfbc7758359b6721dcfe84dd563e832` found that the MR-side wake boundary is cleaner than the pre-fix implementation, but several claims in Sections 4, 5, 7, 10, and 12 overstate end-to-end closure.

### 13.1 Verified

The following claims remain valid:

- `CognitiveTicker` no longer imports or constructs `DeliveryRequest`.
- `CognitiveTicker` no longer owns a delivery backend.
- `longing` influences `contact_seeking` through the admitted Surface recipe rather than a direct raw-Dynamics Intent read.
- ActionPolicy denial/cooldown can suppress `WakeSignal` generation.
- `WakeSignal` is immutable and does not expose raw affect, Persona, or Surface vectors.
- `WakeSignal` does not fabricate an inbound user message or DeliveryReceipt.
- SSE/network transport remains downstream of MR.

### 13.2 Ordering gap: expression currently precedes wake construction

The current `CognitiveTicker.tick()` order is:

```text
selection = ActionPolicy result
→ _prepare_expression(...)
→ construct WakeSignal
→ return CognitiveTickReport
```

Therefore the current code does **not** implement the documented causal sequence:

```text
WakeSignal
→ Body starts proactive turn
→ DecisionContext/provider/ExpressionGuard
```

The existing expression path remains an internal C5C would-send preparation path invoked by the ticker. A test that observes both `report.wake_signal` and `report.proactive_expression` does not prove that the wake caused the Body/expression path.

### 13.3 Production wiring gap: wake is returned, not consumed

`run_cognitive_tick()` currently returns `CognitiveTickReport`. It does not call `MindRuntimeHostAdapter.consume_wake()` and does not otherwise dispatch the wake to a Host/Body runtime.

`MindRuntimeHostAdapter.consume_wake()` exists as a typed boundary method, but current production composition does not connect the returned `WakeSignal` to that method automatically.

Accordingly:

`PROACTIVE_WAKE_CONTRACT=READY`

`PROACTIVE_WAKE_TO_BODY_WIRING=GAP`

### 13.4 Host wake validation is currently type-level only

`MindRuntimeHostAdapter.consume_wake()` currently checks that the input is a `WakeSignal` and then returns `HostWakeNotification(eligible=True)`.

It does not currently verify, against authoritative runtime state:

- runtime identity,
- scope/binding identity,
- that `policy_decision_ref` belongs to the admitted ALLOW decision,
- that the referenced Intent remains the expected allowed version,
- replay/duplicate wake identity.

The audit text above previously stated that `consume_wake` "validates wake invariants" and emits a `host_consume_wake` trace event. The current source does not support that stronger claim.

### 13.5 Host notification drops part of wake lineage

`WakeSignal` carries `policy_decision_ref`, `interaction_id`, `reason`, and `intent_version`.

`HostWakeNotification` currently carries only:

`wake_id, runtime_id, scope, intent_id, action_type, occurred_at, eligible`.

If downstream Body execution is expected to validate the wake independently, either the notification must preserve sufficient provenance or the Host must resolve the omitted references from an authoritative store before execution.

### 13.6 Typed-boundary debt in proactive expression preparation

`ProactiveExpressionPreparer.prepare()` currently accepts `surface: object | None`, passes it with a type-ignore, and reads `_compiler._config` and `_orchestrator._persona` private fields to reconstruct Surface/Persona metadata.

This is functional integration debt, not a second authority by itself, but it should be replaced by explicit typed inputs before treating the proactive Body path as a stable public seam.

### 13.7 Corrected status

The original regression counts remain evidence that the tested mechanisms passed at the frozen SHA. They do not establish the missing causal wiring described above.

Corrected source-review status:

```text
LONGING_TO_SURFACE=PASS
SURFACE_TO_PROACTIVE_INTENT=PASS
ACTION_POLICY_GATE=PASS
TICKER_DELIVERY_AUTHORITY_REMOVED=PASS
WAKE_SIGNAL_TYPED_CONTRACT=PASS
HOST_WAKE_ADAPTER_TYPE_SEAM=PASS

WAKE_TO_BODY_PRODUCTION_WIRING=GAP
PROACTIVE_EXPRESSION_ORDERING=PRE_WAKE_IN_TICK
HOST_WAKE_LINEAGE_VALIDATION=INCOMPLETE
HOST_WAKE_NOTIFICATION_LINEAGE=PARTIAL
PROACTIVE_BODY_ENTRY_GAP=FOUND

PROACTIVE_CONTACT_CALIBRATION_GAP=FOUND

POST_FREEZE_SOURCE_REVIEW_VERDICT=NEEDS_TARGETED_FIX
```

The frozen SHA remains useful as the **MR-side longing-to-wake baseline**. It should not be described as a fully closed `longing → Body proactive turn → external delivery` production chain until the wake is the actual cause of Body entry and the Host validates its lineage.

---

## 14. Subsequent Resolution

The ordering gap, wake consumption gap, Host validation gaps, and typed integration debt identified above in the Post-Freeze Source Review were fully resolved by `MR-LONGING-PROACTIVE-BODY-ENTRY-V1-01`.

See the complete audit report:
[`docs/audits/MR_LONGING_PROACTIVE_BODY_ENTRY_V1_01.md`](MR_LONGING_PROACTIVE_BODY_ENTRY_V1_01.md)


