# D11S Deterministic Certification and D11L Entry Design

**Status:** Approved after independent architecture-entry review

**Authority:** ADR-0008, ADR-0003, ADR-0004, ADR-0007, the accepted D7R design,
and the D10 integration report.

**Scope:** D11S implementation design plus D11L entry conditions. D11L host
integration, D11P onboarding, Native Memory, distributed runtime, deployment,
and release are excluded.

## 1. Goal

Produce reproducible repository-owned evidence that the compressed Product
Slice remains bounded, replayable, model-isolated, history-safe, and restart
consistent over fixed 30-day and 90-day inputs. Preserve an honest boundary:
D11S is deterministic certification, not live Kayla shadow validation.

## 2. Gate Topology

```text
D10 accepted at be4b260
  -> D11S fixed-clock certification
  -> D11L separately designed real shadow validation
  -> D11 completion decision
  -> D11P onboarding/productization
```

D11S can authorize only D11L design/integration. D11L alone cannot authorize
D11P unless a final D11 integration review accepts both D11S and D11L evidence.

## 3. Non-Negotiable Boundaries

1. The one canonical `TurnOrchestrator` remains the only Product Slice
   decision path.
2. Validation code may schedule inputs, advance a Clock, compose existing
   ports/backends, snapshot outputs, calculate digests, and evaluate
   invariants. It may not reproduce Transition, Intent, Policy, Expression,
   commit, or reconcile business logic.
3. LLM/provider output may write prose only. Model swap cannot alter the
   deterministic internal-decision digest.
4. Historical Context remains bounded and read-only. Retrieval cannot touch,
   reinforce, promote, persist, or become Persona.
5. D11S adds no Native Memory, MemoryCandidate, Memory table, Memory writeback,
   automatic Persona learning, background worker, remote service, or UI.
6. Every simulation uses an injected Clock. Production code may not read the
   system clock directly.
7. Fixed inputs and manifests are immutable, stable ordered, and hashed over
   their actual serialized UTF-8 bytes.
8. A 90-day virtual horizon is never reported as 90 days of wall-clock
   operation.
9. D11S failures produce no automatic rule, Persona, threshold, or policy
   mutation. They are evidence for a later reviewed change.
10. D11S cannot change a protected runtime contract without a new ADR.

## 4. Package Boundary

Create `src/mind_runtime/validation/` as a certification layer:

- `contracts.py` — frozen, slotted certification inputs, digests, invariant
  results, and reports;
- `schedule.py` — validates and stable-orders fixed simulation events;
- `composition.py` — constructs the canonical runtime with existing ports and
  durable backends; contains no business decision rules;
- `horizon.py` — advances the injected Clock, submits scheduled events, invokes
  existing scheduler/orchestrator entry points, and captures checkpoints;
- `digest.py` — canonical serialization and SHA-256 evidence digests;
- `invariants.py` — pure checks over captured authoritative records;
- `model_swap.py` — executes two complete canonical turns from identical
  pre-turn durable state and frozen inputs, then compares captured authority;
- `history_audit.py` — verifies repeated surfacing does not mutate or multiply
  historical influence;
- `restart.py` — destroys the first composition, creates a fresh composition
  over the same SQLite files, and compares authoritative snapshots;
- `report.py` — writes canonical JSON evidence, a byte-hashed artifact
  manifest, and a human-readable summary from the same typed result.

`validation` may import public contracts and public composition/runtime ports.
No existing domain package may import `mind_runtime.validation`.

