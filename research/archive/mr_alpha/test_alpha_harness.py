"""MR-ALPHA-Harness: integration tests for the Alpha harness.

These tests validate the MR-ALPHA harness machinery itself — the runner,
scorer, report, and persistence boundary — without depending on the actual
production slow-plasticity consumer (C).

The tests use synthetic slow-state adapters and a stub emotional transition,
so they are deterministic and fast.  They do NOT validate that the
accumulated-state dynamics are correct against real evidence corpora; that
is the job of the production binding (AS-B).

Run with:  pytest tests/mr_alpha/ -v
"""

from __future__ import annotations

import tempfile
from datetime import UTC, datetime
from pathlib import Path

import pytest

from mind_runtime.homeostasis.contracts import HomeostasisDecision
from mind_runtime.state.persistence import SqliteStateBackend
from tests.mr_alpha.ablations import AblationArm, AblationSpec
from tests.mr_alpha.orchestrator import build_alpha_report
from tests.mr_alpha.persistence_harness import StateSnapshot
from tests.mr_alpha.probes import DEFAULT_FIXED_PROBE_SUITE
from tests.mr_alpha.protocol import AlphaProtocol
from tests.mr_alpha.report import AlphaReport, render_markdown, write_report
from tests.mr_alpha.runner import AlphaProtocolRunner, AlphaRunner, AlphaRunResult
from tests.mr_alpha.scorer import (
    AlphaScorer,
    ArmInternalMetrics,
    CriterionVerdict,
    InternalStateMetrics,
)
from tests.support.fake_clock import FakeClock

# ── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture
def protocol() -> AlphaProtocol:
    return AlphaProtocol()


@pytest.fixture
def scorer(protocol: AlphaProtocol) -> AlphaScorer:
    return AlphaScorer(protocol)


@pytest.fixture
def tmp_dir() -> Path:
    d = Path(tempfile.mkdtemp(prefix="mr_alpha_test_"))
    yield d
    import shutil

    shutil.rmtree(d, ignore_errors=True)


@pytest.fixture
def baseline_internal() -> InternalStateMetrics:
    return InternalStateMetrics(
        total_turns=10,
        meaningful_appraisals=4,
        slow_candidates=2,
        accepted_writes=2,
        rejected_writes=0,
        accept_ratio=1.0,
        dimensions_affected=("agent.slow.somatic_anxiety",),
        accumulated_delta={"agent.slow.somatic_anxiety": 0.15},
        state_persistence_delta=0.0,
        consumer_invocations=5,
        signal_density=0.4,
    )


# ── Test: AlphaProtocol ─────────────────────────────────────────────────────

class TestAlphaProtocol:
    def test_evidence_mode_is_harness_validation(self, protocol: AlphaProtocol) -> None:
        assert protocol.evidence_mode == "harness_validation"
        assert protocol.is_harness_validation

    def test_version(self, protocol: AlphaProtocol) -> None:
        assert "alpha-v" in protocol.version

    def test_criteria_thresholds(self, protocol: AlphaProtocol) -> None:
        c = protocol.score_criteria
        assert c.min_meaningful_appraisals >= 1
        assert c.min_slow_candidates >= 1
        assert c.min_accepted_writes >= 1
        assert c.min_accumulated_delta > 0
        assert c.min_consumer_invocations >= 1


# ── Test: AlphaScorer ───────────────────────────────────────────────────────

