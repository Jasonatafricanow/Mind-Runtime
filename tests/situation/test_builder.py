"""D6.2 SituationBuilder tests: deterministic aggregation over Effective State."""

from datetime import UTC, datetime, timedelta

from mind_runtime.contracts import Interaction, InteractionStatus, RuntimeState, Situation
from mind_runtime.situation.builder import SituationBuilder
from mind_runtime.state.resolver import EffectiveStateView
from tests.golden.fixtures.common import make_scope, make_state

NOW = datetime(2026, 8, 22, 2, 30, tzinfo=UTC)


def make_interaction(*, started_at: datetime = NOW) -> Interaction:
    return Interaction(
        interaction_id="interaction-1",
        scope=make_scope(),
        channel="chat",
        session_id="session-1",
        turn_id="turn-1",
        started_at=started_at,
        committed_at=None,
        status=InteractionStatus.OPEN,
    )


def make_view(*states: RuntimeState) -> EffectiveStateView:
    return EffectiveStateView(states=states, resolved_at=NOW)


def make_builder() -> SituationBuilder:
    return SituationBuilder()


def test_builder_g1_night_awake_engaged() -> None:
    """G1: 02:30, recently awake, active conversation -> suppressed sleep norm."""
    awake = make_state(
        dimension="user.sleep.phase",
        value="awake",
        status="active",
        now=NOW - timedelta(minutes=5),
    )
    situation = make_builder().build(
        interaction=make_interaction(),
        effective_view=make_view(awake),
        scope=make_scope(),
        clock=NOW,
    )
    assert isinstance(situation, Situation)
    facts = dict(situation.derived_facts)
    assert facts["time.daypart"] == "night"
    assert facts["user.recently_awake"] == "true"
    assert facts["conversation.active"] == "true"
    assert facts["conversation.idle"] == "false"
    assert facts["sleep_norm_relevance"] == "suppressed"


def test_builder_idle_conversation() -> None:
    awake = make_state(
        dimension="user.sleep.phase",
        value="awake",
        status="active",
        now=NOW - timedelta(minutes=5),
    )
    situation = make_builder().build(
        interaction=make_interaction(started_at=NOW - timedelta(minutes=30)),
        effective_view=make_view(awake),
        scope=make_scope(),
        clock=NOW,
    )
    facts = dict(situation.derived_facts)
    assert facts["conversation.active"] == "false"
    assert facts["conversation.idle"] == "true"
    # Night + awake but idle conversation: sleep norm NOT suppressed.
    assert facts["sleep_norm_relevance"] == "normal"


def test_builder_no_effective_state() -> None:
    situation = make_builder().build(
        interaction=make_interaction(),
        effective_view=make_view(),
        scope=make_scope(),
        clock=NOW,
    )
    facts = dict(situation.derived_facts)
    assert facts["user.recently_awake"] == "false"
    assert situation.effective_state_ref == "none"


def test_builder_is_deterministic_for_replay() -> None:
    awake = make_state(
        dimension="user.sleep.phase",
        value="awake",
        status="active",
        now=NOW - timedelta(minutes=5),
    )
    first = make_builder().build(
        interaction=make_interaction(),
        effective_view=make_view(awake),
        scope=make_scope(),
        clock=NOW,
    )
    second = make_builder().build(
        interaction=make_interaction(),
        effective_view=make_view(awake),
        scope=make_scope(),
        clock=NOW,
    )
    assert first == second
