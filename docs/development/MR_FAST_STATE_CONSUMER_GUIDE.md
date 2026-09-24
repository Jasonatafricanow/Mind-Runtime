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
| `curiosity` | inquiry/exploration | Bind to question/retrieval Intent without turning retrieval into authority. |
| `anger` | boundary/confrontation | Audit existing Surface/Intent/expression coverage before adding anything. |
| `sadness` | initiative suppression | Audit existing initiative/expression coverage; prefer suppression over new action types. |
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
- **Fail-Closed Prose Guard**: Provider-generated prose is validated by `ExpressionGuard` before transport; empty or banned prose triggers `abort_proactive_turn` (`HostTurnStatus.ABORTED`), moving the Intent to `SUPERSEDED` and committing zero messages.
- **Delivery Commitment**: Delivery is committed only via explicit `commit_proactive_turn` after external delivery.
- **Config-Gated Production Activation**: While runtime code is wired and verified, production activation is blocked by the certified manifest until calibration is completed (`SHARING_URGE_CALIBRATION_STATUS=PROVISIONAL`, `SHARING_URGE_PRODUCTION_ACTIVATION=BLOCKED_BY_CONFIG`).

