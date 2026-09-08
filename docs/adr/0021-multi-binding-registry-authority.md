# ADR-0021: Multi-Binding Registry Authority

- Status: ACCEPTED (R1 corrections integrated 2026-09-06)
- Date: 2026-09-06
- Supersedes: nothing; extends ADR-0020 (runtime identity binding & storage
  isolation) with a PUBLIC identity, enumeration, and admin registry surface
- Consumers: Observation Window (W2-D scoped API, W2-E URL identity,
  W2-F legacy alias; strictly read-only), upstream composition/admin seam (writer)
- Review history: initial draft → R1 review corrections §R1.1–R1.6 (below)
  integrated; ACCEPTED at R1

## Context

ADR-0020 established that one runtime binding owns four identity fields
(`persona_id`, `agent_id`, `runtime_id`, `storage_namespace`) plus an
environment, resolved through one fail-closed discovery chain
(reference > `binding.json` manifest > explicit persona). Phase 0/1 of the
Observation Window deliberately exposed NO public binding identity: OW
observed exactly one binding via the internal `binding_scope_key` token,
with "no public binding_id, no selector, no registry enumeration" frozen as
Phase 0/1 hard boundaries.

Phase 2 introduces a public, URL-safe binding identity, an enumeration
surface, and an upstream administrative registry authority so that product
pages can address a specific authoritative binding (`?runtime={binding_id}`),
legacy endpoints can alias an authoritative default, and upstream tooling can
explicitly register/manage runtime bindings. This requires an authority
decision BEFORE any contract or code: who owns the binding_id, where it is
stable, who can write, and what `list_bindings()` is allowed to return.

This ADR freezes ownership and lifecycle semantics. The upstream interface
(W2-B), upstream implementation (W2-C), OW scoped API (W2-D), URL identity
(W2-E), and legacy compatibility (W2-F) are separate gated steps and inherit
from here.

## R1 review corrections (ACCEPTED 2026-09-06, normative)

- **R1.1 — One-to-one active registry identity.** One active
  `RuntimeBinding` / `storage_namespace` has exactly one `binding_id`, and
  one active `binding_id` maps to exactly one authoritative binding.
  Duplicate public ids for the same authoritative binding (in either
  direction) fail closed at registry load and at registration (`DUPLICATE_ACTIVE_IDENTITY`,
  `DUPLICATE_BINDING_ID`).
- **R1.2 — Explicit initialization & no automatic remint.**
  - Store absent: `REGISTRY_UNINITIALIZED` → fail closed for the
    read port; zero writes performed.
  - Store corrupt: `REGISTRY_CORRUPT` → fail closed; zero writes
    performed.
  - Neither condition permits startup discovery to reconstruct or remint a
    `binding_id` for an existing `RuntimeBinding`. Recovery and bootstrap are
    explicit administrative authority only.
- **R1.3 — Upstream default authority vs OW legacy ambiguity.** Upstream
  default resolution returns exactly `DEFAULT_BINDING` (carrying the
  authoritative `BindingDescriptor` public identity carrier) or
  `NO_DEFAULT_BINDING` — it NEVER infers "the only binding" as default.
  OW (W2-F) owns the HTTP projection of the explicit conditions
  `AMBIGUOUS_BINDING` and `DEFAULT_BINDING_UNDECLARED`, derived from
  `NO_DEFAULT_BINDING` + `list_bindings()` cardinality.
  Deriving, searching, or inferring `binding_id` from `RuntimeBinding` is
  strictly prohibited.
- **R1.4 — Exact environment admission equality.**
  Admission is exact equality:
  - `PRODUCTION` admission scope → admits `PRODUCTION` only.
  - `LAB` admission scope → admits `LAB` only.
  - No environment is a superset of another. Cross-environment access is
    strictly denied (`ADMISSION_DENIED`), and other-environment entries are
    filtered upstream at the port boundary before reaching the caller.
- **R1.5 — `list_bindings()` ordering is non-authoritative.** Returned
  order carries no authority and MUST NOT be consumed as authority.
  First-entry semantics are permanently forbidden.
- **R1.6 — Upstream-only writer/admin authority & initialize safety.**
  OW remains strictly read-only. Registry mutation authority lives exclusively
  in upstream composition/administration (`initialize`, `register`, `set_default`,
  `clear_default(environment)`).
  - `initialize()` safely creates a new store; if already initialized, it fails
    closed (`REGISTRY_ALREADY_INITIALIZED`).
  - `register(binding, binding_id)` consumes an external authoritative `binding_id`
    input (validated URL-safe grammar), rejecting duplicates.
  - Default mutation occurs ONLY via `set_default(binding_id)` (which atomically
    replaces any prior default in that environment only) or `clear_default(environment)`.
    For each environment independently, exactly 0 or 1 default entry exists at all times.

## Decision

### 1. Ownership (frozen)

