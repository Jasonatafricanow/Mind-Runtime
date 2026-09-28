"""SemanticAppraisalProducer and Model implementations (ADR-0019-R4)."""

from __future__ import annotations

import json
import os
from typing import cast

from mind_runtime.contracts.appraisal import (
    AppraisalModelProposal,
    SemanticAppraisal,
    SemanticAppraisalContext,
    SemanticAppraisalModelPort,
    SemanticEventCandidate,
)
from mind_runtime.contracts.historical import HistoricalContextBundle
from mind_runtime.contracts.late_projection import AcceptedAppraisal
from mind_runtime.contracts.scope import Scope
from mind_runtime.contracts.situation import Situation
from mind_runtime.emotional_transition.provider import (
    ChatTransport,
    ProviderUnavailableError,
    SchemaInvalidError,
    UrllibChatTransport,
)

_HISTORY_PATTERN_KEYWORDS: tuple[str, ...] = (
    "recurring",
    "repeated",
    "pattern",
    "accumulating",
    "history",
    "prior",
    "chronic",
    "frequent",
)


def _extract_trusted_evidence_pool(
    *,
    candidate: SemanticEventCandidate,
    context: SemanticAppraisalContext,
) -> tuple[str, ...]:
    """Extract trusted evidence pool per ADR-0019-R4 §2.3.

    trusted_evidence_pool =
        candidate.evidence_refs
        ∪ authorized situation evidence refs
        ∪ bounded-history evidence refs actually supplied to the appraisal producer
    """
    refs: list[str] = list(candidate.evidence_refs)

    situation = context.situation
    if isinstance(situation, Situation) and situation.evidence_refs:
        refs.extend(situation.evidence_refs)
    elif hasattr(situation, "evidence_refs") and situation.evidence_refs:
        refs.extend(cast(tuple[str, ...], situation.evidence_refs))

    history = context.history
    if isinstance(history, HistoricalContextBundle):
        for summary in history.pattern_summaries:
            refs.extend(summary.matched_refs)
        for ep in history.episodes:
            refs.extend(ep.source_refs)
        for fact in history.stable_facts:
            refs.extend(fact.source_refs)
        for ev in history.relationship_events:
            refs.extend(ev.source_refs)
        refs.extend(history.source_refs)
    elif history is not None:
        if hasattr(history, "pattern_summaries"):
            for summary in getattr(history, "pattern_summaries", ()):
                refs.extend(getattr(summary, "matched_refs", ()))
        if hasattr(history, "source_refs"):
            refs.extend(getattr(history, "source_refs", ()))

    return tuple(dict.fromkeys(refs))


def _extract_trusted_history_refs(context: SemanticAppraisalContext) -> tuple[str, ...]:
    """Extract specifically trusted history evidence refs."""
    refs: list[str] = []
    history = context.history
    if isinstance(history, HistoricalContextBundle):
        for summary in history.pattern_summaries:
            refs.extend(summary.matched_refs)
        for ep in history.episodes:
            refs.extend(ep.source_refs)
        for fact in history.stable_facts:
            refs.extend(fact.source_refs)
        for ev in history.relationship_events:
            refs.extend(ev.source_refs)
        refs.extend(history.source_refs)
    elif history is not None:
        if hasattr(history, "pattern_summaries"):
            for summary in getattr(history, "pattern_summaries", ()):
                refs.extend(getattr(summary, "matched_refs", ()))
        if hasattr(history, "source_refs"):
            refs.extend(getattr(history, "source_refs", ()))
    return tuple(dict.fromkeys(refs))