The canonical certification composition explicitly constructs
`FactIngestService` with `SqliteFactBackend`, `ResolverEffectiveStatePort` with
`EffectiveStateResolver` and `StateDefinitionRegistry`, `SituationBuilder`,
`EngineEmotionalTransitionPort`, `BoundedHistoricalContextAdapter`,
`DeterministicIntentEngine`, `IntentLifecycleService` with
`SqliteIntentBackend`, `DeterministicActionPolicy`, `DecisionContextCompiler`,
`DeterministicContextRenderer`, `DeterministicExpressionGuardChain`,
`FixedPreviousExpressionPort` or an explicit disabled previous-expression
port, and `DeterministicExpressionCoordinator`, then supplies them to the one
`TurnOrchestrator`. It explicitly supplies policy resources, Persona, effect
rules, semantic-provider mode, durable State/Checkpoint backends, and the
in-memory ReceiptRegistry. It exposes an exact concrete component/config
inventory and fails construction if any `Stub*` implementation, implicit
orchestrator default, or unhashed config is present.

## 5. Typed Certification Records

All records are frozen and slotted. IDs and string labels are non-empty.
Datetimes are aware UTC.

### SimulationEvent

```text
event_id: str
at_offset: timedelta
evidence: tuple[Evidence, ...]
historical_context: HistoricalContextBundle | None
expected_path: str
```

Events are unique by `event_id`; offsets are non-negative. Ordering is
`(at_offset, event_id)`. Inputs sharing an offset are applied in that order.
The schedule contains no callable or mutable payload.

### CertificationPlan

```text
certification_id: str
source_head: str
persona_version: str
runtime_config_manifest_sha256: str
horizon_days: Literal[30, 90]
started_at: datetime
events: tuple[SimulationEvent, ...]
checkpoint_interval: timedelta
```

`source_head` is injected from and must equal the checked-out Git HEAD at
execution; it is not written into a tracked file that would change that HEAD.
The checked-in horizon JSON is a plan template containing the event/schedule
bytes. The runtime CertificationPlan binds those template bytes, current HEAD,
and the verified manifest hash without rewriting an input file. The horizon is
exactly 30 or 90 virtual days. The checkpoint interval is positive and cannot
exceed one day. The plan is invalid unless the referenced manifest exists and
its actual canonical UTF-8 bytes match `runtime_config_manifest_sha256`.

### RuntimeConfigManifest

```text
manifest_version: str
components: tuple[RuntimeComponentConfig, ...]
fixture_artifacts: tuple[InputArtifactRef, ...]
recovery_horizon_days: int
convergence_tolerance: str
```

`RuntimeComponentConfig` contains `component_id`, `schema_version`, canonical
JSON `payload`, and `payload_sha256`. The payload contains the actual complete
effective constructor values, not only a digest. `runtime-config.json` must
contain exactly one payload for each of: State definitions, Persona profile,
fact ingest, effective-state resolver, situation builder, emotional effects,
historical-context adapter, Intent engine/lifecycle, ActionPolicy,
PolicyResources, decision-context compiler, context renderer, expression
guard, expression coordinator, previous-expression mode/value, checkpoint
policy, semantic-provider mode/value, and ReceiptRegistry mode. Disabled
features are explicit payloads; an omitted implicit default is invalid.

`InputArtifactRef` contains a repository-relative logical path, byte length,
and SHA-256 of the actual file bytes. It binds both horizon templates, both
expression-provider fixtures, the G27 history fixture, and the G12 restart
fixture. Provider fixture hashes therefore cover the actual scripted response
bytes.

Typed decoder functions validate each payload hash and decode it into the
existing production constructor types. Unknown/missing/duplicate component
IDs, unknown keys, schema drift, a digest-only entry without payload, or an
artifact byte mismatch fail closed. This manifest is the complete
deterministic runtime-input boundary: changing any payload, provider fixture,
recovery window, or tolerance changes the canonical manifest hash. Provider
identity and expression prose remain excluded from the internal decision
digest, but the exact provider fixtures used by certification remain bound as
inputs.

Authoritative input bytes are checked in at:

- `certification/d11s/inputs/runtime-config.json`;
- `certification/d11s/inputs/horizon-30.json`;
- `certification/d11s/inputs/horizon-90.json`;
- `certification/d11s/inputs/model-swap-left.json`;
- `certification/d11s/inputs/model-swap-right.json`;
- `certification/d11s/inputs/history-g27.json`;
- `certification/d11s/inputs/restart-g12.json`.

