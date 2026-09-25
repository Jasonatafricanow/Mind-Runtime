# MR Fast-State Consumer Development Guide

Date: 2026-09-24

This guide defines the implementation pattern for FAST_FUNCTION_V1 consumers. It is deliberately consumer-driven: a fast state is admitted because it provides a concrete runtime function, not because it belongs to a complete emotion taxonomy.

## 1. Two independent statuses

Never use one status word for both the state and its consumer.

- **State/contract status**: is the state key and functional contract admitted?
- **Consumer status**: is the declared function actually wired through its authoritative consumer path?

`FastStateStatus.ACTIVE` does not mean end-to-end feature completion.

## 2. Generic implementation pattern

For behavior-affecting fast states:

```text
open semantic appraisal
→ Dynamics fast state
→ Surface (when behavioral projection is required)
→ Intent / bounded control consumer
→ ActionPolicy
→ effect-specific seam
```

For externally active functions, the effect-specific seam is normally a wake/request boundary, not direct transport:

```text
ActionPolicy ALLOW
→ WakeSignal
→ Host/Adapter
→ Body starts turn
→ DecisionContext
→ provider realization
→ ExpressionGuard
→ existing delivery authority
```

Forbidden shortcuts:

```text
Dynamics → Delivery
Surface → Delivery
IntentEngine → Delivery
CognitiveTicker → DeliveryRequest
WakeSignal → final user-visible text
```

## 3. Consumer-first admission rule

Before adding a new fast state, answer:

1. What distinct runtime function does it provide?
2. Which component is the sole consumer?
3. What existing states cannot provide the same function by composition?
4. What is its time behavior: trigger, accumulation, decay/recovery?
5. What authority boundary prevents the state from directly executing external actions?

If the function or consumer is unclear, keep the meaning in open semantic Appraisal and leave it UNMAPPED.

## 4. Longing reference implementation

Post-freeze baseline: `e48ce1ecacfbc7758359b6721dcfe84dd563e832`

Hardened production closure: `MR-LONGING-PROACTIVE-PRODUCTION-HARDENING-V1-01`

```text
agent.affect.longing
→ Surface.contact_seeking
→ proactive Intent (IntentEngine)
→ ActionPolicy (DeterministicActionPolicy)
→ WakeSignal (CognitiveTicker stops strictly at WakeSignal)
→ Host.consume_wake(...) (admission & lineage validation against real authorities)
→ Host.begin_proactive_turn(...) (Body entry -> HostTurnStatus.PROCESSING)
→ DecisionContext handed to external Body
→ external Body runs provider generation (no provider inside ticker or MR)
→ Host.guard_proactive_prose(...) (ExpressionGuard -> HostTurnStatus.PROCESSING)
→ external transport sends message
→ Host.commit_proactive_turn(...) (Intent ALLOWED -> COMPLETED, HostTurnStatus.COMMITTED)
```

Key causal rules verified:
1. `provider_call_count == 0` prior to Host wake admission. `CognitiveTicker` has no provider execution capability.
2. Host rejects invalid wake without invoking provider; admission fails closed if lifecycle or policy authorities are unavailable.
3. Host exactly-once idempotency: duplicate wake returns `ALREADY_PROCESSED` with 0 additional provider calls; conflicting payload fails closed.
4. Process-restart context loss fails closed as unsupported V1 recovery (`missing_authoritative_wake_context`); no synthetic context is reconstructed.
5. Guard acceptance alone returns `HostTurnStatus.PROCESSING`; delivery commitment is explicit via `commit_proactive_turn`, which transitions Intent to `COMPLETED` and clears pending in-memory context.
6. Guard rejection aborts the turn via `abort_proactive_turn`, which transitions Intent to `SUPERSEDED` and clears pending context.

## 5. Required test shape for future consumers

Tests must distinguish structural coexistence from causal order.

For an outbound-capable function, prove separately:

- state affects only the admitted Surface/Intent path;
- raw state cannot bypass that path;
- ActionPolicy can deny/defer;
- anti-repeat/cooldown remains independent from affect magnitude;
- the effect seam carries bounded typed references only;
- the downstream consumer validates runtime/scope/lineage;
- the effect seam is what causes downstream execution;
- provider generation happens after the execution/wake boundary when the architecture requires Body execution;
- Guard rejection prevents external delivery;
- no internal output becomes user/world Evidence without new external evidence.

A test that merely obtains both a wake and generated prose in one function call is insufficient to prove `wake → Body turn` causality.

## 6. V1 implementation queue

| Fast state | Function | Next implementation work |
|---|---|---|
| `longing` | proactive contact | **Production hardened & architecture closed**: ticker provider capability removed; fail-closed admission against real authorities; no synthetic context reconstruction; explicit `commit_proactive_turn` transitions Intent to `COMPLETED`; real production composition wired. Certified manifest config gap noted (`PROACTIVE_RUNTIME_CONFIG_GAP=FOUND`). Calibration remains provisional. |
| `sharing_urge` | proactive share | **Architecture closed & verified under MR-SHARING-URGE-PROACTIVE-SHARE-V1-01**: Bound directly via `dimension_weights=(("agent.affect.sharing_urge", 1.0),)` with `surface_control_weights=()`. `Surface.initiative` was rejected because it is a composite control ($0.60 \times \text{sharing\_urge} + 0.50 \times \text{curiosity} - 0.25 \times \text{sadness}$), inducing cross-talk from curiosity and sadness. Anti-spam invariant verified: `SHARING_URGE_CONTROLS_SHARE_PRESSURE != SHARING_URGE_CONTROLS_SEND_FREQUENCY`. Production activation blocked by frozen candidate manifest; calibration provisional. |
| `curiosity` | inquiry/exploration | **Architecture closed & verified under MR-CURIOSITY-PROACTIVE-INQUIRY-V1-01**: Question branch closed via direct binding `dimension_weights=(("agent.affect.curiosity", 1.0),)` and `surface_control_weights=()`. Autonomous retrieval branch remains explicitly deferred (`CURIOSITY_RETRIEVAL_BRANCH=DEFERRED`, `RETRIEVAL_IS_ACTION_AUTHORITY=NO`). Anti-spam invariant verified: `CURIOSITY_CONTROLS_INQUIRY_PRESSURE != CURIOSITY_CONTROLS_QUESTION_FREQUENCY`. Production activation blocked by frozen candidate manifest; calibration provisional. |
| `anger` | boundary/confrontation | **Audited & closed under MR-ANGER-BOUNDARY-CONFRONTATION-AUDIT-V1-01**: Primary consumer is `Surface confrontation / expression directness path`. Surface/expression branch closed via `agent.affect.anger` → `Surface.confrontation` → Candidate Expression Map v2 (`directness`) → provider envelope. Intent capability exists structurally because confrontation is Intent-eligible, but concrete boundary Intent branch is deferred because no authoritative boundary-event-to-Intent binding exists (`ANGER_INTENT_BRANCH=DEFERRED_NO_BOUNDARY_EVENT_TO_INTENT_AUTHORITY`, `BOUNDARY_EVENT_TO_INTENT_AUTHORITY=NONE`). Core authority invariant: `ANGER_CONTROLS_BOUNDARY_PRESSURE != ANGER_GRANTS_ACTION_PERMISSION`. Final verdict: `ANGER_EXPRESSION_CLOSED_INTENT_DEFERRED`. |
| `sadness` | initiative suppression | **Audited under MR-SADNESS-INITIATIVE-SUPPRESSION-AUDIT-V1-01**: Primary consumer is `Surface initiative / expression warmth path`. Surface initiative projection verified ($\Delta\text{initiative} = -0.25 \times \Delta\text{sadness}$). Secondary warmth expression branch closed via `expressive_warmth` ($\Delta = -0.20 \times \Delta\text{sadness}$) → qualitative `warmth` guidance. **Primary function runtime gap found**: No configured or certified IntentRule consumes `Surface.initiative`; ActionPolicy and CognitiveTicker do not gate on initiative; dedicated proactive intents (`spontaneous_share`, `proactive_inquiry`, `reach_out`) use direct Dynamics roots to prevent cross-talk, so sadness produces zero suppression on proactive dispatch (`SADNESS_EFFECTIVE_INITIATIVE_CONSUMER=NONE`, `SADNESS_PRIMARY_FUNCTION_RUNTIME_GAP=FOUND`). Semantic invariant: `SADNESS_SUPPRESSES_INITIATIVE_PRESSURE != SADNESS_GRANTS_ACTION_PERMISSION`. Final verdict: `SADNESS_SURFACE_CLOSED_PRIMARY_CONSUMER_GAP_FOUND`. |
| `restlessness` | activity wake | Define activity/wake consumer separately from proactive contact. |
| `diligence_pressure` | follow-up persistence | Preserve unresolved-item relevance; never shorten reminder cooldown. |
| `fatigue` | cognitive rest pressure | Remains registered-only until sleep/daydream/offline-consolidation scheduling is explicitly designed and calibrated. |

