"""Authority and Ownership validators for the factual ingest gate."""

from mind_runtime.contracts import AuthorityLevel, Evidence, ScopeDomain
from mind_runtime.providers.clock import Clock

AUTHORITY_CAPABLE_SOURCE_TYPES = frozenset({"user_message", "user_profile", "typed_event"})
INTERNALLY_DERIVED_SOURCE_TYPES = frozenset(
    {
        "assistant",
        "assistant_message",
        "assistant_output",
        "assistant_expression",
        "model_output",
        "derived_context",
        "internal_projection",
    }
)


class AuthorityError(Exception):
    """Evidence is not admissible as a user fact."""


class OwnershipError(Exception):
    """The writing runtime does not own the target scope."""


class AuthorityValidator:
    """Admit only reviewed authority-capable producer types."""

    def __init__(self, *, clock: Clock) -> None:
        self._clock = clock

    def is_user_fact(self, evidence: Evidence) -> bool:
        return (
            evidence.source_type in AUTHORITY_CAPABLE_SOURCE_TYPES
            and evidence.authority_level is not AuthorityLevel.NONE
        )

    def require_user_fact(self, evidence: Evidence) -> None:
        if evidence.source_type not in AUTHORITY_CAPABLE_SOURCE_TYPES:
            classification = (
                "internally derived"
                if evidence.source_type in INTERNALLY_DERIVED_SOURCE_TYPES
                else "unregistered"
            )
            raise AuthorityError(
                f"{classification} source type cannot become a user fact: "
                f"{evidence.source_type} ({evidence.id})"
            )
        if evidence.authority_level is AuthorityLevel.NONE:
            raise AuthorityError(
                f"evidence with NONE authority cannot become a user fact: {evidence.id}"
            )


class OwnershipValidator:
    """Require runtime and Persona authority for Persona-owned scopes."""

    def __init__(self, *, clock: Clock) -> None:
        self._clock = clock

    def require_owner(
        self,
        evidence: Evidence,
        *,
        writing_runtime: str,
        writing_persona_id: str | None,
    ) -> None:
        scope = evidence.scope
        if scope.domain is ScopeDomain.AGENT:
            if scope.agent_id != writing_runtime:
                raise OwnershipError(
                    f"runtime {writing_runtime} cannot write agent scope owned by {scope.agent_id}"
                )
            if scope.persona_id != writing_persona_id:
                raise OwnershipError(
                    f"writing persona {writing_persona_id!r} cannot write persona "
                    f"scope owned by {scope.persona_id!r}"
                )
        elif scope.domain is ScopeDomain.RELATIONSHIP:
            if scope.persona_id != writing_persona_id:
                raise OwnershipError(
                    f"writing persona {writing_persona_id!r} cannot write relationship "
                    f"scope owned by {scope.persona_id!r}"
                )
        elif writing_persona_id is not None:
            raise OwnershipError(f"{scope.domain.value} scope forbids writing persona authority")
