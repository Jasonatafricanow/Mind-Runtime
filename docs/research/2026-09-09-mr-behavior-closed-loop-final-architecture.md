# MR Behavior-Closed-Loop Final Architecture

- Date: 2026-09-09
- Status: FINAL DESIGN CONFIRMATION
- Branch: `docs/behavior-first-product-loop-20260909`
- Scope: final conceptual architecture for behavior-first Emotion Dynamics, personality modulation, proactive topic genesis, LCE/StateBar integration, and existing Intent/ActionPolicy/Expression authority.
- Authority note: this is a design freeze for the next architecture phase. It does not modify current production contracts or the scope of ADR-0027. Any contract change still requires ADR -> Contract/Golden Test -> implementation.

## 1. Product target

The final product is **observable Agent behavior**.

Users do not buy an emotion ontology. They perceive whether the Agent:

- initiates contact at a meaningful time;
- brings up a relevant unfinished topic instead of generic small talk;
- follows up on real-world events;
- changes warmth, directness, persistence, initiative, or distance after prior experience;
- preserves disagreement and boundaries;
- repairs mistakes through changed behavior;
- shares new thoughts that formed from shared history;
- waits when acting would be intrusive;
- carries consequences across time and later recovers when the underlying state changes.

Everything internal is justified only insofar as it improves this observable behavior.

## 2. Preserve MR's existing core advantage

The accepted semantic-late-projection direction remains the foundation:

```text
Semantic Event != Emotional Classification
Semantic Appraisal != Affect State
Projection != Semantic Authority
```

MR does not enumerate every possible emotional meaning or event-to-emotion rule.

Open semantic understanding is used to determine what the current event means; deterministic runtime projection then decides how that meaning affects finite internal dynamics.

This avoids the impossible enumeration approach.

## 3. Final conceptual pipeline

The system is not a single linear emotion-classification pipeline. It is a behavior loop with two interacting candidate sources: internal state and available topics.

```text
                         External / Current World
                         StateBar / fresh signals
                                  │
                                  │
Interaction / Evidence ──> Semantic Appraisal <── LCE / existing cognition
                                  │                 Cognitive Frontier / Dream
                                  │
                                  ▼
                      Personality Response Kernel
                                  │
                           contribution vector
                                  ▼
                      Canonical Emotion Dynamics
                    accumulate / decay / recover /
                          couple / trajectory
                                  │
                                  ▼
                    Derived Behavior Tendencies
                                  │
                                  ├───────────────┐
                                  │               │
                                  ▼               ▼
                         Intent pressure     Topic Genesis
                                  │               │
                                  └──────┬────────┘
                                         ▼
                              Intent candidate scoring
                                         ▼
                           existing Intent lifecycle /
                                Scheduler / ActionPolicy
                                         ▼
                          selected motive + topic +
                         behavior/expression modifiers
                                         ▼
                                  Expression path
                                         ▼
                                LLM prose / media
                                         ▼
                                ExpressionGuard
                                         ▼
                              Observable Agent behavior
```

Important: **Topic Genesis is not strictly downstream of behavior selection.**

There are two legitimate proactive routes:

### Route A — internal pressure seeks a topic

```text
longing / concern / accumulated motive reaches useful threshold
-> proactive intent pressure
-> Topic Genesis searches for the best available subject
-> meaningful REACH_OUT / SHARE / follow-up candidate
```

### Route B — a topic itself creates pressure to act

```text
LCE insight / Dream hypothesis / unfinished issue / relevant external news
-> candidate becomes semantically appraised
-> curiosity / concern / excitement / other Dynamics contribution
-> proactive intent pressure
-> SHARE / EXPLORE / REACH_OUT candidate
```

This bidirectional relation is required. Otherwise the system could only decorate pre-existing proactive pressure and could not act because it genuinely discovered something worth discussing.

## 4. Personality: the Agent-specific response function

Personality is not primarily a descriptive label such as "gentle", "INTJ", or "rebellious".