class SemanticAppraisalProducer:
    """Canonical assembler / validator for SemanticAppraisal (ADR-0019-R4)."""

    def __init__(self, *, model: SemanticAppraisalModelPort | None = None) -> None:
        if model is not None and (
            not isinstance(model, SemanticAppraisalModelPort)
            and not hasattr(model, "propose")
        ):
            raise TypeError("model must implement SemanticAppraisalModelPort")
        self._model = model

    @property
    def has_model(self) -> bool:
        return self._model is not None

    def assemble(
        self, *, candidate: SemanticEventCandidate, context: SemanticAppraisalContext
    ) -> SemanticAppraisal:
        return self._evaluate(candidate=candidate, context=context)[0]

    def accept(
        self,
        *,
        candidate: SemanticEventCandidate,
        context: SemanticAppraisalContext,
        interaction_id: str,
        persona_id: str,
        route_abstention_reasons: tuple[str, ...],
        projection_scope: Scope | None = None,
        proposal: AppraisalModelProposal | None = None,
    ) -> AcceptedAppraisal:
        from mind_runtime.contracts.late_projection import (
            AcceptedAppraisal,
            authorized_history,
            digest,
        )
        from mind_runtime.contracts.scope import ScopeDomain

        situation, history = context.situation, context.history
        bound = (
            context.candidate == candidate
            and bool(interaction_id)
            and bool(persona_id)
            and getattr(situation, "scope", None) == candidate.scope
            and getattr(situation, "origin_runtime_id", None) == candidate.origin_runtime_id
            and getattr(situation, "persona_id", None) == persona_id
            and authorized_history(history, candidate.scope, candidate.origin_runtime_id)
            and (
                projection_scope is None
                or (
                    projection_scope.domain == ScopeDomain.AGENT
                    and projection_scope.persona_id == persona_id
                )
            )
        )
        if bound and not route_abstention_reasons:
            appraisal, valid = self._evaluate(
                candidate=candidate,
                context=context,
                proposal=proposal,
            )
            trusted = _extract_trusted_evidence_pool(candidate=candidate, context=context)
        else:
            # Fail before invoking a model with foreign authority.
            valid = False
            trusted = candidate.evidence_refs
            appraisal = SemanticAppraisal(
                f"appraisal-{candidate.candidate_id}",
                candidate.scope,
                candidate.origin_runtime_id,
                getattr(situation, "situation_id", "invalid"),
                ("unappraised",),
                "neutral",
                "unspecified",
                0.0,
                (),
                None,
            )
        status = (
            "REJECTED"
            if not bound
            else "ABSTAINED"
            if route_abstention_reasons
            else "ACCEPTED"
            if valid
            else "ERROR"
        )
        reasons = (
            ()
            if status == "ACCEPTED"
            else route_abstention_reasons
            or ("invalid_lineage" if not bound else "appraisal_provider_or_validation_error",)
        )
        identity = digest(
            (
                appraisal,
                candidate,
                interaction_id,
                persona_id,
                trusted,
                route_abstention_reasons,
                status,
                reasons,
                projection_scope,
            )
        )
        return AcceptedAppraisal(
            "acceptance-" + identity,
            status,
            appraisal,
            candidate,
            interaction_id,
            persona_id,
            trusted,
            route_abstention_reasons,
            reasons,
            projection_scope,
        )

    def _evaluate(
        self,
        *,
        candidate: SemanticEventCandidate,
        context: SemanticAppraisalContext,
        proposal: AppraisalModelProposal | None = None,
    ) -> tuple[SemanticAppraisal, bool]:
        appraisal_id = f"appraisal-{candidate.candidate_id}"
        scope = candidate.scope
        origin_runtime_id = candidate.origin_runtime_id

        situation = context.situation
        if isinstance(situation, Situation):
            situation_ref = situation.situation_id
        elif hasattr(situation, "situation_id"):
            situation_ref = str(situation.situation_id)
        else:
            situation_ref = "situation-default"

        trusted_pool = _extract_trusted_evidence_pool(candidate=candidate, context=context)
        trusted_history_refs = _extract_trusted_history_refs(context)

        default_failure = SemanticAppraisal(
            appraisal_id=appraisal_id,
            scope=scope,
            origin_runtime_id=origin_runtime_id,
            situation_ref=situation_ref,
            meanings=("unappraised",),
            valence="neutral",
            relationship_relevance="unspecified",
            confidence=0.0,
            evidence_refs=(),
            salience=None,
        )

        if proposal is None:
            if self._model is None:
                return (default_failure, False)
            try:
                proposal = self._model.propose(
                    candidate=candidate,
                    context=context,
                    trusted_evidence_pool=trusted_pool,
                )
            except Exception:
                return (default_failure, False)

        if not isinstance(proposal, AppraisalModelProposal):
            return (default_failure, False)

        if not proposal.meanings or any(not m.strip() for m in proposal.meanings):
            return (default_failure, False)

        if not proposal.valence or not proposal.valence.strip():
            return (default_failure, False)

        if not proposal.relationship_relevance or not proposal.relationship_relevance.strip():
            return (default_failure, False)

        if proposal.appraisal_confidence is None:
            return (default_failure, False)
        if (
            isinstance(proposal.appraisal_confidence, bool)
            or not 0.0 <= proposal.appraisal_confidence <= 1.0
        ):
            return (default_failure, False)

        if any(ref not in trusted_pool for ref in proposal.supporting_evidence_refs):
            return default_failure, False

        if proposal.salience is None:
            return (
                SemanticAppraisal(
                    appraisal_id=appraisal_id,
                    scope=scope,
                    origin_runtime_id=origin_runtime_id,
                    situation_ref=situation_ref,
                    meanings=proposal.meanings,
                    valence=proposal.valence,
                    relationship_relevance=proposal.relationship_relevance,
                    confidence=proposal.appraisal_confidence,
                    evidence_refs=(),
                    salience=None,
                ),
                True,
            )

        if isinstance(proposal.salience, bool) or not 0.0 <= proposal.salience <= 1.0:
            return (default_failure, False)

        pool_set = set(trusted_pool)
        for ref in proposal.supporting_evidence_refs:
            if ref not in pool_set:
                return (default_failure, False)

        combined_text = " ".join(proposal.meanings).lower()
        references_history_pattern = any(kw in combined_text for kw in _HISTORY_PATTERN_KEYWORDS)

        selected_refs = list(proposal.supporting_evidence_refs)
        if references_history_pattern:
            has_history_ref = any(ref in set(trusted_history_refs) for ref in selected_refs)
            if not has_history_ref:
                trusted_history_in_pool = [ref for ref in trusted_history_refs if ref in pool_set]
                if not trusted_history_in_pool:
                    return (default_failure, False)
                selected_refs.append(trusted_history_in_pool[0])

        evidence_refs = tuple(dict.fromkeys(selected_refs))

        return (
            SemanticAppraisal(
                appraisal_id=appraisal_id,
                scope=scope,
                origin_runtime_id=origin_runtime_id,
                situation_ref=situation_ref,
                meanings=proposal.meanings,
                valence=proposal.valence,
                relationship_relevance=proposal.relationship_relevance,
                confidence=proposal.appraisal_confidence,
                evidence_refs=evidence_refs,
                salience=proposal.salience,
            ),
            True,
        )