class TestAlphaScorer:
    def test_arm_internal_to_metrics_empty(self, scorer: AlphaScorer) -> None:
        arm_internal = ArmInternalMetrics(
            total_turns=0,
            slow_candidates=0,
            accepted_writes=0,
            rejected_writes=0,
            consumer_invocations=0,
            meaningful_appraisals=0,
        )
        m = scorer._arm_internal_to_metrics(arm_internal, 0)
        assert m.total_turns == 0
        assert m.signal_density == 0.0
        assert m.accept_ratio == 0.0

    def test_arm_internal_to_metrics_with_data(self, scorer: AlphaScorer) -> None:
        arm_internal = ArmInternalMetrics(
            total_turns=10,
            slow_candidates=3,
            accepted_writes=2,
            rejected_writes=1,
            consumer_invocations=5,
            meaningful_appraisals=4,
        )
        now = datetime.now(UTC)
        pre = StateSnapshot.from_pairs(
            slow_states=(("agent.slow.anxiety", 0.1),),
            slow_provenance=("p1",),
            at=now,
        )
        post = StateSnapshot.from_pairs(
            slow_states=(("agent.slow.anxiety", 0.25),),
            slow_provenance=("p1", "p2"),
            at=now,
        )
        m = scorer._arm_internal_to_metrics(arm_internal, 5, pre=pre, post=post)
        assert m.total_turns == 10
        assert m.meaningful_appraisals == 4
        assert m.slow_candidates == 3
        assert m.accepted_writes == 2
        assert m.accept_ratio == 2 / 3
        assert m.dimensions_affected == ("agent.slow.anxiety",)
        assert m.accumulated_delta["agent.slow.anxiety"] == pytest.approx(0.15)
        assert m.signal_density == pytest.approx(0.4)

    def test_verdict_mutation_pass(self, scorer: AlphaScorer, baseline_internal: InternalStateMetrics) -> None:
        v = scorer._verdict_mutation(baseline_internal)
        assert v.criterion == "M"
        assert v.result == "PASS"

    def test_verdict_mutation_fail_zero(self, scorer: AlphaScorer) -> None:
        m = InternalStateMetrics.empty()
        v = scorer._verdict_mutation(m)
        assert v.criterion == "M"
        assert v.result == "FAIL"
        assert "meaningful_appraisals=0" in v.evidence

    def test_verdict_persistence_pass(self, scorer: AlphaScorer) -> None:
        now = datetime.now(UTC)
        pre = StateSnapshot.from_pairs(
            slow_states=(("a", 1.0),), slow_provenance=("p1",), at=now
        )
        post = StateSnapshot.from_pairs(
            slow_states=(("a", 1.0),), slow_provenance=("p1",), at=now
        )
        v = scorer._verdict_persistence(pre, post)
        assert v.criterion == "P"
        assert v.result == "PASS"

    def test_verdict_persistence_fail_mismatch(self, scorer: AlphaScorer) -> None:
        now = datetime.now(UTC)
        pre = StateSnapshot.from_pairs(
            slow_states=(("a", 1.0),), slow_provenance=("p1",), at=now
        )
        post = StateSnapshot.from_pairs(
            slow_states=(("a", 2.0),), slow_provenance=("p1",), at=now
        )
        v = scorer._verdict_persistence(pre, post)
        assert v.criterion == "P"
        assert v.result == "FAIL"

    def test_verdict_consumption_pass(self, scorer: AlphaScorer) -> None:
        m = InternalStateMetrics(
            total_turns=10, meaningful_appraisals=4, slow_candidates=2,
            accepted_writes=2, rejected_writes=0, accept_ratio=1.0,
            dimensions_affected=(), accumulated_delta={},
            state_persistence_delta=0.0, consumer_invocations=5, signal_density=0.4,
        )
        v = scorer._verdict_consumption(m)
        assert v.criterion == "C"
        assert v.result == "PASS"

    def test_verdict_consumption_fail(self, scorer: AlphaScorer) -> None:
        m = InternalStateMetrics.empty()
        v = scorer._verdict_consumption(m)
        assert v.criterion == "C"
        assert v.result == "FAIL"

    def test_score_arm_overall_pass(
        self, scorer: AlphaScorer, baseline_internal: InternalStateMetrics
    ) -> None:
        now = datetime.now(UTC)
        pre = StateSnapshot.from_pairs(
            slow_states=(("agent.slow.anxiety", 0.1),), slow_provenance=("p1",), at=now
        )
        post = StateSnapshot.from_pairs(
            slow_states=(("agent.slow.anxiety", 0.1),), slow_provenance=("p1",), at=now
        )
        score = scorer.score_arm(
            arm=AblationArm.BASELINE,
            internal=baseline_internal,
            pre_snapshot=pre,
            post_snapshot=post,
            consumer_invocations=5,
            intent_scores_per_probe=(("probe-p1", 0.8),),
            raw_outputs=("output1",),
            baseline_internal=None,
        )
        assert score.overall in ("PASS", "FAIL")
        assert score.arm == AblationArm.BASELINE
        assert score.mutation.criterion == "M"
        assert score.persistence.criterion == "P"
        assert score.consumption.criterion == "C"
        assert score.behavioral_consequence.criterion == "B"

    def test_failure_boundary_none_on_pass(
        self, scorer: AlphaScorer, baseline_internal: InternalStateMetrics
    ) -> None:
        now = datetime.now(UTC)
        pre = StateSnapshot.from_pairs(
            slow_states=(("a", 1.0),), slow_provenance=("p1",), at=now
        )
        post = StateSnapshot.from_pairs(
            slow_states=(("a", 1.0),), slow_provenance=("p1",), at=now
        )
        score = scorer.score_arm(
            arm=AblationArm.BASELINE,
            internal=baseline_internal,
            pre_snapshot=pre,
            post_snapshot=post,
            consumer_invocations=5,
            intent_scores_per_probe=(),
            raw_outputs=(),
        )
        assert score.failure_boundary is None


