# MR-REALITY-OBSERVATION-CONTRACT-01

## Temporal / Modality Semantics Contract

**Status:** `CONTRACT_ACCEPTABLE_FOR_IMPLEMENTATION`

**Decision:** `C1 — Extend Observation + observation-only prospective storage`

**Implementation status:** architecture freeze only. This document does not
modify `src/`, `tests/`, SQLite migrations, or the StateBar reuse branch.

**Scope:** define how Mind Runtime represents an evidence-backed proposition
with modality, semantic time, confidence, and an optional effective window.
Observation admission is not equivalent to current-state admission.

**StateBar reference:** `Jasonatafricanow/Statebar-mcp` at
`496dc4d8e952bb200430a1bd6f80d865241ec9ec` is a semantic reference only. It
is not an MR authority, runtime dependency, or persistence dependency.

## 1. Frozen authority boundary

```text
user Evidence
  -> RealityCandidate / proposal
  -> deterministic validation and temporal normalization
  -> accepted MR Observation
  -> StateEligibility
  -> FactualReconciler only when eligible
  -> RuntimeState / StateTransition
  -> EffectiveStateResolver
  -> Situation / DecisionContext
```

The following remain frozen:

- LLM output is never canonical mutation authority.
- `FactualReconciler` remains the only canonical state writer.
- `RuntimeState.status` remains lifecycle, not modality.
- Future observations do not automatically activate into canonical state.
- No StateBar Store, SQLite schema, SnapshotBuilder, MCP, REST, CLI, daemon,
  or StateBar lifecycle/reconciliation authority is introduced.
- Memory, Semantic Appraisal, Affect, Persona, Relationship state,
  DecisionContext, and Intent/Behavior retain their existing ownership.

## 2. Current MR contract evidence

| Object | Expresses | Does not express | Created / persisted | Consumed by | Authority |
|---|---|---|---|---|---|
| `Evidence` | Durable source input, scope, source authority, `occurred_at`, `received_at`, payload | Interpreted modality, canonical state, lifecycle | Source adapter / host; fact backend | Admission, provenance, audit | Original source; user Reality requires user message |
| `Observation` | Immutable evidence-backed interpretation, key/value, numeric confidence, causal `observed_at`, evidence refs | Semantic time, modality, validity window, lifecycle, currentness | `FactIngestService`; observations table | Eligibility, reconciliation, validation | Evidence-backed interpretation, not state |
| Fact admission | Atomic/idempotent Evidence + Observation pairing and `NEW`/`REPAIRED`/`REPLAY` | State transition and currentness | `FactIngestService` + fact backend | Orchestrator and observers | Durable fact-plane admission |
| `StateIntent` | Typed dimension/value input to D4 reconciliation | Modality, semantic time, future scheduling | Observation interpreter | `FactualReconciler` | Reconciler and state registry |
| `RuntimeState` | Canonical dimension, value, lifecycle, validity and relevance | Observation modality; future plan semantics | Reconciler; state backend | Effective resolver, Situation | MR canonical state |
| `StateTransition` | Committed from/to canonical states | Source proposition modality and natural-language time | Reconciler/orchestrator; state backend | History and audit | MR canonical transition history |
| `EffectiveStateResolver` | Read-only effective state view and upper-bound expiry | Future activation, observation-only projections | Pure read | Situation and state consumers | Single effective-state read gate |
| `Situation` | Deterministic interpretation of effective state + interaction + clock | Raw/prospective Observation semantics | `SituationBuilder`; not a fact store | DecisionContext and cognition | Derived projection |
| `PendingWorkingOverlay` | Pre-admission, in-memory working evidence | Durable prospective observation or modality authority | Orchestrator memory; non-durable | Optional compiler external items | Explicitly non-canonical |
| `DecisionContext` | Bounded current-turn cognition context | Raw prospective observations by default | Context compiler | Agent/expression surface | Bounded projection |

Evidence references:

- `Evidence` separates `occurred_at` and `received_at`:
  `src/mind_runtime/contracts/evidence.py:16-55`.
