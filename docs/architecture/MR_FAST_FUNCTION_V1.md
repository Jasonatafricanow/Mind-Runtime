# MR Fast Function V1 Architecture Contract

## Principle

> "A fast state exists only when it provides a distinct runtime function."

Fast states exist solely to drive concrete behavioral and cognitive functions within the runtime pipeline. They are not an open taxonomy of human emotions, nor an ontological representation of personality.

## V1 Functional Fast State Lock

| State | Semantic Label | Primary Function | Consumer | Outbound-capable? | Status |
|---|---|---|---|:---:|---|
| `agent.affect.longing` | longing | `PROACTIVE_CONTACT` | Intent / proactive message path | Yes | ACTIVE |
| `agent.affect.sharing_urge` | sharing urge | `PROACTIVE_SHARE` | Intent / share path | Yes | ACTIVE |
| `agent.affect.curiosity` | curiosity | `INQUIRY_EXPLORATION` | Intent / retrieval-or-question path | Yes | ACTIVE |
| `agent.affect.anger` | anger / boundary pressure | `BOUNDARY_CONFRONTATION` | existing Surface / Intent / expression path | Yes | ACTIVE |
| `agent.affect.sadness` | sadness / low mood | `INITIATIVE_SUPPRESSION` | existing initiative / expression path | No | ACTIVE |
| `agent.affect.restlessness` | activation / excitation | `ACTIVITY_WAKE` | CognitiveTicker / wake-reconsider path | No | ACTIVE |
| `agent.affect.diligence_pressure` | responsibility pressure | `FOLLOW_UP_PERSISTENCE` | unresolved-task/follow-up Intent reconsideration + ActionPolicy anti-repeat controls | Yes | ACTIVE |
| `agent.affect.fatigue` | fatigue / cognitive load | `COGNITIVE_REST_PRESSURE` | future homeostasis / cognitive-mode scheduler | No | REGISTERED_ONLY |

## Key Invariants

1. **Restlessness Semantic Compatibility**: The persisted state key `agent.affect.restlessness` remains canonical for compatibility. Its V1 product interpretation is broadened to activation/excitation (tendency to wake, seek activity, or break prolonged inactivity).
2. **Diligence Anti-Spam (`FOLLOW_UP_PERSISTENCE != FOLLOW_UP_FREQUENCY`)**: `diligence_pressure` means an unresolved obligation remains behaviorally relevant for reconsideration. It does **not** mean sending reminders more frequently. Outbound reminder frequency remains strictly governed by cooldown, user response, duplicate protection, and ActionPolicy.
3. **Fatigue Ownership & Registered-Only Status**: `agent.affect.fatigue` is the only genuinely new V1 state concept. Its function contract is frozen, targeting cognitive-mode scheduling (daydream, sleep, offline consolidation, dream). Because adding it to canonical dynamics would require uncalibrated parameters (awake accumulation rate, sleep threshold, circadian model), its status is `REGISTERED_ONLY` until calibrated. Fatigue has no outbound-action consumer and does not send outbound messages.
4. **Existing States Outside V1 Lock**: Compatible runtime states (`agent.affect.closeness_craving`, `agent.affect.social_pull`, `agent.affect.introspective_pull`, `agent.affect.anxiety`) are preserved in persona configurations but are not members of `FAST_FUNCTION_V1`. In particular, `introspective_pull` is not the authority for fatigue / sleep / dream processing.

## Open Semantic Appraisal Boundary

Open semantic Appraisal may contain unlimited meanings. FAST_FUNCTION_V1 does not attempt to enumerate human emotion. Unsupported meanings remain unmapped rather than creating new state dimensions.

## Implementation Status Is Separate from Contract Status

`FastStateStatus.ACTIVE` means the fast-state contract/state key is admitted and available to runtime composition. It does **not** mean that the declared product consumer is fully wired end-to-end.

Consumer closure is tracked separately:

| State | Functional contract | Current consumer implementation |
|---|---|---|
| `agent.affect.longing` | `PROACTIVE_CONTACT` | **Core causal seam implemented, production composition not yet closed**: the explicit test composition proves Dynamics → Surface → Intent → ActionPolicy → `WakeSignal` → Host admission → proactive Body execution. The default production Xiyue composition does not yet wire the proactive ticker/expression-preparer path end-to-end. |
| `agent.affect.sharing_urge` | `PROACTIVE_SHARE` | Contract locked; dedicated consumer binding not yet certified. |
| `agent.affect.curiosity` | `INQUIRY_EXPLORATION` | Contract locked; dedicated consumer binding not yet certified. |
| `agent.affect.anger` | `BOUNDARY_CONFRONTATION` | Existing Surface/Intent/expression roots exist; no new V1 consumer certification is implied by this registry. |
| `agent.affect.sadness` | `INITIATIVE_SUPPRESSION` | Existing initiative/expression roots exist; no new V1 consumer certification is implied by this registry. |
| `agent.affect.restlessness` | `ACTIVITY_WAKE` | Contract locked; dedicated activity-wake consumer not yet certified. |
| `agent.affect.diligence_pressure` | `FOLLOW_UP_PERSISTENCE` | Contract locked; dedicated unresolved-item persistence consumer not yet certified. |
| `agent.affect.fatigue` | `COGNITIVE_REST_PRESSURE` | `REGISTERED_ONLY`; no canonical dynamics or sleep/daydream consumer yet. |

