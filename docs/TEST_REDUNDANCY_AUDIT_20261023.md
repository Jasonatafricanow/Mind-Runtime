# Test redundancy audit — 2026-10-23

Baseline: `70a88547b0fc9186465a96b7128de327ec3fc3da`.

The baseline CI reported 3,967 passed, 7 skipped, 1 xfailed and 4 deselected,
with 94% coverage. These are execution outcomes, not a count of independent
product guarantees.

## Inventory and limits

The audit scanned all 265 tracked test modules under `tests` and `xiyue/tests`:
3,062 test function definitions. Collection with optional LCE available selected
3,975 cases from 3,060 functions; parameter expansion accounts for 915 extra cases.
Collection executes no test bodies. `historical/tests` is a separate offline suite.

Removing docstrings and comparing AST bodies found 7 groups with 9 excess
definitions, unchanged after local-variable normalization. Ignoring literal values
as well produced 41 candidate groups containing 91 definitions. These are candidate
counts, not redundancy counts: imports, fixtures and parameter values can change
the contract. For example, recipe constants with identical names come from two
different production modules and cannot all be removed as copies.

Manual review of candidate inputs, imports, helpers and assertions confirmed the
following lower bound. This is not proof that every remaining test is unique.

## Removed redundant cases: 13

| Removed cases | Count | Retained guarantee |
| --- | ---: | --- |
| Registry-size checks in dynamics, curiosity, sharing and anger suites | 4 | `tests/dynamics/test_fast_functions.py::test_fast_function_v1_count_constant` checks the count constant and both collection lengths. |
| Sharing recipe digest check | 1 | The identical surface-module constant assertions remain in the curiosity suite. The expression-module recipe check remains separate. |
| Anger expression-map digest check | 1 | The sadness suite checks the same map constants and calls the production map validator. |
| Longitudinal unregistered seam and two tests labelled orchestrator integration | 3 | The U5 registered/unregistered resolver tests cover the exact same calls. The deleted “integration” tests never called the orchestrator. |
| Persona calibration no-unintended-coupling check | 1 | `test_t4_no_unconfigured_coupling` has the same engine, impulse, comparison and tolerance. |
| Shadow DR5 collision, identical resave and close/reopen checks | 3 | DR2 collision/idempotency tests and the full record roundtrip cover these inputs and stronger outcomes. The deleted tests did not inject storage failure. |

No production source, public contract or coverage threshold changed.

## Removed non-runtime checks: 6

One curiosity, two anger and three sadness tests only asserted literal status
strings assigned in the same test module (`PASS`, `NONE`, `CLOSED`, `DEFERRED`, etc.).
They could stay green with broken production behavior. They are not counted among
the 13 duplicates. Their historical conclusions remain in source notes; real
authority/cross-talk tests remain.

## Repeated execution

The `lce-integration` job reran 124 cases already included in `quality.tests` with
the same Python version, dev dependencies and pinned LCE revision. Those tests do
not depend on MR-Mem; the full job's additional MR-Mem package provides no separate
LCE test dimension. Remove this redundant job; retain its cases in full coverage.

Restrict `historical-tools` push events to `main`, as already done for the other
workflows, to avoid branch-push plus PR duplicate runs. Preserve its offline suite
and pinned compatibility dependency. Preserve the separate host job using minimal
test dependencies: that checks a distinct installation configuration.

## Areas not labelled duplicates

- The 915 parameter expansions are not automatically redundant. Different scopes,
  missing identities, input types and fault paths can each catch a real regression.
- Three legacy `coverage_gaps` modules contain 91 collected cases. Their naming and
  branch-oriented comments are maintenance concerns, not evidence that all 91 cases
  can be deleted. They include database corruption, replay and observation-order
  checks. No wholesale deletion or threshold reduction was performed.
- Static source checks and historical certification fixtures are weaker than live
  behavior evidence. Passing them does not certify core semantic algorithm quality.

The focused retained suites contained 235 cases after deletion. Local sandbox
hard-link restrictions affected 38 of them; rerun only those with local hard-link
access rather than repeat the 197 already passing cases. Final CI on the published
commit remains the full-suite/coverage authority.
