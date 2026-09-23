# MR-W3-SURFACE-ARCHITECTURE-01

Date: 2026-09-23. Status: architecture frozen under accepted ADR-0028; no production implementation. Verdict: **ARCHITECTURE_READY_FOR_W3_IMPLEMENTATION**. The next gate freezes a Candidate recipe and revises RED contracts before W3-B implementation; production activation is later.

Repository: C:/projects/mind-runtime-main-merge. Architecture worktree: .worktrees/mr-w3-surface-architecture-01, branch w/mr-w3-surface-architecture-01. Exact implementation base: ee6b25d535ffc3e3b1e0f37c567ab5572049b0ea; tree: 113956e8cd17e1e1a927a2201fd4ac5d14391e55. Main HEAD observed at start: 17772842aaffd44c4ff1a643e9fa4621fa9e6652. No legacy repository supplies authority.

## 1. Authority recovery

| Class | Recovered source and treatment |
|---|---|
| AUTHORITATIVE | The exact W2 commit/tree above; AGENTS.md; accepted ADR-0004, ADR-0006, ADR-0007, ADR-0027; their implemented contracts and current production path. W2 owns immutable AcceptedAppraisal, one AppraisalProjector, UNMAPPED, gain-once, transactional application receipt, and bounded COGNITIVE_MEANING. |
| PROVISIONAL | Untracked docs/architecture/MR_AFFECT_RUNTIME_CONTRACT_01.md v1.1.0 in main and its tracked evidence snapshot at docs/audits/evidence/mr-late-projection-mainline-reconcile-01/affect-v1.1.0-snapshot.md. The original and snapshot have identical normalized text but different on-disk line endings. Its explicit disposition/dependency/overlap proposals are design input, not a committed production contract. Production coefficients, tone bands, and per-agent calibration remain provisional. |
| TEST_ONLY | Untracked docs/contracts/MR_SURFACE_AFFECT_GOLDENS_01.md and tests/surface/ in C:/projects/w/mr-surface-affect-goldens-01. The report records 98 intentional behavioral RED and 3 fixture-integrity passes; these results are historical, not rerun here. surface-reference-v1 arithmetic and binary64 digests are fixture oracles only. |
| SUPERSEDED | The pre-acceptance ADR-0027 status and pre-final W2 review verdicts. They do not supersede the supplied W2 final commit. The historical V0.1.4 combined behavior diagram yields to accepted ADR-0004/0006/0007. |
| CONFLICTING | ADR-0007 and current code permit qualitative bands directly from raw affect; current compiler also admits static persona style, and Host builds a numeric Slow summary. These are valid legacy paths but conflict with a single Surface behavior interpretation in SURFACE_V1. Accepted ADR-0028 narrows their use in that mode; no W2 invariant changes. |
| MISSING | Production behavioral disposition/schema revision, Surface recipe/admission, Surface projector/result, score overlap validator, bound Intent input, durable consumer-use linkage, expression control admission, and actual Host/provider Surface exposure. W2 source review explicitly says Surface was not added. |

The main untracked Affect document has SHA-256 2e8c53f74be19297cbb2e6a91fe8a512f973a41da2327602c8514c82e88763dd. The separate Golden worktree is uncommitted at 1777284. Neither receives authority merely from its title or historical verdict.

## 2. Existing-contract conflicts and disposition

ADR-0006 gives IntentEngine direct projected-vector access. W3 adds a typed Surface input and validates each rule's root ownership; it does not remove the existing legitimate nonoverlapping raw-dimension path. ADR-0007 allows configured affect bands, while W3 SURFACE_V1 must disable those bands and duplicate behavioral persona-style constraints. That is a scoped ADR amendment, not a contradiction with W2 application or cognition. The current Host adapter's Slow numeric summary is separately prohibited in SURFACE_V1 exposure. Legacy mode can retain it pending separate Slow-exposure review.

