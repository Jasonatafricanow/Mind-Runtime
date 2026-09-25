# Migration Gate A — Reality/Input (2026-09-25)

## Identity and outcome

- Execution brief: GitHub issue #11; dedicated Reality issue #8.
- Source worktree/branch: `C:\projects\mind-runtime-main-merge\.worktrees\mr-reality-eligibility-replay-stability-01`, `w/mr-reality-eligibility-replay-stability-01`.
- Source authority: `14154a52848906b67ad200ce39f0094b2d06e0e5` (clean at audit).
- Target base: current `main@c378e1ae246bb5b7ab3505165d8f701c7bf5dfae`.
- Forward-port branch: `w/mr-migration-reality-gate-a-20260925`.
- Implementation commit: `cabb3ed535dc9762e00c2b3655b2bb5718517d1b`.
- Boundary regression commit: `919d152579d44025eeef724b3e69f5fe4489832a`.
- Pull request: [#12](https://github.com/Jasonatafricanow/Mind-Runtime/pull/12).
- Gate A was merged as `ed229e694b9f98e834430f5be7f18784ace02881`, with parents `c378e1ae246bb5b7ab3505165d8f701c7bf5dfae` and `7d12aa7374bbaeb13e18c5f730b1b72380ca2462`. The merge tree equals the verified PR head tree. The source worktree/ref remains preserved.

## Exact changes

Production files added:

```text
src/mind_runtime/contracts/reality.py
src/mind_runtime/reality/__init__.py
src/mind_runtime/reality/eligibility.py
src/mind_runtime/reality/extraction.py
src/mind_runtime/reality/temporal.py
```

Production files modified:

```text
src/mind_runtime/contracts/__init__.py
src/mind_runtime/contracts/observation.py
src/mind_runtime/facts/persistence.py
src/mind_runtime/facts/ports.py
src/mind_runtime/facts/service.py
src/mind_runtime/pipeline/orchestrator.py
src/mind_runtime/shadow/runtime_loop.py
src/mind_runtime/state/reconciler.py
```

Tests added:

```text
tests/reality/test_observation_contract.py
tests/reality/test_reality_input.py
tests/reality/test_reality_persistence.py
tests/reality/test_replay_provenance.py
tests/reality/test_replay_stability.py
tests/reality/test_state_eligibility.py
tests/reality/test_temporal_normalization.py
tests/reality/test_migration_edge_boundaries.py
tests/memory/test_real_body_agent_offline.py
```

Tests modified:

```text
tests/contract/test_d1_2_evidence_observation_state_transition.py
tests/contract/test_import_direction.py
tests/reality/test_state_eligibility.py
```

The architecture contract `docs/architecture/MR_REALITY_OBSERVATION_CONTRACT_01.md` was added from the source commit. There was no ADR edit at Gate A. Historical StateBar reuse planning/audit documents remain recovery evidence for Gate C.

## Source identity and interface reconciliation

The final Reality source was forward-ported without merging its branch. Of the 23 source-changed files, 22 have blob IDs identical to `14154a5`. The only shared-file reconciliation was `src/mind_runtime/pipeline/orchestrator.py`: the target retains current main's `Path` import and `object` types for its external Memory reservation seam. A direct file diff against `14154a5` shows only those differences. No Reality behavior was intentionally changed.

The MR-native input path admits evidence-backed typed Observations, then passes eligible current or exact terminal facts through the existing factual reconciliation authority. Future/planned/tentative statements remain observation-only; replay retains causal evidence and semantic target. The port introduces no StateBar runtime import or writeback, and no direct Reality-to-Affect/Persona/Memory writer. The current Memory V1 architecture, Memory ADR-0028, LCE, packaging and CI configuration were not edited.

The extra tests exercise provider failure/malformed output, temporal windows, eligibility rejection, and fail-closed vocabulary. Offline Memory Body tests protect the current mainline request framing, response recording and inconclusive failure semantics across this migration; they do not change Memory production code.

## Verification

| Gate | Result |
| --- | --- |
| Pre-port RED | `python -m pytest tests/reality -q -x` failed collection on absent `EffectiveWindow` |
| Source Reality tests, Python 3.12 | 69 passed |
| Affected contract/facts/state/pipeline/shadow, Python 3.14 | 1167 passed |
| Full suite, Python 3.12, final `919d152` | `3025 passed, 7 skipped, 4 deselected, 1 xfailed` in 542.25 s |
| Coverage, final `919d152` | `94.03058707449432%`; required 94%; pass |
| Ruff baseline, final `919d152` | 781 current / 801 allowed; pass |
| mypy baseline, final `919d152` | 110 current / 125 allowed; pass |
| GitHub Actions quality on `919d152` | [run #191](https://github.com/Jasonatafricanow/Mind-Runtime/actions/runs/36102559554): Success, clean-install/python/tests jobs passed |
| GitHub Actions quality on report commit `7d12aa7` | [run #193](https://github.com/Jasonatafricanow/Mind-Runtime/actions/runs/36103423784): Success |
| GitHub Actions quality on merged main `ed229e6` | [run #194](https://github.com/Jasonatafricanow/Mind-Runtime/actions/runs/36103845878): Success |

The first PR run on `cabb3ed` failed only the 94% aggregate coverage gate; its 2993 tests passed. The new regression tests raised measured coverage without changing production behavior or the threshold. Windows required `tzdata` in the ignored local Python 3.12 virtual environment; repository dependencies were unchanged. A preliminary Python 3.14 Ruff invocation had a GBK subprocess decoding error, so only the UTF-8 Python 3.12 rerun is counted.

## Remaining boundary

Gate A is merged and current-main CI is green. The old Reality worktree, branch and predecessor archive refs remain preserved until issue #11's final disposition review.
