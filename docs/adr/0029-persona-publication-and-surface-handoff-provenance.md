# ADR-0029: Immutable Persona publication and durable W3 handoff provenance

- Date: 2026-09-23
- Status: **ACCEPTED**
- Accepted by: PERSONA AUTHORITY DECISION and ARCHITECTURE CONFLICT RESOLUTION, MR-W3-E-AUTHORITY-HARDENING-01
- Extends ADR-0028 and the E3 interpretation in `MR_ARCHITECTURE_LOCK_v1_1.md`
- Does not alter W2 appraisal, Dynamics, FACT, or ActionPolicy authority

## Decision 1: Persona revision publication

`PersonaProfile` remains the sole semantic owner of stable personality and its
complete four-field disposition. A Persona config publication repository under
the existing Persona/config boundary stores immutable, versioned schema-2
artifacts. Only an explicit config author/review path publishes. Runtime
consumption is read-only; there is no learned or runtime Persona mutation and
no second canonical personality state.

The publication identity is `(persona_id, profile_version,
effective_content_digest)`. The `(persona_id, profile_version)` slot is
create-once. Same digest is idempotent; different digest is
`PERSONA_REVISION_CONFLICT`; changed content requires a new revision. A
missing required historical artifact is `REPLAY_UNAVAILABLE`. A corrupt or
digest-mismatched artifact fails closed. Published revisions remain retrievable
while referenced by replay evidence.

`BindingRegistry` continues to own RuntimeBinding selection. It may pin an
exact `PersonaRevisionRef` on a binding but owns only that reference, not
Persona content, defaults, mutation, or publication. Restart resolves durable
RuntimeBinding → exact reference → immutable published artifact → recomputed
digest → `PersonaProfile` → Surface composition. Historical work never loads
today's mutable alias. Legacy mutable aliases remain legal for LEGACY mode;
`SURFACE_V1` requires an immutable published schema-2 revision. Publication
does not activate a real Agent. Kayla/Xiyue values remain unchanged. Future
learned personality evolution needs a separate authority decision and ADR.
Binding mutations serialize across processes so a concurrent registry writer
cannot silently replace a pinned revision. The lock is coordination only;
the existing binding document remains the selection authority.

## Decision 2: E3 consumer-use provenance

C7 `DeliveryRequest` is the existing durable Soul→Body operational handoff
envelope. `SqliteDeliveryBackend` may persist bounded, immutable W3
consumer-use provenance in that envelope. This does not give DeliveryBackend
Surface, Persona, Affect, Intent scoring, policy, or cognitive authority. It
does not interpret or recompute the provenance. No Surface store, separate
provider-attempt database, or second audit writer is introduced.

In `SURFACE_V1` the single production order is Intent → ActionPolicy ALLOW →
DecisionContextCompiler → deterministic renderer admission of the essential
action, Policy constraints and qualitative Surface bundle → durable
DeliveryRequest commit → Body/Host provider execution → ExpressionGuard.
Provider dispatch is withheld if the durable commit fails. A request pins the
admitted envelope and bounded provenance: handoff/context identity, selected
Intent and action, Policy decision/constraint references, controls ID,
recipe/map references, admitted qualitative guidance, Intent score-use ref,
renderer/admission identity and logical provider-attempt idempotency identity.
It never stores raw Persona traits, Dynamics or Surface numeric vectors as a
second state. Internal test providers and Host transport consume the same
renderer-admitted semantic envelope; they do not form parallel production
authorities.

Retry of the same logical request reuses its immutable envelope and
provenance; same request ID with different bytes or provenance fails closed.
The generic C7 carrier daemon must not send a Surface provider envelope as a
user message. Body/Host consumes that request through the admitted handoff
seam. A retrying Body resolves the request by ID and verifies runtime/scope,
candidate recipe/map identity, and the admitted action, Policy constraints,
and qualitative guidance before provider use.
Restart may inspect/retry from the durable request without recomputing
Surface, loading a current Persona alias, or needing ShadowStore or a surviving
Checkpoint. `DeliveryReceipt` and existing attempt lifecycle provide only
operational execution acknowledgement linked back to the request; they never
become experiential Evidence or reinforce Affect/Persona. Surface remains
derived and non-canonical. The candidate recipe/map and real-Agent activation
gates of ADR-0028 are unchanged.