## 7. Slow-state/personality relationship

Stable personality and slow relational state do not need to become a second list of surface emotions.

Their job is to modulate response functions such as:

```text
appraisal sensitivity
trigger threshold
fast-state gain
baseline
recovery/decay
coupling
expression suppression or release
```

The fast-state layer stays small and function-defined. Open semantic meaning remains upstream and may stay unmapped when no runtime consumer exists.


## 8. Production-closure checklist learned from Longing V1

A passing causal harness is not enough to claim production wiring. Before a consumer is marked production-closed, verify all of the following in the real composition root:

- the runtime builder actually wires every required component;
- the external Host adapter has a reachable entry path for the wake/result;
- no legacy optional injection can bypass the intended authority boundary;
- missing authority fails closed rather than skipping validation;
- restart/recovery either uses durable authoritative artifacts or explicitly fails closed;
- accepted expression is not labeled as committed delivery unless the delivery authority actually committed it;
- configuration gaps in frozen certification inputs are explicitly recorded rather than mocked.

All criteria of this checklist were satisfied during `MR-LONGING-PROACTIVE-PRODUCTION-HARDENING-V1-01`.

## 9. Sharing Urge Implementation and Boundary Choices

Task: `MR-SHARING-URGE-PROACTIVE-SHARE-V1-01`

### 9.1 Causal Architecture
- State: `agent.affect.sharing_urge`
- Intent Kind: `spontaneous_share`
- Action Type: `proactive_share` (`proactive=True`)
- Downstream seam: `WakeSignal` → `Host.consume_wake` → `begin_proactive_turn` → external Body / provider generation → `guard_proactive_prose` → transport → `commit_proactive_turn`.

### 9.2 Rationale: Why `surface_control_weights=()` was chosen over `Surface.initiative`
1. **Cross-Talk Prevention**:
   In Candidate Recipe v2, `Surface.initiative` is defined as:
   $$\text{initiative} = 0.60 \times \text{sharing\_urge} + 0.50 \times \text{curiosity} - 0.25 \times \text{sadness}$$
   `spontaneous_share` does not use `Surface.initiative` because `initiative` is a composite control of `sharing_urge + curiosity + sadness`. Using it would introduce cross-talk into dedicated `PROACTIVE_SHARE`, where changes in curiosity (epistemic exploration) or sadness (depressive suppression) would modulate sharing pressure even with constant `sharing_urge`.
2. **Preserving Candidate Recipe v2 Integrity**:
   Adding a dedicated surface control (such as `sharing_drive` or `sharing_pressure`) would alter `CANDIDATE_RECIPE_V2_DIGEST` (`4f37f46f89f6176fd5fefe0167ec7a81e341839f4fb9b98fa3cc348ddeaf9a55`) and invalidate the frozen 5-control surface manifest.
3. **Dedicated Dimension Weighting**:
   By configuring `IntentRule(kind="spontaneous_share", dimension_weights=(("agent.affect.sharing_urge", 1.0),), surface_control_weights=())`, the sharing urge directly drives intent scoring with zero coupling to other affects and zero disruption to the Surface plane.

