"""G11~G16 golden scenario fixtures (D2.4)."""

from datetime import timedelta

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


def make_g11() -> GoldenScenario:
    """G11 Scope 隔离: kayla affect must not enter lara scope."""
    clock = make_clock(now=NOW)
    kayla_scope = Scope(domain=ScopeDomain.AGENT, agent_id="kayla", persona_id="persona-kayla")
    return GoldenScenario(
        golden_id="G11",
        title="Scope 隔离",
        owner="MR-D3 not implemented",
        clock=clock,
        runtime_id="runtime-1",
        scope=kayla_scope,
        persona=(make_persona(),),
        initial_canonical_state=(
            make_state(
                dimension="agent.affect.longing",
                value=0.7,
                scope=kayla_scope,
            ),
        ),
        historical_context=None,
        input_evidence=(
            make_evidence(
                text="kayla longing observation",
                source_id="kayla-1",
                scope=kayla_scope,
            ),
        ),
        expected_deterministic_outputs=(("scope.leak_to_lara", "false"),),
        expected_allowed_llm_path=None,
        expected_canonical_changes=(),
        expected_projected_changes=(),
    )


def make_g12a() -> GoldenScenario:
    """G12a (D5.8 stage): committed canonical state survives restart.

    The full G12 composite restart story (state + memory + relationship +
    pending writeback) stays with G12 (ADR-0003); this staged contract
    covers only the D5-owned part: after a turn commits through the durable
    StateBackend, a fresh orchestrator on the same backend restores the
    canonical state.
    """
    clock = make_clock(now=NOW)
    scope = make_scope()
    return GoldenScenario(
        golden_id="G12a",
        title="重启恢复 (D5 阶段)",
        owner="MR-D5 not implemented",
        clock=clock,
        runtime_id="runtime-1",
        scope=scope,
        persona=(make_persona(),),
        initial_canonical_state=(
            make_state(dimension="user.sleep.phase", value="awake", scope=scope),
        ),
        historical_context=None,
        input_evidence=(make_evidence(text="我刚睡醒"),),
        expected_deterministic_outputs=(("restart.consistent", "true"),),
        expected_allowed_llm_path=None,
        expected_canonical_changes=(ExpectedChange("user.sleep.phase", "awake"),),
        expected_projected_changes=(),
    )


def make_g12() -> GoldenScenario:
    """G12 composite restart over the existing durable Product Slice.

    Under ADR-0008 this covers durable facts, user/agent/relationship State,
    Intent history, checkpoint recovery inputs/decision, and unchanged
    read-only history. ReceiptRegistry remains in-memory; Native Memory and
    Memory writeback are explicitly outside G12 and remain blocked under MR-4.
    """
    clock = make_clock(now=NOW)
    scope = make_scope()
    return GoldenScenario(
        golden_id="G12",
        title="现有持久平面组合重启恢复",
        owner="MR-D11 not implemented",
        clock=clock,
        runtime_id="runtime-1",
        scope=scope,
        persona=(make_persona(),),
        initial_canonical_state=(
            make_state(dimension="user.sleep.phase", value="awake", scope=scope),
        ),
        historical_context=None,
        input_evidence=(make_evidence(text="我刚睡醒"),),
        expected_deterministic_outputs=(("restart.consistent", "true"),),
        expected_allowed_llm_path=None,
        expected_canonical_changes=(ExpectedChange("user.sleep.phase", "awake"),),
        expected_projected_changes=(),
    )


def make_g13() -> GoldenScenario:
    """G13 Projection 不得提前污染 Canonical State: failed turn leaves canonical 0.42."""
    clock = make_clock(now=NOW)
    scope = Scope(domain=ScopeDomain.AGENT, agent_id="agent-1", persona_id="persona-1")
    return GoldenScenario(
        golden_id="G13",
        title="Projection 不得提前污染 Canonical State",
        owner="MR-D5 not implemented",
        clock=clock,
        runtime_id="runtime-1",
        scope=scope,
        persona=(make_persona(),),
        initial_canonical_state=(
            make_state(
                dimension="agent.affect.longing",
                value=0.42,
                scope=scope,
            ),
        ),
        historical_context=None,
        input_evidence=(make_evidence(text="你好呀"),),
        expected_deterministic_outputs=(("canonical.agent.affect.longing", 0.42),),
        expected_allowed_llm_path=None,
        expected_canonical_changes=(ExpectedChange("agent.affect.longing", 0.42),),
        expected_projected_changes=(ExpectedChange("agent.affect.longing", 0.55),),
    )


def make_g14() -> GoldenScenario:
    """G14 ActionPolicy 与 ExpressionGuard 分离: policy allowed, guard rewrite_required."""
    clock = make_clock(now=NOW)
    scope = make_scope()
    return GoldenScenario(
        golden_id="G14",
        title="ActionPolicy 与 ExpressionGuard 分离",
        owner="MR-D10 not implemented",
        clock=clock,
        runtime_id="runtime-1",
        scope=scope,
        persona=(make_persona(),),
        initial_canonical_state=(
            make_state(dimension="user.sleep.phase", value="awake", scope=scope),
        ),
        historical_context=None,
        input_evidence=(),
        expected_deterministic_outputs=(
            ("action.policy", "allowed"),
            ("expression.guard", "rewrite_required"),
        ),
        expected_allowed_llm_path=None,
        expected_canonical_changes=(),
        expected_projected_changes=(),
    )


