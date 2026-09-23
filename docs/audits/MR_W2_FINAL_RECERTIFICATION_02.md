# MR-W2-FINAL-RECERTIFICATION-02

**Final verdict: NEEDS_TARGETED_FIX**

This review is limited to receiver-proven status guard closure and the previously identified typed Host/receipt seams. No production or test file was modified. No W2 final commit was created.

## Authority and checkpoint

| Item | Observed value |
|---|---|
| Repository | `C:\projects\mind-runtime-main-merge` |
| Reviewed worktree | `C:\projects\mind-runtime-main-merge\.worktrees\mr-late-projection-w2-runtime-consumption-01` |
| Branch | `w/mr-late-projection-w2-runtime-consumption-01` |
| HEAD / W2 base | `f0c4df1f7b5808bfd5218d1fca990d5e216f96aa` |
| Previous reviewer tracked diff SHA-256 | `fdc4a3d613e00c87a08e9c9212e3800b8a3daa357dcee87b396bc9766ac66150` |
| Previous reviewer combined manifest SHA-256 | `f2e2afd7560952e6262ed8e740d1e94187fc03fe7b29528db49859c9775b0d24` |
| Current tracked binary diff SHA-256 | `6f7624adf99ca3a4e1bf52813e30d72b3cb558c51acce2f3befdc67e797c00e3` — matches the supplied post-fix checkpoint |

The previous reviewer hashes are recorded evidence from the prior recertification. The current post-fix hash was independently recomputed from `git diff --no-ext-diff --binary HEAD`. The hardening report identifies `tests/state/test_ports.py` as its only code edit and reports zero production edits. Because the previous dirty tree was not committed or saved as a complete per-file snapshot, its two aggregate hashes cannot alone prove that each other file is byte-for-byte unchanged. The current production source is consistent with the reported narrow fix; the exact pre/post changed-file claim remains provenance-limited.

## Closure checks

| Gate | Result | Evidence |
|---|---|---|
| Receiver-proven guard | **FAIL** | The visitor tracks annotations, constructors and aliases, but a later assignment from an unresolved conditional/subscript expression does not clear the previous approved type in `visit_Assign`. A `.status` read after that assignment is incorrectly allowed. |
| Original reviewer counterexample | PASS | `state: RuntimeState; state.status == HostTurnStatus.COMMITTED` reports one offender. |
| Typed projection status | PASS | `projection: AppraisalProjectionResult; projection.status is ProjectionStatus.MAPPED` reports no offender. |
| `.status.value` | PASS for required case | `state: RuntimeState; state.status.value == "committed"` reports one offender; there is no unconditional `.status.value` allowance. |
| Constructor and simple alias provenance | PASS for required cases | `RuntimeState(...) -> state2.status` reports one offender; `AppraisalProjectionResult(...) -> projection2.status` reports none. |
| Unknown receiver | **FAIL** | An initially unannotated `x.status` reports an offender. An approved variable reassigned from a conditional or subscript expression with unproven type retains stale approval and reports none. An unknown *named call* such as `get_state()` is correctly rejected by this implementation; the failing cases are the unresolved expression forms. |
| Current production dynamic bypass scan | PASS | No `getattr(state, "status")`, `vars(state)["status"]`, `state.__dict__["status"]`, or `operator.attrgetter("status")` authority filter found under `src/mind_runtime/pipeline`. Its only direct `.status` reads are typed projection and pending lifecycle reads. |
| Previous production closures | PASS | Orchestrator still uses direct `projection.status`; Xiyue directly reads `bounded.cognitive_meaning`; receipt backend remains a persistence primitive and `_prepare_appraisal_receipts` performs lineage/runtime/scope/interaction/journal validation before transaction entry. |
| Production diff since supplied frozen checkpoint | Reported NONE; not independently byte-proven | The checkpoint contains aggregate diff/manifest hashes, but no retrievable pre-fix per-file tree. Current tracked production file set and source were inspected; no additional production fix is indicated. |
| Targeted tests | PASS | `tests/state/test_ports.py`: 11 passed; `tests/host/test_xiyue_adapter.py`: 11 passed; `tests/late_projection/test_w2_runtime_consumption.py`: 33 passed. |

