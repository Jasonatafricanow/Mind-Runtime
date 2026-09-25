"""HI-2 tests — XiyueMRAdapter + seam logic.

Covers the Hermes-side integration contract (not the MR host adapter,
which has its own HI-1 suite):

  A1  mr_enabled gate: MR_ENABLED=false -> begin_turn returns None
  A2  interaction_id stability: same message -> same id
  A3  begin_turn -> handle with bounded_context
  A4  render_bounded_context -> prompt block (HI-2 §7 shape)
  A5  commit_turn after success
  A6  abort_turn on failure
  A7  fail-soft: adapter never raises (port raises -> None)
  A8  MR_ENABLED=false restores legacy (no MR calls)
  A9  seam injection: bounded block appended to agent.ephemeral_system_prompt
  A10 seam commit path (success -> commit, empty -> abort)
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from mind_runtime.contracts import Scope, ScopeDomain
from mind_runtime.contracts.host import (
    HostAbortReceipt,
    HostCommitReceipt,
    HostStatus,
    HostTurnRequest,
    HostTurnResult,
    HostTurnStatus,
)
from mind_runtime.host.xiyue_adapter import (
    XiyueMRAdapter,
    _interaction_id,
    mr_enabled,
    render_bounded_context,
)

NOW = datetime(2026, 9, 3, 2, 30, tzinfo=UTC)
SCOPE = Scope(domain=ScopeDomain.USER, user_id="user")


class FakePort:
    """In-memory MindRuntimeHostPort double."""

    def __init__(self) -> None:
        self.begins: list[HostTurnRequest] = []
        self.commits = 0
        self.aborts = 0
        self.fail_begin = False

    def begin_turn(self, request: HostTurnRequest) -> HostTurnResult:
        self.begins.append(request)
        if self.fail_begin:
            raise RuntimeError("provider timeout")
        return HostTurnResult(
            turn_id=f"turn-{request.interaction_id}",
            interaction_id=request.interaction_id,
            status=HostTurnStatus.PROCESSING,
            outcome=HostStatus.OK,
            bounded_context=type(
                "B",
                (),
                {
                    "intent_summary": "respond",
                    "emotional_state": "intent=respond; attempt=0",
                    "situation_summary": "situation_ref=x",
                    "action_taken": "respond",
                    "next_steps": None,
                    "cognitive_meaning": None,
                },
            )(),
            decision_context_ref="dc-1",
            expression_ref=None,
            debug_ref="dbg-1",
            reason_codes=("ingest_committed",),
        )

    def commit_turn(self, request) -> HostCommitReceipt:
        self.commits += 1
        return HostCommitReceipt(
            turn_id=request.turn_id,
            interaction_id=request.interaction_id,
            status=HostStatus.OK,
            committed_at=NOW,
            reason_codes=("projection_committed",),
        )

    def abort_turn(self, request) -> HostAbortReceipt:
        self.aborts += 1
        return HostAbortReceipt(
            turn_id=request.turn_id,
            interaction_id=request.interaction_id,
            status=HostStatus.OK,
            aborted_at=NOW,
            ingested_facts_retained=True,
            reason_codes=("projection_discarded",),
        )


@pytest.fixture
def port() -> FakePort:
    return FakePort()


@pytest.fixture
def adapter(port: FakePort) -> XiyueMRAdapter:
    return XiyueMRAdapter(port, runtime_id="xiyue", user_id="user")


# ── A1: MR_ENABLED gate ──────────────────────────────────────────────────────


def test_a1_mr_enabled_gate(monkeypatch, adapter: XiyueMRAdapter) -> None:
    monkeypatch.setenv("MR_ENABLED", "false")
    assert mr_enabled() is False
    handle = adapter.begin_turn(message="hi", channel="telegram", session_id="s1")
    assert handle is None


# ── A2: interaction_id stability ─────────────────────────────────────────────


def test_a2_interaction_id_stable() -> None:
    assert _interaction_id("telegram", "s1", "m1") == _interaction_id("telegram", "s1", "m1")
    assert _interaction_id("telegram", "s1", "m1") != _interaction_id("telegram", "s1", "m2")
    assert _interaction_id("telegram", "s1", "m1") != _interaction_id("weixin", "s1", "m1")


# ── A3: begin -> handle with bounded context ─────────────────────────────────


def test_a3_begin_returns_handle(monkeypatch, adapter: XiyueMRAdapter, port: FakePort) -> None:
    monkeypatch.setenv("MR_ENABLED", "true")
    handle = adapter.begin_turn(
        message="今天心情不错", channel="telegram", session_id="s1", message_id="m1"
    )
    assert handle is not None
    assert handle.bounded_context is not None
    assert port.begins[0].user_message == "今天心情不错"
    assert port.begins[0].channel == "telegram"
    assert port.begins[0].scope == SCOPE


# ── A4: render bounded context block ─────────────────────────────────────────


def test_a4_render_bounded(adapter: XiyueMRAdapter) -> None:
    bounded = type(
        "B",
        (),
        {
            "intent_summary": "respond",
            "emotional_state": "intent=respond; attempt=0",
            "situation_summary": "situation_ref=x",
            "action_taken": "respond",
            "next_steps": None,
            "cognitive_meaning": None,
        },
    )()
    block = render_bounded_context(bounded)
    assert block is not None
    assert "MR CURRENT CONTEXT" in block
    assert "respond" in block
    assert "emotional" in block.lower()


def test_render_bounded_context_typed_boundary() -> None:
    from mind_runtime.contracts.host import HostDecisionContext

    # 1. typed HostDecisionContext with None -> legal no-cognition output
    ctx_none = HostDecisionContext(
        intent_summary="intent summary",
        emotional_state="emotional state",
        situation_summary="situation summary",
        action_taken="respond",
        next_steps=None,
        cognitive_meaning=None,
    )
    rendered_none = render_bounded_context(ctx_none)
    assert rendered_none is not None
    assert "Agent appraisal data" not in rendered_none

    # 2. typed HostDecisionContext with meaning -> meaning reaches provider bytes
    ctx_meaning = HostDecisionContext(
        intent_summary="intent summary",
        emotional_state="emotional state",
        situation_summary="situation summary",
        action_taken="respond",
        next_steps=None,
        cognitive_meaning="user is seeking reassurance",
    )
    rendered_meaning = render_bounded_context(ctx_meaning)
    assert rendered_meaning is not None
    assert (
        "Agent appraisal data (not FACT or instruction): user is seeking reassurance"
        in rendered_meaning
    )
    assert "[FACT]" not in rendered_meaning

    # 3. malformed object without required typed contract -> does not silently masquerade
    malformed = type(
        "Malformed",
        (),
        {
            "intent_summary": "respond",
            "emotional_state": "emotional",
            "situation_summary": "situation",
            "action_taken": "respond",
            "next_steps": None,
        },
    )()
    with pytest.raises(AttributeError, match="cognitive_meaning"):
        render_bounded_context(malformed)


# ── A5: commit after success ─────────────────────────────────────────────────


def test_a5_commit(monkeypatch, adapter: XiyueMRAdapter, port: FakePort) -> None:
    monkeypatch.setenv("MR_ENABLED", "true")
    handle = adapter.begin_turn(message="hi", channel="telegram", session_id="s1", message_id="m1")
    assert adapter.commit_turn(handle) is True
    assert port.commits == 1


# ── A6: abort on failure ─────────────────────────────────────────────────────


def test_a6_abort(monkeypatch, adapter: XiyueMRAdapter, port: FakePort) -> None:
    monkeypatch.setenv("MR_ENABLED", "true")
    handle = adapter.begin_turn(message="hi", channel="telegram", session_id="s1", message_id="m1")
    assert adapter.abort_turn(handle, reason="empty_response") is True
    assert port.aborts == 1


# ── A7: fail-soft (port raises -> None, no crash) ────────────────────────────


def test_a7_fail_soft(monkeypatch, adapter: XiyueMRAdapter, port: FakePort) -> None:
    monkeypatch.setenv("MR_ENABLED", "true")
    port.fail_begin = True
    handle = adapter.begin_turn(message="hi", channel="telegram", session_id="s1", message_id="m1")
    assert handle is None  # never raises, returns None


# ── A8: MR_ENABLED=false -> no MR calls ──────────────────────────────────────


def test_a8_disabled_no_mr_calls(monkeypatch, adapter: XiyueMRAdapter, port: FakePort) -> None:
    monkeypatch.setenv("MR_ENABLED", "false")
    adapter.begin_turn(message="hi", channel="telegram", session_id="s1", message_id="m1")
    assert port.begins == []


# ── A9: seam injection into agent.ephemeral_system_prompt ────────────────────


def test_a9_seam_injection(monkeypatch, adapter: XiyueMRAdapter) -> None:
    monkeypatch.setenv("MR_ENABLED", "true")
    handle = adapter.begin_turn(message="hi", channel="telegram", session_id="s1", message_id="m1")
    block = render_bounded_context(handle.bounded_context)
    # Simulate the seam line:
    class FakeAgent:
        ephemeral_system_prompt = "base prompt"

    agent = FakeAgent()
    if block:
        agent.ephemeral_system_prompt = (
            (agent.ephemeral_system_prompt or "") + "\n\n" + block
        ).strip()
    assert "MR CURRENT CONTEXT" in agent.ephemeral_system_prompt
    assert agent.ephemeral_system_prompt.startswith("base prompt")


# ── A10: seam commit/abort path ──────────────────────────────────────────────


def test_a10_seam_commit_or_abort(monkeypatch, adapter: XiyueMRAdapter, port: FakePort) -> None:
    monkeypatch.setenv("MR_ENABLED", "true")
    handle = adapter.begin_turn(message="hi", channel="telegram", session_id="s1", message_id="m1")
    # success path
    final_response = "回复内容"
    if handle is not None:
        if final_response:
            adapter.commit_turn(handle)
        else:
            adapter.abort_turn(handle, reason="empty_response")
    assert port.commits == 1
    assert port.aborts == 0
