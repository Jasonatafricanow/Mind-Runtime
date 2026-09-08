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

from datetime import datetime, timezone
import json
import os
import time
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

GLM_URL = os.environ.get(
    "GLM_URL", "https://open.bigmodel.cn/api/paas/v4/chat/completions"
)
GLM_MODEL = os.environ.get("GLM_MODEL", "glm-4.5-air")

#: Canonical relational-event kinds — MUST match the certified manifest's
#: ``emotional_effects.rules[].event_kind`` values (runtime-config.json).
CANONICAL_EVENT_KINDS = (
    "plan_confirmed",
    "plan_cancelled",
    "warm_reunion",
    "harsh_message",
)

#: Prompt-level legal outputs: the four canonical kinds plus explicit
#: abstention. Anything else the model emits is rejected by the parser.
_ALLOWED_KINDS = frozenset(CANONICAL_EVENT_KINDS) | {"abstain"}

SYSTEM_PROMPT = (
    "You are a precise RELATIONAL EVENT classifier for a companion agent's "
    "internal cognitive runtime. You receive one raw user message and must "
    "identify which RELATIONSHIP EVENT happened — not the topic, not the "
    "sentiment. You must reply with ONLY a JSON object, no prose, no "
    "markdown, exactly: "
    '{"kind": "...", "confidence": 0.0-1.0, "attributes": {"...": "..."}}.\n\n'
    "Event kinds (the ONLY legal values):\n"
    "- plan_confirmed: user confirms or agrees to a shared plan / "
    "arrangement (e.g. '我们周六就这么定了')\n"
    "- plan_cancelled: user cancels or breaks a previously shared plan or "
    "promise (e.g. '对不起，今晚说好的计划取消了')\n"
    "- warm_reunion: user expresses warmth about being back together after "
    "time apart (e.g. '好久不见，终于又能和你说话了，我很想你')\n"
    "- harsh_message: user rejects or pushes the agent away harshly "
    "(e.g. '你真的很烦，别再来找我')\n\n"
    "If the message does not clearly constitute one of these relational "
    'events, abstain: reply {"kind": "abstain", "confidence": 0.0, '
    '"attributes": {}}.\n'
    "NEVER output any other kind — in particular the topic-level taxonomy "
    "(distress_sharing, ownership_complaint, request_favor, appreciation, "
    "playful_flirt, factual) is FORBIDDEN: it classifies topics, not "
    "relational events.\n"
    "Choose the SINGLE best fit. Confidence = how sure you are."
)


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
            "Classify into at most ONE kind from the taxonomy. Reply with ONLY JSON."
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
        completion_tokens = usage_info.get("completion_tokens") if isinstance(usage_info, dict) else None
        total_tokens = usage_info.get("total_tokens") if isinstance(usage_info, dict) else None
        usage_source = "ACTUAL" if (isinstance(prompt_tokens, int) and isinstance(total_tokens, int)) else "UNAVAILABLE"

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
                    occurred_at=datetime.now(timezone.utc),
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

        kind = payload.get("kind")
        if not isinstance(kind, str) or kind not in _ALLOWED_KINDS:
            return ProviderExecutionResult(
                candidates=(),
                provider_name="glm",
                model=self._model,
                latency_ms=latency_ms,
                success=True,
                explicit_abstain=False,
                raw_output=raw_content,
                error=f"unallowed_kind_{kind}",
            )
        if kind == "abstain":
            return ProviderExecutionResult(
                candidates=(),
                provider_name="glm",
                model=self._model,
                latency_ms=latency_ms,
                success=True,
                explicit_abstain=True,
                raw_output=raw_content,
            )

        try:
            confidence = float(payload.get("confidence", 0.0))
        except (TypeError, ValueError):
            confidence = 0.0
        if not 0.0 <= confidence <= 1.0:
            confidence = 0.0
        attrs_raw = payload.get("attributes") or {}
        if not isinstance(attrs_raw, dict):
            attrs_raw = {}
        attributes = tuple(
            sorted(
                (str(k), str(v)) for k, v in attrs_raw.items() if str(k) and str(v)
            )
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
