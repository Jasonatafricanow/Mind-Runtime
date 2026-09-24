# Audit Report: MR-LONGING-PROACTIVE-PRODUCTION-HARDENING-V1-01

**Date**: 2026-09-24  
**Task**: `MR-LONGING-PROACTIVE-PRODUCTION-HARDENING-V1-01`  
**Type**: BOUNDED PRODUCTION HARDENING + HOST/BODY BOUNDARY CORRECTION  
**Base HEAD**: `3a00bf3a68eba0cb22ede750089894e47e96c593`  
**Branch**: `w/mr-longing-proactive-contact-v1-01`  
**Final Status**: `MR_LONGING_PROACTIVE_PRODUCTION_HARDENING_V1_PASS`  

---

## 1. Executive Summary

This task completes the bounded production hardening of the longing fast-state proactive-contact path, resolving all five architectural gaps identified in the post-push source review of candidate `57515c89bf3893d7a7fe3e15c444039bab9abfe3`:

| Audit Metric | Candidate `57515c89` | Hardened Baseline | Resolution |
|---|:---:|:---:|---|
| `TICKER_PROVIDER_CAPABILITY` | `FOUND` | **`REMOVED`** | `CognitiveTicker` has no `expression` parameter, rejects kwargs, and terminates strictly at `WakeSignal`. |
| `WAKE_ADMISSION_FAIL_CLOSED` | `FAIL` | **`PASS`** | `consume_wake` validates against real authorities (`IntentLifecycleService`, `SqliteIntentBackend`, `DeterministicActionPolicy`) and fails closed on missing authority or mismatches. |
| `RESTART_CONTEXT_AUTHORITY` | `UNSAFE_FALLBACK` | **`FAIL_CLOSED_PROCESS_LOCAL`** | Deleted synthetic fallback context reconstruction in `_resolve_tick_context`; context loss fails closed with `missing_authoritative_wake_context`. |
| `PROACTIVE_DELIVERY_COMMIT` | `NOT_IMPLEMENTED` | **`IMPLEMENTED`** | Guard ACCEPT returns `PROCESSING`. Explicit `commit_proactive_turn(wake_id)` transitions Intent to `COMPLETED` and marks `COMMITTED`. `abort_proactive_turn` transitions Intent to `SUPERSEDED` and marks `ABORTED`. |
| `PRODUCTION_COMPOSITION_STATUS` | `GAP` | **`WIRED`** | `default_adapter` and `mr_seam` wire real `intent_rules`, `action_policy_config`, `policy_resources`, `delivery_db`, and `expression_guard`. |
| `PROACTIVE_RUNTIME_CONFIG_GAP` | N/A | **`FOUND`** | Certified manifest (`certification/d11s/inputs/runtime-config.json`) lacks proactive contact rules and SURFACE_V1 persona publication; recorded explicitly without mocking. |
| `CORE_CAUSAL_TEST_COMPOSITION` | `PASS` | **`PASS`** | Strict causal order preserved: `policy_allow < wake_created < host_wake_admitted < proactive_body_entry <= proactive_expression_context < provider_realization < expression_guard <= proactive_expression`. |

---

## 2. Hardened Architecture & Authority Boundaries

### 2.1 Complete Removal of CognitiveTicker Provider Capability
`CognitiveTicker` has been completely decoupled from expression realization:
- Removed `expression` parameter from `CognitiveTicker.__init__` and `build_cognitive_ticker`.
- `build_cognitive_ticker` and `CognitiveTicker` raise `TypeError` if `expression` is passed.
- Deleted `_prepare_expression(...)` and all internal expression coordinator wiring.
- `CognitiveTicker.tick(...)` stops strictly at `WakeSignal` construction.
- Non-proactive allowed intents emit no `WakeSignal`.

### 2.2 Fail-Closed Host Admission Against Real Authorities
In `MindRuntimeHostAdapter.consume_wake(...)`:
- Verifies that `orchestrator.cognitive_tick_components` or orchestrator attributes contain real `IntentLifecycleService` and `DeterministicActionPolicy`.
- Missing lifecycle authority -> `rejected:intent_authority_unavailable`.
- Missing policy authority -> `rejected:policy_authority_unavailable`.
- Validates runtime ID match (`rejected:runtime_id_mismatch`), scope match (`rejected:scope_mismatch`), intent existence (`rejected:unknown_intent_id`), intent status `ALLOWED` (`rejected:intent_not_allowed`), intent version match against authoritative lifecycle (`rejected:intent_version_mismatch`), and action type match against policy (`rejected:unsupported_intent_action`).

### 2.3 Deletion of Synthetic Fallback Context Reconstruction
- Removed the code in `_resolve_tick_context(...)` that previously reconstructed a fresh synthetic `Situation` and synthesized an `ActionPolicyResult(ALLOW)` from wake fields.
- If in-memory execution context is absent (e.g., process restart or eviction), `begin_proactive_turn` fails closed returning `HostTurnStatus.FAILED` with reason `missing_authoritative_wake_context`.
- Replay is explicitly frozen as `WAKE_REPLAY_SCOPE=PROCESS_LOCAL`.

