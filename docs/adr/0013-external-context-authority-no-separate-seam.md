# ADR-0013: External Context Authority — NO SEPARATE SEAM

**Status:** Accepted (Ratified 2026-09-02 — C7C-R3-R2.1 + ADR-0013-RAT)
**Date:** 2026-09-02
**Parent:** `C7C-R3-R1 — External Memory Gate Authority & Production Wiring Audit` (CLASSIFICATION=C — CONTRACT NOT FROZEN)
**Supersedes:** None
**Related:**
- `C7C-R3-R2.1 — External Context Authority Contract Correction & Ratification`
- `docs/superpowers/specs/2026-09-02-external-context-authority-design.md`
- `docs/superpowers/audits/c7c-r3-r1-external-memory-authority-final-review.md`
- `ADR-0014 — C7D-Audit Delivery Capability Level`
- `MR_ARCHITECTURE_LOCK_v1_2_COMPLETE.md`

---

## Problem

A prototype "external-memory authority boundary" existed in three incompatible lineages:

1. `578672e` → reverted at `b402945` as "P0 alpha contamination mislabeled as C7C-R3"
2. `dfc8d30` — `authority_boundary.py` complete but `__init__.py` is a SyntaxError; orphan branch on top of main
3. Workspace untracked — `memory/authority_boundary.py` + `memory/__init__.py`

The `8eb8689` commit (C9-W1B) re-introduced the orchestrator wiring with a broken import path, breaking orchestrator construction at `d0d5f4f`.

The question this ADR answers: **Does MR need a separate External Context Authority Boundary seam, or do existing MR primitives already assign ownership for every plane?**

---

## Core Decision

**MR architecture assigns ownership for every required plane; no new authority seam is needed.**

The four planes are owned as follows. Implementation completeness varies by plane.

| Plane | Architecture Owner | Implementation Status |
|-------|-------------------|---------------------|
| Evidence authority | D3 | Partial |
| Memory admission | M1A | Partial |
| Retrieval / surfacing | Memory Track / SurfacePolicy | Future |
| Working-memory overlay | C9-W1B | Partial |

A **fifth** additional authority layer is rejected because the four planes above are architecturally distinct and sufficient.

---

## Existing Primitive Ownership (Frozen by Architecture)

These are the authoritative owners; they are not being changed by this ADR.

### Plane 1 — Evidence Authority

```text
Owner:        D3
Question:     "Is this input a legitimate evidence source?"
              "Does this claim have traceable provenance?"
Contract:     AuthorityLevel (USER/AGENT/EXTERNAL/PROVIDER)
              Evidence.provenance_refs must be non-empty
```

### Plane 2 — Memory Admission

```text
Owner:        M1A
Question:     "Should this evidence become canonical memory?"
Contract:     MemoryCandidate + AdmissionGate → ADMIT/REJECT/DEFER
```

### Plane 3 — Retrieval / Surfacing

```text
Owner:        Memory Track / SurfacePolicy (future)
Question:     "Does existing canonical memory reach the Body generation context?"
Contract:     SurfaceDecision (ALLOW/SANITIZE/DENY)
Status:       ARCHITECTURE OWNER FROZEN — IMPLEMENTATION STATUS = FUTURE/PARTIAL
```

### Plane 4 — Working-Memory / Pending Overlay

```text
Owner:        C9-W1B
Question:     "Does non-canonical evidence appear in next-turn compiler context?"
Contract:     PendingWorkingEvidence — no canonical transfer
```

---

## Evidence / Memory Lifecycle: Two Distinct Planes

The following two paths are architecturally separate. They must **not** form a loop.

### WRITE / ADMISSION PLANE

```text
novel external/provider-derived claim
        ↓
Evidence
        ↓
D3 EvidenceAuthority (provenance, authority_level)
        ↓
MemoryCandidate
        ↓
M1A AdmissionGate
        ↓
CommittedMemory
```

### READ / RETRIEVAL PLANE

```text
CommittedMemory (existing)
        ↓
derived projection / Mem0 / other retrieval provider
        ↓
retrieval result
        ↓
mr_memory_id / provider_ref resolution
        ↓
resolve back to existing canonical memory
        ↓
scope + lifecycle eligibility
        ↓
SurfacePolicy
        ↓
Budget / Ranking
        ↓
Cognitive Context
```