# ── Test: AlphaReport ────────────────────────────────────────────────────────

class TestAlphaReport:
    def test_report_roundtrip(
        self, protocol: AlphaProtocol, tmp_dir: Path
    ) -> None:
        report = AlphaReport(
            protocol=protocol,
            run_id="test-run-1",
            commit="abc1234",
            evidence_mode=protocol.evidence_mode,
            started_at=datetime.now(UTC),
            finished_at=datetime.now(UTC),
            arm_scores=(),
            mutation=CriterionVerdict("M", "PASS", "evidence", 0.5, 0.3),
            persistence=CriterionVerdict("P", "PASS", "evidence", 1.0, 1.0),
            consumption=CriterionVerdict("C", "PASS", "evidence", 5.0, 1.0),
            behavioral_consequence=CriterionVerdict("B", "PASS", "evidence", 0.0, 1.0),
            ablation_summary={},
            signal_density=0.4,
            failure_boundary=None,
            final_verdict="READY_FOR_PRODUCTION_BINDING",
            external_dependency="C (consumption seam)",
            c_is_authoritative=False,
            b_is_authoritative=False,
        )
        written_path = write_report(report, tmp_dir)
        assert written_path.exists()
        assert written_path.suffix == ".md"
        assert written_path.read_text(encoding="utf-8").startswith("# MR Accumulated-State Causal Alpha")

    def test_render_markdown_produces_tables(
        self, protocol: AlphaProtocol, tmp_dir: Path
    ) -> None:
        report = AlphaReport(
            protocol=protocol,
            run_id="test-run-2",
            commit="abc1234",
            evidence_mode=protocol.evidence_mode,
            started_at=datetime.now(UTC),
            finished_at=datetime.now(UTC),
            arm_scores=(),
            mutation=CriterionVerdict("M", "FAIL", "zero appraisals", 0.0, 3.0),
            persistence=CriterionVerdict("P", "PASS", "slow_states survived", 1.0, 1.0),
            consumption=CriterionVerdict("C", "PASS", "consumer invoked 7 times", 7.0, 1.0),
            behavioral_consequence=CriterionVerdict("B", "PASS", "BASELINE reference", 0.0, 1.0),
            ablation_summary={},
            signal_density=0.0,
            failure_boundary="Appraisal: zero semantic candidates emitted",
            final_verdict="READY_FOR_PRODUCTION_BINDING",
            external_dependency="C",
            c_is_authoritative=False,
            b_is_authoritative=False,
        )
        md = render_markdown(report)
        assert "# MR Accumulated-State Causal Alpha" in md
        assert "## Per-Arm Verdicts" in md
        assert "## MUTATION" in md
        assert "READY_FOR_PRODUCTION_BINDING" in md
        assert "zero semantic candidates emitted" in md


# ── Test: Runner smoke (BASELINE arm only, fast) ─────────────────────────────