The provisional v1.1.0 contract describes the same five controls and dependency sets as this decision. This document accepts those roots and the no-fallback principle, but does not promote its sample formulas, its exact proposed class names, or the RED fixture serialization to production authority. No accepted repository contract requires Surface to be a second affect ontology, FACT, permission, or persistence authority. No irreconcilable authoritative conflict was found.

## 3. Problem statement and non-goals

W2 ends with accepted internal meaning and a Dynamics snapshot. W3 answers how that snapshot and this Agent's stable behavioral disposition produce observable **tendencies**. Required counterfactuals are (a) identical Dynamics and different authorized Persona revisions produce different applicable Surface values; (b) identical Persona revision and different Dynamics produce different applicable Surface values. Initiative has no direct Persona root in V1, so (a) is required for the Surface vector, not every control.

W3 excludes event extraction, Reality/StateBar, semantic acceptance, AppraisalProjector, W2 transactions, Memory, LCE, OW, personality learning, and character-card comparison experiments. Character material may bootstrap an explicitly reviewed Persona revision. A full role card is never the recurring runtime personality authority or automatically injected every turn.

## 4. Final production topology

| Arrow | Sole authority and typed handoff | Failure and lineage |
|---|---|---|
| Accepted internal state → Dynamics snapshot | Existing DynamicsEngine plus orchestrator/state owner; ProjectedMindState or committed RuntimeState vector | Preserve projected/committed phase, affect scope, per-state ID/version. No extra Dynamics step. W2 application/commit remains untouched. |
| Persona source → stable disposition | Validated PersonaProfile loader/config owner; immutable four-field block bound to persona ID, profile revision, content digest | Incomplete or mismatched block is ineligible for SURFACE_V1. No default numbers or model-generated runtime override. |
| Dynamics + disposition → Surface | **One** deterministic SurfaceProjectionPort, composed once for both turn and tick, with pinned recipe and dependency manifest | Whole result AVAILABLE or UNAVAILABLE; same admitted inputs and recipe yield same values/identity. No LLM, clock read, I/O, state write, or second interpretation by consumers. |
| Surface → Intent influence | DeterministicIntentEngine consumes typed controls and a validated rule/recipe binding; only contact_seeking, initiative, confrontation may contribute | Surface-dependent rule produces no candidate if controls are unavailable/stale. Typed score trace names control, source and overlap validation. No action request or permission. |
| Intent → ActionPolicy | Existing candidate/lifecycle and ActionPolicy | Policy alone ALLOW/DEFER/DENY under current factual/resource/schedule constraints. A high control cannot bypass it. |
| Surface → Expression | Existing DecisionContextCompiler consumes the same Surface result after ALLOW; only confrontation, expressive_warmth, expressive_restraint enter bounded expression guidance | Missing or stale Surface blocks SURFACE_V1 provider dispatch; never falls back to raw affect bands, Slow numbers, or role card. |
| DecisionContext → renderer → Host → Provider | Compiler owns admission; deterministic renderer owns one budgeted provider envelope; Host forwards its admitted expression segment as opaque text; provider realizes prose only | Action/Policy and Surface expression constraints are indivisible essential items. Overflow fails expression before provider call; optional meaning/history omissions are traced. Host does not reinterpret controls. |

The recommended code placement is a small src/mind_runtime/surface/ pure component with a contract in contracts/surface.py and configuration admission in the existing composition/validation layer. This placement is a slice target, not an authorization to add a second projector at the appraisal boundary. One Surface evaluation follows each authorized Dynamics snapshot; the exact result object is shared with Intent and Expression. The user-turn orchestrator and CognitiveTicker use the same port and rule validation.

## 5. Surface semantic definition and V1 vocabulary

Surface is a derived behavioral/expression control vector: f(current Dynamics, stable agent-specific disposition, pinned deterministic recipe). It is neither a new emotion ontology nor a canonical state. Values are finite [0,1] internal strengths, not direct instructions. Exactly five keys exist: contact_seeking, initiative, confrontation, expressive_warmth, expressive_restraint. withdrawal and reassurance_seeking are **absent from V1 schema**, never zero or null.

