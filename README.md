# Mind Runtime

Mind Runtime is an external mind runtime for agents. It turns authoritative
Evidence into Observation and Effective State, compiles factual Context, and
uses a deterministic Emotional Transition to produce Projected Internal State.
Intent/Scheduler and ActionPolicy decide what may be attempted before bounded
Decision Context, Agent expression, ExpressionGuard, and Commit. LLMs may help
with typed semantic candidates and expression, but own no Persona, state,
Intent, policy, memory, lifecycle, or final numeric authority.

## Verified V0.x boundary

V0.x validates Companion Agents only: Kayla first, Lara second.
Xiyue is currently only a Shared User State consumer and does not enter the
full affective pipeline.
General Agent Runtime remains a North Star, not a verified claim.
Statebar, Xinchao, OB, and MemoraX are references/adapters, not top-level
product modules.
MR-2 history is read-only; native Memory begins only after the D11P review and
MR-4 gates.

This repository is a modular monolith with one canonical pipeline. It is not a
drop-in replacement for any referenced system, and it does not expose their
schemas or terminology as its product API.

## First Product Slice

The frozen Product Slice pipeline is:

```text
Interaction
-> Evidence
-> Observation
-> Effective State
-> Factual Context
-> Deterministic Emotional Transition
-> Projected Internal State
-> Intent / Scheduler
-> ActionPolicy
-> Minimal Decision Context
-> Agent / LLM Expression
-> ExpressionGuard
-> Commit
```

Semantic LLM output is an optional typed-candidate input, never affect, Intent,
or Policy authority. `Projected Internal State` is not Canonical State; a
projected transition needs a commit or reconcile boundary before it becomes
canonical. Historical facts cannot resurrect state or reinforce themselves.
ActionPolicy and ExpressionGuard remain separate layers.

### Delivery terms and order

- **MR** — Architecture Milestone; a planning boundary, not a direct development assignment.
- **D** — Delivery Gate / Epic; a collection of work packages with an entry gate.
- **W** — Work Package; the default unit assigned to a development agent.

Implementation follows this order without skipping the walking skeleton:

```text
D0 -> D1 -> D2 -> D2S -> D3 -> D4 -> D5 -> D6 -> D7 -> D7R -> D8 -> D9 -> D10 -> D11S -> D11L -> D11 completion -> D11P
```

MR-4 Native Memory and MR-5 Distributed Runtime are outside the continuous
first-Product-Slice backlog. Read-only research does not authorize a Memory
write path or a later-gate implementation.

## Repository status

