"""The Hermes seam keeps Surface provider bytes and prose admission bounded."""

from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace

import pytest

from mind_runtime.contracts.host import HostProviderProseResult, HostStatus, HostTurnStatus
from mind_runtime.host.xiyue_adapter import (
    XiyueMRAdapter,
    _interaction_id,
    render_bounded_context,
)
from tests.host.test_xiyue_adapter import FakePort


def test_host_rejects_nontext_surface_provider_envelope():
    with pytest.raises(ValueError, match="SURFACE_V1 envelope must be text"):
        render_bounded_context(SimpleNamespace(provider_envelope_text=b"not text"))


def test_host_stable_identity_bounds_oversized_external_message_id():
    first = _interaction_id("chat", "session", "m" * 300)
    assert first.startswith("mr-") and len(first) == 27
    assert first == _interaction_id("chat", "session", "m" * 300)
    assert first != _interaction_id("chat", "session", "n" * 300)


def test_host_legacy_context_omits_absent_optional_fields():
    assert render_bounded_context(None) is None
    bounded = SimpleNamespace(
        intent_summary="respond",
        emotional_state="calm",
        situation_summary="user greeted",
        action_taken=None,
        next_steps="wait",
        cognitive_meaning=None,
    )
    text = render_bounded_context(bounded)
    assert "Next steps: wait" in text
    assert "Selected intent/action guidance" not in text


@pytest.mark.parametrize("forbidden", ["contact_seeking: high", "controls_id: leak"])
def test_host_rejects_internal_surface_data_in_provider_envelope(forbidden):
    with pytest.raises(AssertionError, match="Information isolation violation"):
        render_bounded_context(SimpleNamespace(provider_envelope_text=forbidden))


@pytest.mark.parametrize("status,allowed", [(HostStatus.OK, True), (HostStatus.FAILED, False)])
def test_host_prose_guard_requires_explicit_ok(monkeypatch, status, allowed):
    port = FakePort()
    adapter = XiyueMRAdapter(port)
    monkeypatch.setenv("MR_ENABLED", "true")
    handle = adapter.begin_turn(message="hello", channel="chat", session_id="s")
    assert handle is not None
    captured = []

    def guard(request):
        captured.append(request)
        return HostProviderProseResult(request.interaction_id, status)

    port.guard_provider_prose = guard
    assert adapter.guard_turn_prose(handle, "bounded reply") is allowed
    assert captured[0].turn_id == handle.turn_id
    assert captured[0].interaction_id == handle.interaction_id
    assert captured[0].prose == "bounded reply"


def test_host_prose_guard_fails_closed_on_port_exception(monkeypatch):
    port = FakePort()
    adapter = XiyueMRAdapter(port)
    monkeypatch.setenv("MR_ENABLED", "true")
    handle = adapter.begin_turn(message="hello", channel="chat", session_id="s")
    assert handle is not None

    def broken(_request):
        raise RuntimeError("guard unavailable")

    port.guard_provider_prose = broken
    assert adapter.guard_turn_prose(handle, "reply") is False
    assert adapter.guard_turn_prose(None, "reply") is False


def test_host_does_not_start_failed_turn(monkeypatch):
    port = FakePort()
    original = port.begin_turn

    def failed(request):
        return replace(original(request), status=HostTurnStatus.FAILED)

    port.begin_turn = failed
    monkeypatch.setenv("MR_ENABLED", "true")
    adapter = XiyueMRAdapter(port)
    assert adapter.begin_turn(message="hello", channel="chat", session_id="s") is None


@pytest.mark.parametrize("operation", ["commit_turn", "abort_turn"])
def test_host_terminal_delivery_fails_soft_if_authority_unavailable(monkeypatch, operation):
    port = FakePort()
    adapter = XiyueMRAdapter(port)
    monkeypatch.setenv("MR_ENABLED", "true")
    handle = adapter.begin_turn(message="hello", channel="chat", session_id="s")
    assert handle is not None

    def broken(_request):
        raise RuntimeError("canonical authority unavailable")

    setattr(port, operation, broken)
    assert getattr(adapter, operation)(handle) is False
    assert getattr(adapter, operation)(None) is False


@pytest.mark.parametrize("operation", ["commit_turn", "abort_turn"])
def test_host_terminal_delivery_requires_ok_receipt(monkeypatch, operation):
    port = FakePort()
    adapter = XiyueMRAdapter(port)
    monkeypatch.setenv("MR_ENABLED", "true")
    handle = adapter.begin_turn(message="hello", channel="chat", session_id="s")
    assert handle is not None
    original = getattr(port, operation)

    def degraded(request):
        return replace(original(request), status=HostStatus.DEGRADED)

    setattr(port, operation, degraded)
    assert getattr(adapter, operation)(handle) is False


def test_host_inspection_returns_none_when_port_fails():
    port = FakePort()
    adapter = XiyueMRAdapter(port)

    def broken(_request):
        raise RuntimeError("inspect unavailable")

    port.inspect = broken
    assert adapter.inspect("turn-1", include_trace=True) is None
