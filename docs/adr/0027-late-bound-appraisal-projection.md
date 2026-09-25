# ADR-0027: Open appraisal and late-bound runtime projection

- Date: 2026-09-09
- Status: ACCEPTED
- Accepted: 2026-09-09
- User authorization: approved for implementation under MR-LATE-PROJECTION-01.
- Assignment: MR-LATE-PROJECTION-01, P1 Architecture Closure.
- Audited base: a7c347dcfe2bcc0867d9851275bbe5ea1e2c96f8 (local main).

## Problem and verified consumer audit

`emotional_transition/effects.py:123-166` selects the first event kind and
returns `unknown_event_kind` before reading its appraisal. Known recipes use
candidate confidence for the amount and appraisal salience for downstream
authority; meanings, valence and relationship relevance do not drive selection.
`dynamics/ports.py:446-453` additionally requires nonempty impulses and no mapper
abstention for accepted_events. Thus semantic acceptance depends on coverage.

`contracts/emotional_transition.py:159` carries projected state, accepted events
and AssessmentTrace, but no accepted appraisal payload. `expression/context.py`
DecisionContextCompilerInput and compile() have no appraisal input/consumer.
`contracts/expression.py:12` has no meaning kind. An assessment trace reference
does not supply bounded semantic content. Existing OW APPRAISAL telemetry can
display meanings but is neither a durable semantic source nor a cognition seam.
No legal existing Appraisal -> DecisionContext seam was found in this base.

There is also an upstream choke: `glm_provider.py:44-83,220` declares the four
recipe kinds the ONLY legal outputs and rejects any other kind. `zen_provider.py`
also prompts with a finite taxonomy. Opening only the mapper cannot meet the
novel-natural-language acceptance chain. Remove recipe-membership validation and
closed-taxonomy prompt instructions; retain bounded string/schema, confidence,
evidence, transport and egress validation. Known kinds remain illustrative
compatibility examples, never an exhaustive ontology. Add parser/prompt regression
coverage for a novel valid event and malformed/oversized outputs. No transport or
credential changes are included.

## Authority decision proposed for acceptance

Semantic Event is not emotional classification; Semantic Appraisal is not
Affect State; projection is not semantic authority; OW labels are not ontology.
Accepted appraisals retain open strings, not a closed dictionary of meanings.
Provider proposals remain subject to producer validation and trusted evidence.
SemanticAppraisalProducer remains the acceptance owner: successful validated
assembly is recorded as ACCEPTED independently of mapping; model text or an OW
APPRAISAL event alone cannot assert acceptance. The runtime binds that accepted
record to its candidate, interaction and scope before materialization.
Durable acceptance records include owner/version and the route verdict. Router
abstention prevents acceptance on that route, even if a payload was assembled;
payload existence is insufficient. Projection abstention is downstream and cannot
retroactively revoke valid semantic acceptance.
Finite runtime dimensions are computing interfaces owned by current definitions.
Keep all four current affect dimensions and their existing numeric semantics.

Introduce a first-class immutable AppraisalProjectionResult at the current
EffectMapper boundary. Replace its implementation with one deterministic
projector; if the EffectMapper name is retained for callers, it delegates only
and owns no independent mapping rules. Legacy recipes are explicit versioned
compatibility recipes in this same projector, with unchanged amounts, confidence
scaling, bounded-history caps, salience, sensitivity, recovery and coupling.

New recipes may predicate on exact meanings, valence, relationship relevance,
salience and confidence, with explicit bounded context dependencies. They must
not guess a closest affect dimension. V1 supplies no speculative new numeric
recipe for recognition, relief or concern. Absence of a recipe is UNMAPPED.
Legacy event-only operation remains supported with an explicit missing-appraisal
marker and nullable source_appraisal_ref; it must never fabricate ACCEPTED.

## Inputs, materialization and invalidation

Projector input contains validated appraisal (when available), bound candidate,
runtime identity/scope, trusted evidence references, explicitly selected bounded
history, and versioned Persona/state definitions and recipe configuration.
Reject cross-scope/runtime binding, stale/superseded appraisal and invalid lineage.
The projector has no model/provider port, clock reads, random source or I/O.

