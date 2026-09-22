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


class SourceResolver:
    """Resolve and validate source references against the FactBackend."""

    def __init__(self, backend: object) -> None:
        self._backend = backend

    def resolve(
        self,
        ref: str,
        *,
        expected_scope: Scope,
        expected_runtime: str | None = None,
    ) -> ResolvedSource:
        from mind_runtime.contracts.trace import EpistemicMode, ResolvedSource, SourceKind

        backend = self._backend
        # 1. Try direct lookup in expected_scope
        ev_pair = backend.find_evidence(expected_scope, ref) if hasattr(backend, "find_evidence") else None
        ob = backend.find_observation(expected_scope, ref) if hasattr(backend, "find_observation") else None

        # 2. If not found, check across all scopes to distinguish scope_mismatch from ref_not_found
        if ev_pair is None and ob is None:
            all_ev = [ev for ev, _ in backend.load_evidence() if ev.id == ref] if hasattr(backend, "load_evidence") else []
            all_ob = [o for o in backend.load_observations() if o.id == ref] if hasattr(backend, "load_observations") else []
            if all_ev or all_ob:
                found_scope = all_ev[0].scope if all_ev else all_ob[0].scope
                found_rt = all_ev[0].origin_runtime_id if all_ev else all_ob[0].origin_runtime_id
                return ResolvedSource(
                    ref=ref,
                    root_evidence_id=all_ev[0].id if all_ev else (all_ob[0].evidence_refs[0] if all_ob[0].evidence_refs else None),
                    admitted_observation_id=all_ob[0].id if all_ob else None,
                    scope=found_scope,
                    origin_runtime_id=found_rt,
                    source_kind=SourceKind.UNKNOWN,
                    epistemic_mode=EpistemicMode.UNKNOWN,
                    is_admitted=True,
                    is_valid_for_longitudinal_support=False,
                    denial_reason="scope_mismatch",
                )
            return ResolvedSource(
                ref=ref,
                root_evidence_id=None,
                admitted_observation_id=None,
                scope=expected_scope,
                origin_runtime_id=expected_runtime or "",
                source_kind=SourceKind.UNKNOWN,
                epistemic_mode=EpistemicMode.UNKNOWN,
                is_admitted=False,
                is_valid_for_longitudinal_support=False,
                denial_reason="ref_not_found",
            )

        evidence = ev_pair[0] if ev_pair else None
        observation = ob
        root_ev_id = evidence.id if evidence else (observation.evidence_refs[0] if observation and observation.evidence_refs else None)
        if root_ev_id and not evidence and hasattr(backend, "find_evidence"):
            ev_pair2 = backend.find_evidence(expected_scope, root_ev_id)
            if ev_pair2:
                evidence = ev_pair2[0]

        actual_runtime = evidence.origin_runtime_id if evidence else (observation.origin_runtime_id if observation else "")
        if expected_runtime and actual_runtime != expected_runtime:
            return ResolvedSource(
                ref=ref,
                root_evidence_id=root_ev_id,
                admitted_observation_id=observation.id if observation else None,
                scope=expected_scope,
                origin_runtime_id=actual_runtime,
                source_kind=SourceKind.UNKNOWN,
                epistemic_mode=EpistemicMode.UNKNOWN,
                is_admitted=True,
                is_valid_for_longitudinal_support=False,
                denial_reason="runtime_mismatch",
            )

        source_type = evidence.source_type if evidence else "unknown"
        authority = evidence.authority_level if evidence else AuthorityLevel.NONE

        if source_type in INTERNALLY_DERIVED_SOURCE_TYPES:
            return ResolvedSource(
                ref=ref,
                root_evidence_id=root_ev_id,
                admitted_observation_id=observation.id if observation else None,
                scope=expected_scope,
                origin_runtime_id=actual_runtime,
                source_kind=SourceKind.DERIVED,
                epistemic_mode=EpistemicMode.INFERRED,
                is_admitted=True,
                is_valid_for_longitudinal_support=False,
                denial_reason="derived_source_cannot_support_longitudinal",
            )

        if source_type in ("user_message", "user_profile"):
            source_kind = SourceKind.USER_REPORT
            epistemic_mode = EpistemicMode.REPORTED
            valid = (authority is not AuthorityLevel.NONE)
            denial = None if valid else "authority_level_none"
        elif source_type == "typed_event":
            source_kind = SourceKind.EXTERNAL_OBSERVATION
            epistemic_mode = EpistemicMode.OBSERVED
            valid = (authority is not AuthorityLevel.NONE)
            denial = None if valid else "authority_level_none"
        else:
            source_kind = SourceKind.UNKNOWN
            epistemic_mode = EpistemicMode.UNKNOWN
            valid = False
            denial = f"unsupported_source_type_{source_type}"

        return ResolvedSource(
            ref=ref,
            root_evidence_id=root_ev_id,
            admitted_observation_id=observation.id if observation else None,
            scope=expected_scope,
            origin_runtime_id=actual_runtime,
            source_kind=source_kind,
            epistemic_mode=epistemic_mode,
            is_admitted=True,
            is_valid_for_longitudinal_support=valid,
            denial_reason=denial,
        )