The first three are eligible to bias Intent. Expressive warmth and restraint are expression-only. Confrontation may also shape manner of an already permitted expression; that does not create an action. Consumer behavior uses typed control IDs and versioned rendering rules, never a condition such as “warmth > .8 means say a fixed phrase.” A model may realize wording within the admitted constraints, while deterministic Policy and Guard retain their authorities.

The recipe must be finite, deterministic, versioned, range-checked, inspectable, and bound at composition. V1 uses a restricted declarative expression graph with statically enumerable lookup roots; arbitrary callbacks, provider calls, hidden reads, control-to-control edges, and implicit roots are not allowed. Each rule declares exactly the roots it actually reads; validation compares the graph's lookup set to the manifest. Each declared root must also be observably effective in at least one non-saturated admissible fixture, so a zero coefficient cannot satisfy the contract by syntactic mention alone. Same inputs mean same numeric output within a pinned arithmetic/serialization implementation profile. Exact coefficients and band cutoffs are **not frozen here**: the existing reference arithmetic has no production calibration evidence.

Before W3-B implementation, W3-B0 must admit SURFACE_V1_CANDIDATE: an implementation-authorized, deterministic, immutable recipe revision and matching expression map. CANDIDATE_RECIPE_V1 names its first admitted revision, distinct from the historical surface-reference-v1 fixture. Admission freezes recipe_id, revision, content_digest, numerical profile, exact root manifest, range semantics, deterministic evaluation rules, directional invariants and version-bound acceptance vectors. This gives W3-B/C/D a fixed implementation target; it does **not** claim validated psychology, final Persona calibration or production deployment permission. After admission, any behavioral change creates a new revision/digest and new acceptance vectors; no in-place edit of candidate-v1 is permitted. PRODUCTION_ACTIVATED is a later explicit gate after W3 certification, counterfactual validation, post-W3 experiment evidence and calibration review. A certified candidate may be activated unchanged, or evidence may require candidate-v2 and fresh certification. The old surface-reference-v1 arithmetic remains TEST_ONLY / REFERENCE_FIXTURE.

Justified directional expectations for the admitted recipe: increasing attachment_approach must not lower contact_seeking; increasing confrontation_readiness must not lower confrontation; increasing expressive_warmth_bias must not lower expressive_warmth; increasing trait expressive_restraint must not raise contact_seeking or confrontation and must not lower control expressive_restraint. Saturation may make a response equal. Other directions, including anger's interaction with warmth/contact and sadness with initiative, require explicit recipe tests rather than an unproved psychological rule.

## 6. Stable disposition authority

PersonaProfile is the sole owner. Its complete immutable behavioral_disposition has precisely four finite, non-bool [0,1] traits: attachment_approach, confrontation_readiness, expressive_restraint, expressive_warmth_bias. These are stable traits, distinct from Dynamic current values and distinct from same-named Surface controls through typed namespaces. A read-only view may copy values and identity for Surface, but cannot own defaults, persistence, mutation, or an overlay.

The current loader accepts only profile_version=1 and maps it directly to PersonaProfile.version; Kayla config has no behavioral block. W3 must separate serialization schema_version from positive profile content revision. Legacy files with absent schema_version decode as schema 1 and whole behavioral block absent. Explicit schema 2 has a complete four-field block; unknown fields, partial/null/invalid values reject. Same persona ID and revision with different effective content digest is a conflict. The config author/review process alone may publish a new immutable profile revision; runtime composes one snapshot and atomically switches all bound Surface/Intent/expression configuration between evaluations. No mid-turn reload and no learned mutation in W3.

