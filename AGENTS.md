# Mind Runtime Contributor Instructions

These instructions are for development and code-changing agents. They are not a reviewer
rubric and do not define conclusions about project quality.

## Canonical repository

- Repository: `Jasonatafricanow/Mind-Runtime`
- Integration branch: `main`
- Start new work from the current `main`.
- Do not reconstruct or backdate the pre-publication Git history. If a legacy change is
  still required, audit and forward-port the bounded change onto current `main`.

The public Git history is a cleaned publication baseline. See `PROJECT-HISTORY.md` and
`docs/case-studies/00-origin-and-scope-freeze.md` for provenance and evidence limits.

## Current architecture authority

For current behavior, use this order:

1. current source code;
2. executable tests and runtime configuration;
3. accepted ADRs/specifications;
4. historical design records.

Do not treat chat transcripts, historical work orders, or retrospective notes as stronger
authority than current code/tests/accepted contracts.

Useful entry points:

- `README.md` — current runtime surface and verification;
- `PROJECT-HISTORY.md` — publication-history boundary;
- `docs/architecture/MR_ARCHITECTURE_LOCK_v1_1.md` — scope/authority freeze;
- `docs/adr/` — accepted architecture decisions;
- `docs/case-studies/` — curated decision history.

## Change control

When new evidence or a requirement conflicts with a frozen contract, use:

```text
evidence / requirement -> ADR or contract update -> executable verification -> implementation
```

Do not change architecture-critical behavior first and justify it retrospectively.

Preserve these core boundaries unless an accepted ADR changes them:

- model output is not self-authorizing canonical state;
- retrieval is not authority;
- assistant output is not automatically external evidence;
- projected/uncommitted state is not canonical state;
- MR does not own open-ended planning, tool execution, or carrier execution;
- LCE remains optional and cannot directly write MR canonical state;
- Observation Window remains read-only with respect to MR cognition/state;
- derived embeddings, relations, caches, and summaries are rebuildable and non-authoritative.

## Verification

Before proposing a merge, run the narrow tests for the changed surface and the repository
quality gate that applies to it. The public CI currently covers:

- clean installation and runtime dependency imports;
- pytest failures and diagnostic coverage reporting (no aggregate minimum);
- Ruff no-regression baseline;
- mypy no-regression baseline.

Do not hide failing tests, silently widen skips/xfails, or claim external/live validation
that was not performed.

## Test design discipline

Coverage is a diagnostic signal. There is no required aggregate percentage. Test
necessity must be justified by a failure it detects, not by line/branch counts or a
target test/source ratio. Removing an assertion can lose a guarantee without changing
coverage at all.

- Test externally meaningful behavior, contracts, persistence, restart/replay, authority,
  isolation, idempotency, and fail-closed boundaries.
- Before adding a test, search the nearest suite for the same contract. Extend an existing
  table or fixture instead of restating the setup in a new test.
- Give each shared behavior a primary owning suite. This does not replace a consumer's
  distinct configuration or conditional path. Feature suites should test their actual
  configuration and integration seam, not repeat the shared scoring, host lifecycle,
  renderer-isolation, and permission matrix with a different emotion or intent label.
- State the distinct failure a new case detects that existing cases cannot. A renamed
  fixture, different arbitrary number, extra parameter row, or historical task ID does
  not establish a new testing angle. Delete redundant cases instead of merely folding
  them into a larger parameter table.
- Prefer assertions on the result of a real operation over constructor-input echoes,
  source-text searches, or CSS-value checklists. Static checks do not establish rendered
  usability, permission enforcement, or runtime data flow, but can guard an explicit
  source/configuration constraint. Do not delete them without checking what failure
  they detect and whether another assertion or a deliberate contract retirement covers it.
- Prefer `pytest.mark.parametrize`, small builders, and shared fixtures for symmetric
  environments, invalid-input matrices, thresholds, and fault-injection matrices.
- Do not add `test_*_coverage_gaps.py` cases whose only purpose is to hit an implementation
  branch. If a defensive branch is unreachable through supported interfaces, document the
  invariant or simplify the implementation instead of inventing a production-impossible
  test double solely for coverage.
- A refactor should not preserve duplicate tests merely to keep the collected-test count
  high. Preserve distinct guarantees, not historical test volume.
- Assertions against status/verdict literals defined in the same test file are notes,
  not runtime verification. Keep historical conclusions in documentation.
- Do not rerun a subset in CI when the full job already covers it with the same relevant
  dependencies. Separate minimal-install jobs must verify a distinct dependency contract.
- `research/archive/**` is frozen historical evidence, not an active runtime contract or
  default verification surface. Do not use archived harnesses, red-phase proofs, or old gate
  vocabulary as implementation authority unless an accepted current ADR explicitly revives it.

## Scope discipline

Keep changes bounded. If work starts creating a new planner, workflow engine, tool router,
carrier platform, generic agent framework, or unrelated research subsystem, stop and
re-check ownership before expanding MR.

Task reports should state: changed files, verification run, contract/ADR impact, explicit
non-goals, known gaps, and whether the change is ready to merge.
