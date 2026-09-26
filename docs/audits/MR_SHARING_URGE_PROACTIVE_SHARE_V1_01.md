# Audit Report: MR-SHARING-URGE-PROACTIVE-SHARE-V1-01

**Date**: 2026-09-25  
**Task ID**: `MR-SHARING-URGE-PROACTIVE-SHARE-V1-01`  
**Type**: BOUNDED FAST-STATE CONSUMER BINDING & AUDIT FREEZE  
**Base SHA**: `87193868205931436568c0d2e7a14d0dc301f340`  
**Code Freeze Candidate**: `3780d69eb8fc5b1e18e41d0a02117aa32ce137f8`  
**Target Branch**: `w/mr-sharing-urge-proactive-share-v1-01`  
**Worktree**: `C:\projects\mind-runtime-main-merge\.worktrees\mr-sharing-urge-proactive-share-v1-01`  
**Code Verdict**: `SHARING_URGE_PROACTIVE_SHARE_V1_READY_CONFIG_PENDING`  
**Final Freeze Verdict**: `SHARING_URGE_PROACTIVE_SHARE_V1_FROZEN_CONFIG_PENDING`  

---

## 1. Executive Summary

This task implements, hardens, and audits the second `FAST_FUNCTION_V1` consumer:
$$\text{agent.affect.sharing\_urge} \longrightarrow \text{PROACTIVE\_SHARE}$$

Higher `sharing_urge` increases pressure to spontaneously share a thought, observation, or currently available content with the user. It strictly obeys all kernel boundaries:
- It does **not** bypass `ActionPolicy`.
- It does **not** control outbound send frequency (`SHARING_URGE_CONTROLS_SHARE_PRESSURE != SHARING_URGE_CONTROLS_SEND_FREQUENCY`).
- It does **not** invent synthetic user/world Evidence (`SYNTHETIC_EVIDENCE_PATH = NONE`).
- It does **not** leak raw `sharing_urge` into provider context (`RAW_SHARING_URGE_PROVIDER_LEAK = NONE`).
- It does **not** directly execute provider generation inside Mind Runtime.
- It does **not** create a second delivery mechanism (reuses Hermes and established proactive delivery pipeline).

All 18 architectural, semantic, and authority constraints are verified. All 31 tests in `tests/intents/test_sharing_urge_proactive_share.py` and 14 tests in `tests/dynamics/test_fast_functions.py` pass, while 62/62 longing proactive tests pass with zero regressions.

---

## 2. Frozen Causal Pipeline

```text
agent.affect.sharing_urge
→ IntentRule(
      kind="spontaneous_share",
      dimension_weights=(("agent.affect.sharing_urge", 1.0),),
      surface_control_weights=(),
  )
→ DeterministicIntentEngine (monotonically scores candidate)
→ DeterministicActionPolicy (rules: action_type="proactive_share", proactive=True)
→ CognitiveTicker (stops strictly at WakeSignal)
→ Host validates wake lineage & authority (consume_wake)
→ Body begins proactive turn (begin_proactive_turn -> HostTurnStatus.PROCESSING)
→ DecisionContext handed to external Body (< BODY_BOUNDARY)
→ external Body runs provider generation (content-dependent prose)
→ ExpressionGuard validates external prose (guard_proactive_prose)
→ Hermes/external transport sends message (existing delivery mechanism)
→ Host commits delivery (commit_proactive_turn -> HostTurnStatus.COMMITTED, Intent ALLOWED -> COMPLETED)
```

### Pre-Body Causal Boundary
The Mind Runtime pre-Body causal sequence is:
```text
policy_allow < wake_created < host_wake_admitted < proactive_body_entry <= proactive_expression_context < BODY_BOUNDARY
```
External Body then executes provider realization. When prose returns to MR:
```text
ExpressionGuard → delivery eligibility
```
Upon external delivery completion:
```text
commit_proactive_turn → Intent COMPLETED
```
No cross-process single continuous trace is claimed.

---

## 3. Core Architectural Decisions & Invariant Validations

### 3.1 Anti-Spam Invariant (`SHARING_URGE_CONTROLS_SHARE_PRESSURE != SHARING_URGE_CONTROLS_SEND_FREQUENCY`)
- `validate_sharing_urge_anti_spam_invariant` in `src/mind_runtime/dynamics/fast_functions.py` enforces that `sharing_urge` controls candidate scoring pressure, but has zero authority to shorten, bypass, or modulate `ActionPolicy` cooldowns.
- `ActionPolicy` alone governs send frequency via `proactive_cooldown` and resource constraints.

