"""MR-ALPHA-AS1: Automated Alpha Report — AS-08.

Produces one canonical report per experiment run, in Markdown form.

Reports are ALWAYS marked ``EVIDENCE_MODE = HARNESS_VALIDATION_ONLY`` until
AS-09 binds the harness to production (B+C authoritative).  Reports
without that marker MUST NOT be claimed as MR Alpha evidence.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Literal

from tests.mr_alpha.ablations import AblationArm
from tests.mr_alpha.protocol import AlphaProtocol
from tests.mr_alpha.scorer import ArmScore, CriterionVerdict

__all__ = [
    "AlphaReport",
    "render_markdown",
    "FinalVerdict",
]

FinalVerdict = Literal["PASS", "FAIL", "BLOCKED", "INVALID", "READY_FOR_PRODUCTION_BINDING"]


@dataclass(frozen=True)
class AlphaReport:
    """Canonical per-run Alpha report."""

    # Identity
    protocol: AlphaProtocol
    run_id: str
    commit: str
    evidence_mode: str
    started_at: datetime
    finished_at: datetime

    # Per-arm verdicts
    arm_scores: tuple[ArmScore, ...]

    # Per-criterion results (across all arms)
    mutation: CriterionVerdict
    persistence: CriterionVerdict
    consumption: CriterionVerdict
    behavioral_consequence: CriterionVerdict

    # Ablation behavior summary
    ablation_summary: dict[AblationArm, str] = field(default_factory=dict)
    signal_density: float = 0.0

    # Hard gate result
    external_dependency: str = ""
    failure_boundary: str | None = None
    final_verdict: FinalVerdict = "BLOCKED"

    # C/B ablation context
    c_is_authoritative: bool = False
    b_is_authoritative: bool = False


def render_markdown(report: AlphaReport) -> str:
    """Render AlphaReport as GitHub-flavored Markdown per ticket §10."""

    lines: list[str] = []
    lines.append("# MR Accumulated-State Causal Alpha")
    lines.append("")
    lines.append(f"**Protocol version:** {report.protocol.version}")
    lines.append(f"**Run ID:** {report.run_id}")
    lines.append(f"**Commit:** {report.commit}")
    lines.append(f"**Evidence Mode:** EVIDENCE_MODE = {report.evidence_mode} — NOT_VALID_FOR_MR_ALPHA")
    lines.append("**Adapter:** Synthetic slow-state adapter (harness validation only)")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## Per-Arm Verdicts")
    lines.append("")
    lines.append("| Arm | Overall | M | P | C | B |")
    lines.append("|---|---|---|---|---|---|")
    for score in report.arm_scores:
        lines.append(
            f"| {score.arm.label} | **{score.overall}** | {score.mutation.result} | "
            f"{score.persistence.result} | {score.consumption.result} | "
            f"{score.behavioral_consequence.result} |"
        )
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## MUTATION")
    lines.append(f"**Result:** {report.mutation.result}")
    lines.append(f"**Evidence:** {report.mutation.evidence}")
    lines.append("")
    lines.append("## PERSISTENCE")
    lines.append(f"**Result:** {report.persistence.result}")
    lines.append(f"**Evidence:** {report.persistence.evidence}")
    lines.append("")
    lines.append("## CONSUMPTION")
    lines.append(f"**Result:** {report.consumption.result}")
    lines.append(f"**Evidence:** {report.consumption.evidence}")
    lines.append("")
    lines.append("## BEHAVIORAL CONSEQUENCE")
    lines.append(f"**Result:** {report.behavioral_consequence.result}")
    lines.append(f"**Evidence:** {report.behavioral_consequence.evidence}")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## ABLATIONS")
    lines.append("")
    lines.append("| Arm | State Changed | Persisted | Consumed | Behavior |")
    lines.append("|-----|-------------|-----------|----------|----------|")
    for arm, summary in report.ablation_summary.items():
        lines.append(f"| {arm.label} | {summary} | — | — | — |")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## SIGNAL DENSITY")
    lines.append(f"{report.signal_density:.4f}")
    if report.signal_density < report.protocol.score_criteria.min_signal_density_ratio:
        lines.append(
            "_WARNING: signal_density below threshold — plasticity may be "
            "behaviorally irrelevant in this corpus._"
        )
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## FAILURE BOUNDARY")
    if report.failure_boundary:
        lines.append(report.failure_boundary)
    else:
        lines.append("No failure boundary detected by automatic classification.")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## FINAL VERDICT")
    lines.append("")
    lines.append(f"**{report.final_verdict}**")
    lines.append("")
    lines.append("")
    if report.final_verdict == "READY_FOR_PRODUCTION_BINDING":
        lines.append("Completed: AS-00 … AS-08")
        lines.append("Blocked: AS-09 Production Adapter, AS-10 Whole-System Alpha")
        if report.external_dependency:
            lines.append("")
            lines.append(f"External dependency: {report.external_dependency}")
        lines.append("")
        lines.append("No production semantics were recreated.")
        lines.append("")
        lines.append("EVIDENCE_MODE = HARNESS_VALIDATION_ONLY — NOT_VALID_FOR_MR_ALPHA")
    return "\n".join(lines)


def write_report(report: AlphaReport, path: Path) -> Path:
    """Write the rendered Markdown to disk; return the final path."""
    final_path = path / f"{report.run_id}.md"
    final_path.write_text(render_markdown(report), encoding="utf-8")
    return final_path