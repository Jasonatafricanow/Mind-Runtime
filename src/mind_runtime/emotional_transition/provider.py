"""Guarded semantic providers and the model egress policy (C3).

All model access for emotional transition flows through this module:

    SemanticRouter (existing seam)
        ↓ ambiguous language
    OpenAICompatibleProvider (guarded)   — the ONLY allowed entry point
        ├── ModelEgressPolicy   fail-closed gate on WHAT may leave
        ├── transport guards    https-only + SSRF-safe destination checks
        └── validation          strict candidate contract

Authority rules enforced here (dispatch §7/§14):
  * candidates carry semantic kind/attributes/confidence/refs ONLY — any
    numeric affect or relationship-state write is rejected SCHEMA_INVALID
    before it can reach the engine;
  * evidence_refs must be grounded in the supplied observation ids;
  * RecordedSemanticProvider feeds RECORDED validated artifacts back so
    replay stays deterministic without re-generation.

Metrics are plain counters read by callers; there is no dashboard.
"""

from __future__ import annotations

import ipaddress
import json
import re
import socket
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field, replace
from enum import StrEnum
from typing import Protocol, runtime_checkable

from mind_runtime.contracts import Observation, Scope, SemanticEventCandidate, Situation

#: Re-exported for loop/wiring code; validation lives with the router seam.
from mind_runtime.emotional_transition.semantic import (  # noqa: F401
    SemanticCandidateProvider,
)
from mind_runtime.providers.clock import Clock


class EgressMode(StrEnum):
    """What private context may cross a model boundary."""

    DISABLED = "disabled"
    SANITIZED = "sanitized"
    EXPLICITLY_ALLOWED_PRIVATE_CONTEXT = "explicitly_allowed_private_context"


@dataclass(frozen=True)
class ModelEgressPolicy:
    """Fail-closed model-egress gate (dispatch §9).

    DISABLED (default): not even a connection attempt is permitted.
    SANITIZED: person names are coded to <person:N> tokens inside text
    payloads handed outward; ids/scopes/scores pass unchanged.
    EXPLICITLY_ALLOWED_PRIVATE_CONTEXT: local/trusted deployments see full
    private semantics (ADR-0011: the private instance owns this choice).
    """

    mode: EgressMode = EgressMode.DISABLED
    known_names: tuple[str, ...] = ()
    provider_name: str = "unset"

    def __post_init__(self) -> None:
        if self.mode is not EgressMode.DISABLED and self.provider_name == "unset":
            raise ValueError("non-disabled egress policy must name its provider")


class ProviderUnavailableError(RuntimeError):
    """Egress refused the call, or the transport failed."""


class SchemaInvalidError(RuntimeError):
    """Provider output violated the validated-candidate contract."""


_RESERVED_ATTRIBUTE_MARKERS = ("affect", "trust", "relationship_state", "motivation")
_NUMERIC_PATTERN = re.compile(r"^-?\d+(\.\d+)?$")

KNOWN_SEMANTIC_KINDS = (
    "gratitude",
    "affection_expression",
    "plan_cancellation",
    "explicit_acceptance",
    "explicit_rejection",
    "distress_sharing",
    "achievement_sharing",
)