### 3.2 Direct Dimension Binding Without Surface Pollution
- `Surface.initiative` is defined as:
  $$\text{initiative} = 0.60 \times \text{sharing\_urge} + 0.50 \times \text{curiosity} - 0.25 \times \text{sadness}$$
  `spontaneous_share` does not use `Surface.initiative` because `initiative` is a composite control containing `sharing_urge + curiosity + sadness`. Using `initiative` as the dedicated share root would permit curiosity/sadness cross-talk into the dedicated share function.
- Adding a new Surface control (`sharing_drive`, `sharing_pressure`) would mutate Candidate Recipe v2 and break its frozen digest (`4f37f46f89f6176fd5fefe0167ec7a81e341839f4fb9b98fa3cc348ddeaf9a55`).
- Therefore, the share `IntentRule` binds directly to `agent.affect.sharing_urge` via `dimension_weights=(("agent.affect.sharing_urge", 1.0),)` and explicitly sets `surface_control_weights=()`.

### 3.3 Semantic & Functional Independence from Longing
- `PROACTIVE_CONTACT != PROACTIVE_SHARE`.
- Longing drives connection seeking (`agent.affect.longing` $\rightarrow$ `Surface.contact_seeking` $\rightarrow$ `proactive_contact`).
- Sharing urge drives thought/content sharing (`agent.affect.sharing_urge` $\rightarrow$ `spontaneous_share` $\rightarrow$ `proactive_share`).
- No shared intent rules, no cross-contamination, and zero regressions in `tests/intents/test_longing_proactive_contact.py`.

### 3.4 Host Wake Admission, Guard Enforcement, and Delivery Commitment
- `consume_wake` validates against real authorities (`IntentLifecycleService`, `SqliteIntentBackend`, `DeterministicActionPolicy`) and enforces `proactive=True`.
- Guard acceptance returns `HostTurnStatus.PROCESSING`; delivery commitment is explicit via `commit_proactive_turn(wake_id)`, transitioning the Intent to `COMPLETED` and returning `HostTurnStatus.COMMITTED`.
- Guard rejection (e.g. empty or forbidden openings) immediately aborts the turn (`HostTurnStatus.ABORTED`), transitions Intent to `SUPERSEDED`, and commits zero delivery.
- Replaying duplicate wake returns `HostTurnStatus.ALREADY_PROCESSED` with 0 provider calls.

### 3.5 Evidence & Context Isolation
- `SYNTHETIC_EVIDENCE_PATH = NONE`: MR does not invent fake user/world Evidence items merely because `sharing_urge` is high.
- `RAW_SHARING_URGE_PROVIDER_LEAK = NONE`: MR does not expose raw `sharing_urge` state keys or values to provider-visible context.
- Bounds note: This bounds Mind Runtime state and context construction; it does not claim that external LLM hallucination is impossible.

---

## 4. Test Verification Summary

### 4.1 Sharing Urge Test Suite (`tests/intents/test_sharing_urge_proactive_share.py`)
Result: **31 passed in 8.94s**

