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
| `agent.affect.anger` | anger / boundary pressure | `BOUNDARY_CONFRONTATION` | Surface confrontation / expression directness path | Yes | ACTIVE |
| `agent.affect.sadness` | sadness / low mood | `INITIATIVE_SUPPRESSION` | Surface initiative / expression warmth path | No | ACTIVE |
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
| `agent.affect.curiosity` | `INQUIRY_EXPLORATION` | **Verified & architecture closed under MR-CURIOSITY-PROACTIVE-INQUIRY-V1-01**: Question branch closed via dedicated Intent (`proactive_inquiry`, `surface_control_weights=()`) and proactive ActionPolicy (`proactive_question`, `proactive=True`) → `WakeSignal` → Host lifecycle & guard pipeline. Autonomous retrieval branch remains explicitly deferred (`CURIOSITY_RETRIEVAL_BRANCH=DEFERRED`, `RETRIEVAL_IS_ACTION_AUTHORITY=NO`). Anti-spam invariant verified: `CURIOSITY_CONTROLS_INQUIRY_PRESSURE != CURIOSITY_CONTROLS_QUESTION_FREQUENCY`. Direct dimension binding preserves Candidate Recipe v2 digest (`4f37f46f89f6176fd5fefe0167ec7a81e341839f4fb9b98fa3cc348ddeaf9a55`). Production activation is blocked by config (`CURIOSITY_PRODUCTION_ACTIVATION=BLOCKED_BY_CONFIG`). Calibration is provisional (`PROVISIONAL`). |
| `agent.affect.anger` | `BOUNDARY_CONFRONTATION` | **Audited & closed under MR-ANGER-BOUNDARY-CONFRONTATION-AUDIT-V1-01 / MR-ANGER-BOUNDARY-CONFRONTATION-CLEANUP-V1-02**: Expression branch closed via `agent.affect.anger` → `Surface.confrontation` → Candidate Expression Map v2 (`directness` ∈ `low` \| `moderate` \| `high`) → `DecisionContextCompiler` (SURFACE_V1) → `DeterministicContextRenderer`. Directness is rendered with zero raw anger/float/trait leak. Proactive/autonomous boundary intent branch remains explicitly deferred (`ANGER_INTENT_BRANCH=DEFERRED_NO_BOUNDARY_EVENT_TO_INTENT_AUTHORITY`, `BOUNDARY_EVENT_TO_INTENT_AUTHORITY=NONE`). Intent capability exists structurally because confrontation is Intent-eligible, but concrete boundary Intent branch is deferred because no authoritative boundary-event-to-Intent binding exists. Core authority invariant verified: `ANGER_CONTROLS_BOUNDARY_PRESSURE != ANGER_GRANTS_ACTION_PERMISSION`. Final verdict: `ANGER_EXPRESSION_CLOSED_INTENT_DEFERRED`. |
| `agent.affect.sadness` | `INITIATIVE_SUPPRESSION` | **Audited under MR-SADNESS-INITIATIVE-SUPPRESSION-AUDIT-V1-01**: Surface initiative projection verified ($\Delta\text{initiative} = -0.25 \times \Delta\text{sadness}$). Expression warmth branch closed via `expressive_warmth` ($\Delta = -0.20 \times \Delta\text{sadness}$) → qualitative `warmth` guidance with zero raw leak. **Primary function runtime gap found**: No configured or certified IntentRule consumes `Surface.initiative`; ActionPolicy and CognitiveTicker do not gate on initiative; dedicated proactive intents (`spontaneous_share`, `proactive_inquiry`, `reach_out`) use direct Dynamics roots to prevent cross-talk, so sadness produces zero suppression on proactive dispatch (`SADNESS_EFFECTIVE_INITIATIVE_CONSUMER=NONE`, `SADNESS_PRIMARY_FUNCTION_RUNTIME_GAP=FOUND`). Semantic invariant: `SADNESS_SUPPRESSES_INITIATIVE_PRESSURE != SADNESS_GRANTS_ACTION_PERMISSION`. Final verdict: `SADNESS_SURFACE_CLOSED_PRIMARY_CONSUMER_GAP_FOUND`. |
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

