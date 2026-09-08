# ADR-0007: Bound expression authority behind typed context and deterministic guards

- **Date:** 2026-08-23
- **Status:** Accepted for D10 implementation

## Problem

D9 selects and permits an Intent without an LLM, but the remaining expression
path is still a walking-skeleton shortcut. `DecisionContext.expression_context`
is an unstructured tuple of strings, the orchestrator constructs it directly,
and `ExpressionGuardPort` receives only the generated text, Scope, and runtime
id. A real deduplication or temporal-grounding guard cannot obtain the prior
expression or the factual time context through that contract. There is also no
bounded rewrite protocol.

Leaving those gaps to a provider prompt would make behavior depend on model
tendency and context quality. Giving a guard access to raw State, history, or a
database dump would instead recreate the context-pollution and authority
problems that D7R compressed out of the runtime.

## Previous Assumption

The D1/D2S contracts were intentionally sufficient for a single fake Agent
call followed by one stub guard result. A tuple of string constraints and the
`accepted` / `rewrite_required` booleans kept the canonical pipeline
executable before D10 had an owner for compilation, rendering, or retries.

## New Evidence

- D7R requires a minimal DecisionContext with no semantic duplication or raw
  numeric trace in ordinary prompts.
- D9 now provides the selected Intent and the sole ActionPolicy permission,
  so D10 must not let generated prose change either decision.
- G14 requires Policy to remain allowed while a repeated expression is sent
  through an independent rewrite path.
- The registered legacy rules need the previous expression and authoritative
  Situation time facts, neither of which is available to the current guard
  port.
- The product requires a deterministic operational lower bound across model
  swaps and context-quality changes.

## Decision

D10 introduces one typed, bounded expression boundary after an allowed D9
Intent:

```text
selected Intent + allowed Policy + typed runtime inputs
        -> DecisionContextCompiler
        -> typed bounded DecisionContext
        -> ContextRenderer
        -> expression provider (wording only)
        -> deterministic ExpressionGuard chain
        -> ACCEPT | REWRITE | REJECT
```

`DecisionContextCompiler` is the only authority that may convert runtime
objects into provider-visible expression context. It consumes typed objects,
never raw persistence rows or arbitrary object dumps. It emits typed context
items with a kind, key, value, stable priority, and source references.
Configuration selects
which Situation facts and affect dimensions are visible. Numeric affect values
are mapped deterministically to configured qualitative bands before they enter
ordinary expression context.

`ContextRenderer` is deterministic and budgeted. Trusted instructions and
untrusted factual/history text render into separate sections. Overflow drops
whole optional items in a stable priority order and traces the omission; it
never silently truncates an essential action or Policy constraint. The
provider renderer never exposes raw State, raw history results, database rows,
or contribution traces. A separate diagnostic rendering mode exposes only item
references, priorities, and budget omissions; it still has no raw affect or
contribution data, and its output type cannot be passed to the expression
provider.

The expression provider may choose wording and nuance only. It cannot change
the selected Intent, action type, Policy permission, factual items, projected
state, Persona, or source references.

The guard contract becomes a per-attempt typed evaluation. It receives the
candidate expression, its DecisionContext, the explicit attempt number, and
the bounded prior expression carried by that context. The result has one
disposition enum: `ACCEPT`, `REWRITE`, or `REJECT`, plus machine-readable
violation codes. Guards never generate replacement prose. The placeholder
`rewritten_expression` field and contradictory boolean combinations are
removed.

A deterministic expression coordinator owns the capped loop. `REWRITE` adds
only registered, reason-coded guidance to a new immutable DecisionContext and
asks the provider for another draft. Configuration owns the maximum rewrite
count; the Kayla compatibility fixture starts at two. Exhaustion becomes
`REJECT/retry_exhausted` and produces no sent action.

The first guard chain contains only registered deterministic rules:

1. non-empty/output-shape validation;
2. forbidden opening detection;
3. normalized first-eight-Unicode-code-point prefix deduplication;
4. explicit temporal-grounding contradictions against Situation daypart.

Temporal grounding uses a configured phrase-to-daypart incompatibility table.
It does not ask an LLM to judge truth and does not hard-code genuinely
ambiguous semantics. Unknown phrasing is not promoted into a false factual
verdict; D11 shadow metrics own miss-rate evidence and future rule proposals.

The prior expression comes only from a read-only `PreviousExpressionPort`
queried after D9 selects an allowed action. A returned item must be same-Scope,
bound to the queried action type, carry an aware send time, and carry explicit
`SENT` delivery status plus its receipt reference.
The default port returns none. D10 adds no expression-history table, Memory
write, reinforcement, or provider-derived Persona update; a host or later D11
adapter may expose already-authoritative delivery history through the port.
UNSENT, UNKNOWN, rejected, and failed-rewrite drafts are never eligible prior
expressions.

