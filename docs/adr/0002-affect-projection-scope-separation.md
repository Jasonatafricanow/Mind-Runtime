# ADR-0002: Affect projection scope separation (D7.7)

- **Date:** 2026-08-23
- **Status:** Accepted

## Problem

The D7 delivery review (2026-08-23) found a P1 blocker: `kayla_v0_profile()`
correctly defines `agent.affect.*` dimensions, but the canonical
`TurnOrchestrator.run()` passes the user interaction scope into
`DynamicsPort.project`; `EngineDynamicsPort` then constructs the projected
`RuntimeState` under that user scope, and the D1 domain contract rejects it
(`ValueError: dimension must use approved <domain>.<name> form`). The
D7.6 workaround of renaming test dimensions to `user.affect.*` bypassed the
real product semantics: Kayla's private affect belongs to the Kayla agent
scope, and per non-negotiable boundary #15 private affect must never be
written across Persona scope.

## Previous Assumption

- The D1 projection contracts (`ProjectedMindState`,
  `TurnProjection`) bind the projected mind state to the turn's scope
  (`projected_mind_state.scope == turn scope`), which was true while the
  only projections were stub projections synthesized inside the turn
  scope (`{scope.domain}.affect.stub`).
- A persona could be treated as a tuple of dimension profiles without a
  persona identity, and the turn scope could stand in for the projection
  scope.

## New Evidence

- `src/mind_runtime/dynamics/kayla_v0.py` defines
  `agent.affect.longing/irritation/anxiety/excitement` under
  `persona_id="kayla_v0"` — the affect belongs to the agent scope, and the
  D1 `RuntimeState` domain rule (`require_domain_key`) makes
  `agent.affect.*` illegal under a user scope.
- `src/mind_runtime/pipeline/orchestrator.py` passed
  `scope=turn.interaction.scope` (user) into `DynamicsPort.project`, so the
  real engine port could never run on the canonical pipeline with an
  agent-domain persona.
- The D7.6 port tests were renamed to `user.affect.*` to pass, silently
  dropping the agent-scope product semantics; G7 only exercised the engine
  through the test-side `DynamicsPipeline`, never the orchestrator wiring.

## Decision

Execute the D7.7 closure: separate the interaction scope (user) from the
affect **projection scope** (the persona's own agent scope), and evolve the
D1 projection contracts minimally so the projected mind state may carry its
real scope:

1. **Projection scope resolution.** `EngineDynamicsPort.project` accepts an
   explicit `projection_scope`; when absent it derives one from the
   persona: agent-domain dimensions -> `Scope(AGENT, persona_id,
   persona_id)`; user-domain dimensions -> the turn scope; mixed domains
   fail closed. The port validates every persona dimension against the
   resolved scope domain before constructing any `RuntimeState`
   (agent.affect.* under a user scope is rejected up front).
2. **ProjectedMindState.scope semantics.** `ProjectedMindState.scope` is
   the scope the projected mind belongs to (the projection scope): for
   agent-domain personas this is the persona's agent scope; otherwise the
   turn scope. The D1 invariant `projected_state.scope == scope` is
   unchanged.
3. **TurnProjection relaxation.** `TurnProjection` keeps the turn scope for
   its context artifacts (observations, `effective_state_before`,
   `transition_intents`), but its `projected_mind_state` may now carry an
   agent/persona scope in addition to the turn scope. This is the minimal
   contract change that makes agent affect projectable; the orchestrator
   remains the only `TurnProjection` builder.
4. **Orchestrator persona identity.** `TurnOrchestrator(persona=...)` now
   takes a `PersonaProfile` (id + dimensions) instead of a bare dimension
   tuple, so the persona id is available to derive the projection scope;
   the default dynamics port is the real engine port whenever a persona is
   provided.
5. **Real integration coverage.** A user-scope Kayla turn runs through the
   real orchestrator: the projected state is `agent.affect.*` scoped to the
   Kayla agent scope, and commit/abort boundaries are tested (commit
   promotes the agent-scoped affect into canonical; abort leaves canonical
   untouched).

## Rejected Alternatives

- **Keep the D1 turn-scope binding and rename Kayla dimensions to
  `user.affect.*`.** Rejected: this was the D7.6 workaround that hid the
  blocker; it contradicts the Kayla legacy inventory and boundary #15
  (agent private affect must live in the agent's persona scope).
- **Derive the projection scope inside the port without an orchestrator
  change.** Rejected: the orchestrator must know the persona id and
  explicitly pass the projection scope for auditability; implicit
  derivation alone leaves the turn scope as a silent fallback.
- **Change `TransitionIntent` scoping too.** Rejected: agent-scoped
  `turn_commit` intents belong to a later gate (the D1 intent machinery
  requires before/after states in the intent scope); D7 projections of
  agent affect carry no intent (the projected dimension differs from the
  effective user dimension), so no intent change is needed now.

## Affected Contracts

Protected contract categories touched (per AGENTS.md change control, this
ADR is the authorization):

- Category 6 (TurnProjection and commit boundary): `TurnProjection`
  validation relaxed — `projected_mind_state.scope` may be an agent/persona
  scope instead of exactly the turn scope. `ProjectedMindState`'s
  `projected_state.scope == scope` invariant is unchanged; its `scope`
  field's meaning is now the projection scope.
- Category 7 (Dynamics): `DynamicsPort.project` gains the optional
  `projection_scope` parameter (additive); `TurnOrchestrator.persona` type
  changes from `tuple[AffectiveDimensionProfile, ...]` to
  `PersonaProfile | None` (additive surface; absence preserves the stub
  behavior).

No change to `RuntimeState` domain rules, `Scope`, ownership, or the
`AffectiveDimensionProfile` trait contract (still no current field).

## Migration

The orchestrator `persona` tuple form is replaced by `PersonaProfile`;
existing callers that pass a tuple must wrap it (only tests do today). The
stub path and the user-domain persona path behave exactly as before
(projection in the turn scope). Rollback: revert the D7.7 commits; the D1
turn-scope binding returns and agent-domain personas cannot project through
the canonical pipeline (the pre-D7.7 state).

## Acceptance Tests

- `tests/dynamics/test_ports.py` — agent affect projects into the
  persona's agent scope; envelope keeps the turn scope; agent dimension
  under an explicit user projection scope fails closed; user-domain
  personas fall back to the turn scope; explicit projection scope wins;
  mixed-domain personas fail closed.
- `tests/pipeline/test_projection.py` — user-scope Kayla turn through the
  real orchestrator: projected state `agent.affect.*` in the Kayla agent
  scope; commit promotes it into canonical; abort leaves canonical
  untouched; the `TurnProjection` envelope keeps the user scope.
- `tests/contract/test_d1_3_projection_checkpoint_receipt.py` — agent-scope
  projected mind states accepted by `TurnProjection`; mismatched
  user-domain scopes still rejected.
- Golden G7 stays green through the test-side `DynamicsPipeline` (the
  fixture's trait profiles cannot drive the engine port directly); the
  canonical orchestrator wiring is covered by the integration tests above.
- Full quality gate: `pytest` green, `ruff check`, `ruff format --check`,
  `mypy --strict`, coverage 100%, clean worktree.
