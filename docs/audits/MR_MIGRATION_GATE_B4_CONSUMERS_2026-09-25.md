# Migration Gate B4 — Proactive Behavior Consumers

## Provenance and gate state

- Execution brief: GitHub issue #11, Gate B4.
- Target current-main base: `45cf36a91760f6eb9e39774edd656c1a2fc08a97` (merged Gate B3 close).
- Forward-port branch/worktree: `w/mr-migration-consumers-gate-b4-20260925` at
  `C:\projects\mind-runtime-main-merge\.worktrees\mr-migration-consumers-gate-b4-20260925`.
- Historical source branches & commits:
  - Longing: `8719386807eb932ce96a2cae72e1c9e4e3e3b333` (from `w/mr-longing-proactive-contact-v1-01`)
  - Fast-state consumer contracts: `9387147...`
  - Sharing urge: `be16499...` (from `w/mr-sharing-urge-proactive-share-v1-01`)
  - Curiosity: `a83922c...` (from `w/mr-curiosity-proactive-inquiry-v1-01`)
  - Anger: `1edd62e...` (from `w/mr-anger-boundary-confrontation-v1-01`)
  - Sadness: `9b46d66...` (from `w/mr-sadness-initiative-suppression-v1-01`)
  - Registry invariants: `b5af05a...`
- Takeover resolution and defect repairs:
  - Fixed runtime control-flow defect in `MindRuntimeHostAdapter.abort_proactive_turn`:
    elevated `pending_exec = self._pending_exec_contexts.get(wake_id)` before the
    lifecycle authority check to ensure deterministic fail-closed behavior across all paths.
  - Hardened typed boundary in `_resolve_expression_preparer` by explicitly typing
    local inspection variables as `object`, removing `no-any-return` violations without casts.
  - Declared `proactive_context_preparer: object = None` on `TurnOrchestrator` to
    resolve attribute definition and replace `setattr` in `runtime_loop.py`, satisfying Ruff `B010`.
  - Replaced untyped `r.json()` in `zen_provider.py` with standard `json.loads(r.text)`
    to ensure full type-safety under local environments with `curl_cffi` installed.
  - Added deterministic fail-closed regression test
    `test_abort_proactive_turn_without_lifecycle_fails_closed` in
    `tests/intents/test_longing_proactive_contact.py`.

## Exact path reconciliation

| Target path | Target change | Source treatment & Behavior preservation |
| --- | --- | --- |
| `src/mind_runtime/cognition/express.py` | Modified | Proactive context preparation without direct compiler config read; deterministic envelope isolation |
| `src/mind_runtime/cognition/tick.py` | Modified | Wake boundary restoration; Ticker produces wake signals without calling providers |
| `src/mind_runtime/contracts/host.py` | Modified | HostProactiveTurnResult contract alignment; explicit lifecycle states |
| `src/mind_runtime/dynamics/fast_functions.py` | Modified | Anti-spam invariants for sharing urge and curiosity; fast-state function specs |
| `src/mind_runtime/host/runtime_adapter.py` | Modified | Strict causal proactive turn lifecycle: wake admission -> Body entry -> ExpressionGuard -> delivery commit; fail-closed abort |
| `src/mind_runtime/host/xiyue_adapter.py` | Modified | Synchronous seam integration, non-proactive wake rejection |
| `src/mind_runtime/pipeline/orchestrator.py` | Modified | Proactive context preparer binding on orchestrator |
| `src/mind_runtime/shadow/runtime_loop.py` | Modified | Runtime wiring for proactive context preparer |
| `tests/intents/test_longing_proactive_contact.py` | Added/Updated | Full Longing proactive contact test suite, invariant verification, fail-closed abort tests |
| `tests/intents/test_sharing_urge_proactive_share.py` | Added/Updated | Sharing urge proactive share intent and ActionPolicy tests |
| `tests/intents/test_curiosity_proactive_inquiry.py` | Added/Updated | Curiosity proactive inquiry tests, autonomous retrieval deferral checks |
| `tests/surface/test_anger_boundary_confrontation.py` | Added/Updated | Anger boundary confrontation surface directness tests |
| `tests/surface/test_sadness_initiative_suppression.py` | Added/Updated | Sadness initiative suppression audit tests |
| `tests/dynamics/test_fast_functions.py` | Updated | Fast function registry anti-spam invariants and consumer validation |

## Historical behavior status preservation

- **Longing**: Proactive contact runtime path is closed and hardened; production activation remains governed by config. Ticker never invokes provider realization. Causal order: Policy -> WakeSignal -> Host wake admission -> Body entry -> ExpressionGuard -> delivery commit.
- **Sharing urge**: Dedicated `spontaneous_share` intent and `proactive_share` ActionPolicy path are wired; production activation remains blocked by config; anti-spam invariant is strictly validated.
- **Curiosity**: Proactive-question branch is closed; autonomous retrieval branch remains explicitly deferred; retrieval does not grant action authority.
- **Anger**: Surface confrontation -> qualitative directness expression dampening is closed; proactive confrontation/boundary Intent remains deferred; anger cannot grant action permission.
- **Sadness**: Surface initiative/warmth suppression was audited; primary downstream initiative consumer is explicitly recorded as not certified (`SADNESS_PRIMARY_FUNCTION_RUNTIME_GAP=FOUND`).
- No deferred or config-blocked features were silently activated during migration.

## Verification results

| Check | Result |
| --- | --- |
| Focused B4 suites (6 suites, 217 tests) | **217 passed in 44.20s** |
| Ruff baseline no-regression | `scripts/check_ruff_baseline.py` passed: current=753, baseline=801 (reduced by 48 findings) |
| mypy baseline no-regression | `scripts/check_mypy_baseline.py` passed: current=107, baseline=125 (reduced by 18 findings) |
| Full pytest suite with coverage | `coverage run -m pytest -q` passed with exit code 0 |
| Full suite test count & duration | **3821 passed, 8 skipped, 4 deselected, 1 xfailed (G28 strict xfail)** in 618.35s |
| Aggregate branch coverage | **94% total coverage** (18,754 stmts, 907 miss, 6,138 branches, 510 partial) |
