"""C-4 transport-boundary contract tests (URLEgress / UrllibChatTransport).

The transport MUST refuse:
- non-https endpoints
- hostnames that resolve to loopback/private/link-local/reserved IPs
- framed._headers injecting transport-controlled headers
- framed._headers containing non-string entries

These cover all fail-closed paths required by the live provider path.
No network calls are made; URL resolution and header sanitization are
unit-tested directly.
"""

from __future__ import annotations

import pytest

from mind_runtime.emotional_transition.provider import (
    ProviderUnavailableError,
    SchemaInvalidError,
    UrllibChatTransport,
    _sanitize_transport_headers,
    validate_egress_url,
)


def test_egress_rejects_http() -> None:
    """Plain http is refused; provider endpoints must be https-only."""
    with pytest.raises(ProviderUnavailableError, match="must use https"):
        validate_egress_url("http://api.example.com/v1/chat")


def test_egress_rejects_loopback() -> None:
    """Loopback resolution is blocked at the egress layer."""
    with pytest.raises(ProviderUnavailableError, match="non-public"):
        validate_egress_url("https://127.0.0.1/v1/chat")


def test_egress_rejects_private_resolve() -> None:
    """A /etc/hosts-style private hostname is blocked."""
    with pytest.raises(ProviderUnavailableError, match="non-public"):
        validate_egress_url("https://localhost/v1/chat")


def test_egress_allowed_hosts_bypasses_resolution() -> None:
    """Operator allowlist skips DNS resolution (deliberate trust decision)."""
    validate_egress_url(
        "https://api.deepseek.com/v1/chat", allowed_hosts=("api.deepseek.com",)
    )


def test_egress_allowed_hosts_rejects_unlisted() -> None:
    """Unlisted host under allowed_hosts mode is refused."""
    with pytest.raises(ProviderUnavailableError, match="not in allowlist"):
        validate_egress_url(
            "https://other.example.com/v1/chat",
            allowed_hosts=("api.deepseek.com",),
        )


def test_transport_sanitizes_authorization_only() -> None:
    """_sanitize_transport_headers allows Authorization; drops anything else."""
    sanitized = _sanitize_transport_headers(
        {"_headers": {"Authorization": "Bearer test-token-xyz"}}
    )
    assert sanitized == {"Authorization": "Bearer test-token-xyz"}


def test_transport_rejects_host_header_injection() -> None:
    """Host/Content-Length/Connection in framed._headers is fail-closed."""
    for blocked in ("Host", "Content-Length", "Connection", "Transfer-Encoding"):
        with pytest.raises(SchemaInvalidError, match="transport-controlled"):
            _sanitize_transport_headers(
                {"_headers": {blocked: "value"}}
            )


def test_transport_drops_non_allowlist_headers_silently() -> None:
    """Unknown headers are dropped (not raised) to keep framed surface narrow."""
    sanitized = _sanitize_transport_headers(
        {"_headers": {"X-Custom-Vendor-Header": "foo"}}
    )
    assert sanitized == {}


def test_transport_rejects_non_string_header_entry() -> None:
    """A non-string value in _headers is rejected, not silently coerced."""
    with pytest.raises(SchemaInvalidError, match="must be strings"):
        _sanitize_transport_headers(
            {"_headers": {"Authorization": 12345}}
        )


def test_transport_rejects_non_mapping_headers() -> None:
    """framed._headers must be a dict, not a list or scalar."""
    with pytest.raises(SchemaInvalidError, match="must be a mapping"):
        _sanitize_transport_headers({"_headers": "Bearer token"})


def test_urllib_transport_passes_https_through_validation() -> None:
    """UrllibChatTransport.post_json enforces egress before any socket use."""
    transport = UrllibChatTransport(allowed_hosts=("api.deepseek.com",))
    with pytest.raises(ProviderUnavailableError, match="not in allowlist"):
        transport.post_json(
            "https://other.example.com/v1/chat",
            {"hello": "world"},
            0.01,
        )