def validate_candidate(
    raw: object,
    *,
    scope: Scope,
    origin_runtime_id: str,
    allowed_refs: frozenset[str],
) -> SemanticEventCandidate:
    """Strictly validate one provider-proposed event candidate."""
    if not isinstance(raw, dict):
        raise SchemaInvalidError("candidate must be a JSON object")
    kind = raw.get("kind")
    if not isinstance(kind, str) or kind not in KNOWN_SEMANTIC_KINDS:
        raise SchemaInvalidError(f"unsupported semantic category: {kind!r}")
    confidence = raw.get("confidence")
    if isinstance(confidence, bool) or not isinstance(confidence, int | float):
        raise SchemaInvalidError("confidence must be a number")
    if not 0.0 <= float(confidence) <= 1.0:
        raise SchemaInvalidError("confidence out of bounds")
    refs = raw.get("evidence_refs")
    if not isinstance(refs, list) or not all(isinstance(ref, str) for ref in refs) or not refs:
        raise SchemaInvalidError("evidence_refs must be a non-empty string list")
    ungrounded = [ref for ref in refs if ref not in allowed_refs]
    if ungrounded:
        raise SchemaInvalidError(f"evidence_refs not grounded in supplied context: {ungrounded}")
    attributes_raw = raw.get("attributes", {})
    if not isinstance(attributes_raw, dict):
        raise SchemaInvalidError("attributes must be an object")
    attributes: list[tuple[str, str]] = []
    for key, value in attributes_raw.items():
        if not isinstance(key, str) or not isinstance(value, str):
            raise SchemaInvalidError("attributes must map strings to strings")
        lowered = key.lower()
        if any(marker in lowered for marker in _RESERVED_ATTRIBUTE_MARKERS):
            raise SchemaInvalidError(f"attribute {key!r} attempts an affect/state authority write")
        if _NUMERIC_PATTERN.match(value):
            raise SchemaInvalidError(f"attribute {key!r} carries a bare numeric value")
        attributes.append((key, value))
    return SemanticEventCandidate(
        candidate_id=f"semantic-provider-{kind}-{refs[0]}",
        scope=scope,
        origin_runtime_id=origin_runtime_id,
        kind=kind,
        attributes=tuple(sorted(attributes)),
        confidence=float(confidence),
        evidence_refs=tuple(refs),
    )


# Bounded handle protocol for LLM-grounded evidence refs (C-6).
# The LLM only ever sees turn-local handle strings ("o0", "o1", ...);
# canonical Observation ids never leave the host. Handles are
# turn-local, opaque to the LLM, and never reused across turns (the
# handle→id mapping is rebuilt from scratch for every provider call).
_HANDLE_PREFIX = "o"


def _grounding_handles(
    safe_observations: tuple[Observation, ...],
) -> tuple[dict[str, str], tuple[str, ...]]:
    """Build a turn-local handle→canonical-id mapping and the handle list.

    The mapping is intentionally one-shot: once the provider returns, the
    references in its output are resolved against this exact map. A new
    call to the provider produces a fresh map, so the LLM cannot smuggle
    cross-turn state by guessing handle strings.
    """
    if len(safe_observations) > 999:
        # Defense against pathological payloads (LLM prompt size);
        # turn it into schema-invalid so it is counted + refused.
        raise SchemaInvalidError(
            f"too many observations in one provider call: {len(safe_observations)}")
    handle_to_id: dict[str, str] = {}
    handles: list[str] = []
    for index, observation in enumerate(safe_observations):
        # INVARIANT: handles are generated from a monotonic enumerate index
        # prefixed by _HANDLE_PREFIX. The set of keys is therefore unique by
        # construction; the membership check below is a defensive guard
        # that becomes reachable only if the handle generation semantics
        # change (e.g. switching to a hash-based or content-derived scheme).
        # If you alter handle generation, the unreachable-branch claim here
        # must be re-verified and this `pragma` removed accordingly.
        handle = f"{_HANDLE_PREFIX}{index}"
        if handle in handle_to_id:  # pragma: no cover  see note above
            raise SchemaInvalidError(f"handle collision: {handle}")
        handle_to_id[handle] = observation.id
        handles.append(handle)
    return handle_to_id, tuple(handles)


def _is_valid_handle(value: object) -> bool:
    """A handle is a turn-local opaque token: 'o' + 1..999 digits."""
    return (isinstance(value, str) and len(value) > 1
            and value.startswith(_HANDLE_PREFIX)
            and value[1:].isdigit()
            and 0 <= int(value[1:]) < 1000)


