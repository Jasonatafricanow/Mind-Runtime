# D7R Compressed Runtime and Agent Onboarding Design

**Status:** Approved in product discussion on 2026-08-22; implementation still
requires the D7R ADR and contract/golden re-baseline required by repository
governance.

**Base HEAD:** `56235e4ebf2b3b6700da5e0d95685ad3276d802c`

**Scope:** D7R through the first Product Slice productization gate.

**Primary validation target:** Kayla companion agent.

## 1. Decision Summary

Mind Runtime keeps the trust boundaries already delivered by D3-D7, but it no
longer treats every conceptual step in an emotional causal chain as an
independent runtime subsystem.

The first Product Slice uses one deterministic, traceable emotional transition
path:

```text
Evidence / Observation
        -> Effective State
        -> factual Context
        -> deterministic Emotional Transition
        -> Projected Internal State
        -> Intent
        -> ActionPolicy
        -> Minimal DecisionContext
        -> Agent / LLM expression
        -> ExpressionGuard
        -> Commit
```

LLMs remain useful for bounded language interpretation and expression. They do
not own Persona truth, Canonical State, final affect values, Intent selection,
policy permission, memory reinforcement, or ongoing personality judgement.

Agent import and new-Agent creation remain required product capabilities. They
are delivered only after the Kayla runtime has passed shadow and long-horizon
validation. The onboarding design freezes the user flow and authority boundary
now, while deliberately deferring the exact core attributes, point pool, and
numeric compilation table until real Kayla evidence exists.

## 2. Why the Baseline Is Changing

The frozen V0.1.4 topology separates Situation, SemanticAppraisal,
ResolvedAppraisal, Dynamics, Motivation, ActionPolicy, and DecisionContext.
Those concepts remain useful for explanation, but the current contracts create
three risks:

1. The same semantic fact can be represented and weighted in several layers.
2. Persona, relationship, and historical influence can be applied more than
   once before an affect transition is complete.
3. Correlated Situation, appraisal, affect, motivation, Persona, and history
   summaries can all be rendered back to the base model, amplifying model bias
   and context pollution.

There is already a concrete ownership overlap: D6 computes proactive cooldown
and media eligibility verdicts inside Situation, while the frozen D9 scope also
assigns those verdicts to ActionPolicy. `ResolvedAppraisal` also carries
`motivation_signals`, while the canonical pipeline separately derives
Motivation from ProjectedMindState.

The correction follows one rule:

> Separate authority; do not split computation merely to make the causal chain
> visible. Preserve the complete causal explanation in an immutable trace.

## 3. Goals

The revised first Product Slice must:

- run one persistent Kayla internal-state model outside the base model;
- produce deterministic, bounded, replayable emotional state transitions;
- explain every transition through source evidence and contribution records;
- keep Persona traits separate from current internal state;
- produce durable, reconsiderable Intents instead of direct actions;
- keep ActionPolicy as the only action-permission authority;
- keep ExpressionGuard separate from ActionPolicy;
- remain useful when semantic or expression LLM providers are unavailable;
- bound the influence of uncertain language interpretation and historical
  context;
- remain stable when the base model or context-window implementation changes;
- validate long-horizon behavior before adding native memory writeback;
- finish with a product onboarding UI for importing an existing Agent or
  creating a new one.

## 4. Non-Goals

The revised first Product Slice does not include:

- native Memory admission, consolidation, reinforcement, or Persona learning;
- automatic promotion of repeated episodes into habits or traits;
- continuous LLM review of an Agent's personality;
- a general semantic ontology for every possible Agent domain;
- dynamic creation of personality dimensions by an LLM;
- fine-grained public tuning of sensitivity, coupling, or recovery floats;
- proof that work, trading, game, and other Agent classes all share one affect
  profile;
- MR-5 distributed deployment;
- replacement of the delivered D3-D5 factual, state, projection, commit,
  receipt, recovery, or replay boundaries.

## 5. Preserved Trust Boundaries

The following existing decisions remain non-negotiable:

- Evidence and Observation are the factual authority.
- Assistant output is not automatically Evidence.
- Business logic consumes Effective State, never raw state.
- Persona Trait is not Current State.
- Projected State is not Canonical State.
- Derived internal changes commit only through the turn commit boundary.
- Scope, Authority, and Ownership checks fail closed.
- Action candidates and external side effects retain receipt/reconcile
  semantics.