### 9.3 Invariants Enforced
- **Anti-Spam Invariant**: `SHARING_URGE_CONTROLS_SHARE_PRESSURE != SHARING_URGE_CONTROLS_SEND_FREQUENCY`. Sharing urge increases scoring pressure for spontaneous sharing; it has zero authority to shorten, bypass, or modulate `ActionPolicy` cooldowns.
- **MR Pre-Body Ordering**: `policy_allow < wake_created < host_wake_admitted < proactive_body_entry <= proactive_expression_context < BODY_BOUNDARY`. External Body then performs provider generation. When prose returns to MR, `ExpressionGuard` determines delivery eligibility, and explicit `commit_proactive_turn` transitions Intent to `COMPLETED`.
- **Fail-Closed Prose Guard**: Provider-generated prose is validated by `ExpressionGuard` before transport; empty or banned prose triggers `abort_proactive_turn` (`HostTurnStatus.ABORTED`), moving the Intent to `SUPERSEDED` and committing zero messages.
- **Delivery Commitment**: Delivery is committed only via explicit `commit_proactive_turn` after external delivery.
- **Evidence & Isolation Bounds**: `SYNTHETIC_EVIDENCE_PATH=NONE` (MR does not invent fake user/world Evidence items); `RAW_SHARING_URGE_PROVIDER_LEAK=NONE` (MR does not expose raw `sharing_urge` state to provider-visible context).
- **Config-Gated Production Activation**: While runtime code is wired and verified, production activation is blocked by the certified manifest until calibration is completed (`SHARING_URGE_CALIBRATION_STATUS=PROVISIONAL`, `SHARING_URGE_PRODUCTION_ACTIVATION=BLOCKED_BY_CONFIG`).

## 10. Curiosity Implementation and Boundary Choices

Task: `MR-CURIOSITY-PROACTIVE-INQUIRY-V1-01`

### 10.1 Causal Architecture
- State: `agent.affect.curiosity`
- Intent Kind: `proactive_inquiry`
- Action Type: `proactive_question` (`proactive=True`)
- Downstream seam: `WakeSignal` → `Host.consume_wake` → `begin_proactive_turn` → external Body / provider generation → `guard_proactive_prose` → transport → `commit_proactive_turn`.

### 10.2 Rationale: Why `surface_control_weights=()` was chosen over `Surface.initiative`
1. **Cross-Talk Prevention**:
   In Candidate Recipe v2, `Surface.initiative` is defined as:
   $$\text{initiative} = 0.60 \times \text{sharing\_urge} + 0.50 \times \text{curiosity} - 0.25 \times \text{sadness}$$
   `proactive_inquiry` does not use `Surface.initiative` because `initiative` is a composite control of `sharing_urge + curiosity + sadness`. Using it would introduce cross-talk into dedicated `INQUIRY_EXPLORATION`, where changes in sharing urge or sadness would modulate inquiry pressure even with constant `curiosity`.
2. **Preserving Candidate Recipe v2 Integrity**:
   Adding a dedicated surface control (such as `curiosity_drive` or `inquiry_pressure`) would alter `CANDIDATE_RECIPE_V2_DIGEST` (`4f37f46f89f6176fd5fefe0167ec7a81e341839f4fb9b98fa3cc348ddeaf9a55`) and invalidate the frozen 5-control surface manifest.
3. **Dedicated Dimension Weighting**:
   By configuring `IntentRule(kind="proactive_inquiry", dimension_weights=(("agent.affect.curiosity", 1.0),), surface_control_weights=())`, curiosity directly drives intent scoring with zero coupling to other affects and zero disruption to the Surface plane.

### 10.3 Rationale: Why Autonomous Retrieval Remains Deferred (`CURIOSITY_RETRIEVAL_BRANCH=DEFERRED`, `RETRIEVAL_IS_ACTION_AUTHORITY=NO`)
1. **Retrieval Is Context, Not Authority**:
   Memory retrieval (`MemoryRetrievalService.search(...)`) provides bounded historical and factual context. It has zero authority to fabricate an Intent candidate, grant `ActionPolicyResult(ALLOW)`, or emit a `WakeSignal`.
