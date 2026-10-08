# MR Long-Horizon Failure Suite

This is a small executable index of failure modes that matter specifically to
long-lived agents.

It is not a benchmark score and it is not a claim that every long-horizon
problem is solved. Its purpose is simpler: make the runtime's most important
authority failures easy to reproduce, review, and extend.

Run it with:

```bash
python -m pip install -e ".[dev]"
python scripts/run_long_horizon_failure_suite.py
```

## What the suite currently checks

| ID | Failure mode | Current executable coverage |
| --- | --- | --- |
| LH-01 | Assistant output or other derived runtime artifacts re-enter as authoritative evidence | `tests/pipeline/test_no_self_authorizing_feedback.py` |
| LH-02 | Restart/replay writes the same canonical memory again | `tests/memory/test_admission.py::test_admission_on_commits_once_and_restart_replay_is_noop` |
| LH-03 | Rejected assistant-derived evidence creates memory anyway | `tests/memory/test_admission.py::test_rejected_evidence_never_creates_job_or_memory` |
| LH-04 | An extractor forges evidence, observation, or scope provenance | `tests/memory/test_admission.py::test_extractor_cannot_forge_provenance` |
| LH-05 | Pending interpretation is mistaken for canonical state | `tests/pipeline/test_c9_w1b_pending_overlay.py::test_w1b2_pending_not_canonical` |
| LH-06 | Rejected or aborted pending state leaks into future authority | `tests/pipeline/test_c9_w1b_pending_overlay.py::test_w1b4_reject_clears_without_promotion`, `test_w1b7_abort_clears_pending_no_promotion` |
| LH-07 | Replayed evidence creates duplicate provenance | `tests/facts/test_provenance.py::test_provenance_recording_is_idempotent_per_event` |

The suite deliberately points at the real regression tests instead of copying
their logic into a second test layer.

## Open failure cases worth contributing

These are useful public test problems even when the eventual runtime policy is
not yet decided:

- **Equivalent-evidence amplification:** the same underlying event arrives
  through paraphrase, summary, or duplicate transport IDs and is accidentally
  counted as independent authority.
- **Contradiction and supersession:** newer evidence conflicts with an older
  interpretation, but both continue to influence current state as if they were
  simultaneously authoritative.
- **Semantic extraction false positive:** a parser or model turns a mention
  into a factual state change even though the source text never asserted that
  state.

For these open cases, the first contribution should normally be a minimal
failing test or fixture, not a new subsystem.

## What makes a good failure-suite case

A useful case has four properties:

1. A short sequence of turns/events reproduces it.
2. The expected invariant can be stated without product-specific prose.
3. The test distinguishes source evidence from model/runtime interpretation.
4. It can fail for a real architectural reason rather than because of a
   particular prompt wording.

Good examples:

```text
user evidence
-> model/runtime interpretation
-> derived artifact
-> later turn
-> derived artifact must NOT become new independent evidence
```

```text
evidence E
-> commit
-> restart
-> replay E
-> canonical memory/provenance count must remain stable
```

## Contribution rule

Do not add a new architecture concept just to make a failure test pass.

If a proposed fix changes a frozen contract such as Evidence, State, Memory,
Authority, Ownership, TurnProjection, DecisionContext, or Intent semantics,
open an ADR first as required by `AGENTS.md`.

For a first contribution, prefer:

```text
minimal reproduction
-> failing regression test
-> explain the violated invariant
-> smallest implementation change
-> targeted suite
-> full pytest suite
```

The goal is to make long-horizon failures easier to attack in code, not to add
more vocabulary around them.
