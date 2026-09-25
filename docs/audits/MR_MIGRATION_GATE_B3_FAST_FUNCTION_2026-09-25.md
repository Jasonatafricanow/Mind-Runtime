# Migration Gate B3 — Fast Function V1 registry

## Provenance and gate state

- Execution brief: GitHub issue #11, Gate B3. Historical source branch and
  preserved worktree: `w/mr-fast-function-v1-01` at
  `C:\projects\mind-runtime-main-merge\.worktrees\mr-fast-function-v1-01`.
  Its clean source HEAD is `5f9635287e8774dd5f8c086bcbc0677b7a3786e7`,
  parent `17772842aaffd44c4ff1a643e9fa4621fa9e6652`.
- Target current-main base: `664cded5cae036bbc8e6e35f546b70f6e29ac557`,
  after Gate B2 Surface and its evidence closure. Forward-port branch/worktree:
  `w/mr-migration-fast-function-gate-b3-20260925` at
  `C:\projects\mind-runtime-main-merge\.worktrees\mr-migration-fast-function-gate-b3-20260925`.
- Code, architecture, and test port: `19f2542ae041f82d3b29094fe5314229fe2738f0`.
  Additional registry rejection and inherited `Mapping.get` boundary tests:
  `aa42726b319b01c1c4aef1447e0188e0beaf02c3`.
  The historical branch was not merged, reset, or removed.

## Exact path reconciliation

| Target path | Target change | Source treatment |
| --- | --- | --- |
| `src/mind_runtime/dynamics/fast_functions.py` | Added | Eight historical function specs and registry; format/string wrapping and `Mapping.get` type correction |
| `src/mind_runtime/dynamics/__init__.py` | Modified | Historical public exports, applied to current main |
| `tests/dynamics/test_fast_functions.py` | Added | Historical A–L tests, mechanically formatted |
| `docs/architecture/MR_FAST_FUNCTION_V1.md` | Added | Historical contract with explicit registry/consumer/activation distinction |

The source commit also contained
`docs/audits/MR_FAST_FUNCTION_V1_IMPLEMENTATION_01.md`. That document reports
historical test results at the old base; it remains in the preserved source
line as historical evidence for Gate C classification, rather than being
published as current Gate B3 certification.

The only code interface drift was current mypy's `Mapping.get` override
check. Removing the redundant override uses the inherited `Mapping.get`,
which delegates to the same registry `__getitem__` and preserves lookup
behavior. The historical strings and eight function identities are unchanged.
No current Memory, LCE, Surface, Persona, or runtime configuration path was
modified.

`FastStateStatus.ACTIVE` is a registry admission status. It does not assert
that a named consumer is closed or that production configuration activates it.
`REGISTERED_ONLY` fatigue remains without live dynamics calibration or an
outbound consumer. `external_action_capable` does not grant action permission;
ActionPolicy retains that authority. The Longing, Sharing, Curiosity, Anger,
and Sadness consumer dispositions belong to Gate B4.

## Verification

| Check | Result |
| --- | --- |
| Pre-port RED | `pytest tests/dynamics/test_fast_functions.py -q -x` failed on missing `mind_runtime.dynamics.fast_functions` under Python 3.12 |
| Focused Fast Function at source port | 12 passed |
| Focused Fast Function after rejection tests | 18 passed |
| Dynamics, Intent, Expression, Surface, Host | 860 passed in 74.29 s |
| Ruff no-regression | 752 current / 801 baseline; pass |
| mypy no-regression | 107 current / 125 baseline; pass |
| First fixed-HEAD full suite at `19f2542` | 3596 passed, 7 skipped, 4 deselected, 1 xfailed in 521.84 s; exact coverage 93.49981486814498%, below 94 display threshold |
| Early PR CI on `19f2542` | [run #252](https://github.com/Jasonatafricanow/Mind-Runtime/actions/runs/36122840048): tests passed but aggregate coverage failed; Python, clean-install, and LCE integration passed |
| Fixed-HEAD full suite at `aa42726` | 3602 passed, 7 skipped, 4 deselected, 1 xfailed in 498.85 s |
| Fixed-HEAD coverage at `aa42726` | 93.5409552803719% exact, displayed 94%; `coverage report --skip-covered` passes fail-under=94 |
| GitHub Actions on `aa42726` | [PR quality #254](https://github.com/Jasonatafricanow/Mind-Runtime/actions/runs/36124020880) and [push quality #253](https://github.com/Jasonatafricanow/Mind-Runtime/actions/runs/36124014427) both succeeded, including tests, Python static, clean-install, and LCE integration |
| GitHub Actions on report commit | [PR quality #255](https://github.com/Jasonatafricanow/Mind-Runtime/actions/runs/36125719126) and [push quality #256](https://github.com/Jasonatafricanow/Mind-Runtime/actions/runs/36125724114): success |
| Merged main | PR #17 merged as `389ad3bb28be524cba5eeabc89df8ac10c0c84a3`; parents `664cded5cae036bbc8e6e35f546b70f6e29ac557` and `66d9c28d4064862ba0e195a2f4e78c806be635fa` |
| GitHub Actions on merged main | [main quality #257](https://github.com/Jasonatafricanow/Mind-Runtime/actions/runs/36126298281): success |

## Gate disposition

**GATE B3 CLOSED.** Fixed-HEAD full suite and coverage passed; report-commit
quality, PR #17 merge, and merged-main quality all succeeded. The exact target
merge is `389ad3bb28be524cba5eeabc89df8ac10c0c84a3`. Historical
refs/worktrees remain preserved for Issue #11's final matrix.
