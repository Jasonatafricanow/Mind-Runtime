"""Golden adapters backed by real D11S canonical certifications."""

import shutil
import subprocess
from pathlib import Path

from mind_runtime.pipeline.fake_agent import FakeAgent
from mind_runtime.validation import (
    CertificationPlan,
    DurablePaths,
    audit_repeated_history,
    certify_horizon,
    certify_restart,
    compare_model_swap,
    decode_runtime_config_manifest_bytes,
    load_history_fixture,
    load_horizon_template,
    load_model_swap_fixture,
    load_restart_fixture,
    sha256_bytes,
    verify_fixture_artifacts,
)
from tests.golden.scenario import GoldenScenario, ScenarioResult

ROOT = Path(__file__).parents[2]
INPUTS = ROOT / "certification/d11s/inputs"


def _source_head() -> str:
    return subprocess.run(
        ["git", "rev-parse", "--verify", "HEAD"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _plan_from_template(horizon_days: int) -> CertificationPlan:
    template = load_horizon_template(INPUTS / f"horizon-{horizon_days}.json")
    manifest_path = INPUTS / "runtime-config.json"
    return CertificationPlan(
        certification_id=template.certification_id,
        source_head=_source_head(),
        persona_version=template.persona_version,
        runtime_config_manifest_sha256=sha256_bytes(manifest_path.read_bytes()),
        horizon_days=template.horizon_days,
        started_at=template.started_at,
        events=template.events,
        checkpoint_interval=template.checkpoint_interval,
    )


class D11SLongHorizonPipeline:
    """Run G26 through the verified 90-day canonical horizon twice."""

    def run(self, scenario: GoldenScenario) -> ScenarioResult:
        if scenario.golden_id != "G26":
            raise ValueError(f"unsupported D11S long-horizon Golden {scenario.golden_id}")
        plan = _plan_from_template(90)
        # Durable roots live under the repository working tree (the platform
        # temp area may be read-only under sandboxed runs); `pt*` is
        # gitignored. The empty-root contract of certify_horizon still holds.
        directory = ROOT / f"pt-d11s-g26-{id(self)}"
        try:
            certification = certify_horizon(plan, root=directory, repository_root=ROOT)
        finally:
            shutil.rmtree(directory, ignore_errors=True)
        by_code = {result.code: result for result in certification.invariants}
        outputs: tuple[tuple[str, object], ...] = (
            ("horizon.days", certification.virtual_horizon_days),
            (
                "affect.within_bounds",
                "true" if by_code["state.boundedness"].passed else "false",
            ),
            (
                "recovery.replayable",
                "true" if by_code["replay.semantic_records"].passed else "false",
            ),
            (
                "self_excitation.unbounded",
                "false" if by_code["history.no_self_excitation"].passed else "true",
            ),
        )
        return ScenarioResult(
            golden_id=scenario.golden_id,
            deterministic_outputs=outputs,
            canonical_changes=(),
            projected_changes=(),
            llm_calls=(),
        )


class D11SModelSwapPipeline:
    """Run G25 through the real paired expression-provider swap."""

    def run(self, scenario: GoldenScenario) -> ScenarioResult:
        if scenario.golden_id != "G25":
            raise ValueError(f"unsupported D11S model-swap Golden {scenario.golden_id}")
        plan = _plan_from_template(30)
        left = FakeAgent(load_model_swap_fixture(INPUTS / "model-swap-left.json").responses)
        right = FakeAgent(load_model_swap_fixture(INPUTS / "model-swap-right.json").responses)
        directory = ROOT / f"pt-d11s-g25-{id(self)}"
        try:
            result = compare_model_swap(
                left,
                right,
                plan,
                root=directory,
                repository_root=ROOT,
            )
        finally:
            shutil.rmtree(directory, ignore_errors=True)
        outputs: tuple[tuple[str, object], ...] = (
            (
                "model_swap.internal_transition",
                "same" if result.internal_transition_same else "different",
            ),
            ("model_swap.intent", "same" if result.intent_same else "different"),
            ("model_swap.policy", "same" if result.policy_same else "different"),
            (
                "model_swap.expression",
                "may_differ" if result.expressions_differ else "same",
            ),
        )
        return ScenarioResult(
            golden_id=scenario.golden_id,
            deterministic_outputs=outputs,
            canonical_changes=(),
            projected_changes=(),
            llm_calls=(),
        )


class D11SHistoryPipeline:
    """Run G27 through the real history anti-amplification audit."""

    def run(self, scenario: GoldenScenario) -> ScenarioResult:
        if scenario.golden_id != "G27":
            raise ValueError(f"unsupported D11S history Golden {scenario.golden_id}")
        fixture = load_history_fixture(INPUTS / "history-g27.json")
        directory = ROOT / f"pt-d11s-g27-{id(self)}"
        try:
            result = audit_repeated_history(
                fixture.bundle.episodes[0],
                fixture.bundle.pattern_summaries[0],
                retrievals=fixture.retrieval_count,
                root=directory,
                repository_root=ROOT,
            )
        finally:
            shutil.rmtree(directory, ignore_errors=True)
        outputs: tuple[tuple[str, object], ...] = (
            ("history.unique_source_count", result.unique_source_count),
            ("history.retrieval_count", result.retrieval_count),
            ("history.influence_multiplier", result.influence_multiplier),
            ("history.reinforced", "true" if result.reinforced else "false"),
        )
        return ScenarioResult(
            golden_id=scenario.golden_id,
            deterministic_outputs=outputs,
            canonical_changes=(),
            projected_changes=(),
            llm_calls=(),
        )


class D11SRestartPipeline:
    """Run corrected G12 through the real fresh-composition restart audit."""

    def run(self, scenario: GoldenScenario) -> ScenarioResult:
        if scenario.golden_id != "G12":
            raise ValueError(f"unsupported D11S restart Golden {scenario.golden_id}")
        manifest = decode_runtime_config_manifest_bytes(
            (INPUTS / "runtime-config.json").read_bytes()
        )
        verify_fixture_artifacts(manifest, ROOT)
        fixture = load_restart_fixture(INPUTS / "restart-g12.json")
        directory = ROOT / f"pt-d11s-g12-{id(self)}"
        try:
            result = certify_restart(
                fixture,
                DurablePaths.under(directory),
                repository_root=ROOT,
            )
        finally:
            shutil.rmtree(directory, ignore_errors=True)
        consistent = (
            result.fact_digest_before == result.fact_digest_after
            and result.state_digest_before == result.state_digest_after
            and result.intent_digest_before == result.intent_digest_after
            and result.checkpoint_digest_before == result.checkpoint_digest_after
            and result.recovery_decision_before == result.recovery_decision_after
            and result.history_hash_before == result.history_hash_after
        )
        return ScenarioResult(
            golden_id=scenario.golden_id,
            deterministic_outputs=(("restart.consistent", "true" if consistent else "false"),),
            canonical_changes=(),
            projected_changes=(),
            llm_calls=(),
        )
