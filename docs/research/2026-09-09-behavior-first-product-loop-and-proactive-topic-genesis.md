# MR Behavior-First Product Loop & Proactive Topic Genesis

- Date: 2026-09-09
- Status: FINAL DESIGN DIRECTION / RESEARCH FREEZE
- Scope: product-facing behavior architecture and the interface between MR, LCE, StateBar, proactive topic selection, and expression.
- Non-authority note: this document does **not** amend frozen Dynamics contracts, ADR-0027, ActionPolicy, ExpressionGuard, LCE authority, or StateBar authority. Any future runtime contract change still follows `ADR -> Contract/Golden Test -> implementation`.

## 1. Why this direction exists

The product output of Mind Runtime is not an emotion taxonomy, a psychological dashboard, or a larger internal state model. The product output is **observable Agent behavior**.

A user does not care how elaborate the internal emotional machinery is if the resulting Agent still behaves like a generic assistant. The product closes only when internal state produces behavior that the user can notice across time:

- initiates contact for a reason;
- follows up on something that mattered;
- changes tone or degree of accommodation after prior events;
- preserves disagreement instead of collapsing into generic agreeableness;
- repairs a mistake with changed behavior rather than generic apology;
- waits instead of intruding;
- reduces investment after an unresolved negative event;
- brings up a new idea formed from previous interactions;
- uses real-world current state and prior understanding to choose a relevant topic.

Therefore the design order is:

```text
Observable Behavior
        ↑
Behavior selection / expression
        ↑
Emotion Dynamics + current meaning + context
        ↑
Personality-conditioned response to experience
        ↑
Semantic Appraisal
        ↑
Event / Situation / Evidence
```

This keeps product value as the optimization target and prevents MR from becoming an increasingly complex but behaviorally inert internal model.

## 2. Preserve the accepted MR distinction

The current late-projection direction remains intact:

```text
Semantic Event != Emotional Classification
Semantic Appraisal != Affect State
Projection != Semantic Authority
```

The open semantic layer can express arbitrarily rich meanings without first forcing them into a closed emotion taxonomy. Runtime projection remains finite and deterministic where it changes authoritative state.

This document does not reopen that decision.

## 3. Product behavior is the "dish"; Dynamics is the "kitchen"

The useful analogy is a restaurant:

```text
User-facing dish              = Agent observable behavior
Kitchen process               = Emotion Dynamics
Ingredient properties         = Personality / disposition
Order + current ingredients   = Event + Appraisal + Situation
Cooking technique selection   = late-bound semantic projection
Kitchen observation camera    = OW
```

The user judges the dish, not the complexity of the kitchen.

Accordingly, Dynamics should be evaluated by one question:

> Does this internal state dimension produce a distinct, persistent, useful difference in eventual Agent behavior?

Likewise, product behavior should not be exploded into dozens of variants merely because the motive differs.

## 4. Behavior Primitives, not emotion-specific behavior classes

Many market-facing behaviors that look different are variants of the same underlying behavior primitive.

For example:

```text
"I miss you"                  -> REACH_OUT
"How did your interview go?" -> REACH_OUT
"Are you hungover today?"     -> REACH_OUT / CARE
"I thought of something"      -> REACH_OUT / SHARE
"I still disagree"            -> CHALLENGE
```

The differences are mainly:

1. motive;
2. topic;
3. urgency;
4. expression;
5. context.

The first provisional behavior primitive set is:

```text
REACH_OUT
    Initiate an interaction.

EXPLORE
    Extend the current cognition/topic rather than merely answer the last turn.

SHARE
    Proactively contribute an Agent-originated idea, reflection, observation, or discovery.

CHALLENGE
    Preserve disagreement, refuse, assert a boundary, or push back on a judgment.

CARE
    Prioritize the user's current condition or situation and act supportively toward it.

REPAIR
    Address a problem caused by the Agent, including changed behavior rather than apology-only output.

WITHDRAW
    Reduce investment, warmth, initiative, or relational approach after relevant unresolved experience.

WAIT
    Deliberately refrain from acting even when an internal motive exists.
```

These are not yet frozen kernel enums. They are the current product-coverage basis for design and testing.

## 5. Do not create separate behavior types for every motive

The following are **not** separate behavior primitives:

```text
MISS_MESSAGE
WORRY_MESSAGE
EXPECT_MESSAGE
CURIOUS_MESSAGE
JEALOUS_MESSAGE
CELEBRATE_MESSAGE
```

Instead:

```text
Behavior = REACH_OUT
Motive = dynamics-derived
Topic = context-derived
Expression = personality/state-conditioned
```

Example:

```text
Behavior:
  REACH_OUT

Motive:
  concern + longing

Topic:
  last-night alcohol use / possible hangover

Expression:
  warm, restrained, non-nagging
```

Possible output:

> "You drank quite a bit last night. Headache today? Remember to get some water in."

The richness comes from motive + context + expression, not from multiplying behavior classes.

## 6. Personality is a response difference, not a descriptive label

Personality becomes behaviorally real when the same accepted Appraisal produces different Dynamics deltas in different Agents.

Conceptually:

```text
DeltaDynamics = Response(Personality, Appraisal, Context)
```

Example: the same event is understood as "an important person was unexpectedly late".

Agent A may produce:

```text
irritation +10
vigilance  +2
```

Agent B may produce:

```text
irritation +1
vigilance  +10
```

One becomes more annoyed and boundary-oriented; the other becomes more worried and checking-oriented.

That difference is personality.

The personality layer therefore belongs in the response function that changes Dynamics, and later in the projection from state to behavior/expression. It should not be reduced to a prose persona label.

## 7. Emotion Dynamics should remain internal and compositional

The current four dimensions (`longing`, `irritation`, `anxiety`, `excitement`) were engineering choices used to establish the first MR wiring. They are not treated here as a researched final basis.

Future Dynamics design should not start from "what emotions exist?" or "how many axes do other projects have?".

It should start from:

> Which persistent internal pressures are required to generate the product behavior space under different histories and personalities?

Dynamics may be higher-dimensional than the final behavior-facing control space. Multiple Dynamics can combine to produce one outward behavior.

Example:

```text
attachment pressure
+ concern / threat vigilance
+ current health-relevant situation

-> REACH_OUT / CARE
```

Likewise, similar outward behavior can arise from very different internal causes, which matters for later recovery and future transitions.

## 8. Surface emotion labels are derived explanations, not mandatory control nodes

Natural-language emotional descriptions such as:

```text
hurt
jealous
relieved
grateful
disappointed
worried
affectionate
```

can remain rich and effectively open-ended.

They may be derived from:

```text
Dynamics state
+ Dynamics trajectory
+ current Appraisal
+ bounded context
```

and used for:

- OW observability;
- Agent self-expression;
- debugging;
- research;
- user-facing explanation where appropriate.

They do **not** need to become canonical state axes or mandatory behavior-routing nodes.

Behavior can legally be derived from the underlying state and current meaning without first forcing the combination into one named emotional category.

## 9. The missing product component: Proactive Topic Genesis

Proactive behavior is not complete when MR can answer only:

> "Should I contact the user?"

It also needs:

> "If I contact the user now, what is actually worth talking about?"

This is the purpose of **Proactive Topic Genesis / Topic Resolver**.

It is not a new semantic authority and not a new memory system. It is a bounded selection layer that ranks existing, authorized candidate material for a chosen behavior.

Conceptual flow:

```text
MR Dynamics
    ↓
Should act?
    ↓ yes
Behavior Primitive selected
    ↓
Topic Resolver
    ↓
Rank candidate topics
    ↓
Chosen TopicCandidate
    ↓
Expression / provider
```

Candidate sources may include:

```text
StateBar current reality
Pending commitments / planned events
Conversation open loops
LCE compiled cognition
Cognitive Frontier unresolved hypotheses
Dream / offline reflection candidates
Shared memories / callbacks
Fresh external signals relevant to known interests
```

These sources retain their own authority. Topic Resolver consumes them; it does not convert them into FACT or Memory authority.

## 10. Why Topic Genesis matters

Without Topic Genesis, proactive messaging degenerates into repetitive relationship filler:

```text
"What are you doing?"
"I miss you."
"Just wanted to check in."
```

With Topic Genesis, the same REACH_OUT behavior can produce different meaningful interactions.

### Example A: unfinished real-world event

Known situation:

```text
User had an interview today.
Current time is after the event.
```

Behavior:

```text
REACH_OUT
```

Topic:

```text
interview outcome
```

Output direction:

> "How did that interview go today?"