def test_guarded_provider_translates_value_error_to_unavailable() -> None:
    """A transport that raises ValueError/TimeoutError becomes ProviderUnavailableError."""
    from datetime import UTC, datetime

    from mind_runtime.emotional_transition.provider import (
        EgressMode,
        GuardedSemanticProvider,
        ModelEgressPolicy,
        OpenAICompatibleProvider,
        ProviderUnavailableError,
    )
    from tests.support.fake_clock import FakeClock

    class _ErrorTransport:
        def post_json(
            self, url: str, payload: dict[str, object], timeout_s: float
        ) -> dict[str, object]:
            raise ValueError("malformed JSON response from stub")

    guarded = GuardedSemanticProvider(
        egress=ModelEgressPolicy(mode=EgressMode.DISABLED, provider_name="stub"),
        clock=FakeClock(datetime(2026, 8, 28, 12, 0, tzinfo=UTC)),
    )
    provider = OpenAICompatibleProvider(
        guarded=guarded,
        endpoint_url="https://api.example.com/v1/chat/completions",
        model="stub-model",
        api_key_env="STUB_KEY",
        transport=_ErrorTransport(),
        timeout_s=1.0,
        allowed_hosts=("api.example.com",),
    )
    with pytest.raises(ProviderUnavailableError, match="malformed envelope"):
        provider._post({"messages": []}, {})


def test_guarded_provider_folds_invalid_on_schema_error() -> None:
    """When the LLM response is parseable JSON but a candidate fails
    _resolve_handle_refs, the guarded counter increments and SchemaInvalidError
    propagates with fold_invalid() called exactly once."""
    from datetime import UTC, datetime

    from mind_runtime.contracts import (
        Scope,
        ScopeDomain,
        Situation,
    )
    from mind_runtime.emotional_transition.provider import (
        EgressMode,
        GuardedSemanticProvider,
        ModelEgressPolicy,
        OpenAICompatibleProvider,
        SchemaInvalidError,
    )
    from tests.emotional_transition.test_grounding_handle import make_observation
    from tests.support.fake_clock import FakeClock

    class _BadCandidateTransport:
        """Returns a valid chat envelope but the candidate uses a non-existent
        grounding handle; the inner resolver must raise SchemaInvalidError."""

        def post_json(
            self, url: str, payload: dict[str, object], timeout_s: float
        ) -> dict[str, object]:
            return {
                "choices": [
                    {
                        "message": {
                            "content": (
                                '{"candidates":[{"kind":"gratitude","confidence":0.5,'
                                '"evidence_refs":["o99"],"attributes":{}}]}'
                            )
                        }
                    }
                ]
            }

    guarded = GuardedSemanticProvider(
        egress=ModelEgressPolicy(
            mode=EgressMode.SANITIZED, provider_name="stub", known_names=()
        ),
        clock=FakeClock(datetime(2026, 8, 28, 12, 0, tzinfo=UTC)),
    )
    provider = OpenAICompatibleProvider(
        guarded=guarded,
        endpoint_url="https://api.example.com/v1/chat/completions",
        model="stub-model",
        api_key_env="STUB_KEY",
        transport=_BadCandidateTransport(),
        timeout_s=1.0,
        allowed_hosts=("api.example.com",),
    )
    obs = (make_observation("obs-1"),)
    user_scope = Scope(domain=ScopeDomain.USER, user_id="u1")
    situation = Situation(
        situation_id="sit-1",
        scope=user_scope,
        origin_runtime_id="xiyue",
        derived_facts=(),
        effective_state_ref="none",
        observed_at=datetime(2026, 8, 28, 12, 0, tzinfo=UTC),
        historical_context=None,
        persona_id=None,
        relationship_ids=(),
        evidence_refs=(),
    )
    with pytest.raises(SchemaInvalidError, match="not in this turn's grounding set"):
        provider.propose(
            observations=obs,
            context=situation,
            scope=user_scope,
        )
    assert guarded.metrics.get("schema_invalid", 0) >= 1
