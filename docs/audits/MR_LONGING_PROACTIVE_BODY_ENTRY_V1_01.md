# Audit Report: MR-LONGING-PROACTIVE-BODY-ENTRY-V1-01

**Date**: 2026-09-24  
**Task**: `MR-LONGING-PROACTIVE-BODY-ENTRY-V1-01`  
**Type**: BOUNDED PRODUCTION INTEGRATION + CAUSAL-ORDER CORRECTION  
**Starting Baseline**: `LONGING_PROACTIVE_WAKE_V1_SHA = e48ce1ecacfbc7758359b6721dcfe84dd563e832`  
**Remote Branch HEAD**: `154139ff63e304029fb672175fe0c56ed3717ac4`  
**Final Status**: `LONGING_PROACTIVE_BODY_ENTRY_V1_READY`

---

## 1. Executive Summary

This task closes the causal gap identified in the post-freeze source review of `e48ce1ecacfbc7758359b6721dcfe84dd563e832`. In the previous baseline, `CognitiveTicker.tick()` prepared expression (and thus executed provider generation) before constructing the `WakeSignal`, meaning the wake did not cause the expression.

Under `MR-LONGING-PROACTIVE-BODY-ENTRY-V1-01`:
1. `CognitiveTicker.tick()` stops at `WakeSignal` construction. In the proactive contact production path, the ticker does **not** call provider realization. Before Host wake admission, `provider_call_count == 0`.
2. `MindRuntimeHostAdapter.consume_wake()` implements strict admission gating: validating runtime ID, scope, Intent existence, Intent status (`ALLOWED`), authoritative Intent version match, and action type match. Replay of identical wakes is idempotent (`ALREADY_PROCESSED`); conflicting wake payloads fail closed.
3. `HostWakeNotification` preserves complete bounded lineage (`intent_version`, `interaction_id`, `policy_decision_ref`, `reason`).
4. `MindRuntimeHostPort` and `MindRuntimeHostAdapter` provide `run_proactive_turn(wake: WakeSignal) -> HostProactiveTurnResult`.
5. Proactive expression is cleanly split into Phase A (`prepare_context`) and Phase B (`realize_after_wake`). Provider realization executes **only after** wake admission.
6. ExpressionGuard evaluation occurs after provider generation; on guard rejection, the turn aborts without delivery eligibility.

---

## 2. Answers to the 5 Mandatory Audit Questions

### Question 1: What exact object currently owns proactive provider invocation?
**Answer**: `DeterministicExpressionCoordinator.express(...)`, driven by `ProactiveExpressionPreparer.realize_after_wake(...)` during Host proactive turn execution (`MindRuntimeHostAdapter.run_proactive_turn`). Provider invocation is owned by the Host/Body execution boundary, **not** `CognitiveTicker`.

### Question 2: What exact data does it need from the tick?
**Answer**:
1. Authoritative `Intent` (with `IntentStatus.ALLOWED` and version 2).
2. `ActionPolicyResult` with permission matching the proactive action type (`"proactive_message"`).
3. The frozen `Situation` instance from the tick.
4. `ProjectedMindState` containing the uncommitted projected mind state.
5. The `assessment_trace_ref` string from `EmotionalTransitionResult.assessment_trace.trace_id`.
6. `accepted_appraisals` from the transition.
7. Durable `state_rows` loaded from the state backend.
8. `persona_ref`, `persona_version`, and `persona_content_digest`.
9. `SurfaceProjectionResult` from surface projection.
10. Wall-clock timestamp (`now`).

### Question 3: Can that data be reconstructed safely after Wake admission?
**Answer**: Yes. When `CognitiveTicker` emits a `WakeSignal`, it indexes the deterministic tick execution context in `_pending_wake_contexts[wake_id]`. Upon Host wake admission, `run_proactive_turn(wake)` retrieves this context and passes it to `prepare_context(...)` and `realize_after_wake(...)`, ensuring deterministic, safe reconstruction without re-running dynamics or fabricating turns.

### Question 4: Is there an existing Host/Body proactive entry seam?
**Answer**: Prior to this task, `MindRuntimeHostPort` only provided `begin_turn` for inbound user messages (`HostTurnRequest`). There was no typed proactive turn entry seam.

### Question 5: If not, what is the minimum new typed seam required?
**Answer**:
```python
class MindRuntimeHostPort(Protocol):
    def consume_wake(self, wake: WakeSignal) -> HostWakeNotification: ...
    def run_proactive_turn(self, wake: WakeSignal) -> HostProactiveTurnResult: ...
```
Accompanied by the immutable result contract:
```python
@dataclass(frozen=True, slots=True)
class HostProactiveTurnResult:
    wake_id: str
    runtime_id: str
    scope: Scope
    intent_id: str
    action_type: str
    status: HostTurnStatus
    outcome: HostStatus
    expression_ref: str | None = None
    would_send: str | None = None
    reason: str | None = None
```

---

## 3. Verified Causal Order

The trace ordering across all components proves the invariant:

$$\text{policy\_allow} < \text{wake\_created} < \text{host\_wake\_admitted} < \text{proactive\_body\_entry} \le \text{proactive\_expression\_context} < \text{provider\_realization} < \text{expression\_guard} \le \text{proactive\_expression}$$

Verified by test `test_e_trace_ordering_proves_causal_sequence`:
- `policy_allow`: Recorded by `CognitiveTicker._decide()` on ActionPolicy ALLOW.
- `wake_created`: Recorded by `CognitiveTicker.tick()` on WakeSignal construction.
- `host_wake_admitted`: Recorded by `MindRuntimeHostAdapter.consume_wake()` on admission.
- `proactive_body_entry`: Recorded by `MindRuntimeHostAdapter.run_proactive_turn()`.
- `proactive_expression_context`: Recorded by `ProactiveExpressionPreparer.prepare_context()`.
- `provider_realization`: Recorded by `ProactiveExpressionPreparer.realize_after_wake()` immediately before calling `DeterministicExpressionCoordinator.express()`.
- `expression_guard`: Recorded by `ProactiveExpressionPreparer.realize_after_wake()` after guard evaluation.
- `proactive_expression`: Recorded by `ProactiveExpressionPreparer.realize_after_wake()` on final artifact creation.

---

## 4. Host Wake Validation Analysis

`MindRuntimeHostAdapter.consume_wake()` validates:
1. `runtime_id`: Rejects mismatch (`"rejected:runtime_id_mismatch"`).
2. `scope`: Rejects scope domain or ID mismatch (`"rejected:scope_mismatch"`).
3. `intent_id`: Rejects non-existent intent in authoritative lifecycle (`"rejected:intent_not_found"`).
4. `intent.status`: Rejects if referenced intent is not `IntentStatus.ALLOWED` (`"rejected:intent_not_allowed"`).
5. `intent_version`: Rejects if `wake.intent_version` does not match `intent.sync.version` (`"rejected:intent_version_mismatch"`).
6. `action_type`: Rejects if wake action type does not match intent kind (`"rejected:action_type_mismatch"`).
7. `policy_decision_ref`: Documented as `POLICY_DECISION_REF_VALIDATION=UNRESOLVED_BY_CURRENT_STORE` (ActionPolicy produces transient decision objects; no durable policy decision store exists in the current architecture).
8. **Process-Local Replay & Conflict**:
   - Same `wake_id` with identical payload: returns `HostWakeNotification(eligible=False, reason="already_admitted")`. In `run_proactive_turn`, returns `HostProactiveTurnResult(status=HostTurnStatus.ALREADY_PROCESSED, outcome=HostStatus.ALREADY_PROCESSED)` with 0 provider calls.
   - Same `wake_id` with conflicting payload: fails closed (`HostTurnStatus.FAILED`, `HostStatus.FAILED`).

---

## 5. Lineage & Non-Pollution Invariants

1. **HostWakeNotification Lineage**: Preserves all 11 fields (`wake_id`, `runtime_id`, `scope`, `intent_id`, `intent_version`, `action_type`, `interaction_id`, `policy_decision_ref`, `occurred_at`, `reason`, `eligible`).
2. **No Raw Leakage**: Neither `WakeSignal`, `HostWakeNotification`, nor `HostProactiveTurnResult` exposes internal dynamics (`longing`), Persona cards, or raw Surface control vectors.
3. **No Inbound Faking**: Proactive wake processing never instantiates `HostTurnRequest(user_message="...")` or invokes `begin_turn`.
4. **No User Evidence Fabrication**: Wake processing admits zero `user_message` Evidence records.
5. **No Ticker Delivery Authority**: AST inspection confirms `src/mind_runtime/cognition/tick.py` has no reference to `DeliveryRequest` or delivery backends.

---

## 6. Status Semantics

- `FAST_STATE_CONTRACT_STATUS=ACTIVE`
- `CONSUMER_STRUCTURAL_STATUS=PASS`
- `CONSUMER_PRODUCTION_WIRING_STATUS=PASS`
- `CALIBRATION_STATUS=PROVISIONAL`
- `PROACTIVE_BODY_ENTRY_GAP=NONE` (provider invocation demonstrably depends on successful wake admission)
- `PROACTIVE_CONTACT_CALIBRATION_GAP=FOUND` (timing, cooldown, and surface weights remain configuration-owned)

---

## 7. Verification Summary

### Targeted Suites (All PASS)
- `tests/intents/test_longing_proactive_contact.py`: **35/35 PASS**
- `tests/intents`: **103/103 PASS**
- `tests/cognition`: **84/84 PASS**
- `tests/host`: **302/302 PASS**
- `tests/surface`: **128/128 PASS**
- `tests/expression`: **107/107 PASS**
- `tests/delivery`: **156/156 PASS**
- `tests/dynamics`: **58/58 PASS**

### Full Repository Test Suite (Single Run)
```text
3268 passed, 11 skipped, 4 deselected, 1 xfailed in 385.62s
```
- Total test count: 3284
- Failures: 0
- Expected strict xfail: 1 (`test_golden_g24_g28.py::test_g28_full_loop_strict_xfail`)
