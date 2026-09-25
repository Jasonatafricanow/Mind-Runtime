# ADR-0030: Automatic bounded Thread maintenance after canonical Memory admission

- Status: ACCEPTED
- Date: 2026-09-25
- Builds on: ADR-0023, ADR-0028
- Canonical architecture: `docs/architecture/MEMORY_ARCHITECTURE_V1.md`

## Decision

New canonical Memory automatically enters a durable, retryable Thread-maintenance
path. Thread maintenance is derived product state. It cannot authorize, alter,
or replace canonical Memory.

The default production path is deliberately conservative and deterministic:

```text
admitted Evidence / Observation
-> canonical Memory commit
-> durable thread_update_intent
-> deterministic Thread policy
   -> OPEN one explicit unfinished line
   -> UPDATE one unambiguous existing line
   -> RESOLVE one unambiguous explicit line
   -> or NOOP
```

No additional LLM call is required by this path.

## Why

Thread is the explicit medium-term working layer. Requiring callers to invoke
`open_thread()` / `update_thread()` manually leaves the architecture present
but inert during normal use.

At the same time, automatic Thread maintenance must not become a second
longitudinal reasoner. The default policy therefore performs only bounded
line-tracking operations that can be justified from the new Memory plus existing
open Threads.

## Durable ordering and retry

`CanonicalMemoryStore` registers a `thread_update_intents` row in the same
transaction that inserts a new canonical Memory.

The intent records canonical commit time and is replayed in
`(registered_at, memory_id)` order. A product mutation may therefore crash
before its intent receipt is marked successful without losing the work.

Replay is idempotent:

- an already-supported Memory does not increment Thread touch count again;
- an already-opened Thread is not duplicated;
- an already-resolved line is not resolved twice;
- queue failure never rolls back or mutates canonical Memory.

Existing historical Memory is **not** automatically backfilled. Explicit
`ThreadUpdateQueue.rebuild(...)` exists for controlled migration/lab use only.

## Default deterministic policy

The default policy opens a Thread only when the new Memory contains an explicit
unfinished-line cue and is not merely an obvious short-term/current-state item.

Examples of eligible cues include bounded forms of:

- considering / planning / waiting / undecided;
- 考虑 / 打算 / 计划 / 纠结 / 尚未决定 / 等待回复;
- equivalent Portuguese unfinished-line wording.

A new Memory updates an existing Thread only when lexical topic overlap selects
one line above a minimum threshold and with sufficient margin over the next-best
candidate.

If multiple Threads are similarly plausible, the policy abstains.

An explicit resolution can close a matched Thread. A topic-less resolution such
as "算了，不买了" may close a Thread only when exactly one open Thread exists in
the authorized Scope.

## StateBar boundary

The policy rejects obvious short-lived/current-state statements such as
"tonight", "right now", "马上", or similar forms unless the same text also carries
a continuity/unresolved marker.

This is only a conservative guard. StateBar remains the authority for current
state and semantic expiry; Thread does not become another short-term state table.

## Maturity boundary

Automatic line tracking does **not** create `working_summary` and does not set
`mature=True`.

That is intentional.

A deterministic lexical matcher can establish that an explicit line remains
open and that a new Memory belongs to it. It cannot claim that the longitudinal
meaning of those Memories has already been reasoned.

Thread maturity still requires an already-reasoned online structure supplied
through the existing bounded Thread update seam. This preserves the rule:

> tracking continuity is not the same operation as interpreting trajectory.

LCE development is independent of this decision.

## Policy replacement seam

`ThreadUpdatePolicy` is injectable at Memory composition. A future online
reasoner may provide a richer policy without changing canonical Memory,
Thread persistence, or the durable retry queue.

Any richer policy remains a proposal layer. Runtime-owned product mutation and
canonical support checks remain authoritative.

## Consequences

After this ADR, normal Memory-enabled production composition automatically:

1. creates explicit medium-term Threads for conservative unfinished-line cases;
2. updates bounded support when later Memory clearly continues the line;
3. closes a line on unambiguous explicit resolution;
4. abstains instead of guessing when relation assignment is ambiguous.

Automatic semantic maturity and latent longitudinal discovery are separate
problems and are not implied by this mechanism.
