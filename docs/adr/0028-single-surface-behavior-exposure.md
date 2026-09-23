# ADR-0028: One Surface authority for agent-specific behavior and expression

- Date: 2026-09-23
- Status: **PROPOSED / architecture draft**
- Base implementation authority: ee6b25d535ffc3e3b1e0f37c567ab5572049b0ea
- Companion decision record: docs/architecture/MR_W3_SURFACE_ARCHITECTURE_01.md
- Scope: W3 Surface behavior boundary only; no production implementation in this draft

## Problem

W2 has an auditable appraisal-to-internal-state chain. Current Intent scoring can still read raw projected Dynamics, and current expression can independently band raw affect, add static Persona style, and expose a Host Slow numeric summary. There is no single place where current state and this Agent's stable behavioral disposition become behavior/expression tendencies. Merely adding a Surface formula would leave duplicate behavioral interpretations and permit double weighting of a Dynamics root in one Intent score.

## Decision proposed for acceptance

1. Stable behavioral disposition is a complete, immutable four-trait part of versioned PersonaProfile: attachment_approach, confrontation_readiness, expressive_restraint, expressive_warmth_bias. The loader separates schema version from content revision. Character material may be compiled into an explicitly reviewed profile revision; neither character text nor the provider owns runtime Persona.
2. A single pure Surface projection consumes one admitted Dynamics snapshot, its bound Persona revision, and a pinned deterministic recipe. It emits exactly five derived [0,1] controls: contact_seeking, initiative, confrontation, expressive_warmth, expressive_restraint. withdrawal and reassurance_seeking are absent. Surface has no canonical state, FACT, permission, action request, appraisal acceptance, or affect-effect authority.
3. Each control's typed, complete Dynamics and Persona roots are fixed by the companion architecture. The admitted recipe's actual lookup set must equal its declared manifest. Formula coefficients and renderer bands are versioned configuration and require separate production admission; surface-reference-v1 remains TEST_ONLY.
4. IntentEngine may use contact_seeking, initiative and confrontation as bounded typed modifiers. Composition rejects any scored rule whose direct Dynamics roots intersect the transitive roots of a scored control, or whose scored controls share any Dynamics or Persona root. Surface-aware rules have no event bonus in V1. Runtime checks snapshot, Persona, recipe and ruleset binding before scoring. Missing or invalid Surface withholds affected candidates; no zero/default/raw fallback. ActionPolicy alone grants action permission.
5. In explicit SURFACE_V1 expression mode, DecisionContextCompiler admits the same Surface result after Policy ALLOW and renders confrontation, expressive_warmth and expressive_restraint as one bounded expression bundle. It disables raw-affect bands and overlapping behavioral persona style. Host forwards the renderer-admitted guidance without recomputing it or appending raw Slow numeric context. Provider realizes prose; ExpressionGuard remains independent. Contact seeking and initiative are represented through selected Intent/action, not duplicate provider instructions.
6. Surface is recomputed on restart from canonical state and immutable versioned config. Projected/committed phase, runtime/affect scope, interaction/tick, Persona revision/digest, per-state IDs/versions, recipe revision/digest and dependency digest form the result lineage. No independently writable Surface store is created. Admitted Intent and actual provider attempts retain bounded, immutable consumer-use evidence linked to their existing lifecycle/attempt traces. Unreconstructible historical inputs yield REPLAY_UNAVAILABLE, not an invented old result.

## Relationship to accepted ADRs

ADR-0027 and W2 are unchanged: AcceptedAppraisal stays immutable; one AppraisalProjector produces effects; UNMAPPED preserves meaning; Dynamics applies gain once; the existing application receipt remains exactly once; COGNITIVE_MEANING never becomes FACT. Surface starts after Dynamics. ADR-0006 still owns deterministic Intent and ActionPolicy separation. This ADR adds a checked Surface input and narrows direct-root scoring for Surface-aware rules. ADR-0007 still owns compiler, renderer, provider prose and ExpressionGuard; this ADR replaces its raw-affect/behavioral-style exposure only in SURFACE_V1. LEGACY remains explicit and mutually exclusive with SURFACE_V1.

## Rejected alternatives

- Let Intent, Expression or Host independently derive behavior from raw Dynamics and Persona: multiple authorities and uncheckable causal overlap.
- Send a full role card or raw trait/state vector to the provider every turn: model behavior becomes the runtime personality authority and bypasses bounded exposure.
- Use Surface as an action or permission command: violates ADR-0006 and ActionPolicy.
- Persist Surface as a second canonical state: creates unnecessary writer/replay authority for a deterministic derived view.
- Adopt the RED Golden reference coefficients as production psychology: they are fixture arithmetic without calibration evidence.
- Keep raw affect bands alongside Surface and ask the provider not to double count: a prompt cannot enforce information isolation.

## Change-control and acceptance gates

Before implementation, accept this ADR, rebase/adapt the RED Surface Goldens to the W2 base and this decision, and admit a versioned production recipe plus expression map. Verify the single port is used by turn and tick; Persona counterfactuals and Dynamics counterfactuals; exact five-key output; no I/O/model/state mutation; state/profile/recipe lineage; per-score direct/control and pairwise-control overlap rejection including Persona roots; event-bonus exclusion; policy denial despite high control; expression budget failure before provider; provider-visible Surface guidance with no raw state; abort/restart; and W2 regression. Independent W review and complete-suite evidence remain required.

If any implementation path requires changing a W2 final invariant, making Surface a second ActionPolicy, exposing the full internal vector to provider, or bypassing root overlap validation, stop for architecture conflict. This draft authorizes no source edits, merge, push, deployment, or release.
