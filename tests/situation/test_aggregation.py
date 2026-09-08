"""D6.4 SituationBuilder aggregation tests: no raw facts are dumped."""

from datetime import UTC, datetime, timedelta

from mind_runtime.contracts import Interaction, InteractionStatus, RuntimeState, Situation
from mind_runtime.situation.builder import SituationBuilder, SituationCounters
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


def build(
    *, awake: bool = True, active: bool = True, counters: SituationCounters | None = None
) -> Situation:
    from mind_runtime.state.resolver import EffectiveStateView

    states: tuple[RuntimeState, ...] = ()
    if awake:
        states = (
            make_state(
                dimension="user.sleep.phase",
                value="awake",
                status="active",
                now=NOW - timedelta(minutes=5),
            ),
        )
    builder = SituationBuilder()
    return builder.build(
        interaction=make_interaction(started_at=NOW if active else NOW - timedelta(hours=1)),
        effective_view=EffectiveStateView(states=states, resolved_at=NOW),
        scope=make_scope(),
        clock=NOW,
        counters=counters,
    )


def test_aggregation_awake_and_engaged() -> None:
    situation = build()
    facts = dict(situation.derived_facts)
    assert facts["user_activity"] == "awake_and_engaged"
    assert facts["conversation_mode"] == "active"
    assert facts["schedule_norm_relevance"] == "low"  # night + awake + engaged


def test_aggregation_awake_but_idle() -> None:
    situation = build(active=False)
    facts = dict(situation.derived_facts)
    assert facts["user_activity"] == "awake_and_idle"
    assert facts["conversation_mode"] == "idle"
    assert facts["schedule_norm_relevance"] == "normal"


def test_aggregation_not_recently_awake() -> None:
    situation = build(awake=False)
    facts = dict(situation.derived_facts)
    assert facts["user_activity"] == "not_recently_awake"


def test_counters_remain_factual_and_carry_no_policy_verdicts() -> None:
    counters = SituationCounters(
        photo_count_today=9,
        last_proactive_at=NOW - timedelta(minutes=5),
        last_interaction_at=NOW - timedelta(minutes=5),
    )
    situation = build(counters=counters)
    facts = dict(situation.derived_facts)
    assert counters.last_proactive_at is not None
    assert counters.last_interaction_at is not None
    assert facts["counter.photo_count_today"] == "9"
    assert facts["counter.last_proactive_at"] == counters.last_proactive_at.isoformat()
    assert facts["counter.last_interaction_at"] == counters.last_interaction_at.isoformat()
    assert facts["recent_interaction_recency"] == "recent"
    assert "proactive.cooldown_ready" not in facts
    assert "media.photo_budget_state" not in facts
    assert "media.photo_frequency_eligible" not in facts
    assert not any("allowed" in key or "eligible" in key or "ready" in key for key in facts)


def test_situation_never_dumps_raw_state() -> None:
    """D6.4 audit: the Situation exposes only aggregated derived facts."""
    situation = build()
    keys = {key for key, _ in situation.derived_facts}
    # No raw state payload keys, no state ids, no evidence dumps.
    assert not any(key.startswith("raw.") for key in keys)
    assert not any(key.startswith("state.") for key in keys)
    assert "value" not in keys
    assert situation.evidence_refs == ()
    # The effective state is referenced, not embedded.
    assert situation.effective_state_ref


def test_derived_fact_keys_are_allowlisted() -> None:
    """The derived-fact vocabulary is the frozen first batch plus aggregates."""
    situation = build()
    keys = {key for key, _ in situation.derived_facts}
    allowed = {
        "time.daypart",
        "user.recently_awake",
        "user_activity",
        "conversation.active",
        "conversation.idle",
        "conversation_mode",
        "counter.photo_count_today",
        "counter.last_proactive_at",
        "counter.last_interaction_at",
        "recent_interaction_recency",
        "sleep_norm_relevance",
        "schedule_norm_relevance",
    }
    assert keys == allowed


def test_situation_replayable_under_fake_clock() -> None:
    """D6 merge gate: same inputs + same clock -> identical Situation."""
    first = build()
    second = build()
    assert first == second
