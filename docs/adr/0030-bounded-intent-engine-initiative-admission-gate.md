# ADR-0030: Initiative admission after domain scoring

- Date: 2026-09-25
- Status: ACCEPTED
- Production activation: BLOCKED_BY_CONFIG

## Problem

`Surface.initiative` is already derived from general proactive pressure, including
sharing urge, curiosity and sadness. Before this change it had no downstream
consumer, so lowering initiative did not actually suppress spontaneous share or
proactive inquiry.

## Decision

Only two spontaneous motives may declare `minimum_initiative`:

- `spontaneous_share` with the single direct root `agent.affect.sharing_urge`;
- `proactive_inquiry` with the single direct root `agent.affect.curiosity`.

The engine first computes the ordinary domain strength. If that strength is below
its normal threshold, the rule ends there. If it passes, the engine validates the
current Surface projection and checks `Surface.initiative >= minimum_initiative`.

Initiative is an admission gate, not a score contribution. It never changes the
domain strength and it never grants action permission.

```text
domain motive strength
        ↓
ordinary minimum-strength check
        ↓
optional Surface.initiative admission
        ↓
Intent candidate
        ↓
ActionPolicy
```

A missing, stale or invalid Surface fails closed. A below-threshold initiative
produces no candidate while keeping the already-computed domain strength in the
existing `IntentScoreTrace`.

## Deliberate non-effects

This is not a global "sadness blocks contact" rule. `reach_out`,
`scheduled_follow_up`, `respond` and other Intent kinds cannot declare this gate.
If sadness later has its own contact-seeking behavior, that is a separate Intent
path.

The gate does not add a second trace contract. Existing `IntentScoreTrace` fields
carry the Surface refs and reason code. This keeps the implementation bounded and
avoids a parallel admission-record hierarchy.

Legacy rules that omit `minimum_initiative` keep the previous ruleset hash shape.