def _resolve_handle_refs(
    item: object,
    handle_to_id: dict[str, str],
    *,
    scope: Scope,
    origin_runtime_id: str,
) -> SemanticEventCandidate:
    """Resolve handle refs to canonical IDs, then defer to validate_candidate.

    Resolution happens in a guarded window (before validate_candidate is
    invoked): any handle that does not map, any cross-turn attempt, any
    raw canonical id in the response — all fail closed. The LLM's
    evidence_refs field is the ONLY place where a non-canonical id can
    appear; after resolution the candidate carries canonical ids only.
    """
    if not isinstance(item, dict):
        raise SchemaInvalidError("candidate must be a JSON object")
    kind = item.get("kind")
    if not isinstance(kind, str) or kind not in KNOWN_SEMANTIC_KINDS:
        raise SchemaInvalidError(f"unsupported semantic category: {kind!r}")
    confidence = item.get("confidence")
    if isinstance(confidence, bool) or not isinstance(confidence, int | float):
        raise SchemaInvalidError("confidence must be a number")
    if not 0.0 <= float(confidence) <= 1.0:
        raise SchemaInvalidError("confidence out of bounds")
    handle_refs = item.get("evidence_refs")
    if not isinstance(handle_refs, list) or not handle_refs:
        raise SchemaInvalidError("evidence_refs must be a non-empty list of handles")
    if len(handle_refs) > len(handle_to_id):
        raise SchemaInvalidError(
            "evidence_refs longer than the handle set (one per observation)")
    canonical_refs: list[str] = []
    for ref in handle_refs:
        if not _is_valid_handle(ref):
            raise SchemaInvalidError(
                f"evidence_refs entries must be turn-local handles (e.g. 'o0'); "
                f"got {ref!r}")
        if ref not in handle_to_id:
            raise SchemaInvalidError(
                f"evidence_refs handle {ref!r} not in this turn's grounding set")
        canonical_id = handle_to_id[ref]
        if canonical_id in canonical_refs:
            # Duplicate handles resolve to the same canonical id: skip
            # silently so a noisy LLM does not lose its only citation.
            continue
        canonical_refs.append(canonical_id)
    attributes_raw = item.get("attributes", {})
    if not isinstance(attributes_raw, dict):
        raise SchemaInvalidError("attributes must be an object")
    attributes: list[tuple[str, str]] = []
    for key, value in attributes_raw.items():
        if not isinstance(key, str) or not isinstance(value, str):
            raise SchemaInvalidError("attributes must map strings to strings")
        lowered = key.lower()
        if any(marker in lowered for marker in _RESERVED_ATTRIBUTE_MARKERS):
            raise SchemaInvalidError(f"attribute {key!r} attempts an affect/state authority write")
        if _NUMERIC_PATTERN.match(value):
            raise SchemaInvalidError(f"attribute {key!r} carries a bare numeric value")
        attributes.append((key, value))
    # Once handle refs are resolved, defer to validate_candidate for
    # kind/confidence/attributes + candidate assembly (the canonical
    # contract is unchanged for all other adapters).
    resolved = {
        "kind": kind,
        "confidence": float(confidence),
        "evidence_refs": canonical_refs,
        "attributes": dict(attributes),
    }
    return validate_candidate(
        resolved,
        scope=scope,
        origin_runtime_id=origin_runtime_id,
        allowed_refs=frozenset(handle_to_id.values()),
    )


def _egress_text(text: str, policy: ModelEgressPolicy) -> str:
    if policy.mode is not EgressMode.SANITIZED:
        return text
    from mind_runtime.shadow.redaction import redact_text

    return redact_text(text, policy.known_names)


def _egress_observation(observation: Observation, policy: ModelEgressPolicy) -> Observation:
    """Provider-side view of one observation under the egress policy.

    Frozen payloads are Mapping-typed (FrozenMapping), so the sanitized
    copy is rebuilt as a plain mapping — replace() re-freezes it.
    """
    if policy.mode is not EgressMode.SANITIZED:
        return observation
    value = observation.value
    from collections.abc import Mapping

    if isinstance(value, Mapping) and isinstance(value.get("text"), str):
        return replace(
            observation,
            value={**value, "text": _egress_text(str(value["text"]), policy)},
        )
    return observation


