# Audit Report: MR-CURIOSITY-PROACTIVE-INQUIRY-V1-01

**Date**: 2026-09-25  
**Task ID**: `MR-CURIOSITY-PROACTIVE-INQUIRY-V1-01`  
**Type**: BOUNDED FAST-STATE CONSUMER BINDING & AUDIT FREEZE (QUESTION BRANCH ONLY)  
**Base SHA**: `be16499d8a673940dba3e6196f51ff7dd79be054`  
**Target Branch**: `w/mr-curiosity-proactive-inquiry-v1-01`  
**Worktree**: `C:\projects\mind-runtime-main-merge\.worktrees\mr-curiosity-proactive-inquiry-v1-01`  
**Code Verdict**: `CURIOSITY_PROACTIVE_INQUIRY_V1_READY_CONFIG_PENDING`  
**Branch Verdict**: `QUESTION_BRANCH_CLOSED_RETRIEVAL_BRANCH_DEFERRED`  

---

## 1. Executive Summary

This task implements, hardens, and audits the first concrete consumer branch for:
$$\text{agent.affect.curiosity} \longrightarrow \text{INQUIRY\_EXPLORATION}$$

In V1, curiosity is bound to proactive inquiry / follow-up questioning:
- **Question Branch (Closed)**: `agent.affect.curiosity` $\rightarrow$ `IntentRule(kind="proactive_inquiry")` $\rightarrow$ `ActionPolicy(action_type="proactive_question", proactive=True)`.
- **Retrieval Branch (Deferred)**: Autonomous background retrieval remains explicitly deferred (`CURIOSITY_RETRIEVAL_BRANCH=DEFERRED`). Retrieval provides informational context only, never action authority (`RETRIEVAL_IS_ACTION_AUTHORITY=NO`).

Higher `curiosity` increases pressure to explore, inquire, or ask a follow-up question. It strictly obeys all kernel boundaries:
- It does **not** bypass `ActionPolicy`.
- It does **not** control outbound question frequency (`CURIOSITY_CONTROLS_INQUIRY_PRESSURE != CURIOSITY_CONTROLS_QUESTION_FREQUENCY`).
- It does **not** turn retrieval into action authority or self-authorized messaging.
- It does **not** invent synthetic user/world Evidence (`SYNTHETIC_EVIDENCE_PATH = NONE`).
- It does **not** leak raw `curiosity` into provider context (`RAW_CURIOSITY_PROVIDER_LEAK = NONE`).
- It does **not** directly execute provider generation inside Mind Runtime.
- It does **not** create a second delivery mechanism (reuses Hermes and established proactive delivery pipeline).
- It does **not** pollute Surface controls or alter the Candidate Recipe v2 digest (`4f37f46f89f6176fd5fefe0167ec7a81e341839f4fb9b98fa3cc348ddeaf9a55`).

All 41 tests in `tests/intents/test_curiosity_proactive_inquiry.py` and 15 tests in `tests/dynamics/test_fast_functions.py` pass, while Longing (62/62) and Sharing Urge (31/31) tests pass with zero regressions.

---

## 2. Frozen Causal Pipeline

