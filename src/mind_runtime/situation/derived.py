"""Deterministic derived-fact rules (D6.2/D6.3).

All rules are pure functions over Effective State (never raw state),
Interaction, Clock, and explicit counters. Derived facts are Situation
projections — they are never written as canonical user facts and never
land in long-term Memory.
"""

from datetime import datetime, timedelta

from mind_runtime.contracts import Interaction
from mind_runtime.situation.temporal import Daypart
from mind_runtime.state.resolver import EffectiveStateView


def recently_awake(
    effective: EffectiveStateView,
    *,
    now: datetime,
    window: timedelta,
) -> bool:
    """True when user.sleep.phase is awake and observed within ``window``."""
    for state in effective.states:
        if state.dimension == "user.sleep.phase" and state.value == "awake":
            return now - state.last_observed_at <= window
    return False


def conversation_active(
    interaction: Interaction,
    *,
    now: datetime,
    idle_window: timedelta,
) -> bool:
    """True when a chat interaction is within the idle window."""
    if interaction.channel != "chat":
        return False
    return now - interaction.started_at <= idle_window


def sleep_norm_relevance(
    daypart_value: Daypart,
    *,
    recently_awake_value: bool,
    conversation_active_value: bool,
) -> str:
    """The sleep-norm suggestion is suppressed for a recently-awake, engaged
    night conversation — '02:30 + recently_awake + active' must never derive
    'you should sleep' (baseline D6 principle)."""
    if daypart_value is Daypart.NIGHT and recently_awake_value and conversation_active_value:
        return "suppressed"
    return "normal"


def proactive_cooldown_ready(
    last_proactive_at: datetime | None,
    *,
    now: datetime,
    cooldown: timedelta,
) -> bool:
    """True when enough time passed since the last proactive action."""
    if last_proactive_at is None:
        return True
    return now - last_proactive_at >= cooldown


def interaction_last_message_at(effective: EffectiveStateView) -> datetime | None:
    """Read the interaction.last_message_at dimension (stored as ISO text)."""
    for state in effective.states:
        if state.dimension == "interaction.last_message_at":
            value = state.value
            if isinstance(value, str):
                return datetime.fromisoformat(value)
    return None


def media_photo_budget_state(photo_count_today: int, *, budget: int) -> str:
    """The daily photo budget as 'ok' | 'exhausted' (pure counter rule)."""
    if photo_count_today >= budget:
        return "exhausted"
    return "ok"


def media_photo_frequency_eligible(
    photo_count_today: int,
    *,
    budget: int,
    sticky_threshold: int = 3,
) -> str:
    """Deprecated legacy helper: DO NOT WIRE.

    Conflates the daily budget with the send-photo cadence and reads the
    wrong counter (photos sent today, not settled proactive prompts since
    the last SEND_PHOTO). Superseded by ``media_photo_cadence_eligible``
    (C6B); kept only until the C11 cleanup sweep retires it.
    """
    if photo_count_today >= budget:
        return "blocked"
    if photo_count_today >= sticky_threshold:
        return "optional"
    return "eligible"


def media_photo_cadence_eligible(
    handled_proactive_prompts: int | None,
    *,
    threshold: int | None,
) -> bool:
    """Legacy gap #6 (image.quota_frequency) cadence, read half only.

    An image becomes OPTIONAL once ``threshold`` settled proactive prompts
    have passed since the last settled SEND_PHOTO; eligibility is never an
    obligation, and the daily media cap stays ActionPolicy authority.

    ``threshold`` is REQUIRED deployment configuration — ``None`` disables
    the cadence feature entirely. There is deliberately no default number:
    a runtime that does not configure the cadence never inherits one
    deployment's 1-per-3 rule (algorithm is generic, numbers are config).
    A missing counter still fails closed (not eligible); the authoritative
    counter is host-owned and its updates belong to settled delivery
    outcomes (C7), never to this derivation.
    """
    if threshold is not None and (isinstance(threshold, bool) or threshold < 1):
        raise ValueError("cadence threshold must be a positive integer")
    if threshold is None:
        return False
    if handled_proactive_prompts is None:
        return False
    if handled_proactive_prompts < 0:
        raise ValueError("handled_proactive_prompts must not be negative")
    return handled_proactive_prompts >= threshold


def recent_interaction_recency(
    last_interaction_at: datetime | None,
    *,
    now: datetime,
    recent_window: timedelta,
) -> str:
    """Interaction recency: 'recent' | 'stale' | 'unknown'."""
    if last_interaction_at is None:
        return "unknown"
    if now - last_interaction_at <= recent_window:
        return "recent"
    return "stale"