1. `test_a_fast_function_v1_registry_has_exactly_eight_entries`: Verifies `FAST_FUNCTION_V1_COUNT == 8` and registry contains 8 entries.
2. `test_b_sharing_urge_maps_to_proactive_share`: Verifies `agent.affect.sharing_urge` maps to `FastFunctionKind.PROACTIVE_SHARE`, consumer is "Intent / share path", and status is `ACTIVE`.
3. `test_c_increasing_sharing_urge_monotonically_increases_share_intent_strength`: Verifies monotonically increasing sharing urge produces strictly increasing `spontaneous_share` intent strength.
4. `test_d_low_sharing_urge_below_threshold_produces_no_candidate`: Below rule threshold (0.50), no intent candidate is produced and trace records `below_minimum_strength`.
5. `test_e_high_sharing_urge_produces_spontaneous_share_candidate`: Above rule threshold (0.85 > 0.50), `spontaneous_share` candidate is produced with matching strength.
6. `test_f_changing_curiosity_alone_does_not_change_spontaneous_share_score`: Changing `curiosity` across `[0.0, 0.2, 0.5, 0.8, 1.0]` does not alter `spontaneous_share` score (zero cross-talk).
7. `test_g_changing_sadness_alone_does_not_change_spontaneous_share_score`: Changing `sadness` across `[0.0, 0.2, 0.5, 0.8, 1.0]` does not alter `spontaneous_share` score (zero cross-talk).
8. `test_h_share_rule_has_empty_surface_control_weights`: Dedicated share rule explicitly specifies `surface_control_weights == ()`.
9. `test_i_share_rule_uses_sharing_urge_as_only_fast_state_scoring_root`: Dedicated share rule specifies `dimension_weights == (("agent.affect.sharing_urge", 1.0),)`.
10. `test_j_no_new_surface_control_introduced`: Exactly 5 Surface controls exist; no new controls (`sharing_drive`, `sharing_pressure`, etc.) introduced.
11. `test_k_candidate_surface_recipe_digest_remains_unchanged`: Candidate Recipe v2 digest remains strictly `4f37f46f89f6176fd5fefe0167ec7a81e341839f4fb9b98fa3cc348ddeaf9a55`.
12. `test_l_spontaneous_share_intent_allow_emits_wake_signal`: Policy `ALLOW` for `spontaneous_share` emits a `WakeSignal` from `CognitiveTicker`.
13. `test_m_wake_signal_action_type_is_proactive_share`: The emitted `WakeSignal` carries `action_type="proactive_share"`.
14. `test_n_host_rejects_forged_share_wake_when_policy_rule_non_proactive`: Host admission rejects wake backed by non-proactive policy rule with `rejected:intent_not_proactive`.
15. `test_o_host_rejects_action_type_mismatch`: Host admission rejects wake when wake action type does not match authoritative policy rule with `rejected:unsupported_intent_action`.
16. `test_p_begin_proactive_turn_returns_processing_with_non_empty_envelope`: `begin_proactive_turn` returns status `PROCESSING` and non-empty bounded context envelope.
17. `test_q_provider_envelope_contains_selected_share_action_semantics`: Bounded context envelope contains selected action type `proactive_share` and intent kind `spontaneous_share`.
18. `test_r_provider_envelope_contains_no_literal_sharing_urge`: Bounded context envelope contains no literal `sharing_urge` state key or value.
19. `test_s_no_internal_mr_provider_execution_occurs`: `CognitiveTicker` and MR runtime invoke 0 LLM/provider calls; provider execution is external to MR.
20. `test_t_guard_accept_alone_does_not_commit`: `guard_proactive_prose` ACCEPT returns `PROCESSING` and does NOT transition Intent to `COMPLETED` or mark `COMMITTED`.
21. `test_u_guard_accept_and_explicit_commit_transitions_intent_completed`: Explicit `commit_proactive_turn` transitions Intent to `COMPLETED` and marks turn `COMMITTED`.
22. `test_v_guard_reject_fails_closed`: `guard_proactive_prose` REJECT immediately marks turn `ABORTED`, transitions Intent to `SUPERSEDED`, and commits zero delivery.
23. `test_w_higher_sharing_urge_cannot_shorten_proactive_cooldown`: High `sharing_urge` cannot shorten or alter configured `proactive_cooldown`.
24. `test_x_eligible_share_inside_cooldown_defers_and_emits_no_wake`: Within cooldown window, policy returns `DEFER` and `CognitiveTicker` emits no `WakeSignal`.
25. `test_y_no_share_specific_frequency_counters_used`: Proactive share uses general interaction recency/cooldown; no custom share frequency counters.
26. `test_z_same_wake_replay_remains_process_local_idempotent`: Replaying duplicate wake returns `ALREADY_PROCESSED` with 0 additional provider invocations.
27. `test_information_isolation_explicitly_forbids_sharing_urge`: DecisionContext compiler configuration explicitly forbids raw affect states.
28. `test_certified_manifest_proactive_share_gap_verified`: `SHARING_URGE_PRODUCTION_ACTIVATION=BLOCKED_BY_CONFIG`: Certified manifest lacks proactive share rules.
29. `test_longing_proactive_contact_remains_unaffected`: Proactive contact path for longing remains 100% operational with zero regressions.
30. `test_longing_and_sharing_distinct_intent_and_action`: Longing (`proactive_contact`) and sharing urge (`proactive_share`) have distinct intent kinds, action types, and rules.
31. `test_competition_between_longing_and_sharing_urge_single_wake`: When both are active, deterministic engine and scheduler emit exactly one wake signal without collision.