### CRITICAL INVARIANT

```text
Retrieved
≠ Admitted

Retrieved
≠ Reinforced
```

**The READ plane does NOT loop back into the WRITE plane.** A retrieval result is not re-admitted by default.

---

## Mem0 Path C Compatibility

**Mem0 Path C remains valid under this ADR.**

Mem0 is a **disposable derived retrieval/index provider** — it does not become an authority domain.

```text
Mem0 retrieval result
        ↓
mr_memory_id / provider_ref resolution
        ↓
resolve back to existing CommittedMemory (MR-owned)
        ↓
scope + lifecycle eligibility
        ↓
SurfacePolicy
        ↓
cognition
```

Frozen statements:

```text
provider deletion         ≠  Soul forgetting
provider UUID             ≠  memory_id
provider search result    ≠  authority
similarity score         ≠  authority
```

This ADR does not change M0-R2 / Memory Track Path C direction.

---

## Novel vs. Retrieved: Two Separate Paths

The following two categories are completely distinct:

### Category A — Novel External/Provider-Derived Claim

```text
genuinely new external material with no existing canonical memory

        ↓
Evidence
        ↓
D3 EvidenceAuthority
        ↓
MemoryCandidate
        ↓
AdmissionGate
        ↓
CommittedMemory (optional — admission may reject/defer)
```

### Category B — Retrieval Result Derived from Existing Canonical Memory

```text
Mem0 / embedding search over existing CommittedMemory

        ↓
retrieval result
        ↓
mr_memory_id / provider_ref resolution
        ↓
canonical memory verification
        ↓
scope + lifecycle
        ↓
SurfacePolicy
        ↓
cognitive context
```

Mem0 belongs to Category B, not Category A.

---

## Default Semantics (Frozen per Existing Contracts)

| Condition | Default | Owner Contract |
|-----------|---------|---------------|
| `Evidence` missing `authority_level` or `provenance_refs` | `REJECT` or `DEFER` | D3 EvidenceAuthority |
| `MemoryCandidate` missing mandatory provenance | `REJECT` or `DEFER` | M1A AdmissionGate |
| `SurfacePolicy` not configured | `DENY` — do not surface | SurfacePolicy owner |
| `PendingWorkingOverlay` not configured | Empty pending items | C9-W1B |
| Retrieval candidate cannot resolve to authorized canonical memory | Do not surface | SurfacePolicy owner |
| Retrieval / external provider unavailable | Continue cognition without that material | Per ADR-0014 |

**Missing authority metadata → reject or defer per existing contracts. No generic AuthorityProvider abstraction exists.**

---

## LLM Boundary (Frozen)

```text
SemanticProvider (J8-SP1) proposes event kinds from raw text.
SemanticProvider does NOT decide authority.

Authority is structural (typed Evidence object), not positional (string prefix).
LLM may assist EvidenceAuthority classification as a proposal only.
LLM must NOT decide canonical authority.
LLM must NOT decide policy permission.
```

---

## Reinforcement Invariant (Correctly Frozen)

```text
Retrieved / Surfaced / Activated / Used alone
MUST NOT reinforce.

Legitimate memory weight/lifecycle change may arise from:

A. new authoritative Evidence through admission

OR

B. explicit deterministic MR lifecycle policy.
```

Specifically forbidden as sole reinforcement triggers:

```text
retrieval frequency alone
body echo alone
surface count alone
activation count alone
```

Reinforcement is NOT equivalent to re-admission.

---

## Failure Semantics (Frozen)

```text
Authority subsystem unavailable
→ external context UNAVAILABLE
→ cognition CONTINUES without external context
→ turn does NOT fail hard
```

Per ADR-0014: MR runtime must fail-soft on missing external sources.

---

## Prototype Disposition (Frozen by This ADR)

