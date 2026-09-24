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
| `agent.affect.longing` | `PROACTIVE_CONTACT` | **Production hardened & architecture closed**: explicit test composition proves Dynamics → Surface → Intent → ActionPolicy → `WakeSignal` → Host admission → Body proactive turn → external provider generation → ExpressionGuard → explicit delivery commit. Ticker provider capability is removed; host admission fails closed against real lifecycle/policy authorities; restart context loss fails closed with `missing_authoritative_wake_context`; replay is process-local; Guard accept returns `PROCESSING` and explicit `commit_proactive_turn` transitions Intent to `COMPLETED` and marks `COMMITTED`. Production runtime config gap is explicitly noted (`PROACTIVE_RUNTIME_CONFIG_GAP=FOUND`). |
| `agent.affect.sharing_urge` | `PROACTIVE_SHARE` | **Verified & architecture closed under MR-SHARING-URGE-PROACTIVE-SHARE-V1-01**: Dedicated consumer binding verified via `agent.affect.sharing_urge` → `IntentRule(kind="spontaneous_share", dimension_weights=(("agent.affect.sharing_urge", 1.0),), surface_control_weights=())` → `ActionPolicy(action_type="proactive_share", proactive=True)` → `WakeSignal` → Host lifecycle & guard pipeline. Anti-spam invariant verified: `SHARING_URGE_CONTROLS_SHARE_PRESSURE != SHARING_URGE_CONTROLS_SEND_FREQUENCY`. Direct dimension binding preserves frozen candidate recipe digest (`4f37f46f89f6176fd5fefe0167ec7a81e341839f4fb9b98fa3cc348ddeaf9a55`). Production activation is blocked by config (`SHARING_URGE_PRODUCTION_ACTIVATION=BLOCKED_BY_CONFIG`). Calibration is provisional (`PROVISIONAL`). |
| `agent.affect.curiosity` | `INQUIRY_EXPLORATION` | Contract locked; dedicated consumer binding not yet certified. |
| `agent.affect.anger` | `BOUNDARY_CONFRONTATION` | Existing Surface/Intent/expression roots exist; no new V1 consumer certification is implied by this registry. |
| `agent.affect.sadness` | `INITIATIVE_SUPPRESSION` | Existing initiative/expression roots exist; no new V1 consumer certification is implied by this registry. |
| `agent.affect.restlessness` | `ACTIVITY_WAKE` | Contract locked; dedicated activity-wake consumer not yet certified. |
| `agent.affect.diligence_pressure` | `FOLLOW_UP_PERSISTENCE` | Contract locked; dedicated unresolved-item persistence consumer not yet certified. |
| `agent.affect.fatigue` | `COGNITIVE_REST_PRESSURE` | `REGISTERED_ONLY`; no canonical dynamics or sleep/daydream consumer yet. |

### Longing V1 closure boundary

Post-freeze baseline:

`LONGING_PROACTIVE_WAKE_V1_SHA = e48ce1ecacfbc7758359b6721dcfe84dd563e832`

Hardened production closure at `MR-LONGING-PROACTIVE-PRODUCTION-HARDENING-V1-01`:

```text
longing
→ Surface.contact_seeking
→ proactive Intent (IntentEngine)
→ ActionPolicy (DeterministicActionPolicy)
→ WakeSignal (CognitiveTicker stops strictly at WakeSignal)
→ Host validates wake lineage & authority (consume_wake)
→ Body begins proactive turn (begin_proactive_turn -> HostTurnStatus.PROCESSING)
→ DecisionContext handed to external Body
→ external Body runs provider generation (no provider inside ticker or MR begin_proactive_turn)
→ ExpressionGuard validates external prose (guard_proactive_prose -> HostTurnStatus.PROCESSING)
→ Hermes/external transport sends message
→ Host commits delivery (commit_proactive_turn -> HostTurnStatus.COMMITTED, Intent ALLOWED -> COMPLETED)
```

Verified invariants:
1. **Ticker provider capability removed**: `CognitiveTicker` has no `expression` parameter or `_prepare_expression`; provider call count prior to Host wake admission is strictly 0.
2. **Wake admission fails closed**: `consume_wake(...)` verifies against real authorities (`IntentLifecycleService`, `DeterministicActionPolicy`); missing authorities or mismatches result in `rejected:*`.
3. **No synthetic context reconstruction**: Fallback synthesis of `Situation` or `ActionPolicyResult` was deleted; missing in-memory execution context fails closed with `missing_authoritative_wake_context`.
4. **Process-local replay**: Exactly-once idempotency is process-local (`WAKE_REPLAY_SCOPE=PROCESS_LOCAL`).
5. **Guard accept vs delivery commit**: Guard ACCEPT returns `HostTurnStatus.PROCESSING` (not `COMMITTED`). Intent transitions to `COMPLETED` and status becomes `COMMITTED` only upon explicit `commit_proactive_turn(wake_id)`. Guard REJECT or `abort_proactive_turn` transitions intent to `SUPERSEDED` and marks `ABORTED`.
6. **Causal trace ordering**:
   `policy_allow < wake_created < host_wake_admitted < proactive_body_entry <= proactive_expression_context < provider_realization < expression_guard <= proactive_expression`.
