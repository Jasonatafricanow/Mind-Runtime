"""MR Fast Function V1 product-level fast-state lock (MR-FAST-FUNCTION-V1).

A fast state exists only when it provides a distinct runtime function.
Freezes the relationship between product-admitted affect states and their
concrete runtime consumers to prevent arbitrary emotion-taxonomy drift.
"""

from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Final


class FastFunctionKind(StrEnum):
    """The eight admitted product runtime functions for V1 fast states."""

    PROACTIVE_CONTACT = "PROACTIVE_CONTACT"
    PROACTIVE_SHARE = "PROACTIVE_SHARE"
    INQUIRY_EXPLORATION = "INQUIRY_EXPLORATION"
    BOUNDARY_CONFRONTATION = "BOUNDARY_CONFRONTATION"
    INITIATIVE_SUPPRESSION = "INITIATIVE_SUPPRESSION"
    ACTIVITY_WAKE = "ACTIVITY_WAKE"
    FOLLOW_UP_PERSISTENCE = "FOLLOW_UP_PERSISTENCE"
    COGNITIVE_REST_PRESSURE = "COGNITIVE_REST_PRESSURE"


class FastStateStatus(StrEnum):
    """Lifecycle status of an admitted fast state contract."""

    ACTIVE = "ACTIVE"
    REGISTERED_ONLY = "REGISTERED_ONLY"


@dataclass(frozen=True, slots=True)
class FastStateFunctionSpec:
    """Immutable functional contract for an admitted fast state."""

    state_key: str
    semantic_label: str
    function_kind: FastFunctionKind
    primary_consumer: str
    external_action_capable: bool
    status: FastStateStatus = FastStateStatus.ACTIVE
    product_label: str | None = None
    notes: str = ""

    def __post_init__(self) -> None:
        if not self.state_key.startswith("agent.affect."):
            raise ValueError(f"state_key must use 'agent.affect.' prefix: {self.state_key!r}")
        if not self.semantic_label.strip():
            raise ValueError("semantic_label must be non-empty")
        if not isinstance(self.function_kind, FastFunctionKind):
            raise ValueError(f"function_kind must be a FastFunctionKind: {self.function_kind!r}")
        if not self.primary_consumer.strip():
            raise ValueError("primary_consumer must be non-empty")
        if self.product_label is None:
            object.__setattr__(self, "product_label", self.semantic_label)


FAST_FUNCTION_V1_COUNT: Final[int] = 8

FOLLOW_UP_PERSISTENCE_NOT_FREQUENCY_INVARIANT: Final[str] = (
    "FOLLOW_UP_PERSISTENCE != FOLLOW_UP_FREQUENCY"
)

LONGING_CONTROLS_CONTACT_PRESSURE_NOT_FREQUENCY_INVARIANT: Final[str] = (
    "LONGING_CONTROLS_CONTACT_PRESSURE != LONGING_CONTROLS_SEND_FREQUENCY"
)

SHARING_URGE_CONTROLS_SHARE_PRESSURE_NOT_FREQUENCY_INVARIANT: Final[str] = (
    "SHARING_URGE_CONTROLS_SHARE_PRESSURE != SHARING_URGE_CONTROLS_SEND_FREQUENCY"
)
SHARING_URGE_CONTROLS_SHARE_PRESSURE_NOT_FREQUENCY: Final[str] = (
    SHARING_URGE_CONTROLS_SHARE_PRESSURE_NOT_FREQUENCY_INVARIANT
)

CURIOSITY_CONTROLS_INQUIRY_PRESSURE_NOT_FREQUENCY_INVARIANT: Final[str] = (
    "CURIOSITY_CONTROLS_INQUIRY_PRESSURE != CURIOSITY_CONTROLS_QUESTION_FREQUENCY"
)
CURIOSITY_CONTROLS_INQUIRY_PRESSURE_NOT_FREQUENCY: Final[str] = (
    CURIOSITY_CONTROLS_INQUIRY_PRESSURE_NOT_FREQUENCY_INVARIANT
)

