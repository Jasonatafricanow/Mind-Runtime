# ADR-0010: No Self-Authorizing Feedback

- **Date:** 2026-08-25
- **Status:** Accepted — independent architecture/contract review passed;
  production work remains gated per sequential W

## Problem

Mind Runtime already rejects assistant messages as authoritative user facts,
keeps Historical Context read-only, separates projection from Canonical State,
and certifies one D11S.5 history item against retrieval amplification. Those
guards are local. They do not yet express one system-level rule covering every
internally derived artifact, and two concrete boundaries remain incomplete:

1. `OwnershipValidator` checks only the Agent runtime name. It does not check
   the Persona owner of Agent scope and does not check Relationship scope at
   all, even though the existing `Ownership` contract treats both domains as
   Persona-owned.
2. the D8 historical adapter validates bundle/item/summary scopes but the
   general influence chain has no typed audit that proves a read, restatement,
   projection, or repeated retrieval did not gain authority, ownership, or
   influence.

Without a single authority rule, a future integration could accidentally turn
Historical Context into local relationship evidence, treat assistant prose as
Evidence, or count repeated internal surfacing as a new affect cause while
each individual subsystem still appears locally valid.

## Previous Assumption

The existing local rules were assumed to compose safely:

- `assistant_message` has no factual authority;
- Historical Context is query-only and immutable;
- `HistoricalContextBundle.scope` matches the current read scope;
- a projection is not Canonical State;
- D11S.5 proves three retrievals do not change one history effect.

These rules remain correct, but their composition is not a complete proof.
They neither name all legal sources of influence escalation nor prevent a new
adapter from laundering an internally derived artifact through a different
provenance label.

## New Evidence

1. `src/mind_runtime/facts/validators.py` rejects only the exact
   `assistant_message` provenance label and accepts any other non-`NONE`
   source type. The repository already recognizes `assistant`,
   `assistant_expression`, and `model_output` as assistant-derived values in
   another invariant, so a denylist at admission is both inconsistent and
   fail-open.
2. `OwnershipValidator.require_owner(...)` handles `ScopeDomain.AGENT` only
   and checks only `agent_id`. It does not verify the Agent `persona_id`;
   `ScopeDomain.RELATIONSHIP` also contains `persona_id` but has no admission
   check at all.
3. `BoundedHistoricalContextAdapter` correctly rejects a provider bundle,
   item, or pattern summary whose scope differs from the current query. The
   current Product Slice therefore has no foreign-scope visibility policy;
   foreign history must continue to fail closed rather than being silently
   rebound.
4. `EffectMapper` derives history influence from the unique summary identity,
   `match_count`, confidence, and configured cap. It does not use retrieval
   count. D11S.5 proves this only for one fixture and three decisions, not as a
   generalized authority invariant.
5. registered time recovery is a legitimate new Dynamics cause even without
   new Evidence. A generalized anti-amplification rule must preserve this path
   and must also permit genuinely new authoritative Evidence to change a
   verified pattern summary.

## Decision

Adopt the following invariant:

> An internally derived artifact MUST NOT gain additional factual authority,
> ownership, or decision influence solely because it is retrieved, surfaced,
> restated, projected, or consumed again by the runtime.

Or, equivalently:

> 任何内部派生产物，不得仅因为再次被检索、浮现、复述、投影或消费，而获得新的事实权威、所有权或决策权重。

The invariant is named **No Self-Authorizing Feedback**.

### 1. Legal escalation evidence (frozen)

Additional authority, ownership, or decision influence is legal only when the
audit captures and reconciles one of these records from the real runtime path:

1. a new authoritative Evidence/Observation pair whose `NEW` or `REPAIRED`
   disposition reconciles with exact factual-plane inventories captured before
   and after `FactIngestPort` admission;
2. an actually applied Dynamics contribution reproduced from authenticated
   runtime-config bytes, component hashes, decoded effect rules, Persona, and
   registered policy bindings;
3. a `TurnProjection.transition_intent` reconciled with the persisted
   `StateTransition`/canonical state at the existing commit boundary, including
   the real Observation-ID to Evidence-ID cause mapping.

A caller-supplied label or opaque reference is never sufficient. In
particular, `internal_projection -> canonical_state` is legal only for the
third reconciled record. `internal_projection -> Evidence` or canonical fact
is always illegal, even if a caller claims a commit basis.

Retrieval count, surface count, prompt injection count, assistant repetition,
projection reuse, similarity, and context compilation are not legal bases.

### 2. Read, ownership, and scope (frozen)

- `read`, `retrieve`, or `surface` does not mean `reinforce`.
- `can_read` does not mean `owns`.
- the current Product Slice has no cross-Persona Historical Context visibility
  policy. A foreign-scope bundle, item, or pattern summary therefore fails
  closed at the bounded historical adapter.