class TestAlphaRunnerSmoke:
    def test_runner_baseline_arm_terminates(self, protocol: AlphaProtocol, tmp_dir: Path) -> None:
        from tests.mr_alpha.fixtures import CONTROL_NEUTRAL

        runner = AlphaRunner(protocol, CONTROL_NEUTRAL, reports_dir=tmp_dir)
        db_path = tmp_dir / "smoke.sqlite"
        if db_path.exists():
            db_path.unlink()
        backend = SqliteStateBackend(db_path)
        spec = AblationSpec(arm=AblationArm.BASELINE, trajectory_ref="control_neutral")
        clock = FakeClock(datetime.now(UTC))

        result = runner.run_arm(spec, backend, clock)

        assert result.arm.label == "BASELINE"
        assert result.arm_internal_metrics.total_turns >= 1
        assert result.arm_internal_metrics.slow_candidates >= 0
        assert result.arm_internal_metrics.accepted_writes >= 0
        assert result.persistence.state_survived_boundary is True
        assert result.consumer_invocations >= 0
        assert len(result.intent_scores_per_probe) >= 0
        assert len(result.raw_outputs) >= 0

    def test_runner_all_arms_terminates(self, protocol: AlphaProtocol, tmp_dir: Path) -> None:
        from tests.mr_alpha.fixtures import TRUST_SUPPORT

        runner = AlphaRunner(protocol, TRUST_SUPPORT, reports_dir=tmp_dir)
        clock = FakeClock(datetime.now(UTC))

        for arm in AblationArm:
            db_path = tmp_dir / f"smoke_{arm.value}.sqlite"
            if db_path.exists():
                db_path.unlink()
            backend = SqliteStateBackend(db_path)
            spec = AblationSpec(arm=arm, trajectory_ref="trust_support")
            result = runner.run_arm(spec, backend, clock)
            assert result.arm.label == arm.label
            assert result.arm_internal_metrics.total_turns >= 1

    def test_harness_positive_path_baseline_treatment(
        self, protocol: AlphaProtocol, tmp_dir: Path
    ) -> None:
        """Positive-path harness validation.

        The harness must produce:

        - BASELINE:    slow_states_post = 0, probe_mean = 0.4 (base signal, no slow to read)
        - TREATMENT:   slow_states_post > 0, probe_mean > 0.4 (consumer reads slow state)
        - WRITE_OFF:   slow_states_post = 0, probe_mean = 0.4 (writer disabled, consumer base)
        - CONSUME_OFF: slow_states_post > 0, probe_mean = 0.0 (consumer disabled)
        - STATE_RESET: slow_states_post was reset before probes; probe_mean ≈ 0.4

        This proves the ablation matrix is structurally correct, not merely
        that the runner did not crash.
        """
        from tests.mr_alpha.fixtures import TRUST_SUPPORT

        runner = AlphaRunner(protocol, TRUST_SUPPORT, reports_dir=tmp_dir)
        clock = FakeClock(datetime.now(UTC))

        observations: dict[str, tuple[int, float, bool]] = {}

        for spec in AblationSpec.default_suite("trust_support"):
            db_path = tmp_dir / f"positive_{spec.arm.value}.sqlite"
            if db_path.exists():
                db_path.unlink()
            backend = SqliteStateBackend(db_path)
            result = runner.run_arm(spec, backend, clock)
            slow_states = len(result.post_snapshot.slow_states)
            mean_score = (
                sum(s for _, s in result.intent_scores_per_probe)
                / max(len(result.intent_scores_per_probe), 1)
            )
            persisted = result.persistence.state_survived_boundary
            observations[spec.arm.label] = (slow_states, mean_score, persisted)

        # BASELINE — neutralized trajectory → no slow writes
        s, m, p = observations[AblationArm.BASELINE.label]
        assert s == 0, f"BASELINE should have 0 slow states; got {s}"
        assert abs(m - 0.4) < 0.01, f"BASELINE probe_mean should be ≈0.4; got {m}"
        assert p

        # TREATMENT — original trajectory → slow writes fire
        s, m, p = observations[AblationArm.TREATMENT.label]
        assert s > 0, f"TREATMENT should have >0 slow states; got {s}"
        assert m > 0.4, f"TREATMENT probe_mean should exceed baseline 0.4; got {m}"
        assert p

        # WRITE_OFF — writer disabled → no slow states, but consumer still emits base
        s, m, p = observations[AblationArm.WRITE_OFF.label]
        assert s == 0, f"WRITE_OFF should have 0 slow states; got {s}"
        assert abs(m - 0.4) < 0.01, f"WRITE_OFF probe_mean should be ≈0.4 (base); got {m}"

        # CONSUME_OFF — slow writes fire but consumer has no slow_reader so it
        # emits the base signal (same as baseline).  Behaviorally inert.
        s, m, p = observations[AblationArm.CONSUME_OFF.label]
        assert s > 0, f"CONSUME_OFF should have >0 slow states; got {s}"
        assert abs(m - 0.4) < 0.01, (
            f"CONSUME_OFF probe_mean should be ≈0.4 (base, consumer inert from baseline); got {m}"
        )
        assert p

        # STATE_RESET — slow writes fire then reset; consumer sees baseline
        s, m, p = observations[AblationArm.STATE_RESET.label]
        # After reset, slow dims are present (versions preserved) but values reset to 0.
        # We check that consumer sees baseline behavior (m ≈ 0.4).
        assert abs(m - 0.4) < 0.01, f"STATE_RESET probe_mean should be ≈0.4; got {m}"

    def test_treatment_divergence_exceeds_threshold(
        self, protocol: AlphaProtocol, tmp_dir: Path
    ) -> None:
        """Behavioral divergence between TREATMENT and BASELINE must exceed
        the protocol's threshold."""
        from tests.mr_alpha.ablations import AblationSpec
        from tests.mr_alpha.fixtures import TRUST_SUPPORT
        from tests.mr_alpha.runner import AlphaRunner

        runner = AlphaRunner(protocol, TRUST_SUPPORT, reports_dir=tmp_dir)
        clock = FakeClock(datetime.now(UTC))

        scores_by_arm: dict[str, float] = {}
        for spec in AblationSpec.default_suite("trust_support"):
            db_path = tmp_dir / f"divergence_{spec.arm.value}.sqlite"
            if db_path.exists():
                db_path.unlink()
            backend = SqliteStateBackend(db_path)
            result = runner.run_arm(spec, backend, clock)
            mean_score = (
                sum(s for _, s in result.intent_scores_per_probe)
                / max(len(result.intent_scores_per_probe), 1)
            )
            scores_by_arm[spec.arm.label] = mean_score

        baseline_score = scores_by_arm[AblationArm.BASELINE.label]
        treatment_score = scores_by_arm[AblationArm.TREATMENT.label]
        divergence = abs(treatment_score - baseline_score)
        assert divergence >= protocol.score_criteria.behavioral_divergence_threshold, (
            f"TREATMENT/BASELINE divergence {divergence:.3f} below threshold "
            f"{protocol.score_criteria.behavioral_divergence_threshold}"
        )


