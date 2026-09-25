# Migration Gate B2 — W3 Surface, Persona publication, durable handoff

## Provenance and gate state

- Execution brief: GitHub issue #11. Historical W3 source tree:
  `386d3e8d8e49a1f2d8e9d6d4e18641ed2d0c504e`; W3 delta begins after
  `ee6b25d535ffc3e3b1e0f37c567ab5572049b0ea`. Source branch/worktree:
  `w/mr-w3-e-authority-hardening-01` at
  `C:\projects\mind-runtime-main-merge\.worktrees\mr-w3-e-authority-hardening-01`.
- Forward-port branch/worktree: `w/mr-migration-surface-gate-b2-20260925`,
  `C:\projects\mind-runtime-main-merge\.worktrees\mr-migration-surface-gate-b2-20260925`.
  Initial target main base: `26305fefec3a81fa77688eb42d28c7d8f0dd7102`,
  containing merged Gate A/B1 and their evidence correction PR #14. Current
  target main base: `478860257fa494c4801a9c565fa9b578fa315d82`.
- Code/docs/test source port: `dbf55ca9f3eede4f005c098eb657e5211a7697e9`.
  Platform lock typing correction: `1ca93dc4fca2cafafccd1693c584d994e51d0898`.
  Fail-closed boundary tests: `1f02131290a63975443f2e48fef0a365b85c9432` and
  `b53c3bdfc8098a10f4bb7c72d58a8d5495b756d5`. The current main was
  merged normally into this branch at `8afc0fe326034f6cf2bc9800dd5da3917fbd8ac6`;
  its tree equals GitHub's PR auto-merge tree at `00f9ff522b6f96f5d58d1604ecfab6cb8c8a85b7`.
  Additional Host/consumer/Expression boundary tests: `6481bc0ea5c3568de5d6c2d98bee8b354da621fc`.
