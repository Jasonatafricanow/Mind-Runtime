"""G24-G28 compressed Product Slice acceptance fixtures."""

from collections.abc import Sequence
from datetime import UTC, datetime

from tests.golden.fixtures.common import (
    make_clock,
    make_evidence,
    make_persona,
    make_scope,
)
from tests.golden.scenario import GoldenScenario


def _scenario(
    *,
    golden_id: str,
    title: str,
    owner: str,
    text: str,
    outputs: Sequence[tuple[str, object]],
    now: datetime,
) -> GoldenScenario:
    scope = make_scope()
    return GoldenScenario(
        golden_id=golden_id,
        title=title,
        owner=owner,
        clock=make_clock(now=now),
        runtime_id="runtime-1",
        scope=scope,
        persona=(make_persona(),),
        initial_canonical_state=(),
        historical_context=None,
        input_evidence=(make_evidence(text=text, scope=scope, occurred_at=now, received_at=now),),
        expected_deterministic_outputs=tuple(outputs),
        expected_allowed_llm_path=None,
        expected_canonical_changes=(),
        expected_projected_changes=(),
    )


def make_g24() -> GoldenScenario:
    return _scenario(
        golden_id="G24",
        title="Due Intent wakes for reconsideration, never direct execution",
        owner="MR-D9 not implemented",
        text="稍后提醒我再联系",
        outputs=(
            ("intent.status", "due"),
            ("scheduler.effect", "reconsider"),
            ("scheduler.direct_execute", "false"),
            ("policy.rechecked", "true"),
        ),
        now=datetime(2026, 8, 20, 14, 0, tzinfo=UTC),
    )


def make_g25() -> GoldenScenario:
    return _scenario(
        golden_id="G25",
        title="Base-model swap preserves internal decision",
        owner="MR-D11 not implemented",
        text="我刚睡醒",
        outputs=(
            ("model_swap.internal_transition", "same"),
            ("model_swap.intent", "same"),
            ("model_swap.policy", "same"),
            ("model_swap.expression", "may_differ"),
        ),
        now=datetime(2026, 8, 20, 2, 30, tzinfo=UTC),
    )


def make_g26() -> GoldenScenario:
    return _scenario(
        golden_id="G26",
        title="Ninety-day internal state remains bounded and replayable",
        owner="MR-D11 not implemented",
        text="继续进行长期模拟",
        outputs=(
            ("horizon.days", 90),
            ("affect.within_bounds", "true"),
            ("recovery.replayable", "true"),
            ("self_excitation.unbounded", "false"),
        ),
        now=datetime(2026, 8, 20, 12, 0, tzinfo=UTC),
    )


def make_g27() -> GoldenScenario:
    return _scenario(
        golden_id="G27",
        title="Repeated surfacing cannot amplify or reinforce history",
        owner="MR-D11 not implemented",
        text="重新检查同一条历史",
        outputs=(
            ("history.unique_source_count", 1),
            ("history.retrieval_count", 3),
            ("history.influence_multiplier", 1.0),
            ("history.reinforced", "false"),
        ),
        now=datetime(2026, 8, 20, 16, 0, tzinfo=UTC),
    )


def make_g28() -> GoldenScenario:
    return _scenario(
        golden_id="G28",
        title="Onboarding analysis is one-time and user-activated",
        owner="MR-D11P not implemented",
        text="导入这份双方完整对话",
        outputs=(
            ("onboarding.roles", "user+agent"),
            ("onboarding.llm_call_count", 1),
            ("onboarding.recommendation_authoritative", "false"),
            ("persona.activation_requires_user", "true"),
            ("runtime.personality_llm_calls", 0),
        ),
        now=datetime(2026, 8, 20, 18, 0, tzinfo=UTC),
    )