- Current `Observation` has no temporal/modality fields:
  `src/mind_runtime/contracts/observation.py:17-50`.
- Fact admission preserves original causal identity and received time:
  `src/mind_runtime/facts/service.py:299-387`.
- Current observation persistence has no semantic columns:
  `src/mind_runtime/facts/persistence.py:102-125` and `223-239`.
- `StateIntent` has no modality or semantic window:
  `src/mind_runtime/state/reconciler.py:54-105`.
- Reconciler creates current-like state with `valid_from=now`:
  `src/mind_runtime/state/reconciler.py:259-300`.
- Resolver checks `valid_until`, but not `now < valid_from`:
  `src/mind_runtime/state/resolver.py:75-89`.
- Situation consumes Effective State, Interaction, and clock:
  `src/mind_runtime/situation/builder.py:48-117`.
- Pending evidence is non-canonical and non-durable:
  `src/mind_runtime/memory/pending.py:1-23` and `57-72`.
- DecisionContext is a bounded compiled view:
  `src/mind_runtime/contracts/decision.py:15-42`.

## 3. Observation contract

The immutable Observation gains exactly three semantic components:

```text
Observation
  existing identity/provenance, key, value, confidence, observed_at
  modality: ObservationModality
  semantic_time: SemanticTime
  effective_window: EffectiveWindow | null
```

These are dedicated typed fields. They must not be encoded in `value`, key
spelling, free-form metadata, or a downstream convention.

### 3.1 Confidence

`confidence` remains extractor confidence in `[0, 1]`:

> How confident is the extractor that the user expressed this proposition?

It does not describe whether the proposition is asserted, planned, tentative,
estimated, or inferred. `confidence=0.99` and `modality=TENTATIVE` is valid.

### 3.2 observed_at

`Observation.observed_at` is always the original durable
`Evidence.received_at`. It is causal provenance, not the time discussed by the
user. Retry and repair turns cannot replace it with retry time.

### 3.3 modality

The finite MR-native vocabulary is:

```text
ASSERTED | PLANNED | TENTATIVE | ESTIMATED | INFERRED
```

| Modality | Meaning | State eligibility |
|---|---|---|
| `ASSERTED` | User presents a factual claim, including an explicit past claim | Current only when its resolved window contains now; terminal operations require a target |
| `PLANNED` | User states an intended future action/event | Observation-only |
| `TENTATIVE` | User marks the proposition possible, uncertain, or conditional | Observation-only |
| `ESTIMATED` | User marks the value/proposition approximate or estimated | Observation-only by default |
| `INFERRED` | Extractor derives beyond literal assertion | Observation-only |

Upstream `confirmed` normalizes to `ASSERTED`; it is not a second stored
value. `PLANNED` and `TENTATIVE` are mutually exclusive. `cancelled`,
`completed`, and `resolved` are not modalities: they are target operations or
existing lifecycle semantics.

## 4. Semantic time

`semantic_time` is a small typed interpretation, not raw natural-language
text:

```text
SemanticTime:
  relation: CURRENT | PAST | FUTURE | UNRESOLVED
  precision: INSTANT | DAY | DAYPART | RANGE | UNRESOLVED
  daypart: MORNING | AFTERNOON | EVENING | NIGHT | null
```

Rules:

- `daypart` is present only for `DAYPART`.
- `UNRESOLVED` means no absolute time may be invented.
- `tomorrow afternoon` is `FUTURE + DAYPART + AFTERNOON`.
- `last night` is `PAST + DAYPART + NIGHT`.
- `next Tuesday` is `FUTURE + DAY`; its actual UTC bounds are in the window.
- `just now` may be `PAST + INSTANT`; without a deterministic bounded range
  it has no effective window.

The raw expression is not duplicated into Observation. It remains in the
authoritative Evidence payload, so equivalent wording does not create a new
semantic identity merely because its string differs.

## 5. Effective window

When temporal normalization is possible, `effective_window` is:

```text
EffectiveWindow:
  kind: POINT | INTERVAL | OPEN_INTERVAL
  start_at: aware UTC datetime
  end_at: aware UTC datetime | null
```

Rules:

- `INTERVAL` is half-open `[start_at, end_at)`.
- `INTERVAL` requires `start_at < end_at`.
- `POINT` is the single instant `start_at`; it is not current-state proof.
- `OPEN_INTERVAL` is `[start_at, +infinity)` and is for explicitly ongoing
  current propositions.
- All stored bounds are aware UTC datetimes.
- A null window means unresolved normalization, not `now`.

Examples:

| Meaning | SemanticTime | Window |
|---|---|---|
| `现在胃疼` | current/instant | open interval beginning at anchor |
| `今天` | current/day | local calendar-day interval converted to UTC |
| `明天下午` | future/daypart/afternoon | tomorrow's local-afternoon interval in UTC |
| `昨晚` | past/daypart/night | prior local-night interval in UTC |
| `过阵子` | future/range | null unless a bounded range is deterministic |

## 6. Temporal normalization authority

Relative time is anchored to the original durable Evidence:

```text
anchor = original Evidence.received_at
```

It is not anchored to processing time, retry time, or a newly created
Interaction.

Timezone authority is ordered as follows:

1. trusted user/runtime binding timezone;
2. trusted host-provided timezone attached to the Interaction;
3. explicit source timezone only when marked trusted by the source adapter.

An LLM-produced timezone is not trusted authority. UTC is the storage format,
not an implicit user-reality timezone. If no trusted timezone exists for a
timezone-dependent expression, the Observation may persist with a null window
but is not current-state eligible.

For the same semantic proposal, original `received_at`, and trusted timezone,
normalization must return the same typed result. The LLM may propose; MR
deterministic validation accepts the result.

## 7. State eligibility gate

The frozen outcomes are:

```text
ELIGIBLE_CURRENT | ELIGIBLE_TERMINAL | OBSERVATION_ONLY | REJECTED
```

### 7.1 ELIGIBLE_CURRENT

All conditions are required:

1. admitted user Evidence;
2. registered/allowed MR state dimension and scope;
3. modality `ASSERTED`;
4. resolved window containing the current instant;
5. no unresolved future/past meaning;
6. valid typed state key and definition.

Only then may the observation become a value update for
`FactualReconciler`. The reconciler owns state creation, supersession,
validity, and persistence.

### 7.2 ELIGIBLE_TERMINAL

An explicit `completed`, `resolved`, or `cancelled` operation may enter the
reconciler only when its typed key identifies one legal existing target state.
A terminal operation without a valid target cannot create a new active state.

### 7.3 OBSERVATION_ONLY

The Observation is durable and replayable but performs no canonical state
write. This is the default for `PLANNED`, `TENTATIVE`, `ESTIMATED`,
`INFERRED`, future windows, unresolved time/timezone, unsupported dimensions,
and past assertions without a valid terminal target.

Observation-only records do not mutate RuntimeState, StateTransition,
Situation, DecisionContext, Memory, Affect, Persona, Relationship state, or
Intent/Behavior.

### 7.4 REJECTED

Malformed, unauthorized, cross-scope, schema-invalid, or immutable-conflicting
proposals are rejected. Existing factual audit behavior for source Evidence
is unchanged.

## 8. Prospective downstream policy

The selected policy is **P0 — Persist only**:

```text
future/planned/tentative Observation
  -> durable fact persistence
  -> no EffectiveState entry
  -> no Situation input
  -> no DecisionContext item
```

`PendingWorkingOverlay` cannot substitute for this because it is pre-admission,
in-memory, and intentionally lost on restart.

P1/C2, a separate prospective Situation surface, is `DEFERRED` because it
expands the cognition contract without evidence required by this task. P2,
converting prospective observations into generic facts/context, is `REJECTED`
because it collapses plans into current reality. C3, a separate
`ProspectiveObservation` type, is `REJECTED for this freeze` as duplicate
durable identity/replay machinery without demonstrated need.

## 9. Past, completed, and cancellation semantics

Past is a temporal relation, not automatic currentness:

- past assertions persist as Observation;
- they do not become indefinite `ACTIVE` state;
- explicit terminal operations may transition only an exact existing target;
- terminal state answers what happened and is not a current-like state;
- `relevant_until` remains cancellation-context relevance, not generic event
  or prospective-observation relevance;