| Artifact | Disposition | Rationale |
|----------|-------------|-----------|
| `578672e` | RETIRED / historical prototype | Already reverted at `b402945` |
| `dfc8d30` `authority_boundary.py` | RECONCILE/REMOVE under follow-up cleanup ticket | Out of scope per this ADR; authority for removal comes from this ADR |
| `dfc8d30` `__init__.py` (SyntaxError) | RETIRED | Never valid |
| Workspace `memory/authority_boundary.py` | RESEARCH_ONLY / provenance evidence | Historical; not for commit |
| Workspace `memory/__init__.py` | RESEARCH_ONLY / provenance evidence | Historical; not for commit |
| C7C-R3 gate wiring tests | RETIRE_FROM_FORMAL_C7C_SURFACE | Mislabeled; move to spike if archived |
| `8eb8689` orchestrator wiring | RECONCILE/REMOVE under follow-up cleanup ticket | Authority for removal comes from this ADR's NO_SEPARATE_BOUNDARY decision, not from any ORCH-R1 patch |
| `gate_external_memory()` function (anywhere) | RETIRED | Not part of production contract |

> **Note on ORCH-R1:** The ORCH-R1 repair was rejected and reverted. It exists as counterfactual evidence only. The authoritative basis for cleanup is this ADR's decision that no separate external-memory authority seam exists in the target architecture.

---

## Pending Working Overlay Relationship

```text
PendingWorkingEvidence
≠ retrieval result
≠ external memory
≠ canonical memory
```

Pending evidence is bounded current-turn material. It does not pass through any external-memory authority gate because no such gate is part of the production contract.

Pending evidence remains subject to its existing evidence/source lifecycle contracts (D3). This ADR does not exempt it from authority — it simply does not route through a non-existent gate.

---

## SurfacePolicy Implementation Status

```text
ARCHITECTURE OWNER:    FROZEN (Memory Track / SurfacePolicy owner)
IMPLEMENTATION STATUS: PARTIAL / FUTURE
```

This ADR does not claim SurfacePolicy is currently fully implemented. It records that the architecture assigns this owner. The implementation completeness is a separate concern from the authority boundary decision.

---

## Naming Correction

The previous prototype used "C7C-R3" as the owner ticket. This was a mislabel. Per Architecture Lock v1.2 line E3:

```text
C7C-R3 = frozen projection replay / crash consistency
```

If a future ADR introduces a separate domain for external context authority, the ticket naming rule is:

```text
ECAB-N — External Context Authority Boundary N
```

This ADR does NOT currently authorize ECAB-1. ECAB-N is a future naming reservation only.

---

## Ownership Statement

```text
NEW_OWNER = NONE

PLANE_OWNERS:
  Evidence authority     = D3
  Memory admission       = M1A
  Retrieval / surfacing  = Memory Track / SurfacePolicy owner
  Pending overlay        = C9-W1B
```

"No fifth owner" means the four existing owners cover the required planes. It does not mean those planes are unowned.

---

## J8-SP1 Consequence (Two Dimensions)

### Semantic Dependency

```text
J8_SP1_SEMANTIC_DEPENDENCY = INDEPENDENT
```

The SemanticProvider abstraction (J8-SP1) does not depend on an external-context authority boundary. Semantic proposal is orthogonal to authority decision.

### Topology Unblock

```text
J8_SP1_TOPOLOGY_UNBLOCK = ENABLED_BY_THIS_CONTRACT_DECISION
                          BUT PENDING C9_WIRING_CLEANUP
```

This ADR provides the authoritative basis for a follow-up cleanup ticket to reconcile the dangling external-memory wiring in the c7a lineage. Until that cleanup is done, J8-SP1 topology remains blocked.

```text
Sequence:
  1. This ADR (or superseding) ratified
  2. C9-W1B-R2 cleanup ticket removes dangling wiring from c7a lineage
  3. clean c7a descendant created
  4. J8-SP1 replayed onto clean lineage
  5. fresh composition tests + independent review
  6. J8-SP1 CLOSED
```

---

## Schema Realism

This ADR does NOT introduce new domain contracts. It references existing contracts:

| Mentioned Schema | Status in This ADR |
|------------------|-------------------|
| `Evidence` / `AuthorityLevel` | Existing contract (D3) — referenced, not redefined |
| `MemoryCandidate` / `AdmissionGate` | Existing contract (M1A) — referenced, not redefined |
| `SurfaceDecision` | Future owner contract — referenced conceptually |
| `PendingDecision` | Existing contract (C9-W1B) — referenced, not redefined |
| `ExternalContextDecisionTrace` | **NOT introduced** — trace responsibility remains with each plane's owner |
| `ExternalContextAuthorityPort` | **NOT introduced** — no new port exists |
| `ExternalContextAuthorityPolicy` | **NOT introduced** — no new policy exists |

