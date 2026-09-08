# MR-ALPHA: Accumulated-State Causal Acceptance Protocol

**Version:** alpha-v1
**Status:** `READY_FOR_PRODUCTION_BINDING`

## Purpose

MR-ALPHA is a **harness-validation-only** protocol for the B-W (slow-plasticity) accumulated-state dynamics in the Mind Runtime. It establishes a causal, per-arm scoring framework to detect regressions in the mutation, persistence, consumption, and behavioral-consequence dimensions of accumulated-state dynamics.

> ⚠️ **Evidence Mode:** This protocol operates in `harness_validation` mode. It does NOT run against production evidence corpora or the production slow-plasticity consumer (C). Production binding requires AS-B and is tracked separately.

## Protocol Scoring Criteria

MR-ALPHA scores four independent causal criteria:

| Criterion | What it measures | Default threshold |
|-----------|-----------------|------------------|
| **M** — Mutation | Internal-state change from appraisal → homeostasis → slow_write | meaningful_appraisals ≥ 3, slow_candidates ≥ 1, accepted_writes ≥ 1, accumulated_delta ≥ 0.001 |
| **P** — Persistence | Slow-state identity survives the runtime destroy/reload boundary | slow_states identical; provenance subset-superset |
| **C** — Consumption | IntentEngine (consumer) was invoked during the trajectory | consumer_invocations ≥ 1 |
| **B** — Behavioral Consequence | Ablation arms (WRITE_OFF, CONSUME_OFF, STATE_RESET) are behaviorally inert; TREATMENT diverges | behavioral_divergence < 0.01 (ablations); ≥ 0.01 (TREATMENT) |

An arm's **overall verdict** is:

- `PASS` — all four criteria pass
- `FAIL` — at least one criterion fails
- `BLOCKED` — topology is missing (e.g., no consumer wired)

## Protocol Arms

| Arm | Role | Description |
|-----|------|-------------|
| `BASELINE` | Reference | Full pipeline with real emotional-transition + slow-plasticity writer |
| `TREATMENT` | Probe | Introduces a synthetic emotional-transition injection into the trajectory |
| `WRITE_OFF` | Ablation | Slow-plasticity writer is replaced with a no-op stub |
| `CONSUME_OFF` | Ablation | Intent consumer is not invoked; slow_states are frozen |
| `STATE_RESET` | Ablation | Slow-states are cleared after each turn |

## Architecture

```
tests/mr_alpha/
├── __init__.py           # Public API re-exports
├── protocol.py           # AlphaProtocol + AlphaScoreCriteria (AS-00)
├── ablations.py          # AblationArm + AblationSpec (AS-06)
├── probes.py             # FixedProbeSuite (AS-05)
├── runner.py             # AlphaRunner + AlphaProtocolRunner (AS-02)
├── causal_trace.py       # CausalTrace + CausalTraceEntry (AS-03)
├── persistence_harness.py # PersistenceHarness + StateSnapshot (AS-04)
├── scorer.py             # AlphaScorer (AS-07)
├── report.py             # AlphaReport + render_markdown + write_report (AS-08)
├── orchestrator.py       # AlphaOrchestrator + build_alpha_report
├── adapters/
│   ├── __init__.py
│   ├── synthetic_slow_state.py  # SyntheticSlowStateAdapter
│   └── synthetic_emotional_transition.py  # SyntheticEmotionalTransitionAdapter
├── fixtures/
│   ├── __init__.py
│   ├── control_neutral.py    # Neutral emotional evidence corpus
│   ├── trust_support.py      # Trust-supportive evidence corpus
│   └── conflict_boundary.py   # Conflict-near boundary evidence corpus
├── conftest.py           # Shared pytest fixtures
└── test_alpha_harness.py # Integration tests
```

## Running the Protocol

### Full harness (all arms, harness-validation mode)

```python
from pathlib import Path
from tests.mr_alpha.orchestrator import AlphaOrchestrator
from tests.mr_alpha.protocol import AlphaProtocol
from tests.mr_alpha.fixtures import CONTROL_NEUTRAL

protocol = AlphaProtocol()
orch = AlphaOrchestrator(protocol, CONTROL_NEUTRAL, reports_dir=Path("reports/"))
report = orch.run()
```

### Single arm directly

```python
from tests.mr_alpha.runner import AlphaRunner
from tests.mr_alpha.ablations import AblationArm, AblationSpec
from tests.support.fake_clock import FakeClock
from datetime import datetime, UTC

runner = AlphaRunner(protocol, CONTROL_NEUTRAL, reports_dir=Path("reports/"))
result = runner.run_arm(
    AblationSpec(arm=AblationArm.BASELINE, trajectory_ref="control_neutral"),
    backend,
    FakeClock(datetime.now(UTC)),
)
```

## Report Output

Each run produces:

- `{run_id}.md` — Human-readable report with per-arm verdict table, criterion evidence, ablation summary, and failure boundary
- `{run_id}.json` — Machine-readable report (same data as JSON)

## Production Binding (AS-B)

The harness-validation report is a **gate toward** production binding, not the binding itself. The `final_verdict` is `READY_FOR_PRODUCTION_BINDING`, meaning the harness machinery is correct and stable. The production binding (AS-B) requires:

1. A real emotional-transition implementation that fires on evidence keys
2. A production slow-plasticity consumer (C) that reads `agent.slow.*` from the runtime
3. An evidence corpus of real typed-events (not synthetic probes)
4. Wiring of the consumption seam (IntentEngine/Compiler reading `agent.slow.*`)

AS-B will produce an `EVIDENCE_MODE = production` report that supersedes the harness-validation report.

## Failure Boundary Classification

When M fails, the scorer classifies the failure into one of four boundaries:

| Boundary | Description | Typical fix |
|----------|-------------|-------------|
| `Appraisal` | Zero semantic candidates emitted | Check SemanticRouter or evidence key types |
| `Homeostasis` | Candidates surfaced but no HomeostasisDecision | Check salience threshold or H6 bridge |
| `Slow write` | Candidates accepted by gate but not SLOW_ACCEPT | Check gate disposition threshold |
| `Mutation` | Slow writes occurred but accumulated_delta below threshold | Adjust effect magnitude or evidence corpus |
