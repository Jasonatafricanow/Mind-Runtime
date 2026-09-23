"""GLM semantic provider for MR SemanticCandidateProvider.

Classifies a raw user observation into a typed SemanticEventCandidate using
the GLM API (open.bigmodel.cn, OpenAI-compatible, Bearer key). GLM is one
of the optional backends selectable via ``MR_SEMANTIC_PROVIDER=glm`` — the
factory is the authoritative entry point.

Contract:
  * credential from environment only (``GLM_API_KEY``) — never hardcoded.
  * bounded request schema: model + messages + max_tokens + temperature=0.
  * timeout behavior: configurable ``timeout_s`` (default 60s).
  * provider failure -> abstention (returns ()).
  * no state write, no numeric affect authority.  Pure proposal layer.
  * URL host is validated against private/reserved ranges before network I/O.
  * with a missing API key the instance silently abstains on every call.
"""

from __future__ import annotations

import json
import os
import time
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlsplit

from mind_runtime.contracts import (
    Observation,
    Scope,
    SemanticEventCandidate,
    Situation,
)
from mind_runtime.contracts.telemetry import TelemetrySinkProtocol
from mind_runtime.emotional_transition.provider import validate_egress_url
from mind_runtime.emotional_transition.semantic import (
    ProviderExecutionResult,
    SemanticCandidateProvider,
)

GLM_URL = os.environ.get("GLM_URL", "https://open.bigmodel.cn/api/paas/v4/chat/completions")
GLM_MODEL = os.environ.get("GLM_MODEL", "glm-4.5-air")

#: Compatibility examples only; ADR-0027 does not make recipes an ontology.
CANONICAL_EVENT_KINDS = (
    "plan_confirmed",
    "plan_cancelled",
    "warm_reunion",
    "harsh_message",
)

SYSTEM_PROMPT = (
    "Propose at most ONE semantic event for the supplied user message. "
    "Reply with ONLY JSON, no prose or markdown, exactly: "
    '{"kind": "...", "confidence": 0.0, "attributes": {"...": "..."}}. '
    "Event kinds are open strings. These are non-exhaustive compatibility examples: "
    "plan_confirmed (confirms a shared plan), plan_cancelled (cancels a shared plan), "
    "warm_reunion (warm return after absence), harsh_message (harsh rejection). "
    "Use a novel descriptive kind when these examples do not express the event. "
    "Do not force an event into an example or guess an affect/state value. "
    "Kind must be a nonblank printable string of at most 128 characters. "
    "Confidence must be a JSON number from 0 to 1. Attributes must map nonblank "
    "printable strings to strings: at most 32 entries, keys at most 64 characters, "
    "values at most 1024 characters, combined keys and values at most 8192 characters. "
    "When no event is supported, reply "
    '{"kind": "abstain", "confidence": 0.0, "attributes": {}}.'
)


def _validated_event_payload(payload: object) -> tuple[str, float, tuple[tuple[str, str], ...]]:
    """Bound provider syntax independently of recipe or meaning vocabulary."""
    if not isinstance(payload, dict) or set(payload) != {"kind", "confidence", "attributes"}:
        raise ValueError("invalid_candidate_schema")

    def bounded_text(value: object, limit: int) -> bool:
        return (
            isinstance(value, str)
            and 0 < len(value) <= limit
            and bool(value.strip())
            and value.isprintable()
        )

    kind = payload["kind"]
    confidence = payload["confidence"]
    attributes = payload["attributes"]
    if not bounded_text(kind, 128):
        raise ValueError("invalid_candidate_schema")
    if (
        isinstance(confidence, bool)
        or not isinstance(confidence, (int, float))
        or not 0 <= confidence <= 1
    ):
        raise ValueError("invalid_candidate_schema")
    if not isinstance(attributes, dict) or len(attributes) > 32:
        raise ValueError("invalid_candidate_schema")
    if any(
        not bounded_text(key, 64) or not bounded_text(value, 1024)
        for key, value in attributes.items()
    ):
        raise ValueError("invalid_candidate_schema")
    if sum(len(key) + len(value) for key, value in attributes.items()) > 8192:
        raise ValueError("invalid_candidate_schema")
    return kind, float(confidence), tuple(sorted(attributes.items()))


