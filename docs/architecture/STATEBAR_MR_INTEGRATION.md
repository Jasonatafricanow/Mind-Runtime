# Statebar integration notes

This document records the intended integration between Statebar and Mind Runtime.

Statebar and MR remain separate systems:

- Statebar maintains short-lived/current user state from observations.
- MR consumes selected external facts as input to its existing evidence and decision pipeline.
- MR does not write back to Statebar.
- Importing a Statebar fact does not directly mutate MR affect, memory, persona, or long-term state.

## 1. External Statebar path

When a Statebar service is available, MR may read a bounded snapshot.

```text
Statebar current state
    -> bounded snapshot
    -> identity/freshness checks
    -> MR Evidence
    -> Situation
    -> appraisal / decision context
    -> host
```

MR does not copy the whole Statebar database or reconciliation engine.

The integration needs only enough data to identify and validate each item:

```text
subject_id
source_state_id
category
key
value
status
last_observed_at
valid_until
snapshot_ref
```

The exact transport may be MCP, REST, or an adapter. Transport choice must not change the validation rules below.

## 2. Identity and freshness

A Statebar item is usable only when it belongs to the currently bound user/runtime and is still current.

Minimum checks:

```text
snapshot subject == MR bound user
source_state_id is present
item is not expired
item is not stale for its state type
value is present and schema-valid
```

Useful rejection reasons include:

```text
IDENTITY_MISMATCH
STALE
EXPIRED
EMPTY_VALUE
STATEBAR_UNAVAILABLE
```

A rejected or unavailable Statebar item is omitted from MR input. It must not fail the whole turn.

`last_observed_at` and processing/update time are not interchangeable. Freshness should be based on the semantic observation/lifecycle data supplied by Statebar, not merely on when MR received the snapshot.

## 3. Projection into MR

Accepted Statebar items enter MR as normal Evidence with explicit source metadata.

Conceptually:

```text
source_id   = Statebar source_state_id
occurred_at = Statebar last_observed_at
received_at = MR receipt time
payload     = bounded Statebar item
scope       = current bound user
```

The projected item then follows the existing MR path.

It must not create a second write path for:

- RuntimeState;
- Memory;
- affect/dynamics;
- persona/relationship state;
- intent/action state.

If a Statebar fact eventually affects those systems, it should happen through existing MR processing rather than a special Statebar shortcut.

For example, there is no direct mapping such as:

```text
Statebar: sleep=bad
    -> affect.irritability += 0.3
```

The fact is first provided to the normal situation/appraisal path.

## 4. Reusing Statebar extraction code

A separate experiment may reuse Statebar's extraction/validation techniques inside MR without embedding the Statebar runtime.

The useful pattern is:

```text
raw user text
    -> deterministic extraction
    -> optional structured model extraction
    -> schema validation
    -> proposed observation
    -> deterministic state eligibility check
```

Only the extraction/validation technique is reused. Statebar's persistence, lifecycle, reconciler, MCP server, REST server, and CLI remain outside MR.

## 5. Observation time and modality

The MR observation path needs to keep these fields separate:

```text
confidence
modality
observed_at
semantic_time
effective_window
```

They answer different questions:

- `confidence`: confidence that the proposition was extracted correctly;
- `modality`: asserted, planned, tentative, estimated, inferred;
- `observed_at`: source/evidence time;
- `semantic_time`: current, past, future, unresolved;
- `effective_window`: normalized absolute window when it can be resolved safely.

A future or tentative statement is not current state.

Examples:

```text
"我现在胃疼"
-> asserted + current
-> may be eligible for current state

"我明天下午去写书法"
-> planned + future
-> observation only

"我明天下午可能去写书法"
-> tentative + future
-> observation only
```

Reaching the future timestamp does not automatically activate a plan. New state requires an explicit rule and appropriate evidence.

## 6. State eligibility

Before an MR-native observation reaches `FactualReconciler`, it should be classified into one of four outcomes:

```text
ELIGIBLE_CURRENT
ELIGIBLE_TERMINAL
OBSERVATION_ONLY
REJECTED
```

### ELIGIBLE_CURRENT

Typical requirements:

- user-authored/authorized evidence;
- registered state key/dimension;
- asserted modality;
- resolved window that contains now;
- valid type and scope.

### ELIGIBLE_TERMINAL

Used for an explicit completion, cancellation, or resolution of an existing target.

A terminal observation may close a matching state but must not invent a new active state.

### OBSERVATION_ONLY

Used for plans, tentative statements, estimates, inferred values, future windows, unresolved time, or other observations that should remain durable without changing current state.

### REJECTED

Used for malformed, unauthorized, cross-scope, schema-invalid, or conflicting input.

## 7. Persistence rules

Reading Statebar data should persist only what MR needs for traceability and normal processing.

The integration must not:

- mirror all Statebar state into another MR state table;
- create Memory solely because a Statebar field was read;
- reinforce Memory solely because the same snapshot was read again;
- update affect/persona/relationship state directly;
- treat a snapshot refresh as new user evidence.

Source IDs and snapshot IDs should remain available for debugging/replay.

## 8. Failure behavior

Statebar is optional input.

Expected behavior:

```text
correct identity + current item -> include
wrong identity                 -> exclude
stale/expired item             -> exclude
Statebar unavailable           -> continue MR turn without it
malformed payload              -> exclude / record reason
writeback attempt              -> not supported
```

No fallback should fabricate replacement facts when Statebar data is unavailable.

## 9. Observation Window

The Observation Window may expose the integration trace as read-only telemetry.

Useful fields:

```text
snapshot_ref
subject_id
binding/runtime
item key
source_state_id
freshness result
include/exclude reason
MR evidence ref
pipeline stage
```

Missing/rejected data should remain visible as excluded/unknown rather than disappearing silently.

## 10. Test plan

### Boundary tests

At minimum:

1. a valid Statebar item reaches MR Evidence;
2. wrong subject identity is rejected;
3. stale/expired state is rejected;
4. Statebar unavailability does not fail the turn;
5. non-allowlisted data does not reach provider-visible context;
6. host receives bounded MR context, not raw Statebar JSON;
7. no Statebar writeback occurs;
8. reading Statebar does not by itself create/reinforce MR Memory.

### Time/modality tests

Cover:

- current assertion;
- past assertion;
- future plan;
- tentative future plan;
- unresolved time;
- cancellation/completion;
- replay/retry.

The main regression to prevent is:

```text
successfully extracted proposition
!=
current canonical state
```

### End-to-end lineage test

For one accepted Statebar fact, verify the same source identity through:

```text
Statebar snapshot
-> MR Evidence
-> Situation
-> appraisal input
-> DecisionContext
-> host bounded context
```

The test should assert IDs/fields at each step rather than judging response prose.

### A/B integration test

Use isolated persistence/telemetry namespaces:

```text
A: MR without Statebar input
B: MR with read-only Statebar input
```

Arm B should contain the expected Statebar-derived Evidence and downstream trace. Arm A should not.

## 11. Non-goals

This integration does not:

- merge the Statebar runtime into MR;
- make Statebar required for MR startup;
- add a second canonical writer for MR state;
- create automatic future-plan activation;
- map Statebar fields directly to affect/persona/memory;
- infer missing external facts when Statebar is unavailable.

The implementation should stay small enough that the boundary can be understood from code and tests without a separate terminology layer.