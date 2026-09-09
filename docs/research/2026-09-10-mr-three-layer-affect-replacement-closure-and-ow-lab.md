# MR Three-Layer Affect Replacement Closure + OW Lab

- Date: 2026-09-10
- Status: DECISION LOG — READY FOR IMPLEMENTATION PLANNING
- Branch: `docs/three-layer-affect-closure-20260910`
- Scope: architecture decisions reached after re-auditing the existing MR closed loop. This document records replacement boundaries and product requirements only; it does not implement contract/code changes.
- Relationship to prior design: this note refines the 2026-09-09 behavior-closed-loop design. Where the earlier document sounds like the new affect work may require redesigning MR broadly, this document is authoritative for the narrower replacement scope: **replace the affect/personality segment, preserve the existing downstream closed loop.**

## 1. Primary closure: replace, do not reconstruct MR

The existing MR product loop is already the correct skeleton:

```text
Evidence / Current World
        ↓
Situation
        ↓
Semantic Understanding / Appraisal
        ↓
Affect transition
        ↓
IntentEngine
        ↓
ActionPolicy
        ↓
DecisionContextCompiler
        ↓
Body LLM
        ↓
ExpressionGuard
        ↓
Commit / Receipt / OW
```

The new three-layer affect work does **not** introduce a second Agent, a second behavior runtime, or a pure-algorithm cognition system.

The intended replacement seam is only the middle segment:

```text
Semantic Appraisal
        ↓
[ current narrow event-kind/effect mapping ]
        ↓
Current Dynamics / behavior input
```

This will be replaced by the three-layer design while preserving the existing Intent, Policy, expression, commit, replay, authority, and observability architecture.

## 2. Three-layer target

The affect/personality replacement is conceptually:

```text
Personality Disposition
        ↓
Emotion Dynamics
        ↓
Surface Affect / Behavioral Drive
        ↓
existing IntentEngine
```

The three layers have different jobs.

### 2.1 Personality Disposition

Stable Agent-specific response tendencies.

It answers:

> Under the same accepted meaning, how is this Agent characteristically easier/harder to move, in which direction, and with what recovery/coupling tendencies?

It is not the current emotional state and is not merely prose style.

### 2.2 Emotion Dynamics

Persistent internal control state carried across turns.

It answers:

> What behavior-relevant internal pressure has accumulated, how does it decay/recover, and how does history continue to affect later behavior?

Dynamics is not required to numerically encode every named human emotion or every nuance of subjective meaning.

### 2.3 Surface Affect / Behavioral Drive

A smaller action-facing projection used to shape Intent scoring and Body stance.

It answers:

> Given current Dynamics plus current meaning, what outward control tendencies are relevant now?

It is not a new action authority. IntentEngine and ActionPolicy remain downstream authorities.

The exact dimensions/parameters of all three layers remain to be frozen before implementation.

## 3. Semantic meaning must not be crushed into affect numbers

A major correction from the day's discussion:

```text
accepted semantic meaning
        ├──────────────→ bounded cognition / Body context
        │
        └──────────────→ affect projection when authorized
```

Rich semantic Appraisal may contain meaning that is useful for natural behavior even when no affect recipe exists.

Therefore MR does **not** need to solve the impossible function:

```text
all human meaning → complete numeric psychology
```

Only the subset of meaning that should leave persistent behavior-relevant consequences needs to project into Dynamics.

The rest may remain open semantic cognition and later be exposed to Body through a bounded, non-authoritative context item such as the `COGNITIVE_MEANING` direction already proposed in ADR-0027.

This preserves the key boundary:

```text
Semantic Appraisal != Affect State
```

## 4. LLM authority boundary

MR remains a hybrid system rather than a pure-algorithm replacement for LLM intelligence.

### Semantic LLM may

- interpret open natural language;
- resolve references/ambiguity;
- propose what happened;
- propose relational/contextual meaning;
- provide bounded confidence/salience/evidence-linked semantic proposals.

### Semantic LLM may not

- directly write canonical psychological state;
- directly choose final affect values;
- directly score/select/permit Intent;
- directly grant action permission;
- directly mutate Persona.

### MR owns

- state admission and canonical truth;
- whether accepted meaning projects into internal state;
- deterministic Dynamics evolution;
- persistence/recovery/coupling/limits;
- Intent authority;
- ActionPolicy permission;
- bounded context compilation;
- commit/replay/provenance.

### Body LLM owns

Natural execution inside an already bounded behavior contract.