Closed at task `MR-SHARING-URGE-PROACTIVE-SHARE-V1-01` (Base SHA: `87193868205931436568c0d2e7a14d0dc301f340`, Code Freeze Candidate: `3780d69eb8fc5b1e18e41d0a02117aa32ce137f8`).

#### 1. Causal Pipeline
```text
agent.affect.sharing_urge
→ IntentRule(kind="spontaneous_share", dimension_weights=(("agent.affect.sharing_urge", 1.0),), surface_control_weights=())
→ DeterministicIntentEngine
→ ActionPolicy(action_type="proactive_share", proactive=True)
→ CognitiveTicker stops strictly at WakeSignal
→ Host validates wake lineage & authority (consume_wake)
→ Body begins proactive turn (begin_proactive_turn -> HostTurnStatus.PROCESSING)
→ DecisionContext handed to external Body (< BODY_BOUNDARY)
→ external Body runs provider generation (content-dependent prose)
→ ExpressionGuard validates external prose (guard_proactive_prose)
→ Hermes/external transport sends message (existing delivery mechanism)
→ Host commits delivery (commit_proactive_turn -> HostTurnStatus.COMMITTED, Intent ALLOWED -> COMPLETED)
```

The MR-side pre-Body ordering is:
`policy_allow < wake_created < host_wake_admitted < proactive_body_entry <= proactive_expression_context < BODY_BOUNDARY`

External Body then performs provider generation. When prose returns to MR, `ExpressionGuard` determines delivery eligibility. After external delivery success, `commit_proactive_turn` transitions Intent to `COMPLETED`.

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
6. **No Synthetic Evidence & No Raw State Provider Leak**:
   `SYNTHETIC_EVIDENCE_PATH=NONE` (MR does not invent fake user/world Evidence items merely because `sharing_urge` is high).
   `RAW_SHARING_URGE_PROVIDER_LEAK=NONE` (MR does not expose raw `sharing_urge` state to provider-visible context).
   *(Note: This bounds MR context construction; it does not claim external LLM hallucination is impossible).*
7. **Delivery Mechanism Reuse**:
   Reuses the standard proactive delivery pipeline and Hermes transport; does not introduce a secondary outbound path.
8. **Production Activation Blocked by Config**:
   Runtime machinery is fully wired and verified. Production activation is blocked by configuration pending parameter calibration (`SHARING_URGE_CALIBRATION_STATUS=PROVISIONAL`, `SHARING_URGE_PRODUCTION_ACTIVATION=BLOCKED_BY_CONFIG`).

### Curiosity V1 closure boundary

Closed at task `MR-CURIOSITY-PROACTIVE-INQUIRY-V1-01` (Base SHA: `be16499d8a673940dba3e6196f51ff7dd79be054`).

#### 1. Causal Pipeline
```text
agent.affect.curiosity
→ IntentRule(kind="proactive_inquiry", dimension_weights=(("agent.affect.curiosity", 1.0),), surface_control_weights=())
→ DeterministicIntentEngine
→ ActionPolicy(action_type="proactive_question", proactive=True)
→ CognitiveTicker stops strictly at WakeSignal
→ Host validates wake lineage & authority (consume_wake)
→ Body begins proactive turn (begin_proactive_turn -> HostTurnStatus.PROCESSING)
→ DecisionContext handed to external Body (< BODY_BOUNDARY)
→ external Body runs provider generation (content-dependent prose)
→ ExpressionGuard validates external prose (guard_proactive_prose)
→ Hermes/external transport sends message (existing delivery mechanism)
→ Host commits delivery (commit_proactive_turn -> HostTurnStatus.COMMITTED, Intent ALLOWED -> COMPLETED)
```

