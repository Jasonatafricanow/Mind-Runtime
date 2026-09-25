# ADR-0027: Three-timescale memory architecture and product governance

- Status: ACCEPTED
- Date: 2026-09-25
- Authority: closes the bounded MR Memory product architecture on top of ADR-0023 through ADR-0026.

## Decision

MR uses one durable memory asset base across three cognitive timescales. These are not three competing databases.

### 1. Current state / short-term memory — StateBar

StateBar owns temporary current state, plans, cancellations, symptoms and activities, semantic validity windows, and transition history. Expiration means the state is no longer current.

Examples include "I am eating later today", "I am waiting for a reply", and "I am going to sleep".

StateBar remains a separate bounded current-state service. MR does not copy that current-state authority into a second short-term memory implementation.

### 2. Medium/long-term memory — MR Memory

CommittedMemory remains the canonical durable semantic record admitted from Evidence and Observation authority.

The product layer adds only derived state in the same memory.sqlite:

- MemoryAttention: importance, explicit reinforcement count, resolved, digested, dont_surface;
- MemoryThread: an optional explicit unresolved trajectory over canonical Memory IDs.

Decay affects visibility, never factual truth or authority. Retrieval remains read-only and does not reinforce a Memory. Explicit reinforce is the only product operation that increases activation count.

A Thread can represent a medium-horizon concern such as "I am saving to replace my computer". It does not duplicate supporting content and it does not become Evidence.

### 3. Latent longitudinal cognition — LCE

LCE reads the same canonical Memory substrate and may discover structures that were not explicit when the original events occurred.

Its outputs are hypotheses or accepted derived cognition, not factual Memory. The user remains the highest authority over interpretations about the user's own meaning. A rejected interpretation cannot become fact through repetition.

## The resulting architecture

    interaction evidence
        |
        +--> StateBar: what is current now?
        |
        +--> MR canonical Memory: what remains durably remembered?
                 |
                 +--> attention / surfacing governance
                 +--> explicit unresolved Threads
                 |
                 +--> LCE: what latent longitudinal structure may exist?

Stable MR Memory IDs remain the shared substrate for retrieval, Threads, and LCE. Provider IDs, embeddings, retrieval scores, Thread hypotheses, and LCE Baselines never become canonical Memory identity or factual authority.

## Product governance

The product layer freezes three rules.

First, surfacing is separate from storage. A Memory can remain durable while becoming quiet.

Second, retrieval is not reinforcement. Search, automatic context retrieval, and LCE reads do not increase activation count. Reinforcement is an explicit write.

Third, resolution and digestion lower automatic visibility without deleting the underlying Memory.

Explicit search and LCE reads do not obey digested or dont_surface. Automatic and spontaneous reads do. Canonical lifecycle still wins: an ARCHIVED or SUPERSEDED Memory is not surfaced by this policy.

The default attention score is a replaceable product policy based on importance, explicit activation count, age, and a resolved multiplier. The score never mutates canonical content, provenance, lifecycle, or Evidence.

## Unresolved trajectories

MemoryThread is a product object, not a new epistemic layer.

It carries:

- stable caller-supplied thread identity;
- exact MR Scope;
- one open question;
- one to thirty-two canonical supporting Memory IDs;
- OPEN, RESOLVED, or ABANDONED status;
- bounded OPENED, SUPPORT, PROGRESS, REVERSAL, and RESOLVED events;
- product importance, touch count, suppression, and last-update time.

Every supporting event is revalidated against canonical Memory and exact Scope. Inactive or missing support prevents a Thread from automatic surfacing.

Thread surfacing decays attention without deleting the Thread. This prevents every remembered statement from becoming a permanently active TODO.

Automatic model classification of whether a message should open, touch, or resolve a Thread is outside the storage contract. A model may propose a transition; runtime code owns durable state change.

## StateBar boundary

StateBar expiration and Memory decay mean different things:

- StateBar expiry: no longer current.
- Memory decay: still remembered, less likely to surface.
- LCE revision or invalidation: an interpretation is no longer supported.

Short-lived StateBar state should not be duplicated as a medium-horizon Thread merely because it looks unresolved. If an experience later deserves durable remembrance, it uses the normal Evidence -> Observation -> Memory path.

## LCE boundary

LCE remains separate computation over the shared Memory substrate.

A Thread may be useful context for an explicitly tracked concern, but it is not an LCE truth. LCE may also discover structures for which no Thread ever existed.

No new MR-to-LCE transport or parallel Memory store is introduced. Existing stable Memory IDs and canonical substrate remain the authority seam.

## Self-pollution

Generated or retrieved cognition still cannot authorize itself.

A separate longitudinal concern remains: a real external event can be causally downstream of an agent intervention. That provenance may later constrain whether the event counts as independent support without changing whether it factually occurred. This belongs to evidence quality and LCE research, not to another Memory redesign.

## Completion boundary

After this ADR, MR Memory is architecturally closed when the following remain true:

- canonical admission, provenance, and stable identity;
- rebuildable provider projections and bounded retrieval;
- product attention and surfacing with explicit-only reinforcement;
- optional unresolved Thread lifecycle over canonical IDs;
- StateBar remains the current-state owner;
- LCE remains the latent longitudinal cognition owner;
- no derived layer may reverse-promote itself into factual Memory.

Future ranking tuning, UI, proposal-model improvements, or richer LCE algorithms are product and research changes. They are not reasons to redesign the memory store.