- ActionPolicy and ExpressionGuard remain separate.
- Historical reads cannot touch, reinforce, or resurrect state.
- LLM output cannot directly mutate state or choose final affect values.
- Replay, fixed clocks, versioned configuration, and causal trace remain
  required.

## 6. Runtime Components and Authority

### 6.1 Factual Context

The current `Situation` implementation remains a compatibility surface during
D7R, but its semantics narrow to a factual Context frame. It may contain:

- deterministic time and elapsed-time features;
- current interaction and conversation state;
- current effective user/world facts;
- bounded counters and recurrence summaries;
- references to the evidence from which those features were derived.

It must not contain action verdicts such as `cooldown_ready`, `allowed`,
`blocked`, photo eligibility, or budget permission. It must not infer a stable
trait or user judgement.

Whether the public type is later renamed from `Situation` to `ContextFrame` is
an ADR migration decision, not a prerequisite for the compressed computation.

### 6.2 Typed Semantic Event

Clear events enter the transition engine as typed events produced by
deterministic extraction or a trusted adapter. When natural language is
genuinely ambiguous, an optional semantic provider may return multiple typed
event candidates with confidence and evidence references.

The semantic provider may not return affect values, state transitions,
Motivation, Intent, policy decisions, traits, or memory write operations.

Low-confidence or conflicting candidates must abstain, remain low-impact, or
wait for later evidence. They must not be converted into a strong Canonical
State change merely because a provider produced a syntactically valid object.

### 6.3 Emotional Transition Engine

The engine is the single computational authority for one internal-state step.
It consumes:

```text
current canonical/projected internal state
+ elapsed time
+ typed events
+ factual Context
+ fixed PersonaProfile version
+ bounded historical facts
```

It produces:

```text
Projected Internal State
+ TransitionIntent records
+ Assessment/Contribution Trace
```

The engine applies each influence exactly once. A contribution trace records:

- source event or elapsed-time cause;
- evidence and history references;
- Persona/Profile version;
- state before;
- recovery, event, history, modifier, and coupling contributions;
- state after;
- confidence and any abstention or clamping reason.

`SemanticAppraisal` may remain as an optional semantic input record.
`ResolvedAppraisal` does not remain an independent runtime authority or a
required service hop. Its useful explanatory fields migrate into the
transition trace. `motivation_signals` do not belong in appraisal resolution.

### 6.4 Persona

The first Product Slice uses the existing fixed `kayla_v0` profile and the
dynamic dimension/policy mechanics delivered by D7. The Kernel must not branch
on `persona_id` and must not fix the schema to Kayla's dimensions.

Persona owns baseline, bounds, sensitivity, recovery, and coupling
configuration. It does not own current affect. Runtime calculations record the
exact Persona version they used.

No automatic runtime process mutates Persona in this Product Slice.

### 6.5 Intent and Scheduler

Internal state does not directly produce an action. It produces one or more
Intent candidates:

```text
Intent {
    kind
    strength
    earliest_at
    due_at
    expires_at
    reconsideration_policy
    cause_refs
    state_refs
    status
}
```

An Intent that must survive restart is durable and versioned. Reaching
`due_at` wakes the Intent for reconsideration; it never authorizes execution.
Reconsideration uses current Context, current internal state, and current
Policy. Intent lifecycle distinguishes at least candidate, deferred, allowed,
blocked, expired, completed, and superseded outcomes without rewriting
terminal history.

### 6.6 ActionPolicy

ActionPolicy is the sole authority for whether a candidate action may execute.
The first batch owns:

- proactive cooldown;
- active-conversation and pending-reply interruption rules;
- media budget and frequency rules;
- current resource/tool availability;
- Intent expiry and current eligibility.

Every result carries a machine-readable reason. Policy consumes factual Context
and current counters; it does not mutate affect or Persona.

### 6.7 Minimal DecisionContext and Expression

DecisionContext renders only what the expression model needs:

- selected action/Intent;
- relevant factual Context;
- a bounded semantic summary of relevant internal state;
- policy constraints;
- expression style and guard constraints.

It does not repeat the same conclusion as raw history, appraisal, affect,
Motivation, Persona prose, and relationship prose. Raw numeric traces stay out
of ordinary prompts.

The expression provider may change wording and nuance. It may not change the
selected Intent, override Policy, create facts, or mutate state. The existing
ExpressionGuard accept/rewrite/reject boundary remains.

## 7. Historical Influence and Pollution Control

