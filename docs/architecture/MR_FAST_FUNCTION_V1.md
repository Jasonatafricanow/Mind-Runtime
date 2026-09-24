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
| `agent.affect.longing` | `PROACTIVE_CONTACT` | **Production-wired & causal**: Dynamics → Surface `contact_seeking` → Intent → ActionPolicy → `WakeSignal` → Host wake admission (`consume_wake`) → Body proactive turn (`run_proactive_turn`) → `DecisionContext` → provider realization → `ExpressionGuard` → Delivery boundary. |
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

Completed causal closure (`MR-LONGING-PROACTIVE-BODY-ENTRY-V1-01`):

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

Verified invariants:
1. **Provider call count before admission == 0**: CognitiveTicker never directly invokes provider generation; provider is called only after successful Host wake admission.
2. **Lineage preservation**: HostWakeNotification retains `wake_id`, `runtime_id`, `scope`, `intent_id`, `intent_version`, `action_type`, `interaction_id`, `policy_decision_ref`, `occurred_at`, `reason`, and `eligible`.
3. **Replay & conflict**: Process-local exactly-once admission; same wake is idempotent, conflicting payload on same `wake_id` fails closed.
4. **Guard enforcement**: Guard rejection aborts the turn without external delivery or uncommitted affect state modification.
5. **Causal trace ordering**:
   `policy_allow < wake_created < host_wake_admitted < proactive_body_entry <= proactive_expression_context < provider_realization < expression_guard <= proactive_expression`.

