# ADR-0022: Runtime Metadata and Canonical Memory Authority Clarification

- **Status:** ACCEPTED (MR-MEM-0A)
- **Date:** 2026-09-06
- **Ticket:** MR-MEM-0A (Architecture authority clarification only — NO production feature implementation)
- **Author:** Mind Runtime Architecture
- **Evidence Base:**
  - `docs/adr/0001-d3-closure-durable-facts-canonical-ingest.md` (D3 durable persistence baseline)
  - `docs/adr/0003-g12-restart-staged-split-state-backend.md` (D5.8 durable state backend)
  - `docs/adr/0005-atomic-affect-vector-projection.md` (Atomic affect projection)
  - `docs/adr/0020-runtime-identity-binding-storage-isolation.md` (Runtime identity, binding, storage isolation)
  - `docs/adr/0021-cognitive-turn-atomic-admission-authority.md` (Atomic turn admission and commit markers)
  - `src/mind_runtime/contracts/common.py` (`SyncFields`, `Syncable` contracts)
  - `src/mind_runtime/contracts/scope.py` (`Scope`, `ScopeDomain` contracts)
  - `src/mind_runtime/delivery/persistence.py`, `src/mind_runtime/facts/persistence.py`, `src/mind_runtime/pipeline/orchestrator.py`
- **Authority Basis:**
  - AGENTS.md (Protected contract category 3: Memory semantics; category 4: Scope, Authority, and Ownership)
  - ADR-0020 §4 (Clarified; authority-plane prohibition bounded)
- **Supersedes:** Nothing. Clarifies ADR-0020 §4.

---

## 1. Context and Problem Definition

### 1.1 The Apparent Conflict in ADR-0020 §4
ADR-0020 §4 states:

> "RuntimeBinding lives in the composition/configuration layer. Its fields are FORBIDDEN from entering Canonical State, Evidence, C10 dimensions, Memory items, EmotionalTransition, or Expression (Forbidden shortcuts F6/F7). The existing Scope domain identities (state-plane agent_id derived from persona, cognition/tick.py:808-818) remain the canonical-state authority — the binding agent_id is a deployment identity and is never wired into Scope."

This prohibition was formulated to prevent deployment-level physical hosting identifiers (`RuntimeBinding.agent_id`, `storage_namespace`, file paths) from leaking into the cognitive core and corrupting canonical state, persona identity, or affect valuation.

However, an unclarified lexical reading of this clause conflicts with established Mind Runtime production architecture:
1. **Pervasive Provenance Metadata:** All canonical persisted entities across MR (`Observation`, `Fact`, `Evidence`, `CanonicalState`, `StateTransition`, `TurnProjection`, `Intent`, `ActionRequest`, `DeliveryReceipt`, `CommitMarker`) carry `origin_runtime_id: str` and `SyncFields(scope, origin_runtime_id, object_id, version, idempotency_key)` as part of their standard persistence, sync, replay, and idempotency contracts (`src/mind_runtime/contracts/common.py`).
2. **Existing Domain Scope:** The canonical scoping contract `Scope` (`src/mind_runtime/contracts/scope.py`) explicitly includes an `agent_id` field when scoped to `ScopeDomain.AGENT`.
3. **Imminent Memory Contracts (MR-MEM-1):** Future `CommittedMemory` entities must align with MR persistence and sync standards. If ADR-0020 §4 were misread as a global lexical ban on the string name `origin_runtime_id` or `SyncFields`, `CommittedMemory` could not participate in standard distributed synchronization or audit. Conversely, if ADR-0020 §4 were not strictly bounded, implementers might mistakenly use deployment `RuntimeBinding.agent_id` or `storage_namespace` as the semantic memory owner, namespace, or partition key.

This architectural clarification ADR resolves the apparent conflict and formally freezes the authority boundaries prior to the implementation of MR-MEM-1.

---

## 2. Decision

### 2.1 Deployment / Binding Identity vs. Canonical Provenance / Sync Metadata

We freeze an explicit, non-negotiable architectural distinction between **Deployment/Binding Identity** and **Canonical Provenance/Sync Metadata**:

```text
┌────────────────────────────────────────────────────────────────────────┐
│                        PHYSICAL HOSTING PLANE                          │
│                                                                        │
│   RuntimeBinding (persona_id, agent_id, runtime_id, storage_ns, env)   │
│   • Owns WHERE the Soul lives (physical file paths, DB instances)       │
│   • Single-writer process lease & restart manifest verification        │
│   • FORBIDDEN from becoming cognitive content or semantic memory owner  │
└──────────────────────────────────┬─────────────────────────────────────┘
                                   │ resolves physical DB path
                                   ▼
┌────────────────────────────────────────────────────────────────────────┐
│                        CANONICAL MEMORY STORE                          │
│                                                                        │
│   CommittedMemory / Canonical Objects:                                 │
│   • Scope (domain, user_id, persona_id, ...) → WHAT memory is about    │
│   • origin_runtime_id / SyncFields           → WHERE it originated     │
│     (for sync, idempotency, conflict detection, replay, lineage)       │
│   • Cognitive content                        → semantic truth          │
└────────────────────────────────────────────────────────────────────────┘
```

#### 2.1.1 Deployment / Binding Identity (`RuntimeBinding`)
`RuntimeBinding` (`src/mind_runtime/runtime_binding.py`) provides deployment-level and durable-lifeline binding information.

Binding and deployment fields MUST NOT become:
- canonical cognitive content
- semantic Memory identity
- Memory partition authority
- fact truth authority
- affect authority
- provider-independent semantic meaning

In particular, the fields:
- `agent_id` (deployment-level consuming agent)
- `storage_namespace` (addressing label resolving to a physical directory)
- filesystem paths (resolved SQLite database paths)
- provider or deployment identifiers

MUST NOT be copied into `CommittedMemory` or any canonical memory contract as semantic ownership or partition fields.

#### 2.1.2 Canonical Provenance and Sync Metadata (`origin_runtime_id`, `SyncFields`)
Existing `origin_runtime_id` and `SyncFields` belong to the **provenance and synchronization plane**, not the deployment binding plane.

They are permitted in canonical persisted objects (including future `CommittedMemory`) when used strictly for:
- origin provenance (recording which logical runtime authored or committed the record)
- sync identity (uniquely identifying objects during multi-runtime sync or replication)
- replay and idempotency tracking
- conflict detection
- lineage and audit trails

They do NOT constitute cognitive content.
They do NOT establish semantic truth.
They do NOT replace physical Runtime ownership.

---

### 2.2 Memory Consequence (`CommittedMemory`)

Future `CommittedMemory` contracts:
1. **MAY carry** the current production-equivalent of `origin_runtime_id` and `SyncFields` when required by existing MR persistence, replication, and sync conventions (`src/mind_runtime/contracts/common.py`).
2. **MUST NOT introduce** a second, redundant `runtime_id`, `agent_id`, `storage_namespace`, or `binding_path` semantic ownership model.
3. **Memory Ownership Hierarchy:** Memory ownership remains physical and hierarchical:
   ```text
   authoritative Runtime
           ↓
   RuntimeBinding
           ↓
   storage_namespace
           ↓
   canonical Memory store
   ```
   Row-level `origin_runtime_id` is purely metadata describing historical origin; it is NOT the owner of the storage universe.

---

### 2.3 Scope Clarification

The existing structured `Scope` contract (`src/mind_runtime/contracts/scope.py`) remains lawful inside canonical Memory:
- `Scope` is an established MR domain/canonical scoping contract.
- Scoping fields:
  - `domain`: `USER`, `AGENT`, `RELATIONSHIP`, `INTERACTION`, `WORLD`
  - Associated identifiers: `user_id`, `persona_id`, `relationship_id`, `world_id`, `interaction_id`, and `agent_id` (when `domain=AGENT`)
- Allowing `Scope` in Memory does NOT mean `RuntimeBinding` fields have been copied into cognition.
- **Invariants:**
  - Do NOT flatten `Scope` into an untyped string.
  - Do NOT derive Memory storage ownership from `scope.agent_id`.
  - `Scope` defines what the canonical object is about, not where the physical storage lives.

---

### 2.4 Explicit Agent Boundary

`agent_id` remains:
> "consuming Body / deployment identity and, where relevant, provenance of submitted interaction."

It MUST NOT become:
- Memory owner
- Memory namespace
- canonical partition identity
- vector user identity at the shared-contract level

