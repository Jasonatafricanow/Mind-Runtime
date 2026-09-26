# Contributing to Mind Runtime

Mind Runtime is easiest to contribute to through concrete failure modes.

You do not need to understand the entire repository before opening a useful
issue or pull request. A small reproducible problem is more valuable than a
large architecture proposal without an executable case.

## Start here

Install the development environment:

```bash
python -m pip install -e ".[dev]"
```

Run the small long-horizon regression slice:

```bash
python scripts/run_long_horizon_failure_suite.py
```

Then run the full suite before requesting review:

```bash
python -m pytest -q
```

See [MR Long-Horizon Failure Suite](docs/failure-suite/README.md) for the
current public failure cases.

## Good first contributions

Good first changes are narrow and testable:

- add a minimal reproduction for a long-horizon failure;
- improve an existing regression test so the failure is easier to understand;
- add a deterministic fixture for replay, restart, contradiction, or scope
  isolation;
- improve documentation around an existing code boundary;
- fix a bounded bug without changing a frozen contract.

Avoid starting with a new subsystem or a new set of project-specific concepts.

## Before changing runtime behavior

This repository has frozen authority contracts. Read `AGENTS.md` before
changing production behavior.

In particular, changes to Evidence, Observation, State, Memory, Scope,
Authority, Ownership, TurnProjection, Dynamics, Intent, ActionPolicy,
ExpressionGuard, or DecisionContext require the repository's ADR/contract
process when semantics change.

The normal sequence is:

```text
reproduction
-> contract or ADR when required
-> failing test
-> implementation
-> targeted verification
-> full verification
```

## Pull request shape

Keep one pull request focused on one bounded problem. A useful PR description
should state:

- the failure or missing behavior;
- the invariant being protected;
- what changed;
- what did not change;
- targeted tests run;
- full-suite result;
- any remaining gap.

If the change is exploratory, say so. Do not present an experiment as a new
runtime authority.

## Review standard

Review should focus on observable behavior and authority boundaries:

- Where did the information come from?
- Is it evidence, interpretation, projection, pending work, or canonical state?
- What authorizes it to affect a later turn?
- Can replay, restart, retrieval, or model output accidentally strengthen it?
- Can the change be inspected and reverted?

The project intentionally prefers explicit failure semantics over hidden
heuristics.
