# D10 Bounded Expression Runtime — Integration Report

**Branch/worktree:** `w/d10-expression-runtime` / `<MR_REPO_ROOT>\.worktrees\d10-expression-runtime`
**Base HEAD:** `c931e0d04cf9a9547c74c372c9fd76cadb0d9151` (D9 main)
**Final code/test HEAD:** `0bf0f6f6efd6d11f16d79f86f01ee3b2f0f56739`
**Date:** 2026-08-23

## Scope

D10 replaces the D9 expression shortcut with one typed, bounded, deterministic
DecisionContext/Renderer/Guard path in which the provider writes prose only.
No LLM may compile facts, calculate affect, select or mutate Intent, grant
Policy permission, evaluate guards, commit state, or determine delivery truth:
LLM output is a bounded prose candidate consumed by the deterministic chain.

## ADR-0007 contract migration

ADR-0007 is Accepted ("Accepted for D10 implementation") and its protected
DecisionContext / ExpressionGuard contracts are migrated into executable frozen
contract tests (`tests/contract/test_d10_expression_contracts.py`). Provider
and Diagnostic envelopes are distinct types; AgentPort accepts only
`ProviderExpressionContext`. Independent reviews of the ADR-0007 contracts
range and of every subsequent task are recorded under
`docs/superpowers/plans/2026-08-23-d10-task{1..6}-review.md`; all six closed
ACCEPT (with minors only, none blocking).

## Typed compiler and qualitative affect evidence

`DecisionContextCompiler` validates all authority relations (Scope, origin,
Intent, Policy ALLOW + intent match, prior expression scope/origin/action type)
before producing any provider view. Affect values are mapped once into
qualitative labels by configured bands; no raw numeric affect reaches provider
text or the compile trace. Custom 5/12/20/other dimension sets require
configuration, never Kernel schema. Compilation is deterministic: same input
yields the same item ids, order, and trace; no model call and no wall-clock
read.

## Provider/diagnostic renderer separation and exact budgets

`DeterministicContextRenderer` emits the only provider envelope with stable
section order (ACTION, FACT, INTERNAL_STATE, POLICY_CONSTRAINT, PERSONA_STYLE,
HISTORY, PRIOR_EXPRESSION, REWRITE_GUIDANCE), escaping (`\` `\r` `\n`), trust
separation (`[UNTRUSTED_DATA]` on history/prior lines only), whole-item budget
omission in reverse importance order, and fail-closed essential overflow.
`render_diagnostic` exposes refs/priorities/omissions only and returns a type
that cannot satisfy AgentPort.

## Read-only previous-expression authority and exclusions

`PreviousExpressionPort` has no write surface. `NullPreviousExpressionPort` is
the default; `FixedPreviousExpressionPort` returns an item only on exact
Scope/action match. Wrong-Scope/wrong-action/UNSENT/UNKNOWN/naive-time/blank-
receipt items are excluded; a contract-violating port double fails closed at the
compiler. Reading history never reinforces, persists, or updates Persona.

## Guard rule ids/order and legacy closure

`DeterministicExpressionGuardChain` runs structural checks
(`invalid_expression`, `missing_temporal_fact`, `malformed_temporal_fact`;
attempt mismatch is contract-layer, scope/origin mismatch is coordinator-layer)
before content checks in fixed order (`forbidden_opening`, `prefix_duplicate`,
`temporal_conflict`), accumulating once per rule. Temporal rules must share one
exact fact key. Legacy closure: exactly the three registered rules —
`banned_openings_prefix8` -> ForbiddenOpeningGuard + PrefixDedupGuard
(preserve), `time_grounding` -> D6 Situation fact + TemporalGroundingGuard
(change), `repeat_context_prompt` -> bounded prior context + deterministic
dedup (generalize) — see `docs/legacy/kayla-rule-map.md`.

## Rewrite cap and provider call bound

`DeterministicExpressionCoordinator` is the only retry owner: cap
`max_rewrites` counts calls after the initial draft; maximum provider call count
is `1 + max_rewrites`. Every attempt has distinct context/render/draft ids and
one immutable trace row; guard exceptions, invalid guard results, and non-string
provider output fail closed as REJECT; provider failure aborts without a
fabricated result or receipt.

## Canonical receipt/Intent/commit behavior

The orchestrator has one expression path after an allowed candidate:
previous-expression query -> compile -> coordinator. ACCEPT -> SENT receipt with
the accepted expression; REJECT/exhaustion -> one UNSENT receipt with no
outcome; provider failure -> ABORTED with no receipt. Guard verdicts never
change Policy or complete the selected Intent (only reconciled SENT does).
Expression failure never auto-commits projected affect; `commit_turn` remains
the caller's explicit D5 choice.

## Real G14 evidence

G14 now runs the real compiler/renderer/guard/coordinator with a fixed previous
expression and two scripted drafts: first draft duplicates the prior prefix
(REWRITE/prefix_duplicate), second draft is distinct (ACCEPT); Policy stays
ALLOW throughout. Outputs: `("action.policy", "allowed")`,
`("expression.guard", "rewrite_required")`. All pre-D10 green Goldens remain
green (41 passed, 5 xfailed in the golden suite).

## Exact verification outputs

```text
pytest -q                      -> 978 passed, 5 xfailed (exact G12, G25-G28)
ruff check .                   -> All checks passed!
ruff format --check .          -> 254 files already formatted
mypy src tests                 -> Success: no issues found in 203 source files
coverage (statements+branches) -> 100% (0 missed statements, 0 missed branches)
git diff --check               -> clean
git status --short --branch    -> clean w/d10-expression-runtime
```

## Explicit exclusions

D11 (long-horizon validation), D11P (onboarding/productization), MR-4 (native
Memory), MR-5 (distributed runtime), onboarding behavior, and product UI are not
implemented in this branch. `D11 behavior is not implemented in this branch.`

## Verdict

```text
D10: COMPLETE
READY FOR D11: YES
```