Tests may derive helpers from these files but cannot substitute test-only input
objects for certification evidence.

### DailyDecisionDigest

```text
virtual_day: int
canonical_state_hash: str
pending_intent_hash: str
transition_trace_hash: str
policy_decision_hash: str
checkpoint_recovery_hash: str
```

`checkpoint_recovery_hash` covers durable checkpoint status plus the
recovery/reconcile decision, not an unavailable durable ReceiptRegistry.

Expression prose, provider identity, wall-clock duration, temporary database
paths, and nondeterministic process identifiers are excluded. Every included
record is stable ordered by its domain identity before hashing.

### InvariantResult

```text
code: str
passed: bool
observed: str
expected: str
evidence_refs: tuple[str, ...]
```

An invariant without evidence references is invalid. A report is accepted only
when every required invariant is present exactly once and passes.

### CertificationReport

```text
certification_id: str
source_head: str
input_sha256: str
runtime_config_manifest_sha256: str
virtual_horizon_days: int
wall_clock_execution_seconds: float
first_run_daily_digests: tuple[DailyDecisionDigest, ...]
replay_daily_digests: tuple[DailyDecisionDigest, ...]
invariants: tuple[InvariantResult, ...]
certification_sha256: str
```

`input_sha256` covers the exact checked-in plan-template and scheduled-event
bytes; source identity is independently covered by `source_head`. The separate
`runtime_config_manifest_sha256` covers every effective runtime configuration
and provider fixture listed above. `certification_sha256` covers both input
identities, source identity, virtual horizon, daily digests, and invariants
while excluding wall-clock seconds and itself. Replay equality uses this hash.

The writer also emits an `ArtifactManifest` containing logical path, byte
length, and `bytes_sha256` over the actual written UTF-8 JSON bytes. The
artifact-byte hash is external to the report so it does not create a recursive
self-hash. Wall-clock seconds remain present in the report as evidence metadata
but cannot make semantic replay comparison nondeterministic.

The committed report names `certified_code_head`, the merged D11S.1-.7
runtime/test/input commit exercised before D11S.8 report/governance-only
changes. A later `report_commit_head` contains that report
and points back to the certified code head. After review and merge,
`merged_verification_head` identifies main. Post-merge verification evidence is
written outside tracked repository content under the ignored
`.artifacts/d11s/<merged_verification_head>/` path with byte lengths and hashes;
it is never committed back. This prevents report evidence from changing the
HEAD it claims to certify.

## 6. Fixed-Clock Long-Horizon Certification

Each 30-day and 90-day plan includes:

- neutral no-op periods;
- registered positive and negative typed events;
- repeated idempotent evidence;
- explicit contradictory/false historical context followed by authoritative
  current evidence;
- long gaps exercising return-to-baseline;
- values near upper and lower dimension bounds;
- due, expired, and reconsidered Intent lifecycle points;
- at least one restart checkpoint.

The simulator advances directly to the next event or checkpoint. It does not
sleep and does not pretend elapsed wall time. At every virtual day boundary it
captures a `DailyDecisionDigest`.

The replay run starts from empty temporary storage, reuses the exact immutable
plan bytes, and must produce the same ordered daily digests and final
authoritative snapshot.

Required invariants:

- every scalar State value is finite and within its StateDefinition bounds;
- clamp occurs only at configured bounds and is trace visible;
- time recovery under the same Clock produces byte-identical daily digests;
- days without new authoritative events produce only registered time dynamics;
- replay contains no extra Evidence, Observation, Transition, Intent,
  checkpoint, or receipt;
- repeated idempotent evidence cannot create additional state excitation;
- false or contradicted history cannot write Canonical State directly; its
  current-decision contribution is trace bounded, and later authoritative
  current Evidence produces a replayable correction without the historical
  item becoming a new cause unless it is explicitly supplied again;
- Assistant expression never enters Evidence without a separate external
  authority admission.

## 7. Model-Swap Certification — G25