No invented schemas appear in this ADR as frozen contracts.

---

## Hard Rules

```text
H1: MR MUST NOT introduce a fifth authority plane.
H2: Evidence authority = D3 EvidenceAuthority.
    Memory admission = M1A AdmissionGate.
    Retrieval/surfacing = SurfacePolicy.
    Pending overlay = C9-W1B PendingWorkingOverlay.
H3: Pending evidence is NOT external-memory; it is bounded current-turn material.
H4: Missing authority metadata → reject/defer per existing contracts.
    Missing SurfacePolicy → do not surface.
    Missing retrieval/external source → continue without that material.
H5: LLM may propose semantic classification but MUST NOT decide authority.
H6: Trace ≠ Evidence ≠ Memory ≠ Authority. Each plane's owner maintains its own provenance.
H7: Retrieved / surfaced / activated / used alone MUST NOT reinforce.
H8: Future work on this seam MUST use ECAB-N naming and pass through ADR.
    It must NOT reuse C7C-R3.
```

---

## Alternatives Considered

### Option A — Separate External Context Authority Boundary

**Rejected** because:

- Would create a fifth authority layer on the same path already covered by four distinct planes
- No frozen spec, ADR, or architecture lock mandates it
- Three incompatible implementations exist with no single self-consistent lineage
- 9 of 18 "C7C-R3" tests fail structurally — the test suite is mislabeled
- Architecture Lock v1.2 classifies C7C-R3 as a different concern (projection replay / crash consistency)
- The prototype was reverted as "P0 alpha contamination"

### Option B (Chosen) — No Separate Seam

**Accepted** because:

- Four planes already have distinct architecture owners
- No frozen contract for a fifth seam exists
- Naming confusion (C7C-R3 mislabel) is resolved
- Future work, if needed, can use ECAB-N naming and pass through ADR

---

## Consequences

### Positive

- Architecture is cleaner: four owned planes, no fifth layer
- Naming confusion resolved
- Future work has a clear naming rule (ECAB-N) and frozen contract
- Mem0 Path C compatibility preserved

### Negative

- Prototype implementation is retired; future work must rebuild if needed
- "C7C-R3" tests are retired from the formal C7C surface
- Orchestrator dangling wiring must be reconciled (separate ticket)

### Neutral

- Architecture Lock v1.2 is unchanged
- Existing primitives (D3, M1A, C9-W1B) are unchanged
- J8-SP1 topology unblock is enabled but pending cleanup implementation

---

## Required Follow-up Actions

1. **C9-W1B-R2 cleanup ticket** (separate) — Reconcile dangling external-memory wiring from c7a lineage:
   - Remove `gate_external_memory()` call in `TurnOrchestrator.run()` at `d0d5f4f`
   - Remove `authorized_external_items` handling (field does not exist in `DecisionContextCompilerInput`)
   - Retain `_em_authority` and `_em_reference_store` as `None` injection slots (forward-compatibility if future ADR reopens this seam)
2. **J8-SP1 unblock** (separate ticket) — Enabled by this ADR; requires C9-W1B-R2 cleanup first.

---

## Acceptance Criteria

```text
A1  ADR-0013 in docs/adr/                                                [x] PASS
A2  Design spec in docs/superpowers/specs/                                [x] PASS
A3  Naming correction: future work uses ECAB-N, not C7C-R3                [x] PASS
A4  Hard rules H1-H8 frozen                                              [x] PASS
A5  Default semantics per existing contracts                             [x] PASS
A6  Prototype disposition: RECONCILE/REMOVE not "retire post-ORCH-R1"    [x] PASS
A7  Mem0 Path C preserved (Path B, not Path A)                          [x] PASS
A8  Reinforcement invariant: A or B only                                [x] PASS
A9  J8-SP1 consequence: two-dimensional                                 [x] PASS
A10 No new AuthorityProvider / ExternalContextAuthorityPort /           [x] PASS
       ExternalContextDecisionTrace
```

ADR-0013 ratified 2026-09-02. All 10 acceptance criteria PASS.

---

## Reversibility

If a future ADR proves a missing authority domain, this ADR may be superseded. The four existing plane owners remain authoritative.

---

*ADR-0013 — Accepted, ratified 2026-09-02 (C7C-R3-R2.1 + ADR-0013-RAT)*