2. **Separation of Epistemic Drive from Tool Execution**:
   In V1, curiosity manifests as conversational inquiry / follow-up questions to the user (`proactive_question`). Autonomous background retrieval / tool execution requires dedicated resource budgeting, provenance tracking, and policy permissioning that remain outside the V1 companion-first scope.
3. **Cognitive Ticker Independence**:
   `CognitiveTicker` does not invoke retrieval; tick situation has `historical_context=None`. This ensures deterministic, clock-governed ticks without external I/O or vector database dependencies.

### 10.4 Invariants Enforced
- **Anti-Spam Invariant**: `CURIOSITY_CONTROLS_INQUIRY_PRESSURE != CURIOSITY_CONTROLS_QUESTION_FREQUENCY`. Curiosity increases scoring pressure for follow-up questions; it has zero authority to shorten, bypass, or modulate `ActionPolicy` cooldowns.
- **MR Pre-Body Ordering**: `policy_allow < wake_created < host_wake_admitted < proactive_body_entry <= proactive_expression_context < BODY_BOUNDARY`. External Body then performs provider generation. When prose returns to MR, `ExpressionGuard` determines delivery eligibility, and explicit `commit_proactive_turn` transitions Intent to `COMPLETED`.
- **Fail-Closed Prose Guard**: Provider-generated prose is validated by `ExpressionGuard` before transport; empty or banned prose triggers `abort_proactive_turn` (`HostTurnStatus.ABORTED`), moving the Intent to `SUPERSEDED` and committing zero messages.
- **Delivery Commitment**: Delivery is committed only via explicit `commit_proactive_turn` after external delivery.
- **Evidence & Isolation Bounds**: `SYNTHETIC_EVIDENCE_PATH=NONE` (MR does not invent fake user/world Evidence items); `RAW_CURIOSITY_PROVIDER_LEAK=NONE` (MR does not expose raw `curiosity` state to provider-visible context).
- **Multi-Urge Competition**: When `reach_out`, `spontaneous_share`, and `proactive_inquiry` compete, exactly one `WakeSignal` is emitted per tick. Candidate scoring is strictly governed by rule weights and dimension values; no hardcoded emotional priority exists.
- **Config-Gated Production Activation**: While runtime code is wired and verified, production activation is blocked by the certified manifest until calibration is completed (`CURIOSITY_CALIBRATION_STATUS=PROVISIONAL`, `CURIOSITY_PRODUCTION_ACTIVATION=BLOCKED_BY_CONFIG`).

## 11. Anger Implementation and Boundary Choices

Task: `MR-ANGER-BOUNDARY-CONFRONTATION-AUDIT-V1-01`  
Base SHA: `a83922cc5cadf123abc113d6103552d8d5214adb`  
Verdict: `ANGER_EXPRESSION_CLOSED_INTENT_DEFERRED`

### 11.1 Causal Architecture (Expression Branch Closed)
1. **Dynamics to Surface**:
   $$\text{confrontation} = 0.70 \times \text{anger} + 0.40 \times \text{confrontation\_readiness} - 0.30 \times \text{expressive\_restraint}$$
   Secondary dampening effects:
   - $\text{contact\_seeking}$ includes $-0.20 \times \text{anger}$
   - $\text{expressive\_warmth}$ includes $-0.25 \times \text{anger}$
2. **Surface to Qualitative Guidance**:
   `confrontation` maps to qualitative guidance `directness` via Candidate Expression Map v2:
   - `low`: $[0.0, 0.33)$
   - `moderate`: $[0.33, 0.66)$
   - `high`: $[0.66, 1.0]$
3. **Provider Envelope and Isolation**:
   `DecisionContextCompiler` (in `SURFACE_V1` mode) emits items of kind `surface_guidance` with `key="directness"`. `DeterministicContextRenderer` renders `[SURFACE_GUIDANCE] - directness: <band>` and strips all raw anger dimension keys, raw floats, and persona traits. `verify_provider_information_isolation` strictly passes.