The W2 appraisal/Dynamics path may continue using legacy profiles. SURFACE_V1 cannot start on one. The same profile snapshot used for Dynamics is bound into Surface through an explicit runtime-owned provenance envelope, not inferred from scope or a later mutable config read. W3 may implement schema 2 and validate fixture/candidate Personas, but must not invent four trait values or automatically migrate Kayla, Xiyue or another real Agent. Real-agent SURFACE_V1 binding requires a separately authored and reviewed Persona revision plus the later recipe/map production activation decision. Future longitudinal personality evolution can publish a new profile revision through a separate authority and migration; W3 defines only this consumption seam.

## 7. Input/output and dependency contracts

SurfaceProjectionInput contains runtime_id; agent affect scope and owner; interaction/tick reference; admitted projection ID and phase PROJECTED or COMMITTED; a complete authorized Dynamics snapshot with per-root state ID/version/value and StateDefinition bounds/owner; Persona ID/revision/effective-content digest and four traits; pinned Surface recipe ID/revision/digest; and an expected snapshot binding supplied by orchestration. The outer user interaction scope is distinct from agent affect scope (ADR-0002). No provider, clock, DB, random, or file handle belongs in this input.

Successful SurfaceProjectionResult contains controls_id; status AVAILABLE; exactly five typed finite values; runtime/affect scope/owner; source phase and projection ID; interaction/tick ref; Persona ID/revision/content digest; consumed per-root state IDs/versions/value digests; projector implementation version; recipe ID/revision/digest; dependencies by control; and a full dependency digest. It is explicitly derived_only. The result has no permission, action type, FACT kind, or state-write API. Failure contains status UNAVAILABLE and stable reason code with no partial vector. Output IDs use canonical, domain-separated serialization of every authority-relevant consumed input, excluding only nonsemantic evaluation-attempt metadata.

| Control | Dynamics roots | Disposition roots |
|---|---|---|
| contact_seeking | longing, closeness_craving, anger | attachment_approach, expressive_restraint |
| initiative | sharing_urge, curiosity, sadness | none |
| confrontation | anger | confrontation_readiness, expressive_restraint |
| expressive_warmth | closeness_craving, anger, sadness | expressive_warmth_bias |
| expressive_restraint | diligence_pressure | expressive_restraint |

Every Dynamics name above is the fully qualified agent.affect dimension, validated against registered StateDefinition/ownership rather than trusted by prefix. Slow/longitudinal state is not a V1 input. Each recipe's actual read set must equal this manifest at admission; no undeclared source, harmless-looking alias, or callback may bypass it. An unrelated valid Dynamics dimension does not change values or consumed-dependency digest. The full source projection identity still distinguishes separate authorized evaluations.

## 8. Root ownership and Intent boundary

For each scored IntentRule, configuration admission expands each selected control's **transitive** typed roots from the pinned Surface recipe. Let R be nonzero direct Dynamics weights. Let U_i be all Dynamics **and disposition** roots of each nonzero selected Surface control. Reject the ruleset if R intersects any U_i, or if any two U_i intersect. Negative weights count as use; zero-weight entries are schema-validated but cannot hide a contributing path. In V1, a Surface-aware rule must have event_bonus=0 because the accepted event may be an ancestor of the same Dynamics change. Event matching may still determine due_at; it cannot add a second affect reward. There is no allow_overlap switch. Validation is per Intent score, not across independent candidate kinds.

The composition owner validates and binds one immutable tuple of Persona digest, Surface recipe digest/manifest, Intent ruleset digest, and expression exposure mode. Rule construction rejects duplicate kind, unknown/deferred control, duplicate control/root alias, nonfinite weight, missing manifest, overlapping roots, and mismatched recipe. At evaluation, IntentEngine verifies the Surface result's runtime, affect scope, Persona/revision/content digest, source projection/phase, consumed state IDs/versions, recipe and manifest digest against the same admitted snapshot. It rejects stale or substituted results **before scoring**. Atomic config replacement reruns the validator. This makes the R ∩ U check unavoidable in the production composition and runtime path, including tick; a caller cannot pass a bare float map.