7. **Production composition & config gap**: `default_adapter` and `XiyueMRAdapter` wire real `intent_rules`, `action_policy_config`, `policy_resources`, `delivery_db`, and `expression_guard`. The certified manifest (`certification/d11s/inputs/runtime-config.json`) does not yet include proactive contact rules or SURFACE_V1 persona publication (`PROACTIVE_RUNTIME_CONFIG_GAP=FOUND`), but the runtime machinery is verified and hardened.

Final status:

```text
FAST_STATE_CONTRACT_STATUS=ACTIVE
CORE_CAUSAL_TEST_COMPOSITION=PASS
PRODUCTION_COMPOSITION_STATUS=WIRED
TICKER_PROVIDER_CAPABILITY=REMOVED
WAKE_ADMISSION_FAIL_CLOSED=PASS
RESTART_CONTEXT_AUTHORITY=FAIL_CLOSED_PROCESS_LOCAL
WAKE_REPLAY_SCOPE=PROCESS_LOCAL
POLICY_DECISION_REF_VALIDATION=UNRESOLVED_BY_CURRENT_STORE
PROACTIVE_DELIVERY_COMMIT=IMPLEMENTED
PROACTIVE_RUNTIME_CONFIG_GAP=FOUND
CALIBRATION_STATUS=PROVISIONAL
```

### Sharing Urge V1 closure boundary

Closed at task `MR-SHARING-URGE-PROACTIVE-SHARE-V1-01` (Base SHA: `87193868205931436568c0d2e7a14d0dc301f340`).

#### 1. Causal Pipeline
```text
agent.affect.sharing_urge
→ IntentRule(kind="spontaneous_share", dimension_weights=(("agent.affect.sharing_urge", 1.0),), surface_control_weights=())
→ DeterministicIntentEngine
→ ActionPolicy(action_type="proactive_share", proactive=True)
→ CognitiveTicker stops strictly at WakeSignal
→ Host validates wake lineage & authority (consume_wake)
→ Body begins proactive turn (begin_proactive_turn -> HostTurnStatus.PROCESSING)
→ DecisionContext handed to external Body
→ external Body runs provider generation (content-dependent prose)
→ ExpressionGuard validates external prose (guard_proactive_prose)
→ Hermes/external transport sends message (existing delivery mechanism)
→ Host commits delivery (commit_proactive_turn -> HostTurnStatus.COMMITTED, Intent ALLOWED -> COMPLETED)
```

#### 2. Key Verified Invariants
1. **Anti-Spam Invariant (`SHARING_URGE_CONTROLS_SHARE_PRESSURE != SHARING_URGE_CONTROLS_SEND_FREQUENCY`)**:
   `validate_sharing_urge_anti_spam_invariant` verifies that high sharing urge increases candidate pressure and score, but has zero authority to shorten or override `ActionPolicy` cooldowns.
2. **Surface Recipe Digest Invariant**:
   `Surface.initiative` is defined as:
   $$\text{initiative} = 0.60 \times \text{sharing\_urge} + 0.50 \times \text{curiosity} - 0.25 \times \text{sadness}$$
   `spontaneous_share` does not use `Surface.initiative` because `initiative` is a composite control of `sharing_urge + curiosity + sadness`. Using it would introduce cross-talk into dedicated `PROACTIVE_SHARE`. No new Surface control (`sharing_drive`, etc.) was introduced. Candidate Recipe v2 digest (`4f37f46f89f6176fd5fefe0167ec7a81e341839f4fb9b98fa3cc348ddeaf9a55`) and 5 surface controls are preserved intact.
3. **Cross-Talk Freedom**:
   Monotonic scoring strictly driven by `agent.affect.sharing_urge`. Variations in `curiosity` or `sadness` have zero impact on `spontaneous_share` candidate score.
4. **Host Wake Admission & Replay**:
   Wake admission validates against real lifecycle and policy authorities. Duplicate wakes are idempotent and return `ALREADY_PROCESSED` with 0 provider calls.
5. **Fail-Closed Guard & Explicit Delivery Commit**:
   Guard rejection (e.g. empty or forbidden openings) immediately aborts the turn (`HostTurnStatus.ABORTED`), transitions Intent to `SUPERSEDED`, and commits zero delivery. Guard acceptance transitions to `PROCESSING`; only explicit `commit_proactive_turn` marks delivery `COMMITTED` and Intent `COMPLETED`.
6. **Delivery Mechanism Reuse**:
   Reuses the standard proactive delivery pipeline and Hermes transport; does not introduce a secondary outbound path.
7. **Production Activation Blocked by Config**:
   Runtime machinery is fully wired and verified. Production activation is blocked by configuration pending parameter calibration (`SHARING_URGE_CALIBRATION_STATUS=PROVISIONAL`, `SHARING_URGE_PRODUCTION_ACTIVATION=BLOCKED_BY_CONFIG`).