- Pull request: [#15](https://github.com/Jasonatafricanow/Mind-Runtime/pull/15),
  merged at `e64d46ac7d42ada36b345e4abceb93226bce87a0` (parents
  `478860257fa494c4801a9c565fa9b578fa315d82` and
  `c1fe0ef4af5cf95ae7cce8fb995fd8525a7e21bf`). No historical branch
  merge or historical ref deletion was performed.

## Reconciliation

The W3 source delta was extracted by path. The three shared source files
`contracts/__init__.py`, `pipeline/orchestrator.py`, and `shadow/runtime_loop.py`
needed explicit integration. The contract export preserves current Reality/W2
exports and adds Surface. The orchestrator retains the Reality admission and
replay path, typed W2 projection status, and the current Memory seam while
adding one Surface authority and the durable C7 handoff. Runtime composition
retains Reality input and current Memory hybrid/HyDE behavior while binding
one published Persona revision and one Surface projector. The remaining paths
were applied from the W3 delta, with current Ruff/mypy baseline adaptations
and nine new boundary test files added for this gate.

At the initial 60-path port commit, 15 staged blobs exactly matched the
historical W3 source, 42 were adapted, and three paths had no same-name source
(`ADR-0031`, `ADR-0032`, and the mapping note). The largest adapted classes
were ADR references, shared seams, and mechanical formatting/type fixes. The
W3 architecture was not redesigned. Historical Surface ADR-0028 and Persona
ADR-0029 were renumbered to ADR-0031/0032; the exact mapping is in
`MR_W3_ADR_NUMBER_MIGRATION_2026-09-25.md`. Current Memory ADR-0028/0029,
Memory source, and LCE source are unchanged relative to the current main base
`4788602`. The only shared Host file is `host/xiyue_adapter.py`: this gate adds
the W3 provider prose guard on top of current main's Memory/LCE composition.

Surface remains derived and noncanonical. Persona publication is create-once
and runtime resolution is read-only. Intent scoring rejects transitive root
overlap; ActionPolicy retains permission authority. Expression consumes only
bounded qualitative Surface guidance. The provider handoff is persisted in C7
before exposure, and restart recovery checks the exact envelope and provenance.
The Candidate recipe/map are implementation-authorized, not evidence of
production calibration or real-agent activation.

## Verification

| Check | Result |
| --- | --- |
| Pre-port RED | `pytest tests/surface/test_persona_disposition_boundary.py -q -x` failed during collection on absent `BehavioralDisposition` |
| W3 Surface focused | 128 passed |
| Reality/W2/Surface/Memory and affected runtime paths | 1654 passed, 2 skipped on the corrected main base |
| Surface→validation sequence | 519 passed |
| Fixed-HEAD full suite at `b53c3bd` | 3539 passed, 7 skipped, 4 deselected, 1 xfailed in 513.06 s |
| Coverage at `b53c3bd` | 93.63107932923515% exact, displayed 94%; `coverage report --show-missing` passes repository fail-under=94 |
| Ruff no-regression | 752 current / 801 baseline; pass |
| mypy no-regression | 108 current / 125 baseline on Windows; pass |
| GitHub Actions quality on `b53c3bd` push | [run #239](https://github.com/Jasonatafricanow/Mind-Runtime/actions/runs/36114717517): success |
| Early GitHub Actions quality on PR #15 | [run #240](https://github.com/Jasonatafricanow/Mind-Runtime/actions/runs/36114723446): failed aggregate coverage before current-main reconciliation |
| Current-main merge tree at `8afc0fe` | 3541 passed, 7 skipped, 4 deselected, 1 xfailed in 497.28 s; coverage 93.06513568212796% exact, displayed 93, below threshold |
| New boundary tests at `6481bc0` | 43 passed |
| Fixed-HEAD full suite at `6481bc0` on the merged current-main tree | 3584 passed, 7 skipped, 4 deselected, 1 xfailed in 512.83 s |
| Fixed-HEAD coverage at `6481bc0` | 93.51947461897484% exact, displayed 94%; `coverage report --skip-covered` passes repository fail-under=94 |
| Ruff / mypy after current-main merge | 752 / 801 Ruff and 107 / 125 mypy errors; both no-regression gates pass |
| GitHub Actions on `8afc0fe` | [PR run #242](https://github.com/Jasonatafricanow/Mind-Runtime/actions/runs/36117041960) failed aggregate coverage, while tests and static/clean-install/LCE integration passed |
| GitHub Actions on `6481bc0` | [PR quality #243](https://github.com/Jasonatafricanow/Mind-Runtime/actions/runs/36119240527) and [push quality #244](https://github.com/Jasonatafricanow/Mind-Runtime/actions/runs/36119246166) both succeeded, including tests, Python static, clean-install, and LCE integration |
| GitHub Actions on evidence commit `c1fe0ef` | [PR quality #245](https://github.com/Jasonatafricanow/Mind-Runtime/actions/runs/36119970149) and [push quality #246](https://github.com/Jasonatafricanow/Mind-Runtime/actions/runs/36119974177) both succeeded |
| Merged main quality at `e64d46a` | [run #247](https://github.com/Jasonatafricanow/Mind-Runtime/actions/runs/36120503830) succeeded, including tests, Python static, clean-install, and LCE integration |

The first full local run crossed a Git HEAD change during its long-horizon
replay and failed its pinned source-head check. A fixed-HEAD rerun passed all
tests. The earlier PR CI on `dbf55ca` passed its tests but failed Linux mypy
platform typing and aggregate coverage. The platform fix and substantive
fail-closed tests were present at `b53c3bd`. The PR #240 and #242 aggregate
coverage failures arise when W3 is combined with newer Memory/LCE main.
Additional boundary tests were added at `6481bc0`; its fixed-HEAD full run
and both current-main PR/push quality runs passed. No failed run is presented
as successful gate evidence.

## Changed path inventory

The A/M markers below distinguish added and modified paths in the exact Git diff from the current target main base
`4788602` to `6481bc0`, including the additional fail-closed tests. The historical W3
source path list and blob reconciliation above refer to the initial 60-path
port commit only.

```text
A docs/adr/0031-single-surface-behavior-exposure.md
A docs/adr/0032-persona-publication-and-surface-handoff-provenance.md
A docs/architecture/MR_W3_SURFACE_ARCHITECTURE_01.md
A docs/audits/MR_W3_ADR_NUMBER_MIGRATION_2026-09-25.md
A docs/contracts/MR_SURFACE_V1_CANDIDATE_EXPRESSION_MAP_01.md
A docs/contracts/MR_SURFACE_V1_CANDIDATE_RECIPE_01.md
A docs/contracts/MR_SURFACE_V1_GOLDEN_CONTRACT_02.md
M src/mind_runtime/binding_registry.py
M src/mind_runtime/cognition/tick.py
M src/mind_runtime/contracts/__init__.py
M src/mind_runtime/contracts/affect.py
M src/mind_runtime/contracts/behavior.py
M src/mind_runtime/contracts/expression.py
M src/mind_runtime/contracts/host.py
M src/mind_runtime/contracts/intent.py
A src/mind_runtime/contracts/surface.py
M src/mind_runtime/delivery/__init__.py
M src/mind_runtime/delivery/daemon.py
M src/mind_runtime/delivery/persistence.py
A src/mind_runtime/delivery/surface_handoff.py
M src/mind_runtime/dynamics/persona.py
M src/mind_runtime/expression/context.py
M src/mind_runtime/expression/coordinator.py
A src/mind_runtime/expression/expression_map.py
M src/mind_runtime/expression/renderer.py
M src/mind_runtime/host/__init__.py
M src/mind_runtime/host/port.py
M src/mind_runtime/host/runtime_adapter.py
M src/mind_runtime/host/xiyue_adapter.py
M src/mind_runtime/intents/engine.py
M src/mind_runtime/intents/persistence.py
A src/mind_runtime/intents/surface_validator.py
M src/mind_runtime/persona_config.py
A src/mind_runtime/persona_publication.py
M src/mind_runtime/pipeline/orchestrator.py
M src/mind_runtime/shadow/runtime_loop.py
M src/mind_runtime/state/persistence.py
M src/mind_runtime/state/ports.py
A src/mind_runtime/surface/__init__.py
A src/mind_runtime/surface/adapter.py
A src/mind_runtime/surface/cognition.py
A src/mind_runtime/surface/evaluator.py
A src/mind_runtime/surface/expression_map.py
A src/mind_runtime/surface/lineage.py
A src/mind_runtime/surface/projector.py
A src/mind_runtime/surface/recipe.py
M tests/contract/test_import_direction.py
A tests/surface/__init__.py
A tests/surface/conftest.py
A tests/surface/spec_support.py
A tests/surface/test_binding_registry_persona_fail_closed.py
A tests/surface/test_candidate_conformance.py
A tests/surface/test_committed_recomputation_admission.py
A tests/surface/test_consumer_lineage_rejection.py
A tests/surface/test_expression_provider_boundary.py
A tests/surface/test_expression_wire_admission.py
A tests/surface/test_fail_closed_wire_boundaries.py
A tests/surface/test_fixture_integrity.py
A tests/surface/test_handoff_recovery_rejection.py
A tests/surface/test_host_surface_guard_boundary.py
A tests/surface/test_historical_reference.py
A tests/surface/test_intent_surface_boundary.py
A tests/surface/test_normative_architecture.py
A tests/surface/test_persona_disposition_boundary.py
A tests/surface/test_persona_publication.py
A tests/surface/test_production_handoff.py
A tests/surface/test_publication_and_intent_rejection.py
A tests/surface/test_secondary_consumer_guards.py
A tests/surface/test_turn_tick_surface_boundary.py
```

## Gate disposition

**GATE B2 CLOSED.** Current main was checked at
`478860257fa494c4801a9c565fa9b578fa315d82`; PR and push quality at
`6481bc0` and `c1fe0ef` passed. PR #15 merged at
`e64d46ac7d42ada36b345e4abceb93226bce87a0`, and merged-main quality
#247 passed. Gate B3 Fast Function may begin. Historical W3 branches/worktrees
remain preserved for Issue #11's final disposition matrix.
