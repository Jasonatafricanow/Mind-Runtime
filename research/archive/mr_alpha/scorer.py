"""MR-ALPHA-AS1: Alpha Scorer — AS-07.

Two-layer scoring:

  1. Deterministic internal-state metrics (turn count, slow candidates,
     accepted writes, accumulated delta, persistence delta, consumer
     invocations, signal density).

  2. Behavioral metrics (raw outputs, intent scores per probe, behavioral
     divergence across arms).

A per-arm verdict (M/P/C/B) is computed against the frozen
``AlphaScoreCriteria`` from AS-00.  The overall verdict is the conjunction
of M/P/C/B (PASS only if all four pass; otherwise FAIL; or BLOCKED if
required topology is missing).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, UTC
from typing import Literal, Mapping

from tests.mr_alpha.ablations import AblationArm
from tests.mr_alpha.causal_trace import CausalStepKind, CausalTrace
from tests.mr_alpha.persistence_harness import PersistenceBoundaryResult, StateSnapshot
from tests.mr_alpha.protocol import AlphaProtocol, AlphaScoreCriteria

__all__ = [
    "AlphaScorer",
    "ArmScore",
    "InternalStateMetrics",
    "BehavioralMetrics",
    "CriterionVerdict",
    "Verdict",
    "ArmInternalMetrics",
]

Verdict = Literal["PASS", "FAIL", "BLOCKED"]


@dataclass(frozen=True)
class ArmInternalMetrics:
    """Lightweight internal metrics captured by the runner per arm."""

    total_turns: int
    slow_candidates: int
    accepted_writes: int
    rejected_writes: int
    consumer_invocations: int
    meaningful_appraisals: int


@dataclass(frozen=True)
class InternalStateMetrics:
    """Deterministic internal-state observations from one arm."""

    total_turns: int
    meaningful_appraisals: int
    slow_candidates: int
    accepted_writes: int
    rejected_writes: int
    accept_ratio: float
    dimensions_affected: tuple[str, ...]
    accumulated_delta: Mapping[str, float]
    state_persistence_delta: float
    consumer_invocations: int
    signal_density: float  # meaningful_appraisals / total_turns
    # Absolute post-snapshot slow values (harness mode uses these for
    # mutation criterion; pre-vs-post diff is 0 because trajectory
    # already wrote before pre-snapshot).
    post_slow_values: Mapping[str, float] = field(default_factory=dict)
    # Mean intent score across probes — the behavioral signal that the
    # consumer emits.  Used for B criterion divergence computation.
    behavioral_signal: float = 0.0

    @staticmethod
    def empty() -> "InternalStateMetrics":
        return InternalStateMetrics(
            total_turns=0,
            meaningful_appraisals=0,
            slow_candidates=0,
            accepted_writes=0,
            rejected_writes=0,
            accept_ratio=0.0,
            dimensions_affected=(),
            accumulated_delta={},
            state_persistence_delta=0.0,
            consumer_invocations=0,
            signal_density=0.0,
            post_slow_values={},
            behavioral_signal=0.0,
        )


@dataclass(frozen=True)
class BehavioralMetrics:
    """Behavioral observations from one arm."""

    raw_outputs: tuple[str, ...]
    intent_scores_per_probe: tuple[tuple[str, float], ...]
    behavioral_divergence_vs_baseline: float
    consumer_delta_vs_baseline: float


@dataclass(frozen=True)
class CriterionVerdict:
    """One M / P / C / B verdict with evidence and metrics."""

    criterion: Literal["M", "P", "C", "B"]
    result: Verdict
    evidence: str
    value: float
    threshold: float


@dataclass(frozen=True)
class ArmScore:
    """Score for one arm of the protocol."""

    arm: AblationArm
    internal: InternalStateMetrics
    behavioral: BehavioralMetrics

    mutation: CriterionVerdict
    persistence: CriterionVerdict
    consumption: CriterionVerdict
    behavioral_consequence: CriterionVerdict

    overall: Verdict

    failure_boundary: str | None = None
    ablation_notes: tuple[str, ...] = ()


# ── Scorer ───────────────────────────────────────────────────────────────────


class AlphaScorer:
    """Compute per-arm verdicts from internal-state + behavioral evidence."""

    def __init__(self, protocol: AlphaProtocol) -> None:
        self._protocol = protocol

    @property
    def criteria(self) -> AlphaScoreCriteria:
        return self._protocol.score_criteria

    def _with_behavioral_signal(
        self, metrics: InternalStateMetrics, signal: float
    ) -> InternalStateMetrics:
        """Return a copy of `metrics` with the behavioral_signal updated."""
        return InternalStateMetrics(
            total_turns=metrics.total_turns,
            meaningful_appraisals=metrics.meaningful_appraisals,
            slow_candidates=metrics.slow_candidates,
            accepted_writes=metrics.accepted_writes,
            rejected_writes=metrics.rejected_writes,
            accept_ratio=metrics.accept_ratio,
            dimensions_affected=metrics.dimensions_affected,
            accumulated_delta=metrics.accumulated_delta,
            state_persistence_delta=metrics.state_persistence_delta,
            consumer_invocations=metrics.consumer_invocations,
            signal_density=metrics.signal_density,
            post_slow_values=metrics.post_slow_values,
            behavioral_signal=signal,
        )

    # ── Arm-internal → InternalStateMetrics ──────────────────────────────────
    def _arm_internal_to_metrics(
        self,
        arm_internal: ArmInternalMetrics,
        consumer_invocations: int,
        pre: StateSnapshot | None = None,
        post: StateSnapshot | None = None,
    ) -> InternalStateMetrics:
        total = max(arm_internal.total_turns, 1)
        signal_density = arm_internal.meaningful_appraisals / total
        total_decisions = arm_internal.accepted_writes + arm_internal.rejected_writes
        accept_ratio = (
            arm_internal.accepted_writes / total_decisions
            if total_decisions > 0
            else 0.0
        )

        if pre is not None and post is not None:
            pre_slow = dict(pre.slow_states)
            post_slow = dict(post.slow_states)
            all_dims = set(pre_slow) | set(post_slow)
            accumulated_delta = {
                d: post_slow.get(d, 0.0) - pre_slow.get(d, 0.0) for d in all_dims
            }
            persistence_delta = (
                max((abs(post_slow.get(d, 0.0) - pre_slow.get(d, 0.0)) for d in all_dims), default=0.0)
                if all_dims
                else 0.0
            )
            dims_affected = tuple(sorted(d for d, v in accumulated_delta.items() if v != 0.0))
            # Also expose post-snapshot absolute values for the mutation criterion
            # (the pre-vs-post diff is 0 for harness mode since trajectory already
            # wrote state before the pre-snapshot).  Mutation is the absolute
            # accumulated value, not the diff.
            post_slow_values = dict(post_slow)
        else:
            accumulated_delta = {}
            persistence_delta = 0.0
            dims_affected = ()
            post_slow_values = {}

        return InternalStateMetrics(
            total_turns=arm_internal.total_turns,
            meaningful_appraisals=arm_internal.meaningful_appraisals,
            slow_candidates=arm_internal.slow_candidates,
            accepted_writes=arm_internal.accepted_writes,
            rejected_writes=arm_internal.rejected_writes,
            accept_ratio=accept_ratio,
            dimensions_affected=dims_affected,
            accumulated_delta=dict(accumulated_delta),
            state_persistence_delta=persistence_delta,
            consumer_invocations=consumer_invocations,
            signal_density=signal_density,
            # Absolute post-snapshot values for mutation scoring (harness mode).
            post_slow_values=post_slow_values,
        )

    # ── Top-level entry ──────────────────────────────────────────────────────
    def score_arm(
        self,
        arm: AblationArm,
        internal: InternalStateMetrics,
        pre_snapshot: StateSnapshot,
        post_snapshot: StateSnapshot,
        consumer_invocations: int,
        intent_scores_per_probe: tuple[tuple[str, float], ...],
        raw_outputs: tuple[str, ...],
        *,
        baseline_internal: InternalStateMetrics | None = None,
    ) -> ArmScore:
        behavioral = self._compute_behavioral_metrics(
            intent_scores_per_probe, raw_outputs, baseline_internal, internal
        )

        mutation = self._verdict_mutation(internal)
        persistence = self._verdict_persistence(pre_snapshot, post_snapshot)
        consumption = self._verdict_consumption(internal)
        beh = self._verdict_behavior(behavioral, internal, arm)

        verdicts = [mutation, persistence, consumption, beh]
        if any(v.result == "FAIL" for v in verdicts):
            overall: Verdict = "FAIL"
        elif all(v.result == "PASS" for v in verdicts):
            overall = "PASS"
        else:
            overall = "BLOCKED"

        failure_boundary = self._detect_failure_boundary(
            internal, mutation, persistence, consumption, beh
        )

        return ArmScore(
            arm=arm,
            internal=internal,
            behavioral=behavioral,
            mutation=mutation,
            persistence=persistence,
            consumption=consumption,
            behavioral_consequence=beh,
            overall=overall,
            failure_boundary=failure_boundary,
        )

    # ── Behavioral metrics ──────────────────────────────────────────────────
    def _compute_behavioral_metrics(
        self,
        intent_scores: tuple[tuple[str, float], ...],
        raw_outputs: tuple[str, ...],
        baseline_internal: InternalStateMetrics | None,
        arm_internal: InternalStateMetrics,
    ) -> BehavioralMetrics:
        # Behavioral divergence is measured by intent-score divergence, NOT
        # by slow-state-value divergence.  The slow-state divergence is judged
        # separately by the M criterion; B measures whether the consumer
        # actually changed its behavior.
        if baseline_internal is None:
            divergence = 0.0
            consumer_delta = 0.0
        else:
            divergence = abs(
                arm_internal.behavioral_signal - baseline_internal.behavioral_signal
            )
            consumer_delta = (
                arm_internal.consumer_invocations - baseline_internal.consumer_invocations
            )
        return BehavioralMetrics(
            raw_outputs=raw_outputs,
            intent_scores_per_probe=intent_scores,
            behavioral_divergence_vs_baseline=divergence,
            consumer_delta_vs_baseline=float(consumer_delta),
        )

    # ── Per-criterion verdicts ──────────────────────────────────────────────
    def _verdict_mutation(self, internal: InternalStateMetrics) -> CriterionVerdict:
        c = self.criteria
        # In harness mode the absolute post-snapshot values are the actual
        # mutation signal (the trajectory already wrote before pre-snapshot,
        # so pre-vs-post diff is 0).  Use those directly.
        max_delta = max((abs(v) for v in internal.post_slow_values.values()), default=0.0)
        if max_delta == 0.0:
            # Fall back to accumulated_delta for the legacy pre-vs-post diff
            max_delta = max((abs(v) for v in internal.accumulated_delta.values()), default=0.0)
        passed = (
            internal.meaningful_appraisals >= c.min_meaningful_appraisals
            and internal.slow_candidates >= c.min_slow_candidates
            and internal.accepted_writes >= c.min_accepted_writes
            and max_delta >= c.min_accumulated_delta
        )
        return CriterionVerdict(
            criterion="M",
            result="PASS" if passed else "FAIL",
            evidence=(
                f"meaningful_appraisals={internal.meaningful_appraisals} "
                f"(≥{c.min_meaningful_appraisals}), "
                f"slow_candidates={internal.slow_candidates} (≥{c.min_slow_candidates}), "
                f"accepted_writes={internal.accepted_writes} (≥{c.min_accepted_writes}), "
                f"max_post_slow_value={max_delta:.4f} (≥{c.min_accumulated_delta})"
            ),
            value=max_delta,
            threshold=c.min_accumulated_delta,
        )

    def _verdict_persistence(
        self, pre: StateSnapshot, post: StateSnapshot
    ) -> CriterionVerdict:
        c = self.criteria
        survived = pre.slow_states == post.slow_states
        identity_ok = set(pre.slow_provenance) <= set(post.slow_provenance)
        passed = c.state_survives_boundary and survived and identity_ok
        evidence_parts = []
        if c.state_survives_boundary:
            evidence_parts.append(f"slow_state_survived={'yes' if survived else 'no'}")
        if c.provenance_preserved:
            evidence_parts.append(f"provenance_preserved={'yes' if identity_ok else 'no'}")
        return CriterionVerdict(
            criterion="P",
            result="PASS" if passed else "FAIL",
            evidence="; ".join(evidence_parts) or "no criteria configured",
            value=1.0 if passed else 0.0,
            threshold=1.0,
        )

    def _verdict_consumption(self, internal: InternalStateMetrics) -> CriterionVerdict:
        c = self.criteria
        passed = internal.consumer_invocations >= c.min_consumer_invocations
        return CriterionVerdict(
            criterion="C",
            result="PASS" if passed else "FAIL",
            evidence=(
                f"consumer_invocations={internal.consumer_invocations} "
                f"(≥{c.min_consumer_invocations})"
            ),
            value=float(internal.consumer_invocations),
            threshold=float(c.min_consumer_invocations),
        )

    def _verdict_behavior(
        self,
        behavioral: BehavioralMetrics,
        internal: InternalStateMetrics,
        arm: AblationArm,
    ) -> CriterionVerdict:
        c = self.criteria
        if arm is AblationArm.TREATMENT:
            passed = behavioral.behavioral_divergence_vs_baseline >= c.behavioral_divergence_threshold
            return CriterionVerdict(
                criterion="B",
                result="PASS" if passed else "FAIL",
                evidence=(
                    f"TREATMENT behavioral_divergence={behavioral.behavioral_divergence_vs_baseline:.4f} "
                    f"(≥{c.behavioral_divergence_threshold})"
                ),
                value=behavioral.behavioral_divergence_vs_baseline,
                threshold=c.behavioral_divergence_threshold,
            )
        if arm in (AblationArm.WRITE_OFF, AblationArm.CONSUME_OFF, AblationArm.STATE_RESET):
            passed = behavioral.behavioral_divergence_vs_baseline < c.behavioral_divergence_threshold
            return CriterionVerdict(
                criterion="B",
                result="PASS" if passed else "FAIL",
                evidence=(
                    f"{arm.label} behavioral_divergence={behavioral.behavioral_divergence_vs_baseline:.4f} "
                    f"(<{c.behavioral_divergence_threshold}; ablation is behaviorally inert)"
                ),
                value=behavioral.behavioral_divergence_vs_baseline,
                threshold=c.behavioral_divergence_threshold,
            )
        return CriterionVerdict(
            criterion="B",
            result="PASS",
            evidence=(
                f"BASELINE behavioral_divergence={behavioral.behavioral_divergence_vs_baseline:.4f} (reference)"
            ),
            value=behavioral.behavioral_divergence_vs_baseline,
            threshold=c.behavioral_divergence_threshold,
        )

    # ── Failure boundary classification ────────────────────────────────────
    def _detect_failure_boundary(
        self,
        internal: InternalStateMetrics,
        mutation: CriterionVerdict,
        persistence: CriterionVerdict,
        consumption: CriterionVerdict,
        behavioral: CriterionVerdict,
    ) -> str | None:
        if mutation.result != "FAIL":
            return None
        if internal.meaningful_appraisals == 0:
            return (
                "Appraisal: zero semantic candidates emitted — "
                "SemanticRouter abstained or evidence had no typed_event kind."
            )
        if internal.slow_candidates == 0:
            return (
                "Homeostasis: appraisal produced candidates but no "
                "HomeostasisDecision candidates surfaced (H6 evidence-refs "
                "bridge or salience threshold rejected)."
            )
        if internal.accepted_writes == 0:
            return (
                "Slow write: candidates existed but no SLOW_ACCEPT — "
                "gate disposition never crossed acceptance threshold."
            )
        return (
            f"Mutation: accumulated_delta={max(internal.accumulated_delta.values(), default=0.0):.4f} "
            "did not exceed threshold despite accepted writes."
        )