def validate_egress_url(url: str, *, allowed_hosts: tuple[str, ...] = ()) -> None:
    """SSRF guard: https-only, resolve-and-block non-public destinations.

    Blocks loopback/private/link-local/reserved IPs and cloud-metadata
    style literals; redirects are never followed by the transport. When
    ``allowed_hosts`` is non-empty the hostname MUST be listed — operator
    allowlisting is a deliberate trust decision, so listed hosts skip the
    DNS-resolution probe (wildcard-DNS environments make probing noisy).
    """
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme != "https":
        raise ProviderUnavailableError("model endpoint must use https")
    host = parsed.hostname or ""
    if allowed_hosts:
        if host not in allowed_hosts:
            raise ProviderUnavailableError(f"model host {host!r} not in allowlist")
        return
    try:
        infos = socket.getaddrinfo(host, None)
    except OSError as exc:
        raise ProviderUnavailableError(f"cannot resolve model host: {exc}") from exc
    for info in infos:
        address = ipaddress.ip_address(info[4][0])
        if not address.is_global:
            raise ProviderUnavailableError(f"model host resolves to non-public address {address}")


@runtime_checkable
class ChatTransport(Protocol):
    """Minimal HTTP surface keeping the adapter testable offline."""

    def post_json(
        self, url: str, framed: dict[str, object], timeout_s: float
    ) -> dict[str, object]: ...


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Redirects are never followed across the model boundary."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[no-untyped-def]
        return None


