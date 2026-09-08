"""D4.1 state definitions and validity-policy vocabulary.

`StateDefinition` (D1 contract) carries ``default_validity_policy`` as an
opaque string; this module freezes the D4 policy vocabulary and the
registry that resolves definitions for the reconciler/resolver.

Policy grammar:

- ``None`` / ``"indefinite"`` — no time-based expiry.
- ``"event_only"`` — the dimension cannot change by time at all (identity,
  relationship status); reaffirm does not refresh an envelope.
- ``"ttl:<duration>"`` — expiry after ``<duration>`` (``90s``, ``30m``,
  ``6h``, ``2d``); reaffirm refreshes the envelope by default.
"""

import re
from dataclasses import dataclass
from datetime import timedelta
from enum import StrEnum

from mind_runtime.contracts import StateDefinition

_TTL_RE = re.compile(r"^(\d+)([smhd])$")
_DURATION_UNITS = {"s": "seconds", "m": "minutes", "h": "hours", "d": "days"}


class ValidityKind(StrEnum):
    """How a state's temporal validity is governed."""

    INDEFINITE = "indefinite"
    TTL = "ttl"
    EVENT_ONLY = "event_only"


@dataclass(frozen=True, slots=True)
class ValidityPolicy:
    """The frozen validity policy for one state dimension."""

    kind: ValidityKind
    ttl: timedelta | None = None
    refresh_on_reaffirm: bool = True

    def __post_init__(self) -> None:
        if self.kind is ValidityKind.TTL:
            if self.ttl is None:
                raise ValueError("ttl policy requires a ttl duration")
            if self.ttl <= timedelta(0):
                raise ValueError("ttl must be positive")
        elif self.ttl is not None:
            raise ValueError("non-ttl policy forbids a ttl duration")


def parse_validity_policy(text: str | None) -> ValidityPolicy:
    """Parse the D4 policy grammar; unknown policies fail closed."""
    if text is None or text == "indefinite":
        return ValidityPolicy(kind=ValidityKind.INDEFINITE)
    if text == "event_only":
        return ValidityPolicy(kind=ValidityKind.EVENT_ONLY, refresh_on_reaffirm=False)
    if text.startswith("ttl:"):
        return ValidityPolicy(kind=ValidityKind.TTL, ttl=_parse_duration(text[4:]))
    raise ValueError(f"unknown validity policy: {text!r}")


def _parse_duration(text: str) -> timedelta:
    match = _TTL_RE.fullmatch(text.strip())
    if match is None:
        raise ValueError(f"invalid ttl duration: {text!r} (use e.g. 90s, 30m, 6h, 2d)")
    amount = int(match.group(1))
    unit = match.group(2)
    if amount == 0:
        raise ValueError("ttl duration must be positive")
    return timedelta(**{_DURATION_UNITS[unit]: amount})


class StateDefinitionRegistry:
    """The definitions authority for D4 state dimensions.

    Dimensions are registered once (fixtures/config); duplicate or
    conflicting registration fails closed so the reconciler never resolves
    against ambiguous definitions.
    """

    def __init__(self, definitions: tuple[StateDefinition, ...] = ()) -> None:
        self._definitions: dict[str, StateDefinition] = {}
        for definition in definitions:
            self.register(definition)

    def register(self, definition: StateDefinition) -> None:
        if definition.key in self._definitions:
            raise ValueError(f"state definition already registered: {definition.key}")
        self._definitions[definition.key] = definition

    def get(self, key: str) -> StateDefinition | None:
        return self._definitions.get(key)

    def require(self, key: str) -> StateDefinition:
        definition = self._definitions.get(key)
        if definition is None:
            raise ValueError(f"no state definition registered for {key!r}")
        return definition

    def validity_policy(self, key: str) -> ValidityPolicy:
        """Resolve the validity policy for a dimension (indefinite default)."""
        definition = self._definitions.get(key)
        if definition is None:
            return ValidityPolicy(kind=ValidityKind.INDEFINITE)
        return parse_validity_policy(definition.default_validity_policy)

    def all(self) -> tuple[StateDefinition, ...]:
        return tuple(self._definitions.values())
