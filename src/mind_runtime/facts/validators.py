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
        "summary",
        "derived_summary",
    }
)

_PRIOR_JUDGMENT_QUOTE_PATTERNS = (
    "你之前不是说",
    "你之前说",
    "你上次说",
    "你说过",
    "正如你所说",
    "you previously said",
    "you said earlier",
    "you said before",
    "you already told me",
    "as you said",
    "according to you",
)


def _is_quoting_prior_judgment(payload: object) -> bool:
    """Check if the payload contains quotes of assistant's prior judgments."""
    from collections.abc import Mapping

    if isinstance(payload, Mapping):
        if payload.get("quoted_prior_judgment") is True or payload.get("is_quoted_prior_judgment") is True:
            return True
        text = payload.get("text") or payload.get("content") or payload.get("message") or ""
        if isinstance(text, str):
            text_lower = text.lower()
            return any(pat.lower() in text_lower for pat in _PRIOR_JUDGMENT_QUOTE_PATTERNS)
    elif isinstance(payload, str):
        text_lower = payload.lower()
        return any(pat.lower() in text_lower for pat in _PRIOR_JUDGMENT_QUOTE_PATTERNS)
    return False


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

    def _walk_refs(
        self,
        curr: str,
        expected_scope: Scope,
        path: tuple[str, ...],
    ) -> tuple[bool, object | None]:
        """Walk reference graph detecting cycles and finding leaf Evidence."""
        if curr in path:
            return True, None
        new_path = path + (curr,)
        backend = self._backend

        ev_pair = backend.find_evidence(expected_scope, curr) if hasattr(backend, "find_evidence") else None
        if ev_pair:
            ev = ev_pair[0]
            if isinstance(ev.payload, dict):
                refs = ev.payload.get("evidence_refs") or ev.payload.get("source_refs")
                if isinstance(refs, (list, tuple)):
                    for r in refs:
                        if isinstance(r, str):
                            cycle, found = self._walk_refs(r, expected_scope, new_path)
                            if cycle:
                                return True, None
                            if found:
                                return False, found
            return False, ev

        ob = backend.find_observation(expected_scope, curr) if hasattr(backend, "find_observation") else None
        if ob:
            if ob.evidence_refs:
                for child_ref in ob.evidence_refs:
                    cycle, found = self._walk_refs(child_ref, expected_scope, new_path)
                    if cycle:
                        return True, None
                    if found:
                        return False, found
            return False, None

        return False, None

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

        # 3. Circular reference check
        cycle_detected, leaf_ev = self._walk_refs(ref, expected_scope, ())
        if cycle_detected:
            actual_runtime = evidence.origin_runtime_id if evidence else (observation.origin_runtime_id if observation else "")
            return ResolvedSource(
                ref=ref,
                root_evidence_id=None,
                admitted_observation_id=observation.id if observation else None,
                scope=expected_scope,
                origin_runtime_id=actual_runtime,
                source_kind=SourceKind.UNKNOWN,
                epistemic_mode=EpistemicMode.UNKNOWN,
                is_admitted=True,
                is_valid_for_longitudinal_support=False,
                denial_reason="circular_provenance_detected",
            )

        if leaf_ev is not None:
            evidence = leaf_ev

        root_ev_id = evidence.id if evidence else (observation.evidence_refs[0] if observation and observation.evidence_refs else None)
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

        # 4. Quoted prior judgment check
        is_quoted = False
        if evidence and _is_quoting_prior_judgment(evidence.payload):
            is_quoted = True
        elif observation and _is_quoting_prior_judgment(observation.value):
            is_quoted = True

        if is_quoted:
            return ResolvedSource(
                ref=ref,
                root_evidence_id=root_ev_id,
                admitted_observation_id=observation.id if observation else None,
                scope=expected_scope,
                origin_runtime_id=actual_runtime,
                source_kind=SourceKind.USER_REPORT,
                epistemic_mode=EpistemicMode.REPORTED,
                is_admitted=True,
                is_valid_for_longitudinal_support=False,
                denial_reason="quoted_prior_judgment_cannot_provide_independent_support",
                is_quoted_prior_judgment=True,
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

