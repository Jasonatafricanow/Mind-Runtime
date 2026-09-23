# MR-W2-FINAL-SOURCE-REVIEW-01

只读最终 source review。本文不修改 production/tests；审计结论基于 W2 worktree 的 dirty working tree。

## Verdict

**NEEDS_TARGETED_FIX**

W2 的主要 runtime、SQLite application transaction、retry/restart、UNMAPPED 和 provider cognition 路径均有源码与 targeted-test 证据，但不能认证 `CERTIFIED_READY_FOR_W3`：pipeline 使用 `getattr(projection, "status")` 是此前为绕过 AST 架构测试而采用的语法规避，构成 test-gaming finding。另有一个 bounded hardening observation：cross-interaction lineage 在 orchestrator application seam 强制，generic receipt API 本身不独立证明 source lineage。

## Workspace authority

**WORKSPACE_AUTHORITY: PASS**

- authoritative root: `C:\projects\mind-runtime-main-merge`
- reviewed W2 worktree: `C:\projects\mind-runtime-main-merge\.worktrees\mr-late-projection-w2-runtime-consumption-01`
- legacy forensic root: `C:\projects\Mind Runtime`
- W2 worktree top-level resolves to the authoritative repository and uses `https://github.com/Jasonatafricanow/Mind-Runtime.git`.
- W2 `HEAD` is `f0c4df1f7b5808bfd5218d1fca990d5e216f96aa`, the supplied W2 base; the final implementation is an uncommitted working tree.
- authoritative main worktree is at `17772842aaffd44c4ff1a643e9fa4621fa9e6652`.
- legacy has no task-related new commit. Its recent history remains `f0f575b`, `e751808`, `0beaeba`, `1286365`, `a4f7bb3`, with older pre-existing tracked/untracked dirt and a separate remote (`git@github.com:christopher931649/Mind-runtime.git`).
- representative W2 file hashes differ between the W2 worktree and legacy (`expression/context.py`, `pipeline/orchestrator.py`, `state/persistence.py`, and `tests/validation/test_composition.py`); W2 mtimes are newer. No cross-copy evidence was found.

The W2 worktree is dirty with the implementation files, tests, the prior W2 audit, and the new W2 test file. No production or test file was changed during this review.

## Review identity and diff

The reviewed tree is `f0c4df1f7b5808bfd5218d1fca990d5e216f96aa` plus the tracked W2 modifications and untracked `tests/late_projection/test_w2_runtime_consumption.py` and `docs/audits/MR_LATE_PROJECTION_W2_RUNTIME_CONSUMPTION_01.md`. There is no final commit SHA to certify. Production changes are confined to the W2 orchestration, application receipt/state seam, appraisal-to-expression contracts, renderer/host adapter, and explicit legacy no-appraisal composition path. No SurfaceAffectProjector, behavioral_disposition, Reality/StateBar, Memory, LCE, or OW production feature was added.

## Finding A — projection status and `getattr`

`tests/state/test_ports.py::test_no_raw_status_filtering_in_pipeline_package` scans pipeline source for raw `.status` filtering. Its intended architectural rule is to prevent pipeline code from treating a `RuntimeState.status` field as a canonical filtering authority. `AppraisalProjectionResult.status` is a different, typed evaluation outcome and is explicitly part of the ADR-0027 contract.

The W2 path at `src/mind_runtime/pipeline/orchestrator.py:1222` uses:

```python
if getattr(projection, "status") is not ProjectionStatus.MAPPED:
```

The prior W2 audit explicitly records that this form was selected to avoid triggering that AST test. Other code uses direct typed `result.status`. Thus the underlying projection-status read is semantically legal, but the syntax was deliberately changed to evade the validation rule. This is **same semantics, different syntax** test evasion, not a trustworthy green architecture gate.

Minimal bounded fix: repair the validation/test API to distinguish typed `AppraisalProjectionResult.status` from raw canonical state status, then use the direct typed field and fail if the typed contract is absent. No ADR redesign is required. Until that is done, this finding blocks certification.

## Finding B — application identity and SQLite uniqueness

`application_identity` includes runtime, acceptance, effect-group, and original interaction. The receipt table has `PRIMARY KEY(application_id)` and `UNIQUE(runtime_id, acceptance_id)`. Under the current ADR, one accepted appraisal produces one authorized application group containing zero or many effects; Fast and Slow effects are members of that group, with `legacy_independent` and `required_joint` controlling group admission semantics. Reprojection/version changes create a new evaluation and are evaluation-only; they do not create a second application for the old acceptance.

Therefore the current cardinality is consistent: one acceptance is admitted at most once per runtime. A future contract allowing multiple independently authorized groups for one acceptance would make the SQLite unique key too narrow, but that is not the present ADR-0027 model. This finding is **PASS under the frozen contract**.

## Finding C — actual SQLite atomic boundary

The application path uses `SqliteStateBackend.transaction()` and its single connection. Composition constructs `SqliteCommitMarkerStore(..., connection=state_backend.connection)`; `SlowPlasticityWriter` receives the same backend. Inside the one transaction the orchestrator stages PENDING receipts, writes Fast canonical state, executes prepared Slow plans, records the existing commit marker, and updates receipts to COMMITTED. Publication occurs only after `commit()`.

`ProjectionJournal` is a separate evaluation database. It is deliberately durable before application and is not misrepresented as the application transaction. Nested backend transactions fail closed. This finding is **PASS** for the canonical W2 application path.

## Exactly-once state matrix