- this ADR does not add cross-Persona visibility. A later requirement to let
  Kayla read Lara-private history must define a separately reviewed visibility
  policy and a contract capable of retaining both source and consumer scope.
- a foreign source scope may never be rewritten as current relationship
  ownership by validation, context compilation, expression, or Dynamics.

### 3. Closed source authority capability (frozen)

The factual admission gate owns a closed source-capability registry. The
currently authority-capable source types are the production values already
used by the repository:

```text
user_message
user_profile
typed_event
```

Known internal values include `assistant`, `assistant_message`,
`assistant_output`, `assistant_expression`, `model_output`,
`derived_context`, and `internal_projection`; they are non-authoritative
regardless of asserted level. An unknown source type also fails closed. A new
authority-capable producer must add its source type to this reviewed registry
and its contract tests; merely choosing a new string cannot evade the gate.

This is provenance validation, not semantic text classification. No code may
search prose for phrases such as `我是 Lara`.

The canonical pipeline must not automatically wrap assistant expression,
Decision Context, Historical Context, appraisal output, or projection output
as Evidence on a later turn. If an adversarial caller submits such a record
directly to `FactIngestPort`, the frozen rejected-Evidence audit behavior from
ADR-0009 remains: the rejected raw record may be retained for audit, but no
Observation is admitted and no canonical fact, state, identity, Persona, or
relationship ownership changes.

A user message that quotes earlier assistant prose is new user-originated
Evidence only for the fact that the user supplied that message. It does not
make the quoted proposition true without its own authority rule.

### 4. Relationship ownership (frozen)

`FactIngestPort.admit(...)` gains an explicit
`writing_persona_id: str | None` keyword. This is an authorized public protocol
change, not signature-compatible with old fakes. The canonical orchestrator
and every implementation, adapter, fake, and test double must be inventoried
and updated to supply the active Persona identity (or `None` for unowned
domains).

- user and world scope retain their existing shared/authority behavior;
- agent scope retains the existing `scope.agent_id == writing_runtime` check
  and additionally requires `writing_persona_id == scope.persona_id`;
- relationship scope requires a non-empty `writing_persona_id` equal to
  `scope.persona_id`;
- a relationship write without an active Persona fails closed;
- Evidence origin runtime, payload text, assistant self-claim, or a readable
  historical scope cannot substitute for `writing_persona_id`.

The canonical call convention is domain-specific: Agent/Relationship passes
the active Persona ID; User/World/Interaction passes `None`. A Persona token is
never sent to or silently ignored by an unowned-domain write.

This is an admission guard, not a new Identity subsystem or ownership store.

### 5. Validation-only influence audit (frozen)

Create one thin `mind_runtime.validation.influence_audit` module. Production
domain packages do not import it. It classifies captured inputs and traces but
does not calculate affect, select an Intent, grant Policy permission, or write
state.

The audit defines validation-only origins:

```text
external_evidence
canonical_state
committed_history
derived_context
internal_projection
assistant_output
```

It reports zero or more of these violation codes:

```text
AUTHORITY_ESCALATION
OWNERSHIP_LAUNDERING
RETRIEVAL_AMPLIFICATION
INTERNAL_ECHO
MISSING_PROVENANCE
FOREIGN_SCOPE_REBIND
```

The audit fails closed on malformed scopes, duplicate or empty references,
non-finite influence, unsupported origins/targets, or any claimed authority
that cannot be reconciled with captured admission, registered Dynamics, or
commit records. It does not accept free-form or caller-asserted legal bases.
For admission it verifies before/after Evidence, Observation, and original
provenance inventories; captures the attempted interaction, runtime, and
Persona; and re-runs both authority and ownership gates. It therefore never
trusts `NEW`, `REPAIRED`, or `REPLAY` as a bare label and preserves the original
Interaction identity on repair. A thrown authority/ownership/conflict error is
captured as a mutually exclusive normalized rejection outcome; the audit
requires authority/ownership rejections to retain Evidence/provenance with zero
Observation growth, reconciles conflicts to their documented ADR-0009 shape,
and grants no rejection a verified authority basis. A validation-only snapshot
callback reads the concrete backend/service without widening `FactIngestPort`.
For Dynamics it accepts
only authenticated raw config bytes, decodes configuration internally,
resolves policies through a closed registry, and then replays the captured
input;
an unregistered custom policy is validation-unverifiable rather than silently
treated as legal. For commit it maps
`TransitionIntent.cause_refs -> Observation.id -> Observation.evidence_refs ->
RuntimeState.evidence_refs`. Commit authority requires persisted
`StateTransition.to_state == canonical RuntimeState`; it does not require a
reverse link from `RuntimeState.transition_refs`, and `StateTransition` is not
assumed to carry a nonexistent `cause_refs` field.

### 6. Retrieval and Dynamics (frozen)

For fixed Clock, authoritative Evidence, initial Canonical State, Persona,
history identities, pattern summary, and configuration, compare an independent
no-retrieval control with a repeated-retrieval treatment:

```text
control:   replay the same Evidence with no repeated history
treatment: replay the same Evidence while retrieving the same H ten times
=> zero retrieval-caused applied contribution
=> no retrieval-caused canonical state or transition divergence
```

The first treatment decision may legitimately apply history because it is
paired with newly admitted Evidence. Later interactions reuse that exact
Evidence through ADR-0009 `REPLAY`, hold Clock fixed, and may not apply another
history impulse. Equality of per-decision amounts alone is insufficient: ten
equal impulses can still create cumulative energy. A separate positive
scenario supplies genuinely new authoritative Evidence and may change the
verified summary. Registered elapsed-time Dynamics may also change affect,
but its captured contribution must reconcile with the registered Dynamics
source; it cannot be relabeled as history retrieval.

## Rejected Alternatives

- **A new AntiAmplificationEngine, IdentityEngine, or MemorySafetyEngine.**
  Rejected: duplicates existing authority, ownership, history, and Dynamics
  boundaries and creates competing business logic.
- **A text classifier for identity claims.** Rejected: payload wording is not
  provenance and cannot decide factual authority.
- **Prompt or ExpressionGuard enforcement.** Rejected: authority is decided at
  factual admission and canonical commit boundaries, not in prose generation.
- **Cross-Persona history visibility in this hardening.** Rejected: no current
  visibility policy can authorize the read or preserve dual source/consumer
  scope. Adding one would be a separate architecture revision.
- **Validation-side suppression of runtime behavior.** Rejected: validation
  observes and audits the canonical path; it cannot skip turns, effects, or
  commits to manufacture an invariant.
- **Treating all influence increases as amplification.** Rejected: that would
  block learning from new Evidence and legitimate deterministic Dynamics.

## Affected Contracts

Explicitly authorized changes:

1. **Fact authority:** internally derived provenance labels are rejected even
   when a caller marks them asserted/observed/verified/system.
2. **Scope/Authority/Ownership:** Agent and Relationship admission require the
   current writing Persona identity; Agent retains its runtime-owner check.
3. **FactIngestPort:** authorized signature change adding
   `writing_persona_id`; the canonical orchestrator, every implementation,
   adapter, fake, and test double is updated. User/world behavior remains the
   same after callers explicitly pass `None`.
4. **Historical Context validation:** existing scope/ref identities are
   checked at every history-consuming boundary. `relationship_events` entries
   and their applied summaries must retain relationship-domain scope and
   resolve their refs to selected relationship items; no schema widening and
   no new visibility capability. Because the schema has only one scope,
   `relationship_events` is now legal only in a Relationship-scope query/turn;
   this is an intentional D8 category-admission tightening.
5. **Validation:** a new audit-only classification and shadow trace are added;
   no production package imports validation.

Explicitly unchanged: HistoricalContext public schema, Persona dimension
schema, Dynamics formulas, Situation/Appraisal topology, State schema,
Replication, ActionPolicy, ExpressionGuard, Decision Context, Intent,
databases, MR-4 Native Memory, and D11L/D11P status.

## Migration

- No database migration and no data rewrite.
- Existing user/world/interaction admissions remain behaviorally compatible
  after the call-site migration and explicitly pass `None`. Agent and
  relationship admissions now require the
  matching Persona; agent admission also retains its runtime-owner check.
- existing USER-scope fixtures that categorized items as
  `relationship_events` migrate either to a Relationship-scope query or to the
  non-private `episodes` category; persisted data is not rewritten.
- relationship admissions that previously bypassed Persona ownership will now
  fail closed unless the canonical caller provides the matching Persona ID.
- internally derived records submitted with non-`NONE` authority will now be
  rejected; rejected raw Evidence remains audit-retained under ADR-0009.
- rollback reverts the hardening commits; no persisted schema rollback is
  required.

## Acceptance Tests

1. Lara-private history cannot enter Kayla's current context under the current
   no-visibility policy and cannot create Kayla relationship ownership.
2. assistant self-claim changes no Persona/identity/canonical record and the
   pipeline creates no Evidence from expression output.
3. a repeated-retrieval treatment and an independent no-retrieval control,
   with fixed inputs and replayed Evidence, have no retrieval-caused applied
   contribution or canonical trajectory divergence.
4. projection or assistant transcript echo cannot become admitted Evidence.
5. foreign relationship scope cannot be rebound; Agent and Relationship
   admission require the matching writing Persona, and Agent also requires the
   matching runtime owner.
6. genuinely new authoritative Evidence may change the verified summary and
   legally increase influence.
7. affect-driven retrieval with no new Evidence produces no independent
   history impulse; registered time Dynamics remains trace-visible and legal.
8. G27 remains green; G28 remains the sole strict xfail owned by MR-D11P.
9. full pytest, 100% statement/branch coverage, Ruff, format, strict mypy,
   import-direction audit, diff check, and independent review are green.