The MR-side pre-Body ordering is:
`policy_allow < wake_created < host_wake_admitted < proactive_body_entry <= proactive_expression_context < BODY_BOUNDARY`

External Body then performs provider generation. When prose returns to MR, `ExpressionGuard` determines delivery eligibility. After external delivery success, `commit_proactive_turn` transitions Intent to `COMPLETED`.

#### 2. Key Verified Invariants
1. **Question Branch Closed & Retrieval Branch Deferred**:
   `CURIOSITY_RETRIEVAL_BRANCH=DEFERRED` and `RETRIEVAL_IS_ACTION_AUTHORITY=NO`. This ticket closes the question branch only (`proactive_inquiry` / `proactive_question`). Retrieval provides informational context only, never action authority. Retrieval results cannot create an Intent, cannot produce `ActionPolicyResult(ALLOW)`, and cannot emit a `WakeSignal`. `CognitiveTicker` does not invoke retrieval, and tick situation has `historical_context=None`.
2. **Anti-Spam Invariant (`CURIOSITY_CONTROLS_INQUIRY_PRESSURE != CURIOSITY_CONTROLS_QUESTION_FREQUENCY`)**:
   `validate_curiosity_anti_spam_invariant` verifies that high curiosity increases inquiry scoring pressure, but has zero authority to shorten or override `ActionPolicy` cooldowns.
3. **Surface Recipe Digest Invariant & Cross-Talk Freedom**:
   `Surface.initiative` is defined as:
   $$\text{initiative} = 0.60 \times \text{sharing\_urge} + 0.50 \times \text{curiosity} - 0.25 \times \text{sadness}$$
   `proactive_inquiry` does not use `Surface.initiative` because `initiative` is a composite control containing `sharing_urge + curiosity + sadness`. Using it would introduce cross-talk into dedicated `INQUIRY_EXPLORATION` from `sharing_urge` and `sadness`. No new Surface control (`curiosity_drive`, etc.) was introduced. Candidate Recipe v2 digest (`4f37f46f89f6176fd5fefe0167ec7a81e341839f4fb9b98fa3cc348ddeaf9a55`) and 5 surface controls are preserved intact.
4. **Host Wake Admission & Replay Idempotency**:
   Wake admission validates against real lifecycle and policy authorities. Duplicate wakes are idempotent and return `ALREADY_PROCESSED` with 0 provider calls. Conflicting wake payloads fail closed.
5. **Fail-Closed Guard & Explicit Delivery Commit**:
   Guard rejection (e.g. empty or forbidden openings) immediately aborts the turn (`HostTurnStatus.ABORTED`), transitions Intent to `SUPERSEDED`, and commits zero delivery. Guard acceptance transitions to `PROCESSING`; only explicit `commit_proactive_turn` marks delivery `COMMITTED` and Intent `COMPLETED`.
6. **No Synthetic Evidence & No Raw State Provider Leak**:
   `SYNTHETIC_EVIDENCE_PATH=NONE` (MR does not invent fake user/world Evidence items merely because `curiosity` is high).
   `RAW_CURIOSITY_PROVIDER_LEAK=NONE` (MR does not expose raw `curiosity` state keys or values to provider-visible context).
   *(Note: This bounds MR context construction; it does not claim external LLM hallucination is impossible).*
7. **Delivery Mechanism Reuse**:
   Reuses the standard proactive delivery pipeline and Hermes transport; does not introduce a secondary outbound path.
8. **Multi-Urge Competition**:
   When `reach_out`, `spontaneous_share`, and `proactive_inquiry` compete, exactly one `WakeSignal` is emitted per tick. Candidate scoring is strictly governed by rule weights and dimension values; no hardcoded emotional priority exists.
9. **Production Activation Blocked by Config**:
   Runtime machinery is fully wired and verified. Production activation is blocked by configuration pending parameter calibration (`CURIOSITY_CALIBRATION_STATUS=PROVISIONAL`, `CURIOSITY_PRODUCTION_ACTIVATION=BLOCKED_BY_CONFIG`).

