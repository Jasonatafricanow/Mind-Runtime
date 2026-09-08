"""SituationBuilder: aggregates derived facts into a Situation (D6).

The builder's inputs are restricted to Effective State + Interaction +
Clock + explicit counters (baseline D6 principle); raw state is never
dumped into the Situation. Derived facts are projections only.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta

from mind_runtime.contracts import Interaction, Scope, Situation
from mind_runtime.situation.derived import (
    conversation_active,
    interaction_last_message_at,
    recent_interaction_recency,
    recently_awake,
    sleep_norm_relevance,
)
from mind_runtime.situation.temporal import TemporalSemantics
from mind_runtime.state.resolver import EffectiveStateView


@dataclass(frozen=True)
class SituationCounters:
    """Explicit counters feeding the derived-fact rules (D6.3)."""

    photo_count_today: int = 0
    last_proactive_at: datetime | None = None
    last_interaction_at: datetime | None = None


class SituationBuilder:
    """Builds one deterministic Situation per turn from allowed inputs."""

    def __init__(
        self,
        *,
        runtime_id: str = "runtime-1",
        recently_awake_window: timedelta = timedelta(minutes=30),
        conversation_idle_window: timedelta = timedelta(minutes=5),
        interaction_recent_window: timedelta = timedelta(hours=1),
    ) -> None:
        self._runtime_id = runtime_id
        self._awake_window = recently_awake_window
        self._idle_window = conversation_idle_window
        self._recent_window = interaction_recent_window

    def build(
        self,
        *,
        interaction: Interaction,
        effective_view: EffectiveStateView,
        scope: Scope,
        clock: datetime,
        counters: SituationCounters | None = None,
    ) -> Situation:
        counters = counters or SituationCounters()
        semantics = TemporalSemantics.at(clock)
        awake = recently_awake(effective_view, now=clock, window=self._awake_window)
        active = conversation_active(interaction, now=clock, idle_window=self._idle_window)
        norm = sleep_norm_relevance(
            semantics.daypart,
            recently_awake_value=awake,
            conversation_active_value=active,
        )
        last_message = interaction_last_message_at(effective_view)
        last_interaction = counters.last_interaction_at or last_message
        recency = recent_interaction_recency(
            last_interaction,
            now=clock,
            recent_window=self._recent_window,
        )
        # Aggregated interpretations (D6.4): the Situation speaks in derived
        # concepts, never in raw state dumps.
        if awake and active:
            activity = "awake_and_engaged"
        elif awake:
            activity = "awake_and_idle"
        else:
            activity = "not_recently_awake"
        conversation_mode = "active" if active else "idle"
        schedule_norm = "low" if norm == "suppressed" else "normal"
        facts = (
            ("time.daypart", semantics.daypart.value),
            ("user.recently_awake", "true" if awake else "false"),
            ("user_activity", activity),
            ("conversation.active", "true" if active else "false"),
            ("conversation.idle", "true" if not active else "false"),
            ("conversation_mode", conversation_mode),
            ("counter.photo_count_today", str(counters.photo_count_today)),
            (
                "counter.last_proactive_at",
                counters.last_proactive_at.isoformat()
                if counters.last_proactive_at is not None
                else "none",
            ),
            (
                "counter.last_interaction_at",
                last_interaction.isoformat() if last_interaction is not None else "none",
            ),
            ("recent_interaction_recency", recency),
            ("sleep_norm_relevance", norm),
            ("schedule_norm_relevance", schedule_norm),
        )
        effective_ref = effective_view.states[0].state_id if effective_view.states else "none"
        return Situation(
            situation_id=f"situation-{interaction.interaction_id}",
            scope=scope,
            origin_runtime_id=self._runtime_id,
            derived_facts=facts,
            effective_state_ref=effective_ref,
            observed_at=clock,
            historical_context=None,
            persona_id=None,
            relationship_ids=(),
            evidence_refs=(),
        )
