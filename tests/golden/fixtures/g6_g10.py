"""G6~G10 golden scenario fixtures (D2.3)."""

from dataclasses import replace
from datetime import UTC, datetime

from mind_runtime.contracts import (
    HistoricalContextBundle,
    HistoricalContextItem,
    PatternMatchSummary,
    Scope,
    ScopeDomain,
)
from tests.golden.fixtures.common import (
    NOW,
    make_clock,
    make_evidence,
    make_persona,
    make_scope,
    make_state,
)
from tests.golden.scenario import ExpectedChange, GoldenScenario


def make_g6() -> GoldenScenario:
    """G6 重复事件产生不同意义: first cancellation low threat, repeated -> higher concern."""
    clock = make_clock(now=NOW)
    scope = make_scope()
    item = HistoricalContextItem(
        item_id="hc-1",
        scope=scope,
        external_id="ext-1",
        kind="episode",
        proposition="user cancelled a plan last week",
        source_refs=(),
        confidence=0.8,
        relevance_hint=0.6,
    )
    summary = PatternMatchSummary(
        summary_id="ps-1",
        scope=scope,
        origin_runtime_id="runtime-1",
        match_count=3,
        first_seen_at=NOW,
        last_seen_at=NOW,
        matched_refs=("evidence-1", "evidence-2", "evidence-3"),
        confidence=0.7,
    )
    bundle = HistoricalContextBundle(
        bundle_id="hb-1",
        scope=scope,
        origin_runtime_id="runtime-1",
        episodes=(item,),
        stable_facts=(),
        relationship_events=(),
        pattern_summaries=(summary,),
        source_refs=(),
        provider_trace="fixture",
    )
    return GoldenScenario(
        golden_id="G6",
        title="重复事件产生不同意义",
        owner="MR-D8 not implemented",
        clock=clock,
        runtime_id="runtime-1",
        scope=scope,
        persona=(make_persona(dimension="agent.affect.anxiety", sensitivity=0.5),),
        initial_canonical_state=(),
        historical_context=bundle,
        input_evidence=(
            replace(
                make_evidence(text="我又取消了一个计划", source_id="message-4"),
                source_type="typed_event",
                payload={
                    "kind": "plan_cancelled",
                    "attributes": {"recurrence": "2"},
                },
            ),
        ),
        expected_deterministic_outputs=(
            ("affect.anxiety.without_history", 0.4),
            ("affect.anxiety.with_history", 0.425),
            ("trace.history_applied", 1),
        ),
        expected_allowed_llm_path=None,
        expected_canonical_changes=(),
        expected_projected_changes=(ExpectedChange("agent.affect.anxiety", "higher"),),
    )


def make_g7() -> GoldenScenario:
    """G7 Persona 差异: same observation, different abandonment sensitivity."""
    clock = make_clock(now=NOW)
    scope = Scope(domain=ScopeDomain.AGENT, agent_id="agent-1", persona_id="persona-1")
    return GoldenScenario(
        golden_id="G7",
        title="Persona 差异",
        owner="MR-D7 not implemented",
        clock=clock,
        runtime_id="runtime-1",
        scope=scope,
        persona=(
            make_persona(dimension="agent.trait.abandonment_sensitivity", sensitivity=0.2),
            make_persona(dimension="agent.trait.abandonment_sensitivity_high", sensitivity=0.9),
        ),
        initial_canonical_state=(
            make_state(dimension="agent.affect.anxiety", value=0.4, scope=scope),
        ),
        historical_context=None,
        input_evidence=(make_evidence(text="我们下周再聊吧"),),
        expected_deterministic_outputs=(
            ("affect.transition.low_sensitivity", "small"),
            ("affect.transition.high_sensitivity", "large"),
        ),
        expected_allowed_llm_path=None,
        expected_canonical_changes=(),
        expected_projected_changes=(
            ExpectedChange("agent.affect.anxiety", "different_per_persona"),
        ),
    )


def make_g8() -> GoldenScenario:
    """G8 Assistant 自污染防护: assistant's own words must not become user state."""
    clock = make_clock(now=NOW)
    scope = make_scope()
    return GoldenScenario(
        golden_id="G8",
        title="Assistant 自污染防护",
        owner="MR-D3 not implemented",
        clock=clock,
        runtime_id="runtime-1",
        scope=scope,
        persona=(make_persona(),),
        initial_canonical_state=(
            make_state(dimension="user.health.tired", value="unknown", scope=scope),
        ),
        historical_context=None,
        input_evidence=(
            make_evidence(
                text="感觉你有点累。",
                source_id="assistant-1",
                source_type="assistant_message",
            ),
        ),
        expected_deterministic_outputs=(("user.health.tired", "unchanged"),),
        expected_allowed_llm_path=None,
        expected_canonical_changes=(ExpectedChange("user.health.tired", "unchanged"),),
        expected_projected_changes=(),
    )


def make_g9() -> GoldenScenario:
    """G9 迟到事件: delayed old message must not roll back newer current state."""
    clock = make_clock(now=datetime(2026, 8, 20, 16, 0, tzinfo=UTC))
    scope = make_scope()
    return GoldenScenario(
        golden_id="G9",
        title="迟到事件",
        owner="MR-D4 not implemented",
        clock=clock,
        runtime_id="runtime-1",
        scope=scope,
        persona=(make_persona(),),
        initial_canonical_state=(
            make_state(dimension="user.sleep.phase", value="awake", scope=scope),
        ),
        historical_context=None,
        input_evidence=(
            make_evidence(
                text="我睡了",
                occurred_at=datetime(2026, 8, 20, 13, 50, tzinfo=UTC),
                received_at=clock.now(),
            ),
        ),
        expected_deterministic_outputs=(("user.sleep.phase", "awake"),),
        expected_allowed_llm_path=None,
        expected_canonical_changes=(ExpectedChange("user.sleep.phase", "awake"),),
        expected_projected_changes=(),
    )


def make_g9a() -> GoldenScenario:
    """G9a (D3 stage): delayed event keeps complete ordering information.

    The full G9 anti-rollback semantics stay in D4 (G9b); this staged
    contract covers only what the D3 factual plane owns: occurred_at vs
    received_at stay distinct and ordered in provenance.
    """
    clock = make_clock(now=datetime(2026, 8, 20, 16, 0, tzinfo=UTC))
    scope = make_scope()
    return GoldenScenario(
        golden_id="G9a",
        title="迟到事件-排序信息 (D3 阶段)",
        owner="MR-D3 not implemented",
        clock=clock,
        runtime_id="runtime-1",
        scope=scope,
        persona=(make_persona(),),
        initial_canonical_state=(),
        historical_context=None,
        input_evidence=(
            make_evidence(
                text="我睡了",
                occurred_at=datetime(2026, 8, 20, 13, 50, tzinfo=UTC),
                received_at=clock.now(),
            ),
        ),
        expected_deterministic_outputs=(("ordering.info", "complete"),),
        expected_allowed_llm_path=None,
        expected_canonical_changes=(),
        expected_projected_changes=(),
    )


def make_g10() -> GoldenScenario:
    """G10 Replay: same evidence/clock/persona/memory -> same deterministic outputs."""
    clock = make_clock(now=NOW)
    scope = make_scope()
    return GoldenScenario(
        golden_id="G10",
        title="Replay",
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
        expected_deterministic_outputs=(("user.sleep.phase", "awake"),),
        expected_allowed_llm_path=None,
        expected_canonical_changes=(ExpectedChange("user.sleep.phase", "awake"),),
        expected_projected_changes=(),
    )