The existing additive score form may remain: base + permitted nonoverlapping direct terms + bounded typed Surface modifiers, followed by existing clamp, threshold, ordering and lifecycle. A modifier is configuration-owned and finite; it cannot encode an action request or permission. The trace records each control ID, amount, controls_id, recipe/ruleset references and overlap-validation reference. The current engine silently treats missing/nonfinite raw dimensions as zero; SURFACE_V1 rules must instead withhold their candidate on missing required roots or invalid Surface. Raw-only legacy rules remain in explicit LEGACY mode, and nonoverlapping direct dimensions may remain in SURFACE_V1 where their candidate semantics do not duplicate a migrated control. A single kind has one rule, so a legacy and Surface rule cannot score the same kind in parallel.

## 9. Expression, renderer, Host and provider boundary

SURFACE_V1 is an explicit composition mode. It disables current AffectExpressionRule output, emotion-behavior persona_style_constraints, and Host Slow numeric summary for that mode. Nonbehavioral format/language constraints may remain. The compiler receives SurfaceProjectionResult only after Policy ALLOW; it verifies the same runtime, Persona, interaction/tick and projection binding, and admits typed SURFACE_CONTROL expression items for confrontation, expressive_warmth and expressive_restraint. It does not calculate from raw Dynamics or Persona. Contact seeking and initiative reach Body only through selected Intent/action, avoiding a second “be proactive” instruction.

A versioned SurfaceExpressionRule maps admitted numeric controls into bounded qualitative guidance such as warmth, restraint and directness. The mapping is deterministic, independently versioned and approved with the recipe; it contains no fact claim or fixed phrase. Compiler priority/admission treats the complete expression-control bundle, selected action and Policy constraints as essential and indivisible. Renderer applies the same admission outcome to its provider envelope and Host-facing Surface segment, with item/character budgets and explicit omitted reasons. It never prints numeric Surface values, raw Persona/Dynamics, source digests or diagnostic refs in provider text. Meaning remains quoted APPRAISAL_DATA, never FACT or instruction. Retry reuses the same compiled controls and meaning.

HostDecisionContext remains a human-readable public summary, but its emotional/behavioral segment in SURFACE_V1 must be produced solely from the renderer's already admitted Surface segment. The Host does not inspect raw state, add Slow numbers, reinterpret controls, or append a role card. The current Xiyue render_bounded_context path must demonstrably forward that segment to provider bytes; MR's internal expression provider must receive the same admitted semantics. Changing only the compiler is incomplete. The provider chooses prose, while ActionPolicy and ExpressionGuard still decide permission and guarded output respectively. A calculated Surface invisible to the actual provider is **not W3 complete**.

## 10. Persistence, replay, lineage and failure

Surface is a deterministic derived view, not a canonical table. Current committed RuntimeState rows are durable and versioned; Persona revisions, Surface recipes, renderer mappings and bound rulesets must remain immutable/retrievable for replay. On restart, reload the existing state owner and matching versioned configuration, then recompute Surface; do not persist an independently writable Surface value. A cache, if added, is process-local and keyed by the complete validated result identity. Same admitted inputs produce the same values and semantic ID under the pinned numerical profile. A changed Persona/recipe/state version or source phase yields a distinct ID even if the numbers coincide.

Projected current-turn Surface may influence Intent and permitted expression before commit, but remains tagged PROJECTED. Abort cannot publish it as canonical or make it eligible for another turn. Tick uses the same post-Dynamics snapshot; it cannot secretly re-step Dynamics. Current IntentScoreTrace is generated but not durably consumed by the orchestrator; W3-C must close that audit gap. An admitted Surface-influenced Intent retains an immutable, bounded score-use record linked to its existing durable lifecycle, including controls_id, source IDs, version/digests, rule validation ref and actual scored control contributions. An actual provider attempt retains a linked render/admission trace of the qualitative guidance. These are consumer-use evidence, not an independently writable Surface value or a new state authority. Historical exact replay requires the referenced state versions and immutable configuration artifacts. If one is unavailable, report REPLAY_UNAVAILABLE rather than reconstruct from today's Persona or current state. This is separate from W2 application replay; recomputation never reapplies an appraisal effect or dispatches an action.

