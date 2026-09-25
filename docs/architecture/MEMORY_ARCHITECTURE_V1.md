# Memory Architecture V1

Status: FROZEN ARCHITECTURE  
Date: 2026-09-25  
Scope: StateBar + Mind Runtime Memory + LCE  
Purpose: preserve the design logic so the memory architecture does not have to be reconstructed from conversation history again.

This document is the canonical design explanation for the memory stack. Individual ADRs still govern their bounded implementation decisions, but this file explains how the pieces are intended to fit together and why.

---

## 1. The problem is continuity, not storage

The system is not trying to build a larger chat-history database.

The problem is that three different kinds of continuity exist:

1. **What is true/current right now?**
2. **What happened and what unfinished direction is still explicitly in play?**
3. **What has already been understood across time, including patterns the user never explicitly stated?**

Treating all three as "memory retrieval" causes repeated reasoning, stale current state, duplicated stores, and self-reinforcing interpretations.

The frozen design therefore separates **state**, **memory**, and **compiled understanding**.

A governing principle is:

> Reason only on the delta. Once a logic relation has already been validly derived and committed as cognition, later processing should continue from that result instead of rebuilding the same understanding from raw history.

This is the same reason LCE uses Worktree/Baseline lineage rather than a stateless "retrieve everything and ask the model again" loop.

---

## 2. Historical design references: OB + Mem0 + MemoraX

The MR memory subsystem was intentionally designed by combining useful ideas from existing projects instead of reimplementing every memory primitive.

These are **design references, not runtime authority owners and not required dependencies**.

### Ombre-Brain (OB)

OB is the primary reference for the **product life of memory after it has been stored**:

- memory importance and activation;
- decay as a change in salience, not deletion of history;
- resolved/digested states;
- active surfacing versus explicit search;
- keeping durable memory separate from what should enter foreground attention now;
- explicit reinforcement rather than "retrieval happened, therefore importance increased".

What MR keeps from this direction is the principle:

> Stored does not mean foreground. Remembered does not mean currently active.

MR does not need to copy OB's complete bucket ontology or product surface.

### Mem0

Mem0 is primarily a reference for **replaceable extraction/indexing/retrieval infrastructure**:

- embedding and semantic retrieval;
- provider-backed discovery;
- indexing and candidate search;
- practical memory-tooling patterns that do not need to be reinvented.

MR deliberately does **not** grant Mem0-style provider state authority.

Provider UUIDs, vectors, ranking scores, and provider text are derived index material. Canonical MR Memory IDs and content remain runtime-owned.

### MemoraX

MemoraX is primarily a reference for **write discipline and operational reliability**:

- candidate versus committed state;
- idempotent write paths;
- replay/recovery;
- failure-aware persistence;
- commit discipline rather than optimistic direct model writeback.

MR combines this with its own authority model: model/extractor output can propose Memory, but runtime admission is the only route to canonical Memory.

### The resulting MR rule

The three references are not three subsystems running side by side.

Conceptually:

```text
OB          -> how durable memory should live, fade, surface, and stop nagging
Mem0        -> how memory can be indexed and found
MemoraX     -> how writes/replay/recovery stay reliable

MR          -> who owns canonical truth, scope, provenance, admission and authority
```

---

## 3. One closed-loop memory architecture, three cognitive timescales

The three layers are best understood as:

```text
显性短期 / explicit short-term
        StateBar

显性中期 / explicit medium-term
        MR Memory + open structures

潜意识 / latent longitudinal cognition
        LCE
```

They are not three competing databases.

They answer different questions and use different expiry/revision semantics.

---

## 4. Layer 1 — StateBar: explicit current state

StateBar owns short-lived, explicit state:

- "I am going to eat later."
- "I am waiting for a reply."
- "I am going to sleep."
- "I have a headache right now."
- a near-term plan that has a semantic validity window.

Its question is:

> **What still holds now?**

StateBar therefore owns:

- semantic time windows;
- current/temporary state;
- plan/cancel/resolve transitions;
- expiration;
- stale-event protection;
- deterministic reconciliation;
- bounded current-state snapshots.

A StateBar item expiring means:

> it is no longer current.

It does **not** mean the historical event never happened.

This is why StateBar must not be reimplemented inside MR Memory as another short-term TODO system.

---

## 5. Layer 2 — MR Memory: durable history plus explicit medium-term structure

