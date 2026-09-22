# StateBar-MCP Integration into Mind Runtime

## Design rationale, authority boundaries, and experimental roadmap

**Status:** architecture/design record  
**MR canonical baseline at authoring:** `94348a3cf1c3054c3d150a1c92f2007dd8fb7d0a`  
**StateBar-MCP reference:** `Jasonatafricanow/Statebar-mcp@496dc4d8e952bb200430a1bd6f80d865241ec9ec`

---

## 1. Why StateBar exists next to MR

StateBar-MCP and Mind Runtime solve adjacent but different problems.

StateBar was built as a complete reality-state runtime. Its responsibility is to turn user/world observations into a durable, queryable account of **what is currently true** about the user or environment. It has its own observation extraction, validation, reconciliation, lifecycle, canonical state, snapshot, transport, and persistence machinery.

Mind Runtime solves the next layer:

> given some reality, what does that reality mean to this long-lived agent, and how should that meaning affect cognition, internal state, intent, and behavior?

The integration therefore does **not** treat StateBar as a personality engine, affect engine, or replacement for MR state authority.

A useful shorthand is:

```text
StateBar:
What is true in the world / user state?

MR:
What does that truth mean to this Soul?
```

This separation is the core design constraint.

---

## 2. What we explicitly did not do

The first tempting architecture was to embed StateBar wholesale inside MR.

That would have created overlapping ownership for:

- reconciliation,
- lifecycle,
- canonical current state,
- persistence,
- snapshot selection,
- context rendering,
- and transport.

That design was rejected.

MR does **not** import the full StateBar runtime as a required dependency. In particular, MR does not require:

```text
StateBar Store
StateBar SQLite schema
StateBar Reconciler
StateBar Lifecycle
SnapshotBuilder as MR authority
StateBar MCP server
StateBar REST server
StateBar CLI
StateBar daemon
```

StateBar remains a complete independent project.

The integration instead separates StateBar value into two distinct channels:

1. **external read-only reality consumption**;
2. **reuse of proven extraction/validation techniques inside an MR-native Reality/Input path**.

Those channels intentionally converge only after they enter MR's existing evidence/cognition architecture.

---

## 3. Integration model

### 3.1 External StateBar as a read-only reality source

When a complete StateBar runtime exists beside MR, StateBar remains canonical for its own user-state domain.

MR reads a bounded, identity-bound, freshness-checked snapshot and projects authorized items into the existing MR evidence/situation path.

The intended runtime path is:

```text
StateBar canonical state
    -> bounded read-only snapshot
    -> MR D3 Evidence
    -> Situation.derived_facts + Situation.evidence_refs
    -> Semantic Appraisal input
    -> DecisionContext FACT allowlist
    -> Host bounded_context
    -> Agent / Body
```

There is no new external-context authority plane.

There is no `StateBarAuthority`, no second world-state writer, and no StateBar-to-MR writeback path.

StateBar owns its canonical state. MR owns its cognition.

### 3.2 StateBar-derived techniques inside MR-native Reality/Input

StateBar also proved a useful implementation pattern for turning raw user language into structured reality candidates:

```text
raw user text
    -> fast deterministic extraction
    -> optional structured LLM extraction
    -> deterministic validation
    -> reconciliation / state
```

MR reuses the **techniques**, not the whole runtime.

The reused ideas are limited to:

- fixed-priority fast extraction / masking,
- optional structured LLM extraction,
- bounded schema parsing,
- deterministic validation,
- fail-closed handling of malformed provider output.

Those ideas are adapted into MR-native types and authority boundaries.

The result is not "StateBar running inside MR". It is:

```text
StateBar-proven extraction techniques
        ↓
MR RealityCandidate
        ↓
MR deterministic validation
        ↓
MR Observation
        ↓
MR StateEligibility
        ↓
MR FactualReconciler when eligible
```

The canonical writer remains MR's `FactualReconciler`.

---

## 4. Authority map

The integration is deliberately asymmetric.

| Concern | Authority |
| --- | --- |
| StateBar canonical user state | StateBar |
| StateBar expiry / lifecycle / reconciliation | StateBar |
| StateBar snapshot identity | StateBar |
| MR Evidence legitimacy / provenance | MR |
| MR-native Reality Observation | MR |
| MR current canonical RuntimeState | MR `FactualReconciler` |
| Situation | MR |
| Semantic meaning / appraisal | MR |
| Affect / Dynamics | MR |
| Memory | MR |
| Persona / Relationship state | MR |
| Intent / ActionPolicy | MR |
| DecisionContext | MR |
| OW observability | MR read-only telemetry over the integration |