### 11.2 Intent Branch Deferral (`ANGER_INTENT_BRANCH = DEFERRED_NO_BOUNDARY_EVENT_TO_INTENT_AUTHORITY`)
1. **No Authoritative Boundary Event-to-Intent Binding**:
   Boundary assertion requires an authoritative event distinguishing "anger exists" from "boundary violation occurred". While `SemanticEventCandidate` has an open `kind: str`, the certified manifest and codebase define zero authoritative mappings from boundary events to Intent rules (`BOUNDARY_EVENT_TO_INTENT_AUTHORITY = "NONE"`). Intent capability exists structurally because confrontation is Intent-eligible, but the concrete boundary Intent branch remains deferred.
2. **Certified Manifest Boundaries**:
   `certification/d11s/inputs/runtime-config.json` defines only `respond` and `scheduled_follow_up` Intent rules, and only `text_message` ActionPolicy rules. There is no configured boundary assertion intent or action rule.
3. **No Fourth Proactive Consumer for Symmetry**:
   Mind Runtime does not invent autonomous proactive boundary assertion actions merely to mirror longing, sharing urge, or curiosity. Anger remains behavioral pressure, not action authorization.
4. **Authority Separation Invariant**:
   `ANGER_CONTROLS_BOUNDARY_PRESSURE != ANGER_GRANTS_ACTION_PERMISSION`. Anger controls directness and boundary pressure, but `ActionPolicy` exclusively owns action permission.

### 11.3 Overlap Protection
- `Surface.confrontation` is an eligible surface control under Candidate Recipe v2 (`ELIGIBLE_INTENT_SURFACE_CONTROLS`).
- However, `confrontation` shares transitive roots with other controls:
  - Shares `agent.affect.anger` and `persona.behavioral_disposition.expressive_restraint` with `contact_seeking`.
- `validate_intent_rule_surface_overlap` strictly rejects any Intent rule attempting to combine `contact_seeking` and `confrontation` (`ROOT_OVERLAP`).

## 12. Sadness Implementation and Boundary Choices

Task: `MR-SADNESS-INITIATIVE-SUPPRESSION-AUDIT-V1-01`  
Base SHA: `1edd62e4e3a97e469c4c8229229950476e86861b`  
Verdict: `SADNESS_SURFACE_CLOSED_PRIMARY_CONSUMER_GAP_FOUND`

### 12.1 Surface Initiative Branch (Mathematical Projection Verified)
$$\text{initiative} = 0.60 \times \text{sharing\_urge} + 0.50 \times \text{curiosity} - 0.25 \times \text{sadness}$$
- Monotonically decreases with rising sadness ($\Delta\text{initiative} = -0.25 \times \Delta\text{sadness}$).
- Exactly 5 surface controls preserved (`contact_seeking`, `initiative`, `confrontation`, `expressive_warmth`, `expressive_restraint`).
- Candidate Recipe v2 digest preserved: `4f37f46f89f6176fd5fefe0167ec7a81e341839f4fb9b98fa3cc348ddeaf9a55`.

### 12.2 Expression Warmth Branch (Closed)
$$\text{expressive\_warmth} = 0.55 \times \text{bias} + 0.50 \times \text{closeness} - 0.25 \times \text{anger} - 0.20 \times \text{sadness}$$
- Monotonically decreases with rising sadness ($\Delta\text{expressive\_warmth} = -0.20 \times \Delta\text{sadness}$).
- Candidate Expression Map v2 maps `expressive_warmth` to qualitative `warmth` (`low` | `moderate` | `high`).
- `DecisionContextCompiler` compiles `surface_guidance` with `key="warmth"`.
- `DeterministicContextRenderer` renders `[SURFACE_GUIDANCE] - warmth: <band>` and strictly verifies provider information isolation (zero raw sadness keys or floats).
- Expression Map v2 digest preserved: `bba6794aeda7a1755f8c79ffe5c88bd100918e6bc979ea29b5aa009e958eddf3`.

