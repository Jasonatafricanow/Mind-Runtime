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
- pytest/coverage;
- Ruff no-regression baseline;
- mypy no-regression baseline.

Do not hide failing tests, silently widen skips/xfails, or claim external/live validation
that was not performed.

## Scope discipline

Keep changes bounded. If work starts creating a new planner, workflow engine, tool router,
carrier platform, generic agent framework, or unrelated research subsystem, stop and
re-check ownership before expanding MR.

Task reports should state: changed files, verification run, contract/ADR impact, explicit
non-goals, known gaps, and whether the change is ready to merge.


## Machine-enforced architecture compatibility markers

The repository still has governance tests that verify historical delivery-gate vocabulary.
These markers preserve that executable contract; they are not a reviewer scoring rubric.

Active authority references include:

- `docs/adr/0007-bound-expression-authority.md`
- `docs/adr/0008-split-d11-certification-and-live-shadow.md`
- `docs/superpowers/specs/2026-08-22-d7r-compressed-runtime-and-agent-onboarding-design.md`
- `docs/superpowers/specs/2026-08-23-d11s-deterministic-certification-and-d11l-entry-design.md`

Protected boundary vocabulary retained by governance tests includes
`EmotionalTransition and Assessment/Contribution Trace`,
`Intent lifecycle and scheduling`, and the rule that
`History facts cannot become Persona`.

Current historical gate markers:

- D7R is closed.
- D8 is closed.
- D9 is closed.
- D10 is closed.
- D11S is closed.
- D11L is blocked by the external environment.
- D11P, MR-4, and MR-5 remain blocked.

The frozen split is:

```text
D10 -> D11S -> D11L -> D11 completion -> D11P
```
