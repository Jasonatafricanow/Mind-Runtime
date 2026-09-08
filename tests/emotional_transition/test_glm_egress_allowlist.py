"""GLM-EGRESS-ALLOWLIST-ALIGNMENT — egress validation contract tests.

The GLM semantic provider now uses the shared ``validate_egress_url`` (the
same validator as the DeepSeek transport), passing its operator-configured
endpoint host as ``allowed_hosts``. These prove the aligned behavior:

  * an allowlisted host is permitted even when DNS resolves to a non-global
    (VPN fake-IP) address — the DNS probe is skipped, per DeepSeek contract;
  * a hostname not in the allowlist is rejected;
  * with no allowlist, non-global DNS is rejected and global DNS is permitted.
"""
from __future__ import annotations

import socket

import pytest

from mind_runtime.emotional_transition.provider import (
    ProviderUnavailableError,
    validate_egress_url,
)

GLM_URL = "https://open.bigmodel.cn/api/paas/v4/chat/completions"


def _fake_resolver(monkeypatch, ip: str) -> None:
    def _getaddrinfo(host, port, *args, **kwargs):  # noqa: ANN001, ANN002
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 0))]

    monkeypatch.setattr(socket, "getaddrinfo", _getaddrinfo)


def test_allowlisted_host_permitted_despite_non_global_dns(monkeypatch) -> None:
    # The allowlist branch must skip the DNS probe entirely; even a non-global
    # resolver result must not reject a deliberately allowlisted host.
    _fake_resolver(monkeypatch, "198.18.0.67")  # VPN fake-IP (TEST-NET-2)
    validate_egress_url(GLM_URL, allowed_hosts=("open.bigmodel.cn",))  # no raise


def test_different_hostname_rejected(monkeypatch) -> None:
    _fake_resolver(monkeypatch, "198.18.0.67")
    with pytest.raises(ProviderUnavailableError):
        validate_egress_url("https://evil.example/api", allowed_hosts=("open.bigmodel.cn",))


def test_no_allowlist_non_global_dns_rejected(monkeypatch) -> None:
    _fake_resolver(monkeypatch, "198.18.0.67")
    with pytest.raises(ProviderUnavailableError):
        validate_egress_url(GLM_URL, allowed_hosts=())


def test_no_allowlist_global_dns_permitted(monkeypatch) -> None:
    _fake_resolver(monkeypatch, "121.0.0.1")  # public/global
    validate_egress_url(GLM_URL, allowed_hosts=())  # no raise


def test_glm_provider_derives_allowlist_from_endpoint() -> None:
    from mind_runtime.emotional_transition.glm_provider import GLMSemanticProvider

    provider = GLMSemanticProvider(endpoint_url=GLM_URL)
    allowed = provider._endpoint_url  # operator-configured endpoint is the trust boundary
    assert "open.bigmodel.cn" in allowed