The key rule is:

> crossing the integration boundary never transfers canonical ownership implicitly.

A StateBar fact becoming visible to MR does not automatically make it an MR canonical state, memory, belief, persona trait, or affect mutation.

---

## 5. Why StateBar does not write Affect directly

A shortcut such as:

```text
StateBar:
user.sleep = bad

        ↓

MR:
irritability += 0.3
```

was explicitly rejected.

Reality and psychological meaning are different layers.

Two different Souls can interpret the same external reality differently:

```text
same reality:
user is late

Soul A:
"disrespect"

Soul B:
"not important"

Soul C:
"coordination failure"
```

Therefore StateBar-derived reality must enter MR through Situation / Semantic Appraisal.

The allowed conceptual path is:

```text
Reality
    ↓
Situation
    ↓
Semantic Appraisal
    ↓
Soul-specific Dynamics
    ↓
Intent / behavior
```

There is no direct `StateBar -> Affect` mapping.

---

## 6. External StateBar projection contract

The read-only integration needs enough information to establish identity, freshness, and provenance without inventing a second StateBar schema.

The bounded projection is expected to retain fields equivalent to:

```text
subject_id
items[]:
  category
  key
  value
  status
  source_state_id
  last_observed_at
  valid_until
  last_observation_key

snapshot_ref
projection observed_at
```

`snapshot_ref` is projection identity only. It does not replace StateBar's own `state_id` or observation identity.

MR must not fabricate replacement fields such as generic `sleep_debt`, `stress_level`, or `workload` when those are not actual StateBar fields.

---

## 7. Identity and freshness rules

Before a StateBar item can affect MR cognition, the binding must prove that it belongs to the current user/runtime.

At minimum:

```text
StateBar subject_id
==
MR bound user identity

runtime / binding
==
current MR runtime binding

source_state_id
!= empty
```

A mismatch excludes the projection.

Freshness also matters.

A StateBar item is not "current" merely because it was recently processed. The semantic observation and lifecycle fields are authoritative for freshness.

The integration therefore distinguishes:

```text
last_observed_at
!=
updated_at
```

Typical fail-closed reasons include:

```text
STATEBAR_IDENTITY_MISMATCH
STALE
EXPIRED
EMPTY_VALUE
STATEBAR_UNAVAILABLE
```

These failures are **fail-closed for using the external fact** but **fail-soft for cognition**.

MR must still complete the turn when StateBar is unavailable.

---

## 8. Evidence projection instead of duplicate state persistence

For an accepted StateBar item, MR creates bounded Evidence with deterministic provenance.

Conceptually:

```text
source_id      = StateBar canonical source_state_id
occurred_at    = StateBar last_observed_at
received_at    = current MR receipt time
scope          = current bound user
origin_runtime = current MR runtime
payload        = bounded StateBar item + source metadata
```

The StateBar item is **not** copied into a second MR canonical state table merely because it is consumed.

Allowed persistence on the MR side is limited to the evidence/projection lineage needed for audit and cognition.

Consumption of StateBar data alone must not:

- create a `MemoryCandidate`,
- reinforce Memory,
- update Persona,
- mutate Affect,
- mutate Slow State,
- or bypass normal Appraisal.

Any psychological consequence must be produced by the normal MR cognition path.

---

## 9. Reality/Input reuse and the Observation contract

Reusing StateBar extraction techniques exposed a gap in the original MR Observation contract.

The older MR shape could represent:

```text
key
value
confidence
observed_at
```

but could not faithfully represent propositions such as:

```text
"我明天下午去写书法"
"我明天下午可能去写书法"
"我昨晚没睡好"
```

because those sentences contain semantic time and modality.

Without an explicit contract, a future plan could be silently converted into a current active state.

The MR-native Reality design therefore separates:

```text
confidence
modality
observed_at
semantic_time
effective_window
```

where:

```text
confidence
= extractor confidence that the user expressed the proposition

modality
= asserted / planned / tentative / estimated / inferred

observed_at
= original Evidence receipt time / causal provenance

semantic_time
= current / past / future / unresolved interpretation

effective_window
= deterministic absolute window when normalization is safe
```