### Example B: StateBar-relevant current state

StateBar:

```text
User drank heavily last night.
```

MR:

```text
concern-related pressure elevated
```

Behavior:

```text
REACH_OUT / CARE
```

Topic:

```text
possible hangover / hydration
```

The user perceives memory, concern, and relevance rather than a generic affection message.

### Example C: LCE-created new understanding

LCE / compiled cognition produces a candidate such as:

```text
The user may not dislike repetitive work itself;
they may dislike work that contains too little unresolved structure to model.
```

This does not become canonical truth merely because it was inferred.

It can become a topic candidate:

> "I kept thinking about what you said about work being boring. I wonder if the problem isn't repetition itself, but that there is nothing left there for you to model. Does that fit?"

The user can reject it, weakening/closing the candidate, or confirm it, generating new evidence and a new discussion branch.

This creates a full cognition loop:

```text
history
→ LCE / offline cognition
→ hypothesis candidate
→ proactive social inquiry
→ user feedback
→ evidence update
→ cognition development
```

## 11. Dream / offline cognition should have a product output path

Offline reflection is not valuable merely because it produces more summaries.

Its strongest product path is:

```text
previous interactions
+ existing cognition
+ unresolved frontier
↓
offline recombination / reflection
↓
new hypothesis candidate
↓
Topic Resolver candidate
↓
SHARE / REACH_OUT / EXPLORE
↓
user confirmation or contradiction
```

This gives "sleeping/dreaming" an observable purpose without granting it automatic truth authority.

If the hypothesis is wrong, the user interaction can falsify it. If it is useful, a new topic and evidence path opens.

## 12. External information should serve cognition, not become a news feed

Fresh external information is useful only when it connects to existing user interests, shared research, or an unresolved Cognitive Frontier.

The intended pattern is:

```text
Fresh external signal
+ LCE interest / shared topic / frontier
↓
relevance appraisal
↓
TopicCandidate
↓
SHARE or REACH_OUT
```

Bad product behavior:

> "Here are today's AI headlines."

Desired behavior:

> "I just saw something that directly hits the question we were discussing about persona collapse; the experiment design may actually be useful for our four-Agent comparison."

The system should therefore optimize for *relationship/cognition relevance*, not generic content frequency.

## 13. Topic Resolver ranking dimensions

The first conceptual ranking factors are:

```text
relevance
novelty
timeliness
relationship fit
cognitive value
confidence / uncertainty
intrusiveness
unfinishedness / open-loop value
```

No factor is yet a frozen numeric schema.

The resolver should be allowed to return **no topic**.

If MR still selects REACH_OUT and no better topic exists, a simple relational reach-out is a legitimate fallback. Generic "I miss you" behavior therefore remains possible, but becomes a fallback rather than the only proactive expression.

## 14. Clean separation of responsibilities

The final conceptual role split is:

```text
MR
  Why is there pressure to act now?
  What persistent internal state has accumulated?

LCE
  What has the Agent learned or compiled about the user / shared history?

Cognitive Frontier / Dream
  What unresolved or newly formed hypothesis may be worth testing?

StateBar
  What is currently true or recently true in the external situation?

External information
  What has newly happened in the world that may matter to existing cognition?

Topic Resolver
  What is the best available subject for the selected behavior right now?

Behavior Runtime
  Which action direction is selected: REACH_OUT, EXPLORE, SHARE, CHALLENGE,
  CARE, REPAIR, WITHDRAW, WAIT, etc.?

Expression / LLM
  How is that action naturally expressed in language or another permitted medium?

ActionPolicy
  Is the action actually permitted, scheduled, interruptible, and allowed to use
  the requested channel/resource?
```

This preserves the existing ActionPolicy authority boundary.

## 15. Product-level examples

### Missing the user, no stronger topic

```text
MR: longing pressure high
Topic Resolver: no high-value pending topic
Behavior: REACH_OUT
Result: simple relational contact
```

### Missing the user, but interview pending

```text
MR: longing pressure high
StateBar / pending context: interview completed recently
Topic Resolver: interview outcome outranks generic contact
Behavior: REACH_OUT
Result: asks how the interview went
```

### Concern after drinking

```text
MR: concern-related dynamics elevated
StateBar: heavy drinking last night
LCE: user may have a known hangover pattern
Behavior: REACH_OUT / CARE
Topic: current physical condition
```

