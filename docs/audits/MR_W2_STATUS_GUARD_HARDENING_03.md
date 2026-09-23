# MR-W2 Architecture Guard Audit: Fail-Closed Provenance Invalidation on Every Assignment

- **Audit ID**: `AGY-MR-W2-STATUS-GUARD-HARDENING-03`
- **Worktree**: `C:\projects\mind-runtime-main-merge\.worktrees\mr-late-projection-w2-runtime-consumption-01`
- **Repository**: `C:\projects\mind-runtime-main-merge`
- **Base Commit**: `f0c4df1f7b5808bfd5218d1fca990d5e216f96aa`
- **Pre-Fix Tracked Diff SHA256**: `6f7624adf99ca3a4e1bf52813e30d72b3cb558c51acce2f3befdc67e797c00e3`
- **Pre-Fix Full Tree Manifest SHA256**: `9c335692593adc41ee1200f8daf93637a3e98185d910b0a3c1709eab02eff45b`
- **Post-Fix Tracked Diff SHA256**: `cfc2ba906f1dd588634fa59f6dd804971c4f4fdef6cec5292f2502139a2e0565`
- **Status**: Complete / Passed
- **Verdict**: `READY_FOR_FINAL_RECERTIFICATION`

---

## 1. Problem Statement & Stale-Provenance Vulnerability

In `AGY-MR-W2-STATUS-GUARD-HARDENING-02`, `TypeProvenanceVisitor` introduced AST-based receiver type provenance to replace enum-name matching. However, the visitor's assignment handler had a stale-provenance loophole:
```python
inferred_type = self._resolve_expr_type(node.value)
if inferred_type:
    for target in node.targets:
        if isinstance(target, ast.Name):
            self.current_scope[target.id] = inferred_type
```
If `_resolve_expr_type(node.value)` returned `None` (such as for `IfExp`, `Subscript`, `Attribute`, or unproven `Call`), `self.current_scope[target.id]` was left untouched. Consequently:
1. An approved variable (e.g. `projection: AppraisalProjectionResult`) reassigned from an unresolved or unproven expression (e.g. `projection = state if flag else projection`, `projection = states[0]`, `projection = holder.state`, `projection = unknown_call()`) retained its old `APPROVED` type.
2. Subsequent raw `projection.status` checks bypassed the guard.

---

## 2. Solution: 3-State Provenance Lattice & Fail-Closed Assignment Invalidation

### 2.1 3-State Provenance Lattice
We model variable provenance using an explicit 3-state lattice:
- `APPROVED(type_name: str)`: Proven to be an approved typed protocol object (`AppraisalProjectionResult`, `PendingWorkingEvidence`, `ApplicationReceipt`, etc.).
- `FORBIDDEN(type_name: str)`: Proven to be a forbidden raw state object (`RuntimeState`).
- `UNKNOWN`: Unproven expression, unknown function call, subscript, attribute, or join of incompatible types.

`.status` access is legal **if and only if** receiver provenance is `APPROVED`. Both `FORBIDDEN` and `UNKNOWN` are reported as offenders (fail-closed).

### 2.2 Unconditional Invalidation on Every Assignment
Every assignment construct unconditionally overwrites the target variable's provenance in the active scope:
1. `visit_Assign`:
   - `rhs_prov = self._resolve_expr_provenance(node.value)`
   - Every target is assigned `rhs_prov` (or unpacked into `UNKNOWN`).
2. `visit_AnnAssign`:
   - Type annotations cannot act as casts to bypass provenance verification.
   - If `node.value` is present, the target is approved only if `rhs_prov` is approved and compatible with the annotation; otherwise transitions to `UNKNOWN` (or `FORBIDDEN` if RHS is forbidden).
3. `visit_AugAssign`: Target transitions to `UNKNOWN`.
4. `visit_For` / `visit_AsyncFor`: Target loop variable transitions to `UNKNOWN`.
5. `visit_NamedExpr` (walrus `:=`): Target is assigned `_resolve_expr_provenance(node.value)`.

### 2.3 Expression Resolution Rules
- `ast.Name`: Scoped reverse lookup across scope stack. If not found, returns `UNKNOWN`.
- `ast.Call`:
  - Direct constructor or approved factory method (`get_projection` -> `APPROVED:AppraisalProjectionResult`, `get_by_pending_id` -> `APPROVED:PendingWorkingEvidence`).
  - All other calls return `UNKNOWN`.
- `ast.IfExp` (`body if test else orelse`):
  - Returns `body_prov` iff `body_prov.is_approved` and `body_prov == orelse_prov`.
  - All other conditional expressions return `UNKNOWN`.
- Subscripts, unproven attributes, literals, binary operations: return `UNKNOWN`.

---

## 3. Test Suite Verification & Controls

### 3.1 Positive Controls (6 Passing)
1. Parameter annotation provenance (`def x(projection: AppraisalProjectionResult): ...`).
2. Constructor assignment provenance (`projection = AppraisalProjectionResult(...)`).
3. Simple alias provenance (`result2 = projection`).
4. `PendingWorkingEvidence` typed receiver (`def x(pending: PendingWorkingEvidence): ...`).
5. Conditional expression with both branches approved (`projection = p1 if flag else p2`).
6. Reassignment from approved to another approved (`projection = p1; projection = p2`).

### 3.2 Negative Controls (18 Passing)
1. `state: RuntimeState` with raw string (`state.status == "committed"`).
2. `state: RuntimeState` with `StateLifecycle.ACTIVE`.
3. `state: RuntimeState` with `HostTurnStatus.COMMITTED` (Reviewer counterexample).
4. `state: RuntimeState` with `ProjectionStatus.MAPPED`.
5. `state: RuntimeState` with `.status.value`.
6. `state: RuntimeState` truthiness (`if state.status:`).
7. `state: RuntimeState` helper call (`is_terminal(state.status)`).
8. Constructor provenance negative control (`state = RuntimeState(...)`).
9. Alias negative control (`state2 = state`).
10. Unknown receiver negative control (`def x(something_unknown): ...`).
11. **Reviewer counterexample**: conditional reassignment (`projection = state if flag else projection`).
12. Reassignment from subscript/index (`projection = states[0]`).
13. Reassignment from attribute (`projection = holder.state`).
14. Reassignment from unknown function call (`projection = unknown_call()`).
15. Direct reassignment from state (`projection = state`).
16. `AnnAssign` cast attempt with state (`projection: AppraisalProjectionResult = state`).
17. `AnnAssign` cast attempt with unknown call (`projection: AppraisalProjectionResult = unknown_call()`).
18. For-loop variable overwrite (`for projection in items:`).

### 3.3 Production Scan
- Scanned all files in `src/mind_runtime/pipeline/*.py`.
- **0 offenders found**. All legal typed protocol status accesses (`projection.status` at line 1222, `pending.status` at lines 1662, 1664, 1722, 1724) are verified with approved receiver provenance.

---

## 4. Worktree Integrity & Production Invariance

- **Modified tracked files**: ONLY `tests/state/test_ports.py`.
- **Production changes**: **0 bytes**. No changes to `orchestrator.py`, `persistence.py`, `xiyue_adapter.py`, or any other production file.
- **Verification commands**:
  - `python -m pytest tests/state/test_ports.py -q -v` -> 11/11 passed in 0.31s.
  - `python -m pytest tests/host/test_xiyue_adapter.py tests/late_projection/test_w2_runtime_consumption.py -q -v` -> 44/44 passed in 5.42s.

---

## 5. Final Verdict

`READY_FOR_FINAL_RECERTIFICATION`