Body LLM may use rich meaning and stance to produce natural language, but it must not regain the authority to change the selected action, facts, policy, Persona, or internal state.

A useful product boundary is:

```text
WHAT / permission      → MR
STANCE / control bias  → MR-provided bounded context
HOW / wording          → Body LLM
```

## 5. Current MR affect control: what is algorithmic today

The existing implementation already establishes the desired authority principle.

Current fast affect flow is approximately:

```text
Semantic Provider
  → event kind + confidence

EventEffectRule
  → target dimension + base_amount

EffectMapper
  → impulse = base_amount × candidate confidence

DynamicsEngine
  → impulse × Persona sensitivity
  → recovery
  → relationship modifier
  → coupling
  → clamp
  → proposed affect state
```

Therefore final affect state is Runtime-controlled, not LLM-authored.

The LLM currently influences the input by selecting semantic kind and confidence, but does not directly output `anger += X` or a final canonical affect value.

This principle is preserved in the three-layer replacement.

The problem with the current implementation is not the deterministic Dynamics idea itself. The narrow point is the mapping seam:

```text
event_kind → EventEffectRule
```

It is too closed and too coarse for open semantic Appraisal.

The three-layer work replaces/expands this seam; it does not throw away the deterministic Dynamics/Intent/Policy architecture.

## 6. StateBar integration direction: one semantic understanding, multiple bounded consumers

StateBar and MR must not create a serial double-LLM interpretation chain such as:

```text
message
→ StateBar LLM interpretation
→ canonical StateBar state
→ another MR LLM interpretation of that state
→ affect
```

For MR-integrated operation, the preferred direction is a shared top-level semantic pass that may emit multiple proposals from the same understanding:

```text
current message + authorized current state/context
                  ↓
           shared semantic frame
             /             \
            /               \
StateBar observation      MR appraisal meaning
proposal                  / semantic evidence
    ↓                           ↓
StateBar validator/       MR admission/projection
reconciler
```

StateBar remains the authority for factual/reality state reconciliation. MR remains the authority for psychological state and behavior.

StateBar may still retain its own extractor for standalone use. The shared semantic-pass integration is an MR integration direction to avoid redundant semantic consumption; the exact contract is not implemented by this note.

## 7. Bootstrap is a starting estimate, not immutable truth

Role cards, questionnaires, and historical hot-start inference provide an initial Persona estimate.

The product lifecycle should be:

```text
Role Card / Questionnaire / History
              ↓
      Bootstrap Persona
              ↓
        Real usage
              ↓
   User observes mismatch
              ↓
        OW manual tuning
```

This is intentional product behavior, not a failure of the bootstrap system.

Natural-language personality descriptions are underdetermined. The system cannot guarantee that the first compiled parameters exactly match the user's concept of the Agent.

Therefore:

> Automatically inferred Persona values are defaults/starting points, not uneditable truth.

## 8. OW requirement: parameters must be directly tunable

All meaningful Persona parameters and algorithm weights expected to require calibration should be configuration-backed rather than unnecessarily hard-coded.

OW should expose straightforward editing for relevant three-layer parameters, including whatever is finally frozen under categories such as:

```text
Personality
- baseline/disposition values
- sensitivity/reactivity
- recovery/decay parameters
- coupling
- thresholds

Emotion Dynamics
- algorithm weights
- decay/recovery constants
- coupling strengths
- projection/gating thresholds

Surface Affect / Behavior projection
- projection weights
- thresholds
- behavior-drive weights/modifiers
```

This is a normal configuration-management requirement, not a new authority subsystem.

The design should remain simple:

```text
OW edit
→ schema/range validation
→ save config
→ Git diff/history
→ rollback when needed
```

Git-backed configuration history provides sufficient ordinary audit/recovery for this tuning use case.

The implementation should not invent a separate "Parameter Control Plane" unless future evidence requires one.

## 9. OW Developer Mode / MR Lab

A separate developer/test mode may deliberately unlock much stronger controls than normal user tuning.

Developer mode may expose:

- all Persona/config weights;
- direct live Dynamics sliders;
- direct Surface Affect/control sliders;
- extreme-value injection;
- reset/snapshot utilities;
- Agent cloning/forking for experiments;
- side-by-side behavior comparison.

Example:

```text
Xiyue-Normal
  → normal Persona/config/state DB

Xiyue-Evil / Rage-Test
  → high irritation/assertion reactivity
  → low restraint / altered recovery
  → independent Persona/config/state DB
```