| Authority | Owner | Notes |
| --- | --- | --- |
| Authoritative public `binding_id` | Upstream caller / admin | provided to `register(binding, binding_id)`, immutable |
| `binding_id` stability / URL-safety | Mind Runtime | grammar `^[a-z0-9][a-z0-9-]{0,63}$`; see §2 |
| `binding_id` ↔ `RuntimeBinding` mapping | Mind Runtime | registry entry pins full ADR-0020 manifest identity |
| Registry Read Port (`list_bindings`, `resolve_binding`, `default_binding`) | Mind Runtime | OW consumes as read-only client |
| Registry Write/Admin Port (`initialize`, `register`, `set_default`, `clear_default`) | Upstream composition / admin | UPSTREAM-ONLY; OW never writes or administers |
| Default-binding authority | Upstream composition / admin | explicit flag; mutated only via `set_default` / `clear_default` |
| Ambiguity semantics | Mind Runtime (detection) / OW (HTTP projection) | upstream fails closed; OW maps to 409 |
| Registry persistence / restart semantics | Mind Runtime | see §6 |
| Removed-binding semantics | NOT ADOPTED in Phase 2 (no tombstones) | absent id = unknown = 404; revisit under a new ADR |

**OW explicitly does NOT own any of the above.** OW is a read-only consumer
of the registry read port. OW never writes, never administers, never scans
directories, never derives a binding_id from a namespace or path, never selects
"the only" or "the latest" binding, and never falls back to another binding on
resolution failure.

### 2. binding_id format and stability

- `binding_id` is a URL-safe token: `^[a-z0-9][a-z0-9-]{0,63}$`.
- It is supplied as an authoritative input to `register(binding, binding_id)`,
  persisted in the registry store, and validated once. It is NEVER re-derived
  from identity fields, namespaces, paths, or timestamps.
- It is immutable for the lifetime of the binding. A binding whose identity
  fields change is a new registration and must provide a new `binding_id`
  (fail-closed on attempt to mutate identity under an existing id).
- `binding_id != storage_namespace`. The namespace contains `/`, is not
  URL-safe, and is a storage isolation token (ADR-0020), not a public
  identity. The namespace never appears in URLs, API paths, or page state.

### 3. Registry entry and binding_id → RuntimeBinding mapping

One registry entry pins the complete ADR-0020 manifest identity:

```json
{
  "binding_id": "<url-safe token>",
  "is_default": true,
  "identity": {
    "environment": "production",
    "persona_id": "...",
    "agent_id": "...",
    "runtime_id": "...",
    "storage_namespace": "..."
  }
}
```

Reconstruction of a `RuntimeBinding` from an entry uses the same manifest
path as ADR-0020 (`resolve_storage_paths`, manifest verification). A
registry entry whose pinned identity diverges from the namespace's own
`binding.json` manifest fails closed (`IDENTITY_MANIFEST_DIVERGENCE`) — the
registry indexes authoritative bindings; it is never a second authority
over them.

### 4. list_bindings() and the descriptor

`list_bindings(*, environment)` is an upstream port returning descriptors of
REGISTERED bindings admitted to `environment`. Phase 2 descriptor is frozen to
identity data required by Phase 2:

```text
{ "binding_id", "environment", "agent_id", "runtime_id" }
```

Explicitly NOT in the Phase 2 descriptor: `storage_namespace` (internal),
`persona_id` (authority-internal), `display_name` / rich capability catalog
/ selector UX / polling semantics (Phase 3 concerns, rejected below).
Readiness is NOT part of the descriptor; OW projects availability per
binding through its existing `RuntimeStatusProvider` seam (503 projection
is an OW concern, W2-E).

### 5. Default-binding authority

- Default authority is **environment-scoped**: for each `RuntimeEnvironment`
  independently, the registry contains 0 or 1 explicit default binding
  (`binding.environment == E`).
  - PRODUCTION may have one explicit default (e.g. `production/xiyue`).
  - LAB may independently have one explicit default (e.g. `lab/experiment-a`).
  - A default in one environment never clears, shadows, or affects the default
    of another environment.
- More than one default declared within the SAME environment fails closed at
  registry load (`MULTIPLE_DEFAULTS` for that environment); the registry is
  unusable until repaired.
- The default is an EXPLICIT administrative declaration persisted in the
  registry. Forbidden forever: Xiyue-first, first registry entry,
  only-online binding, latest binding, alphabetical fallback, "the one
  whose manifest we found first", or inferring the sole binding as default.
- Default mutation is permitted ONLY via explicit writer methods:
  - `set_default(binding_id)`: resolves the target entry's authoritative
    environment $E$, atomically sets the target binding as default in $E$,
    and clears any existing default declaration in $E$ only.
  - `clear_default(environment)`: atomically clears any existing default
    declaration in `environment` only.
- `default_binding(*, environment)` returns the default (`DEFAULT_BINDING`)
  carrying the authoritative `BindingDescriptor` belonging to `environment`, or
  an explicit "no default declared" condition (`NO_DEFAULT_BINDING`); it never
  guesses and never falls back across environments. Consumers resolve
  `descriptor.binding_id` via `resolve_binding()` if the full `RuntimeBinding`
  is needed.
