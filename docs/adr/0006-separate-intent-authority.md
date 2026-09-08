# ADR-0006: Separate Intent authority from emotional transition

- **Date:** 2026-08-22
- **Status:** Accepted for D9 implementation

## Problem

ADR-0004 defines the compressed runtime as `Context -> EmotionalTransition ->
Projected Internal State -> Intent -> ActionPolicy`. D7R kept a walking-skeleton
shortcut in which `EmotionalTransitionResult` also contains a fixed `respond`
Intent. D8 correctly made the emotional transition authoritative for affect,
but the shortcut now lets one component own both internal-state calculation and
the first behavioral candidate.

D9 must add multiple scored candidates, durable scheduling, policy fallback,
and restart recovery. Extending the D8 port to perform those jobs would recreate
the combined Dynamics/Motivation/Policy authority that ADR-0004 removed.

## Previous Assumption

The fixed candidate was useful while D7R and D8 proved one canonical pipeline.
It allowed the existing D2S Agent, guard, receipt, projection, and commit path to
remain executable before a real Intent engine existed.

## New Evidence

- G4 requires high contact desire while active conversation blocks action.
- G5 requires a denied photo candidate to fall back to an allowed text candidate.
- G24 requires a due Intent to survive restart and wake for reconsideration
  without executing.
- The user requires deterministic behavior independent of base-model tendency
  and context quality.
- `due_at`, lifecycle history, and ActionPolicy have no coherent owner if the
  emotional transition also selects behavior.

## Decision

`EmotionalTransitionResult` no longer returns cognitive Intents. It returns:

```text
ProjectedMindState
+ accepted typed semantic events
+ AssessmentTrace
```

An accepted event is a confidence-gated `SemanticEventCandidate` already
admitted by D8. Rejected or ambiguous candidates remain trace-only and cannot
drive Intent scoring.

D9 introduces one deterministic `IntentEngine` after projection. It consumes
the projected vector, factual Context, accepted typed events, an injected Clock,
and configuration-owned `IntentRule` records. It emits an ordered candidate set
and a score trace. The Kernel never branches on `persona_id`; different Agents
adapt through Persona dimensions and rule configuration.

The runtime persists admitted Intent versions and append-only lifecycle
transitions. `due_at` wakes an Intent only for reconsideration. A Scheduler
never calls an Agent, creates a receipt, or grants permission.

ActionPolicy is the only action-permission authority. It evaluates candidates
in deterministic score order against factual Context, current effective facts,
resource availability, schedule, and configuration-owned limits. Temporary
constraints yield `DEFER`; hard prohibition yields `DENY`; the first `ALLOW`
candidate becomes the selected action. Lower candidates are superseded only
after a candidate is allowed.

Internal affect and external action remain separate. A denied or deferred
action does not call the expression provider and creates no delivery receipt,
but it does not erase or falsify the projected internal-state transition.

## Preserved Boundaries

- LLMs do not score, schedule, select, permit, or transition Intent.
- Projected State remains non-canonical until D5 commit.
- Situation remains factual and contains no `allowed`, `blocked`, or `ready`
  verdict.
- Policy consumes Effective State or factual Context, never raw State status.
- ExpressionGuard remains separate and cannot override Policy.
- Actions that leave the Runtime retain D5 receipt/reconcile semantics.
- Native Memory, Persona learning, and distributed scheduling remain out of
  scope.

## Rejected Alternatives

### Keep Intent generation inside EmotionalTransition

Rejected because one component would own affect, behavioral desire, and
scheduling inputs. It also makes adding a behavior rule risk changing emotional
state computation.

### Score concrete actions directly and omit durable Intent

Rejected because future follow-up, restart recovery, expiry, reconsideration,
and causal history become implicit scheduler state rather than explicit domain
records.

### Let an LLM choose or rank Intent

Rejected because model swaps and context pollution would change the runtime's
behavioral lower bound. D9 must remain operational without any LLM.

### Let Scheduler execute when `due_at` is reached

Rejected because the current Context, internal state, expiry, resources, and
Policy may differ from those present when the Intent was created.

## Affected Contracts

- `EmotionalTransitionResult`: remove `intents`; add accepted semantic events.
- Add `IntentEngineInput`, `IntentEngineResult`, and score-trace contracts.
- Add append-only `IntentTransition` and scheduler wake contracts.
- Extend `ActionPolicyResult` invariants so decision and permission cannot
  contradict each other.
- Add `IntentEnginePort`, `IntentBackend`, and Scheduler/Policy inputs.
- Update `TurnProjection` Intent references without changing D5 state commit
  authority.

## Migration

The D2S walking skeleton receives a `StubIntentEngine` that emits the same
immediate `respond` candidate, preserving existing integration tests. The D8
engine port returns its accepted semantic event instead of the placeholder
Intent. No production Intent data exists, so no data rewrite is required.

The D9 SQLite backend adds only `intents` and `intent_transitions`; it does not
alter the D3-D5 factual/state tables. Rollback removes the D9 composition and
restores the stub at the port boundary without rewriting Canonical State.

## Acceptance Tests

- Removing or bypassing `IntentEngine` breaks the canonical pipeline tests.
- Same projected vector, events, Context, rules, and Clock produce identical
  candidate ordering and scores.
- Multiple candidates allow policy fallback without an LLM.
- Invalid lifecycle transitions and terminal rewrites fail closed.
- SQLite restart restores the latest Intent version and complete transition
  history.
- A due Intent wakes exactly once for reconsideration and never dispatches.
- Denied/deferred candidates create no Agent call or delivery receipt.
- Allowed external actions preserve existing receipt/reconcile behavior.
- G4, G5, G14, G16a, and G24 are green; later-gate Goldens remain strict xfail.