MR Memory owns durable remembered assets admitted from Evidence/Observation authority.

Its base question is:

> **What happened, and what durable explicit context is still relevant?**

Canonical Memory stores history. It is not a current-state table and it is not a cognition table.

### 5.1 Canonical Memory

Canonical Memory remains the factual/durable semantic record.

Its identity, scope, provenance and lifecycle are runtime-owned.

Vectors, retrieval scores, Threads, LCE structures and model interpretations cannot manufacture canonical Memory authority.

### 5.2 Product attention is not truth

A durable Memory may become less likely to surface without ceasing to be historical truth.

This gives a different time meaning from StateBar:

```text
StateBar expiry
= no longer current

Memory decay
= still remembered, less likely to enter foreground attention
```

Explicit search and longitudinal analysis may still access quiet historical Memory.

Retrieval itself never reinforces Memory. Relevance discovery is not evidence of importance.

### 5.3 Medium-term explicit structures

Some durable memories form an obvious, currently unfinished line during normal interaction.

Example:

```text
I want to replace my computer
-> it is too expensive, so I will wait
-> the old machine is getting slow
-> I am looking at new machines again
```

The important object here is not a giant TODO history.

It is an explicit medium-term structure:

> "Replacing the computer is still an open line, and this is the current understood direction."

A Thread/open structure therefore exists only to represent that an explicit line is **still open** and to point at the currently relevant canonical Memory support.

It must not become a second history database.

### 5.4 What a Thread is not

A Thread is not:

- every related Memory copied into one object;
- a permanent TODO for every casual statement;
- a substitute for canonical Memory;
- a substitute for LCE;
- a complete longitudinal interpretation engine.

The canonical target is closer to:

```text
thread_id
open_question
status
origin support
current bounded support
working_summary (optional, already reasoned online)
mature
updated_at
```

The full history stays in canonical Memory. Thread support is bounded and replaceable;
legacy append-only event histories are collapsed on read rather than becoming a second
trajectory store.

---

## 6. Layer 3 — LCE: latent longitudinal cognition

LCE owns a different question:

> **What longitudinal structure has been understood across this history?**

It is the "subconscious" layer in the three-layer model, but "subconscious" does not mean "only runs while idle".

LCE has **two input paths**.

### 6.1 Path A — direct consumption of already-reasoned explicit structure

If the medium-term layer has already formed a clear logic relation during normal interaction, LCE should consume that structure directly.

Example:

```text
want to replace computer
-> price too high
-> decision: postpone
```

If this relation has already been explicitly reasoned and accepted online, LCE must not wait until a later sleep/idle cycle and rediscover the same relation from three raw Memories.

The architecture rule is:

> **Already-reasoned structure is reusable cognition. Do not pay the inference cost twice.**

Direct handoff still preserves provenance. "Skip duplicate reasoning" does not mean "skip authority checks".

For this explicit online path, the mature Thread is already the bounded working
structure. MR hands its current summary plus stable canonical Memory support to
LCE without asking another model to rediscover the same relation. LCE revalidates
the support and advances the immutable Baseline lineage. A second LCE Worktree
would only duplicate the Thread's already-completed working-state role.

LCE Worktrees remain the draft/confirmation mechanism for the latent-discovery
path, where the structure was not already formed online.

### 6.2 Path B — latent discovery from unstructured history

Other patterns were never explicitly formed online.

Example:

```text
March: avoids company activities
May: starts eating alone more often
July: occasionally looks at jobs
September: wording about work gradually changes
```

No single interaction necessarily created the explicit conclusion:

> "The user may be gradually disengaging from the current job."

This is where sleep/idle/nearline LCE discovery is valuable.

LCE may inspect unstructured history, discover a candidate relation, create a Worktree, and eventually promote an accepted Baseline if support is sufficient.

### 6.3 Sleep is a discovery opportunity, not a mandatory recomputation pass

The wrong architecture is:

```text
store everything during the day
-> at night re-read everything
-> infer again
```

The intended architecture is:

```text
already understood online
-> hand off the existing structure

not yet understood
-> leave available for later LCE discovery
```

Sleep/idle processing exists for the second category.

---

## 7. Git / Worktree analogy

The Git analogy is conceptual, not a literal storage schema.

A useful mapping is:

```text
canonical Memory history
≈ durable source history / commits

CognitionWorktree
≈ current proposed understanding being revised

Baseline revision
≈ accepted compiled understanding

current Baseline HEAD
≈ the latest accepted cognitive starting point
```

