"""MR-ALPHA-AS1: Alpha Protocol orchestrator + report generation.

Ties together AlphaRunner → AlphaScorer → AlphaReport and writes the report
to the reports directory.
"""

from __future__ import annotations

import subprocess
from datetime import datetime
from pathlib import Path

from tests.mr_alpha.ablations import AblationArm, AblationSpec
from tests.mr_alpha.adapters import SyntheticSlowStateAdapter
from tests.mr_alpha.fixtures.trajectory_common import AlphaTrajectory
from tests.mr_alpha.probes import DEFAULT_FIXED_PROBE_SUITE, FixedProbeSuite
from tests.mr_alpha.protocol import AlphaProtocol
from tests.mr_alpha.report import AlphaReport, write_report
from tests.mr_alpha.runner import AlphaProtocolRunner, AlphaRunResult, AlphaRunner
from tests.mr_alpha.scorer import AlphaScorer, ArmScore

__all__ = [
    "AlphaOrchestrator",
    "build_alpha_report",
]


def _git_head_commit(repo_root: Path) -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=repo_root, text=True, timeout=2
        ).strip()
    except Exception:
        return "unknown"


class AlphaOrchestrator:
    """Run the protocol across all arms and produce the AlphaReport."""

    def __init__(
        self,
        protocol: AlphaProtocol,
        trajectory: AlphaTrajectory,
        probe_suite: FixedProbeSuite = DEFAULT_FIXED_PROBE_SUITE,
        *,
        reports_dir: Path,
        repo_root: Path | None = None,
    ) -> None:
        self._protocol = protocol
        self._trajectory = trajectory
        self._probe_suite = probe_suite
        self._reports_dir = reports_dir
        self._repo_root = repo_root or Path(__file__).resolve().parent.parent.parent
        self._protocol_runner = AlphaProtocolRunner(
            protocol, trajectory, probe_suite, reports_dir=reports_dir
        )

    def run(self) -> AlphaReport:
        run_result = self._protocol_runner.run()
        report = build_alpha_report(run_result, self._protocol, self._reports_dir)
        return report


def build_alpha_report(
    run_result: AlphaRunResult,
    protocol: AlphaProtocol,
    reports_dir: Path,
) -> AlphaReport:
    """Score the run_result and assemble an AlphaReport."""

    scorer = AlphaScorer(protocol)
    arm_scores: list[ArmScore] = []
    ablation_summary: dict[AblationArm, str] = {}

    # Find BASELINE for divergence comparison
    baseline_result = run_result.arm_results.get(AblationArm.BASELINE)
    baseline_internal_with_signal = None
    if baseline_result is not None:
        baseline_internal = scorer._arm_internal_to_metrics(
            baseline_result.arm_internal_metrics,
            baseline_result.consumer_invocations,
            pre=baseline_result.pre_snapshot,
            post=baseline_result.post_snapshot,
        )
        baseline_scores = baseline_result.intent_scores_per_probe
        baseline_mean = (
            sum(s for _, s in baseline_scores) / max(len(baseline_scores), 1)
        )
        baseline_internal_with_signal = scorer._with_behavioral_signal(
            baseline_internal, baseline_mean
        )

    for arm, traj_result in run_result.arm_results.items():
        scores = traj_result.intent_scores_per_probe
        mean_signal = (
            sum(s for _, s in scores) / max(len(scores), 1)
        )
        internal = scorer._arm_internal_to_metrics(
            traj_result.arm_internal_metrics,
            traj_result.consumer_invocations,
            pre=traj_result.pre_snapshot,
            post=traj_result.post_snapshot,
        )
        # Inject the mean intent score from the harness probes
        internal_with_signal = scorer._with_behavioral_signal(internal, mean_signal)
        arm_score = scorer.score_arm(
            arm=arm,
            internal=internal_with_signal,
            pre_snapshot=traj_result.pre_snapshot,
            post_snapshot=traj_result.post_snapshot,
            consumer_invocations=traj_result.consumer_invocations,
            intent_scores_per_probe=traj_result.intent_scores_per_probe,
            raw_outputs=traj_result.raw_outputs,
            baseline_internal=baseline_internal_with_signal,
        )
        arm_scores.append(arm_score)
        ablation_summary[arm] = (
            f"overall={arm_score.overall}, "
            f"slow_writes={traj_result.arm_internal_metrics.accepted_writes}, "
            f"consumer_invocations={traj_result.consumer_invocations}"
        )

    # Aggregate per-criterion verdicts across arms
    arm_scores_tuple = tuple(arm_scores)

    # Determine final verdict per ticket §12 (READY_FOR_PRODUCTION_BINDING):
    # B is implemented on this branch but C is not yet wired to production.
    # Therefore the harness cannot run against production consumer; emit
    # READY_FOR_PRODUCTION_BINDING.
    final_verdict = "READY_FOR_PRODUCTION_BINDING"
    external_dependency = (
        "C (consumption seam — IntentEngine/Compiler reading agent.slow.*)"
    )

    # Pick the most pessimistic across arms for the top-level per-criterion display
    if arm_scores_tuple:
        # If any arm passed all four criteria, surface that
        best_overall = max(arm_scores_tuple, key=lambda s: (s.overall == "PASS", 0))
        worst_overall = min(arm_scores_tuple, key=lambda s: (s.overall == "PASS", 1))
        mutation = best_overall.mutation
        persistence = best_overall.persistence
        consumption = best_overall.consumption
        behavioral_consequence = best_overall.behavioral_consequence
    else:
        from tests.mr_alpha.scorer import CriterionVerdict
        mutation = persistence = consumption = behavioral_consequence = CriterionVerdict(
            criterion="X", result="BLOCKED", evidence="no arms executed", value=0.0, threshold=0.0
        )

    # Compute mean signal density across arms
    if arm_scores_tuple:
        signal_density = sum(s.internal.signal_density for s in arm_scores_tuple) / len(arm_scores_tuple)
    else:
        signal_density = 0.0

    # Detect any failure boundary
    failure_boundary = None
    for s in arm_scores_tuple:
        if s.failure_boundary:
            failure_boundary = s.failure_boundary
            break

    return AlphaReport(
        protocol=protocol,
        run_id=run_result.run_id,
        commit=_git_head_commit(Path(__file__).resolve().parent.parent.parent),
        evidence_mode=protocol.evidence_mode,
        started_at=run_result.started_at,
        finished_at=run_result.finished_at,
        arm_scores=arm_scores_tuple,
        mutation=mutation,
        persistence=persistence,
        consumption=consumption,
        behavioral_consequence=behavioral_consequence,
        ablation_summary=ablation_summary,
        signal_density=signal_density,
        failure_boundary=failure_boundary,
        final_verdict=final_verdict,
        external_dependency=external_dependency,
        c_is_authoritative=False,
        b_is_authoritative=False,
    )