ANGER_CONTROLS_BOUNDARY_PRESSURE_NOT_PERMISSION_INVARIANT: Final[str] = (
    "ANGER_CONTROLS_BOUNDARY_PRESSURE != ANGER_GRANTS_ACTION_PERMISSION"
)
ANGER_CONTROLS_BOUNDARY_PRESSURE_NOT_PERMISSION: Final[str] = (
    ANGER_CONTROLS_BOUNDARY_PRESSURE_NOT_PERMISSION_INVARIANT
)


def validate_diligence_anti_spam_invariant(
    *,
    diligence_pressure: float,
    base_cooldown_seconds: float,
    effective_cooldown_seconds: float,
) -> bool:
    """Explicit executable invariant: FOLLOW_UP_PERSISTENCE != FOLLOW_UP_FREQUENCY.

    Higher diligence_pressure preserves an unresolved item for reconsideration,
    but MUST NOT shorten outbound cooldown or directly inflate message frequency.
    """
    if effective_cooldown_seconds < base_cooldown_seconds:
        raise ValueError(
            f"Diligence anti-spam violation: effective cooldown ({effective_cooldown_seconds}s) "
            f"is shorter than base cooldown ({base_cooldown_seconds}s) under diligence_pressure={diligence_pressure}"
        )
    return True


def validate_longing_anti_spam_invariant(
    *,
    longing: float,
    base_cooldown_seconds: float,
    effective_cooldown_seconds: float,
) -> bool:
    """Explicit executable invariant: LONGING_CONTROLS_CONTACT_PRESSURE != LONGING_CONTROLS_SEND_FREQUENCY.

    Higher longing drives contact pressure (via contact_seeking in Surface),
    but MUST NOT shorten outbound cooldown or bypass ActionPolicy gating.
    """
    if effective_cooldown_seconds < base_cooldown_seconds:
        raise ValueError(
            f"Longing anti-spam violation: effective cooldown ({effective_cooldown_seconds}s) "
            f"is shorter than base cooldown ({base_cooldown_seconds}s) under longing={longing}"
        )
    return True


def validate_sharing_urge_anti_spam_invariant(
    *,
    sharing_urge: float,
    base_cooldown_seconds: float,
    effective_cooldown_seconds: float,
) -> bool:
    """Explicit executable invariant: SHARING_URGE_CONTROLS_SHARE_PRESSURE != SHARING_URGE_CONTROLS_SEND_FREQUENCY.

    Higher sharing_urge increases pressure to spontaneously share,
    but MUST NOT shorten outbound cooldown or bypass ActionPolicy gating.
    """
    if effective_cooldown_seconds < base_cooldown_seconds:
        raise ValueError(
            f"Sharing urge anti-spam violation: effective cooldown ({effective_cooldown_seconds}s) "
            f"is shorter than base cooldown ({base_cooldown_seconds}s) under sharing_urge={sharing_urge}"
        )
    return True


def validate_curiosity_anti_spam_invariant(
    *,
    curiosity: float,
    base_cooldown_seconds: float,
    effective_cooldown_seconds: float,
) -> bool:
    """Explicit executable invariant: CURIOSITY_CONTROLS_INQUIRY_PRESSURE != CURIOSITY_CONTROLS_QUESTION_FREQUENCY.

    Higher curiosity increases pressure to explore, inquire, or ask follow-up questions,
    but MUST NOT shorten outbound cooldown or bypass ActionPolicy gating.
    """
    if effective_cooldown_seconds < base_cooldown_seconds:
        raise ValueError(
            f"Curiosity anti-spam violation: effective cooldown ({effective_cooldown_seconds}s) "
            f"is shorter than base cooldown ({base_cooldown_seconds}s) under curiosity={curiosity}"
        )
    return True


