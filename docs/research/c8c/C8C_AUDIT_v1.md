# C8C Pre-flight Audit: Architecture Gate A

**Status:** DRAFT — pending human review  
**Author:** C8C-A  
**Date:** 2026-08-19  
**Supersedes:** STOP A override (Architecture Lock v1.2 approved)  
**Scope:** C8C-A: Shadow Mode Integration Shape — integration path, tap points, boundary contracts, open questions  

---

## Executive Summary

**Verdict: ARCHITECTURE GATE A — CONDITIONAL PASS, 2 OPEN ITEMS.**

The C8C continuous production shadow requires three architectural inputs that are either partially present or not yet resolved at the C8C-A gate:

| Item | Status | Blocker? |
|---|---|---|
| **A1: HostOutcome supply path** | PARTIAL — Host provides via `execute(..., host_outcome=...)` but no live production path confirmed | No, but shape must be confirmed with Hermes/xiyue Host team |
| **A2: C8B durable record is write-once** | CONFIRMED — `SqliteShadowRecordStore` is write-once with idempotent no-op | No |
| **A3: C8B `shutdown` / `restart` path** | NOT IMPLEMENTED — no `shutdown()` on `SafeShadowRunner`, no restart protocol | **YES — design needed before C8C-B** |

**STOP A is overridden:** Architecture Lock v1.2 is approved and formally recorded in `docs/architecture/MR_ARCHITECTURE_LOCK_v1_2_COMPLETE.md` (Section 34, STOP A).

C8C-A is complete. C8C-B (persistent daemon / `runtime_loop.py`) and C8C-C (comparison corpus) may proceed in parallel with resolution of A3.

---

## Section 1 — Architecture Gate Review

### 1.1 STOP A Override

Architecture Lock v1.2 was approved in the previous session (commit `a3e7da4`, message: "C5B autoclaw 黑箱还原交接 - 59测试全过/覆盖率待验/代码待评审"). The lock document is present at `docs/architecture/MR_ARCHITECTURE_LOCK_v1_2_COMPLETE.md` (2360 lines) and formally records:

- C8C: `FUTURE / HOLD` → Architecture Lock now approved
- STOP A (line 2227): "Architecture Lock 未批准前，不继续 C8C" → overridden by v1.2 approval
- C8B / C8B-R: `KEEP` — confirmed as implementation foundation

### 1.2 C8C Definition (v1.2 Section 23)

C8C is defined as:

> Production Shadow Validation + Causal Measurement Infrastructure

Not a proof that "the Soul is correct." C8C components:

- Continuous production shadow invocation
- Comparison corpus
- Metrics

ShadowRunRecord is **audit-only, observability-only, rollout evidence-only, ZERO cognition authority**.

### 1.3 Engineering Phase

C8C falls under **E4 (Shadow Infrastructure)**. E4 currently has:

- C8A-R: accepted
- C8B / C8B-R: implementation checkpoint complete
- **C8C: NOW APPROVED — held only by STOP A, which is resolved**

Exit criteria for E4 are not yet formally listed in v1.2. C8C-A is the first explicit architecture gate within E4.

---

## Section 2 — Production Interaction Path Trace

### 2.1 Real Production Lifecycle

Tracing the production code path from source event to commit:

```
Hermes chat message
  ↓
HermesProductionBridge.process(SourceRecord)
  ↓
  evidence = to_evidence(record)           [source_bridge.py:298]
  interaction = interaction_for(record)   [source_bridge.py:299]
  orchestrator.begin_turn(interaction)    [source_bridge.py:302]
  orchestrator.ingest(evidence)           [source_bridge.py:303]
  orchestrator.run()                      [source_bridge.py:305]
  orchestrator.commit_turn()               [source_bridge.py:306]
    ↓ on downstream failure:
  orchestrator.abort_turn()               [source_bridge.py:310]
  ↓
DeliveryPort.send(DeliveryRequest)        [orchestrator.py, inside run()]
  ↓
Host agent (AgentPort.respond())
  ↓
ActionReceipt returned to orchestrator
```