Result fields: projection_id, status, source_appraisal_ref, source_candidate_ref,
projector_id/version, dependency_digest, effects[], reason_codes[], provenance.
Effects have target domain/scope/dimension, operation, amount/value and source
lineage; they are proposals, never direct state writes or ActionPolicy permission.
Do not treat a longitudinal proposed value as an additive fast affect delta.

The dependency digest is a canonical serialization hash of the complete consumed
input, including appraisal content and identity, candidate, authorized scope and
runtime, recipes, relevant Persona definitions and selected history content.
List ordering is declared and stable; non-finite numbers are rejected. Current
state versions enter the key only for an explicitly state-dependent recipe;
V1 compatibility recipes do not depend on mutable fast-state output. Unrelated
state changes and a later turn number are not invalidators. Dynamics recovery
uses the existing injected time separately, never changes the projection key.

Persist the accepted appraisal and materialized result through a runtime-owned
derived journal alongside existing backend facilities, with an immutable unique
key. This is not Canonical Memory/FACT admission. Reuse an existing result for
the same key, including after restart; conflicting payload for a key fails closed.
Persist source lineage sufficiently to resolve the appraisal without telemetry.
Supersession or version/dependency changes produce a new linked record; never
overwrite old records. Reprojection is explicit caller-authorized work, never an
automatic future-turn LLM call. A reused result does not reapply an old effect;
the existing admission/idempotency boundary owns exactly-once application.
Journal entries carry evaluation outcome separately from application outcome
(pending/committed/aborted) and commit/transition references. Persist evaluation
before application; a journal failure prevents application. Link the committed
application receipt inside the same state transaction. Recovery never reapplies
a committed receipt; an evaluated-but-unapplied entry can be reused by the same
authorized admission. An aborted turn retains its derived semantic audit record
but does not make it eligible for an unrelated future cognition turn.
Bind each source event/appraisal to its original interaction and create a unique
application identity from runtime namespace, source appraisal (or legacy event),
and authorized effect group. Enforce uniqueness in the durable application
receipt, not only the existing interaction marker. A different interaction may
inspect a result only through an authorized read surface and cannot apply it.
Reprojection is evaluation-only by default, including version changes: it never
replays the original effect. A corrective application requires separate explicit
transition authority outside V1. Test crashes before/after journal and state
commit, same-interaction retries, and cross-interaction replay rejection.

## Status semantics

- MAPPED: valid input, matching recipe and 1..N proposed effects. Commit outcome
  is separately reported; MAPPED never means a canonical write succeeded.
- UNMAPPED: accepted appraisal, valid input, no applicable runtime recipe;
  effects empty, reason no_runtime_projection_rule, meaning preserved.
- ABSTAINED: valid evaluation explicitly withholds projection for a documented
  uncertainty/applicability reason; effects empty. Not lack of recipe coverage.
- REJECTED: malformed/unauthorized binding or input; effects empty, reason given.

Appraisal acceptance is a separate status. Provider failures are APPRAISAL_ERROR,
not UNMAPPED. Projection rejection does not erase a separately valid accepted
appraisal; consumer authority validates it independently. Invalid appraisal
payloads cannot enter cognition through this rule.

## Minimal additive cognition contract

Carry accepted appraisals and projection references on EmotionalTransitionResult
independently of impulses and existing accepted_events. Keep legacy Intent
selection behavior for compatibility; do not broaden ActionPolicy permissions.
Add compiler input accepted_appraisals plus an explicit configured admission
policy, and ExpressionContextKind.COGNITIVE_MEANING. This is a scoped read view of
this turn's accepted understanding, not a fact, persistent belief or instruction.

Compiler verifies runtime, Persona/user scope association, situation/interaction
lineage and current acceptance. It emits bounded meaning items with appraisal,
candidate and evidence source refs regardless of projection coverage. Policy
controls eligibility and item/character budgets, not a fixed meaning vocabulary.
Omissions report policy_denied/budget_exhausted; they do not delete the source.
Action and policy constraints retain essential priority; meaning inclusion does
not grant action permission. Renderer labels this as appraisal, quotes semantic
content as data, and never renders it as FACT. Retry reuses these same items.
No retrieval of old appraisals or canonical Memory write is authorized here.

## Multiple targets and atomicity