### Offline insight

```text
Dream / Frontier: new unconfirmed interpretation
MR: enough initiative / curiosity / relational motive to act
Behavior: SHARE or REACH_OUT
Topic: hypothesis
User response: confirm / reject / refine
```

### Preserved disagreement

```text
Appraisal: user's proposal conflicts with Agent's existing judgment
Personality: high conviction / low automatic accommodation
Dynamics/context: no reason to suppress
Behavior: CHALLENGE
Expression: personality-conditioned, bounded by policy
```

### Unresolved negative experience

```text
Prior event left relevant dynamics unresolved
Behavior pressure: approach reduced
Behavior: WITHDRAW or WAIT
Expression: lower warmth / lower initiative, not random hostility
Recovery: future evidence and dynamics can reverse the change
```

## 16. Market-research interpretation rule

Future competitor research should not ask:

> "How many emotions does this product have?"

Instead ask:

> "What user-visible behavior changes after an event, state change, memory, or relationship development?"

Then classify the finding as one of:

```text
new Behavior Primitive candidate
new motive / dynamics requirement
new topic/context source
new expression modifier
new policy / timing requirement
```

Only add a new primitive if an observed high-value behavior cannot be expressed by the existing primitive set plus motive, topic, expression, and policy.

This prevents market research from forcing MR into another project's ontology.

## 17. Final confirmation

The following design direction is confirmed:

1. **Behavior-first**: observable Agent behavior is the product optimization target.
2. **No emotion-enum product design**: do not create one behavior type per named emotion.
3. **Personality as response kernel**: the same Appraisal produces different Dynamics deltas in different personalities.
4. **Dynamics remain internal**: they accumulate, decay, recover, combine, and exist to produce persistent behavioral differences.
5. **Open meaning remains open**: semantic emotion/meaning vocabulary is not restricted to Dynamics dimensions.
6. **Surface emotion is derived**: labels may explain state but are not required as canonical state or mandatory action-routing nodes.
7. **Small behavior primitive set**: current research basis is REACH_OUT, EXPLORE, SHARE, CHALLENGE, CARE, REPAIR, WITHDRAW, WAIT.
8. **Motive != behavior**: longing, concern, curiosity, anticipation, excitement, jealousy, etc. may alter motive/state/topic priority without creating separate behavior classes.
9. **Topic Genesis is required for meaningful proactivity**: proactive behavior must have a route to select a relevant topic from current reality, history, compiled cognition, frontier, dream candidates, and fresh external signals.
10. **LCE has an observable product outlet**: new longitudinal insights can become hypotheses that the Agent proactively brings back to the user for confirmation or falsification.
11. **Dream/offline cognition remains non-authoritative**: it can generate candidates, never automatic truth.
12. **StateBar remains factual context**: it informs relevance and topic choice but does not directly mutate psychology or bypass ActionPolicy.
13. **WAIT is a real outcome**: having motive does not imply acting.
14. **ActionPolicy remains final action permission authority**.
15. **No current ADR-0027 scope expansion**: no new affect axes, LCE redesign, StateBar redesign, or production behavior implementation is introduced by this document.

## 18. Next execution order after current late-projection closure

Do not modify the current ADR-0027 implementation task to absorb this work.

After MR-LATE-PROJECTION-01 is closed, the recommended next architecture work is:

```text
A. Observable Behavior Coverage Audit
   Validate the current primitive set against market cases and MR use cases.

B. Dynamics Requirement Derivation
   Starting from behavior coverage, derive which persistent internal degrees of
   freedom are actually required. Reassess the current four dimensions without
   treating them as final.

C. Personality Response Kernel Contract
   Specify how accepted Appraisal + personality + bounded context produce
   deterministic Dynamics contribution candidates.

D. Behavior Projection Contract
   Specify how Dynamics + current meaning + personality produce behavior pressure,
   modifiers, and WAIT/act candidates without granting ActionPolicy permission.

E. Proactive Topic Resolver Contract
   Specify authorized candidate sources, ranking, no-topic behavior, provenance,
   and policy interaction.

F. LCE / Frontier / Dream read interfaces
   Only after the Topic Resolver contract proves what bounded information it needs.
```

The order is intentional: **product behavior first, then derive internal state requirements, then wire cognition/topic sources into that behavior loop**.