Invalid config (schema, dependency/AST mismatch, recipe identity conflict, overlap, exposure combination) rejects SURFACE_V1 composition. At runtime, missing state/trait, wrong scope/runtime/owner/Persona, stale projection, incompatible bounds, nonfinite values, digest mismatch or unavailable recipe yield whole-result UNAVAILABLE with a stable reason. No missing=0, neutral trait, last-good Surface, raw affect fallback, partial vector, or provider guess. Surface-dependent Intent candidates are withheld; unaffected internal transition/commit follows existing W2 rules. If an otherwise permitted expression requires unavailable Surface or cannot fit the essential bundle, provider dispatch is withheld and diagnosed. Policy denial/defer never calls the expression provider. None of these failures changes AcceptedAppraisal, projection journal, gain application, or W2 receipt semantics.

## 11. Compatibility

LEGACY and SURFACE_V1 are mutually exclusive behavior-exposure configurations. Existing profile schema 1, raw Intent rules and ADR-0007 affect bands remain legal in LEGACY. SURFACE_V1 requires complete schema-2 disposition, pinned recipe/mapping/ruleset, no overlapping scores, and no raw affect or Slow numeric provider exposure. SURFACE_V1_CANDIDATE is the lifecycle status of a recipe used in isolated W3 implementation/certification, not permission to bind SURFACE_V1 to a real Agent. Such a binding needs both PRODUCTION_ACTIVATED recipe/map status and an explicitly reviewed real-Agent Persona revision. There is no runtime fallback between modes. Migration switches a complete composition at a boundary; an in-flight turn keeps its captured version tuple. No Kayla trait numbers or production Surface formula are inferred from current calibration_status=PROVISIONAL.

## 12. Ownership matrix

| Concern | Sole authority |
|---|---|
| Semantic appraisal acceptance | SemanticAppraisalProducer/admission (ADR-0027); AcceptedAppraisal is its immutable result |
| Affect effect projection | One AppraisalProjector (ADR-0027); no Surface role |
| Affect dynamics transition | DynamicsEngine |
| Canonical affect publication | Existing orchestrator commit/backend boundary |
| Stable personality disposition | Versioned PersonaProfile; config loader validates and constructs it |
| Surface projection | One composed deterministic SurfaceProjectionPort and pinned recipe |
| Intent influence/scoring | DeterministicIntentEngine with composition-validated rules |
| Action permission | ActionPolicy only |
| Expression context admission | DecisionContextCompiler |
| Provider context exposure/serialization | DeterministicContextRenderer, using only compiler-admitted items |
| Host transport | Host adapter, forwarding the admitted segment without interpretation |
| Expression realization | Expression provider, prose only |
| Expression acceptance | ExpressionGuard, after generation and separate from ActionPolicy |

## 13. Data exposure matrix

“DC” means the emitted DecisionContext, not the compiler's internal typed input. “Persist” names existing authoritative storage or explicit audit refs, not permission to create a Surface table.

| Data | Intent | DC | Renderer | Host | Provider | Persist |
|---|---|---|---|---|---|---|
| Raw Persona fields | No; only Surface-derived controls | Identity ref only | No | No | No | Yes, immutable versioned config |
| Raw Dynamics fields | Only validated nonoverlapping direct rule inputs | State/projection refs only | No | No | No | Yes, canonical state through existing backend |
| Surface controls | Three eligible numeric controls with lineage | Typed expression subset, qualitative output | Bounded guidance only | Same admitted guidance text | Same guidance text, never floats | No independent store; refs/contributions in trace |
| Appraisal meaning | No direct score input | Bounded COGNITIVE_MEANING | Quoted data | Bounded quoted data | Bounded quoted data, not FACT | W2 accepted journal |
| Reality facts | Via factual Situation | Allowlisted FACT | Bounded data | Bounded summary | Bounded data | Existing factual owner |
| Intent | Scored candidates | Selected kind/ref after Policy | Selected action context | Selected kind/action summary | Permitted goal/action context | Existing Intent lifecycle |
| ActionPolicy | No, applied after score | ALLOW permission/constraints only | Essential constraints | Same constraints | Same constraints | Existing decision/receipt trace |