One appraisal may yield zero or many effects. All effects in one authorized
transition must be validated/staged before any canonical member is written.
ADR-0005 already protects an affect vector, not arbitrary fast/slow transactions.
Extend staging through the existing canonical commit/backend boundary for mixed
targets; do not use a second writer or interpret process serialization as a DB
transaction. Retain HomeostasisGate and Slow admission authority. If any required
target is stale, invalid or cannot participate in the same transaction, the whole
authorized effect group is unapplied with a trace reason. No partial fast write.
To preserve existing production behavior, legacy longitudinal proposals pass the
existing gate BEFORE forming the authorized group: a denied slow proposal is
traced as denied, never represented as an authorized effect. Fast-only admission
in that case remains compatible. Once a mixed group is authorized, failure of
either member aborts both. New recipes may explicitly require joint admission;
for those, denial of any required target prevents authorization of the group.
Recipe metadata distinguishes legacy-independent admission from required-joint
admission; tests must cover both, without weakening transaction atomicity.
Independent elapsed-time recovery is separately attributed and remains legal.
UNMAPPED means zero appraisal-caused mutation; fixed-clock tests additionally
verify zero total mutation. It does not disable ordinary recovery on later ticks.

## OW and coverage

Extend existing causal view to show appraisal acceptance/meanings/lineage and
projection status/version/targets/reasons, meaning preservation and cognition
included/omitted reason. Missing data is UNKNOWN, not no change or UNMAPPED.
Read from materialized records; transient telemetry is an additional view.

Aggregate accepted appraisal_count by distinct appraisal identity and mapped,
unmapped, abstained, rejected counts by distinct projection identity. Report the
window, projector version and denominators. Provider errors have a separate
count; legacy no-appraisal projections are separately bucketed. Replays do not
inflate counts; deliberate reproject versions are separately filterable. Group
unmapped event kinds and exact meanings in bounded pages, never truncate source
records or infer new ontology from display labels.

## Alternatives

1. Recommended: one projector at the existing mapper boundary plus the minimal
   cognition view. Closes meaning loss with one mapping authority.
2. Trace-only UNMAPPED patch: smaller, but fails cognition consumption and PASS.
3. Generic new semantic bus/full Dynamics rewrite: unnecessary scope and more
   authority surfaces. Rejected for this assignment.

## Delivery and tests after acceptance

W1: contracts, source journal, one deterministic projector and legacy recipes.
W2: transition/compiler consumption, staged multi-target commit, replay/restart.
W3: OW coverage, end-to-end trace and independent integration review.
These are sequential parts of this assignment; no release gate advance implied.
Each W requires RED before production changes, targeted and complete existing
suite verification, and independent review. No merge/push/deploy is implied.

Required executable RED cases:
1. Capture all four production recipes and compare exact old/new outputs,
   including bounded history, longitudinal proposal and post-Dynamics vector.
   Include gate denials for low/missing salience and low confidence, proving
   unchanged legacy fast-only behavior and all-or-nothing authorized mixed writes.
2. Novel event with recognition/relief/increased_confidence_in_user is accepted,
   remains resolvable and yields UNMAPPED, including restart.
3. UNMAPPED generates zero impulses and no attributable fast/slow mutation.
4. Allowed cognition consumes preserved meanings with lineage; denied/budgeted
   cases have explicit omission, no FACT item and no fresh semantic inference.
5. Multiple targets succeed together; inject failure/staleness at every write
   boundary and prove no partial persistence or in-memory publication.
6. Identical input/version gives identical canonical result across processes and
   restart; relevant dependency changes invalidate, unrelated state does not.
7. Trap model/provider calls while projecting/replaying; call count stays zero.
8. Appraisal/evidence/version lineage survives round-trip; forged scope rejected.
9. OW and aggregation distinguish all four statuses, provider failure, replay,
   semantic preservation and cognition inclusion; no missing-data substitution.

Final live proof must start with novel natural language via the real configured
semantic provider in an isolated LAB binding and capture accepted appraisal,
materialized projection, bounded cognition and OW. A scripted appraisal fixture
is deterministic integration evidence, never a live semantic trace.

## Explicit exclusions

No new affect axes, closed provider event enum, nearest-emotion mapping, repeated
model projection, FACT masquerade, UI ontology, LCE change, Memory redesign,
production DB mutation, or unrelated dirty-file import.