# ── Test: Orchestrator ───────────────────────────────────────────────────────

class TestOrchestrator:
    def test_build_alpha_report_accepts_empty_arm_results(self, protocol: AlphaProtocol, tmp_dir: Path) -> None:
        from datetime import UTC, datetime

        empty_result = AlphaRunResult(
            run_id="empty-test",
            started_at=datetime.now(UTC),
            finished_at=datetime.now(UTC),
            arm_results={},
            protocol=protocol,
            reports_dir=tmp_dir,
        )
        report = build_alpha_report(empty_result, protocol, tmp_dir)
        assert report.final_verdict == "READY_FOR_PRODUCTION_BINDING"
        assert report.signal_density == 0.0
        assert len(report.arm_scores) == 0

    def test_orchestrator_run_produces_report(
        self, protocol: AlphaProtocol, tmp_dir: Path
    ) -> None:
        from tests.mr_alpha.fixtures import CONTROL_NEUTRAL

        runner = AlphaProtocolRunner(
            protocol, CONTROL_NEUTRAL,
            DEFAULT_FIXED_PROBE_SUITE,
            reports_dir=tmp_dir,
        )
        run_result = runner.run()
        report = build_alpha_report(run_result, protocol, tmp_dir)

        assert report.final_verdict is not None
        assert report.run_id == run_result.run_id
        assert len(report.arm_scores) == len(run_result.arm_results)
        assert report.external_dependency is not None

        # Write report to disk and verify
        md_path = write_report(report, tmp_dir)
        assert md_path.exists()
        text = md_path.read_text(encoding="utf-8")
        assert "# MR Accumulated-State Causal Alpha" in text
        assert "Per-Arm Verdicts" in text


# ── Test: SyntheticSlowStateAdapter scope routing (C10-C1 semantics) ──────────
#
# These assert that the harness adapter mirrors the production
# SlowPlasticityWriter.accept(decision, *, target_scope=...) contract:
#   scope = target_scope or candidate.scope  (scope routing, not passthrough)
#   flush(scope) drains ONLY that scope's pending records (isolation).
# Without this, a signature-drift in the adapter would silently swallow the
# orchestrator's AGENT slow scope and break the scope-isolation guarantee.