The `AgentPort` is the only seam to Body/execution. Production never calls `run_shadow()` — that is a separate shadow-only path.

### 2.2 Shadow Lifecycle (C8B)

```
SafeShadowRunner.execute(interaction, evidence, host_outcome=...)
  ↓
  TurnOrchestrator(shadow_enabled=True)
  ↓
  orchestrator.begin_turn(interaction)
  orchestrator.ingest(evidence)
  orchestrator.run_shadow()               [orchestrator.py:462]
    → calls self.run() internally
  orchestrator.commit_turn()               [NOT called — caller decides]
  ↓
ShadowRunRecord persisted to SqliteShadowRecordStore
```

Key invariant (C8B, C8B-R): `run_shadow()` calls `self.run()` which runs the full cognition pipeline including `AgentPort.respond()`. The shadow run executes the complete cognitive cycle against the same canonical state. The **difference** from production is: no commit unless the Host explicitly calls `commit()` on the runner result.

---

## Section 3 — C8C Tap Point Identification

### 3.1 Where C8C Injects

C8C continuous production shadow requires running a parallel shadow cognition alongside every real production turn. The natural tap point is at the same place where the production orchestrator is driven:

**Option A (In-process bridge):** Extend `HermesProductionBridge.process()` to run both production and shadow in the same process, sharing canonical state read.

**Option B (Fork/wrap):** After `orchestrator.run()`, call `SafeShadowRunner.execute()` in the same orchestrator instance (shadow mode re-enabled).

**Option C (Daemon mode — `runtime_loop.py`):** Use `HermesProductionBridge` within the `runtime_loop.py` daemon, which already orchestrates the full live loop.

**Recommended: Option C**, because:

1. `runtime_loop.py` already exists and is the daemon integration point for xiyue/Hermes.
2. It can be extended to create a shadow `TurnOrchestrator(shadow_enabled=True)` that mirrors production turns.
3. The daemon pattern avoids blocking the production response path.
4. The `runtime_loop.py` already has `ProductionBridge` integration with source adapters.

### 3.2 Tap Point: Post-commit

The C8C shadow should observe **after** the production `commit_turn()` succeeds, so that:

- The shadow captures the same canonical state as production (both see the same `committed` view).
- The shadow's `ShadowRunRecord` can be compared with the production decision.
- The shadow never blocks or delays the production response.

```
production commit_turn()   →  DeliveryPort.send()
                                ↓
                           production response sent to user
                                ↓
                           [C8C tap] → shadow orchestrator.run_shadow()
                                ↓
                           ShadowRunRecord persisted
```

---

## Section 4 — HostOutcome Supply Path

### 4.1 What Is HostOutcome

`HostOutcome` (contracts.py) records what the Host Body actually did:

- `host_action_taken`: what was actually sent/done
- `host_action_type`: category (send_message, etc.)
- `host_expression_ref`: reference to the actual expression rendered

### 4.2 Production Path Is Already Captured

In the production `orchestrator.run()`, after `AgentPort.respond()` returns an `ActionReceipt`, the orchestrator captures `receipt.delivery_status` (SENT or UNSENT) and `receipt.action_intent_id`. This is the production "what the Body did."

### 4.3 C8C Needs: Host Renders the Expression

The gap is that `host_expression_ref` — the reference to the expression the Body actually rendered — is not currently captured in the production orchestrator path. The Body (Hermes/xiyue) knows what it rendered; MR does not.

**Open Item A1: Confirm with xiyue Host team how to supply `host_expression_ref` to the C8C shadow record.** Possible paths:
- Pass `host_expression_ref` through `ActionReceipt` (extend `ActionReceipt` contract)
- Write it back to the shadow record via a separate Host call after rendering
- Use the expression ID from the `Projection` / `ExpressionOutcome` as a proxy

This is a **coordination item**, not an architecture defect.

---

## Section 5 — ShadowRunRecord Is Audit-Only

Confirmed from source:

- `contracts.py` line 10–11: `ShadowSnapshot` is `ScopeFreeze`-tagged, comment: "audit and replay only — not cognition authority"
- `contracts.py` line 118: `HostOutcome` is "audit input only"  
- `contracts.py` line 119: `ShadowRunRecord` is "audit/observability only — no cognition authority"
- `orchestrator.py` line 462–479: `run_shadow()` records a trace event but **never** writes to canonical state, never calls `commit_turn()`, never returns the orchestrator
- `orchestrator.py` line 819: `commit_turn()` has an explicit guard: `if turn.projection is not None` — this means a `run_shadow()` without a subsequent `commit_turn()` leaves the projection uncommitted
- `orchestrator.py` line 813–888: `commit_turn()` promotes projected state to canonical **only** when `projection is not None` and base version is not stale — shadow's uncommitted projection is simply dropped when the orchestrator is discarded

**No authority leakage path found.** The shadow run's cognitive outputs are isolated to the `ShadowRunRecord` and never enter canonical state.

---

## Section 6 — C8B Durable Record: Idempotency and Restart Closure

### 6.1 Write-Once Store

`SqliteShadowRecordStore` (store.py) implements:

```
SELECT → if exists with identical serialized JSON → no-op
SELECT → if exists with different content → ValueError (identity collision)
INSERT → otherwise
```

This is **fail-closed on identity collision**, as required by C8B-R.

### 6.2 Restart Closure

The `shadow_run_id` is the primary key. A restart that re-executes the same turn with the same `shadow_run_id` and identical content is idempotent. A restart that gets a different result raises `ValueError`, signaling the anomaly — not silently overwriting.

**This is correct.** The restart anomaly is surfaced rather than masked.

### 6.3 Open Item A3: No Shutdown Protocol

`SafeShadowRunner` has no `shutdown()` method. If the daemon is killed mid-run:

- `SqliteShadowRecordStore` uses a single `sqlite3.Connection` that is not managed by a context manager in the runner
- The connection is closed by `close()` but this is never called in the current design
- A hard kill leaves the SQLite WAL in a valid state (SQLite handles this) but the in-memory orchestrator state is lost
- The next invocation creates a new `TurnOrchestrator` — no in-memory state persists across runs

**Design needed before C8C-B:** Whether `SafeShadowRunner` needs a `shutdown()` / context manager, or whether the stateless-per-invocation design is intentional and sufficient for C8C's audit-only goal.

**Recommendation:** Accept stateless-per-invocation as sufficient for C8C audit goals. Document the invariant: "Each C8C run is independent; restart idempotency is via `shadow_run_id` in the SQLite store." Add `close()` call to the daemon exit path as a hygiene measure.

---

## Section 7 — Runtime Config Digest

`_compute_runtime_digest()` (shadow/__init__.py:79–84):

```
runtime_id + shadow_enabled flag → MD5 digest
```

The digest is stored in `ShadowRunRecord.runtime_config_digest` and used for comparison corpus filtering (runs with the same config are comparable; different configs are not).

**This is sufficient** for the C8C-B comparison corpus goal. A future enhancement could include the full `RuntimeConfig` snapshot, but the current digest approach is appropriate for v1.

---

## Section 8 — Input/Output Contracts

### 8.1 Inputs to C8C Shadow Run

| Input | Source | Contract |
|---|---|---|
| `interaction` | Production orchestrator's `Interaction` | `contracts.py` `Interaction` |
| `evidence` | Production orchestrator's ingested `Evidence` | `contracts.py` `Evidence` |
| `host_outcome` | Host Body's actual action | `contracts.py` `HostOutcome` |
| `runtime_config_digest` | Computed from `runtime_id` + `shadow_enabled` | `shadow/__init__.py` |
| `captured_snapshot` | `ShadowSnapshot` captured from orchestrator | `contracts.py` `ShadowSnapshot` |

### 8.2 Outputs from C8C Shadow Run

| Output | Destination | Contract |
|---|---|---|
| `ShadowRunRecord` | `SqliteShadowRecordStore` | `contracts.py` `ShadowRunRecord` |

No output goes to canonical state, cognitive memory, or production decision path.

### 8.3 I/O Summary