G25 uses two supported expression-provider doubles with deliberately different
accepted prose. Each side starts in a separate durable store copied from the
same pre-turn authoritative snapshot and receives the same frozen turn-input
bytes and RuntimeConfigManifest. Each side independently executes the complete
real canonical turn through Evidence admission, D8 transition, D9 Intent and
ActionPolicy, D10 context compilation, expression, guard, and commit. The
records being compared are captured outputs; none is supplied as an input.

Both AgentPorts must be called exactly once and must record byte-identical
`ProviderExpressionContext` bytes. The accepted expression strings must differ.
Only after both full turns complete does certification independently capture
and compare each side's D8-D10 authoritative records.

The compared internal digest includes:

- accepted typed events and EmotionalTransition contribution trace;
- projected and committed internal State;
- candidate ordering and selected Intent;
- ActionPolicy decision, constraints, and reason codes.

It excludes expression text and provider identity. The expression values may
differ; every internal field above must be byte-identical. Provider failure is
a separate fail-closed case and cannot be normalized into a successful swap.

D11S does not claim invariance across arbitrary semantic-candidate providers.
The semantic path is fixed identically or disabled in both G25 runs. Live
semantic-model drift belongs to D11L observation and cannot silently change
internal authority.

## 8. History Anti-Amplification — G27

G27 supplies one stable `HistoricalContextItem` plus one explicitly associated
stable `PatternMatchSummary` in three successive retrieval bundles. The summary
has a stable `summary_id`, stable `match_count` and `confidence`, and
`matched_refs` containing the item identity. Before and after each run,
certification records the immutable bundle hash and authoritative database
counts.

Acceptance requires:

```text
history.unique_source_count = 1
history.retrieval_count = 3
history.influence_multiplier = 1.0
history.reinforced = false
```

The real D8 effect path must emit its history contribution/impulse reference
from `PatternMatchSummary.summary_id`. Certification records three indexed
per-decision influence records. Each record must contain exactly one occurrence
of that summary ID and the same manifest-bound effect amount. Retrieval
metadata cannot change `match_count`, `confidence`, or the configured effect
amount, and three retrievals cannot be summed into triple evidence or create a
new causal relation. No history-facing port may expose `write`, `touch`,
`reinforce`, `promote`, or Persona-update methods.

False-history reversibility uses a paired control trajectory. The false-history
and control runs share all frozen inputs except the false historical bundle.
The false history cannot directly create Evidence, Observation, or State. At
the correction event, authoritative current Evidence must cause a traced
transition, and its trace must exclude the old item and summary refs unless
they are explicitly supplied again. After the manifest-owned recovery horizon,
the affected state dimension must converge to the control within the
manifest-owned deterministic tolerance. Both values are hashed inputs; a test
or runner cannot select them dynamically.

## 9. Composite Restart Certification — G12

G12 creates one temporary certification directory containing the existing
SQLite durable stores for facts, canonical state, Intent lifecycle, and
checkpoints. The first canonical composition:

1. admits authoritative user Evidence and Observation;
2. commits user and relationship-scoped State;
3. creates a due/pending Intent;
4. records a checkpoint containing the action id and an UNSENT, SENT, or
   UNKNOWN delivery status used by the existing restart recovery decision;
5. reads an optional immutable HistoricalContextBundle;
6. closes every store and drops every runtime object.

A fresh composition opens the same files and reconstructs the authoritative
state through public backend APIs. Acceptance compares identities, versions,
scope, status, references, canonical hashes, and the deterministic checkpoint
recovery/reconcile decision. `ReceiptRegistry` remains explicitly in-memory;
D11S does not fabricate receipt durability. The read-only historical bundle
hash must be unchanged and no history write record may exist.

The scenario contains no Native Memory object or table. The G12 fixture prose
is updated to say `durable product-slice planes + read-only history`, not
`Memory writeback`.

## 10. Failure Handling

Certification fails closed on:

- Git HEAD/input manifest mismatch;
- naive or non-UTC time;
- duplicate event or invariant identity;
- system-clock access inside the certification path;
- non-finite or out-of-bounds State;
- missing required trace references;
- unequal replay digest;
- unequal internal model-swap digest;
- incomplete or mismatched RuntimeConfigManifest;
- history bundle mutation, duplicate summary influence, failed correction
  convergence, or any history write surface;
- incomplete durable-store close/reopen;
- restart snapshot mismatch;
- an unexpected provider, LLM, network, background-thread, or remote-service
  call.

A failed certification writes a report with failing invariant evidence but
does not update runtime configuration, Persona, policies, Goldens, or gate
status automatically.

## 11. D11L Entry Contract

D11S produces a requirements document for D11L but no host adapter. D11L
cannot begin until a separately reviewed design names all of:

- the real Kayla host and deployment boundary;
- eligible interaction and exclusion definitions;
- exact feature-flag owner and default-OFF behavior;
- shadow, context-assist, and controlled-takeover phase transitions;
- sampling method and minimum sample;
- wall-clock observation duration;
- privacy classification, field-level redaction, and trace retention;
- kill-switch owner, maximum activation latency, and test procedure;
- rollback owner, rollback target, and recovery verification;
- acceptance, pause, abort, and incident thresholds;
- model/provider versions and drift handling.

Synthetic or repository-only evidence cannot fill any missing item. Until all
items are approved and the named environment exists, status is `D11L:
BLOCKED_BY_EXTERNAL_ENVIRONMENT`.

## 12. Test and Golden Strategy

D11S implementation begins with strict RED tests while G12 and G25-G27 remain
xfail. W-level tests cover contracts, schedule validation, canonical
serialization, horizon invariants, model swap, history audit, restart, report
hashing, and import direction.

The Golden transition order is:

1. implement and independently review the owning D11S component;
2. replace `UnimplementedPipeline` with the real canonical certification
   adapter;
3. remove only that scenario's strict xfail;
4. run the complete suite and owner audit.

D11S closes with G12 and G25-G27 green and exactly G28 remaining strict xfail
for D11P. Required final gates:

- all tests pass except exact strict xfail G28;
- Ruff check and format pass;
- strict mypy passes;
- statement and branch coverage are 100%;
- import direction is locked;
- frozen architecture documents remain unchanged except ADR-0008-authorized
  G12/D11 wording;
- every W has an independent review with no open Blocker or Important;
- clean branch and worktree;
- an integration report records exact base/certified-code/report-commit HEAD
  identities, complete runtime/input hashes, virtual and wall-clock durations,
  Golden changes, exclusions, and
  `READY FOR D11L: YES/NO`.

## 13. Work-Package Decomposition

The implementation plan will use these independently reviewable units:

1. **D11S.1 contracts and canonical digest** — typed records, stable JSON,
   hashes, import direction.
2. **D11S.2 fixed schedule and horizon runner** — Clock-driven 30/90-day
   execution through the canonical composition.
3. **D11S.3 boundedness/replay certification** — invariant library, replay,
   G26.
4. **D11S.4 model-swap certification** — provider variants, internal digest,
   G25.
5. **D11S.5 history anti-amplification** — repeated surfacing audit, G27.
6. **D11S.6 composite restart** — existing durable planes, read-only history,
   corrected G12.
7. **D11S.7 reports and D11L entry package** — deterministic artifacts,
   external-condition checklist, no host implementation.
8. **D11S.8 integration gate** — exact Goldens/xfails, governance status,
   independent integration review, `READY FOR D11L` only.

## 14. Completion Semantics

Successful D11S wording is exactly:

```text
D11S: COMPLETE
FIXED-CLOCK 30/90-DAY CERTIFICATION: PASS
LIVE SHADOW VALIDATION: NOT PERFORMED
D11: INCOMPLETE
READY FOR D11L: YES
READY FOR D11P: NO
```

No D11S artifact may shorten that to `D11 COMPLETE`.