**Provider Adapter Translation Boundary:**
A provider adapter (e.g. external vector store, retrieval index, or relational cache) may translate an already-authorized `Scope` and namespace into provider-specific query filters internally. That internal translation is an adapter implementation detail and does NOT change canonical Memory identity or ownership semantics.

---

### 2.5 Explicit Storage Namespace Boundary

`storage_namespace` remains physical durable ownership and addressing infrastructure.
- It MUST NOT be persisted as Memory semantic content merely to prove ownership.
- Production composition resolves:
  ```text
  RuntimeBinding → Memory DB path
  ```
- Memory rows exist inside the SQLite database resolved for that storage namespace. The row itself does not need to repeat the filesystem or storage namespace identity.

---

### 2.6 Relationship to ADR-0020

> **Explicit Authority Statement:**
> This ADR clarifies ADR-0020 §4. It does not supersede or alter RuntimeBinding identity, namespace, single-writer, Production/Lab isolation, or restart semantics.

ADR-0020 §4 is an **authority-plane prohibition**, not a global lexical prohibition against canonical contracts containing an `origin_runtime_id` field for provenance/sync purposes.
- Deployment bindings cannot dictate or pollute cognitive truth, semantic identity, or affect values.
- Tracking which logical runtime authored a record (`origin_runtime_id`) and its idempotency/version (`SyncFields`) is necessary infrastructure for distributed synchronization and deterministic replay, without turning runtime metadata into cognitive state.
- ADR-0020 is preserved unchanged; this ADR records the official clarification.

---

## 3. Authority and Acceptance Matrix

The architectural boundaries frozen by this ADR are summarized below:

| Dimension | Physical Hosting (`RuntimeBinding`) | Canonical Scope (`Scope`) | Provenance / Sync (`SyncFields`) |
|---|---|---|---|
| **Core Question** | WHERE does the Soul live? | WHAT is this memory about? | WHERE did this row originate? |
| **Authority** | Composition / Deployment / Host seam | Dynamics & Canonical Domain plane | Replication / Sync / Audit plane |
| **Semantic Role** | Filesystem path & single-writer lease | Relational context & domain boundaries | Idempotency, replay, conflict detection |
| **Cognitive Status** | FORBIDDEN from cognition | Canonical cognitive boundary | Non-cognitive provenance metadata |
| **Memory Role** | Resolves physical DB destination | Filters semantic scope of memory | Row-level lineage / audit trail |
| **Owner of Universe?** | YES (for that physical process/store) | NO (describes relational target) | NO (describes origin only) |

**Core Acceptance Axioms:**
1. RuntimeBinding owns where the Soul lives.
2. Scope says what the canonical object is about.
3. `origin_runtime_id` records where the object originated for sync/audit.
4. None of these mean the Body agent owns Memory.
5. `CommittedMemory` may carry provenance/sync metadata without importing deployment identity into cognition.

---

## 4. Repository Baseline Check (MR-MEM-1 Pre-Flight Gate)

In accordance with ticket instructions, an explicit Git tracking and reproducibility audit was performed on the active workspace:

| Artifact | Git Status on Working Branch (`w/hi-2-xiyue-host-integration`) | Commit Containing Authority | Working-Tree-Only State |
|---|---|---|---|
| `docs/adr/0020-runtime-identity-binding-storage-isolation.md` | **Untracked** (`??`) | `b20ada1` on branch `w/ow-multi-agent-binding-phase02-v1` (with encoding differences) | Cleaned UTF-8 version exists only in working tree |
| `src/mind_runtime/runtime_binding.py` | **Untracked** (`??`) | `b20ada1` on branch `w/ow-multi-agent-binding-phase02-v1` (with encoding differences) | Cleaned UTF-8 version exists only in working tree |
| `tests/host/test_runtime_binding.py` | **Untracked** (`??`) | **NONE** (Never committed to Git history) | 100% working-tree-only state |

### Baseline Verdict
The authoritative RuntimeBinding implementation and test suite currently exist as uncommitted and untracked workspace state on branch `w/hi-2-xiyue-host-integration`. Furthermore, `tests/host/test_runtime_binding.py` has never been committed on any branch.

Per governance rules, this cannot be resolved by silently committing unrelated workspace files in this ticket.

Therefore:
**MR-MEM-1 status: STILL BLOCKED**
until the authoritative RuntimeBinding implementation and test baseline are formally committed and tracked in a reproducible Git branch.