The critical invariant is:

> Observation admission is not equivalent to current-state admission.

---

## 10. State eligibility gate

An accepted Observation is evaluated before it may enter canonical RuntimeState.

Frozen outcomes are:

```text
ELIGIBLE_CURRENT
ELIGIBLE_TERMINAL
OBSERVATION_ONLY
REJECTED
```

### ELIGIBLE_CURRENT

Requires all of:

```text
authoritative user Evidence
registered MR state dimension
modality = ASSERTED
resolved time window contains now
valid typed key / scope
```

Only then may the observation reach `FactualReconciler`.

### ELIGIBLE_TERMINAL

An explicit completion / resolution / cancellation may transition one exact legal existing target.

It cannot invent a new active state.

### OBSERVATION_ONLY

Default for:

```text
PLANNED
TENTATIVE
ESTIMATED
INFERRED
future window
unresolved time
untrusted timezone
past assertion without a valid terminal target
```

Observation-only records may be durable and replayable, but they do not mutate:

```text
RuntimeState
StateTransition
Situation
DecisionContext
Memory
Affect
Persona
Relationship
Intent / Behavior
```

### REJECTED

Used for malformed, unauthorized, cross-scope, schema-invalid, or immutable-conflicting proposals.

---

## 11. Why future plans are not auto-activated

A future plan is not a future fact.

```text
"我明天下午去写书法"
```

does not become:

```text
user.activity.calligraphy = active
```

merely because the wall clock reaches tomorrow afternoon.

The integration therefore forbids:

```text
future observation
+ time reached
= automatic canonical activation
```

Any later prospective-reality consumption or scheduling layer requires a separate contract.

This avoids turning intention into reality without new evidence.

---

## 12. Current integration topology

The combined design can be summarized as:

```text
                         StateBar-MCP
                      /               \
                     /                 \
       independent Reality Runtime     proven Reality techniques
                  |                            |
                  | read-only                  | adapted / reimplemented
                  v                            v
        External State Projection       MR-native Reality/Input
                  |                            |
                  +-------------+--------------+
                                |
                                v
                           MR Evidence
                                |
                    +-----------+-----------+
                    |                       |
                    v                       v
              MR Observation            Situation
                    |                       |
             StateEligibility               v
                    |                Semantic Appraisal
                    v                       |
            FactualReconciler               v
                    |                Affect / Dynamics
                    v                       |
              RuntimeState                  v
                    +-----------> Intent / Policy
                                            |
                                            v
                                     DecisionContext
                                            |
                                            v
                                          Body
```

This topology keeps Reality and Soul meaning separate while allowing them to interact through explicit MR contracts.

---

## 13. Experimental roadmap

The integration is validated in stages rather than by a single "it seems to work" demo.

### Phase 1 — Audit StateBar as an independent product

Goal:

> understand what StateBar already owns before deciding what MR should reuse.

Audit chain:

```text
raw observation
→ Fast Overlay
→ optional Persistent LLM
→ validation
→ reconciliation
→ lifecycle
→ canonical state
→ snapshot
→ MCP / REST / CLI
```

Expected result:

- extraction/validation techniques may be reused;
- reconciliation/lifecycle/current state remain owned by their current system;
- StateBar remains independently usable.

### Phase 2 — Authority-only integration experiment

Goal:

> prove MR can consume StateBar reality without transferring authority.

Required paths:

```text
correct identity → accepted

wrong identity → rejected

stale / expired → excluded

StateBar unavailable → MR still completes cognition

MR writeback → forbidden
```

This phase validates boundaries before usefulness.

### Phase 3 — Full lineage experiment

Goal:

> prove the same authorized reality fact survives the whole cognition chain.

Required lineage:

```text
StateBar snapshot
→ D3 Evidence
→ Situation.derived_facts / evidence_refs
→ Semantic Appraisal input
→ DecisionContext FACT
→ Host bounded_context
→ agent request boundary
```

The experiment passes on lineage and authority evidence, not on subjective prose quality.

### Phase 4 — OW observability

OW should expose a read-only causal trace for the integration.

Useful fields include:

```text
binding
snapshot_ref
subject_id
freshness
used keys
excluded keys + reason
evidence_refs
phase
```