- unnormalizable past time remains Observation-only.

Cancellation is not modality. The accepted path is:

```text
explicit cancellation
  -> exact target dimension resolution
  -> existing eligible target required
  -> existing CANCELLED lifecycle through FactualReconciler
```

`我不去了` without an exact target remains Observation-only. It cannot cancel
the latest or all plans by fuzzy inference.

## 10. Persistence contract

The future implementation adds dedicated additive columns to `observations`:

```text
modality                  TEXT NOT NULL
semantic_relation         TEXT NOT NULL
semantic_precision        TEXT NOT NULL
semantic_daypart          TEXT NOT NULL DEFAULT ''
effective_window_kind     TEXT NOT NULL
effective_start_at        TEXT NULL
effective_end_at          TEXT NULL
```

Enum values are stable lowercase MR tokens. Bounds are aware UTC timestamps.
`unresolved` requires null bounds; `point` requires start and null end;
`interval` requires both bounds with start before end; `open_interval` requires
start and null end. Daypart is empty unless precision is `daypart`.

Migration is additive:

1. add columns without removing or renaming existing columns;
2. old rows default to `asserted`, `unresolved` relation/precision,
   empty daypart, unresolved window, and null bounds;
3. existing canonical states/transitions are not retroactively reevaluated;
4. readers remain able to load old rows;
5. unresolved legacy time is not used as new current-state proof.

No StateBar database or migration is involved.

## 11. Replay and identity

Exactly-once has three layers.

### 11.1 Provenance identity

The accepted Observation is bound to:

```text
(scope, original Evidence.id, original causal interaction id)
```

Reality Observation IDs remain derived from original Evidence identity and a
deterministic candidate ordinal/fingerprint. Retry interaction identity cannot
replace original causal identity.

### 11.2 Semantic identity

The accepted semantic fingerprint includes:

```text
key, value, confidence, modality, semantic_relation, semantic_precision,
semantic_daypart, effective_window_kind, effective_start_at,
effective_end_at, evidence_refs
```

For the same Evidence/Observation identity, a changed modality, semantic time,
effective window, confidence, or other immutable field is a conflict, not a
replay. A different Evidence ID is a new proposition even if normalized meaning
is equal.

At the persistence boundary, replay therefore requires byte-equivalence of all
accepted canonical Observation fields listed above. Raw wording is excluded
from those bytes because it remains in Evidence; wording-only variation cannot
change the accepted Observation bytes or create a duplicate.

### 11.3 Raw-expression identity

Raw wording remains in Evidence and is excluded from the semantic fingerprint.
Equivalent wording therefore does not create duplicates solely due to string
differences. Replay returns the stored authoritative Observation without
provider calls or mutation.

## 12. Provenance and mixed-source rules

- `Observation.observed_at = original Evidence.received_at`.
- Original Evidence ID, causal interaction, source type, and subject scope are
  retained.
- Assistant-only output cannot create user Reality Observation.
- Assistant text is never silently merged into user text for extraction.
- Any future mixed-context caller must provide separately labeled source
  segments; assistant segments remain non-authoritative.

The current MR source path accepts one Evidence and checks source authority. It
does not authorize a mixed-context extractor.

## 13. Resolver boundary and `valid_from`

The current resolver not checking `now < valid_from` is recorded as **C: the
accepted MR state contract has never used `valid_from` for future activation**.
This is not repaired here because future observations do not enter the
StateBackend and no future state is created. `valid_from` remains canonical
state historical start; `valid_until` retains existing upper-bound behavior.

Automatic activation is forbidden:

```text
wall clock reaches effective_window != automatic canonical Reality State
```

Reminders, prospective consumption, and time-triggered activation require
separate tasks:

- `MR-PROSPECTIVE-REALITY-CONSUMPTION-01`
- `MR-TEMPORAL-RESOLUTION-01`

## 14. Canonical sleep key