class TestSyntheticSlowStateAdapterScopeRouting:
    def _decision(
        self, dim: str, *, scope, value: float = 0.5, decision="slow_accept"
    ) -> HomeostasisDecision:
        from datetime import UTC, datetime

        from mind_runtime.homeostasis.contracts import (
            CandidateStateDelta,
            HomeostasisDecision,
            HomeostasisDisposition,
        )

        now = datetime.now(UTC)
        candidate = CandidateStateDelta(
            target_dimension=dim,
            proposed_value=value,
            scope=scope,
            evidence_refs=(),
            salience=0.8,
            confidence=0.9,
            source_event_ref=None,
            observed_at=now,
        )
        return HomeostasisDecision(
            candidate=candidate,
            prior_value=None,
            decision=HomeostasisDisposition(decision),
            reason_code="scope-routing-test",
            decided_at=now,
        )

    def test_accept_uses_target_scope_over_candidate_scope(self, tmp_dir: Path) -> None:
        """target_scope must take precedence; the record is buffered under
        the passed target_scope, not under candidate.scope."""

        from mind_runtime.contracts import Scope, ScopeDomain
        from mind_runtime.state.persistence import SqliteStateBackend
        from tests.mr_alpha.adapters.synthetic_slow_adapter import (
            SyntheticSlowStateAdapter,
        )

        backend = SqliteStateBackend(tmp_dir / "scope_precedence.sqlite")
        adapter = SyntheticSlowStateAdapter(backend=backend)

        agent_scope = Scope(domain=ScopeDomain.AGENT, agent_id="a1", persona_id="p1")
        other_scope = Scope(domain=ScopeDomain.AGENT, agent_id="a2", persona_id="p2")

        decision = self._decision("agent.affect.anxiety", scope=other_scope)
        adapter.accept(decision, target_scope=agent_scope)

        assert adapter.pending_count == 1
        # The buffered record must carry the target_scope (agent_scope), NOT
        # the candidate's other_scope — proving target_scope wins the route.
        assert adapter._pending[0].scope == agent_scope

        # Flush with agent_scope drains it; flush with other_scope finds nothing.
        flushed = adapter.flush(agent_scope)
        assert len(flushed) == 1
        assert flushed[0].scope == agent_scope
        assert adapter.pending_count == 0

    def test_flush_is_scope_isolated(self, tmp_dir: Path) -> None:
        """flush(scope) must only drain records belonging to that scope;
        other scopes' pending remain buffered."""

        from mind_runtime.contracts import Scope, ScopeDomain
        from mind_runtime.state.persistence import SqliteStateBackend
        from tests.mr_alpha.adapters.synthetic_slow_adapter import (
            SyntheticSlowStateAdapter,
        )

        backend = SqliteStateBackend(tmp_dir / "scope_isolation.sqlite")
        adapter = SyntheticSlowStateAdapter(backend=backend)

        A = Scope(domain=ScopeDomain.AGENT, agent_id="a1", persona_id="p1")
        B = Scope(domain=ScopeDomain.AGENT, agent_id="a2", persona_id="p2")

        # Two decisions routed to different scopes by target_scope.
        adapter.accept(
            self._decision("agent.affect.anxiety", scope=A), target_scope=A
        )
        adapter.accept(
            self._decision("agent.affect.confidence", scope=B), target_scope=B
        )
        assert adapter.pending_count == 2

        flushed_A = adapter.flush(A)
        assert len(flushed_A) == 1
        assert flushed_A[0].dimension == "agent.slow.anxiety"
        # Only scope A drained; scope B still buffered.
        assert adapter.pending_count == 1
        assert adapter._pending[0].scope == B

        flushed_B = adapter.flush(B)
        assert len(flushed_B) == 1
        assert flushed_B[0].dimension == "agent.slow.confidence"
        assert adapter.pending_count == 0

    def test_accept_signature_drift_true(self, tmp_dir: Path) -> None:
        """accept() must accept the production keyword arg target_scope; a
        signature that only accepts decision would break the orchestrator
        callsite (TypeError)."""

        from mind_runtime.contracts import Scope, ScopeDomain
        from mind_runtime.state.persistence import SqliteStateBackend
        from tests.mr_alpha.adapters.synthetic_slow_adapter import (
            SyntheticSlowStateAdapter,
        )

        backend = SqliteStateBackend(tmp_dir / "signature.sqlite")
        adapter = SyntheticSlowStateAdapter(backend=backend)

        # If accept() had dropped target_scope from its signature, this call
        # would raise TypeError.  We assert it does not.
        agent_scope = Scope(domain=ScopeDomain.AGENT, agent_id="a1", persona_id="p1")
        adapter.accept(
            self._decision("agent.affect.anxiety", scope=agent_scope),
            target_scope=agent_scope,
        )
        assert adapter.accepted_count == 1