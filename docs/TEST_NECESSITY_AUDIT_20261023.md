# Test necessity audit — corrected 2026-10-23

The earlier conclusion that all 171 deletions were redundant was wrong. Unchanged
coverage did not show that assertions preserved their failure-detection angles.
This revision restores ten checks and adds missing assertions to existing owners.
It supersedes the necessity claims in `eae2680`, `1a3f613`, and `4c3fa79`.

## Coverage policy

No risk-based justification for 94% was found in the available public baseline or
audited migration records. Public history is a cleaned baseline; this does not prove
that no earlier justification ever existed. The old comment called 94% the current
baseline and required it to rise. That is a ratchet, not a demonstration of adequacy.

The B2 Surface migration audit records 93.0651%, then 43 additional boundary tests
and 93.5195% displayed as 94%. The B3 fast-function audit records 93.4998%, then six
additional tests and 93.5410%. The September 26 re-expansion audit explicitly
identifies coverage-driven additions, including both real failure paths and
coverage-only checks. Threshold pressure is evidenced; it does not make every such
test useless. See those dated documents in `docs/audits/`.

`fail_under = 94` is removed. Coverage measurement and missing-line reports remain;
pytest failures, installation checks, Ruff and mypy gates remain. The explicit cost
is that an aggregate coverage drop no longer fails CI by itself. No replacement
percentage, test count or test/source ratio is prescribed. This policy change is
separate from judging individual deletions and is not a cure for weak assertions.

## Corrections and retained deletions

| Boundary | Correction / decision |
| --- | --- |
| Actual certified configuration | Extend `test_runtime_manifest_decodes_named_executable_fixture` to assert non-proactive policy flags and action types, and absence of anger/confrontation/initiative wiring. The existing exact intent-kind tuple and complete `DecisionContextConfig` equality already cover their respective fields. |
| Host return metadata | Add `HostDecisionContext.action_taken` and `intent_summary` assertions to the existing longing lifecycle. An envelope action assertion did not cover these separately assembled fields. |
| Optional initiative admission | Extend the existing sharing/inquiry cases to verify that sadness does not suppress the motive when the optional minimum-initiative gate is absent. |
| Surface compiler and provider | Extend the existing provider test through projection, compilation and rendering for low/high directness and warmth, including compiled guidance items. Scalar partition tests alone did not cover that path. |
| Chart and mobile contracts | Restore eight scoped checks: focus/compare, selected guide, fixed Y range, bounded requests, stable viewBox, individual non-scaling strokes, minimum widths and causal mobile layout. These are source guards, not rendered visual acceptance. |
| Retired external-memory wiring | Restore two `run()` source guards and assert actual default compatibility fields are `None`. Constructor signature and injected sentinels did not prove the default/run behavior. |
| Repeated formulas | Keep baseline/persona vectors and per-root counterfactuals in `test_candidate_conformance.py`. These exercise the actual adapter, including sadness and anger coefficients; do not restore a second feature harness for another arbitrary numeric point. |
| Test-local status strings | Keep their assertions deleted. Comparing a constant defined in the same test file with its own literal does not validate production activation or calibration. |
| UI detail and construction echoes | Seven removed pixel/density/duplicate-route checks remain removed as a deliberate maintenance tradeoff. Keep removal of constructor-input echoes and repeated missing-resource tests; this is not proof that every source-text check is useless. |

The restored API guard also counts direct `fetch` calls when `runtimeFetch` is
present. Stroke checks bind each relevant SVG element, so an unrelated placeholder
cannot compensate for a missing attribute. One-off source counterexamples confirmed
detection of an added direct request and each of three removed stroke attributes.
These experiments did not modify production files and are not new permanent suites.

## Review and disagreement

Fresh-context internal reviews examined intent, Surface, UI/wiring and policy
deletions. A subsequent patch review found the two weak UI assertions above; a
bounded re-review confirmed those repairs. Reviewer agreement is not a correctness
proof.

At the user's request, Grok Build (`grok-4.7-build`) reviewed a 437-line source
packet covering four seams plus the coverage policy. It completed with
`stopReason=end_turn`, with tools disabled and read-only settings. Earlier CLI
attempts stopped without a review; they are not counted as approvals. This was a
packet review, not a whole-repository inspection or executed mutation analysis.

Its actionable config/UI/retired-wiring/compiler findings are addressed above.
Several conditional concerns were resolved by reading omitted source: both manifest
paths identify the same file; `DecisionContextConfig` is a dataclass whose equality
includes `mode`, defaulting to `LEGACY`; curiosity status constants are test-local;
actual recipe coefficients have retained baseline and per-root vector checks.
Thus the requested restoration of those duplicate assertions was not adopted.

Grok recommended retaining a failing coverage floor. Its concrete concern — losing
an aggregate alarm — is accepted and documented. Retaining an arbitrary floor or
changing its decimal precision does not establish its risk basis. The policy
decision remains to report coverage without a global acceptance percentage. No
claim is made that the reviewer endorsed that choice.

## Size, verification and limits

Historical baseline `857c3f4`: 3,956 selected cases, 95,354 active-test physical
lines and 74,846 effective Python lines. The superseded `4c3fa79` state had 3,785
selected cases and 89,952 / 70,712 lines. This repair restores ten test functions;
it does not reinstate the duplicate feature harnesses. Current source totals and
the final exact-commit CI result accompany the delivery evidence and PR.

Production source remains 48,027 effective Python lines in `src/`, or 70,399 physical
lines including frontend and host tools. Active-test measurements include helpers
in `tests/` and `xiyue/tests/`, exclude research/historical code, and exclude blanks,
standalone comments and docstrings only from the effective-line measure. These
denominators must not be mixed to exaggerate a percentage.

The initial repair passed 45 focused cases. The final UI/compiler revision passed
18 focused cases; those overlap and must not be summed as independent guarantees.
Full verification is performed once in remote CI on the submitted revision. A green
run establishes observed compatibility, not necessity of all remaining tests.

MR has distinct persistence, restart/replay, scope/authority, admission/commit and
external-input failure modes. Those justify substantial testing but not a chosen
number of tests. This audit covers the named deletion families; it does not certify
every remaining case as necessary or assign a whole-repository redundancy rate.
No production algorithm, dependency, skip or xfail policy is changed. Tests still
do not certify SemanticBlock/appraisal quality, real-model effectiveness or deployment.