class UrllibChatTransport:
    """Stdlib transport; no redirect following, strict destination checks."""

    def __init__(self, *, allowed_hosts: tuple[str, ...] = ()) -> None:
        self._allowed_hosts = allowed_hosts

    def post_json(
        self, url: str, framed: dict[str, object], timeout_s: float
    ) -> dict[str, object]:
        validate_egress_url(url, allowed_hosts=self._allowed_hosts)
        headers = _sanitize_transport_headers(framed)
        headers.setdefault("Content-Type", "application/json")
        body_payload = {k: v for k, v in framed.items() if k != "_headers"}

        request = urllib.request.Request(
            url,
            data=json.dumps(body_payload, default=_jsonable_default).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        opener = urllib.request.build_opener(_NoRedirect)
        try:
            with opener.open(request, timeout=timeout_s) as response:
                body = response.read()
        except urllib.error.HTTPError as exc:
            raise ProviderUnavailableError(f"provider http error: {exc.code}") from exc
        except urllib.error.URLError as exc:
            raise ProviderUnavailableError(f"provider unreachable: {exc.reason}") from exc
        try:
            parsed = json.loads(body.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise ProviderUnavailableError(f"malformed provider response: {exc}") from exc
        if not isinstance(parsed, dict):
            raise ProviderUnavailableError("chat response must be a JSON object")
        return parsed


# Headers that the transport layer controls. framed["_headers"] may carry
# only Authorization (and must never inject these — they'd let framed
# payload override transport-level semantics or smuggle smuggling via
# Host/Content-Length mismatches).
_TRANSPORT_CONTROLLED_HEADERS = frozenset(
    {"Host", "Content-Length", "Connection", "Transfer-Encoding",
     "Expect", "Upgrade", "TE", "Trailer", "Content-Encoding"})


def _sanitize_transport_headers(framed: dict[str, object]) -> dict[str, str]:
    """Return the transport-boundary headers that may leave the host.

    framed["_headers"] is the only allowed channel for per-request headers
    (currently just Authorization). The transport layer controls:
      * framing (Content-Type, length)
      * connection (Host, Content-Length, Connection, etc.)
    framed payload MUST NOT be able to override either. Anything outside the
    allow-list is dropped and reported via ValueError so callers don't get
    silent surprise behaviour.
    """
    raw = framed.get("_headers") or {}
    if not isinstance(raw, dict):
        raise SchemaInvalidError("framed._headers must be a mapping")
    sanitized: dict[str, str] = {}
    for key, value in raw.items():
        if not isinstance(key, str) or not isinstance(value, str):
            raise SchemaInvalidError("framed._headers entries must be strings")
        if key.lower() == "authorization":
            sanitized["Authorization"] = value
        elif key in _TRANSPORT_CONTROLLED_HEADERS:
            raise SchemaInvalidError(
                f"framed._headers must not inject transport-controlled header: {key}")
        # Any other header is dropped: the LLM semantic path has no need for
        # arbitrary HTTP headers, and we refuse to widen the surface.
    return sanitized


class GuardedSemanticProvider:
    """Shared guard/metrics core used by every concrete adapter."""

    def __init__(self, *, egress: ModelEgressPolicy, clock: Clock) -> None:
        self.policy = egress
        self._clock = clock
        self.metrics: dict[str, float] = {
            "provider_calls": 0.0,
            "provider_successes": 0.0,
            "provider_failures": 0.0,
            "schema_invalid": 0.0,
            "total_latency_ms": 0.0,
        }

    # -- helpers concrete adapters call -------------------------------------

    def require_egress_allowed(self) -> None:
        """Refuse before ANY bytes/calls happen when policy is disabled."""
        if self.policy.mode is EgressMode.DISABLED:
            self.metrics["provider_failures"] += 1
            raise ProviderUnavailableError(
                "model egress disabled by policy (mode=DISABLED); nothing sent"
            )

    def egress_observations(self, observations: tuple[Observation, ...]) -> tuple[Observation, ...]:
        return tuple(_egress_observation(o, self.policy) for o in observations)

    def fold_success(self, started: float) -> None:
        self.metrics["provider_calls"] += 1
        self.metrics["provider_successes"] += 1
        self.metrics["total_latency_ms"] += (time.perf_counter() - started) * 1000.0

    def fold_invalid(self, started: float) -> None:
        self.metrics["provider_calls"] += 1
        self.metrics["schema_invalid"] += 1
        self.metrics["total_latency_ms"] += (time.perf_counter() - started) * 1000.0


class OpenAICompatibleProvider:
    """First real adapter: chat-completions shape over guarded egress.

    Responsibilities end at transport, schema parsing, and error
    normalization — affect math, state writes, and policy live in Runtime.
    """

    def __init__(
        self,
        *,
        guarded: GuardedSemanticProvider,
        endpoint_url: str,
        model: str,
        api_key_env: str,
        transport: ChatTransport | None = None,
        timeout_s: float = 20.0,
        allowed_hosts: tuple[str, ...] = (),
    ) -> None:
        self._guarded = guarded
        self._url = endpoint_url
        self._model = model
        self._api_key_env = api_key_env
        self._transport: ChatTransport = transport or UrllibChatTransport(
            allowed_hosts=allowed_hosts
        )
        self._timeout_s = timeout_s

    def propose(
        self,
        *,
        observations: tuple[Observation, ...],
        context: Situation,
        scope: Scope,
    ) -> tuple[SemanticEventCandidate, ...]:
        # Disabled policy refuses BEFORE anything is built/sent (S9).
        self._guarded.require_egress_allowed()
        safe_observations = self._guarded.egress_observations(observations)
        started = time.perf_counter()
        import os

        # Bounded grounding handle protocol: the LLM only ever sees
        # turn-local handle strings (o0, o1, ...). canonical Observation
        # IDs NEVER leave the host. After the response, handles are
        # deterministically resolved to canonical IDs inside a guarded
        # window (refusing unknown / cross-turn / out-of-bounds handles)
        # before the canonical ids reach validate_candidate.
        handle_to_id, observation_handles = _grounding_handles(safe_observations)

        payload: dict[str, object] = {
            "model": self._model,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "Classify the latest user message into exactly one semantic "
                        f"kind from: {', '.join(KNOWN_SEMANTIC_KINDS)}. Reply with "
                        "JSON {\"candidates\":[{\"kind\",\"confidence\",\"evidence_refs\","
                        "\"attributes\"}]}. evidence_refs is a JSON array of the "
                        "GROUNDING HANDLES (o0, o1, ...) provided in the user "
                        "message — NOT raw observation ids. Pick ONE OR MORE "
                        "handles that justify the kind. attributes is a JSON object "
                        "mapping short string keys to short string values only."
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "grounding_handles": [
                                {"handle": handle, "payload": obs.value}
                                for handle, obs in zip(
                                    observation_handles, safe_observations, strict=True)
                            ],
                            "situation_id": context.situation_id,
                            "scope_domain": scope.domain.value,
                        },
                        ensure_ascii=False,
                        default=_jsonable_default,
                    ),
                },
            ],
        }
        headers_extra = {"Authorization": f"Bearer {os.environ.get(self._api_key_env, '')}"}
        response = self._post(payload, headers_extra)
        content = response.get("content")
        # Transport-contract guard: our own _post always yields str content;
        # a custom ChatTransport is the only way this could differ. Kept as
        # fail-closed shape checking, not reachable through our transport.
        if not isinstance(content, str):  # pragma: no cover - see note above
            raise SchemaInvalidError("chat reply lacks string content")
        try:
            # payload shaping happens inside the guarded accounting window:
            # malformed JSON counts as schema-invalid, never guessed around
            raw_items = _parse_candidates_payload(content)
        except SchemaInvalidError:
            self._guarded.fold_invalid(started)
            raise
        candidates: list[SemanticEventCandidate] = []
        for item in raw_items:
            try:
                resolved = _resolve_handle_refs(
                    item, handle_to_id, scope=scope,
                    origin_runtime_id=self._guarded.policy.provider_name)
            except SchemaInvalidError:
                self._guarded.fold_invalid(started)
                raise
            candidates.append(resolved)
        self._guarded.fold_success(started)
        return tuple(candidates)

    def _post(self, payload: dict[str, object], headers_extra: dict[str, str]) -> dict[str, object]:
        """One normalized transport round-trip via the injected transport."""

        framed = {**payload, "_headers": headers_extra}
        try:
            response = self._transport.post_json(self._url, framed, self._timeout_s)
        except (ValueError, TimeoutError) as exc:
            self._guarded.metrics["provider_failures"] += 1
            raise ProviderUnavailableError(f"malformed envelope from provider: {exc}") from exc
        except ProviderUnavailableError:
            self._guarded.metrics["provider_failures"] += 1
            raise
        choices = response.get("choices")
        if not isinstance(choices, list) or not choices:
            self._guarded.metrics["provider_failures"] += 1
            raise ProviderUnavailableError("chat envelope lacks choices")
        message = choices[0].get("message") if isinstance(choices[0], dict) else None
        content = message.get("content") if isinstance(message, dict) else None
        if not isinstance(content, str):
            self._guarded.metrics["provider_failures"] += 1
            raise ProviderUnavailableError("chat message lacks text content")
        return {"content": content}


