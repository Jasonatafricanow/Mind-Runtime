"""D6.2 derived-fact rule tests: recently_awake, conversation, sleep norm."""

from datetime import UTC, datetime, timedelta

from mind_runtime.contracts import Interaction, InteractionStatus, RuntimeState
from mind_runtime.situation.derived import (
    conversation_active,
    recently_awake,
    sleep_norm_relevance,
)
from mind_runtime.situation.temporal import Daypart
from mind_runtime.state.resolver import EffectiveStateView
from tests.golden.fixtures.common import make_scope, make_state

NOW = datetime(2026, 8, 22, 2, 30, tzinfo=UTC)


def make_interaction(*, started_at: datetime = NOW, channel: str = "chat") -> Interaction:
    return Interaction(
        interaction_id="interaction-1",
        scope=make_scope(),
        channel=channel,
        session_id="session-1",
        turn_id="turn-1",
        started_at=started_at,
        committed_at=None,
        status=InteractionStatus.OPEN,
    )


def make_view(*states: RuntimeState) -> EffectiveStateView:
    return EffectiveStateView(states=states, resolved_at=NOW)


def test_recently_awake_within_window() -> None:
    state = make_state(
        dimension="user.sleep.phase",
        value="awake",
        status="active",
        now=NOW - timedelta(minutes=10),
    )
    assert recently_awake(make_view(state), now=NOW, window=timedelta(minutes=30)) is True


def test_recently_awake_past_window() -> None:
    state = make_state(
        dimension="user.sleep.phase",
        value="awake",
        status="active",
        now=NOW - timedelta(hours=2),
    )
    assert recently_awake(make_view(state), now=NOW, window=timedelta(minutes=30)) is False


def test_recently_awake_not_awake() -> None:
    state = make_state(dimension="user.sleep.phase", value="sleeping", status="active")
    assert recently_awake(make_view(state), now=NOW, window=timedelta(minutes=30)) is False


def test_recently_awake_no_state() -> None:
    assert recently_awake(make_view(), now=NOW, window=timedelta(minutes=30)) is False


def test_conversation_active_within_idle_window() -> None:
    interaction = make_interaction(started_at=NOW)
    assert conversation_active(interaction, now=NOW, idle_window=timedelta(minutes=5)) is True


def test_conversation_idle_past_window() -> None:
    interaction = make_interaction(started_at=NOW - timedelta(minutes=30))
    assert conversation_active(interaction, now=NOW, idle_window=timedelta(minutes=5)) is False


def test_non_chat_channel_not_active() -> None:
    interaction = make_interaction(channel="email")
    assert conversation_active(interaction, now=NOW, idle_window=timedelta(minutes=5)) is False


def test_sleep_norm_suppressed_for_night_awake_engaged() -> None:
    """G1 core: 02:30 + recently_awake + active must not suggest sleeping."""
    assert (
        sleep_norm_relevance(
            Daypart.NIGHT,
            recently_awake_value=True,
            conversation_active_value=True,
        )
        == "suppressed"
    )


def test_sleep_norm_normal_for_daytime() -> None:
    assert (
        sleep_norm_relevance(
            Daypart.MORNING,
            recently_awake_value=True,
            conversation_active_value=True,
        )
        == "normal"
    )


def test_sleep_norm_normal_when_not_engaged() -> None:
    assert (
        sleep_norm_relevance(
            Daypart.NIGHT,
            recently_awake_value=True,
            conversation_active_value=False,
        )
        == "normal"
    )


def test_sleep_norm_normal_when_not_recently_awake() -> None:
    assert (
        sleep_norm_relevance(
            Daypart.NIGHT,
            recently_awake_value=False,
            conversation_active_value=True,
        )
        == "normal"
    )


# --- D6.3 first-batch rules (cooldown / media / recency) ---


def test_interaction_last_message_at_from_view() -> None:
    from mind_runtime.contracts import Scope, ScopeDomain
    from mind_runtime.situation.derived import interaction_last_message_at

    scope = Scope(domain=ScopeDomain.INTERACTION, interaction_id="interaction-1")
    state = make_state(
        dimension="interaction.last_message_at",
        value=(NOW - timedelta(minutes=10)).isoformat(),
        status="active",
        scope=scope,
    )
    assert interaction_last_message_at(make_view(state)) == NOW - timedelta(minutes=10)


def test_interaction_last_message_at_non_string_value() -> None:
    from mind_runtime.contracts import Scope, ScopeDomain
    from mind_runtime.situation.derived import interaction_last_message_at

    scope = Scope(domain=ScopeDomain.INTERACTION, interaction_id="interaction-1")
    state = make_state(
        dimension="interaction.last_message_at",
        value=123,  # non-string -> not readable
        status="active",
        scope=scope,
    )
    assert interaction_last_message_at(make_view(state)) is None


def test_interaction_last_message_at_missing() -> None:
    from mind_runtime.situation.derived import interaction_last_message_at

    assert interaction_last_message_at(make_view()) is None


def test_cooldown_ready_after_window() -> None:
    from mind_runtime.situation.derived import proactive_cooldown_ready

    last = NOW - timedelta(minutes=40)
    assert proactive_cooldown_ready(last, now=NOW, cooldown=timedelta(minutes=30)) is True


def test_cooldown_blocked_within_window() -> None:
    from mind_runtime.situation.derived import proactive_cooldown_ready

    last = NOW - timedelta(minutes=20)
    assert proactive_cooldown_ready(last, now=NOW, cooldown=timedelta(minutes=30)) is False


def test_cooldown_ready_without_history() -> None:
    from mind_runtime.situation.derived import proactive_cooldown_ready

    assert proactive_cooldown_ready(None, now=NOW, cooldown=timedelta(minutes=30)) is True


def test_photo_budget_state() -> None:
    from mind_runtime.situation.derived import media_photo_budget_state

    assert media_photo_budget_state(3, budget=8) == "ok"
    assert media_photo_budget_state(8, budget=8) == "exhausted"


def test_photo_frequency_eligibility() -> None:
    from mind_runtime.situation.derived import media_photo_frequency_eligible

    assert media_photo_frequency_eligible(0, budget=8) == "eligible"
    assert media_photo_frequency_eligible(3, budget=8) == "optional"
    assert media_photo_frequency_eligible(9, budget=8) == "blocked"


def test_interaction_recency() -> None:
    from mind_runtime.situation.derived import recent_interaction_recency

    assert (
        recent_interaction_recency(
            NOW - timedelta(minutes=5), now=NOW, recent_window=timedelta(hours=1)
        )
        == "recent"
    )
    assert (
        recent_interaction_recency(
            NOW - timedelta(hours=5), now=NOW, recent_window=timedelta(hours=1)
        )
        == "stale"
    )
    assert recent_interaction_recency(None, now=NOW, recent_window=timedelta(hours=1)) == "unknown"