The key consequence is incremental reasoning.

Suppose the history is:

```text
M1 want a new computer
M2 price feels too high
M3 decide to postpone
```

Once this has become an accepted Baseline:

```text
B1:
wanted replacement
-> price became the blocker
-> current decision: postpone
```

a later event:

```text
M4 old computer is becoming slow
```

should be processed as:

```text
B1 + M4
-> Worktree candidate B2
```

not:

```text
M1 + M2 + M3 + M4
-> re-derive B1
-> then derive B2
```

After the user buys the new machine:

```text
B3:
replacement completed
```

becomes the new cognitive starting point.

A later concern such as "should I sell the old computer?" is naturally a new branch from the already-accepted world in which the replacement has happened. It does not require reopening the old question of whether the user replaced the computer.

This is the practical meaning of **Compiled Cognition**:

> the system continues from what has already been understood.

---

## 8. The closed loop

The full architecture is:

```text
interaction / evidence
        |
        +-----------------------------+
        |                             |
        v                             v
StateBar                        MR canonical Memory
what is current now             what happened
        |                             |
        |                       explicit open line
        |                       / medium structure
        |                             |
        |                    +--------+---------+
        |                    |                  |
        |                    v                  v
        |           already reasoned       still unstructured
        |                    |                  |
        |                    v                  v
        |              direct LCE input    LCE discovery
        |                    |                  |
        |                    |              LCE Worktree
        |                    |                  |
        |                    +--------+---------+
        |                             v
        |                         Baseline
        |                             |
        +-----------------------------+
                                      |
                                      v
                         next cognition starts here
```

Each layer consumes **new information or unresolved structure**, not the entire history again.

---

## 9. Surfacing after compiled cognition

Ordinary semantic retrieval remains useful, but it is not the highest-level continuity mechanism.

If a current query touches a topic that already has an accepted longitudinal Baseline, the runtime should prefer supplying the **compiled current understanding** plus only the Memory details needed for the current turn.

Example history:

```text
wanted a new computer
-> decided not to buy because of price
```

Current user input:

```text
"Can you check the M4 price?"
```

The ideal context is not merely the highest-scoring old Memory.

It is closer to:

```text
Accepted understanding:
the user previously wanted to replace the computer but postponed because of price.

New event:
the user is asking about M4 pricing again.
```

This supports a natural response such as:

> "I'll check. You had decided not to replace it because of the price before — are you considering it again?"

The continuity comes from the existing logic line, not from pretending that one old Memory became irrelevant merely because time passed.

Memory attention/surfacing still matters for ordinary supporting detail and for material not represented in compiled cognition. It must not replace longitudinal state with a single ranking formula.

---

## 10. Authority and anti-self-pollution

The system preserves strict authority boundaries across all three layers.

### 10.1 Current state

Extraction/model output may propose state.

Deterministic/runtime-owned reconciliation decides canonical current state.

### 10.2 Memory

Evidence and admitted Observation remain factual authority.

Memory extraction creates candidates, not commit permission.

Retrieval/provider output cannot become canonical content.

### 10.3 Medium structures

A Thread/open structure is derived product state.

Its existence does not make its interpretation factual.

A model may propose that a new Memory relates to an open line; durable mutation remains runtime-governed.

### 10.4 LCE

Worktrees are hypotheses/draft cognition.

Baselines are accepted derived cognition with source support and revision lineage.

A Baseline is still not new factual Evidence.

Repeated retrieval, repeated model wording, or repeated reading cannot increase factual authority.

### 10.5 User authority over subjective meaning

For first-person subjective meaning, preference, intention and self-interpretation, an explicit user correction outranks a model interpretation.

If the system infers:

> "You were sad about losing the item."

and the user says:

> "No. I was happy because I could finally replace it."

the interpretation must not survive merely because the old inference was previously generated.

The underlying event can remain historically true while the derived interpretation is rejected.

---

## 11. Why there is no second Memory store

MR Memory is the shared durable asset substrate.

LCE can maintain its own derived research/runtime artifacts such as Semantic Blocks, Worktrees, Baseline revisions and indexes, but that does not create a second factual Memory authority.

The production binding uses stable MR Memory identities and provenance.

Likewise, Threads do not require a parallel MR-to-LCE bus.

Conceptually:

```text
same canonical Memory assets
        |
        +--> retrieval/surfacing
        +--> explicit open structures
        +--> LCE longitudinal compilation
```

Different consumers apply different policies to the same historical assets.

---

## 12. What each layer is allowed to forget

The word "decay" means different things in each layer.

### StateBar

May forget currentness:

> this is no longer true now.

### MR Memory product layer

May forget foreground attention:

> this still happened, but it no longer needs to be surfaced routinely.

### LCE

May revise or invalidate an interpretation:

> this explanation is no longer adequately supported.

These must not be collapsed into one TTL.

---

## 13. Current implementation alignment and known gaps

This section distinguishes architecture from implementation.

### Already aligned

- StateBar is a separate short-lived current-state service.
- MR has canonical Memory with stable IDs, Scope, provenance, admission and lifecycle.
- vector/embedding projections are rebuildable and non-authoritative.
- retrieval resolves provider hits back through canonical Memory.
- retrieval does not itself create factual authority.
- MR has an optional current-LCE binding over canonical Memory IDs.
- Thread is now a bounded working structure with origin/current support, optional
  already-reasoned summary, and explicit maturity; it no longer owns
  PROGRESS/REVERSAL trajectory semantics or an append-only history.
- a mature Thread can be handed to LCE without another semantic-model call; LCE
  revalidates every supporting canonical Memory ID before Baseline revision.
- accepted LCE Baselines can be read back into HistoricalContext without
  reasoning; when enabled, compiled cognition is placed ahead of raw Memory
  retrieval inside the shared bounded context budget.
- automatic Thread maintenance is wired into the committed turn path. It reuses
  the already-accepted semantic event from the turn; there is no second Thread
  classifier/model call. Explicit `thread_action/thread_question/thread_summary`
  attributes are resolved back to ACTIVE canonical Memory support before a
  Thread may open, update, mature, or resolve.
- Thread identity/update is deterministic and bounded: exact/open-question and
  lexical overlap are used only to choose an existing open Thread; they do not
  create factual authority. A Thread matures only after an explicit working
  summary has support beyond its origin.
- LCE standalone V1 still owns its latent Semantic Block -> structure ->
  Worktree -> Baseline research/runtime path.
- MR exposes a bounded read-only temporal view for LCE Path B. Evidence/source
  chronology remains separate from proposition-valid Reality time, and multiple
  Reality Observations remain separate rather than being collapsed.
- Path B can inject that MR-authoritative temporal view through the existing LCE
  consolidator context without copying canonical Memory into an LCE factual store.

### Current implementation gaps relative to this frozen design

1. **Autonomous latent-discovery scheduling remains separate from the production read seam.**  
   MR now supplies canonical Memory plus authoritative temporal context to the
   LCE consolidator without a second factual store. What remains optional is
   when/how an idle or nearline policy chooses unstructured Memory
   neighborhoods; that scheduler is not a correctness requirement and does
   not change factual authority.

2. **Accepted cognition serving remains opt-in.**  
   `build_memory_history(..., lce_enabled=True)` prefers applicable accepted
   Baselines, but production composition keeps LCE disabled unless explicitly
   configured and the current LCE package is installed.

3. **Sleep/idle scheduling is not a correctness requirement.**  
   It remains a useful discovery mode for unstructured history, not a required
   pass over all Memory.

4. **Memory attention ranking is secondary.**  
   Attention/surfacing governs foreground visibility of ordinary Memory. It
   must not replace or flatten an already-compiled longitudinal logic line.

These are implementation tasks, not reasons to redesign the architecture.

---

## 14. Rules for future memory projects

When evaluating a new memory framework, paper or repository, do not ask:

> "Should this replace our memory system?"

First classify what problem it solves:

```text
current state?
durable factual memory?
index/retrieval?
foreground surfacing?
explicit unfinished line?
longitudinal structure discovery?
compiled cognition lineage?
write/replay reliability?
```

Then map the useful mechanism into the existing owner.

A new project does not justify a fourth memory layer merely because it uses new terminology.

---

## 15. Frozen summary

The architecture can be reduced to four sentences:

1. **StateBar stores what is current.**
2. **MR Memory stores what happened and which explicit medium-term lines are still open.**
3. **LCE stores what those histories have already been understood to mean, with Worktree/Baseline lineage.**
4. **Once a relation has been validly reasoned and compiled, future cognition continues from that result; only new or unresolved material should be reasoned again.**

That is the closed loop.