| Gate | Current status | Scope |
| --- | --- | --- |
| D0 | Complete | Repository bootstrap, governance, clock/test support, Kayla legacy inventory, and this boundary README are present. |
| D1 | Complete | All 26 typed kernel contract groups are frozen under `src/mind_runtime/contracts/` (interaction; scope/authority/ownership; evidence/observation/state/transition; projection/checkpoint/receipt; situation/appraisal/pattern; affect/dynamics/motivation/policy; decision/expression/trace/governance; replication) with `tests/contract/` green. Schema only — no database, resolver, LLM, or Memory behavior. |
| D2 | Complete | Golden scenario harness under `tests/golden/`: scenario schema + runner (run once / replay / restart / compare), FakeLLM (call_count/prompt_type/response), FakeHistoricalProvider, and all G1~G16 + G13b/G16b acceptance entries collectable with every xfail bound to a future D/W. Test infrastructure only — no production behavior. |
| D2S | Complete | Typed stub pipeline under `src/mind_runtime/pipeline/`: TurnOrchestrator (begin → ingest → stub ports → FakeAgent → guard → ActionReceipt → commit/abort), injectable port Protocols, TraceRecorder. One scenario walks begin_turn → commit_turn; a second aborts on FakeAgent failure with canonical untouched; trace reproduces every stage per interaction. Stubs only — no real lifecycle/dynamics/appraisal/policy. |
| D3 | Complete | Factual plane under `src/mind_runtime/facts/`: InteractionCoordinator lifecycle, append-only idempotent durable Evidence/Observation stores `(scope, id)` backed by the V0.1.4 first-batch tables (interactions/evidence/observations, stdlib SQLite, restart/replay semantics), authority gate (assistant output cannot become user fact), ownership gate (cross-persona writes fail closed), provenance (occurred_at vs received_at distinct). The canonical `TurnOrchestrator.ingest()` admits facts only through `FactIngestPort` — no direct Observation construction (D3 closure batch, ADR-0001). Golden G8 (assistant self-pollution), G11 (scope isolation), G9a (delayed-event ordering info), G15a (cross-persona ingest fail-closed) green; G9b/G15b xfail until D4/D5. No affect/Situation/LLM. |
| D4 | Complete | Canonical state plane under `src/mind_runtime/state/`: frozen lifecycle vocabulary (ACTIVE/IMPROVING current-like; RESOLVED/COMPLETED/CANCELLED/SUPERSEDED terminal; EXPIRED validity outcome), ttl/indefinite/event_only validity policies, FactualReconciler (creation, reaffirm envelope refresh, categorical supersession, explicit terminal transitions, delayed observation anti-rollback, terminal protection), lifecycle-vs-relevance separation (`relevant_until` independent), the authoritative `EffectiveStateResolver` read gate (no raw-status consumers), durable `states`/`state_transitions`/`state_definitions` tables (stdlib SQLite), and the current-turn factual overlay (read-your-writes: visible in-turn, committed on commit, discarded on abort). Golden G2 (reaffirm), G3 (cancelled != expired), G8, G9a, G9b (anti-rollback), G11, G15a green. |
| D5 | Complete | Commit boundary (MR-1C) under `src/mind_runtime/pipeline/` + `src/mind_runtime/replication/`: two-phase TransitionIntent contract (ingest facts commit immediately; turn_commit derived transitions promote only via `commit_turn` with optimistic staleness validation), full TurnProjection assembly (Projection != Canonical), UnitOfWork commit/abort (G13: projection failure never pollutes canonical; G13b: ingested facts survive cognitive abort), TurnCheckpoint stores (in-memory + SQLite) with restart recovery decisions (awaiting_commit never treated as committed; dispatched+SENT reconciles; UNKNOWN never silently aborted), ActionReceipt idempotency and delivery reconcile (sent/unsent/unknown), full trace causal chain Evidence→Observation→State→Projection→Receipt with deterministic replay, Null/InMemory ReplicationPort harnesses with a payload allowlist (projected state never replicated, no physical outbox/inbox tables), and the D5.8 closure: canonical state is durable through the optional `StateBackend` (startup load keeps the highest version per scope+dimension; ingest-committed facts and turn-committed projections persist with their transitions; a fresh orchestrator on the same backend restores canonical after restart — G12a green, G12 composite re-owned to MR-D11 per ADR-0003). Golden G2, G3, G8, G9a, G9b, G10 (replay), G11, G12a (restart), G13, G13b, G15a, G15b green. |
| D6 | Complete | Factual Context compatibility plane under `src/mind_runtime/situation/`: deterministic daypart/elapsed semantics, recently-awake and conversation state, explicit counters/timestamps, interaction recency, and sleep-norm suppression. SituationBuilder consumes only Effective State + Interaction + Clock + explicit counters; it emits no cooldown/media `ready`, `eligible`, `allowed`, or `blocked` verdict. G1 remains green; G16a is re-owned as a strict MR-D9 xfail because ActionPolicy is the sole permission authority. |
| D7 | Complete | Algorithmic Persona/Dynamics primitives under `src/mind_runtime/dynamics/`: versioned PersonaProfile (Trait != Current State), configurable 5/12/20/custom dimension sets, replayable return-to-baseline, Accumulator/EventOnly policies, sensitivity, coupling, contribution trace, and final clamp. EngineEmotionalTransitionPort applies those mechanics once, records the exact Persona version and complete state-after trace, and projects agent affect into the Persona-owned scope with commit/abort boundaries. G7 remains green. |
| D7R | Complete | The canonical orchestrator now runs Factual Context → EmotionalTransition/AssessmentTrace → candidate Intent → ActionPolicy. ResolvedAppraisal and Motivation are no longer canonical runtime hops or exported contracts; Situation policy verdicts are removed; the seven-case frozen/compressed executable comparison passes. |
| D8 | Complete | One deterministic emotional-transition step now combines the current atomic affect vector, elapsed time, fixed Persona, trusted typed events, optional bounded read-only history, and confidence-gated semantic candidates. Unknown, low-confidence, conflicting, wrong-Scope, and unavailable-provider paths abstain or fail closed; complete contribution, route, evidence, and history lineage is retained. ADR-0005 makes the affect vector commit/abort atomically. G6, G16, and G16b are green. |
| D9 | Complete | Deterministic configuration-owned Intent scoring with contribution traces; append-only legal lifecycle; atomic in-memory and two-table SQLite persistence; restart-safe due/expiry Scheduler that wakes only for reconsideration; deterministic ActionPolicy for schedule, interruption, pending reply, cooldown, media, and resources; ordered candidate fallback in the one canonical orchestrator; no-dispatch affect commit; and SENT-only receipt completion. G4, G5, G14, G16a, and G24 are green. |
| D10 | Complete | Bounded expression runtime under ADR-0007: typed `DecisionContext` compilation with qualitative affect bands and no raw numeric provider leakage; deterministic provider/diagnostic rendering with trust separation and exact budgets; registered deterministic guard chain (ForbiddenOpening/PrefixDedup/TemporalGrounding, structural-before-content, fixed violation order); bounded rewrite coordinator (max_rewrites cap, immutable attempt trace, ACCEPT/REJECT only, provider failure aborts); read-only same-Scope `PreviousExpressionPort` with no write surface; the one canonical orchestrator expression path (previous -> compile -> coordinate) preserving Policy/Intent/receipt/commit boundaries; and real G14 exercising the whole chain. G14 green; exactly G12 and G25-G28 remain later-gate strict xfails. |
| D11S | Complete | Deterministic fixed-clock certification is closed at `certified_code_head` `25020c9`: real 30/90-day canonical horizons are bounded and byte-replayable; model swaps preserve D8-D10 decisions; repeated history does not amplify; composite restart restores only the existing durable Fact/State/Intent/Checkpoint planes; canonical report artifacts bind exact source/input/runtime hashes. G12 and G25-G27 are green; only G28 remains strict xfail. |
| D11L | Blocked | Blocked by the external environment. All eleven mandatory live-entry fields remain unavailable; no host, eligible traffic, accepted owner, operational threshold, privacy approval, kill-switch/rollback exercise, or live wall-clock evidence exists. |
| D11 | Incomplete | D11S fixed-clock certification passed, but live shadow validation was not performed. `READY FOR D11L: YES` authorizes only a separately reviewed D11L design/environment gate. |
| D11P | Blocked | Agent onboarding and productization wait for their named gates. |

