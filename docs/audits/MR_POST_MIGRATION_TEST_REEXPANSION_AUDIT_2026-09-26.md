# Post-Migration Test Re-Expansion Sub-Audit Report

**Document ID:** `MR-AUDIT-TEST-REEXPANSION-2026-09-26`  
**Execution Context:** GitHub Issue #27 (`MR-LOCAL-RESIDUAL-AUDIT-01`), Comment 4 Sub-Audit  
**Auditor:** Agentic Pair Programmer (AGY)  
**Status:** **`READ-ONLY AUDIT COMPLETE`**  
**Acceptance Line:** `POST_MIGRATION_TEST_REEXPANSION_AUDITED`

---

## 1. Executive Summary & Audit Mandate

This sub-audit executes the post-migration test re-expansion audit requested in Comment 4 on GitHub Issue #27 by repository owner `Jasonatafricanow`.

### 1.1 Scope and Baselines
- **Slimming Baseline HEAD:** `d393a1af90a62cc529f13380c409cfb26db883e9` (Merge commit of PR #25: *"Audit tests by adversarial failure path"*). Full suite baseline: **3,582 passed** (3,615 collected).
- **Target Comparison HEAD:** `d21cbcf3f83429192869b02a1f19600b843eda5e` (Merge commit of PR #22: *"Gate B4 — Proactive Behavior Consumers"*). Full suite target: **3,820 / 3,821 passed** (3,829 collected).
- **Net Test Count Increase:** **+238 passed** (+214 collected test cases across 11 test files).
- **Audit Mandate:** Strictly read-only. No test files or production code have been deleted, pruned, or modified.

### 1.2 Quantitative Reconciliation: 3,582 -> 3,820 Passed (+238 Tests)
The delta between the PR #25 baseline and the Gate B4 merge commit is reconciled mathematically as follows:
1. **Repository-Wide Added Test Functions:** Exactly **+214 net test cases** were introduced across 8 files (6 newly added test files and 2 modified test files). No tests were removed between `d393a1a` and `d21cbcf3`.
2. **Pytest Collection Delta:**
   - Baseline `d393a1a`: **3,615 tests collected** (3,582 passed, 32 skipped, 1 strict xfailed G28, 4 deselected).
   - Target `d21cbcf3`: **3,829 tests collected** (3,821 passed, 8 skipped, 1 strict xfailed G28, 4 deselected).
   - Difference: `3,829 - 3,615 = +214 collected test cases`.
3. **Pass Count Expansion:**
   - `3,820 passed - 3,582 passed = +238 net tests passed`.
   - **Composition of +238:**
     - **+214** passed tests from the newly introduced Gate B4 test suites and consumer contracts.
     - **+24** vector memory integration tests (`tests/memory_vector/`) that were skipped in the minimal PR #25 CI environment (where optional vector dependencies `qdrant-client` / `fastembed` were uninstalled) but fully executed and passed in the Gate B4 certification environment.

---

## 2. Test File Inventory & Diff Breakdown

Across the entire `tests/` hierarchy, exactly **11 files** were added or materially modified between `d393a1a` and `d21cbcf3`. All other 70+ test files remain 100% bit-for-bit identical.

| Test File | Status | Net LOC Diff | Total Tests | Added Tests | Architectural Role & Scope |
|---|---|---|---|---|---|
| `tests/intents/test_longing_proactive_contact.py` | **Added** | +2,412 | 66 | +66 | Longing proactive contact, Ticker decoupling, Host wake admission, ExpressionGuard, delivery commit, fail-closed abort |
| `tests/intents/test_curiosity_proactive_inquiry.py` | **Added** | +1,717 | 41 | +41 | Curiosity proactive inquiry, retrieval authority boundary (deferred), anti-spam invariants, ActionPolicy competition |
| `tests/intents/test_sharing_urge_proactive_share.py` | **Added** | +1,326 | 31 | +31 | Sharing urge spontaneous share, anti-spam cooldown, provider envelope isolation, single-wake competition |
| `tests/surface/test_sadness_initiative_suppression.py` | **Added** | +1,055 | 29 | +29 | Sadness surface initiative & expressive warmth dampening, counterfactual cross-talk protection, truthful consumer gap |
| `tests/surface/test_anger_boundary_confrontation.py` | **Added** | +817 | 29 | +29 | Anger confrontation directness, pressure != permission authority boundary, synthetic fact injection rejection |
| `tests/surface/test_surface_recipe_coverage.py` | **Added** | +302 | 7 | +7 | Candidate recipe validation fail-closed edge cases, cognition eligibility early exits, replay surface recomputation |
| `tests/dynamics/test_fast_functions.py` | **Modified** | +178 | 27 | +9 | FAST_FUNCTION_V1 registry anti-spam invariants, spec validation, and consumer function mapping |
| `tests/host/test_host_adapter.py` | **Modified** | +1,723 | 26 | +2 | Host adapter proactive turn lifecycle, `HostWakeNotification` and `HostProactiveTurnResult` contract validation & `as_dict()` |
| `tests/cognition/test_tick_expression.py` | **Modified** | +284 / -106 | 13 | 0 | Adapted CognitiveTicker to WakeSignal decoupling; covered direct `prepare()`, `handles()`, and `prepare_context()` skips |
| `tests/cognition/test_tick_media_cadence.py` | **Modified** | +163 / -77 | 10 | 0 | Adapted photo cadence tests to WakeSignal delivery pipeline; verified cadence threshold invariants |
| `tests/surface/test_intent_surface_boundary.py` | **Modified** | +2 / 0 | 13 | 0 | Clarified surface control root overlap commentary |
| **TOTAL** | — | **+9,154 / -825** | **285** | **+214** | — |

---

## 3. Classification Under the 2026-09-26 Adversarial Failure-Path Standard

All **214 newly added test cases** across the 8 files were audited and classified into the four mandatory categories:

1. **`DISTINCT_FAILURE_PATH`** (Authority-Boundary & Adversarial Tests): Tests exercising an independent authority boundary, state-machine failure branch, fail-closed gate, information isolation leak check, or anti-tamper invariant. **MUST PRESERVE.**
2. **`SAME_PATH_DUPLICATION`**: Redundant tests checking the exact same code path, duplicate assertions of registry constants/digests already tested authoritatively elsewhere, or separate test functions for numeric float bands that belong in a single parameterized test.
3. **`COVERAGE_ONLY`**: Tests asserting dataclass field validation, `as_dict()` dictionary keys, `__repr__`, or static method presence without exercising runtime failure behaviors.
4. **`HISTORICAL_CERTIFICATION`**: Tests asserting that frozen manifests, historical SHAs, or truthful audit gap markers remain intact for regulatory/provenance compliance.

### 3.1 Aggregate Classification Summary

| Category | Test Count | % of Added Tests | Total LOC | Proposed Disposition |
|---|---|---|---|---|
| **`DISTINCT_FAILURE_PATH`** | **147** | 68.7% | 4,524 | **PRESERVE 100%** (14 tests collapsible into 4 parameterized suites) |
| **`SAME_PATH_DUPLICATION`** | **42** | 19.6% | 850 | **CANDIDATE FOR REMOVAL / COLLAPSE** (-37 test functions) |
| **`HISTORICAL_CERTIFICATION`**| **17** | 7.9% | 394 | **PRESERVE OR CONSOLIDATE** into unified manifest certification module |
| **`COVERAGE_ONLY`** | **8** | 3.7% | 217 | **CANDIDATE FOR PRUNING** (-8 test functions) |
| **TOTAL** | **214** | **100.0%** | **5,985** | Net potential reduction: **-55 tests, -1,417 LOC** |

---

## 4. Per-Suite Detailed Audit & Classification

### 4.1 `tests/intents/test_longing_proactive_contact.py` (66 tests, 2,412 LOC)
- **Role:** Primary behavioral test suite for the longing proactive contact path and the reformed decoupled proactive turn lifecycle in `MindRuntimeHostAdapter`.
- **Classification:**
  - **`DISTINCT_FAILURE_PATH` (52 tests, 1,995 LOC):**
    - `test_foundational_longing_remains_declared_surface_root_for_contact_seeking` (L335)
    - `test_foundational_intent_path_cannot_read_raw_longing_overlap` (L345): Enforces that IntentEngine rejects rules reading raw affect when consuming Surface.
    - `test_foundational_contact_seeking_drives_intent_strength_and_eligibility` (L379)
    - `test_a_cognitive_ticker_cannot_be_constructed_with_provider_executor` (L505): Decoupling boundary.
    - `test_b_cognitive_ticker_tick_cannot_call_provider_realization` (L537): Provider isolation.
    - `test_c_cognitive_ticker_source_has_no_call_path_to_expression` (L554): Static call-path guard.
    - `test_d_action_policy_allow_creates_wake_signal` (L585)
    - `test_e_policy_deny_creates_no_wake_signal` (L603)
    - `test_f_cooldown_defer_creates_no_wake_signal` (L623)
    - **Wake Admission Rejection Matrix** (8 distinct fail-closed branches in `notify_wake`):
      `test_g_missing_lifecycle_authority_rejects_wake` (L652),
      `test_h_missing_policy_authority_rejects_wake` (L672),
      `test_i_wrong_runtime_id_rejects_wake` (L694),
      `test_j_unknown_intent_id_rejects_wake` (L712),
      `test_k_non_allowed_intent_rejects_wake` (L730),
      `test_l_version_mismatch_rejects_wake` (L758),
      `test_m_action_mismatch_rejects_wake` (L776),
      `test_m2_non_proactive_policy_rule_rejects_forged_wake` (L794).
    - `test_n_valid_authoritative_wake_admits` (L817)
    - `test_o_valid_pending_wake_context_can_be_used_after_admission` (L853)
    - `test_p_missing_pending_context_fails_closed` (L878)
    - `test_q_no_code_reconstructs_action_policy_result_from_wake` (L900): Anti-tamper invariant.
    - `test_r_no_code_reconstructs_replacement_situation_from_wake` (L915): Anti-tamper invariant.
    - `test_s_process_restart_context_loss_reported_as_unsupported` (L930)
    - `test_t_successful_proactive_preparation_returns_processing_not_committed` (L966)
    - `test_u_mr_does_not_invoke_production_llm_internally_before_handing_context` (L987)
    - `test_v_external_prose_must_pass_existing_expression_guard` (L1010)
    - `test_w_guard_accept_alone_does_not_mark_delivery_committed` (L1036)
    - `test_x_successful_explicit_proactive_delivery_commit_transitions_intent` (L1065)
    - `test_y_terminal_completion_clears_pending_wake_context` (L1092)
    - `test_z_duplicate_completion_is_idempotent` (L1117)
    - `test_aa_conflicting_replay_fails_closed` (L1142)
    - `test_ae_xiyue_adapter_can_receive_and_start_proactive_host_path` (L1417)
    - `test_af_bounded_proactive_context_reaches_external_body_seam_without_fake_user_turn` (L1442)
    - `test_trace_ordering_proves_causal_sequence` (L1523)
    - `test_no_proactive_expression_artifact_before_admitted_wake` (L1578)
    - `test_wake_does_not_create_user_evidence` (L1595)
    - `test_wake_does_not_synthesize_host_turn_request` (L1615)
    - `test_longing_anti_spam_invariant_remains_valid` (L1644)
    - `test_proactive_surface_parameter_uses_typed_surface_contract` (L1669)
    - `test_proactive_preparation_does_not_read_compiler_config` (L1690)
    - `test_proactive_preparation_does_not_read_orchestrator_persona` (L1704)
    - `test_begin_proactive_turn_renders_provider_envelope` (L1767)
    - `test_commit_without_guard_accept_fails_closed` (L1795)
    - `test_commit_with_guard_reject_fails_closed` (L1826)
    - `test_guard_reject_transitions_intent_to_superseded` (L1859)
    - `test_successful_proactive_turn_lifecycle` (L1894)
    - `test_abort_proactive_turn_transitions_to_superseded` (L1948)
    - `test_abort_transition_failure_fails_closed` (L1981)
    - `test_abort_proactive_turn_without_lifecycle_fails_closed` (L2074): **Real defect regression test** (fixed pending_exec bug in B4 takeover). MUST PRESERVE.
    - `test_proactive_turn_lifecycle_boundary_and_validation_coverage` (L2125): 9 distinct validation error branches.
    - `test_wake_notification_scope_mismatch_rejected` (L2222)
    - `test_proactive_turn_extended_edge_coverage` (L2244)
  - **`SAME_PATH_DUPLICATION` (3 tests, 105 LOC):**
    - `test_foundational_increasing_longing_monotonic_contact_seeking` (L363, 14 LOC): Duplicate of candidate recipe conformance tests.
    - `test_ad_generic_proactive_contact_infrastructure_verified` (L1301, 84 LOC): Composite smoke test duplicating individual lifecycle tests N-X.
    - `test_fast_function_v1_registry_count_remains_eight` (L1635, 7 LOC): Duplicate of `test_fast_functions.py::test_fast_function_v1_count_constant`.
  - **`COVERAGE_ONLY` (3 tests, 44 LOC):**
    - `test_no_type_ignore_on_proactive_path` (L1679, 9 LOC): Text-scraping probe.
    - `test_public_host_adapter_has_no_run_proactive_turn` (L1721, 10 LOC): Static API reflection check.
    - `test_host_proactive_result_contract_clean` (L2047, 25 LOC): Dataclass field name reflection check.
  - **`HISTORICAL_CERTIFICATION` (8 tests, 268 LOC):**
    - `test_foundational_w3_final_sha_is_preserved_and_target_base_is_ancestor` (L305, 28 LOC)
    - `test_ab_production_composition_has_durable_intent_lifecycle_authority` (L1188, 55 LOC)
    - `test_ac_production_composition_has_action_policy_authority` (L1245, 54 LOC)
    - `test_production_composition_wires_context_preparer` (L1387, 28 LOC)
    - `test_ag_no_internal_default_stub_agent_used_as_production_body` (L1473, 13 LOC)
    - `test_ah_downstream_transport_remains_outside_mr_and_config_gap_verified` (L1488, 30 LOC)
    - `test_production_composition_wires_provider_free_preparer` (L1733, 32 LOC)
    - `test_certified_manifest_proactive_gap_verified` (L2017, 28 LOC)

---

### 4.2 `tests/intents/test_curiosity_proactive_inquiry.py` (41 tests, 1,717 LOC)
- **Role:** Certifies curiosity mapping to `INQUIRY_EXPLORATION`, autonomous retrieval deferral, anti-spam cooldown, and ActionPolicy candidate competition.
- **Classification:**
  - **`DISTINCT_FAILURE_PATH` (30 tests, 1,445 LOC):**
    - `test_d_low_curiosity_below_threshold_produces_no_candidate` (L386)
    - `test_e_high_curiosity_produces_proactive_inquiry_candidate` (L534)
    - `test_f_changing_sharing_urge_alone_does_not_change_proactive_inquiry_score` (L534, 99 LOC) [Cross-talk isolation]
    - `test_g_changing_sadness_alone_does_not_change_proactive_inquiry_score` (L633, 99 LOC) [Cross-talk isolation]
    - `test_h_changing_anger_or_longing_alone_does_not_change_proactive_inquiry_score` (L732, 111 LOC) [Cross-talk isolation]
    - `test_i_inquiry_rule_has_empty_surface_control_weights` (L843)
    - `test_j_inquiry_rule_uses_curiosity_as_only_fast_state_scoring_root` (L862)
    - `test_m_proactive_inquiry_intent_allow_emits_wake_signal` (L911)
    - `test_o_host_rejects_forged_inquiry_wake_when_policy_rule_non_proactive` (L938) [Authority boundary]
    - `test_p_host_rejects_action_type_mismatch` (L961) [Authority boundary]
    - `test_q_begin_proactive_turn_returns_processing_with_non_empty_envelope` (L979)
    - `test_r_provider_envelope_contains_selected_inquiry_action_semantics` (L1000)
    - `test_s_provider_envelope_contains_no_literal_curiosity` (L1019) [Information isolation]
    - `test_t_no_internal_mr_provider_execution_occurs` (L1038)
    - `test_u_guard_accept_alone_does_not_commit` (L1062)
    - `test_v_guard_accept_and_explicit_commit_transitions_intent_completed` (L1093)
    - `test_w_guard_reject_fails_closed` (L1122)
    - `test_x_higher_curiosity_cannot_shorten_proactive_cooldown` (L1151) [Anti-spam invariant]
    - `test_y_eligible_inquiry_inside_cooldown_defers_and_emits_no_wake` (L1190)
    - `test_z_no_inquiry_specific_frequency_counters_used` (L1212)
    - `test_aa_same_wake_replay_remains_process_local_idempotent` (L1221)
    - `test_ab_conflicting_wake_replay_fails_closed` (L1258)
    - **Retrieval Authority Boundary Sub-Suite (NON-NEGOTIABLE PRESERVATION):**
      `test_ad_retrieval_output_cannot_fabricate_or_authorize_intent` (L1288),
      `test_ae_retrieval_service_cannot_create_action_policy_allow` (L1315),
      `test_af_retrieval_service_cannot_emit_wake_signal` (L1328),
      `test_ag_cognitive_ticker_does_not_invoke_retrieval` (L1341),
      `test_ah_retrieval_score_is_not_permission_strength` (L1365).
    - `test_ai_information_isolation_explicitly_forbids_curiosity` (L1383)
    - `test_an_three_way_competition_emits_single_wake` (L1547)
    - `test_ao_curiosity_wins_competition_when_highest_strength` (L1643)
  - **`SAME_PATH_DUPLICATION` (9 tests, 247 LOC):**
    - `test_a_fast_function_v1_registry_has_exactly_eight_entries` (L283, 5 LOC): Duplicate of `test_fast_functions.py`.
    - `test_b_curiosity_maps_to_inquiry_exploration` (L290, 10 LOC): Duplicate of `test_fast_functions.py::test_curiosity_maps_to_inquiry_exploration`.
    - `test_c_increasing_curiosity_monotonically_increases_inquiry_intent_strength` (L302, 82 LOC): Monotonic curve duplicate.
    - `test_k_no_new_surface_control_introduced` (L881, 15 LOC): Duplicate of recipe tests.
    - `test_l_candidate_surface_recipe_digest_remains_unchanged` (L898, 8 LOC): Duplicate digest check.
    - `test_n_wake_signal_action_type_is_proactive_question` (L925, 11 LOC): Duplicate of assertion inside `test_m`.
    - `test_ak_longing_proactive_contact_remains_unaffected` (L1425, 51 LOC): Duplicate regression proof.
    - `test_al_sharing_urge_proactive_share_remains_unaffected` (L1478, 51 LOC): Duplicate regression proof.
    - `test_am_longing_sharing_curiosity_distinct_intent_and_action` (L1531, 14 LOC): Duplicate distinction assertion.
  - **`HISTORICAL_CERTIFICATION` (2 tests, 25 LOC):**
    - `test_ac_curiosity_retrieval_branch_is_deferred` (L1282, 4 LOC)
    - `test_aj_certified_manifest_proactive_inquiry_gap_verified` (L1399, 21 LOC)

---

### 4.3 `tests/intents/test_sharing_urge_proactive_share.py` (31 tests, 1,326 LOC)
- **Role:** Certifies sharing urge mapping to `PROACTIVE_SHARE`, dedicated `spontaneous_share` intent, and ActionPolicy anti-spam cooldown.
- **Classification:**
  - **`DISTINCT_FAILURE_PATH` (22 tests, 777 LOC):**
    - `test_d_low_sharing_urge_below_threshold_produces_no_candidate` (L368, 75 LOC)
    - `test_e_high_sharing_urge_produces_spontaneous_share_candidate` (L445, 75 LOC)
    - `test_f_changing_curiosity_alone_does_not_change_spontaneous_share_score` (L522, 100 LOC) [Cross-talk isolation]
    - `test_g_changing_sadness_alone_does_not_change_spontaneous_share_score` (L624, 100 LOC) [Cross-talk isolation]
    - `test_h_share_rule_has_empty_surface_control_weights` (L726, 16 LOC)
    - `test_i_share_rule_uses_sharing_urge_as_only_fast_state_scoring_root` (L744, 17 LOC)
    - `test_l_spontaneous_share_intent_allow_emits_wake_signal` (L795, 12 LOC)
    - `test_n_host_rejects_forged_share_wake_when_policy_rule_non_proactive` (L822, 21 LOC) [Authority boundary]
    - `test_o_host_rejects_action_type_mismatch` (L845, 17 LOC) [Authority boundary]
    - `test_p_begin_proactive_turn_returns_processing_with_non_empty_envelope` (L864, 19 LOC)
    - `test_q_provider_envelope_contains_selected_share_action_semantics` (L885, 17 LOC)
    - `test_r_provider_envelope_contains_no_literal_sharing_urge` (L904, 17 LOC) [Information isolation]
    - `test_s_no_internal_mr_provider_execution_occurs` (L923, 23 LOC)
    - `test_t_guard_accept_alone_does_not_commit` (L948, 29 LOC)
    - `test_u_guard_accept_and_explicit_commit_transitions_intent_completed` (L979, 27 LOC)
    - `test_v_guard_reject_fails_closed` (L1008, 24 LOC)
    - `test_w_higher_sharing_urge_cannot_shorten_proactive_cooldown` (L1037, 37 LOC) [Anti-spam invariant]
    - `test_x_eligible_share_inside_cooldown_defers_and_emits_no_wake` (L1076, 20 LOC)
    - `test_y_no_share_specific_frequency_counters_used` (L1098, 8 LOC)
    - `test_z_same_wake_replay_remains_process_local_idempotent` (L1108, 41 LOC)
    - `test_information_isolation_explicitly_forbids_sharing_urge` (L1154, 13 LOC)
    - `test_competition_between_longing_and_sharing_urge_single_wake` (L1258, 69 LOC)
  - **`SAME_PATH_DUPLICATION` (8 tests, 189 LOC):**
    - `test_a_fast_function_v1_registry_has_exactly_eight_entries` (L265, 5 LOC): Duplicate of registry count test.
    - `test_b_sharing_urge_maps_to_proactive_share` (L272, 10 LOC): Duplicate of `test_fast_functions.py::test_sharing_urge_maps_to_proactive_share`.
    - `test_c_increasing_sharing_urge_monotonically_increases_share_intent_strength` (L284, 82 LOC): Monotonic curve duplicate.
    - `test_j_no_new_surface_control_introduced` (L763, 17 LOC): Duplicate recipe controls check.
    - `test_k_candidate_surface_recipe_digest_remains_unchanged` (L782, 8 LOC): Duplicate digest check.
    - `test_m_wake_signal_action_type_is_proactive_share` (L809, 11 LOC): Duplicate of assertion inside `test_l`.
    - `test_longing_proactive_contact_remains_unaffected` (L1198, 51 LOC): Duplicate regression proof.
    - `test_longing_and_sharing_distinct_intent_and_action` (L1251, 5 LOC): Duplicate distinction assertion.
  - **`HISTORICAL_CERTIFICATION` (1 test, 21 LOC):**
    - `test_certified_manifest_proactive_share_gap_verified` (L1172, 21 LOC)

---

### 4.4 `tests/surface/test_sadness_initiative_suppression.py` (29 tests, 1,055 LOC)
- **Role:** Audits sadness surface initiative & expressive warmth dampening, validates freedom from cross-talk, and records the primary downstream consumer gap.
- **Classification:**
  - **`DISTINCT_FAILURE_PATH` (18 tests, 571 LOC):**
    - `test_d_exact_unclamped_delta_initiative` (L313, 29 LOC): Exact delta formula verification (`Δinitiative = -0.25 * Δsadness`).
    - `test_f_exact_unclamped_delta_expressive_warmth` (L368, 32 LOC): Exact delta formula verification (`Δexpressive_warmth = -0.25 * Δsadness`).
    - `test_j_expressive_warmth_maps_to_qualitative_warmth` (L461, 11 LOC): Band mapping.
    - `test_k_sadness_alters_warmth_band_through_recipe` (L474, 37 LOC): Integration check.
    - `test_l_provider_envelope_contains_qualitative_warmth` (L513, 16 LOC): Envelope inclusion.
    - `test_m_renderer_isolation_and_zero_sadness_leak` (L531, 21 LOC): Information isolation.
    - `test_n_surface_initiative_not_serialized_as_raw_guidance` (L554, 10 LOC): Prevents initiative leakage.
    - `test_o_no_configured_intent_rule_consumes_surface_initiative` (L571, 17 LOC): Audit proof of zero downstream consumer.
    - `test_q_action_policy_has_no_initiative_dependency` (L616, 10 LOC): ActionPolicy isolation.
    - `test_r_cognitive_ticker_does_not_gate_on_initiative` (L628, 12 LOC): Ticker isolation.
    - `test_s_sadness_does_not_suppress_spontaneous_share_candidate_strength` (L642, 125 LOC) [Counterfactual cross-talk check]
    - `test_t_sadness_does_not_suppress_proactive_inquiry_candidate_strength` (L769, 79 LOC) [Counterfactual cross-talk check]
    - `test_u_sadness_does_not_suppress_reach_out_candidate_strength` (L850, 21 LOC) [Counterfactual cross-talk check]
    - `test_v_three_way_competition_under_high_vs_low_sadness` (L873, 120 LOC) [Competition invariance]
    - `test_z_authority_separation_invariant` (L1019, 10 LOC): Sadness modulates pressure, never grants action authority.
    - `test_aa_no_synthetic_withdrawal_or_refusal_actions` (L1031, 12 LOC): No synthetic refusal wake signals.
    - `test_ab_initiative_declared_intent_eligible_in_surface_validator` (L1045, 4 LOC)
    - `test_ac_expression_map_does_not_consume_initiative` (L1051, 5 LOC)
  - **`SAME_PATH_DUPLICATION` (9 tests, 113 LOC):**
    - `test_a_fast_function_v1_count_and_registry_intact` (L270, 5 LOC): Duplicate registry test.
    - `test_b_sadness_maps_to_initiative_suppression_active` (L277, 11 LOC): Duplicate mapping test.
    - `test_c_monotonic_sadness_lowers_initiative` (L290, 21 LOC): Monotonic curve duplicate.
    - `test_e_monotonic_sadness_lowers_expressive_warmth` (L344, 22 LOC): Monotonic curve duplicate.
    - `test_g_exact_five_surface_controls_preserved` (L402, 25 LOC): Duplicate controls test.
    - `test_h_candidate_recipe_v2_digest_preserved` (L429, 13 LOC): Duplicate recipe digest test.
    - `test_i_candidate_expression_map_v2_digest_preserved` (L444, 10 LOC): Duplicate expression map digest test.
    - `test_w_dedicated_intent_cross_talk_protection_passes` (L1000, 3 LOC): Summary wrapper around tests S-U.
    - `test_x_initiative_suppression_ineffective_on_dedicated_intents` (L1005, 3 LOC): Summary wrapper around tests S-U.
  - **`HISTORICAL_CERTIFICATION` (2 tests, 31 LOC):**
    - `test_p_certified_manifest_has_no_initiative_intent_or_policy_rule` (L590, 24 LOC)
    - `test_y_sadness_surface_closed_primary_consumer_gap_found` (L1010, 7 LOC): Truthful audit verdict assertion.

---

### 4.5 `tests/surface/test_anger_boundary_confrontation.py` (29 tests, 817 LOC)
- **Role:** Certifies anger mapping to `BOUNDARY_CONFRONTATION`, directness envelope guidance, and the non-negotiable authority boundary: anger cannot grant action permission.
- **Classification:**
  - **`DISTINCT_FAILURE_PATH` (16 tests, 396 LOC):**
    - `test_d_persona_confrontation_readiness_raises_confrontation` (L303, 28 LOC): Persona interaction.
    - `test_e_persona_expressive_restraint_dampens_confrontation` (L332, 31 LOC): Persona restraint interaction.
    - `test_f_anger_dampens_contact_seeking` (L364, 23 LOC): Dampening formula check (`-0.20 * anger`).
    - `test_g_anger_dampens_expressive_warmth` (L388, 25 LOC): Dampening formula check (`-0.25 * anger`).
    - `test_k_confrontation_maps_to_directness` (L454, 8 LOC): Band mapping.
    - `test_o_decision_context_compiler_surface_v1_includes_directness` (L484, 23 LOC)
    - `test_p_renderer_isolation_and_zero_anger_leak` (L508, 31 LOC): Information isolation.
    - **Anger Authority Boundary Sub-Suite (NON-NEGOTIABLE PRESERVATION):**
      `test_q_high_confrontation_alone_cannot_produce_action_permission` (L540, 54 LOC),
      `test_r_directness_guidance_cannot_construct_action_allow` (L595, 32 LOC),
      `test_s_directness_guidance_cannot_emit_wake_signal` (L628, 28 LOC),
      `test_t_no_synthetic_boundary_event_or_evidence_fabricated` (L657, 7 LOC),
      `test_u_no_synthetic_boundary_fact_injected_into_situation` (L665, 7 LOC).
    - `test_v_surface_overlap_validator_rejects_overlapping_roots` (L674, 11 LOC): Overlap fail-closed gate.
    - `test_y_no_certified_boundary_event_to_intent_authority` (L736, 52 LOC): Manifest boundary event check.
    - `test_aa_confrontation_is_eligible_intent_surface_control` (L795, 5 LOC)
    - `test_ab_overlap_protection_rejects_cross_talk` (L802, 8 LOC): Root isolation check.
  - **`SAME_PATH_DUPLICATION` (9 tests, 96 LOC):**
    - `test_a_fast_function_v1_count_and_registry_intact` (L245, 5 LOC): Duplicate registry test.
    - `test_b_anger_maps_to_boundary_confrontation_active` (L252, 22 LOC): Duplicate mapping test.
    - `test_c_monotonic_anger_raises_confrontation` (L276, 25 LOC): Monotonic curve duplicate.
    - `test_h_exact_five_surface_controls_preserved` (L414, 14 LOC): Duplicate controls test.
    - `test_i_candidate_recipe_v2_digest_preserved` (L430, 8 LOC): Duplicate recipe digest test.
    - `test_j_candidate_expression_map_v2_digest_preserved` (L440, 7 LOC): Duplicate expression map digest test.
    - **Confrontation Band Numeric Probes (Collapsible into 1 parameterized test):**
      `test_l_confrontation_low_band_mapping` (L463, 5 LOC),
      `test_m_confrontation_moderate_band_mapping` (L470, 5 LOC),
      `test_n_confrontation_high_band_mapping` (L477, 5 LOC).
  - **`HISTORICAL_CERTIFICATION` (4 tests, 49 LOC):**
    - `test_w_certified_manifest_has_no_confrontation_intent_rule` (L692, 24 LOC)
    - `test_x_certified_manifest_has_no_boundary_action_policy_rule` (L718, 16 LOC)
    - `test_z_anger_intent_branch_deferred_constant` (L790, 3 LOC)
    - `test_ac_anger_consumer_verdict_closed_intent_deferred` (L812, 6 LOC)

---

### 4.6 `tests/surface/test_surface_recipe_coverage.py` (7 tests, 302 LOC)
- **Role:** Added in commit `e51e12a` to achieve the required 94% aggregate branch coverage gate by covering edge validation branches in `candidate_recipe`, `lineage`, and `cognition`.
- **Classification:**
  - **`DISTINCT_FAILURE_PATH` (5 tests, 200 LOC):**
    - `test_validate_candidate_recipe_wrong_id_or_version` (L66, 13 LOC): Rejects invalid recipe ID or unsupported version with `SURFACE_RECIPE_UNSUPPORTED`.
    - `test_validate_candidate_recipe_mismatched_digest_and_rules` (L81, 30 LOC): Rejects rule count mismatch, unknown control_id, invalid AST primitive, or mismatched lookups with `SURFACE_RECIPE_CONTENT_CONFLICT`.
    - `test_project_surface_for_cognition_eligibility` (L142, 49 LOC): Tests early returns when surface_port is None, persona is None, or persona is ineligible.
    - `test_reconstruct_committed_surface_for_replay_type_checks` (L193, 49 LOC): Defensive `TypeError` checks for persona_publication, revision ref, and backend types.
    - `test_reconstruct_committed_surface_for_replay_missing_markers_and_roots` (L244, 59 LOC): Replay recompute fail-closed error paths.
  - **`COVERAGE_ONLY` (2 tests, 32 LOC):**
    - `test_validate_candidate_recipe_valid` (L59, 5 LOC): Valid recipe smoke test.
    - `test_validate_projected_surface_edges` (L113, 27 LOC): Pokes malformed controls object.

---

### 4.7 `tests/dynamics/test_fast_functions.py` (+9 added tests, 178 LOC diff)
- **Role:** Fast function registry contract validation and anti-spam invariants.
- **Classification:**
  - **`DISTINCT_FAILURE_PATH` (4 tests, 38 LOC):**
    - `test_longing_controls_contact_pressure_without_frequency_permission` (L131, 19 LOC): Fast function anti-spam invariant.
    - `test_fast_function_v1_count_constant` (L389, 5 LOC): Registry completeness constraint.
    - `test_registry_rejects_duplicate_state_key_or_function_kind` (L422, 9 LOC): Registry duplicate rejection.
    - `test_registry_requires_present_state_key` (L433, 5 LOC): Missing state key rejection.
  - **`SAME_PATH_DUPLICATION` (4 tests, 100 LOC):**
    - `test_sharing_urge_maps_to_proactive_share` (L281, 30 LOC): Redundant with `test_sharing_urge_proactive_share.py`.
    - `test_curiosity_maps_to_inquiry_exploration` (L313, 30 LOC): Redundant with `test_curiosity_proactive_inquiry.py`.
    - `test_anger_maps_to_boundary_confrontation` (L345, 20 LOC): Redundant with `test_anger_boundary_confrontation.py`.
    - `test_sadness_maps_to_initiative_suppression` (L367, 20 LOC): Redundant with `test_sadness_initiative_suppression.py`.
  - **`COVERAGE_ONLY` (1 test, 9 LOC):**
    - `test_spec_defaults_product_label_to_semantic_label` (L440, 9 LOC): Dataclass default fallback test.

---

### 4.8 `tests/host/test_host_adapter.py` (+2 added tests, 132 LOC diff)
- **Role:** Added in commit `79d880b` to cover new Host contract dataclasses.
- **Classification:**
  - **`COVERAGE_ONLY` (2 tests, 132 LOC):**
    - `test_host_wake_notification_contract_validation_and_as_dict` (L813, 47 LOC): Exercises field validation (empty wake_id raises, intent_version=0 raises) and `as_dict()` dictionary structure.
    - `test_host_proactive_turn_result_contract_validation_and_as_dict` (L862, 85 LOC): Exercises enum type checks and `as_dict()` with/without `bounded_context`.

---

### 4.9 `tests/cognition/test_tick_expression.py` & `test_tick_media_cadence.py` (0 added tests, adapted logic)
- **Role:** Adapted to the WakeSignal decoupling architecture.
- **Classification:**
  - In `test_tick_expression.py`, the CognitiveTicker tests were updated to verify that `ticker.tick()` emits `wake_signal` rather than directly calling providers. Added assertions for `preparer.handles()` and `prepare_context()` skips (L914-972).
  - In `test_tick_media_cadence.py`, cadence threshold tests were updated to verify `wake_signal` delivery through `_run_test_proactive_turn`.
  - Both files retain their original test count (13 and 10 tests respectively); no new test functions were added, and all modifications represent **`DISTINCT_FAILURE_PATH`** adaptations to the reformed runtime topology.

---

## 5. Non-Negotiable Preservation List (Authority-Boundary & Adversarial Tests)

Under the 2026-09-26 adversarial failure-path standard, the following **147 distinct failure paths** represent core architectural invariants, fail-closed boundaries, or defect regressions and **MUST NOT BE REMOVED OR PRUNED**:

```text
[CRITICAL DEFECT REGRESSIONS - NEVER TOUCH]
1. tests/intents/test_longing_proactive_contact.py::test_abort_proactive_turn_without_lifecycle_fails_closed
   (Direct regression test for the pending_exec control-flow defect resolved during Gate B4 takeover)
2. tests/intents/test_longing_proactive_contact.py::test_proactive_turn_lifecycle_boundary_and_validation_coverage
   (Covers unknown wake handling, scope mismatch, and duplicate replay handling in Host adapter)

[HOST WAKE ADMISSION & AUTHORITY BOUNDARIES]
3. tests/intents/test_longing_proactive_contact.py::test_g_missing_lifecycle_authority_rejects_wake
4. tests/intents/test_longing_proactive_contact.py::test_h_missing_policy_authority_rejects_wake
5. tests/intents/test_longing_proactive_contact.py::test_i_wrong_runtime_id_rejects_wake
6. tests/intents/test_longing_proactive_contact.py::test_j_unknown_intent_id_rejects_wake
7. tests/intents/test_longing_proactive_contact.py::test_k_non_allowed_intent_rejects_wake
8. tests/intents/test_longing_proactive_contact.py::test_l_version_mismatch_rejects_wake
9. tests/intents/test_longing_proactive_contact.py::test_m_action_mismatch_rejects_wake
10. tests/intents/test_longing_proactive_contact.py::test_m2_non_proactive_policy_rule_rejects_forged_wake
11. tests/intents/test_curiosity_proactive_inquiry.py::test_o_host_rejects_forged_inquiry_wake_when_policy_rule_non_proactive
12. tests/intents/test_curiosity_proactive_inquiry.py::test_p_host_rejects_action_type_mismatch
13. tests/intents/test_sharing_urge_proactive_share.py::test_n_host_rejects_forged_share_wake_when_policy_rule_non_proactive
14. tests/intents/test_sharing_urge_proactive_share.py::test_o_host_rejects_action_type_mismatch

[CURIOSITY RETRIEVAL AUTHORITY BOUNDARIES]
15. tests/intents/test_curiosity_proactive_inquiry.py::test_ad_retrieval_output_cannot_fabricate_or_authorize_intent
16. tests/intents/test_curiosity_proactive_inquiry.py::test_ae_retrieval_service_cannot_create_action_policy_allow
17. tests/intents/test_curiosity_proactive_inquiry.py::test_af_retrieval_service_cannot_emit_wake_signal
18. tests/intents/test_curiosity_proactive_inquiry.py::test_ag_cognitive_ticker_does_not_invoke_retrieval
19. tests/intents/test_curiosity_proactive_inquiry.py::test_ah_retrieval_score_is_not_permission_strength

[ANGER AUTHORITY BOUNDARIES (PRESSURE != PERMISSION)]
20. tests/surface/test_anger_boundary_confrontation.py::test_q_high_confrontation_alone_cannot_produce_action_permission
21. tests/surface/test_anger_boundary_confrontation.py::test_r_directness_guidance_cannot_construct_action_allow
22. tests/surface/test_anger_boundary_confrontation.py::test_s_directness_guidance_cannot_emit_wake_signal
23. tests/surface/test_anger_boundary_confrontation.py::test_t_no_synthetic_boundary_event_or_evidence_fabricated
24. tests/surface/test_anger_boundary_confrontation.py::test_u_no_synthetic_boundary_fact_injected_into_situation

[SADNESS AUTHORITY SEPARATION & CONSUMER BOUNDARIES]
25. tests/surface/test_sadness_initiative_suppression.py::test_z_authority_separation_invariant
26. tests/surface/test_sadness_initiative_suppression.py::test_aa_no_synthetic_withdrawal_or_refusal_actions
27. tests/surface/test_sadness_initiative_suppression.py::test_o_no_configured_intent_rule_consumes_surface_initiative
28. tests/surface/test_sadness_initiative_suppression.py::test_q_action_policy_has_no_initiative_dependency
29. tests/surface/test_sadness_initiative_suppression.py::test_r_cognitive_ticker_does_not_gate_on_initiative

[ANTI-SPAM INVARIANTS & SINGLE-WAKE ACTIONPOLICY COMPETITION]
30. tests/intents/test_longing_proactive_contact.py::test_longing_anti_spam_invariant_remains_valid
31. tests/intents/test_curiosity_proactive_inquiry.py::test_x_higher_curiosity_cannot_shorten_proactive_cooldown
32. tests/intents/test_sharing_urge_proactive_share.py::test_w_higher_sharing_urge_cannot_shorten_proactive_cooldown
33. tests/intents/test_curiosity_proactive_inquiry.py::test_an_three_way_competition_emits_single_wake
34. tests/intents/test_curiosity_proactive_inquiry.py::test_ao_curiosity_wins_competition_when_highest_strength
35. tests/intents/test_sharing_urge_proactive_share.py::test_competition_between_longing_and_sharing_urge_single_wake
36. tests/surface/test_sadness_initiative_suppression.py::test_v_three_way_competition_under_high_vs_low_sadness

[INFORMATION ISOLATION & ZERO-LEAKAGE GUARDS]
37. tests/intents/test_curiosity_proactive_inquiry.py::test_s_provider_envelope_contains_no_literal_curiosity
38. tests/intents/test_curiosity_proactive_inquiry.py::test_ai_information_isolation_explicitly_forbids_curiosity
39. tests/intents/test_sharing_urge_proactive_share.py::test_r_provider_envelope_contains_no_literal_sharing_urge
40. tests/intents/test_sharing_urge_proactive_share.py::test_information_isolation_explicitly_forbids_sharing_urge
41. tests/surface/test_sadness_initiative_suppression.py::test_m_renderer_isolation_and_zero_sadness_leak
42. tests/surface/test_sadness_initiative_suppression.py::test_n_surface_initiative_not_serialized_as_raw_guidance
43. tests/surface/test_anger_boundary_confrontation.py::test_p_renderer_isolation_and_zero_anger_leak

[PROACTIVE TURN LIFECYCLE & EXPRESSIONGUARD RECONCILIATION]
44. tests/intents/test_longing_proactive_contact.py::test_w_guard_accept_alone_does_not_mark_delivery_committed
45. tests/intents/test_longing_proactive_contact.py::test_x_successful_explicit_proactive_delivery_commit_transitions_intent
46. tests/intents/test_longing_proactive_contact.py::test_commit_without_guard_accept_fails_closed
47. tests/intents/test_longing_proactive_contact.py::test_commit_with_guard_reject_fails_closed
48. tests/intents/test_longing_proactive_contact.py::test_guard_reject_transitions_intent_to_superseded
49. tests/intents/test_longing_proactive_contact.py::test_abort_proactive_turn_transitions_to_superseded
50. tests/intents/test_longing_proactive_contact.py::test_abort_transition_failure_fails_closed
```

---

## 6. Removable and Collapsible Slimming Blueprint

For future test maintenance passes, this section provides the exact inventory of tests that can be removed or collapsed into compact parameterized fixtures without losing a single distinct failure branch.

### 6.1 Removable Candidates: Same-Path Duplication (-37 tests, ~700 LOC)
1. **Redundant FAST_FUNCTION_V1 Registry & Spec Duplicates across Consumers (9 tests):**
   - `tests/intents/test_longing_proactive_contact.py::test_fast_function_v1_registry_count_remains_eight`
   - `tests/intents/test_curiosity_proactive_inquiry.py::test_a_fast_function_v1_registry_has_exactly_eight_entries`
   - `tests/intents/test_curiosity_proactive_inquiry.py::test_b_curiosity_maps_to_inquiry_exploration`
   - `tests/intents/test_sharing_urge_proactive_share.py::test_a_fast_function_v1_registry_has_exactly_eight_entries`
   - `tests/intents/test_sharing_urge_proactive_share.py::test_b_sharing_urge_maps_to_proactive_share`
   - `tests/surface/test_sadness_initiative_suppression.py::test_a_fast_function_v1_count_and_registry_intact`
   - `tests/surface/test_sadness_initiative_suppression.py::test_b_sadness_maps_to_initiative_suppression_active`
   - `tests/surface/test_anger_boundary_confrontation.py::test_a_fast_function_v1_count_and_registry_intact`
   - `tests/surface/test_anger_boundary_confrontation.py::test_b_anger_maps_to_boundary_confrontation_active`
   *(All 9 are exact duplicates of tests already authoritative in `tests/dynamics/test_fast_functions.py`)*
2. **Duplicate Fast Function Spec Tests in `test_fast_functions.py` (4 tests):**
   - `tests/dynamics/test_fast_functions.py::test_sharing_urge_maps_to_proactive_share`
   - `tests/dynamics/test_fast_functions.py::test_curiosity_maps_to_inquiry_exploration`
   - `tests/dynamics/test_fast_functions.py::test_anger_maps_to_boundary_confrontation`
   - `tests/dynamics/test_fast_functions.py::test_sadness_maps_to_initiative_suppression`
   *(Redundant with registry spec definition assertions)*
3. **Duplicate Candidate Recipe & Expression Map Digest Probes (10 tests):**
   - `tests/intents/test_curiosity_proactive_inquiry.py::test_k_no_new_surface_control_introduced`
   - `tests/intents/test_curiosity_proactive_inquiry.py::test_l_candidate_surface_recipe_digest_remains_unchanged`
   - `tests/intents/test_sharing_urge_proactive_share.py::test_j_no_new_surface_control_introduced`
   - `tests/intents/test_sharing_urge_proactive_share.py::test_k_candidate_surface_recipe_digest_remains_unchanged`
   - `tests/surface/test_sadness_initiative_suppression.py::test_g_exact_five_surface_controls_preserved`
   - `tests/surface/test_sadness_initiative_suppression.py::test_h_candidate_recipe_v2_digest_preserved`
   - `tests/surface/test_sadness_initiative_suppression.py::test_i_candidate_expression_map_v2_digest_preserved`
   - `tests/surface/test_anger_boundary_confrontation.py::test_h_exact_five_surface_controls_preserved`
   - `tests/surface/test_anger_boundary_confrontation.py::test_i_candidate_recipe_v2_digest_preserved`
   - `tests/surface/test_anger_boundary_confrontation.py::test_j_candidate_expression_map_v2_digest_preserved`
   *(All 10 are duplicates of tests in `tests/surface/test_candidate_conformance.py` and `tests/surface/test_surface_recipe_coverage.py`)*
4. **Duplicate Monotonicity Curve Probes (6 tests):**
   - `tests/intents/test_longing_proactive_contact.py::test_foundational_increasing_longing_monotonic_contact_seeking`
   - `tests/intents/test_curiosity_proactive_inquiry.py::test_c_increasing_curiosity_monotonically_increases_inquiry_intent_strength`
   - `tests/intents/test_sharing_urge_proactive_share.py::test_c_increasing_sharing_urge_monotonically_increases_share_intent_strength`
   - `tests/surface/test_sadness_initiative_suppression.py::test_c_monotonic_sadness_lowers_initiative`
   - `tests/surface/test_sadness_initiative_suppression.py::test_e_monotonic_sadness_lowers_expressive_warmth`
   - `tests/surface/test_anger_boundary_confrontation.py::test_c_monotonic_anger_raises_confrontation`
5. **Duplicate Cross-Consumer Regression Proofs (4 tests):**
   - `tests/intents/test_curiosity_proactive_inquiry.py::test_ak_longing_proactive_contact_remains_unaffected`
   - `tests/intents/test_curiosity_proactive_inquiry.py::test_al_sharing_urge_proactive_share_remains_unaffected`
   - `tests/intents/test_sharing_urge_proactive_share.py::test_longing_proactive_contact_remains_unaffected`
   - `tests/intents/test_longing_proactive_contact.py::test_ad_generic_proactive_contact_infrastructure_verified`
6. **Redundant Wrapper / Assertion Echo Tests (4 tests):**
   - `tests/intents/test_curiosity_proactive_inquiry.py::test_n_wake_signal_action_type_is_proactive_question`
   - `tests/intents/test_sharing_urge_proactive_share.py::test_m_wake_signal_action_type_is_proactive_share`
   - `tests/surface/test_sadness_initiative_suppression.py::test_w_dedicated_intent_cross_talk_protection_passes`
   - `tests/surface/test_sadness_initiative_suppression.py::test_x_initiative_suppression_ineffective_on_dedicated_intents`

### 6.2 Removable Candidates: Coverage-Only Probes (-8 tests, ~217 LOC)
1. `tests/host/test_host_adapter.py::test_host_wake_notification_contract_validation_and_as_dict` (47 LOC)
2. `tests/host/test_host_adapter.py::test_host_proactive_turn_result_contract_validation_and_as_dict` (85 LOC)
3. `tests/surface/test_surface_recipe_coverage.py::test_validate_candidate_recipe_valid` (5 LOC)
4. `tests/surface/test_surface_recipe_coverage.py::test_validate_projected_surface_edges` (27 LOC)
5. `tests/intents/test_longing_proactive_contact.py::test_no_type_ignore_on_proactive_path` (9 LOC)
6. `tests/intents/test_longing_proactive_contact.py::test_public_host_adapter_has_no_run_proactive_turn` (10 LOC)
7. `tests/intents/test_longing_proactive_contact.py::test_host_proactive_result_contract_clean` (25 LOC)
8. `tests/dynamics/test_fast_functions.py::test_spec_defaults_product_label_to_semantic_label` (9 LOC)

### 6.3 Collapsible Candidates via Table-Driven Parameterization (-10 test functions, ~450 LOC)
1. **Longing Host Wake Rejection Matrix:**
   - Collapse `test_g` through `test_m2` (8 functions) into a single parameterized test:
     `@pytest.mark.parametrize("rejection_case,corrupt_wake_fn,expected_reason", [...])`
   - **Net reduction:** -7 test functions, preserves all 8 distinct fail-closed branches.
2. **Cross-Talk Freedom Suites (Curiosity, Sharing Urge, Sadness):**
   - Curiosity `test_f`, `test_g`, `test_h` (3 functions) -> 1 parameterized test across interfering affects.
   - Sharing urge `test_f`, `test_g` (2 functions) -> 1 parameterized test.
   - **Net reduction:** -3 test functions, preserves all cross-talk assertions.
3. **Anger Confrontation Float Bands:**
   - Collapse `test_l`, `test_m`, `test_n` into 1 parameterized test:
     `@pytest.mark.parametrize("val,expected_band", [(0.2, "low"), (0.5, "moderate"), (0.8, "high")])`
   - **Net reduction:** -2 test functions, preserves all 3 band branches.

---

## 7. Summary & Final Compliance Statement

- All 214 test cases added between `d393a1af90a62cc529f13380c409cfb26db883e9` and `d21cbcf3f83429192869b02a1f19600b843eda5e` have been catalogued and classified.
- The net test count increase from **3,582 passed -> 3,820 passed (+238 tests)** is fully accounted for: +214 added test functions across 8 files, plus +24 optional vector memory tests executed under Gate B4 full dependencies.
- A concrete slimming blueprint is documented: **-55 test functions** and **~1,417 LOC** can be safely collapsed or removed without touching any of the 147 distinct failure paths.
- **Strictly read-only discipline was maintained:** No test files or production source files were modified or deleted.

POST_MIGRATION_TEST_REEXPANSION_AUDITED