Before MR-4, historical input remains provider-neutral and read-only. It may
return bounded facts such as count, first/last occurrence, time window,
counterexamples, confidence, and source references.

Historical input must not return authoritative judgements such as
`user_is_unreliable` or `relationship_threat=high`. The transition engine owns
the bounded effect of historical facts and records it once.

The following protections are required:

- retrieval or surfacing cannot reinforce a memory;
- repeated retrieval of the same item cannot multiply its influence;
- uncertain or contradicted history has an explicit influence ceiling;
- assistant-generated text cannot silently become supporting evidence;
- a transition cannot promote a history pattern into Persona;
- failure or absence of the history provider leaves deterministic current-turn
  behavior operational;
- history contribution can be disabled and replayed for counterfactual audit.

## 8. Base-Model Isolation

For deterministic scenarios, switching the semantic or expression base model
must not change:

- Projected Internal State;
- Intent kind, strength band, or lifecycle decision;
- ActionPolicy result;
- commit/replay result.

Only ambiguous language classification may differ, and those differences must
remain explicit semantic candidates subject to confidence gates. Expression
wording may differ after the Intent and Policy result are frozen.

The first Product Slice therefore treats the base model as a bounded language
provider, not the mind runtime. The Runtime defines the behavioral lower bound;
the model affects language capability and expression quality.

## 9. Delivery Sequence

### D7R — Architecture Compression Review

1. Create the governing ADR for the topology change.
2. Reclassify protected contracts into authority boundaries versus internal
   computation records.
3. Remove policy verdict ownership from Situation.
4. Replace the required ResolvedAppraisal service hop with transition input and
   trace contracts.
5. Remove appraisal-owned motivation signals.
6. Update the pipeline ports, Golden ownership matrix, and migration notes.
7. Compare the frozen and compressed paths on identical Golden inputs before
   accepting the new topology.

### D8 — Deterministic Emotional Transition

1. Implement typed-event transition inputs for the first Kayla scenarios.
2. Integrate current state, elapsed time, fixed Persona, and bounded history.
3. Produce contribution traces and projected transitions.
4. Add optional semantic-candidate input with abstention and confidence gates.
5. Keep deterministic paths fully operational without an LLM or history
   provider.

### D9 — Intent / Scheduler / ActionPolicy

1. Implement Intent scoring and durable lifecycle.
2. Implement `earliest_at`, `due_at`, `expires_at`, and reconsideration.
3. Move cooldown and media permission into ActionPolicy.
4. Implement conversation-interruption and resource policy.
5. Preserve receipt/reconcile semantics for actions that leave the Runtime.

### D10 — Minimal DecisionContext / Expression

1. Compile bounded expression context without semantic duplication.
2. Connect the selected Intent and policy constraints to the Agent provider.
3. Preserve ExpressionGuard, rewrite caps, and trace.
4. Verify that expression failure cannot commit an unapproved internal
   projection or external action.

### D11 — Kayla Shadow and Long-Horizon Validation

1. Run 30-day and 90-day fixed-input simulations.
2. Test recovery, saturation, clamping, self-excitation, restart, and replay.
3. Inject false history, repeated surfacing, assistant self-output, and
   over-negative semantic candidates.
4. Run model-swap invariance tests.
5. Integrate Kayla through feature-flagged shadow, context-assist, and
   controlled-takeover phases.
6. Retain kill switch, rollback, sampling, redaction, and trace retention.
7. Produce an exit report before onboarding productization or MR-4.

### D11P — Agent Onboarding Productization

D11P is part of the first Product Slice product definition, but begins only
after D11 proves the compressed Runtime is worth configuring.

It provides two entry points:

```text
Import an existing Agent
Create a new Agent
```

#### Existing Agent Import

Required input is a complete, ordered conversation containing both user and
Agent roles. Optional inputs include timestamps, original system prompt, model
identity, model parameters, and an existing character description. Optional
metadata is used when present and ignored when absent; the product does not
require forensic reconstruction of the old system.

A one-time onboarding LLM analyzes the conversation and recommends an
allocation over the fixed core attributes. The recommendation includes enough
representative conversation evidence for the user to understand it. It is not
Persona truth and cannot become active until the user accepts or edits it.

#### New Agent Creation

The user may start from a general template or allocate the same fixed core
attributes manually. A fixed total point budget forces trade-offs and prevents
an all-maximal, personality-free profile.

#### Deferred Onboarding Detail

The following details are intentionally selected at the D11P design gate using
Kayla shadow evidence:

- the names and count of core user-facing attributes;
- the total point budget and per-attribute bounds;
- the fixed compiler mapping from user-facing attributes to D7 parameters;
- the initial template catalogue and preview copy.

These are deferred calibration decisions, not permission to add dynamic
attributes or continuous micro-tuning.

#### Runtime Boundary

After activation, the onboarding LLM leaves the runtime path. It does not
continue judging the Agent's personality. Later user-initiated changes edit the
same fixed core attributes, create a new versioned PersonaProfile, and remain
reversible. The first Product Slice contains no automatic personality learning.

## 10. Persistence and Trace

The Product Slice persists only records required for authority, recovery, and
audit:

- Evidence and Observation;
- Canonical State and StateTransition;
- TurnProjection and commit/reconcile records;
- transition contribution trace;
- durable Intent lifecycle records;
- Action and Delivery receipts;
- versioned PersonaProfile;
- onboarding import result and explicit user activation decision, subject to
  retention/redaction policy.

Factual Context and intermediate assessment calculations are derived. They may
be included in a bounded interaction trace but do not become an additional
canonical truth domain.

## 11. Failure Handling

- Missing semantic provider: deterministic typed-event paths continue;
  ambiguous input abstains instead of guessing.
- Missing history provider: current-turn and time dynamics continue with a
  trace reason.
- Invalid or conflicting Persona: transition fails closed before projection.
- Stale canonical version: existing optimistic commit validation rejects the
  projection.
- Scheduler restart: durable due Intents are reconsidered idempotently.
- Expression provider failure: no external action is treated as sent and no
  turn-commit projection is promoted without the existing reconcile rules.
- Onboarding analysis failure: the user may retry or create from the general
  template; no partial Persona becomes active.
- Optional onboarding metadata missing: analysis uses the complete conversation
  only and does not invent replacement metadata.

## 12. Verification and Acceptance

### 12.1 Existing Golden Preservation

D3-D7 trust-boundary Goldens remain green. D7R must explicitly re-own any
scenario whose previous expected topology depended on ResolvedAppraisal,
Motivation, or Situation policy verdicts. No xfail may lose an owner.

### 12.2 Compression Comparison

The frozen and compressed paths are compared on at least:

- user recently woke at night;
- repeated plan cancellation;
- long silence;
- high longing during an active conversation;
- a future Intent reaching `due_at`;
- deterministic cooldown block;
- a genuinely ambiguous utterance.

Comparison records determinism, trace sufficiency, duplicated rules,
duplicated semantic representations, required module changes, LLM dependency,
replay cost, and final behavior.

### 12.3 Long-Horizon and Adversarial Gates

Acceptance requires evidence that:

- every bounded dimension remains within configured limits;
- recovery and time evolution reproduce under a fixed clock;
- repeated neutral events do not create unbounded affect;
- a surfaced history item cannot reinforce or repeatedly multiply itself;
- false or contradicted history has bounded and reversible impact;
- swapping base models preserves deterministic internal decisions;
- LLM absence preserves deterministic operation;
- restart and replay reproduce Canonical State and pending Intent lifecycle;
- no Assistant output becomes Evidence without an explicit external authority
  path.

### 12.4 Productization Gate

The first Product Slice is not complete until D11P demonstrates:

- import of a complete two-party conversation;
- optional metadata accepted without becoming required;
- one-time recommended core-attribute allocation;
- user review/edit before activation;
- template/manual new-Agent creation;
- fixed total point-budget enforcement;
- versioned activation and rollback;
- no onboarding LLM call in the normal runtime path.

## 13. Migration and Change Control

This document records the approved design direction; it does not silently
override the three frozen V0.1.4 authority documents or `AGENTS.md`.

The first implementation work package is `D7R.1` and must:

1. add an ADR stating the previous assumptions, new evidence, selected
   compressed topology, rejected alternatives, contract migration, and Golden
   impact;
2. update the authoritative baseline documents and governance boundary only as
   authorized by that ADR;
3. add or revise contracts and Golden fixtures before production behavior;
4. preserve compatibility adapters only where they make the migration safer,
   not as a permanent second pipeline.

No D8 production implementation begins before the D7R integration gate accepts
the new contracts and executable comparison evidence.

## 14. Product Stop Gate

After D11P, feature development stops for a real usage review. Native Memory,
automatic personality learning, dynamic user-facing dimensions, multi-domain
Agent generalization, and distributed runtime remain blocked until that review
produces evidence and a new ADR.