### Longing V1 closure boundary

Post-freeze baseline:

`LONGING_PROACTIVE_WAKE_V1_SHA = e48ce1ecacfbc7758359b6721dcfe84dd563e832`

Core causal seam at `57515c89bf3893d7a7fe3e15c444039bab9abfe3`:

```text
longing
→ Surface.contact_seeking
→ proactive Intent
→ ActionPolicy
→ WakeSignal
→ Host consumes and validates wake lineage (consume_wake)
→ Body starts proactive turn (run_proactive_turn)
→ DecisionContext (prepare_context)
→ provider generation (realize_after_wake)
→ ExpressionGuard
→ existing C7 / delivery boundary
```

Verified in the explicit proactive test composition:
1. **Provider call count before admission == 0** when the production-style ticker is composed without its legacy `expression` injection and Host execution is explicitly given the proactive expression preparer. The `CognitiveTicker` class still retains a legacy optional `expression` seam that can call provider realization if injected; this must be removed before a source-level "ticker can never invoke provider" invariant is claimed.
2. **Lineage preservation**: HostWakeNotification retains `wake_id`, `runtime_id`, `scope`, `intent_id`, `intent_version`, `action_type`, `interaction_id`, `policy_decision_ref`, `occurred_at`, `reason`, and `eligible`.
3. **Replay & conflict**: Process-local exactly-once admission; same wake is idempotent, conflicting payload on same `wake_id` fails closed.
4. **Guard enforcement**: Guard rejection aborts the turn without external delivery or uncommitted affect state modification.
5. **Causal trace ordering**:
   `policy_allow < wake_created < host_wake_admitted < proactive_body_entry <= proactive_expression_context < provider_realization < expression_guard <= proactive_expression`.



### Post-push source review boundary

Direct source review of `57515c89bf3893d7a7fe3e15c444039bab9abfe3` found remaining integration gaps that are not visible from the 35 longing tests alone:

- `CognitiveTicker` still has an optional `expression` constructor seam and still contains `_prepare_expression(...)`; if injected, `tick()` can still invoke provider realization before wake creation. Current production-style composition passes no expression preparer, but the class-level authority boundary is not structurally closed.
- `build_cognitive_components(...)` does not install an `expression_preparer`; `default_adapter(...)` does not wire proactive intent rules/ticker execution or expose proactive wake handling through `XiyueMRAdapter`. The passing end-to-end tests manually attach `orchestrator.cognitive_tick_components["expression_preparer"]`.
- `consume_wake(...)` validates the Intent lifecycle only **if** a lifecycle is available. Without one, the method can admit a wake after only the runtime check. Admission must fail closed when authoritative lifecycle/policy metadata is unavailable.
- `_resolve_tick_context(...)` contains a fallback that reconstructs a fresh `Situation` and synthesizes an `ActionPolicyResult(ALLOW)` from wake fields. This is not an authoritative restart reconstruction and must not substitute for the original admitted policy/context.
- Wake replay/result state and pending wake context are process-local. That limitation is acceptable only if explicitly documented; no restart-stable exactly-once claim is made.
- `HostProactiveTurnResult` currently reports `HostTurnStatus.COMMITTED` on Guard acceptance even though no proactive C7/external delivery commit occurs in this path. Accepted expression must not be mislabeled as committed delivery.

Therefore the current source status is:

```text
FAST_STATE_CONTRACT_STATUS=ACTIVE
CORE_CAUSAL_TEST_COMPOSITION=PASS
PRODUCTION_COMPOSITION_STATUS=GAP
TICKER_PROVIDER_CAPABILITY=FOUND
WAKE_ADMISSION_FAIL_CLOSED=FAIL
RESTART_CONTEXT_AUTHORITY=UNSAFE_FALLBACK
PROACTIVE_DELIVERY_COMMIT=NOT_IMPLEMENTED
CALIBRATION_STATUS=PROVISIONAL
```

Do not freeze `57515c89...` as the final production closure. It is a valid causal-seam candidate that still needs one bounded hardening pass.