- Deriving, searching, or inferring `binding_id` from a `RuntimeBinding` is
  strictly prohibited. The registry-to-binding mapping is unidirectional.

### 6. Ambiguity, persistence, restart, and initialization

- **Initialization & Safety (R1.2, R1.6):**
  - An absent registry store is `REGISTRY_UNINITIALIZED`. The read port fails
    closed; zero files are created and zero writes occur.
  - First initialization requires explicit upstream administrative invocation
    of `initialize()`. Calling `initialize()` on an already-initialized store
    fails closed with `REGISTRY_ALREADY_INITIALIZED` (prevents accidental wipe).
  - A corrupt store is `REGISTRY_CORRUPT`. Zero writes occur.
  - Startup discovery NEVER reconstructs or remints a binding on uninitialized
    or corrupt store.
- **Detection of ambiguity:** N > 1 bindings, no default, legacy alias
  requested → upstream returns `AMBIGUOUS_BINDING`, never a silent pick.
  OW maps it to HTTP 409 for legacy alias resolution (W2-F).
- **Restart persistence:** The registry store persists across restarts
  (restart-stable binding_ids; W2-E refresh/bookmark stability depends on this).
  Physical location and format are an upstream implementation concern (W2-C)
  under the ADR-0020 production/LAB root isolation rules; OW never reads the
  store directly.
- **Single writer (Upstream-Only):** Only the upstream composition seam writes
  the registry. OW and product code are strictly read-only.

### 6a. Environment admission boundary (R1.4)

The registry may hold PRODUCTION and LAB entries side by side. Access is
governed by **exact environment equality** at the port boundary:
- `PRODUCTION` admission scope admits ONLY `PRODUCTION` bindings.
- `LAB` admission scope admits ONLY `LAB` bindings.
- Neither environment is a superset of another:
  - `PRODUCTION` requesting `LAB` → `ADMISSION_DENIED`
  - `LAB` requesting `PRODUCTION` → `ADMISSION_DENIED`
- Entries of other environments are excluded upstream from `list_bindings`
  before reaching the consumer.
- The Phase 0/1 production-refuses-LAB guard remains and is layered beneath
  this boundary.

### 7. Removed bindings

No tombstones in Phase 2. A binding_id absent from the registry is
UNKNOWN → HTTP 404. A registered-but-unavailable binding (runtime not
ready) is a 503 projection (W2-E). Never a fallback to another binding.
If tombstones are adopted later, a new ADR is required.

## Alternatives considered and rejected

- **Derive binding_id deterministically from identity fields** (e.g. slug
  of agent/runtime): rejected — re-derivation makes the id appear
  changeable and couples a public token to internal authority fields;
  collisions across environments would need resolution rules that are
  themselves authority decisions.
- **OW-owned registry discovered by scanning runtime dirs**: rejected —
  violates the Phase 0/1 "no scanning" boundary, duplicates authority
  downstream of the composition seam, and makes LAB/production mixing
  undetectable at the source.
- **storage_namespace as the URL key**: rejected — contains `/`, leaks
  storage topology, and conflates isolation token with public identity.
- **Default = only binding / first entry**: rejected — makes adding a
  second binding silently change legacy endpoint semantics; the failure
  mode (ambiguous legacy alias) must be explicit (409), not absorbed.
- **Environment hierarchy / superset (LAB seeing PRODUCTION)**: rejected —
  breaks isolation guarantees; exact equality prevents silent cross-talk.
- **Tombstones now**: rejected — no consumer in Phase 2; adds purge
  semantics that would need their own review.

## Consequences

- **W2-B** freezes the upstream `BindingRegistry` contracts against this
  ownership model:
  - Reader port: `list_bindings(environment)`, `resolve_binding(binding_id, environment)`,
    `default_binding(environment)` with exact equality admission.
  - Writer port (upstream-only): `initialize()`, `register(binding, binding_id)`,
    `set_default(binding_id)`, `clear_default()`.
  - Failure taxonomy: `REGISTRY_UNINITIALIZED`, `REGISTRY_ALREADY_INITIALIZED`,
    `REGISTRY_CORRUPT`, `DUPLICATE_BINDING_ID`, `DUPLICATE_ACTIVE_IDENTITY`,
    `MULTIPLE_DEFAULTS`, `IDENTITY_MANIFEST_DIVERGENCE`, `BINDING_ID_UNKNOWN`,
    `ADMISSION_DENIED`.
- **W2-C** implements this under `mind_runtime` with fail-closed identity
  validation, restart stability, and persistent storage.
- **W2-D/E/F** wire OW to the reader port; the Phase 0/1 single-binding compat seam
  (`SingleBindingRegistryAdapter`) remains for EXPLICIT-SOURCE compat mode
  but production composition migrates to the registry reader port.