The D0-D11S rows record delivered outputs only. D11S Contract, Golden, static,
coverage, persistence/restart, and deterministic certification gates are closed.
Live shadow validation remains blocked and unperformed. D11 is incomplete;
neither `READY FOR D11L: YES` nor D11S completion authorizes D11P, MR-4, or MR-5.

## Local verification on Windows

Use Python 3.12 or later and run the full quality gate from the repository
root:

```powershell
python -m venv .venv
& '.\.venv\Scripts\python.exe' -m pip install -e '.[dev]'
& '.\.venv\Scripts\python.exe' -m pytest -q
& '.\.venv\Scripts\python.exe' -m ruff check .
& '.\.venv\Scripts\python.exe' -m ruff format --check .
& '.\.venv\Scripts\python.exe' -m mypy src tests
& '.\.venv\Scripts\python.exe' -m coverage run -m pytest
& '.\.venv\Scripts\python.exe' -m coverage report --show-missing
```

Passing these commands verifies the current repository checks; it does not
claim a completed Product Slice, a production deployment, or implemented D10
behavior.

## Governing references

- [Repository governance](AGENTS.md)
- [ADR template](docs/adr/0000-template.md)
- [ADR-0004 compressed topology](docs/adr/0004-compress-cognitive-topology.md)
- [ADR-0005 atomic affect vector](docs/adr/0005-atomic-affect-vector-projection.md)
- [ADR-0006 separate Intent authority](docs/adr/0006-separate-intent-authority.md)
- [D7R compressed runtime and onboarding design](docs/superpowers/specs/2026-08-22-d7r-compressed-runtime-and-agent-onboarding-design.md)
- [D8 integration report](docs/superpowers/plans/2026-08-22-d8-integration-report.md)
- [D9 integration report](docs/superpowers/plans/2026-08-22-d9-integration-report.md)
- [V0.1.4 development baseline](docs/Mind%2520Runtime%2520V0.1.4%2520%E5%BC%80%E5%8F%91%E6%80%BB%E7%BA%B2%E5%92%8C%E9%9C%80%E6%B1%82%E5%9F%BA%E7%BA%BF.md)
- [V0.1.4 phased assignment plan](docs/Mind%2520Runtime%2520V0.1.4%2520%E5%88%86%E6%AD%A5%E5%BC%80%E5%8F%91%E4%B8%8E%E5%88%86%E5%B8%83%E6%B4%BE%E5%8D%95%E6%80%BB%E7%BA%B2.md)
- [Kayla legacy rule inventory](docs/legacy/kayla-rule-map.md)
