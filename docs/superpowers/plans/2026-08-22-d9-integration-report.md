# D9 Intent, Scheduler, and ActionPolicy Integration Report

## Verdict

`D9: COMPLETE`

`READY FOR D10: YES`

This verdict authorizes only the named D10 expression-context gate. D10
behavior is not implemented in this branch. D11-D11P, MR-4 Native Memory, and
MR-5 Distributed Runtime remain blocked.

## Repository evidence

- Branch: `w/d9-intent-scheduler-policy`
- Worktree: `<MR_REPO_ROOT>\.worktrees\d9-intent-scheduler-policy`
- Base main HEAD: `e21f829269bb0f30a41b63e9dc82d66db974f032`
- Final D9 code/test HEAD before this closure report: `21136dac0c52bbc396964f2062e09d8a358d77b4`
- Architecture authority: ADR-0004, ADR-0005, and ADR-0006
- Approved design: `2026-08-22-d9-intent-scheduler-action-policy-design.md`
- Merge/push status: not merged and not pushed by this report

## Contract correction and authority

ADR-0006 removes the D7R/D8 walking-skeleton shortcut in which
`EmotionalTransitionResult` emitted a fixed cognitive `respond` Intent. The D8
result now exposes only ProjectedMindState, accepted typed semantic events, and
AssessmentTrace. A separate deterministic IntentEngine owns candidate scoring;
Intent lifecycle owns durable cognitive status; Scheduler owns wake/expiry but
never execution; ActionPolicy alone owns current action permission.

The Kernel contains no `persona_id` behavior branches. Agent adaptation stays
in configuration-owned dimension weights, event rules, thresholds, and policy
rules. No LLM scores, orders, admits, transitions, schedules, wakes, selects,
defers, denies, permits, persists, or completes an Intent.

## Delivered deterministic scoring

`DeterministicIntentEngine` consumes the factual Context, projected internal
state, accepted typed events, fixed rules, and injected UTC Clock. It records
base, configured dimension, and accepted-event contributions separately,
clamps once, excludes below-threshold rules with a trace, and orders admitted
candidates by `(-strength, kind, intent_id)`.

Missing, non-numeric, and non-finite dimensions contribute zero. A matching
typed event is applied once. Scheduled rules parse only their configured UTC
ISO attribute; missing, malformed, non-UTC, conflicting, or already expired
schedules abstain. Identical inputs replay to byte-equivalent results.

## Lifecycle, persistence, and restart evidence

The legal lifecycle is append-only:

```text
CANDIDATE -> ALLOWED | DEFERRED | BLOCKED | EXPIRED | SUPERSEDED
DEFERRED  -> CANDIDATE | EXPIRED | SUPERSEDED
ALLOWED   -> COMPLETED | SUPERSEDED
```

Every transition increments the Intent version, preserves schedule/cause/state
references, and appends one immutable transition. Terminal rewrites, cross-Scope
reads, stale before-versions, identity changes, immutable-fact changes, and
conflicting idempotency reuse fail closed.

The SQLite backend adds only `intents` and `intent_transitions`. It uses the
repository's seven Scope columns, append-only version rows, stable JSON, aware
ISO timestamps, foreign-key lineage, and one transaction for the new Intent
version plus transition. A constraint-trigger fault proves that both writes
roll back together. A fresh backend on the same file restores the same latest
Intent, complete history, transitions, timestamps, and due work.

## Scheduler and Policy evidence

`IntentScheduler.tick(scope, now)` first expires stale candidate/deferred
Intents, then moves only `DEFERRED + ON_DUE + due_at <= now` back to CANDIDATE.
It returns immutable wake records for reconsideration. Repeated ticks create no
duplicate transition or wake. Scheduler has no Agent, Guard, or Receipt
dependency and cannot execute.

ActionPolicy reads only the candidate, factual Situation keys, injected Clock,
fixed configuration, and current resource list. Gate order is schedule,
supported mapping, resources, interruption/pending reply, proactive cooldown,
and media budget. Temporary constraints are DEFER with a denied permission;
unsupported kinds and expired candidates are DENY; a valid current action is
ALLOW with an allowed permission. Malformed named facts fail closed.

## Canonical orchestrator and receipts

The one canonical orchestrator calls D8 once and IntentEngine once, validates
all output Scope/origin/lifecycle shapes before admission, persists all
candidates, and evaluates them in score order. DEFER or DENY continues to the
next candidate. The first ALLOW is selected and only its lower unevaluated
candidates are superseded.

If no candidate is allowed, the orchestrator creates no DecisionContext, calls
no Agent or ExpressionGuard, creates no receipt, and never enters DISPATCHING.
The projected internal state and complete Intent references remain available
to `commit_turn`, so an honest affect transition is not erased by an external
permission failure.

An allowed candidate retains the existing D5 Agent, Guard, checkpoint,
ActionReceipt, delivery-unknown, and reconcile path. Only a reconciled SENT
receipt transitions ALLOWED to COMPLETED. UNKNOWN and UNSENT remain explicit
and do not complete the Intent.

## Golden and quality evidence

The D9-owned Goldens are green:

- G4: high `contact_user` Intent remains distinct from a blocked proactive action.
- G5: photo budget defers photo while text falls back and is allowed.
- G14: ActionPolicy allows while ExpressionGuard independently requests rewrite.
- G16a: proactive cooldown is owned and blocked by Policy.
- G24: a durable due Intent survives restart, wakes for reconsideration, and is
  rechecked without direct execution.

The active Golden inventory is 22 green and exactly 5 strict later-gate xfails:
G12 and G25-G28.

Closure verification on the final code/test tree:

- Pytest: `857 passed, 5 xfailed`
- Ruff check: pass
- Ruff format check: pass
- strict mypy: pass
- Coverage: `3885` statements, `1174` branches, `100%`
- `git diff --check`: pass

## Explicit exclusions

D9 does not implement expression-context compilation, prompting, generation,
or rewrite loops; D10 behavior is not implemented. It also does not deliver
Kayla long-horizon/model-swap certification, relationship/native Memory writes,
onboarding import analysis or UI, Persona learning, distributed scheduling, or
MR-5 replication behavior.

## Merge recommendation

The D9 branch is eligible for local merge after the final branch-choice review.
Do not merge, push, publish, or begin D10 merely because this report exists;
use the verified final repository state and an explicit integration choice.

