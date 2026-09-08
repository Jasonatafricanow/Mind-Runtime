"""D11L shadow traffic classifier (Evidence #2 as executable code).

Classifies one inbound event as ELIGIBLE for shadow sampling.

Fail-closed: unknown channels/senders/triggers, test sessions, non-Kayla
domains, and any missing/unknown field => INELIGIBLE.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class Channel(StrEnum):
    TELEGRAM = "telegram"
    WEIXIN = "weixin"


class Sender(StrEnum):
    USER = "user"
    AGENT = "agent"


class Trigger(StrEnum):
    MESSAGE = "message"  # E1 real private chat
    EMOTION = "emotion"  # E2 emotion-driven proactive message


class SourceDomain(StrEnum):
    KAYLA_PERSONA = "kayla_persona"


# Explicit exclusions that must never be sampled.
_BLOCKED_TRIGGERS = frozenset(
    {"cron", "schedule", "scheduled", "heartbeat", "task", "sync", "mirror"}
)
_BLOCKED_DOMAINS = frozenset({"xinchao", "ombre_brain", "garden", "test", "sandbox"})
_TEST_SESSION_PREFIX = "test/"


@dataclass(frozen=True)
class EventMeta:
    channel: str
    sender: str
    session: str
    trigger: str
    source_domain: str


def classify(meta: EventMeta) -> bool:
    """Return True iff the event is ELIGIBLE for D11L shadow sampling."""
    if meta.channel not in set(Channel):
        return False
    if meta.sender not in set(Sender):
        return False
    if meta.trigger not in set(Trigger):
        return False
    if meta.source_domain != SourceDomain.KAYLA_PERSONA:
        return False
    if meta.session.startswith(_TEST_SESSION_PREFIX):
        return False
    # E2 exclusion surface: explicit blockers win regardless of other fields.
    # Unreachable-by-construction belt-and-braces: the blocked sets are
    # disjoint from the enum-membership gates above ('cron' etc. can never
    # pass the Trigger membership check AND reach this line; likewise for
    # _BLOCKED_DOMAINS vs the KAYLA_PERSONA equality gate). Kept as defense
    # against future edits that loosen the membership gates.
    trigger_norm = str(meta.trigger).lower()
    if trigger_norm in _BLOCKED_TRIGGERS:  # pragma: no cover - unreachable, see note
        return False
    domain_norm = str(meta.source_domain).lower()
    if domain_norm in _BLOCKED_DOMAINS:  # pragma: no cover - unreachable, see note
        return False
    return True
