# MR-W2-CERTIFICATION-FIX-01 Audit Report

## 1. Initial Dirty Checkpoint

- **Worktree**: `C:\projects\mind-runtime-main-merge\.worktrees\mr-late-projection-w2-runtime-consumption-01`
- **Branch**: `w/mr-late-projection-w2-runtime-consumption-01`
- **Base HEAD**: `f0c4df1f7b5808bfd5218d1fca990d5e216f96aa`
- **Initial State**: Source review `MR-W2-FINAL-SOURCE-REVIEW-01` identified one blocking finding: `getattr(projection, "status")` was used in `src/mind_runtime/pipeline/orchestrator.py:1222` as a syntax evasion to avoid triggering the overly broad `.status` AST scan in `tests/state/test_ports.py::test_no_raw_status_filtering_in_pipeline_package`. Additionally, `xiyue_adapter.py` used duck-typing `getattr(bounded, "cognitive_meaning", None)` instead of directly accessing the typed `bounded.cognitive_meaning` field.

---

## 2. Changed Files

### Production Code
1. `src/mind_runtime/pipeline/orchestrator.py`:
   - Line 1222: Restored explicit typed access `if projection.status is not ProjectionStatus.MAPPED:` (removed `getattr(projection, "status")`).
2. `src/mind_runtime/host/xiyue_adapter.py`:
   - Line 116: Restored explicit typed access `if bounded.cognitive_meaning:` (removed `getattr(bounded, "cognitive_meaning", None)`).
3. `src/mind_runtime/state/persistence.py`:
   - Clarified in `stage_application_receipt` and `commit_application_receipt` docstrings that the receipt storage API is a persistence primitive, NOT an independent appraisal authority boundary. Lineage validation is exclusively owned by the canonical mutation seam in `TurnOrchestrator._prepare_appraisal_receipts`.

### Tests
1. `tests/state/test_ports.py`:
   - Replaced naive string-matching check in `test_no_raw_status_filtering_in_pipeline_package` with `RawStateStatusAuditor` AST visitor that accurately enforces the D4.7 invariant: pipeline code must not read raw `RuntimeState.status` to determine canonical/effective state, while explicitly permitting legal typed protocol statuses (`ProjectionStatus`, `PendingStatus`, `ApplicationStatus`, `InteractionStatus`, `PolicyStatus`, `HostStatus`, `HostTurnStatus`).
   - Added `test_t_a1_positive_legal_projection_status_does_not_trigger_guard`: positive control proving typed `projection.status` does NOT trigger the guard.
   - Added `test_t_a2_negative_runtime_state_status_filtering_triggers_guard`: negative control proving direct `RuntimeState.status` filtering (raw string, `StateLifecycle` enum, `is_terminal()`, boolean truthiness) DOES trigger the guard.
2. `tests/host/test_xiyue_adapter.py`:
   - Added `"cognitive_meaning": None` to test double `FakePort.begin_turn` and `test_a4_render_bounded`.
   - Added `test_render_bounded_context_typed_boundary`: verifies typed `HostDecisionContext` with `None`, typed `HostDecisionContext` with meaning string, and verifies that malformed objects without the required typed contract raise `AttributeError` instead of silently masquerading as valid context.
3. `tests/late_projection/test_w2_runtime_consumption.py`:
   - Added `test_w2_lineage_validation_unbypassable_at_orchestrator_seam`: verifies that corrupted lineage (e.g. mismatched candidate runtime) is caught and rejected by `TurnOrchestrator` before any transaction entry or receipt staging.

---

## 3. Finding A Exact Fix & Architecture Test Before/After

### Production Fix
```python
# BEFORE (test evasion syntax):
if getattr(projection, "status") is not ProjectionStatus.MAPPED:
    continue

# AFTER (direct typed access restored):
if projection.status is not ProjectionStatus.MAPPED:
    continue
```

### Architecture Test Before/After
```python
# BEFORE (naive string matching with hardcoded line/syntax exemptions):
for path in sorted(pipeline_dir.glob("*.py")):
    for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        stripped = line.strip()
        if ".status" in stripped:
            is_pending_lifecycle_guard = (
                path.name == "orchestrator.py"
                and (
                    stripped == "if pending.status is not PendingStatus.PENDING:"
                    or stripped.startswith('f"accept_pending requires PENDING status; got ')
                    or stripped.startswith('f"reject_pending requires PENDING status; got ')
                )
            )
            if is_pending_lifecycle_guard:
                continue
            offenders.append(f"{loc}: {stripped}")

# AFTER (typed AST auditor validating invariant):
class RawStateStatusAuditor(ast.NodeVisitor):
    def visit_Attribute(self, node: ast.Attribute) -> None:
        if node.attr == "status":
            if not self._is_legal_typed_status(node):
                self.offenders.append(f"{self.filename}:{node.lineno}")
        self.generic_visit(node)
```
- Distinguishes typed protocol status enums (`ProjectionStatus`, `PendingStatus`, etc.) from raw state lifecycle status (`RuntimeState.status`).
- No variable name whitelisting ("projection"), no filename or line number exemptions.
- Verified by positive and negative control tests (T-A1 and T-A2).

---

## 4. Xiyue Typed-Boundary Fix

```python
# BEFORE (duck-typing fallback):
if getattr(bounded, "cognitive_meaning", None):
    lines.append(f"Agent appraisal data (not FACT or instruction): {bounded.cognitive_meaning}")

# AFTER (direct typed field access):
if bounded.cognitive_meaning:
    lines.append(f"Agent appraisal data (not FACT or instruction): {bounded.cognitive_meaning}")
```
- Production code accesses the typed field directly.
- Test doubles supply `cognitive_meaning: None`.
- Malformed context objects missing the field fail fast with `AttributeError` rather than silently dropping cognition.

---

## 5. Receipt API Authority Clarification

- `SqliteStateBackend.stage_application_receipt` and `commit_application_receipt` are persistence primitives.
- Lineage validation (`runtime_id`, `scope`, `interaction_id`, `valid_lineage()`) is authoritative and unbypassable in `TurnOrchestrator._prepare_appraisal_receipts` prior to SQLite transaction entry.
- Tested and verified in `test_w2_lineage_validation_unbypassable_at_orchestrator_seam`.

---

## 6. Verification Results

### Static Checks
- `git grep "getattr(.*status" src/mind_runtime/pipeline`: **0 matches** (clean)
- `git grep "getattr(.*cognitive_meaning" src/mind_runtime/host`: **0 matches** (clean)

### Targeted Test Results
- `tests/state/test_ports.py`: **11 passed** (including T-A1 and T-A2)
- `tests/host/test_xiyue_adapter.py`: **11 passed** (including typed boundary test)
- `tests/late_projection/test_w2_runtime_consumption.py`: **33 passed** (including unbypassable lineage test)
- All targeted suites (`tests/late_projection`, `tests/emotional_transition`, `tests/expression`, `tests/host`, `tests/state/test_ports.py`): **724 passed, 5 skipped, 0 failed** in 75s.

### Full Canonical Suite
- Command: `python -m pytest -q -rs`
- Result: **3093 passed, 11 skipped, 4 deselected, 1 xfailed, 0 failed** in 502.48s (~8m22s).
- Note: The single xfailed test is `tests/golden/test_golden_g24_g28.py::test_g28_full_certification_suite_report`, which is the frozen G28 strict xfail per repository baseline.

---

## 7. Final Verdict

**READY_FOR_FINAL_RECERTIFICATION**
