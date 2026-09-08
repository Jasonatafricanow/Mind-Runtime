"""G13b/G16b golden scenario fixtures (D2.5)."""

from datetime import UTC, datetime

from mind_runtime.contracts import AppraisalPath, Scope, ScopeDomain
from tests.golden.fixtures.common import (
    make_clock,
    make_evidence,
    make_persona,
    make_scope,
    make_state,
)
from tests.golden.scenario import ExpectedChange, GoldenScenario


def make_g13b() -> GoldenScenario:
    """G13b Factual Commit 必须在 Cognitive Abort 后保留."""
    clock = make_clock(now=datetime(2026, 8, 20, 2, 30, tzinfo=UTC))
    user_scope = make_scope()
    agent_scope = Scope(domain=ScopeDomain.AGENT, agent_id="agent-1", persona_id="persona-1")
    return GoldenScenario(
        golden_id="G13b",
        title="Factual Commit 必须在 Cognitive Abort 后保留",
        owner="MR-D5 not implemented",
        clock=clock,
        runtime_id="runtime-1",
        scope=user_scope,
        persona=(make_persona(),),
        initial_canonical_state=(
            make_state(
                dimension="user.sleep.phase",
                value="sleeping",
                scope=user_scope,
            ),
            make_state(
                dimension="agent.affect.longing",
                value=0.42,
                scope=agent_scope,
            ),
        ),
        historical_context=None,
        input_evidence=(make_evidence(text="我刚睡醒", occurred_at=clock.now()),),
        expected_deterministic_outputs=(
            ("user.sleep.phase", "awake"),
            ("evidence.retained", "true"),
            ("observation.retained", "true"),
            ("abort.projected_affect", "discarded"),
            ("canonical.agent.affect.longing", 0.42),
        ),
        expected_allowed_llm_path=None,
        expected_canonical_changes=(ExpectedChange("user.sleep.phase", "awake"),),
        expected_projected_changes=(ExpectedChange("agent.affect.longing", "aborted"),),
    )


def make_g16b() -> GoldenScenario:
    """G16b 真正语义歧义必须升级到 LLM."""
    clock = make_clock(now=datetime(2026, 8, 20, 20, 0, tzinfo=UTC))
    scope = make_scope()
    return GoldenScenario(
        golden_id="G16b",
        title="真正语义歧义必须升级到 LLM",
        owner="MR-D8 not implemented",
        clock=clock,
        runtime_id="runtime-1",
        scope=scope,
        persona=(make_persona(),),
        initial_canonical_state=(),
        historical_context=None,
        input_evidence=(make_evidence(text="要不我们下周再约？", occurred_at=clock.now()),),
        expected_deterministic_outputs=(
            ("appraisal.path", "llm"),
            ("semantic_candidate.schema", "valid"),
            ("provider_call_count", 1),
            ("llm_output.final_affect", "absent"),
            ("low_confidence.abstained", "true"),
        ),
        expected_allowed_llm_path=AppraisalPath.LLM,
        expected_canonical_changes=(),
        expected_projected_changes=(),
    )
