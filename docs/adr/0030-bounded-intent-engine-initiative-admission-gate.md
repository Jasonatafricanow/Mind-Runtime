# ADR-0030: Initiative admission after domain scoring

- Date: 2026-09-25
- Status: ACCEPTED
- Production activation: BLOCKED_BY_PERSONA_POLICY_BINDING

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

## 2026-09-28 threshold authority clarification

`minimum_initiative` is not a global personality-neutral tuning constant.

The current `Surface.initiative` answers:

> how much proactive pressure exists right now?

The threshold answers a different question:

> for this Persona, how much proactive pressure is required before a
> spontaneous motive is allowed to become an Intent candidate?

Therefore the authority chain is:

```text
fast/internal state
    -> Surface.initiative

published Persona revision
    -> proactive admission threshold(s)

IntentEngine
    -> compares current initiative with Persona-owned threshold

ActionPolicy
    -> still owns final permission
```

Two Personas may legitimately make different choices at the same
`Surface.initiative` value. A more proactive Persona may admit
`spontaneous_share` or `proactive_inquiry` at a lower initiative level; a
more restrained Persona may require a higher level.

The execution field remains `IntentRule.minimum_initiative`, but production
composition must source that value from the bound/published Persona policy
rather than a single global runtime constant.

Production activation therefore remains blocked until Persona publication /
runtime composition provides the threshold authority. Shadow calibration may
validate behavior ranges, but it must not be interpreted as searching for one
universal threshold for every Persona.