### 2.4 Explicit Body Proactive Turn Lifecycle
The Host/Body interface enforces distinct turn states:
1. `begin_proactive_turn(wake: WakeSignal) -> HostProactiveTurnResult`:
   - Checks admission and retrieves bounded context.
   - Returns `HostTurnStatus.PROCESSING` with `outcome=HostStatus.OK` and `bounded_context`.
2. External Body runs provider generation using `bounded_context`.
3. `guard_proactive_prose(wake_id: str, prose: str) -> HostProactiveTurnResult`:
   - Runs `ExpressionGuard` against external prose.
   - Guard ACCEPT: returns `HostTurnStatus.PROCESSING` (not `COMMITTED`).
   - Guard REJECT: transitions intent to `SUPERSEDED`, marks `HostTurnStatus.ABORTED`, and clears pending context.
4. `commit_proactive_turn(wake_id: str) -> HostProactiveTurnResult`:
   - Invoked after successful transport/delivery.
   - Transitions intent from `ALLOWED` to `COMPLETED`.
   - Returns `HostTurnStatus.COMMITTED` with `outcome=HostStatus.OK`.
   - Clears pending wake and execution contexts.
5. `abort_proactive_turn(wake_id: str, reason: str) -> HostProactiveTurnResult`:
   - Transitions intent to `SUPERSEDED`.
   - Returns `HostTurnStatus.ABORTED`.
   - Clears pending wake and execution contexts.

### 2.5 Real Production Composition in default_adapter & XiyueMRAdapter
- `default_adapter` accepts `intent_rules`, `action_policy_config`, `policy_resources`, `delivery_db`, and `expression_guard`, forwarding them to `build_runtime_stack`.
- `build_runtime_stack` instantiates `SqliteIntentBackend`, `IntentLifecycleService`, `DeterministicIntentEngine`, `DeterministicActionPolicy`, and `DeterministicExpressionGuard`, binding them to `orchestrator.cognitive_tick_components`.
- `XiyueMRAdapter` exposes all proactive host methods: `consume_wake`, `begin_proactive_turn`, `guard_proactive_prose`, `commit_proactive_turn`, `abort_proactive_turn`, and `run_proactive_turn`.
- `xiyue/mr_seam.py` decodes and forwards all cognitive and delivery configuration items.

---

## 3. Verification & Test Evidence

### 3.1 Proactive Contact Test Suite
Target: `tests/intents/test_longing_proactive_contact.py`
Result: **49 passed in 19.23s**
- `test_a` - `test_c`: Ticker cannot be constructed with expression; tick cannot call provider; no source path to expression.
- `test_d` - `test_f`: Policy ALLOW creates wake; DENY/DEFER creates no wake.
- `test_g` - `test_m`: Fail-closed admission on missing authorities, wrong runtime, unknown intent, non-ALLOWED status, version mismatch, action mismatch.
- `test_n` - `test_p`: Authoritative wake admits; valid pending context used; missing pending context fails closed.
- `test_q` - `test_s`: No code reconstructs ActionPolicyResult or Situation; restart context loss fails closed.
- `test_t` - `test_aa`: Body entry returns PROCESSING; no LLM before context handover; guard validation; guard ACCEPT is PROCESSING; explicit commit transitions intent to COMPLETED; terminal cleanup; duplicate idempotent; conflicting replay fails closed.
- `test_ab` - `test_ah`: Production composition has durable lifecycle and action policy authorities; tick creates wake with admitted rule; Xiyue adapter exposes proactive methods; bounded context reaches Body without fake user turn; no internal stub agent as body; downstream transport outside MR; config gap verified.
- Causal trace, anti-spam, surface contracts, and type invariants all pass.

### 3.2 Cognition & Host Suites
Target: `tests/cognition/test_tick_expression.py`, `tests/cognition/test_tick_media_cadence.py`, `tests/host/`
Result: **327 passed in 68.76s**

### 3.3 Domain Regression Suites
Target: `tests/intents/`, `tests/expression/`, `tests/surface/`, `tests/delivery/`, `tests/dynamics/`
Result: **566 passed in 43.33s**

### 3.4 Full Repository Test Suite
Target: `python -m pytest`
Result: **3282 passed, 11 skipped, 4 deselected, 1 xfailed (G28) in 500.27s (0:08:20)**
Zero regressions across all merged delivery gates (D0-D11S).

---

## 4. Final Verdict

The longing fast-state proactive-contact path is hardened, verified, and closed against all authority boundaries:
- `TICKER_PROVIDER_CAPABILITY`: REMOVED
- `WAKE_ADMISSION_FAIL_CLOSED`: PASS
- `RESTART_CONTEXT_AUTHORITY`: FAIL_CLOSED_PROCESS_LOCAL
- `WAKE_REPLAY_SCOPE`: PROCESS_LOCAL
- `POLICY_DECISION_REF_VALIDATION`: UNRESOLVED_BY_CURRENT_STORE
- `PROACTIVE_DELIVERY_COMMIT`: IMPLEMENTED
- `PRODUCTION_COMPOSITION_STATUS`: WIRED
- `PROACTIVE_RUNTIME_CONFIG_GAP`: FOUND
- `CORE_CAUSAL_TEST_COMPOSITION`: PASS