def validate_anger_boundary_pressure_invariant(
    *,
    confrontation_score: float,
    action_permission: bool,
    policy_authorized: bool,
) -> bool:
    """Explicit executable invariant: ANGER_CONTROLS_BOUNDARY_PRESSURE != ANGER_GRANTS_ACTION_PERMISSION.

    Higher anger / confrontation pressure increases qualitative directness and expression guidance,
    but MUST NOT grant ActionPolicy permission without independent policy rule authorization.
    """
    if action_permission and not policy_authorized:
        raise ValueError(
            f"Anger boundary pressure invariant violation: action_permission granted without "
            f"independent policy authorization under confrontation_score={confrontation_score}"
        )
    return True


FAST_FUNCTION_V1_SPECS: Final[tuple[FastStateFunctionSpec, ...]] = (
    FastStateFunctionSpec(
        state_key="agent.affect.longing",
        semantic_label="longing",
        function_kind=FastFunctionKind.PROACTIVE_CONTACT,
        primary_consumer="Intent / proactive message path",
        external_action_capable=True,
        status=FastStateStatus.ACTIVE,
        notes=(
            "Invariant: LONGING_CONTROLS_CONTACT_PRESSURE != LONGING_CONTROLS_SEND_FREQUENCY. "
            "Longing drives contact_seeking and intent eligibility, but outbound send frequency "
            "remains strictly governed by ActionPolicy and cooldown."
        ),
    ),
    FastStateFunctionSpec(
        state_key="agent.affect.sharing_urge",
        semantic_label="sharing urge",
        function_kind=FastFunctionKind.PROACTIVE_SHARE,
        primary_consumer="Intent / share path",
        external_action_capable=True,
        status=FastStateStatus.ACTIVE,
        notes=(
            "Invariant: SHARING_URGE_CONTROLS_SHARE_PRESSURE != SHARING_URGE_CONTROLS_SEND_FREQUENCY. "
            "Higher sharing_urge increases pressure to spontaneously share a thought / observation / "
            "currently available content via dedicated Intent (spontaneous_share) and proactive ActionPolicy "
            "(proactive_share), while frequency remains strictly governed by ActionPolicy and cooldown."
        ),
    ),
    FastStateFunctionSpec(
        state_key="agent.affect.curiosity",
        semantic_label="curiosity",
        function_kind=FastFunctionKind.INQUIRY_EXPLORATION,
        primary_consumer="Intent / retrieval-or-question path",
        external_action_capable=True,
        status=FastStateStatus.ACTIVE,
        notes=(
            "Invariant: CURIOSITY_CONTROLS_INQUIRY_PRESSURE != CURIOSITY_CONTROLS_QUESTION_FREQUENCY. "
            "Higher curiosity increases pressure to explore / inquire via dedicated Intent (proactive_inquiry) "
            "and proactive ActionPolicy (proactive_question), while question frequency remains strictly "
            "governed by ActionPolicy and cooldown. Concrete V1 closes the question branch only; "
            "autonomous retrieval subsystem remains deferred."
        ),
    ),
    FastStateFunctionSpec(
        state_key="agent.affect.anger",
        semantic_label="anger / boundary pressure",
        function_kind=FastFunctionKind.BOUNDARY_CONFRONTATION,
        primary_consumer="existing Surface / Intent / expression path",
        external_action_capable=True,
        status=FastStateStatus.ACTIVE,
        notes=(
            "Invariant: ANGER_CONTROLS_BOUNDARY_PRESSURE != ANGER_GRANTS_ACTION_PERMISSION. "
            "Anger drives boundary confrontation pressure via Surface (confrontation -> qualitative directness), "
            "dampens expressive warmth and contact seeking, but has zero authority to grant ActionPolicy permission, "
            "initiate autonomous confrontation, or fabricate boundary violation evidence."
        ),
    ),
    FastStateFunctionSpec(
        state_key="agent.affect.sadness",
        semantic_label="sadness / low mood",
        function_kind=FastFunctionKind.INITIATIVE_SUPPRESSION,
        primary_consumer="existing initiative / expression path",
        external_action_capable=False,
        status=FastStateStatus.ACTIVE,
        notes="Suppresses initiative and dampens expressive spontaneity; does not initiate outbound action.",
    ),
    FastStateFunctionSpec(
        state_key="agent.affect.restlessness",
        semantic_label="activation / excitation",
        product_label="activation / excitation",
        function_kind=FastFunctionKind.ACTIVITY_WAKE,
        primary_consumer="CognitiveTicker / wake-reconsider path",
        external_action_capable=False,
        status=FastStateStatus.ACTIVE,
        notes="Existing restlessness key stays canonical for compatibility; V1 product interpretation broadened to activation/excitation.",
    ),
    FastStateFunctionSpec(
        state_key="agent.affect.diligence_pressure",
        semantic_label="responsibility pressure",
        function_kind=FastFunctionKind.FOLLOW_UP_PERSISTENCE,
        primary_consumer="unresolved-task/follow-up Intent reconsideration + ActionPolicy anti-repeat controls",
        external_action_capable=True,
        status=FastStateStatus.ACTIVE,
        notes="Invariant: FOLLOW_UP_PERSISTENCE != FOLLOW_UP_FREQUENCY. Responsibility pressure preserves relevance; frequency governed by ActionPolicy/cooldown.",
    ),
    FastStateFunctionSpec(
        state_key="agent.affect.fatigue",
        semantic_label="fatigue / cognitive load",
        function_kind=FastFunctionKind.COGNITIVE_REST_PRESSURE,
        primary_consumer="future homeostasis / cognitive-mode scheduler",
        external_action_capable=False,
        status=FastStateStatus.REGISTERED_ONLY,
        notes="Registered-only functional contract. Targets future daydream, sleep, offline consolidation, and dream modes; has no outbound-action consumer.",
    ),
)


