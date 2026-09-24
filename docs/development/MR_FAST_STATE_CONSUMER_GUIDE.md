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

Completed causal closure: `MR-LONGING-PROACTIVE-BODY-ENTRY-V1-01`

```text
agent.affect.longing
→ Surface.contact_seeking
→ proactive Intent
→ ActionPolicy
→ WakeSignal
→ Host.consume_wake(...) (admission & lineage validation)
→ Host.run_proactive_turn(...) (Body entry)
→ ProactiveExpressionPreparer.prepare_context(...) (DecisionContext)
→ ProactiveExpressionPreparer.realize_after_wake(...) (provider)
→ ExpressionGuard
→ delivery boundary
```

Key causal rules verified:
1. `provider_call_count == 0` prior to Host wake admission.
2. CognitiveTicker does NOT invoke provider realization.
3. Host rejects invalid wake without invoking provider.
4. Host exactly-once idempotency: duplicate wake returns `ALREADY_PROCESSED` with 0 additional provider calls; conflicting payload fails closed.
5. Guard rejection prevents external delivery without creating fake Evidence or uncommitted affect mutation.

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
| `longing` | proactive contact | **Closed**: Wake-to-Body wiring, Host lineage validation, and execution ordering closed in MR-LONGING-PROACTIVE-BODY-ENTRY-V1-01. Calibration remains provisional (`PROACTIVE_CONTACT_CALIBRATION_GAP=FOUND`). |
| `sharing_urge` | proactive share | Define one share Intent/action consumer after longing wake boundary is closed. |
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