The runtime meaning of personality is:

> Under the same accepted meaning, how strongly and in what direction does this Agent's internal state change?

Conceptually:

```text
DeltaDynamics = ResponseKernel(
    personality,
    accepted_appraisal,
    bounded_context,
    current_dynamics
)
```

Example: the same meaningful event is "an important person is unexpectedly late".

One personality may produce mostly irritation; another may produce mostly concern/vigilance; another may barely react.

That difference is stable individuality.

Personality may also later modulate recovery, coupling, thresholds, and behavior-expression projection, but no UI personality taxonomy is frozen here.

## 5. Emotion Dynamics: the hidden kitchen

Emotion Dynamics is an internal, continuous, persistent, compositional state space.

It answers:

> What lasting internal pressures has experience left behind, and how are they changing over time?

Dynamics dimensions may:

- accumulate;
- decay;
- recover toward baseline;
- interact/couple;
- have different timescales;
- preserve trajectory information relevant to later behavior.

The current four dimensions (`longing`, `irritation`, `anxiety`, `excitement`) are existing engineering dimensions, not a researched final basis.

They must be re-evaluated together with any new candidate dimensions during the next Dynamics Requirement Derivation phase.

The design does **not** start from "how many human emotions exist?".

It starts from:

> Which persistent degrees of freedom are necessary to generate the observable behavior space under different histories and personalities?

Dynamics may be richer / higher-dimensional than the final behavior-facing space. This is expected.

## 6. Surface emotion labels are not the product control ontology

Natural-language descriptions such as:

```text
misses the user
worried
jealous
hurt
disappointed
relieved
grateful
curious
excited
```

can be generated dynamically from:

```text
Dynamics state
+ Dynamics trajectory
+ current semantic Appraisal
+ bounded context
```

They are useful for:

- OW observability;
- Agent self-description;
- debugging and research;
- natural-language expression.

They are **not required to become canonical Dynamics axes** and are **not required as a mandatory routing stage before behavior**.

This is a direct consequence of late-bound classification: MR does not need to decide "this is jealousy" before it can produce the appropriate behavior.

## 7. Behavior-facing projection: small control space, not an emotion catalogue

The downstream product seam should be a **derived behavior-tendency/control vector**, not another large emotion enum and not a new action authority.

Example candidate controls (illustrative, not yet frozen):

```text
initiative / approach
engagement / persistence
attention / checking
exploration / topic expansion
sharing pressure
care / support pressure
challenge / boundary pressure
repair pressure
withdrawal / distance
warmth
energy
restraint
directness
urgency
```

These controls are projections of internal state for use by the existing Intent and Expression pipeline.

They do not directly perform actions.

A rich internal Dynamics vector can project into a smaller behavior-facing vector. Multiple different internal states can produce the same immediate outward tendency while retaining different future trajectories.

## 8. Do not create a parallel "Behavior Runtime" authority

MR already has an Intent lifecycle, Scheduler, ActionPolicy, bounded Expression path, and ExpressionGuard.

The new design must plug into these existing seams rather than create a second action system.

Therefore terms such as:

```text
REACH_OUT
EXPLORE
SHARE
CHALLENGE
CARE
REPAIR
WITHDRAW
WAIT
```

are currently **product behavior coverage labels**, not frozen kernel enums or a new authority layer.

During implementation, they must either:

- map into existing Intent candidate semantics;
- become scoring dimensions / motive annotations;
- become expression modifiers;
- or remain only test/coverage categories.

`WAIT` in particular is best treated as a legitimate no-action/withhold outcome compatible with Scheduler/ActionPolicy, not automatically as a new executable intent.

## 9. Motive is not behavior

Do not create separate action classes for every emotional motive.

For example:

```text
missing the user
concern
curiosity
anticipation
excitement
jealousy
```

may all contribute to proactive interaction, but they do not require separate message types.

A useful representation is:

```text
Intent candidate:
  action direction
  motive annotations / contributing dynamics
  topic candidate
  urgency
  behavior modifiers
  expression modifiers
  provenance
```