## Independent adversarial probe

The new `TypeProvenanceVisitor` has `visit_Assign` update `current_scope[target]` only when `_resolve_expr_type(node.value)` returns a type. For an `ast.IfExp`, `_resolve_expr_type` returns `None`, so the old approved entry remains even though one branch is a known `RuntimeState`. This is an ordinary conditional assignment:

```python
def check(projection: AppraisalProjectionResult, state: RuntimeState, flag):
    projection = state if flag else projection
    if projection.status == HostTurnStatus.COMMITTED:
        pass
```

Independent execution of the test module's `find_raw_state_status_offenders` returned `['<string>:2']` for the original `RuntimeState` reviewer example, `[]` for the legitimate typed projection, and **`[]` for the conditional reassignment above**. With `flag=True`, that branch reads the raw `RuntimeState.status` and compares it to an approved `StrEnum` value, yet the architecture test would report it legal. `projection = states[0]` and `projection = holder.state` produce the same stale-approval result. As a control, `projection = get_state()` *does* report an offender; the failure is specific to unrecognized expression forms.

The bounded correction is to invalidate or mark the receiver unknown on every assignment whose right-hand type cannot be established, including conditional and subscript assignments over an approved annotation or alias. Add this conditional reassignment as a negative control. This does not call for a W2 production change or ADR redesign.

## Reviewed working-tree identity

- `git diff --name-only HEAD`: 26 tracked files, consisting of the W2 production/test set already present under the base; `tests/state/test_ports.py` is the hardening test file. No staged diff.
- `git diff --stat HEAD`: 26 files changed, 1,060 insertions, 100 deletions.
- Tracked binary diff SHA-256: `6f7624adf99ca3a4e1bf52813e30d72b3cb558c51acce2f3befdc67e797c00e3`.
- Untracked before this report (path : SHA-256):
  - `docs/audits/MR_LATE_PROJECTION_W2_RUNTIME_CONSUMPTION_01.md` : `8e43b29d5aaa4f389767f361060fa6236dbac8095c0e89b85c0a5004d3b4b5cc`
  - `docs/audits/MR_W2_CERTIFICATION_FIX_01.md` : `672dccac108d6e071ecd3671f5a733900788226c8c90452757d6ee0d8673dfb2`
  - `docs/audits/MR_W2_FINAL_RECERTIFICATION_01.md` : `bece708d4b53009b4f0385b6a6244f2f8c10dc4bc14e85d63018c41e6600b66b`
  - `docs/audits/MR_W2_FINAL_SOURCE_REVIEW_01.md` : `2358aa0850d14aff749cd70ed5588930f655f64e18f6fc0d904ba6f7d1a50e94`
  - `docs/audits/MR_W2_STATUS_GUARD_HARDENING_02.md` : `75d4f7b1b934d5dc0871a1824c1bb0662c3868d827dfc3d1e30c720e20da232c`
  - `tests/late_projection/test_w2_runtime_consumption.py` : `55d193fe6081c22a0e4b827f17e1f8d4a191b4852902df306c012efdd9200cf7`
- Combined reviewed tree manifest SHA-256 before this self-referential report: `53fe65499fb2cc80ba5606a88b7d016fac51507f578d1bf3a4a446b0504f60ec` (binary tracked diff bytes followed by sorted untracked path, NUL, file bytes).

The prior full-suite result of 3,093 passed, 11 skipped, 4 deselected, 1 xfailed, 0 failed remains implementation evidence. A full rerun was not warranted by this bounded review because the status guard blocker is independently reproduced. **The commit gate stays closed; no `W2_FINAL_SHA` is certified.**