Diagnostic/OW authorization is separate from ordinary Host/provider exposure. Neither a reference nor a debug API authorizes Host to resolve and inject raw internal values. Slow state remains an existing canonical class; SURFACE_V1 specifically omits its current raw numeric Host summary.

## 14. Existing RED Golden disposition

Golden authority has three distinct layers:

| Layer | Frozen meaning |
|---|---|
| Normative architecture invariants | Five controls and exact root manifests; single authority; no I/O/model/state mutation; determinism; lineage; missing-data fail closed; Persona/Dynamics counterfactual structure; root-overlap rejection; provider information isolation. These hold independently of calibration. |
| CANDIDATE_RECIPE_V1 conformance vectors | W3-B0 freezes candidate recipe/map identity, digest, numerical profile and expected vectors before W3-B. RED then proves that implementation matches this candidate revision, not that the recipe is psychologically correct. Behavioral changes require a new revision and new vectors. |
| Historical reference fixture | surface-reference-v1 arithmetic stays TEST_ONLY / REFERENCE_FIXTURE. It may check a fixture evaluator, but cannot silently become the W3 candidate or a production recipe. |

| Decision | Existing material | Required change before promotion |
|---|---|---|
| KEEP | Five-key vocabulary, complete direct root manifests, no deferred placeholders, counterfactual structure, missing-data rejection, determinism/no-I/O/no-mutation, projected-vs-committed and abort/restart obligations | Retain as normative architecture assertions after rebase to W2 SHA and accepted ADR. |
| ADAPT | The structural, lineage and failure assertions in G1–G14, G16–G17 and G20, plus their test-only adapter | Bind to actual Persona/snapshot/result types and the single production port; test versioned config admission, full typed roots including Persona-root overlap, turn **and tick**, Intent score and provider-visible expression. Do not let a test adapter compute outputs or fabricate restart evidence. Any exact sample number inside these cases remains TEST_ONLY. |
| REPLACE | G15/G18/G19 exact numeric values, recipe AST/binary64 digests, sample clamp trace and exact sample tone bands as W3 conformance criteria | Preserve them only in the historical reference-fixture suite. New candidate-bound RED vectors must use the frozen CANDIDATE_RECIPE_V1 and expression-map revision, with independent expected oracles. The 98 RED count is not a target metric or production-calibration evidence. |
| DELETE | Any assertion that treats reference arithmetic as universal production psychology, assumes schema-2 loader already exists, or accepts a fake provider/Host pass from a pure Surface calculation | Remove only those invalid claims when the revised RED suite is reviewed; do not silently delete useful RED coverage. |

The Golden contract is currently untracked on a different base and has no W2 Intent/Host end-to-end coverage. Existing fixture-integrity GREEN does not certify Surface behavior. W3-B0 must first freeze the candidate recipe and map, then revise RED around those exact versions; implementation cannot choose coefficients opportunistically after seeing tests or experiments.

## 15. Minimal implementation slices and gates

