# MR-W2-FINAL-RECERTIFICATION-03

**Final verdict: NEEDS_TARGETED_FIX**

The identity gate failed. This audit stopped before provenance probes, production review, targeted tests, or commit. No production or test file was changed.

| Checkpoint | Expected | Independently observed | Result |
|---|---|---|---|
| Worktree | `C:\projects\mind-runtime-main-merge\.worktrees\mr-late-projection-w2-runtime-consumption-01` | Same (`git rev-parse --show-toplevel`) | PASS |
| Base HEAD | `f0c4df1f7b5808bfd5218d1fca990d5e216f96aa` | Same | PASS |
| Tracked binary diff SHA-256 | `cfc2ba906f1dd588634fa59f6dd804971c4f4fdef6cec5292f2502139a2e0565` | Same | PASS |
| Full tree manifest SHA-256 | `bfc3f3915b83d5605d2071f2a49a71681fff660b32aee8643e1891378e64060e` | `c9ee8d70ec04985c167e892c31b5e12f483364699b760264cf9aeb0c902d4aa9` | **FAIL** |

The observed manifest used the previous reviewer method: SHA-256 over `git diff --no-ext-diff --binary HEAD`, then for each sorted `git ls-files --others --exclude-standard` path, append UTF-8 path, NUL, and file bytes. Eight untracked paths existed before this report: the W2 runtime audit, certification fix audit, final source review, recertification 01, recertification 02, status guard hardening 02, status guard hardening 03, and `tests/late_projection/test_w2_runtime_consumption.py`. Excluding status guard hardening 03 still yielded `0889a4b9ba25e12db2f377ad9640c0909db462af66f5adcd139b96b96051eaff`, not the supplied manifest.

The supplied checkpoint does not define an alternative full-tree manifest algorithm. The tracked diff alone cannot authenticate the untracked files. This report itself was created only after the failed calculation and was excluded from that calculation.

**No `CERTIFIED_READY_FOR_W3` verdict or `W2_FINAL_SHA` is issued. No commit, merge, or push occurred.** Resolve the manifest identity/method mismatch and provide one reproducible byte manifest before recertification resumes.
