# MR-W2-STATUS-GUARD-HARDENING-02 Audit Report

## 1. Checkpoint Hashes & Scope

- **Repository**: `C:\projects\mind-runtime-main-merge`
- **Worktree**: `C:\projects\mind-runtime-main-merge\.worktrees\mr-late-projection-w2-runtime-consumption-01`
- **Base HEAD**: `f0c4df1f7b5808bfd5218d1fca990d5e216f96aa`
- **Pre-Fix Tracked Diff SHA-256**: `fdc4a3d613e00c87a08e9c9212e3800b8a3daa357dcee87b396bc9766ac66150` (verified byte-exact)
- **Pre-Fix Combined Tree Manifest SHA-256**: `f2e2afd7560952e6262ed8e740d1e94187fc03fe7b29528db49859c9775b0d24` (verified byte-exact)
- **Post-Fix Tracked Diff SHA-256**: `6f7624adf99ca3a4e1bf52813e30d72b3cb558c51acce2f3befdc67e797c00e3`
- **Production Diff**: **NONE** (Zero production changes; only `tests/state/test_ports.py` was modified).

---

## 2. Failure Mechanism in Prior Version

In `MR-W2-CERTIFICATION-FIX-01`, `RawStateStatusAuditor` evaluated `.status` accesses by inspecting whether the expression was compared against any enum name listed in `APPROVED_TYPED_STATUS_ENUMS`.

Because it checked only the RHS enum name rather than the receiver's type, an expression such as:
```python
state.status == HostTurnStatus.COMMITTED
```
where `state` is a `RuntimeState`, was erroneously allowed because `HostTurnStatus` was in the approved enum set. In Python semantics, `RuntimeState(status="committed").status == HostTurnStatus.COMMITTED` evaluates to `True`. Similarly, `.status.value` was allowed without checking the receiver type.

---

## 3. New Receiver-Proven Mechanism

The guard was completely rewritten to enforce the true architectural invariant:
> `.status` access is legal **ONLY IF** the receiver itself is proven to be an approved typed protocol object.

The new `TypeProvenanceVisitor`:
1. Maintains a lexical scope stack for symbol type resolution.
2. Tracks parameter type annotations in function and method signatures.
3. Tracks local variable type annotations (`AnnAssign`).
4. Tracks constructor assignments (`Assign` with `Call` to known classes).
5. Tracks method call provenance (e.g. `get_projection(...)` -> `AppraisalProjectionResult`, `get_by_pending_id(...)` -> `PendingWorkingEvidence`).
6. Tracks simple aliases (`Assign` from one variable to another), preserving approved or forbidden type provenance across renames.
7. Evaluates `node.attr == "status"` strictly against the receiver's inferred type:
   - If the receiver type is in `APPROVED_STATUS_RECEIVER_TYPES`: **ALLOWED**.
   - Otherwise (forbidden or unknown): **REPORTED AS OFFENDER**.

---

## 4. Approved & Forbidden Receiver Types

### Approved Receiver Types (`APPROVED_STATUS_RECEIVER_TYPES`)
- `AppraisalProjectionResult` (ADR-0027 late projection result)
- `PendingWorkingEvidence` (M1A/C9-W1B pre-admission pending overlay)
- `ApplicationReceipt` (ADR-0027 durable application receipt)
- `AcceptedAppraisal` (ADR-0027 accepted appraisal record)
- `Interaction` (interaction lifecycle contract)
- `HostDecisionContext` (host boundary context)
- `HostTurnResult` (host turn execution result)
- `HostCommitReceipt` (host commit receipt)
- `HostAbortReceipt` (host abort receipt)
- `ActionPolicyResult` (action policy result)
- `ShadowRecord` (shadow execution record)
- `ShadowRunRecord` (shadow run record)

### Forbidden Receiver Types (`FORBIDDEN_STATUS_RECEIVER_TYPES`)
- `RuntimeState` (permanent ban on raw state status reads in pipeline)

### Unknown Receiver Policy
- **Fails Closed**: Any receiver whose type cannot be proven to be in `APPROVED_STATUS_RECEIVER_TYPES` is reported as an offender. Unknown receivers are never automatically allowed.

---

## 5. Control Tests & Counterexample Verification

### Negative Controls (`test_t_a2_negative_runtime_state_status_filtering_triggers_guard`)
1. `def x(state: RuntimeState): if state.status == "committed": pass` -> **OFFENDER**
2. `def x(state: RuntimeState): if state.status == StateLifecycle.ACTIVE: pass` -> **OFFENDER**
3. `def x(state: RuntimeState): if state.status == HostTurnStatus.COMMITTED: pass` -> **OFFENDER** (Reviewer counterexample)
4. `def x(state: RuntimeState): if state.status is ProjectionStatus.MAPPED: pass` -> **OFFENDER**
5. `def x(state: RuntimeState): if state.status.value == "committed": pass` -> **OFFENDER**
6. `def x(state: RuntimeState): if state.status: pass` -> **OFFENDER**
7. `def x(state: RuntimeState): is_terminal(state.status)` -> **OFFENDER**
8. `state = RuntimeState(...); if state.status == HostTurnStatus.COMMITTED: pass` -> **OFFENDER** (Constructor provenance)
9. `state2 = state; if state2.status == HostTurnStatus.COMMITTED: pass` -> **OFFENDER** (Alias provenance)
10. `def x(something_unknown): if something_unknown.status == "anything": pass` -> **OFFENDER** (Unknown receiver fails closed)

### Positive Controls (`test_t_a1_positive_legal_projection_status_does_not_trigger_guard`)
1. Parameter annotation: `def x(projection: AppraisalProjectionResult): if projection.status is not ProjectionStatus.MAPPED: pass` -> **LEGAL (0 offenders)**
2. Constructor assignment: `projection = AppraisalProjectionResult(...); if projection.status is ProjectionStatus.MAPPED: pass` -> **LEGAL (0 offenders)**
3. Alias provenance: `result2 = projection; if result2.status is ProjectionStatus.MAPPED: pass` -> **LEGAL (0 offenders)**
4. Typed pending receiver: `def x(pending: PendingWorkingEvidence): if pending.status is not PendingStatus.PENDING: pass; msg = f"{pending.status.value}"` -> **LEGAL (0 offenders)**

### Reviewer Counterexample Probe Result
- Probe: `RuntimeState.status == HostTurnStatus.COMMITTED`
- Result: **OFFENDER** (`['<string>:3']`)
- Probe: `AppraisalProjectionResult.status is ProjectionStatus.MAPPED`
- Result: **NO OFFENDER** (`[]`)

---

## 6. Test Suite Execution

- `python -m pytest tests/state/test_ports.py -q`: **11 passed in 0.25s**
- `python -m pytest tests/host/test_xiyue_adapter.py -q`: **11 passed in 0.23s**
- `python -m pytest tests/late_projection/test_w2_runtime_consumption.py -q`: **33 passed in 4.99s**
- Total targeted tests: **100% GREEN**

---

## 7. Final Verdict

**READY_FOR_FINAL_RECERTIFICATION**