### Anger V1 closure boundary

Closed at task `MR-ANGER-BOUNDARY-CONFRONTATION-AUDIT-V1-01` (Base SHA: `a83922cc5cadf123abc113d6103552d8d5214adb`).

#### 1. Causal Pipeline (Expression Branch - Closed)
```text
agent.affect.anger
→ Surface.confrontation (= 0.70 * anger + 0.40 * confrontation_readiness - 0.30 * expressive_restraint)
→ Candidate Expression Map v2 (source_control="confrontation" -> guidance_dimension="directness")
→ Qualitative band partition (low: [0.0, 0.33), moderate: [0.33, 0.66), high: [0.66, 1.0])
→ DecisionContextCompiler (SURFACE_V1: items of kind surface_guidance with key="directness")
→ DeterministicContextRenderer (renders [SURFACE_GUIDANCE] - directness: <band>)
→ External Body / Provider realization (contains zero raw anger floats, names, or persona traits)
```

Secondary surface dampening effects:
- `contact_seeking`: includes term `-0.20 * anger`
- `expressive_warmth`: includes term `-0.25 * anger`

#### 2. Autonomous Intent Branch Deferral (Intent Branch - Deferred)
- `BOUNDARY_EVENT_TO_INTENT_AUTHORITY = "NONE"`: No authoritative boundary-event-to-Intent binding exists distinguishing "anger exists" from "boundary assertion warranted". Intent capability exists structurally because confrontation is Intent-eligible, but concrete boundary Intent branch is deferred because no certified boundary-event-to-Intent binding exists.
- `BOUNDARY_INTENT_RULE = "NONE"`: Certified manifest (`certification/d11s/inputs/runtime-config.json`) contains zero confrontation-driven Intent rules.
- `BOUNDARY_ACTION_POLICY_RULE = "NONE"`: Certified manifest contains zero boundary action policy rules.
- `ANGER_INTENT_BRANCH = "DEFERRED_NO_BOUNDARY_EVENT_TO_INTENT_AUTHORITY"`.
- No new proactive boundary action type is invented merely for symmetry.

#### 3. Key Verified Invariants
1. **Authority Separation (`ANGER_CONTROLS_BOUNDARY_PRESSURE != ANGER_GRANTS_ACTION_PERMISSION`)**:
   `ANGER_CONTROLS_BOUNDARY_PRESSURE_NOT_PERMISSION_INVARIANT` records the semantic boundary: elevated anger / confrontation creates qualitative directness pressure, but has zero authority to grant ActionPolicy permission without independent policy rule authorization. ActionPolicy exclusively owns action permission.
2. **Recipe Digest Preservation**:
   Candidate Recipe v2 digest (`4f37f46f89f6176fd5fefe0167ec7a81e341839f4fb9b98fa3cc348ddeaf9a55`) and the 5 surface controls (`contact_seeking`, `initiative`, `confrontation`, `expressive_warmth`, `expressive_restraint`) are preserved unchanged.
3. **Expression Map Digest Preservation**:
   Candidate Expression Map v2 digest (`bba6794aeda7a1755f8c79ffe5c88bd100918e6bc979ea29b5aa009e958eddf3`) maps `confrontation` to `directness` across frozen monotonic partitions.
4. **Zero Raw Affect / Trait Leakage**:
   `DeterministicContextRenderer.verify_provider_information_isolation` verifies that raw affect names (`agent.affect.anger`), raw numeric floats, and persona traits (`confrontation_readiness`, `expressive_restraint`) are strictly absent from the rendered provider context.
5. **No Synthetic Boundary Evidence or Facts**:
   `SYNTHETIC_EVIDENCE_PATH = NONE`. Elevated anger never fabricates synthetic user/world evidence or injects synthetic boundary violation facts into `Situation`.
