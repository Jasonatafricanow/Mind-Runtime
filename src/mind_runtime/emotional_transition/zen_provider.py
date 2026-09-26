"""Zen hy3-free provider for MR SemanticCandidateProvider.

Uses the opencode.ai/zen free anonymous endpoint (hy3-free) to classify an
observation into a typed SemanticEventCandidate. Uses curl_cffi to bypass
Cloudflare 1010. Falls back to abstention (no candidates) on any failure —
this is a *proposal* layer; MR's canonical gate decides trust.

Contract:
  * keyless by default (anonymous endpoint). If OPENCODE_API_KEY is set,
    the request includes a Bearer header.
  * bounded request schema: model + messages + max_tokens + temperature=0.
  * timeout behavior: configurable ``timeout_s`` (default 60s).
  * provider failure -> abstention (returns ()).
  * no state write, no numeric affect authority.  Pure proposal layer.
  * no canonical write authority.
"""

from __future__ import annotations

import json
import os
import time
from datetime import UTC, datetime
from typing import Any

from mind_runtime.contracts import (
    Observation,
    Scope,
    SemanticEventCandidate,
    Situation,
)
from mind_runtime.contracts.telemetry import TelemetrySinkProtocol

# Both vendor adapters implement the same open, bounded proposal contract.
from mind_runtime.emotional_transition.glm_provider import (
    SYSTEM_PROMPT,
    _validated_event_payload,
)
from mind_runtime.emotional_transition.semantic import (
    ProviderExecutionResult,
    SemanticCandidateProvider,
)

ZEN_URL = "https://opencode.ai/zen/v1/chat/completions"
ZEN_MODEL = os.environ.get("ZEN_MODEL", "hy3-free")


def _require_safe_host(url: str) -> None:
    """Refuse reserved/private IP hosts to prevent SSRF from poisoned configuration."""
    from urllib.parse import urlsplit

    host = urlsplit(url).hostname or ""
    if not host:
        raise ValueError("Zen endpoint URL missing hostname")
    import ipaddress

    try:
        ip = ipaddress.ip_address(host)
        if ip.is_private or ip.is_loopback or ip.is_reserved or ip.is_link_local or ip.is_multicast:
            raise ValueError(f"Zen endpoint host {host} is private/reserved (SSRF)")
    except ValueError as exc:
        if "does not appear to be an IPv4 or IPv6 address" in str(exc):
            return
        raise


class ZenHy3Provider(SemanticCandidateProvider):
    """Classify raw observations via the free zen hy3-free endpoint."""

    def __init__(
        self,
        *,
        model: str = ZEN_MODEL,
        timeout_s: float = 60.0,
        max_tokens: int = 320,
        telemetry_sink: TelemetrySinkProtocol | None = None,
    ) -> None:
        self._model = model
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
                provider_name="zen",
                model=self._model,
                latency_ms=0.0,
                success=True,
                explicit_abstain=False,
            )
        obs = observations[0]
        interaction_id = getattr(obs, "interaction_id", "unknown")
        text = (
            obs.value if isinstance(obs.value, str) else json.dumps(obs.value, ensure_ascii=False)
        )
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
        payload: dict[str, Any] = {}

        try:
            payload = self._classify(messages)
        except Exception as exc:
            success = False
            error_msg = str(exc)

        latency_ms = (time.perf_counter() - t0) * 1000

        # Zen does not expose token usage -> UNAVAILABLE
        if sink is not None:
            try:
                sink.record_llm_usage(
                    interaction_id=interaction_id,
                    stage="SEMANTIC_APPRAISAL",
                    provider="zen",
                    model=self._model,
                    prompt_tokens=None,
                    completion_tokens=None,
                    total_tokens=None,
                    usage_source="UNAVAILABLE",
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
                provider_name="zen",
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
                provider_name="zen",
                model=self._model,
                latency_ms=latency_ms,
                success=True,
                explicit_abstain=False,
                error="invalid_candidate_schema",
            )
        if kind in {"abstain", "none"}:
            return ProviderExecutionResult(
                candidates=(),
                provider_name="zen",
                model=self._model,
                latency_ms=latency_ms,
                success=True,
                explicit_abstain=True,
            )

        cand = SemanticEventCandidate(
            candidate_id=f"zen-{obs.id}",
            scope=scope,
            origin_runtime_id=obs.origin_runtime_id,
            kind=kind,
            attributes=attributes,
            confidence=confidence,
            evidence_refs=obs.evidence_refs,
        )
        return ProviderExecutionResult(
            candidates=(cand,),
            provider_name="zen",
            model=self._model,
            latency_ms=latency_ms,
            success=True,
            explicit_abstain=False,
        )

    def _classify(self, messages: list[dict[str, str]]) -> dict[str, Any]:
        body = {
            "model": self._model,
            "messages": messages,
            "max_tokens": self._max_tokens,
            "temperature": 0.0,
        }
        # Gate: validate URL host before any network I/O to prevent SSRF.
        _require_safe_host(ZEN_URL)
        # Lazy import so the module can be imported on systems without
        # curl_cffi installed (the factory must still be importable).
        from curl_cffi import requests as curl_requests

        headers = {"Content-Type": "application/json"}
        key = os.environ.get("OPENCODE_API_KEY", "")
        if key:
            headers["Authorization"] = "Bearer " + key
        # allow_redirects=False: curl_cffi would otherwise follow any
        # 30x redirect to a private address, defeating the
        # _require_safe_host check above.
        r = curl_requests.post(
            ZEN_URL,
            json=body,
            headers=headers,
            impersonate="chrome120",
            timeout=self._timeout_s,
            allow_redirects=False,
        )
        if r.status_code != 200:
            raise RuntimeError(f"Zen {r.status_code}: {r.text[:300]}")
        j = json.loads(r.text)
        msg = j.get("choices", [{}])[0].get("message", {})
        content = msg.get("content", "") or ""
        # strip markdown fences if present
        content = content.strip()
        if content.startswith("```"):
            content = content.split("```", 2)[1]
            content = content.lstrip("json").strip()
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            # try to find first {...} block
            start = content.find("{")
            end = content.rfind("}")
            if start != -1 and end != -1 and end > start:
                try:
                    return json.loads(content[start : end + 1])
                except json.JSONDecodeError:
                    pass
            raise RuntimeError(f"Zen returned non-JSON: {content[:200]}") from None