def _jsonable_default(value: object) -> object:
    """JSON fallback for frozen runtime containers (FrozenMapping etc.)."""
    from collections.abc import Mapping

    if isinstance(value, Mapping):
        return dict(value)
    if isinstance(value, (set, frozenset)):
        return sorted(value)
    return str(value)


def _parse_candidates_payload(content: str) -> list[object]:
    """Extract + minimally shape the candidates array inside `content`."""
    start = content.find("{")
    end = content.rfind("}")
    if start == -1 or end == -1:
        raise SchemaInvalidError("provider reply contains no JSON object")
    try:
        decoded = json.loads(content[start : end + 1])
    except json.JSONDecodeError as exc:
        raise SchemaInvalidError(f"malformed JSON from provider: {exc}") from exc
    if not isinstance(decoded, dict) or not isinstance(decoded.get("candidates"), list):
        raise SchemaInvalidError("payload lacks candidates array")
    items = decoded["candidates"]
    if not items:
        raise SchemaInvalidError("empty candidates array")
    result: list[object] = list(items)
    return result


class StaticListProvider:
    """Local fixture/static-classifier adapter emitting validated batches."""

    def __init__(
        self,
        batches: list[list[dict[str, object]]],
        *,
        guarded: GuardedSemanticProvider | None = None,
        capture: list[tuple[Observation, ...]] | None = None,
        raise_error: Exception | None = None,
    ) -> None:
        self.batches = [list(batch) for batch in batches]
        self.guarded = guarded
        self.capture = capture
        self.raise_error = raise_error

    def propose(
        self,
        *,
        observations: tuple[Observation, ...],
        context: Situation,
        scope: Scope,
    ) -> tuple[SemanticEventCandidate, ...]:
        started = time.perf_counter()
        safe = self.guarded.egress_observations(observations) if self.guarded else observations
        if self.capture is not None:
            self.capture.append(safe)
        if self.raise_error is not None:
            # transport-style failure injected INSIDE the guarded window so
            # failure accounting matches real adapters
            if self.guarded:
                self.guarded.metrics["provider_calls"] += 1
                self.guarded.metrics["provider_failures"] += 1
                self.guarded.metrics["total_latency_ms"] += (time.perf_counter() - started) * 1000.0
            assert self.raise_error is not None
            raise self.raise_error
        batch = self.batches.pop(0) if self.batches else []
        allowed = frozenset(o.id for o in observations)
        try:
            candidates = tuple(
                validate_candidate(
                    item,
                    scope=scope,
                    origin_runtime_id="local",
                    allowed_refs=allowed,
                )
                for item in batch
            )
        except SchemaInvalidError:
            if self.guarded:
                self.guarded.fold_invalid(started)
            raise
        if self.guarded:
            self.guarded.fold_success(started)
        return candidates