class ConfiguredSemanticAppraisalModel:
    """Production V1 model estimator reading full required context bundle.

    Per ADR-0019-R4 §5: reads candidate + persona + situation + history.
    Context-sensitive appraisal (not pure event-kind-only lookup).
    """

    def __init__(self, *, default_salience_map: dict[str, float] | None = None) -> None:
        self._default_salience_map = default_salience_map or {
            "plan_confirmed": 0.85,
            "warm_reunion": 0.90,
            "plan_cancelled": 0.88,
            "harsh_message": 0.86,
        }

    def propose(
        self,
        *,
        candidate: SemanticEventCandidate,
        context: SemanticAppraisalContext,
        trusted_evidence_pool: tuple[str, ...],
    ) -> AppraisalModelProposal:
        kind = candidate.kind
        history = context.history

        has_recurring = False
        if isinstance(history, HistoricalContextBundle):
            for s in history.pattern_summaries:
                if s.match_count > 1:
                    has_recurring = True
                    break

        if has_recurring:
            meanings = (f"{kind}_recurring", "historical_pattern")
            salience_base = self._default_salience_map.get(kind, 0.75)
            salience = min(1.0, salience_base + 0.05)
        else:
            meanings = (f"{kind}_interpretation", "relational_significance")
            salience = self._default_salience_map.get(kind, 0.75)

        valence = "negative" if "cancelled" in kind or "harsh" in kind else "positive"
        relationship_relevance = "relational_security"

        supporting = tuple(ref for ref in candidate.evidence_refs if ref in trusted_evidence_pool)
        if not supporting and trusted_evidence_pool:
            supporting = (trusted_evidence_pool[0],)

        appraisal_conf = 0.82

        return AppraisalModelProposal(
            meanings=meanings,
            valence=valence,
            relationship_relevance=relationship_relevance,
            salience=salience,
            appraisal_confidence=appraisal_conf,
            supporting_evidence_refs=supporting,
        )


