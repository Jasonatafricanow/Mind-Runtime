# Test necessity and consolidation — 2026-10-23

Baseline: `857c3f4cded80522644784aafd21e26da007c01e`.

The earlier AST-copy audit answered too narrow a question. Different source text,
fixture names, emotion labels, and historical task IDs do not establish independent
product guarantees. The suite has accumulated repeated feature matrices and checks
that never exercise the behavior described by their names.

## Size and denominator

Tracked active Python tests include helpers in `tests/` and `xiyue/tests/`.
Production Python is `src/`; host tools are separately identified. Effective lines
exclude blanks, standalone comments, and AST docstrings. Physical lines include them.
Research, historical tools/tests, documentation and data fixtures are excluded.

| Measure | Before | After |
| --- | ---: | ---: |
| Active test Python files | 310 | 306 |
| Active test physical lines | 95,354 | 89,945 |
| Active test effective Python lines | 74,846 | 70,707 |
| Production `src/` effective Python lines | 48,027 | 48,027 |
| Test / production effective Python lines | 155.8% | 147.2% |
| Test share of test + production effective Python lines | 60.9% | 59.6% |
| All production physical source lines, including frontend and host tools | 70,399 | 70,399 |
| Test / all production physical source lines | 135.4% | 127.8% |
| Test share of combined physical source | 57.5% | 56.1% |
| Selected pytest cases with optional integrations available | 3,956 | 3,785 |

Frontend physical lines: HTML 3,936, JavaScript 1,320, CSS 811. Host Python:
2,006. Production Python physical lines: 62,326. Ratios use matching units;
the Python-only ratio must not be presented as the whole repository's proportion.

This change removes 171 test functions/cases and a net 5,409 physical lines
(4,139 effective Python lines). It does not add parameter-expanded replacement
cases. Selected-case reduction is 4.3%; physical test-code reduction is 5.7%.
These are measured reductions, not an estimate of all remaining redundancy.

## Decisions by behavior, rather than textual similarity

| Removed or consolidated family | Retained owner / distinct guarantee |
| --- | --- |
| Curiosity and sharing repeat hand-written generic weight, threshold, and unconfigured-dimension rules | `tests/intents/test_engine.py` owns scoring. Feature suites retain actual wake/action selection, cooldown semantics, isolation configuration, competition, and completed begin/guard/commit chains. |
| Longing, curiosity, sharing repeat stages of the same host lifecycle | Longing retains host authority/rejection, explicit commit, abort, recovery and replay cases. Curiosity/sharing each retain a full chain; its assertions now include the selected action, nonempty host context, renderer isolation, and ALLOWED until explicit commit. |
| Anger and sadness duplicate surface interpretation and generic intent-engine matrices | `tests/dynamics/test_fast_functions.py`, `tests/surface/test_candidate_conformance.py`, `test_expression_provider_boundary.py`, and `test_intent_surface_boundary.py` own mappings, counterfactual isolation, exact bands, renderer payload restrictions, denied dispatch, and scoring boundaries. Two duplicated feature files are removed. |
| Constructing DENY or a helper-created Situation and asserting the supplied value | Removed: these cases do not invoke authorization, ticking, or observation generation. Real policy denial and pipeline behavior tests remain. |
| Historical SHA, source spelling, compiler-private-field and numeric-default regex checks | Removed: current runtime propagation, rejection and compatibility contracts remain. Historical conclusions belong in documents. |
| CSS numbers, breakpoints, HTML class spellings | Removed two checklist files and three isolated checks. Route, language and projection contracts remain. No claim that this constitutes rendered visual acceptance. |
| Longitudinal resolver checks repeated in lineage and authority suites | U5/U6 resolver cases own unregistered targets and affect rejection; actual salience propagation and veto chains remain. |
| Ticker construction repeated with identical missing resources; construction-only ticker and durable-row checks | Existing missing-resource rejection, behavioral ticker execution, and persistence readback/lifecycle tests own these guarantees. |

The September 26 re-expansion audit proposed reductions but was read-only. Its
classification of a case as a unique guarantee is not accepted merely because the
case name says “isolation”: the actual call and observable assertion decide that.
See `audits/MR_POST_MIGRATION_TEST_REEXPANSION_AUDIT_2026-09-26.md` for history.

## Why retain substantial testing at all?

MR has durable state, scoped authority, explicit admission and commit, crash/replay
recovery, external payload validation, and independent host/renderer boundaries.
Deleting a restart test because a normal save passed would lose a distinct failure
mode. Conversely, repeating a shared linear scoring formula for every emotion
does not establish a different algorithm. Shared behaviors get an owning suite;
feature tests justify themselves through their real configuration or integration seam.

There is no target test/source ratio or target test count. This audit does not
certify the remaining 3,785 selected cases as independently necessary. The whole
tree was inventoried; semantic consolidation concentrated on the repeated proactive,
surface, UI-checklist, longitudinal, wiring and construction families above.
Additional large suites contain real fault-injection and compatibility contracts
as well as possible further consolidation; they are not deleted by filename or size.

## Verification and limits

The changed areas passed three bounded local regressions: 158, 75, and 99 cases.
These are execution results, not new independent guarantees. Collection confirms
3,785 selected / 3,789 collected, with the same four live cases deselected.
The final submitted revision must pass the existing full remote quality workflow,
including the unchanged 94% coverage gate, plus host and historical-tool workflows.
Consult the PR checks for that revision's result; this document records no future pass.

No production code, algorithm, dependency, coverage threshold, skip or xfail policy
was changed. Tests still do not certify SemanticBlock compilation or appraisal
quality, real-model effectiveness, or production deployment.