ActionPolicy and ExpressionGuard remain separate authorities. A rewrite or
rejection cannot turn an allowed Policy result into deny/defer, rescore an
Intent, or mutate affect. An accepted final expression follows the existing
receipt/reconcile path. Retry exhaustion records an UNSENT receipt; a provider
failure before a guarded result preserves the existing abort/no-receipt
behavior. Only reconciled `SENT` completes the D9 Intent.

Projected affect remains independent from expression success. D10 never
auto-commits it. The existing explicit D5 commit boundary may still promote an
honest projected internal transition even when no wording was sent; a guard
has no authority to approve or erase affect.

## Preserved Boundaries

- LLMs may write prose but cannot own facts, Persona, affect, Intent, Policy,
  lifecycle, scheduling, commit, or delivery truth.
- Situation remains the source of deterministic temporal facts.
- Historical input remains bounded, read-only, source-referenced, and treated
  as data rather than provider instructions.
- Prior-expression input is a bounded read-only view of sent delivery history,
  not a new Memory authority or write path.
- DecisionContext is a compiled view, not a new canonical store.
- ExpressionGuard cannot call an LLM or rewrite prose itself.
- ActionPolicy cannot inspect or reject wording.
- The canonical orchestrator remains the only production pipeline.
- Native Memory, Persona learning, onboarding, and D11/D11P behavior remain
  out of scope.

## Rejected Alternatives

### Keep `tuple[str, ...]` as the expression-context contract

Rejected because string conventions cannot reliably enforce kind, lineage,
trust level, stable ordering, uniqueness, or a no-raw-dump boundary. They also
make retry guidance indistinguishable from factual context.

### Let the model self-check repetition and temporal truth

Rejected because the same input would vary across providers, temperatures,
and polluted contexts. Provider self-review can improve style, but it is not a
Runtime permission or guard verdict.

### Give guards raw Context, State, history, or prompt text

Rejected because each guard would rebuild its own interpretation and could
leak or duplicate semantics. Guards receive only the compiled typed view and
their fixed configuration.

### Let guards produce replacement text

Rejected because deterministic string substitution cannot preserve natural
expression, while an LLM-backed guard would combine generation and authority.
Guards return reason codes; the provider remains the sole prose generator.

### Reject every phrase not proven temporally correct

Rejected because a finite lexicon cannot prove arbitrary language. D10 blocks
registered explicit contradictions and preserves uncertainty instead of
claiming a false semantic authority.

## Affected Contracts

- `DecisionContext`: replace unstructured expression strings with typed,
  source-referenced context items and add selected action plus attempt data.
- Add compiler input, context-item kind, render result, and compile/render
  trace contracts.
- `ExpressionGuardResult`: replace overlapping booleans and guard-written text
  with one `ExpressionDisposition` and reason codes.
- Add `ExpressionGuardInput`, per-attempt trace, and final expression outcome.
- `ExpressionGuardPort`: accept the typed guard input.
- Add compiler, renderer, and expression-coordinator ports without creating a
  second orchestrator.
- Add a read-only `PreviousExpressionPort`; no new persistence contract or
  table is authorized.

## Migration

The D2S stubs and FakeAgent migrate to the typed context and disposition enum.
Existing G14 synthetic guard behavior is replaced by the real prefix guard and
coordinator. There is no production DecisionContext persistence and no data
rewrite.

Rollback may restore the D9 direct Agent/stub-guard composition because no D3-
D9 canonical or Intent schema changes are made. Any D10 trace records are
derived execution evidence, not Canonical State.

## Acceptance Tests

- Same typed inputs and configuration produce byte-equivalent DecisionContext,
  provider rendering, guard order, reason codes, and trace metadata.
- Compiler rejects wrong-Scope inputs, duplicate/conflicting items, raw-dump
  attempts, invalid bands, and missing essential action/Policy data.
- Ordinary rendering contains no raw numeric affect or contribution trace;
  diagnostic output is type-isolated from the provider port.
- Untrusted history and prior output render as quoted data, never trusted
  instructions.
- Registered forbidden openings, prefix collisions, and explicit time
  contradictions request rewrite deterministically.
- Blank provider output reaches structural validation and is rejected; it can
  never satisfy ACCEPT or REWRITE result invariants.
- Wrong-Scope, wrong-action, UNSENT, UNKNOWN, or unreferenced prior-expression
  items fail closed or are absent and can never seed dedup history.
- A clean expression is accepted; invalid structure is rejected fail closed.
- Rewrite attempts stop at the configured cap and every attempt is traced.
- G14 runs through the real guard chain: Policy remains allowed while the
  repeated first draft requests rewrite.
- Guard failure cannot mutate Policy, Intent, affect, Persona, or Canonical
  State, and cannot complete an Intent without reconciled `SENT` evidence.