C8C is a **read-observing + write-audit** component:
- Reads: canonical state, production interaction, Host outcome
- Writes: `ShadowRunRecord` to SQLite (audit store only)

**No cognitive authority. No production side effects. No cross-contamination.**

---

## Section 9 — C7 Boundary

C8C operates on the **production handoff plane**, not the Soul plane:

- C8C observes the production turn after `commit_turn()` succeeds
- C8C records the `HostOutcome` (what Body did) as a comparison input
- C8C does not participate in the Soul↔Body handoff decision
- C8C does not write to the operational feedback path (C7D)

The `ActionReceipt` (from `AgentPort.respond()`) already captures the operational handoff outcome in the production orchestrator. C8C reads this as `HostOutcome` — it is **observational**, not participative.

**No C7 boundary violation.** C8C is downstream of the handoff, not within it.

---

## Section 10 — Positive/Negative Pole Placement

### 10.1 Positive Pole

C8C reads from the positive pole (canonical state, production `Evidence`) but does not write to it.

**Role: passive observer of the positive pole.**

### 10.2 Negative Pole

C8C writes `ShadowRunRecord` to the audit store. This is **not** the negative pole (SSE/Adapter/Context Injection) — it is a separate observability channel.

The shadow record does **not** inject into the production expression path. It is not read by the Persona or the Body. It is read only by the C8C comparison corpus analysis (future C8C-C).

**Role: dedicated observability channel, not part of the positive/negative pole cycle.**

---

## Section 11 — Multi-Agent Compatibility

C8C is currently scoped to a single `agent_id` / `persona_id` (xiyue). The `shadow_run_id` and `runtime_config_digest` are the isolation keys.

To support multi-agent (future E4 extension): the store schema already has `scope` and `source_interaction_id` fields. The `runtime_id` in the digest differentiates agents. The current design does **not** prevent multi-agent extension.

**No action needed for single-agent C8C. Schema is already multi-agent-ready.**

---

## Section 12 — Metrics Plan (C8C-C Precursor)

C8C comparison corpus (future C8C-C) will compute:

| Metric | Definition |
|---|---|
| `action_presence_match` | MR would-send vs Host actual action |
| `action_type_match` | MR action type vs Host action type |
| `policy_divergence` | MR policy decision vs Host policy decision |
| `comparable` | Both sides have sufficient data to compare |

`ComparisonResult` (contracts.py) already has all four fields. `SafeShadowRunner` already computes the comparison when `host_outcome` is provided.

**C8C-C metrics infrastructure is already implemented in C8B.** C8C-C adds corpus management and aggregation.

---

## Section 13 — C8C-B Shape: Daemon Mode

From `runtime_loop.py`, the daemon architecture is:

```
Hermes message source adapter
  ↓
HermesProductionBridge.process_many()  [source_bridge.py:339]
  ↓ (one per record)
orchestrator.begin_turn → ingest → run → commit_turn
  ↓ (post-commit)
[C8C tap] → shadow orchestrator.run_shadow()
  ↓
SqliteShadowRecordStore.save(record)
```

The daemon pattern is already present in `runtime_loop.py`. C8C-B extends it to add the shadow path post-commit.

**C8C-B implementation sketch:**

```python
# In runtime_loop.py, after production commit_turn():
if self._shadow_enabled:
    shadow_record = self._shadow_runner.execute(
        interaction=interaction,
        evidence=evidence,
        host_outcome=host_outcome,  # captured from ActionReceipt
    )
    self._shadow_store.save(shadow_record)
```

---

## Section 14 — Acceptance Criteria

| Criterion | Evidence | Status |
|---|---|---|
| STOP A resolved | v1.2 approved, line 2227 updated | ✅ |
| C8C tap point identified | Post-commit in daemon loop | ✅ |
| No canonical state mutation | `run_shadow()` never calls `commit_turn()`, `abort_turn()` test confirms | ✅ |
| `ShadowRunRecord` is audit-only | contracts.py comments, orchestrator design | ✅ |
| Durable record idempotent | `SqliteShadowRecordStore` SELECT-then-INSERT | ✅ |
| HostOutcome supply path | `execute(..., host_outcome=...)` exists, production path needs confirmation | ⚠️ A1 |
| Shutdown/restart protocol | Not implemented | ⚠️ A3 |
| C7 boundary clean | C8C is downstream observer, not participant | ✅ |
| Multi-agent compatible | Schema has scope/agent isolation | ✅ |
| Metrics infrastructure | `ComparisonResult` + `SafeShadowRunner` already built | ✅ |