6. **Root Overlap Protection**:
   `validate_intent_rule_surface_overlap` strictly rejects any Intent rule attempting to combine `contact_seeking` and `confrontation` (`ROOT_OVERLAP`) because both share `agent.affect.anger` and `persona.behavioral_disposition.expressive_restraint`.
7. **Final Verdict**:
   `FINAL_VERDICT = ANGER_EXPRESSION_CLOSED_INTENT_DEFERRED`.

### Sadness V1 closure boundary

Audited at task `MR-SADNESS-INITIATIVE-SUPPRESSION-AUDIT-V1-01` (Base SHA: `1edd62e4e3a97e469c4c8229229950476e86861b`).

#### 1. Surface Initiative Branch (Mathematical Behavior Verified)
```text
agent.affect.sadness
→ Surface.initiative (= clamp(0.60 * sharing_urge + 0.50 * curiosity - 0.25 * sadness, 0.0, 1.0))
→ Unclamped rate: Δinitiative = -0.25 * Δsadness
```
Mathematical projection into `Surface.initiative` strictly passes.

#### 2. Secondary Expression Warmth Branch (Closed)
```text
agent.affect.sadness
→ Surface.expressive_warmth (= clamp(0.55 * bias + 0.50 * closeness - 0.25 * anger - 0.20 * sadness, 0.0, 1.0))
→ Unclamped rate: Δexpressive_warmth = -0.20 * Δsadness
→ Candidate Expression Map v2 (source_control="expressive_warmth" -> guidance_dimension="warmth")
→ Qualitative band partition (low: [0.0, 0.33), moderate: [0.33, 0.66), high: [0.66, 1.0])
→ DecisionContextCompiler (SURFACE_V1: items of kind surface_guidance with key="warmth")
→ DeterministicContextRenderer (renders [SURFACE_GUIDANCE] - warmth: <band>)
→ External Body / Provider realization (contains zero raw sadness floats, names, or persona traits)
```
Expression warmth branch is fully verified and marked `CLOSED`.

#### 3. Effective Initiative Consumer & Primary Function Runtime Gap (Gap Found)
- **Zero Downstream Consumers**: While `initiative ∈ ELIGIBLE_INTENT_SURFACE_CONTROLS`, zero Intent rules across runtime configuration and the certified manifest consume `Surface.initiative` (`INITIATIVE_INTENT_RULE = "NONE"`).
- **ActionPolicy Independence**: `DeterministicActionPolicy` does not inspect, gate, or modulate permissions on `initiative` (`ACTION_POLICY_CONSUMES_INITIATIVE = "NO"`).
- **CognitiveTicker Independence**: `CognitiveTicker` passes computed `Surface` to `IntentEngineInput`, but executes zero generic suppression or gating on `initiative` (`TICKER_CONSUMES_INITIATIVE_AS_GATE = "NO"`).
- **Expression Map Independence**: Expression Map does not consume `initiative` (`EXPRESSION_MAP_CONSUMES_INITIATIVE = "NO"`).
- **Cross-Talk Protection & Counterfactual Proof**:
  - `spontaneous_share` scores directly from `agent.affect.sharing_urge` (`SADNESS_SUPPRESSES_SPONTANEOUS_SHARE = NO`).
  - `proactive_inquiry` scores directly from `agent.affect.curiosity` (`SADNESS_SUPPRESSES_PROACTIVE_INQUIRY = NO`).
  - `reach_out` scores from `contact_seeking` which has no sadness term (`SADNESS_SUPPRESSES_REACH_OUT = NO`).
  - `DEDICATED_INTENT_CROSS_TALK_PROTECTION = "PASS"`.
  - `INITIATIVE_SUPPRESSION_EFFECTIVE_ON_DEDICATED_INTENTS = "NO"`.
- **Architectural Findings**:
  - `SADNESS_SURFACE_INITIATIVE_PROJECTION = "PASS"`
  - `SADNESS_EFFECTIVE_INITIATIVE_CONSUMER = "NONE"`
  - `SADNESS_PRIMARY_FUNCTION_RUNTIME_GAP = "FOUND"`
  - `SADNESS_EXPRESSION_BRANCH = "CLOSED"`
  - `FINAL_VERDICT = "SADNESS_SURFACE_CLOSED_PRIMARY_CONSUMER_GAP_FOUND"`