### 4.2 Fast Functions & Surface Suites
- `tests/dynamics/test_fast_functions.py`: **14 passed**
- `tests/surface/`: **128 passed**

### 4.3 Longing Suite (Regression Invariant)
- `tests/intents/test_longing_proactive_contact.py`: **62 passed in 23.42s** (ZERO regressions)

### 4.4 Full Intents Suite
- `tests/intents/`: **161 passed in 35.78s**

### 4.5 Core Regression Suite (`python -m pytest --ignore=tests/memory_vector -q`)
Target: `python -m pytest --ignore=tests/memory_vector -q`  
Result: **3299 passed, 7 skipped, 4 deselected, 1 xfailed, 2 warnings in 455.37s (0:07:35)**  
Core regression status: **`PASS`**

### 4.6 Full Repository Test Suite (`python -m pytest`)
Target: `python -m pytest`  
Result: **3316 passed, 12 failed, 11 skipped, 4 deselected, 1 xfailed, 2 warnings in 526.15s (0:08:46)**  
- `FULL_SUITE_GREEN = NO`
- `OPTIONAL_MEMORY_VECTOR_ENVIRONMENT = BLOCKED`
- `OPTIONAL_MEMORY_VECTOR_FAILURES = 12`
- Analysis: All 12 failures are located strictly within `tests/memory_vector/test_isolation_optional.py` (6) and `tests/memory_vector/test_qdrant.py` (6), caused by the optional extra package `qdrant-client` not being installed in the local virtual environment (`ProviderPackageMissing: install mind-runtime[memory-vector] for Qdrant`). No files under `memory_vector` were modified by `MR-SHARING-URGE-PROACTIVE-SHARE-V1-01`. Therefore, the 12 failures are environment/optional-extra dependency gaps, not evidence of any regression.

---

## 5. Non-Negotiable Boundaries Compliance

1. **Mind Runtime is not an upgraded Xinchao product**: Preserved.
2. **Kernel must not fix schema to 12 dimensions**: Dynamic dimensions preserved.
3. **TurnProjection is not Canonical State**: Affect projections strictly follow commit boundaries.
4. **ActionPolicy and ExpressionGuard remain separate layers**: Maintained.
5. **No provider in Ticker**: CognitiveTicker stops strictly at WakeSignal.
6. **No synthetic context reconstruction**: Fails closed if authoritative wake context is missing.
7. **No new surface controls**: Candidate Recipe v2 digest and 5 controls unchanged.
8. **Anti-spam boundary**: Sharing urge does not control send frequency.

---

## 6. Worktree Status & Merge Recommendation

- Worktree: Clean, no uncommitted files or stray debug artifacts.
- Tests: 100% passing across targeted, domain, and core suites.
- Recommendation: **READY FOR MERGE** to base branch upon review.

---

## 7. Final Status Keys

```text
FAST_FUNCTION_V1_COUNT = 8
SHARING_URGE_TO_SHARE_INTENT = PASS
SHARE_INTENT_KIND = spontaneous_share
SHARE_ACTION_TYPE = proactive_share
SHARE_DIRECT_FAST_ROOT = agent.affect.sharing_urge
SHARE_SURFACE_CONTROL = NONE
SURFACE_RECIPE_CHANGED = NO
CURIOSITY_TO_SHARE_CROSS_TALK = NONE
SADNESS_TO_SHARE_CROSS_TALK = NONE
ACTION_POLICY_GATE = PASS
PROACTIVE_WAKE_PATH = PASS
HOST_BODY_BOUNDARY_REUSED = PASS
RAW_SHARING_URGE_PROVIDER_LEAK = NONE
SYNTHETIC_EVIDENCE_PATH = NONE
SHARING_URGE_ANTI_SPAM = PASS
LONGING_REGRESSION = PASS
SHARING_URGE_CALIBRATION_STATUS = PROVISIONAL
SHARING_URGE_PRODUCTION_ACTIVATION = BLOCKED_BY_CONFIG
CORE_REGRESSION = PASS
FULL_SUITE_GREEN = NO
OPTIONAL_MEMORY_VECTOR_ENVIRONMENT = BLOCKED
CODE_VERDICT = SHARING_URGE_PROACTIVE_SHARE_V1_READY_CONFIG_PENDING
FINAL_VERDICT = SHARING_URGE_PROACTIVE_SHARE_V1_FROZEN_CONFIG_PENDING
```