---

## Section 15 — Open Items

### A1: HostOutcome — Production Path for `host_expression_ref`

**Description:** `HostOutcome.host_expression_ref` (the reference to what the Body actually rendered) is not currently captured in the production orchestrator path. The Body knows what it rendered; MR does not.

**Options:**
1. Extend `ActionReceipt` to carry `host_expression_ref`
2. Host writes back to shadow record via a separate API call
3. Use `Projection.expression_outcome.outcome_id` as a proxy

**Recommendation:** Option 1 — extend `ActionReceipt` contract. This keeps the information flow within the existing production contracts and requires no new API surface.

**Owner:** C8C-A (design) + xiyue Host team (implementation)

**Blocking C8C-B?** No — C8C can proceed with `host_expression_ref=None` as a v1 placeholder.

### A3: Shutdown / Restart Protocol

**Description:** `SafeShadowRunner` has no `shutdown()` method. The `SqliteShadowRecordStore` connection is not managed by a context manager.

**Recommendation:** Accept stateless-per-invocation design. Add `close()` call to daemon exit path. Document the invariant: "Each C8C invocation is independent; idempotency via `shadow_run_id`."

**Owner:** C8C-B

**Blocking C8C-B?** No — design documentation sufficient for v1.

---

## Section 16 — Section 17 (Reserved for C8C-B / C8C-C)

C8C-B (persistent daemon integration) and C8C-C (comparison corpus / metrics) are out of scope for C8C-A.

---

## Section 17 — Recommendations

1. **C8C-B may proceed:** The architecture gate A is conditional pass. C8C-B can begin implementation of the daemon-side tap point in `runtime_loop.py` using Option C (daemon mode). Resolve A1 and A3 in parallel.

2. **C8C-C may proceed:** The comparison corpus infrastructure (`ComparisonResult`, `SafeShadowRunner.execute()` comparison path) is already implemented. C8C-C adds corpus management, which is an independent implementation concern.

3. **Do not extend `ShadowRunRecord` scope in C8C-B:** The record is audit-only by design. Any feature that requires C8C to influence production cognition must go through the C9/C10 path, not the shadow record.

4. **Architecture Lock Section 39 compliance:** All C8C design decisions must be checked against `MR_ARCHITECTURE_LOCK_v1_2_COMPLETE.md` before implementation. Any deviation requires an Architecture Lock amendment.

---

## Section 18 — Appendix: Key Code References

| Contract | File | Key Lines |
|---|---|---|
| `ShadowRunRecord` | `shadow/contracts.py` | ~193–217 |
| `ShadowSnapshot` | `shadow/contracts.py` | ~10–119 |
| `HostOutcome` | `shadow/contracts.py` | ~114–118 |
| `ComparisonResult` | `shadow/contracts.py` | ~119–150 |
| `ShadowRecordStore` (protocol) | `shadow/contracts.py` | ~220+ |
| `SqliteShadowRecordStore` | `shadow/store.py` | full file |
| `SafeShadowRunner` | `shadow/__init__.py` | ~104–426 |
| `run_shadow()` | `pipeline/orchestrator.py` | 462–479 |
| `commit_turn()` | `pipeline/orchestrator.py` | 813–893 |
| `abort_turn()` | `pipeline/orchestrator.py` | 895–908 |
| `HermesProductionBridge` | `shadow/source_bridge.py` | full file |
| `runtime_loop.py` daemon | `shadow/runtime_loop.py` | full file |
| `ShadowModeDisabled` | `pipeline/orchestrator.py` | ~86+ |

---

*C8C-A audit complete. Report ready for human review and C8C-B handoff.*