### 12.3 Effective Consumer Gap (`SADNESS_PRIMARY_FUNCTION_RUNTIME_GAP = FOUND`)
1. **Unbound Intermediate Control**: While `initiative` is declared Intent-eligible in `ELIGIBLE_INTENT_SURFACE_CONTROLS`, zero configured or certified Intent rules consume it (`INITIATIVE_INTENT_RULE = "NONE"`).
2. **ActionPolicy and Ticker Independence**: Neither `DeterministicActionPolicy` nor `CognitiveTicker` gates or modulates on `initiative` (`ACTION_POLICY_CONSUMES_INITIATIVE = "NO"`, `TICKER_CONSUMES_INITIATIVE_AS_GATE = "NO"`).
3. **Expression Map Independence**: Expression Map does not consume `initiative`.
4. **Dedicated Intent Cross-Talk Protection**:
   `spontaneous_share` and `proactive_inquiry` intentionally score from direct Dynamics roots (`agent.affect.sharing_urge` and `agent.affect.curiosity`) without consuming `initiative` to avoid cross-talk. Counterfactual tests confirm:
   - `SADNESS_SUPPRESSES_SPONTANEOUS_SHARE = NO`
   - `SADNESS_SUPPRESSES_PROACTIVE_INQUIRY = NO`
   - `SADNESS_SUPPRESSES_REACH_OUT = NO`
   - `DEDICATED_INTENT_CROSS_TALK_PROTECTION = PASS`
   - `INITIATIVE_SUPPRESSION_EFFECTIVE_ON_DEDICATED_INTENTS = NO`
5. **No Invented Global Inhibition**:
   The runtime does not invent uncoordinated ad-hoc inhibition mechanisms (ActionPolicy sadness gates, global candidate multipliers, negative WakeSignals, or synthetic "withdraw" actions). Any future primary consumer binding requires a dedicated ADR.
6. **Authority Separation Invariant**:
   `SADNESS_SUPPRESSES_INITIATIVE_PRESSURE != SADNESS_GRANTS_ACTION_PERMISSION`. Sadness is internal affect modulation; ActionPolicy exclusively owns action permissions.

## 13. Initiative Admission Gate Implementation Pattern

Task: `MR-INITIATIVE-ADMISSION-GATE-V1-01`  
ADR: `docs/adr/0030-bounded-intent-engine-initiative-admission-gate.md`  
Base SHA: `9b46d663ae9d8595357c16b2e71b12ae6ec017d8`  
Verdict: `INITIATIVE_ADMISSION_GATE_V1_READY_CONFIG_PENDING`

### 13.1 Causal Architecture
```text
domain-specific Dynamics root
→ domain Intent strength
→ independent Surface.initiative admission gate
→ admitted Intent candidate
→ existing ActionPolicy
→ existing downstream lifecycle
```

### 13.2 Key Rules and Patterns
1. **Post-Domain Evaluation Sequence**:
   - Compute and clamp domain score from single direct root (`agent.affect.sharing_urge` or `agent.affect.curiosity`).
   - If domain score < `minimum_strength`, intent is not admitted due to domain threshold; gate is not evaluated.
   - If domain score >= `minimum_strength`, evaluate independent `Surface.initiative` admission gate against `minimum_initiative`.
   - Domain score is preserved on trace regardless of gate verdict (`trace.final_strength`).
2. **Conditional Overlap Policy (`ROOT_OVERLAP_POLICY = "CONDITIONAL"`)**:
   - Independent admission gate inspection (`minimum_initiative`) is allowed.
   - Direct scoring weight (`surface_control_weights`) remains strictly forbidden and rejected.
3. **Lineage Fail-Closed**:
   - Surface unavailable → `surface_unavailable`
   - Malformed/tampered surface → `surface_invalid`
   - Stale/mismatched runtime, interaction, persona, projection, or state version → `surface_stale_or_mismatch`
4. **Downstream Isolation**:
   - Gate rejection results in `candidates=()`, suppressing downstream ActionPolicy, lifecycle admission, and WakeSignal emission.
   - ActionPolicy, Ticker, Surface recipe, expression map, and certified manifest remain untouched.
5. **Persistence Compatibility**:
   - Legacy `ruleset_ref` byte-identical when `minimum_initiative is None`.
   - Legacy SQLite JSON `surface_use` byte-identical when `surface_admission is None`.