| Slice | Narrow authority changed | Independent acceptance |
|---|---|---|
| W3-A Persona/config authority | PersonaProfile and loader; schema/content revision split; immutable four-trait block | Same ID/revision content conflict, legacy separation, missing/invalid block failure; fixture/candidate Personas only, no real-Agent activation or W2 source change. |
| W3-B0 Candidate recipe and RED admission | Non-production versioned recipe/map specification and revised Golden contract | Freeze CANDIDATE_RECIPE_V1 identity, digest, numerical profile, exact roots, range/evaluation rules, directional invariants and acceptance vectors **before** W3-B code; retain old arithmetic as reference fixture. |
| W3-B pure Surface | New single Surface contract/port and composition; declared roots and deterministic candidate recipe evaluation | Counterfactuals, complete five-key vector, candidate-bound vectors, isolation, lineage, restart reconstruction, abort, no I/O/model/clock or Dynamics mutation. |
| W3-C Intent | Intent rule/input/trace and composition overlap validator; orchestrator and tick pass same result | R ∩ U and pairwise root rejection including disposition roots; event bonus exclusion; stale snapshot refusal; durable linkage of score-use evidence for admitted candidates; Policy denial despite high controls. |
| W3-D expression/Host | Compiler, renderer, Host exposure and proactive expression integration | Raw affect/style/Slow absence in SURFACE_V1, essential bundle/budget failure, actual provider bytes and linked render/admission evidence across retries, ActionPolicy/Guard unchanged. |
| W3-E certification | Tests and independent review only | W2 invariant regression, complete current suite, production-shaped turn and tick, restart/abort, real provider-visible Surface and candidate-revision conformance; exact HEAD/tree and environment evidence. No role-card benchmark or calibration claim. |
| POST-W3 EXP | Separate role-card versus quantified-personality experiment | May inform calibration/version selection; cannot redefine architecture or mutate the certified candidate revision. |
| POST-W3 CAL | Separate candidate calibration and activation review | Activate a certified revision unchanged or create candidate-v2 with new RED/certification; separately approve each real-Agent Persona binding before production use. |

Each implementation slice starts with an accepted ADR/contract and a reviewed RED proof for its own authority change under AGENTS.md. W3 may be technically complete and certified while SURFACE_V1 production activation remains NOT YET. Certification proves the runtime mechanism conforms to the frozen candidate, not that Persona values or recipe coefficients meet production-quality calibration. No slice silently alters W2 AcceptedAppraisal, AppraisalProjector, Dynamics sensitivity, receipt, or FACT boundary. Mainline integration, merge and push are outside this architecture task.

## 16. Deferred questions and risks

FUTURE EXTENSION: additional personality dimensions, longitudinal disposition mutation, withdrawal/reassurance controls, Slow-to-Surface dependencies, calibrated cross-language expression maps, and a causally typed event bonus exception. None enters V1 or receives default values.

W3-B0 still must author and freeze concrete Candidate recipe/map revisions; this document intentionally does not declare the historical test coefficients as calibrated. Post-W3 experiments may inform coefficients, mapping calibration or revision selection, but cannot change root ownership, the five-key vocabulary, single Surface boundary, Policy/exposure authority, lineage or fail-closed semantics. Ontology extensions need another ADR. Production activation requires later validation/calibration and real-Agent Persona authoring review; do not auto-migrate Kayla or Xiyue. Existing Host Slow exposure is a concrete migration risk. Historical exact replay depends on retained old state/config versions; if retention is insufficient, only current-state restart recomputation can be certified. Provider wording remains variable, so W3 tests must assert bounded input, policy/guard behavior and causal influence rather than identical prose.

Stop with ARCHITECTURE_CONFLICT if implementation proves any W2 final invariant must change, accepted contracts cannot be reconciled by a scoped ADR, Surface must grant action permission, raw Persona/Dynamics must be exposed to provider, a second Surface owner is required, or root overlap cannot be enforced on both production turn and tick. Do not workaround these conditions.

## 17. Final verdict

**ARCHITECTURE_READY_FOR_W3_IMPLEMENTATION.** The production topology, ownership, typed roots, fail-closed scoring and exposure seams are specified without changing W2, and ADR-0028 is accepted. The next gate is frozen Candidate recipe/map admission followed by candidate-bound RED contract revision. W3 implementation and certification can close while production activation remains NOT YET. Experiment and calibration follow W3-E; they may choose or revise a recipe version, never rewrite the architecture or the meaning of a frozen revision. This verdict is not evidence that Surface exists, that a real Agent is activated, or permission to merge/push.