class GLMSemanticProvider(SemanticCandidateProvider):
    """Classify raw observations via the GLM API."""

    def __init__(
        self,
        *,
        model: str = GLM_MODEL,
        endpoint_url: str = GLM_URL,
        api_key: str | None = None,
        timeout_s: float = 60.0,
        max_tokens: int = 200,
        telemetry_sink: TelemetrySinkProtocol | None = None,
    ) -> None:
        self._model = model
        self._endpoint_url = endpoint_url
        self._api_key = api_key or os.environ.get("GLM_API_KEY", "")
        self._timeout_s = timeout_s
        self._max_tokens = max_tokens
        self._telemetry_sink = telemetry_sink

    def propose(
        self,
        *,
        observations: tuple[Observation, ...],
        context: Situation,
        scope: Scope,
        telemetry_sink: TelemetrySinkProtocol | None = None,
        **kwargs: Any,
    ) -> tuple[SemanticEventCandidate, ...]:
        res = self.propose_with_telemetry(
            observations=observations,
            context=context,
            scope=scope,
            telemetry_sink=telemetry_sink,
        )
        return res.candidates

    def propose_with_telemetry(
        self,
        *,
        observations: tuple[Observation, ...],
        context: Situation,
        scope: Scope,
        telemetry_sink: TelemetrySinkProtocol | None = None,
    ) -> ProviderExecutionResult:
        if not observations:
            return ProviderExecutionResult(
                candidates=(),
                provider_name="glm",
                model=self._model,
                latency_ms=0.0,
                success=True,
                explicit_abstain=False,
            )
        if not self._api_key:
            return ProviderExecutionResult(
                candidates=(),
                provider_name="glm",
                model=self._model,
                latency_ms=0.0,
                success=False,
                explicit_abstain=False,
                error="missing_api_key",
            )
        obs = observations[0]
        interaction_id = getattr(obs, "interaction_id", "unknown")
        raw = obs.value
        if isinstance(raw, str):
            text = raw
        elif isinstance(raw, dict):
            text = json.dumps(dict(raw), ensure_ascii=False)
        else:
            text = str(raw)
        prompt = (
            "User message:\n"
            f"{text}\n\n"
            "Propose at most ONE event; novel kinds are allowed. Reply with ONLY JSON."
        )
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ]

        sink = telemetry_sink or self._telemetry_sink
        t0 = time.perf_counter()
        success = True
        error_msg: str | None = None
        usage_info: dict[str, Any] | None = None
        raw_content: str | None = None
        payload: dict[str, Any] = {}

        try:
            payload, usage_info, raw_content = self._classify_with_usage(messages)
        except Exception as exc:
            success = False
            error_msg = str(exc)

        latency_ms = (time.perf_counter() - t0) * 1000

        # Token usage accounting (Authority: llm_usage_records)
        prompt_tokens = usage_info.get("prompt_tokens") if isinstance(usage_info, dict) else None
        completion_tokens = (
            usage_info.get("completion_tokens") if isinstance(usage_info, dict) else None
        )
        total_tokens = usage_info.get("total_tokens") if isinstance(usage_info, dict) else None
        usage_source = (
            "ACTUAL"
            if (isinstance(prompt_tokens, int) and isinstance(total_tokens, int))
            else "UNAVAILABLE"
        )

        if sink is not None:
            try:
                sink.record_llm_usage(
                    interaction_id=interaction_id,
                    stage="SEMANTIC_APPRAISAL",
                    provider="glm",
                    model=self._model,
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    total_tokens=total_tokens,
                    usage_source=usage_source,
                    latency_ms=round(latency_ms, 2),
                    success=success,
                    retry_count=0,
                    error_message=error_msg,
                    occurred_at=datetime.now(UTC),
                )
            except Exception:
                pass

        if not success:
            return ProviderExecutionResult(
                candidates=(),
                provider_name="glm",
                model=self._model,
                latency_ms=latency_ms,
                success=False,
                error=error_msg,
            )

        try:
            kind, confidence, attributes = _validated_event_payload(payload)
        except ValueError:
            return ProviderExecutionResult(
                candidates=(),
                provider_name="glm",
                model=self._model,
                latency_ms=latency_ms,
                success=True,
                explicit_abstain=False,
                raw_output=raw_content,
                error="invalid_candidate_schema",
            )
        if kind in {"abstain", "none"}:
            return ProviderExecutionResult(
                candidates=(),
                provider_name="glm",
                model=self._model,
                latency_ms=latency_ms,
                success=True,
                explicit_abstain=True,
                raw_output=raw_content,
            )

        cand = SemanticEventCandidate(
            candidate_id=f"glm-{obs.id}",
            scope=scope,
            origin_runtime_id=obs.origin_runtime_id,
            kind=kind,
            attributes=attributes,
            confidence=confidence,
            evidence_refs=obs.evidence_refs,
        )
        return ProviderExecutionResult(
            candidates=(cand,),
            provider_name="glm",
            model=self._model,
            latency_ms=latency_ms,
            success=True,
            explicit_abstain=False,
            raw_output=raw_content,
        )

    def _classify_with_usage(
        self, messages: list[dict[str, str]]
    ) -> tuple[dict[str, Any], dict[str, Any] | None, str]:
        body = {
            "model": self._model,
            "messages": messages,
            "max_tokens": self._max_tokens,
            "temperature": 0.0,
            "thinking": {"type": "disabled"},
        }
        import urllib.request

        validate_egress_url(
            self._endpoint_url,
            allowed_hosts=(urlsplit(self._endpoint_url).hostname or "",),
        )
        req = urllib.request.Request(
            self._endpoint_url,
            data=json.dumps(body).encode(),
            headers={
                "Content-Type": "application/json",
                "Authorization": "Bearer " + self._api_key,
            },
        )

        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, req, fp, code, msg, hdrs, newurl):
                return None

        no_redirect_opener = urllib.request.build_opener(NoRedirect())
        with no_redirect_opener.open(req, timeout=self._timeout_s) as resp:
            j = json.loads(resp.read().decode())
        usage = j.get("usage")
        msg = j.get("choices", [{}])[0].get("message", {})
        content = msg.get("content", "") or ""
        content = content.strip()
        raw_content = content
        if content.startswith("```"):
            content = content.split("```", 2)[1]
            content = content.lstrip("json").strip()
        try:
            parsed = json.loads(content)
            return parsed, usage, raw_content
        except json.JSONDecodeError:
            start = content.find("{")
            end = content.rfind("}")
            if start != -1 and end != -1 and end > start:
                try:
                    parsed = json.loads(content[start : end + 1])
                    return parsed, usage, raw_content
                except json.JSONDecodeError:
                    pass
            raise RuntimeError(f"GLM returned non-JSON: {raw_content[:200]}") from None

    def _classify(self, messages: list[dict[str, str]]) -> dict[str, Any]:
        parsed, _, _ = self._classify_with_usage(messages)
        return parsed