- **Authority Separation Invariant**:
  `SADNESS_SUPPRESSES_INITIATIVE_PRESSURE_NOT_PERMISSION_INVARIANT = "SADNESS_SUPPRESSES_INITIATIVE_PRESSURE != SADNESS_GRANTS_ACTION_PERMISSION"`. Sadness is internal affect modulation, not an inaction policy verdict. ActionPolicy exclusively owns action permission.

### Initiative Admission Gate V1 closure boundary

Implemented at task `MR-INITIATIVE-ADMISSION-GATE-V1-01` (Base SHA: `9b46d663ae9d8595357c16b2e71b12ae6ec017d8`, ADR-0030: `docs/adr/0030-bounded-intent-engine-initiative-admission-gate.md`).

#### 1. Causal Pipeline
```text
domain-specific Dynamics root
→ domain Intent strength
→ independent Surface.initiative admission gate
→ admitted Intent candidate
→ existing ActionPolicy
→ existing downstream lifecycle
```

#### 2. Key Architecture Invariants
1. **Separation of Motivation and Behavioral Threshold**:
   Domain strength continues to answer "How strongly does the agent want to perform this specific action?" (`agent.affect.sharing_urge` for `spontaneous_share`, `agent.affect.curiosity` for `proactive_inquiry`).
   `Surface.initiative` answers "Does the agent currently possess enough overall initiative to self-start this turn?"
2. **Domain Score Preservation**:
   Gated rules evaluate and clamp domain score first. The domain strength is preserved identically across gate pass, below-threshold, and lineage failures. Initiative never alters or multiplies domain strength, nor adds score contributions (`contributions` contain zero `surface` or `initiative` entries).
3. **Motive Gating Scope**:
   Strictly restricted to `spontaneous_share` and `proactive_inquiry`. `reach_out` (longing root) remains ungated by initiative. Reactive and scheduled intents (`respond`, `scheduled_follow_up`, `assert_boundary`) remain ungated.
4. **Conditional Overlap Policy (`ROOT_OVERLAP_POLICY = "CONDITIONAL"`)**:
   Independent admission gate inspection is permitted (`minimum_initiative`), while direct score contribution (`surface_control_weights`) continues to be rejected by `ROOT_OVERLAP`.
5. **Fail-Closed Lineage Validation**:
   Admission gate fails closed if `Surface` is unavailable, malformed/tampered (`surface_invalid`), or stale/mismatched across runtime, interaction, persona, projection, or state versions (`surface_stale_or_mismatch`).
6. **Persistence & Wire Compatibility**:
   - `ruleset_ref` byte-identical to legacy calculation when `minimum_initiative is None`.
   - SQLite JSON `surface_use` byte-identical to legacy serialization when `surface_admission is None`.
7. **Downstream Isolation**:
   Gate rejection suppresses candidate emission (`candidates=()`), lifecycle admission, policy evaluation, and WakeSignal generation.
   ActionPolicy, Surface recipe, expression map, and certified manifest remain untouched. CognitiveTicker and orchestrator behavioral semantics remain unchanged; the existing observer/audit seam was extended to retain current IntentEngine traces.
8. **Audit & Activation Status**:
   - `ROOT_OVERLAP_POLICY = "CONDITIONAL"`
   - `REJECTED_TRACE_AUDIT_SEAM = "REUSED"`
   - `INITIATIVE_GATE_CALIBRATION_STATUS = "PROVISIONAL"`
   - `INITIATIVE_GATE_PRODUCTION_ACTIVATION = "BLOCKED_BY_CONFIG"`
   - `FINAL_VERDICT = "INITIATIVE_ADMISSION_GATE_V1_READY_CONFIG_PENDING"`