def make_g15() -> GoldenScenario:
    """G15 Replication Authority / Ownership: cross-agent write must fail closed."""
    clock = make_clock(now=NOW)
    lara_scope = Scope(domain=ScopeDomain.AGENT, agent_id="lara", persona_id="persona-lara")
    return GoldenScenario(
        golden_id="G15",
        title="Replication Authority / Ownership",
        owner="MR-D5 not implemented",
        clock=clock,
        runtime_id="runtime-lara",
        scope=lara_scope,
        persona=(make_persona(),),
        initial_canonical_state=(),
        historical_context=None,
        input_evidence=(
            make_evidence(
                text="inbound kayla affect write",
                source_id="inbound-kayla-1",
                scope=lara_scope,
            ),
        ),
        expected_deterministic_outputs=(
            ("inbox.apply.kayla_affect_write", "fail_closed"),
            ("inbox.apply.user_observation", "allowed_after_authority"),
        ),
        expected_allowed_llm_path=None,
        expected_canonical_changes=(),
        expected_projected_changes=(),
    )


def make_g15a() -> GoldenScenario:
    """G15a (D3 stage): cross-persona fact-entry write fails closed.

    The full replication inbox semantics stay in D5 (G15b); this staged
    contract covers only the D3-owned part: a Lara runtime submitting an
    Evidence for the Kayla agent scope is rejected by the Ownership gate
    before any Observation is produced.
    """
    clock = make_clock(now=NOW)
    kayla_scope = Scope(domain=ScopeDomain.AGENT, agent_id="kayla", persona_id="persona-kayla")
    return GoldenScenario(
        golden_id="G15a",
        title="Replication Authority / Ownership (ingest 阶段)",
        owner="MR-D3 not implemented",
        clock=clock,
        runtime_id="runtime-lara",
        scope=kayla_scope,
        persona=(make_persona(),),
        initial_canonical_state=(),
        historical_context=None,
        input_evidence=(
            make_evidence(
                text="inbound kayla affect write",
                source_id="inbound-kayla-1",
                scope=kayla_scope,
            ),
        ),
        expected_deterministic_outputs=(("inbox.apply.kayla_affect_write", "fail_closed"),),
        expected_allowed_llm_path=None,
        expected_canonical_changes=(),
        expected_projected_changes=(),
    )


def make_g16a() -> GoldenScenario:
    """G16a (D6 stage): proactive cooldown blocks deterministically, no LLM.

    The full G16 appraisal-router semantics stay in D8; this staged contract
    covers only the D6-owned deterministic input: the last message is inside
    the proactive cooldown window, so the proactive path is blocked.
    """
    clock = make_clock(now=NOW)
    interaction_scope = Scope(domain=ScopeDomain.INTERACTION, interaction_id="interaction-1")
    return GoldenScenario(
        golden_id="G16a",
        title="主动冷却-确定性路径 (D6 阶段)",
        owner="MR-D9 not implemented",
        clock=clock,
        runtime_id="runtime-1",
        scope=make_scope(),
        persona=(make_persona(),),
        initial_canonical_state=(
            make_state(
                dimension="interaction.last_message_at",
                value=(clock.now() - timedelta(minutes=10)).isoformat(),
                scope=interaction_scope,
            ),
        ),
        historical_context=None,
        input_evidence=(),
        expected_deterministic_outputs=(("proactive.cooldown", "blocked"),),
        expected_allowed_llm_path=None,
        expected_canonical_changes=(),
        expected_projected_changes=(),
    )


def make_g16() -> GoldenScenario:
    """G16 AppraisalRouter 不做无意义 LLM 调用: cooldown blocked, llm_call_count=0."""
    clock = make_clock(now=NOW)
    interaction_scope = Scope(domain=ScopeDomain.INTERACTION, interaction_id="interaction-1")
    user_scope = make_scope()
    return GoldenScenario(
        golden_id="G16",
        title="AppraisalRouter 不做无意义 LLM 调用",
        owner="MR-D8 not implemented",
        clock=clock,
        runtime_id="runtime-1",
        scope=user_scope,
        persona=(make_persona(),),
        initial_canonical_state=(
            make_state(
                dimension="interaction.last_message_at",
                value=(clock.now() - timedelta(minutes=10)).isoformat(),
                scope=interaction_scope,
            ),
        ),
        historical_context=None,
        input_evidence=(),
        expected_deterministic_outputs=(
            ("appraisal_path", "deterministic"),
            ("route_reason", "no_semantic_event"),
            ("provider_call_count", 0),
        ),
        expected_allowed_llm_path=None,
        expected_canonical_changes=(),
        expected_projected_changes=(),
    )