class FastFunctionRegistry(Mapping[str, FastStateFunctionSpec]):
    """Frozen, typed registry for admitted fast state function specs."""

    def __init__(self, specs: tuple[FastStateFunctionSpec, ...] = FAST_FUNCTION_V1_SPECS) -> None:
        self._specs_by_key: dict[str, FastStateFunctionSpec] = {}
        self._specs_by_kind: dict[FastFunctionKind, FastStateFunctionSpec] = {}
        for spec in specs:
            if spec.state_key in self._specs_by_key:
                raise ValueError(f"duplicate state key in registry: {spec.state_key!r}")
            if spec.function_kind in self._specs_by_kind:
                raise ValueError(
                    f"duplicate function kind in registry: {spec.function_kind!r} "
                    f"already bound to {self._specs_by_kind[spec.function_kind].state_key!r}"
                )
            self._specs_by_key[spec.state_key] = spec
            self._specs_by_kind[spec.function_kind] = spec

    def __getitem__(self, key: str) -> FastStateFunctionSpec:
        return self._specs_by_key[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self._specs_by_key)

    def __len__(self) -> int:
        return len(self._specs_by_key)

    def get(
        self, key: str, default: FastStateFunctionSpec | None = None
    ) -> FastStateFunctionSpec | None:
        return self._specs_by_key.get(key, default)

    def require(self, key: str) -> FastStateFunctionSpec:
        spec = self._specs_by_key.get(key)
        if spec is None:
            raise KeyError(f"no fast function registered for state key: {key!r}")
        return spec

    def get_by_function(self, kind: FastFunctionKind) -> FastStateFunctionSpec | None:
        return self._specs_by_kind.get(kind)

    def require_by_function(self, kind: FastFunctionKind) -> FastStateFunctionSpec:
        spec = self._specs_by_kind.get(kind)
        if spec is None:
            raise KeyError(f"no fast function registered for function kind: {kind!r}")
        return spec


FAST_FUNCTION_V1_REGISTRY: Final[FastFunctionRegistry] = FastFunctionRegistry()