class RecordedSemanticProvider:
    """Replay seam: feeds RECORDED validated artifacts; zero generation."""

    def __init__(self, batches: list[list[dict[str, object]]]) -> None:
        self.batches = [list(batch) for batch in batches]

    def propose(
        self,
        *,
        observations: tuple[Observation, ...],
        context: Situation,
        scope: Scope,
    ) -> tuple[SemanticEventCandidate, ...]:
        batch = self.batches.pop(0) if self.batches else []
        allowed = frozenset(o.id for o in observations)
        return tuple(
            validate_candidate(
                item, scope=scope, origin_runtime_id="recorded", allowed_refs=allowed
            )
            for item in batch
        )


@dataclass
class RouteMetrics:
    """Aggregate route/provider counters (C3.6); callers dump as they wish."""

    route_distribution: dict[str, int] = field(default_factory=dict)
    provider_metrics: dict[str, float] = field(default_factory=dict)
    fallbacks: int = 0

    def observe_route(self, path: str) -> None:
        self.route_distribution[path] = self.route_distribution.get(path, 0) + 1

    def as_dict(self) -> dict[str, object]:
        calls = self.provider_metrics.get("provider_calls", 0.0)
        invalid = self.provider_metrics.get("schema_invalid", 0.0)
        latency = self.provider_metrics.get("total_latency_ms", 0.0)
        failures = self.provider_metrics.get("provider_failures", 0.0)
        success = self.provider_metrics.get("provider_successes", 0.0)
        return {
            "route_distribution": dict(self.route_distribution),
            "provider_call_rate": calls,
            "provider_success_rate": (success / calls) if calls else 0.0,
            "provider_failure_rate": (failures / calls) if calls else 0.0,
            "schema_invalid_rate": (invalid / calls) if calls else 0.0,
            "fallback_rate": (self.fallbacks / calls) if calls else 0.0,
            "avg_latency_ms": latency / calls if calls else 0.0,
        }
