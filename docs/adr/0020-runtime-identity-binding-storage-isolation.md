# ADR-0020: Runtime Identity, Binding, and Storage Namespace Isolation

- Status: ACCEPTED (MR-RUNTIME-01)
- Date: 2026-09-06
- Evidence base: `docs/audits/MR_RUNTIME_BINDING_REALITY_AUDIT.md`
- Supersedes: nothing (new authority; existing authorities are reused, not replaced)

## Context

MR Core is consumed today by exactly one runtime (Xiyue production via the
Hermes gateway seam), but the architecture cannot express that boundary:

- `runtime_id` values are hardcoded and divergent per plane (`"xiyue"` host,
  `"kayla"`/`"production-shadow"` shadow, `"runtime-1"` manifest) while the
  durable namespace is implicitly "whatever `~/.hermes/profiles/xiyue/runtime`
  resolves to".
- There is no `agent_id` deployment identity and no `storage_namespace`
  addressing boundary. A lab/experiment runtime composed with default paths
  silently writes into production storage.
- Restart re-binds to whichever path the new process resolves, with no check
  that it reconnected to the same durable identity.

This is a Scope/Authority/Ownership change (protected contract category 4) and
therefore goes through ADR → Contract/Golden Test → implementation.

## Decision

### 1. The four identity authorities

| Identity | Authority | Owner | Lifecycle |
|---|---|---|---|
| `persona_id` | `PersonaProfile.persona_id` (`dynamics/persona.py`), sourced from the certified manifest in production | dynamics plane (existing) | durable; outlives any runtime |
| `agent_id` | NEW — composition-level consuming-Agent identity, supplied by the integration seam that builds the runtime | `RuntimeBinding` | deployment-time; change requires a new binding (new namespace for LAB) |
| `runtime_id` | EXISTING `origin_runtime_id` / `TurnOrchestrator(runtime_id=...)` sync authority | `RuntimeBinding` supplies it; orchestrator keeps ownership | durable sync identity; production compat value `"xiyue"` is preserved |
| `storage_namespace` | NEW — the durable addressing boundary resolved at composition time | `RuntimeBinding` + `resolve_storage_paths` | namespace → one filesystem directory → one set of SQLite files |

`RuntimeBinding` is a composition/configuration object
(`src/mind_runtime/runtime_binding.py`):

```text
RuntimeBinding(persona_id, agent_id, runtime_id, storage_namespace, environment)
```

with `environment ∈ {PRODUCTION, LAB}`. All four identity fields are required
and validated (non-empty; `storage_namespace` is a relative namespace label —
no absolute paths, no `..` segments, no backslash). There are no constructor
defaults: a missing identity dimension is a construction failure (fail-closed).

`environment` is composition-level ONLY. It selects storage resolution and
isolation policy; no code below the composition layer (orchestrator, dynamics,
appraisal, memory, expression) may branch on it. There is deliberately no
`if is_lab` anywhere in Core semantics — environment differences come from
binding, configuration, storage namespace, and external adapters.

### 2. Namespace resolution and fail-closed isolation

- PRODUCTION: the only valid namespace is the compat namespace
  `"production/xiyue"`, resolving to the existing production directory
  (`~/.hermes/profiles/xiyue/runtime`, overridable by the EXISTING
  `MR_FACTS_DB` / `MR_STATE_DB` env relocation contract). This preserves the
  §11 compatibility requirement: implicit old configuration becomes an explicit
  production binding with identical physical storage.
- LAB: any namespace except the reserved `"production/xiyue"`, resolving to
  `<lab_root>/<storage_namespace>/` (default `~/.mind-runtime/lab/<ns>/`).
  LAB resolution IGNORES `MR_FACTS_DB` / `MR_STATE_DB` — ambient deployment
  config must not relocate a lab namespace.
- Containment guard: a LAB-resolved root and the production root must be
  disjoint (neither may equal or contain the other). Violation → construction
  failure. This is filesystem-level isolation (separate SQLite files), not a
  WHERE-filter (Forbidden shortcut F2).
- A LAB binding that is missing any identity dimension (including
  `storage_namespace`) fails at construction — never falls back to production
  defaults.

### 3. Binding manifest (restart reconstruction seam)

The first composition into a namespace writes `binding.json` (environment,
persona_id, agent_id, runtime_id, storage_namespace) beside the state DB.
Every subsequent composition into an occupied namespace verifies the manifest
and fails closed on identity mismatch (wrong binding into an occupied
namespace, or a LAB binding into the production namespace). This closes the
restart loop:

```text
same binding re-supplied at process start
→ same namespace resolution
→ same SQLite files
→ canonical state reloads (existing ADR-0003 path)
→ process death ≠ MR identity loss
```

### 4. Binding is not cognition

`RuntimeBinding` lives in the composition/configuration layer. Its fields are
FORBIDDEN from entering Canonical State, Evidence, C10 dimensions, Memory
items, EmotionalTransition, or Expression (Forbidden shortcuts F6/F7). The
existing `Scope` domain identities (state-plane `agent_id` derived from
persona, `cognition/tick.py:808-818`) remain the canonical-state authority —
the binding `agent_id` is a deployment identity and is never wired into
`Scope`.

### 5. Wiring (minimal)

`default_adapter` (`host/xiyue_adapter.py`) gains an optional `binding`
parameter. When absent it builds the production-compat binding from the
supplied manifest persona (`persona_id = persona.persona_id`, compat
`agent_id="hermes-xiyue"`, `runtime_id="xiyue"`,
`storage_namespace="production/xiyue"`, `environment=PRODUCTION`) — the only
permitted default, documented as production compatibility. Paths and
`origin_runtime_id` for `build_runtime_stack` then come from the binding.
No other production code path changes; `build_runtime_stack` remains the
backend construction owner.

## Consequences

- Two independently constructed runtimes over one MR Core (e.g. two LAB
  bindings) are physically isolated at the filesystem/SQLite level; a reload
  of each sees only its own writes.
- The shadow plane's divergent `runtime_id` literals are now visible as
  binding inputs (follow-up W may align them); this ADR does not change
  shadow-plane values.
- Multi-agent concurrent-write authority (two agents sharing ONE namespace)
  is explicitly out of scope and remains undefined; isolation is per-namespace.
- LCE, Hot Start, Semantic Ingestion v2, Trajectory, C10 semantics, Memory
  ontology, and cognition projection policy are untouched.