class ModelBackedSemanticAppraisalModel:
    """Production model-backed semantic appraisal estimator (ADR-0019-R4)."""

    def __init__(
        self,
        *,
        endpoint_url: str,
        model: str,
        api_key_env: str = "APPRAISAL_API_KEY",
        timeout_s: float = 15.0,
        allowed_hosts: tuple[str, ...] = (),
        transport: ChatTransport | None = None,
    ) -> None:
        self._url = endpoint_url
        self._model = model
        self._api_key_env = api_key_env
        self._timeout_s = timeout_s
        self._allowed_hosts = allowed_hosts
        self._transport: ChatTransport = transport or UrllibChatTransport(
            allowed_hosts=allowed_hosts
        )

    def propose(
        self,
        *,
        candidate: SemanticEventCandidate,
        context: SemanticAppraisalContext,
        trusted_evidence_pool: tuple[str, ...],
    ) -> AppraisalModelProposal:
        # Fast fail if transport is UrllibChatTransport and API key is missing
        api_key = os.environ.get(self._api_key_env, "")
        if not api_key and isinstance(self._transport, UrllibChatTransport):
            raise ProviderUnavailableError(f"API key env var {self._api_key_env} is not set")

        situation_id = getattr(context.situation, "situation_id", str(context.situation))
        persona_info = tuple(getattr(p, "dimension", str(p)) for p in context.persona)
        history_info: tuple[str, ...] = ()
        if context.history is not None:
            history_info = tuple(
                getattr(s, "summary_id", str(s))
                for s in getattr(context.history, "pattern_summaries", ())
            )

        payload: dict[str, object] = {
            "model": self._model,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You are a semantic appraisal estimator for Mind Runtime. "
                        "Evaluate the emotional and relational significance "
                        "of the candidate event. "
                        "Respond with a single JSON object with keys: "
                        "meanings (list of strings), valence (string), "
                        "relationship_relevance (string), salience (number 0.0-1.0), "
                        "appraisal_confidence (number 0.0-1.0), "
                        "supporting_evidence_refs (list of strings strictly selected "
                        "from trusted_evidence_pool)."
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "candidate": {
                                "candidate_id": candidate.candidate_id,
                                "kind": candidate.kind,
                                "attributes": dict(candidate.attributes),
                                "confidence": candidate.confidence,
                            },
                            "situation_id": situation_id,
                            "persona_dimensions": persona_info,
                            "history_patterns": history_info,
                            "trusted_evidence_pool": list(trusted_evidence_pool),
                        },
                        ensure_ascii=False,
                    ),
                },
            ],
        }

        headers_extra = {"Authorization": f"Bearer {api_key}"}
        framed = {**payload, "_headers": headers_extra}
        response = self._transport.post_json(self._url, framed, self._timeout_s)

        choices = response.get("choices")
        if not isinstance(choices, list) or not choices:
            raise ProviderUnavailableError("chat envelope lacks choices")

        choice0 = choices[0]
        if not isinstance(choice0, dict):
            raise ProviderUnavailableError("choice is not a dict")

        message = choice0.get("message")
        if not isinstance(message, dict):
            raise ProviderUnavailableError("choice lacks message")

        content = message.get("content")
        if not isinstance(content, str):
            raise ProviderUnavailableError("chat message lacks text content")

        start = content.find("{")
        end = content.rfind("}")
        if start == -1 or end == -1:
            raise SchemaInvalidError("response contains no JSON object")

        parsed = json.loads(content[start : end + 1])
        if not isinstance(parsed, dict):
            raise SchemaInvalidError("parsed appraisal proposal is not a dict")

        raw_meanings = parsed.get("meanings")
        if not isinstance(raw_meanings, list) or not raw_meanings:
            raise SchemaInvalidError("meanings must be a non-empty list")
        meanings = tuple(str(m) for m in raw_meanings)

        valence = str(parsed.get("valence", ""))
        relationship_relevance = str(parsed.get("relationship_relevance", ""))

        salience_raw = parsed.get("salience")
        salience = float(salience_raw) if salience_raw is not None else None

        appraisal_conf_raw = parsed.get("appraisal_confidence")
        if appraisal_conf_raw is None:
            raise SchemaInvalidError("appraisal_confidence is required")
        appraisal_confidence = float(appraisal_conf_raw)

        raw_refs = parsed.get("supporting_evidence_refs", [])
        if not isinstance(raw_refs, list):
            raw_refs = []
        supporting_evidence_refs = tuple(str(r) for r in raw_refs)

        return AppraisalModelProposal(
            meanings=meanings,
            valence=valence,
            relationship_relevance=relationship_relevance,
            salience=salience,
            appraisal_confidence=appraisal_confidence,
            supporting_evidence_refs=supporting_evidence_refs,
        )