Because MR supports multiple Agent consumers, these experimental variants should remain isolated by Agent identity/scope and their own state/database/configuration so they cannot contaminate the normal Agent.

Direct manual state injection is allowed in Developer Mode. It is useful for testing the actual end-to-end control strength of:

```text
Dynamics
→ Surface Affect
→ Intent
→ Body behavior
```

For observability, manually injected changes should simply be marked in OW traces as synthetic/manual override so they are not confused with algorithm-generated transitions.

This trace marker is diagnostic metadata, not a restriction on the experiment.

## 10. Why MR Lab matters technically

Extreme profiles provide a direct end-to-end test of whether MR is genuinely controlling behavior.

For the same input, two isolated Agents with materially different Persona/Dynamics parameters should produce observably different:

- internal trajectories;
- behavior tendencies;
- selected Intent/motive where relevant;
- stance/expression behavior.

If extreme parameter differences still produce nearly identical output, the likely defect is downstream consumption strength rather than the Persona data itself.

Therefore MR Lab is both a developer tool and an executable capability-boundary test.

## 11. What is frozen today

The following conceptual decisions are considered closed for the next implementation phase:

1. **This is a replacement of the affect/personality segment, not a reconstruction of MR.**
2. **The existing IntentEngine → ActionPolicy → DecisionContext → Body LLM → Guard closed loop remains.**
3. **Open semantic meaning may survive independently of affect projection and may be consumed by Body as bounded cognition.**
4. **Semantic LLM has interpretation/proposal authority, not canonical affect/action authority.**
5. **Final affect-state evolution remains Runtime/algorithm controlled.**
6. **The current narrow `event_kind → EventEffectRule` seam is the main part to replace/expand.**
7. **The new conceptual stack is Personality Disposition → Emotion Dynamics → Surface Affect/Behavioral Drive.**
8. **Bootstrap Persona values are editable starting estimates.**
9. **OW must expose tunable Persona and algorithm parameters with simple Git-backed diff/rollback.**
10. **Developer Mode / MR Lab may expose direct live-state and extreme-value controls for isolated test Agents.**
11. **Multi-Agent experimental personalities must remain identity/state/database isolated.**
12. **StateBar/MR integration should avoid redundant serial semantic interpretation; shared semantic understanding with separate authority consumers is the preferred direction.**

## 12. What is deliberately not frozen yet

Tomorrow's design/implementation work still needs to freeze:

- exact Personality Disposition dimensions and parameters;
- exact Emotion Dynamics basis;
- exact Surface Affect / behavior-control basis;
- the deterministic projection contract from accepted Appraisal into the three-layer stack;
- the projection from Dynamics + current meaning into Intent-facing controls;
- the precise Body `DecisionContext` consumption contract for semantic meaning vs stance vs hard action constraints;
- exact StateBar shared-semantic integration contract;
- OW concrete UI layout and exact editable field set.

No new dimensions should be accepted merely because they resemble emotion labels. Each should justify a distinct persistent/control role or observable behavior capability.

## 13. Explicit non-decisions / anti-drift rules

Do not drift tomorrow into any of the following unless new evidence explicitly requires it:

```text
- full MR rewrite
- second behavior runtime
- per-user trained psychology model
- pure-algorithm replacement of natural-language intelligence
- Body LLM regaining Intent or action authority
- forcing every semantic meaning into numeric affect
- giant closed emotion taxonomy
- mandatory new parameter-authority subsystem just to support tuning
- treating bootstrap values as immutable truth
```

## 14. Development order for the next session

Proceed in this order:

```text
1. Freeze the three-layer semantics and exact candidate dimensions/parameters.

2. Define the replacement seam against the current MR contracts:
   Semantic/Appraisal
      ↓
   Personality Disposition
      ↓
   Emotion Dynamics
      ↓
   Surface Affect / Behavior Drive
      ↓
   existing IntentEngine

3. Specify how rich semantic meaning is preserved into bounded cognition/Body context without granting it state/action authority.

4. Integrate the replacement into the current pipeline without changing unrelated Intent/Policy/Expression authority.

5. Revisit and optimize internal algorithms only after the new seam is executable end-to-end.

6. Add OW configuration editing for frozen parameters and weights.

7. Add Developer Mode / MR Lab for direct state injection, extreme personas, cloning, and isolated A/B behavior tests.
```

The next phase should be judged by one product criterion:

> With the same semantic event and the same base model, different Agent parameters must produce coherent, persistent, observable behavioral differences while MR—not the Body LLM—retains state, Intent, and permission authority.