Typical phases:

```text
snapshot
situation
appraisal
decision_context
host_bounded_context
```

Missing or rejected data must remain visible as UNKNOWN / excluded, not silently disappear.

### Phase 5 — Isolated production-shaped A/B

Use two isolated arms:

```text
Arm A:
MR without StateBar projection

Arm B:
MR + read-only StateBar projection
```

Isolation requirements:

- distinct MR persistence namespaces,
- distinct StateBar transport/database namespaces where applicable,
- distinct telemetry namespaces,
- distinct interaction IDs,
- distinct idempotency domains.

Arm B must show the same authorized StateBar fact at every permitted pipeline point.

Arm A must show no StateBar-derived Evidence or FACT.

The experiment is not required to produce a dramatic literary difference in the final response. The required result is a traceable causal difference.

### Phase 6 — RED boundary tests

Before production implementation, lock down failure semantics with RED tests covering at least:

1. real StateBar-shaped snapshot reaches MR Evidence and Situation;
2. correct identity binding accepted;
3. wrong identity rejected while cognition continues;
4. allowlisted field reaches Situation;
5. non-allowlisted field cannot reach provider-visible FACT context;
6. unavailable StateBar fails soft;
7. stale/expired state is not treated as current;
8. Semantic Appraisal can see the bounded fact;
9. DecisionContext only includes authorized FACT;
10. Host receives bounded context, never raw StateBar JSON;
11. MR performs no StateBar writeback;
12. StateBar use alone does not create or reinforce MR Memory.

### Phase 7 — Reality semantic stress tests

The StateBar-derived Reality/Input path is then tested against propositions whose semantics are easy to corrupt:

```text
current
past
future
planned
tentative
unresolved time
cancellation
retry / replay
```

Examples:

```text
"我现在胃疼"
→ ASSERTED + current
→ eligible current state

"我明天下午去写书法"
→ PLANNED + future
→ durable Observation only

"我明天下午可能去写书法"
→ TENTATIVE + future
→ durable Observation only

"我不去了"
→ cancellation only with an exact valid target
```

This phase verifies that "understood by the extractor" never silently means "true right now".

---

## 14. Success criteria

The integration is considered healthy only if all of the following remain true:

```text
StateBar still works independently

MR can run without StateBar

no StateBar writeback

no duplicate canonical state authority

no second lifecycle/reconciliation engine inside MR

no direct StateBar -> Affect shortcut

identity/freshness failures are explicit

provider failures are fail-soft for cognition

prospective reality never masquerades as current fact

replay preserves original provenance

OW can trace the same fact across the full lineage

full-suite regression remains clean against canonical main
```

---

## 15. Design consequence

The main architectural consequence is broader than StateBar itself.

StateBar demonstrated a useful pattern:

```text
open semantic understanding
→ bounded structured proposal
→ deterministic runtime validation
→ explicit authority transition
```

MR adopts that pattern without adopting StateBar's entire runtime.

That same principle now appears consistently across MR:

```text
Reality:
model/extractor proposes
MR decides what becomes canonical reality

Appraisal:
model understands meaning
MR decides how that meaning is accepted/projected

Memory:
candidate extraction is not memory authority

Soul dynamics:
semantic meaning does not directly mutate state without runtime rules
```

The integration therefore is not primarily a transport integration.

It is an authority-preserving bridge between **Reality** and **Cognition**.

---

## 16. Summary

StateBar-MCP was not merged into Mind Runtime as a second state machine.

Instead:

1. StateBar remains a complete independent Reality Runtime.
2. Its canonical state can be consumed by MR through a bounded read-only Evidence projection.
3. Its mature extraction/validation techniques are selectively adapted into an MR-native Reality/Input layer.
4. MR keeps ownership of Observation semantics, state eligibility, canonical state, appraisal, affect, memory, persona, intent, and behavior.
5. StateBar facts never mutate Affect or Memory directly.
6. Future/planned/tentative reality is preserved as Observation without being promoted to current fact.
7. Integration is validated through identity/freshness gates, full lineage tracing, OW observability, isolated A/B experiments, and RED boundary tests.

The intended end state is:

> **StateBar describes reality; MR interprets what that reality means to a Soul.**

That boundary is the reason the two systems can be integrated without collapsing into one another.
