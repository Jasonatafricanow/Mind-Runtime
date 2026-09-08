"""G1~G5 golden scenario fixtures (D2.2)."""

from datetime import UTC, datetime

from mind_runtime.contracts import Scope, ScopeDomain
from tests.golden.fixtures.common import (
    NOW,
    make_clock,
    make_evidence,
    make_persona,
    make_scope,
    make_state,
)
from tests.golden.scenario import ExpectedChange, GoldenScenario


def make_g1() -> GoldenScenario:
    """G1 凌晨刚醒: 02:30 user says 刚睡醒 while chatting."""
    clock = make_clock(now=datetime(2026, 8, 20, 2, 30, tzinfo=UTC))
    return GoldenScenario(
        golden_id="G1",
        title="凌晨刚醒",
        owner="MR-D6.2 not implemented",
        clock=clock,
        runtime_id="runtime-1",
        scope=make_scope(),
        persona=(make_persona(),),
        initial_canonical_state=(make_state(dimension="user.sleep.phase", value="sleeping"),),
        historical_context=None,
        input_evidence=(
            make_evidence(text="我刚睡醒", occurred_at=clock.now(), received_at=clock.now()),
        ),
        expected_deterministic_outputs=(
            ("user.sleep.phase", "awake"),
            ("conversation.active", "true"),
            ("sleep_norm_relevance", "suppressed"),
        ),
        expected_allowed_llm_path=None,
        expected_canonical_changes=(ExpectedChange("user.sleep.phase", "awake"),),
        expected_projected_changes=(),
    )


def make_g2() -> GoldenScenario:
    """G2 状态 reaffirm: headache at 08:00 stays active at 21:00."""
    clock = make_clock(now=datetime(2026, 8, 20, 21, 0, tzinfo=UTC))
    return GoldenScenario(
        golden_id="G2",
        title="状态 reaffirm",
        owner="MR-D4 not implemented",
        clock=clock,
        runtime_id="runtime-1",
        scope=make_scope(),
        persona=(make_persona(),),
        initial_canonical_state=(
            make_state(dimension="user.health.headache", value="active", status="active"),
        ),
        historical_context=None,
        input_evidence=(make_evidence(text="头还是疼", occurred_at=clock.now()),),
        expected_deterministic_outputs=(("user.health.headache", "active"),),
        expected_allowed_llm_path=None,
        expected_canonical_changes=(ExpectedChange("user.health.headache", "active"),),
        expected_projected_changes=(),
    )


def make_g3() -> GoldenScenario:
    """G3 cancelled 不是 expired: cancelled plan is context, not expired."""
    clock = make_clock(now=datetime(2026, 8, 20, 18, 0, tzinfo=UTC))
    return GoldenScenario(
        golden_id="G3",
        title="cancelled 不是 expired",
        owner="MR-D4 not implemented",
        clock=clock,
        runtime_id="runtime-1",
        scope=make_scope(),
        persona=(make_persona(),),
        initial_canonical_state=(
            make_state(
                dimension="user.planning.calligraphy",
                value="cancelled",
                status="cancelled",
            ),
        ),
        historical_context=None,
        input_evidence=(),
        expected_deterministic_outputs=(("context.recently_cancelled", "true"),),
        expected_allowed_llm_path=None,
        expected_canonical_changes=(),
        expected_projected_changes=(),
    )


def make_g4() -> GoldenScenario:
    """G4 想发但不能发: high longing, active conversation -> Intent high, action blocked."""
    clock = make_clock(now=NOW)
    agent_scope = Scope(domain=ScopeDomain.AGENT, agent_id="agent-1", persona_id="persona-1")
    interaction_scope = Scope(domain=ScopeDomain.INTERACTION, interaction_id="interaction-1")
    return GoldenScenario(
        golden_id="G4",
        title="想发但不能发",
        owner="MR-D9 not implemented",
        clock=clock,
        runtime_id="runtime-1",
        scope=agent_scope,
        persona=(make_persona(sensitivity=0.9),),
        initial_canonical_state=(
            make_state(
                dimension="agent.affect.longing",
                value=0.82,
                scope=agent_scope,
            ),
            make_state(
                dimension="interaction.turn_state",
                value="active",
                scope=interaction_scope,
            ),
        ),
        historical_context=None,
        input_evidence=(),
        expected_deterministic_outputs=(
            ("intent.contact_user", "high"),
            ("action.proactive_message", "blocked"),
        ),
        expected_allowed_llm_path=None,
        expected_canonical_changes=(),
        expected_projected_changes=(ExpectedChange("agent.affect.longing", 0.82),),
    )


def make_g5() -> GoldenScenario:
    """G5 图片预算: photo budget exhausted, text still allowed."""
    clock = make_clock(now=NOW)
    agent_scope = Scope(domain=ScopeDomain.AGENT, agent_id="agent-1", persona_id="persona-1")
    user_scope = make_scope()
    return GoldenScenario(
        golden_id="G5",
        title="图片预算",
        owner="MR-D9 not implemented",
        clock=clock,
        runtime_id="runtime-1",
        scope=agent_scope,
        persona=(make_persona(),),
        initial_canonical_state=(
            make_state(
                dimension="user.media.photo_budget_used",
                value=8,
                scope=user_scope,
            ),
            make_state(
                dimension="agent.affect.photo_share_desire",
                value=0.9,
                scope=agent_scope,
            ),
        ),
        historical_context=None,
        input_evidence=(),
        expected_deterministic_outputs=(
            ("action.photo", "blocked"),
            ("action.text_message", "allowed"),
        ),
        expected_allowed_llm_path=None,
        expected_canonical_changes=(),
        expected_projected_changes=(),
    )