Existing Situation logic reads `user.sleep.phase` at
`src/mind_runtime/situation/derived.py:22-25`, while the prototype used
`user.sleep`. The frozen canonical key is:

```text
user.sleep.phase
```

`user.sleep` is not an accepted alias. This mismatch is a follow-up hardening
item and is not patched in this architecture task.

## 15. Mandatory scenario matrix

| Input | Modality | Semantic time | Effective window | Persisted | Canonical result |
|---|---|---|---|---|---|
| `我刚睡醒` | `ASSERTED` | current/instant | resolved open interval | YES | `ELIGIBLE_CURRENT` with `user.sleep.phase` |
| `我现在胃疼` | `ASSERTED` | current/instant | resolved window containing now | YES | `ELIGIBLE_CURRENT` |
| `我刚才游泳了` | `ASSERTED` | past/instant or past range | deterministic if bounded, otherwise null | YES | terminal completion only with valid target; otherwise Observation-only |
| `我昨晚没睡好` | `ASSERTED` | past/daypart | prior local-night range when timezone trusted | YES | Observation-only unless valid terminal target exists |
| `我明天下午去写书法` | `PLANNED` | future/daypart | tomorrow local-afternoon range | YES | Observation-only; never current |
| `我明天下午可能去写书法` | `TENTATIVE` | future/daypart | tomorrow local-afternoon range | YES | Observation-only; never current |
| `我可能换工作` | `TENTATIVE` | unresolved future/range | null | YES | Observation-only |
| `我不去了` | asserted operation | current/instant | current anchor if resolved | YES | cancellation only against exact target; otherwise Observation-only |

Unknown temporal meaning never defaults to now.

## 16. Option decision and downstream impact

**Recommended:** C1 — extend Observation with typed semantic fields, add the
eligibility gate, and persist prospective observations only.

**Deferred:** C2/P1 — prospective Situation/DecisionContext surface. It needs
its own cognition contract, budgets, and review.

**Rejected:** P2 generic Fact/context conversion, C3 duplicate durable type,
raw value/metadata encoding, planned/tentative RuntimeState statuses, and full
StateBar runtime reuse.

Existing owners remain unchanged: Fact/Evidence owns source authority;
Reality/Input proposes; FactualReconciler writes canonical state;
EffectiveStateResolver reads effective state; Situation and DecisionContext
project bounded current context; Memory/Affect/Persona/Relationship/Intent do
not receive direct authority from prospective Observation.

## 17. Follow-up implementation scope

Implementation is a separate authorized task and is limited to typed Observation
fields, deterministic normalization, additive persistence, replay conflict
checks, a pure eligibility gate, current/terminal/observation-only tests, and
the `user.sleep.phase` key correction. It must not add a prospective Situation
surface, automatic activation, Memory/Affect/Persona authority, or StateBar
runtime dependency.

This document authorizes none of those production changes by itself.

## 18. Frozen summary

```yaml
Observation:
  modality: ASSERTED | PLANNED | TENTATIVE | ESTIMATED | INFERRED
  semantic_time: typed relation + precision + optional daypart
  effective_window: POINT | INTERVAL | OPEN_INTERVAL | null
  confidence: extractor confidence only
  observed_at: original Evidence.received_at

Current-state eligibility:
  ASSERTED + resolved window containing now + allowed key -> ELIGIBLE_CURRENT
  explicit terminal operation + exact valid target -> ELIGIBLE_TERMINAL
  future/planned/tentative/estimated/inferred -> OBSERVATION_ONLY
  unresolved time/timezone -> OBSERVATION_ONLY
  invalid authority/schema/conflict -> REJECTED

Prospective policy: P0 persistence-only
Persistence: additive dedicated columns with legacy defaults
Replay identity: original Evidence/provenance plus normalized semantic fields
Timezone authority: trusted runtime/user binding, then trusted host/source
Anchor authority: original Evidence.received_at
Canonical writer: FactualReconciler only
Auto activation: FORBIDDEN
StateBar runtime dependency: NONE
Canonical sleep key: user.sleep.phase
```

**Final verdict:** `CONTRACT_ACCEPTABLE_FOR_IMPLEMENTATION`