```text
agent.affect.curiosity
→ IntentRule(
      kind="proactive_inquiry",
      dimension_weights=(("agent.affect.curiosity", 1.0),),
      surface_control_weights=(),
  )
→ DeterministicIntentEngine (monotonically scores candidate)
→ DeterministicActionPolicy (rules: action_type="proactive_question", proactive=True)
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

### 3.1 Anti-Spam Invariant (`CURIOSITY_CONTROLS_INQUIRY_PRESSURE != CURIOSITY_CONTROLS_QUESTION_FREQUENCY`)
- `validate_curiosity_anti_spam_invariant` in `src/mind_runtime/dynamics/fast_functions.py` enforces that `curiosity` controls candidate scoring pressure, but has zero authority to shorten, bypass, or modulate `ActionPolicy` cooldowns.
- `ActionPolicy` alone governs question frequency via `proactive_cooldown` and resource constraints.

### 3.2 Direct Dimension Binding Without Surface Pollution
- `Surface.initiative` is defined as:
  $$\text{initiative} = 0.60 \times \text{sharing\_urge} + 0.50 \times \text{curiosity} - 0.25 \times \text{sadness}$$
  `proactive_inquiry` does not use `Surface.initiative` because `initiative` is a composite control containing `sharing_urge + curiosity + sadness`. Using `initiative` as the inquiry root would permit sharing urge and sadness cross-talk into the dedicated inquiry function.
- Adding a new Surface control (`curiosity_drive`, `inquiry_pressure`) would mutate Candidate Recipe v2 and break its frozen digest (`4f37f46f89f6176fd5fefe0167ec7a81e341839f4fb9b98fa3cc348ddeaf9a55`).
- Therefore, the inquiry `IntentRule` binds directly to `agent.affect.curiosity` via `dimension_weights=(("agent.affect.curiosity", 1.0),)` and explicitly sets `surface_control_weights=()`.

### 3.3 Autonomous Retrieval Deferral & Authority Independence
- `CURIOSITY_RETRIEVAL_BRANCH = "DEFERRED"`: V1 closes the question branch only. Autonomous background retrieval / tool execution is explicitly deferred.
- `RETRIEVAL_IS_ACTION_AUTHORITY = "NO"`: Memory retrieval (`MemoryRetrievalService.search(...)`) provides bounded informational context. It cannot create an `Intent`, cannot produce `ActionPolicyResult(ALLOW)`, and cannot emit a `WakeSignal`.
- `CognitiveTicker` does not invoke retrieval; tick situation explicitly has `historical_context=None`. Retrieval relevance scores are search ranking scores, not action permission strengths.

### 3.4 Semantic & Functional Independence from Longing and Sharing Urge
- `PROACTIVE_CONTACT != PROACTIVE_SHARE != INQUIRY_EXPLORATION`.
- Longing drives connection seeking (`agent.affect.longing` $\rightarrow$ `Surface.contact_seeking` $\rightarrow$ `reach_out` $\rightarrow$ `proactive_message`).
- Sharing urge drives thought/content sharing (`agent.affect.sharing_urge` $\rightarrow$ `spontaneous_share` $\rightarrow$ `proactive_share`).
- Curiosity drives epistemic inquiry (`agent.affect.curiosity` $\rightarrow$ `proactive_inquiry` $\rightarrow$ `proactive_question`).
- All three intents, actions, and function kinds remain strictly distinct.

### 3.5 Host Wake Admission, Guard Enforcement, and Delivery Commitment
- `consume_wake` validates against real authorities (`IntentLifecycleService`, `SqliteIntentBackend`, `DeterministicActionPolicy`) and enforces `proactive=True`.
- Guard acceptance returns `HostTurnStatus.PROCESSING`; delivery commitment is explicit via `commit_proactive_turn(wake_id)`, transitioning the Intent to `COMPLETED` and returning `HostTurnStatus.COMMITTED`.
- Guard rejection (e.g. empty or forbidden openings) immediately aborts the turn (`HostTurnStatus.ABORTED`), transitions Intent to `SUPERSEDED`, and commits zero delivery.
- Replaying duplicate wake returns `HostTurnStatus.ALREADY_PROCESSED` with 0 provider calls. Conflicting wake payloads fail closed (`HostTurnStatus.FAILED`).

### 3.6 Multi-Urge Competition (Three-Way Urge Resolution)
- When `reach_out`, `spontaneous_share`, and `proactive_inquiry` all compete in the same tick, candidate selection is strictly governed by rule weights and dimension values.
- Exactly one `WakeSignal` is emitted per tick. The highest-scoring candidate is selected and allowed; lower candidates are transitioned to `SUPERSEDED`.
- Zero hardcoded emotional priority exists.

### 3.7 Evidence & Context Isolation Bounds
- `SYNTHETIC_EVIDENCE_PATH = NONE`: MR does not invent fake user/world Evidence items merely because `curiosity` is high.
- `RAW_CURIOSITY_PROVIDER_LEAK = NONE`: MR does not expose raw `curiosity` state keys or values to provider-visible context (`DeterministicContextRenderer.verify_provider_information_isolation`).
- Bounds note: This bounds Mind Runtime state and context construction; it does not claim that external LLM hallucination is impossible.

---

## 4. Real Source Test Inventory

### 4.1 Dynamics Fast Function Suite (`tests/dynamics/test_fast_functions.py` - 15 tests)
1. `test_a_fast_function_v1_contains_exactly_eight_entries`
2. `test_b_all_eight_canonical_keys_are_unique`
3. `test_c_every_state_has_exactly_one_primary_function`
4. `test_d_existing_restlessness_key_remains_unchanged`
5. `test_e_restlessness_product_semantics_are_activation_excitation`
6. `test_f_diligence_pressure_maps_to_follow_up_persistence_not_frequency`
7. `test_g_fatigue_has_no_outbound_action_consumer`
8. `test_h_fatigue_is_associated_only_with_cognitive_rest_mode_ownership`
9. `test_i_legacy_states_are_not_deleted`
10. `test_j_module_has_no_dependency_on_provider_body_llm`
11. `test_k_no_numeric_psychological_calibration_is_introduced`
12. `test_registry_immutability_and_lookup`
13. `test_sharing_urge_maps_to_proactive_share`
14. `test_curiosity_maps_to_inquiry_exploration`
15. `test_fast_function_v1_count_constant`

### 4.2 Curiosity Proactive Inquiry Suite (`tests/intents/test_curiosity_proactive_inquiry.py` - 41 tests)
1. `test_a_fast_function_v1_registry_has_exactly_eight_entries`
2. `test_b_curiosity_maps_to_inquiry_exploration`
3. `test_c_increasing_curiosity_monotonically_increases_inquiry_intent_strength`
4. `test_d_low_curiosity_below_threshold_produces_no_candidate`
5. `test_e_high_curiosity_produces_proactive_inquiry_candidate`
6. `test_f_changing_sharing_urge_alone_does_not_change_proactive_inquiry_score`
7. `test_g_changing_sadness_alone_does_not_change_proactive_inquiry_score`
8. `test_h_changing_anger_or_longing_alone_does_not_change_proactive_inquiry_score`
9. `test_i_inquiry_rule_has_empty_surface_control_weights`
10. `test_j_inquiry_rule_uses_curiosity_as_only_fast_state_scoring_root`
11. `test_k_no_new_surface_control_introduced`
12. `test_l_candidate_surface_recipe_digest_remains_unchanged`
13. `test_m_proactive_inquiry_intent_allow_emits_wake_signal`
14. `test_n_wake_signal_action_type_is_proactive_question`
15. `test_o_host_rejects_forged_inquiry_wake_when_policy_rule_non_proactive`
16. `test_p_host_rejects_action_type_mismatch`
17. `test_q_begin_proactive_turn_returns_processing_with_non_empty_envelope`
18. `test_r_provider_envelope_contains_selected_inquiry_action_semantics`
19. `test_s_provider_envelope_contains_no_literal_curiosity`
20. `test_t_no_internal_mr_provider_execution_occurs`
21. `test_u_guard_accept_alone_does_not_commit`
22. `test_v_guard_accept_and_explicit_commit_transitions_intent_completed`
23. `test_w_guard_reject_fails_closed`
24. `test_x_higher_curiosity_cannot_shorten_proactive_cooldown`
25. `test_y_eligible_inquiry_inside_cooldown_defers_and_emits_no_wake`
26. `test_z_no_inquiry_specific_frequency_counters_used`
27. `test_aa_same_wake_replay_remains_process_local_idempotent`
28. `test_ab_conflicting_wake_replay_fails_closed`
29. `test_ac_curiosity_retrieval_branch_is_deferred`
30. `test_ad_retrieval_output_cannot_fabricate_or_authorize_intent`
31. `test_ae_retrieval_service_cannot_create_action_policy_allow`
32. `test_af_retrieval_service_cannot_emit_wake_signal`
33. `test_ag_cognitive_ticker_does_not_invoke_retrieval`
34. `test_ah_retrieval_score_is_not_permission_strength`
35. `test_ai_information_isolation_explicitly_forbids_curiosity`
36. `test_aj_certified_manifest_proactive_inquiry_gap_verified`
37. `test_ak_longing_proactive_contact_remains_unaffected`
38. `test_al_sharing_urge_proactive_share_remains_unaffected`
39. `test_am_longing_sharing_curiosity_distinct_intent_and_action`
40. `test_an_three_way_competition_emits_single_wake`
41. `test_ao_curiosity_wins_competition_when_highest_strength`

### 4.3 Regression Suites Verified
- `tests/intents/test_longing_proactive_contact.py`: 62 passed, 0 failed.
- `tests/intents/test_sharing_urge_proactive_share.py`: 31 passed, 0 failed.
- `tests/dynamics/test_fast_functions.py`: 15 passed, 0 failed.

---

## 5. Summary Table

| Fast State | Fast Function Kind | Intent Kind | Action Type | Proactive? | Primary Consumer | Branch Status | Production Config Status |
|---|---|---|---|:---:|---|---|---|
| `agent.affect.longing` | `PROACTIVE_CONTACT` | `reach_out` | `proactive_message` | Yes | Intent / proactive message path | Closed | Blocked by config |
| `agent.affect.sharing_urge` | `PROACTIVE_SHARE` | `spontaneous_share` | `proactive_share` | Yes | Intent / share path | Closed | Blocked by config |
| `agent.affect.curiosity` | `INQUIRY_EXPLORATION` | `proactive_inquiry` | `proactive_question` | Yes | Intent / retrieval-or-question path | Question closed, Retrieval deferred | Blocked by config |
| `agent.affect.anger` | `BOUNDARY_CONFRONTATION` | — | — | — | existing Surface/Intent/expression | Audit pending | Config pending |
| `agent.affect.sadness` | `INITIATIVE_SUPPRESSION` | — | — | No | existing initiative/expression | Existing roots | Config pending |
| `agent.affect.restlessness` | `ACTIVITY_WAKE` | — | — | No | CognitiveTicker / wake-reconsider | Contract locked | Config pending |
| `agent.affect.diligence_pressure` | `FOLLOW_UP_PERSISTENCE` | — | — | Yes | follow-up Intent reconsideration | Contract locked | Config pending |
| `agent.affect.fatigue` | `COGNITIVE_REST_PRESSURE` | — | — | No | future cognitive-mode scheduler | Registered only | Uncalibrated |

---

## 6. Final Verdict

```text
TASK=MR-CURIOSITY-PROACTIVE-INQUIRY-V1-01
BASE_SHA=be16499d8a673940dba3e6196f51ff7dd79be054
FAST_STATE=agent.affect.curiosity
FAST_FUNCTION=INQUIRY_EXPLORATION
QUESTION_BRANCH_STATUS=CLOSED
RETRIEVAL_BRANCH_STATUS=DEFERRED
RETRIEVAL_IS_ACTION_AUTHORITY=NO
INQUIRY_INTENT_KIND=proactive_inquiry
INQUIRY_ACTION_TYPE=proactive_question
ANTI_SPAM_INVARIANT=CURIOSITY_CONTROLS_INQUIRY_PRESSURE != CURIOSITY_CONTROLS_QUESTION_FREQUENCY
SURFACE_RECIPE_DIGEST=4f37f46f89f6176fd5fefe0167ec7a81e341839f4fb9b98fa3cc348ddeaf9a55
SURFACE_CONTROL_COUNT=5
CROSS_TALK_FREEDOM=VERIFIED
THREE_WAY_COMPETITION=VERIFIED
LONGING_REGRESSION=ZERO_FAILURES (62/62)
SHARING_URGE_REGRESSION=ZERO_FAILURES (31/31)
CURIOSITY_TESTS=41_PASSED
DYNAMICS_TESTS=15_PASSED
CALIBRATION_STATUS=PROVISIONAL
PRODUCTION_ACTIVATION=BLOCKED_BY_CONFIG
CODE_VERDICT=CURIOSITY_PROACTIVE_INQUIRY_V1_READY_CONFIG_PENDING
```
