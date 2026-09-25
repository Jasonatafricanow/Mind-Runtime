# Migration Gate B1 — hardened Late Projection W2 (2026-09-25)

## Provenance and result

- Execution brief: GitHub issue #11, behavior migration issue #10.
- Final source tree: `ee6b25d535ffc3e3b1e0f37c567ab5572049b0ea`, recovered from the local W3/behavior ancestry. Source sequence: `2a2af13`, `f3196eb`, `6e027cd`, `41f4f1e`, `f0c4df1`, `ee6b25d`. The intervening `645d0dd` is historical audit evidence rather than production code.
- Source branch/worktree lineage: archived Late Projection F1/F2 and W1 refs, then `w/mr-late-projection-w2-runtime-consumption-01`; the final W2 commit is also an ancestor of `w/mr-w3-surface-*` and later behavior branches.
- Initial target main base: `ed229e694b9f98e834430f5be7f18784ace02881` (Gate A merge).
- Updated target main base: `04e545b9c1b42be2e22ee95de1490ac6d455acdc`, after concurrent Memory hybrid retrieval publication. The B1 branch incorporated this main commit by normal merge, without force push.
- Forward-port branch/worktree: `w/mr-migration-w2-gate-b1-20260925`, `C:\projects\mind-runtime-main-merge\.worktrees\mr-migration-w2-gate-b1-20260925`.
- Migration code/test commit: `912210e366cc006ef7b82195657bff8da16e4d70`; current-main incorporation commit: `68729253e68fcfd60c72cdf2df599fc333f5403e`.
- Pull request: [#13](https://github.com/Jasonatafricanow/Mind-Runtime/pull/13). Final main replacement SHA is recorded after merge.

## Exact migrated files

Production added:

```text
src/mind_runtime/contracts/late_projection.py
src/mind_runtime/emotional_transition/projection_journal.py
```

Production modified:

```text
src/mind_runtime/cognition/express.py
src/mind_runtime/cognition/tick.py
src/mind_runtime/contracts/emotional_transition.py
src/mind_runtime/contracts/expression.py
src/mind_runtime/contracts/host.py
src/mind_runtime/dynamics/ports.py
src/mind_runtime/emotional_transition/appraisal.py
src/mind_runtime/emotional_transition/effects.py
src/mind_runtime/emotional_transition/glm_provider.py
src/mind_runtime/emotional_transition/zen_provider.py
src/mind_runtime/expression/context.py
src/mind_runtime/expression/renderer.py
src/mind_runtime/host/runtime_adapter.py
src/mind_runtime/host/xiyue_adapter.py
src/mind_runtime/pipeline/orchestrator.py
src/mind_runtime/shadow/runtime_loop.py
src/mind_runtime/state/persistence.py
src/mind_runtime/validation/composition.py
src/mind_runtime/validation/contracts.py
```

Tests added: `tests/emotional_transition/test_open_vendor_vocabulary.py`; `tests/late_projection/{test_f1_f2_hardening,test_foundation,test_journal_supersession,test_legacy_equivalence,test_w2_runtime_consumption}.py`; fixture `tests/late_projection/fixtures/legacy-effects.json`.

Tests modified: `tests/contract/test_import_direction.py`; `tests/emotional_transition/test_appraisal_producer.py`; `tests/host/{test_ow_transient_trace_journal_v1,test_xiyue_adapter}.py`; `tests/state/test_ports.py`; `tests/validation/test_composition.py`.

ADR-0027 changed from proposed to historically accepted. The old W2 audit files remain preserved on the source lineage for Gate C classification; especially `MR_W2_FINAL_RECERTIFICATION_03.md`, which says `NEEDS_TARGETED_FIX` because its untracked-file manifest did not match. This gate does not represent that report as a successful certification.

## Reconciliation and semantic boundary

The final source diff was extracted against common ancestor `17772842aaffd44c4ff1a643e9fa4621fa9e6652` and applied only to the 35 production/test/ADR paths above. There was no wholesale branch merge. Fresh blob comparison after the migration commit found **27/35 exact source blobs** and eight explicit adaptations:

| Path | Reason for difference |
| --- | --- |
| `src/mind_runtime/pipeline/orchestrator.py` | Preserve current Memory seam and Gate A Reality admission/replay, plus current import/format style at two equivalent merge conflicts. W2 uses typed `projection.status`. |
| `src/mind_runtime/shadow/runtime_loop.py` | Preserve Gate A Reality production composition. |
| `tests/contract/test_import_direction.py` | Preserve Gate A Reality contract import allowances. |
| `src/mind_runtime/dynamics/ports.py` | Wrap one long error string to satisfy current Ruff per-file baseline. |
| `src/mind_runtime/validation/composition.py` | Sort imports for the current Ruff baseline. |
| `tests/host/test_ow_transient_trace_journal_v1.py` | Remove an import made unused by the W2 test change. |
| `tests/host/test_xiyue_adapter.py` | Wrap one long assertion. |
| `tests/state/test_ports.py` | Use equivalent `StrEnum` declaration and shorten one test docstring for the current Ruff baseline. |

No W2 behavior was intentionally changed. Source and migrated code contain no `getattr(projection, "status")` shortcut. Accepted semantic meaning remains independent of effect-map coverage; the journal and application receipt carry the durable exactly-once boundary; `COGNITIVE_MEANING` remains bounded provider context rather than FACT or action authority. The concurrent Memory hybrid retrieval files and Memory ADR-0028/0029 are unchanged relative to the updated target main; no LCE file changed.

## Verification

| Gate | Result |
| --- | --- |
| Pre-port RED | `pytest tests/late_projection/test_foundation.py -q -x` failed on absent `SemanticAppraisalProducer.accept` |
| W2/status-guard/vendor focused | `pytest tests/late_projection tests/state/test_ports.py tests/emotional_transition/test_open_vendor_vocabulary.py -q -x`: 212 passed |
| Affected Reality/Memory/facts/state/pipeline/host/expression/emotional | 1642 passed, 3 skipped on the initial Gate A base |
| Updated-base W2/status-guard/Memory-hybrid/Reality | 321 passed on `6872925` |
| Full suite on updated base, Python 3.12 | 3252 passed, 7 skipped, 4 deselected, 1 xfailed in 500.11 s |
| Coverage on updated base | 94.15750150819063%; required 94%; pass |
| Ruff baseline | 765 current / 801 allowed; pass |
| mypy baseline | 109 current / 125 allowed; pass |
| GitHub Actions quality on `6872925` | [run #205](https://github.com/Jasonatafricanow/Mind-Runtime/actions/runs/36105148663): Success, clean-install/python/tests jobs passed |

The initial full run on `912210e` was stopped at 53% without a failure when main published new Memory hybrid retrieval code. It is not a certification result. The complete result above is from the updated target base. The currently published Memory main quality run #201 also completed successfully.

## Remaining boundary

This report commit needs its own current PR CI. Merge Gate B1 only after that result and a fresh main-head check. Keep all archived and local W2 refs/worktrees until issue #11's final disposition. W3 Surface, Fast Function and consumers remain separate later gates.