Thus:

```text
"I miss you, what are you doing?"
```

and:

```text
"You had that interview today. How did it go?"
```

may both be proactive contact, but the second obtains its subject from current context rather than from a new behavior class.

## 10. Proactive Topic Genesis

Meaningful proactive behavior requires a bounded mechanism for finding **what is worth talking about now**.

Candidate sources:

```text
A. StateBar
   current/recent external state

B. pending / unfinished events
   appointments, promised follow-ups, unresolved real-world outcomes

C. conversation open loops
   questions or issues left unresolved

D. LCE / Compiled Cognition
   established reusable understanding

E. Cognitive Frontier
   unresolved hypotheses and open questions

F. Dream / offline reflection
   newly formed non-authoritative hypotheses

G. shared memories / callbacks
   when relevant rather than retrieved for their own sake

H. fresh external signals
   news/research/events that connect strongly to existing interests or frontier
```

The resolver ranks candidate topics by factors such as:

```text
relevance
novelty
timeliness
cognitive value
relationship fit
unfinishedness
confidence / uncertainty
intrusiveness
```

These are conceptual factors, not yet frozen numeric fields.

The resolver may return no suitable topic.

## 11. Proactivity examples

### Pure missing / no better topic

```text
Dynamics -> proactive pressure
Topic Genesis -> no stronger candidate
Intent -> simple relational reach-out
```

The generic "I miss you" form remains a valid fallback.

### Missing + unfinished event

```text
Dynamics -> proactive pressure
StateBar / pending context -> interview completed today
Topic Genesis -> interview outcome ranked highly
Intent -> reach out about interview
```

The same underlying proactive desire becomes meaningful because context supplies the topic.

### Concern from current reality

```text
StateBar -> user drank heavily last night
Semantic Appraisal -> possible current discomfort / wellbeing relevance
Personality Response -> concern-related Dynamics contribution
Topic Genesis -> current condition / hydration
Intent -> proactive check-in / care-shaped interaction
```

StateBar provides facts only. It does not directly write psychology or action permission.

### New LCE / Dream insight

```text
history + compiled cognition + unresolved frontier
-> offline recombination
-> hypothesis candidate
-> semantic appraisal of novelty/relevance
-> dynamics / intent pressure
-> proactive SHARE / EXPLORE / contact
-> user confirms / rejects / refines
-> new evidence
```

This is the observable product outlet of LCE and Dream.

The Agent does not merely remember; it returns with a new question or possible understanding.

### Relevant external news

```text
fresh signal
+ known user interest
+ shared research / frontier
-> high relevance
-> semantic appraisal
-> proactive pressure
-> SHARE / discussion candidate
```

The goal is not a news feed. The goal is cognition-relevant initiative.

## 12. LCE, StateBar, Dream, MR: clean responsibility split

```text
MR / Emotion Dynamics
    What internal pressure has accumulated and why might the Agent want to act?

Personality
    How strongly and in what direction does experience change the Agent?

LCE / Compiled Cognition
    What has already been understood and can be reused?

Cognitive Frontier
    What remains unresolved or uncertain?

Dream / offline cognition
    What new non-authoritative hypotheses or connections were formed?

StateBar
    What is currently/recently true in the external situation?

Fresh external information
    What new world signal may matter to the existing cognition?

Topic Genesis
    What is worth talking about now?

Existing Intent lifecycle / Scheduler / ActionPolicy
    What candidate action is selected, when may it occur, and is it permitted?

Expression / LLM
    How is the selected action naturally verbalized?

ExpressionGuard
    Does the final expression satisfy bounded expression rules?

OW
    How did meaning -> dynamics -> behavior pressure -> topic -> intent -> policy -> expression happen?
```

No component bypasses its existing authority boundary.

## 13. Product closure criterion

The architecture is successful only if users can perceive causal, persistent individuality.

Examples:

```text
The Agent did not merely remember the interview; it came back and asked how it went.

The Agent did not merely label itself worried; it noticed the current situation and checked in.

The Agent did not merely store a disagreement; it remained less accommodating on the unresolved point.

The Agent did not merely summarize old chats during sleep; it returned with a new hypothesis and asked whether it was right.

The Agent did not merely have "longing = 0.8"; it found a relevant reason to contact the user rather than repeating generic affection text.

The Agent did not randomly become cold; a prior event changed Dynamics, which reduced approach/warmth until later recovery evidence changed the state.
```

This is the product meaning of MR continuity and individuality.

## 14. Final development sequence

The current `MR-LATE-PROJECTION-01` remains isolated and completes first.

After it closes:

```text
1. OBSERVABLE BEHAVIOR COVERAGE AUDIT
   Define the user-visible behavior changes MR must be capable of producing.
   Market research is evidence here.

2. BEHAVIOR-FACING CONTROL BASIS
   Derive the smallest useful tendency/control space required to express those
   product behaviors through the existing Intent/Expression architecture.

3. DYNAMICS REQUIREMENT DERIVATION
   Re-evaluate the current four dimensions from zero.
   Derive the internal persistent degrees of freedom needed to generate the
   behavior-facing control basis.

4. PERSONALITY RESPONSE KERNEL
   Define how accepted Appraisal + personality + bounded context produce
   Dynamics contributions, and which personality parameters modulate recovery,
   coupling, thresholds, and later projection.

5. BEHAVIOR PROJECTION CONTRACT
   Define the deterministic derived projection from Dynamics + current meaning
   into behavior-facing tendencies/motives/modifiers. It must not bypass Intent
   or ActionPolicy authority.

6. PROACTIVE TOPIC GENESIS CONTRACT
   Define candidate sources, ranking, provenance, no-topic outcome, and both
   proactive routes: pressure-seeks-topic and topic-creates-pressure.

7. BOUNDED READ INTERFACES
   Only after the Topic Genesis contract is known, authorize the minimum read
   surfaces required from LCE, Frontier, Dream, StateBar, open loops, and fresh
   external information.

8. END-TO-END PRODUCT GOLDENS
   Validate observable scenarios rather than internal elegance alone.
```

## 15. Final frozen principles

1. **Behavior is the product.**
2. **Do not redesign MR around competitor emotion taxonomies.** Market research supplies behavior requirements, not ontology authority.
3. **Semantic understanding remains open and emotion classification remains late-bound.**
4. **Personality is primarily an Agent-specific response kernel.**
5. **Emotion Dynamics is a richer internal persistent state space whose dimensions are derived from behavior requirements, not from emotion-word enumeration.**
6. **The current four affect dimensions are provisional engineering history, not final research truth.**
7. **Named surface emotions are derived explanations, not mandatory canonical state or action-routing categories.**
8. **The behavior-facing projection should be smaller than and downstream of Dynamics, and should plug into the existing Intent/ActionPolicy/Expression pipeline.**
9. **Motive, topic, behavior direction, and expression are separate concerns.**
10. **Meaningful proactivity requires Topic Genesis.**
11. **Topic Genesis supports both directions: internal pressure searches for a topic; a valuable topic can itself create pressure to act.**
12. **LCE's strongest product outlet is not memory recall but reusable understanding and new hypotheses that can become proactive conversation.**
13. **Dream/offline cognition may create candidates, never automatic truth.**
14. **StateBar supplies factual context, never psychological or action authority.**
15. **Fresh external information is filtered through existing cognition and relevance; MR is not a generic news-feed engine.**
16. **No-action is a legitimate outcome.**
17. **ActionPolicy retains final permission/timing/channel authority; ExpressionGuard retains final expression boundary.**
18. **OW should expose the causal path, not become ontology or authority.**
19. **Every new internal dimension must justify itself through distinct observable behavior capability.**
20. **Every end-to-end milestone must be judged by whether the Agent actually behaves differently in a coherent, persistent, personality-specific way.**
