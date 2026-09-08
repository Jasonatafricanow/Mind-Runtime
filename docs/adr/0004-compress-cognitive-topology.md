# ADR-0004: Compress the cognitive topology after D7

- **Date:** 2026-08-22
- **Status:** Accepted

## Problem

The V0.1.4 pipeline turns explanatory distinctions into mandatory runtime
hops. Situation already owns cooldown/media verdicts also assigned to D9
ActionPolicy; ResolvedAppraisal owns motivation signals while Motivation is
derived again from ProjectedMindState; Persona/history can be applied more than
once; and correlated internal representations can be repeated to the base
model.

## Previous Assumption

Separating Situation, SemanticAppraisal, ResolvedAppraisal, Dynamics,
Motivation, and DecisionContext as protected first-class contracts was assumed
necessary to preserve a complete and explainable emotional causal chain.

## New Evidence

- D6 and the D9 baseline assign cooldown and media eligibility to different
  authorities.
- `ResolvedAppraisal.motivation_signals` has no input path into the separate
  `MotivationPort`, which re-derives desire from ProjectedMindState.
- The canonical turn path passes `elapsed=0` to D7 Dynamics, so layer closure
  does not yet prove long-horizon behavior.
- The approved design review concluded that authority separation and complete
  contribution trace preserve trust without separate computation services.

## Decision

The active design authority is
`2026-08-22-d7r-compressed-runtime-and-agent-onboarding-design.md`.
ADR-0004 and that design supersede conflicting topology clauses in the three
V0.1.4 baselines. Preserve factual authority, Canonical/Projection, commit,
Scope/Ownership, ActionPolicy, ExpressionGuard, replay, and Persona/State
boundaries. Narrow Situation to factual Context; make one deterministic
Emotional Transition the computational authority; migrate useful appraisal
explanation into an Assessment/Contribution Trace; remove appraisal-owned
motivation signals; introduce durable reconsiderable Intent; and deliver Agent
import/creation as D11P after Kayla validation.

This ADR authorizes no D8 production implementation by itself.

## Rejected Alternatives

- Continue the frozen D8 topology unchanged: rejected because it preserves
  demonstrated duplicate ownership before product evidence.
- Remove emotional appraisal logic: rejected because traceable emotional
  causality remains a product requirement.
- Give semantic and personality decisions to the LLM: rejected because model
  and context variance would own runtime behavior.
- Implement Agent onboarding immediately: rejected because its numeric Persona
  compiler must be calibrated after Kayla shadow evidence.

## Affected Contracts

Protected categories affected in later D7R work are Situation, Dynamics input,
SemanticAppraisal/ResolvedAppraisal, Motivation/Intent, ActionPolicy input,
DecisionContext, and trace. D3-D5 authority and persistence contracts remain
unchanged in D7R.1.

## Migration

D7R.1 changes authority documents and stages Goldens only. Later D7R work
introduces new contracts test-first, switches the one canonical orchestrator,
and removes compatibility adapters before the D7R integration gate. Existing
Canonical State requires no data migration. Rollback reverts D7R commits and
restores the V0.1.4 topology before any D8 production data exists.

## Acceptance Tests

- Governance audit proves all baselines point to ADR-0004 and the approved
  design.
- README and AGENTS audit proves D7R is the active gate and D8 remains blocked.
- G24-G28 are strict xfails with owners MR-D9, MR-D11, and MR-D11P.
- Existing D3-D7 tests and Goldens remain green.
- Full pytest, Ruff, mypy strict, and coverage gates pass.
