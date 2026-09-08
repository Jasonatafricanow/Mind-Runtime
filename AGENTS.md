# Mind Runtime Repository Governance

## Scope and authority

These instructions apply to the entire repository. The following three V0.1.4
documents remain the historical architecture baseline:

- `docs/MindRuntimeV0.1.4完整版_开发总纲_需求基线_分布派单.md`
- `docs/Mind%20Runtime%20V0.1.4%20分步开发与分布派单总纲.md`
- `docs/Mind%20Runtime%20V0.1.4%20开发总纲和需求基线.md`

ADR-0004 through ADR-0008 and the approved D7R/D9/D10/D11S designs are the
active authority where the compressed topology conflicts with V0.1.4:

- `docs/adr/0004-compress-cognitive-topology.md`
- `docs/adr/0005-atomic-affect-vector-projection.md`
- `docs/adr/0006-separate-intent-authority.md`
- `docs/adr/0007-bound-expression-authority.md`
- `docs/adr/0008-split-d11-certification-and-live-shadow.md`
- `docs/superpowers/specs/2026-08-22-d7r-compressed-runtime-and-agent-onboarding-design.md`
- `docs/superpowers/specs/2026-08-22-d9-intent-scheduler-action-policy-design.md`
- `docs/superpowers/specs/2026-08-23-d10-bounded-expression-runtime-design.md`
- `docs/superpowers/specs/2026-08-23-d11s-deterministic-certification-and-d11l-entry-design.md`

`docs/OB3.2.0源码审计与MR-4吸收矩阵.md` is MR-4 evidence. It is not
authority to alter the D0-D11 delivery pipeline.

## Change control

When new evidence or a new requirement conflicts with a frozen contract, use
this sequence:

```text
new evidence or requirement -> ADR -> Contract/Golden Test -> implementation
```

Do not change code first and justify it retrospectively in documentation. The
following protected contract categories cannot change without an ADR:

1. Observation semantics.
2. State semantics.
3. Memory semantics.
4. Scope, Authority, and Ownership.
5. Replication contract.
6. TurnProjection and commit boundary.
7. Dynamics.
8. SemanticAppraisal input, EmotionalTransition and Assessment/Contribution Trace.
9. ActionPolicy boundary.
10. ExpressionGuard boundary.
11. DecisionContext.
12. Intent lifecycle and scheduling.

## Execution boundary

V0.x is companion-first, a modular monolith, and one canonical pipeline. The
required delivery order is `D0 -> D1 -> D2 -> D2S -> D3 -> D4 -> D5 -> D6 ->
D7 -> D7R -> D8 -> D9 -> D10 -> D11S -> D11L -> D11 completion -> D11P`. W is
the only default development assignment unit.

## Non-negotiable boundaries

1. Mind Runtime is not an upgraded Xinchao product.
2. The kernel must not fix the schema to 12 dimensions.
3. OB API semantics must not become the Memory domain model.
4. Business logic must consume Effective State, not raw state.
5. LLMs may not mutate Canonical State or choose final affect values.
6. Assistant output is not automatically Evidence.
7. History facts cannot become Persona, resurrect old State, reinforce
   themselves, or bypass a new traced EmotionalTransition.
8. Business rules cannot exist only in prompts.
9. Completed, cancelled, resolved, or superseded states cannot decay into
   expired.
10. V0.x must not split into microservices unless explicit performance or
    security-isolation evidence and an ADR justify that boundary.
11. TurnProjection is not Canonical State; projected transitions require a
    commit or reconcile boundary.
12. ActionPolicy and ExpressionGuard remain separate layers.
13. MR-2 history access is read-only and cannot introduce Memory writeback or
    consolidation.
14. Genuine semantic ambiguity cannot be hard-coded merely to reduce LLM use.
15. Private affect or relationship state cannot be written across Persona
    scope; Ownership checks fail closed.
16. Uncommitted Projected State cannot be synchronized or replicated.
17. OB names such as bucket, breath, hold, grow, feel, and dream cannot become
    core domain APIs.
18. Embeddings, BM25, automatic relations, and retrieval caches are derived
    and rebuildable, never authoritative Memory truth.
19. Retrieved, surfaced, or activated Memory cannot automatically reinforce
    itself.
20. Similarity alone cannot create a causal relation.
21. OB thresholds, decay parameters, and relation caps cannot be copied and
    claimed applicable to Chinese, Portuguese, or English corpora without
    benchmark and calibration.
22. OB event sourcing, Raft, microkernel, or Rust experiments do not justify
    making the first Product Slice globally event-sourced or distributed.
23. Mem0, OB-native, or any external backend cannot become the unique MR-4
    implementation before provider benchmarking; only after D17 may an ADR
    lock the default Memory engine or provider.
24. Situation/Factual Context provides facts only. ActionPolicy exclusively
    owns cooldown, interruption, media, and resource permission.
25. LLM output may provide bounded semantic candidates or expression. It cannot
    own Persona, Internal State, Intent selection, or Policy permission.

## W-level discipline

- Use one branch/worktree for one bounded W-level objective; do not develop
  directly on the base branch.