| Scenario | Evaluation | Receipt | Fast/Slow canonical state | Commit marker | Published memory |
|---|---|---|---|---|---|
| journal/projection write fails | accepted row may remain; no materialized result | absent | unchanged | absent | unchanged |
| failure before transaction / receipt staging | retained evaluation | absent | unchanged | absent | unchanged |
| receipt staged then transaction aborts | retained evaluation | rolled back/absent | rolled back | absent | unchanged |
| state committed, response lost, restart | retained | COMMITTED | committed once | present | reloads durable state; retry does not reapply |
| post-commit publication failure | retained | COMMITTED | committed once | present | reloads canonical state and records recovery trace |
| same-interaction retry | reused evaluation/receipt | same COMMITTED receipt | no second write | existing marker | unchanged |
| different interaction presents old result | readable audit/evaluation only | none | unchanged | unchanged | unchanged |

The W2 tests exercise rollback, restart reuse, same-interaction retry, publication failure, mixed-group behavior, and cross-interaction rejection. The lifecycle’s `ABORTED` value is traced on failure but is not persisted as a durable receipt row after rollback; the durable distinction is evaluation retained versus application absent.

## Cross-interaction protection

`_prepare_appraisal_receipts` validates interaction, scope, runtime lineage, journal acceptance equality, source appraisal/candidate references, and projection scope before entering the canonical transaction, raising `CanonicalPersistenceError("cross-interaction appraisal application rejected")`. This blocks the production application path before any receipt/state write. Existing W2 tests cover old-result replay rejection and restart.

Bounded observation: `SqliteStateBackend.stage_application_receipt` enforces receipt identity/uniqueness but does not itself validate source interaction lineage. An unrelated direct caller with backend access could call the generic receipt API. The canonical orchestrator seam is protected, but the backend API is not a complete independent authority boundary. This should be hardened or explicitly constrained before claiming an unbypassable authority seam.

## Legacy no-appraisal path

`LEGACY_NO_APPRAISAL` is selected only when no appraisal producer is configured. A configured producer rejection/error does not silently fall back to legacy mapping; this is covered by the W2 tests. The compatibility route is therefore explicit rather than an acceptance bypass.

## UNMAPPED and gain-once

Production orchestration carries accepted appraisals and projection references independently of impulses. A valid accepted novel meaning with no recipe reaches `UNMAPPED`, has empty effects, causes no appraisal mutation, and remains available to cognition. The targeted production-shaped test reaches Host bytes.

The projector emits Fast amounts before sensitivity. `DynamicsEngine` remains the sole sensitivity owner. No W2 wiring adds Persona gain, salience gain, or another multiplier; F1/F2 gain-once tests remain green.

## COGNITIVE_MEANING provider boundary

The verified path is:

`AcceptedAppraisal journal -> DecisionContextCompiler -> ExpressionContextKind.COGNITIVE_MEANING -> renderer -> HostDecisionContext -> xiyue Host bytes`.

Compiler admission is bounded to current interaction, ACCEPTED status, valid runtime/persona/scope lineage, and journal-resolvable source. Budget and policy omission do not delete the appraisal or alter projection status. Renderer emits `[COGNITIVE_MEANING]`/`[APPRAISAL_DATA]`; the Xiyue adapter labels it `Agent appraisal data (not FACT or instruction: ...)`. The W2 UNMAPPED production test asserts meaning text reaches Host output and no FACT section is emitted.

`HostDecisionContext` has a typed optional `cognitive_meaning` field. `xiyue_adapter.py` uses `getattr(..., "cognitive_meaning", None)` as compatibility handling; this is non-blocking while the production object remains typed, but a stricter boundary should use the typed field directly so a missing production field cannot silently drop cognition.

No ActionPolicy grant, Intent bypass, tool permission, or Surface behavior is introduced. Meaning remains appraisal data, never FACT, instruction, or mutation authority.

## Test-quality audit and probes

- Current targeted review run: **165 passed** across `tests/late_projection`, import-direction, OW transient trace, Xiyue runtime bundle, and cognition tick/expression tests.
- AGY’s reported canonical full suite: **3089 passed, 11 skipped, 4 deselected, 1 xfailed, 0 failed**. This review does not treat that report alone as proof; the source and targeted checks above were independently inspected.
- W2 tests assert durable SQLite state/receipt outcomes and final provider strings, rather than only mock call counts. Restart tests rebuild backend/journal connections; they are fresh connections rather than a spawned OS process.
- P1 status/getattr: reproduced by source inspection; the bypass is present and documented above.
- P2 identity/UNIQUE: schema and receipt staging show a second `(runtime_id, acceptance_id)` row is rejected even when application/effect-group identity differs; this matches the current one-group-per-acceptance ADR.
- P3 shared connection: composition passes `state_backend.connection` to the marker store and the Slow writer references the same backend; transaction code writes all four durable members through that connection.
- P4/P5 restart and cross-interaction: covered by W2 targeted tests and the source lineage checks.
- P6 UNMAPPED production orchestration and P7 final provider bytes/FACT separation: covered by the production-shaped W2 test and renderer/Host source inspection; targeted suite is green.

## Non-blocking observations

1. `ABORTED` is represented in trace/lifecycle objects but not retained as a durable receipt row after a rolled-back transaction.
2. Xiyue’s `getattr` compatibility read can silently omit cognition from an untyped/malformed Host object.
3. Generic receipt storage does not independently encode/validate source interaction lineage; the orchestrator is the protected mutation seam.

## Blocking findings

1. **Finding A / test gaming:** direct typed projection status was replaced with `getattr` specifically to evade the raw-status AST test. Repair the test boundary and restore explicit typed access before certification.

Given this blocker, the only supportable verdict for the reviewed working tree is **NEEDS_TARGETED_FIX**. No W3 certification is issued.