- Every W declares its allowed scope, forbidden scope, test entry, and
  review/merge gate. Preserve unrelated work.
- Split and report an oversized W before its scope grows. Do not implement a
  later Delivery Gate.
- For behavior, write tests or executable fixtures before production behavior;
  run targeted verification plus the complete existing suite.
- Require an independent review for every W, then a D-level integration review
  against the current W and Kernel Baseline. Do not release on promises to
  finish missing work later.
- Prework is limited to non-production artifacts. It cannot merge production
  code or define or merge premature APIs whose prerequisite contract has not
  merged.
- At merge time the worktree is clean and has no unexplained skip, xfail, or
  TODO.
- Complete a task report with Branch/Worktree, Base HEAD, Final HEAD, files,
  tests, verification, affected Golden scenarios, contract changes, explicit
  exclusions, gaps, worktree status, and merge recommendation.

## Current gate

D1 (typed kernel contracts), D2 (golden harness), D2S (walking skeleton),
D3 (fact ingestion), D4 (canonical state), D5 (commit boundary), D6
(situation), and D7 (persona/dynamics) are merged. The D3 closure batch
(ADR-0001) restored the frozen V0.1.4 persistence baseline; D4 delivered
the canonical state plane; D5 delivered the commit boundary (two-phase
intents, projection never canonical, UnitOfWork with staleness validation,
checkpoint recovery, receipt reconcile, trace chain, replication harness).
D6 delivers the situation plane under `src/mind_runtime/situation/`:
TemporalSemantics (daypart, replayable under the injected Clock), the
frozen factual context rules (recently_awake, conversation active/idle,
explicit counters/timestamps, interaction recency, sleep-norm suppression),
and SituationBuilder aggregation
(user_activity / conversation_mode / schedule_norm_relevance) consuming
only Effective State + Interaction + Clock + explicit counters — raw state
is never dumped into the Situation. D7 delivers the dynamics plane under
`src/mind_runtime/dynamics/`: PersonaProfile (Trait != Current State),
DimensionSet/DynamicDimensionRegistry (5/12/20/custom named sets —
configuration, never kernel schema), ContinuousReturnToBaseline /
Accumulator / EventOnly policies (replayable, per-dimension dispatch),
DynamicsEngine with an explainable contribution trace and a final clamp
(coupling can never push a dimension out of bounds), the Kayla v0
compatibility profile fixture (parameters in fixture/config, not kernel),
and EngineEmotionalTransitionPort wiring the engine into the canonical pipeline
(providing a `persona` to the orchestrator swaps the stub for the real
engine port). ADR-0002 (D7.7) separates the interaction scope from the
affect projection scope: agent affect projects into the persona's own
agent scope, never the user turn scope, and a user-scope Kayla turn runs
through the real orchestrator with commit/abort boundaries. ADR-0003
(D5.8) wires the durable StateBackend into the orchestrator: canonical
state loads at startup (highest version per scope+dimension), ingest and
turn commits persist states/transitions, restart restores canonical
  (G12a green; G12 composite re-owned to MR-D11). Golden G1, G2, G3, G7,
  G8, G9a, G9b, G10, G11, G12a, G13, G13b, G15a, and G15b are green.

D7R is closed: factual Context, EmotionalTransition/AssessmentTrace, cognitive
Intent, ActionPolicy input, the one canonical orchestrator, and executable
compression evidence are accepted. D8 is closed: typed-event mapping, optional
bounded semantic-candidate routing with abstention, read-only bounded history,
elapsed-time integration, complete evidence/contribution trace, and atomic
affect-vector projection/commit are accepted under ADR-0004 and ADR-0005.
D9 is closed: EmotionalTransition returns accepted typed events instead of a
fixed cognitive Intent; configuration-owned rules score ordered candidates;
append-only Intent versions and transitions persist through in-memory and
SQLite backends; restart-safe Scheduler ticks expire or wake for reconsideration
without execution; ActionPolicy alone owns schedule, interruption, cooldown,
media, and resource permission; and the canonical orchestrator performs
candidate fallback while keeping affect commit independent from dispatch.
G4, G5, G14, G16a, and G24 are green. D10 is closed: ADR-0007 freezes the bounded
expression authority; the canonical orchestrator has one expression path
(previous-expression query -> DecisionContextCompiler -> bounded
ExpressionCoordinator with a deterministic renderer and guard chain); the
provider writes prose only; the read-only PreviousExpressionPort has no write
surface; ExpressionGuard chain evaluation is deterministic and registered
(ForbiddenOpening/PrefixDedup/TemporalGrounding), ActionPolicy and
ExpressionGuard remain separate, guard verdicts never complete an Intent
(SENT-only reconcile), and expression failure never auto-commits projected
affect; real G14 exercises the whole D10 chain. D11S is closed: fixed-clock
30/90-day certification, bounded replay, model-swap isolation, history
anti-amplification, composite restart, and deterministic report publication
are accepted; G12 and G25-G27 are green and only G28 remains a strict xfail.
D11L is blocked by the external environment: its eleven mandatory live-entry
fields remain unavailable, live shadow validation was not performed, and D11
remains incomplete. D11P, MR-4, and MR-5 remain blocked.
