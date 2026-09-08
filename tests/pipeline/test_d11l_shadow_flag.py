"""D11L Evidence #3 — shadow feature flag default-OFF proofs.

Proves MIND_RUNTIME_SHADOW_ENABLED gate is fail-closed:
  * absent env / unknown values => disabled
  * explicit constructor override wins over env
  * run_shadow() refuses when disabled
  * run_shadow() proceeds past the gate when enabled (next failure is
    missing-turn, not the gate)
"""

from datetime import UTC, datetime

import pytest

from mind_runtime.pipeline.orchestrator import (
    ShadowModeDisabled,
    TurnOrchestrator,
    resolve_shadow_enabled,
)
from mind_runtime.pipeline.trace import TraceRecorder
from tests.support.fake_clock import FakeClock


def _orchestrator(shadow_enabled: bool | None = None) -> TurnOrchestrator:
    return TurnOrchestrator(
        clock=FakeClock(datetime(2026, 8, 19, 12, 0, tzinfo=UTC)),
        trace=TraceRecorder(),
        shadow_enabled=shadow_enabled,
    )


# ── pure gate resolution (unit) ────────────────────────────────────────────


@pytest.mark.parametrize(
    "raw_env, expected",
    [
        (None, False),  # env absent
        ("", False),  # empty
        ("0", False),  # explicit zero
        ("false", False),  # false
        ("FALSE", False),  # false (upper)
        ("off", False),  # off
        ("random-junk", False),  # unknown value
        ("1", True),  # on
        ("true", True),  # on
        ("TRUE", True),  # on (upper)
        ("yes", True),  # on
        ("on", True),  # on
    ],
)
def test_resolve_shadow_enabled_values(raw_env: str | None, expected: bool) -> None:
    assert resolve_shadow_enabled(None, raw_env) is expected


def test_resolve_explicit_wins_over_env() -> None:
    assert resolve_shadow_enabled(True, None) is True
    assert resolve_shadow_enabled(True, "0") is True
    assert resolve_shadow_enabled(False, "1") is False
    assert resolve_shadow_enabled(False, None) is False


# ── orchestrator integration (fail-closed) ────────────────────────────────


def test_default_off_when_env_absent(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MIND_RUNTIME_SHADOW_ENABLED", raising=False)
    orch = _orchestrator()
    assert orch.shadow_enabled is False
    with pytest.raises(ShadowModeDisabled):
        orch.run_shadow()


def test_env_value_1_enables(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MIND_RUNTIME_SHADOW_ENABLED", "1")
    orch = _orchestrator()
    assert orch.shadow_enabled is True
    # gate passed: now the failure is missing-turn, not the gate
    with pytest.raises(Exception) as ei:
        orch.run_shadow()
    assert not isinstance(ei.value, ShadowModeDisabled)


def test_env_false_disables(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MIND_RUNTIME_SHADOW_ENABLED", "0")
    orch = _orchestrator()
    assert orch.shadow_enabled is False
    with pytest.raises(ShadowModeDisabled):
        orch.run_shadow()


def test_explicit_false_overrides_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MIND_RUNTIME_SHADOW_ENABLED", "1")
    orch = _orchestrator(shadow_enabled=False)
    assert orch.shadow_enabled is False
    with pytest.raises(ShadowModeDisabled):
        orch.run_shadow()


def test_explicit_true_overrides_missing_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MIND_RUNTIME_SHADOW_ENABLED", raising=False)
    orch = _orchestrator(shadow_enabled=True)
    assert orch.shadow_enabled is True


def test_default_off_does_not_affect_normal_run(monkeypatch: pytest.MonkeyPatch) -> None:
    """D11S regression guard: plain runs remain fully functional w/o gate."""
    monkeypatch.delenv("MIND_RUNTIME_SHADOW_ENABLED", raising=False)
    orch = _orchestrator()
    assert orch.shadow_enabled is False
    # beginning a turn and running should fail on missing turn content,
    # never on the ShadowModeDisabled gate.
    with pytest.raises(Exception) as ei:
        orch.run()
    assert not isinstance(ei.value, ShadowModeDisabled)


def test_run_shadow_enabled_executes_the_real_turn() -> None:
    """Gate-ON + begun turn: run_shadow mirrors one full lifecycle turn."""
    from mind_runtime.contracts import Interaction, InteractionStatus, Scope, ScopeDomain
    from mind_runtime.pipeline.orchestrator import TurnState

    orch = _orchestrator(shadow_enabled=True)
    interaction = Interaction(
        interaction_id="it-shadow-run",
        scope=Scope(domain=ScopeDomain.USER, user_id="user-1"),
        channel="telegram",
        session_id="session-1",
        turn_id="turn-1",
        started_at=datetime(2026, 8, 19, 12, 0, tzinfo=UTC),
        committed_at=None,
        status=InteractionStatus.OPEN,
    )
    orch.begin_turn(interaction)
    orch.run_shadow()
    # run() stops at DISPATCHING by lifecycle design; the shadow mirror
    # completes its turn exactly like a real reactive turn does.
    state_after_shadow_run = orch.state
    orch.commit_turn()
    assert (state_after_shadow_run, orch.state) == (
        TurnState.DISPATCHING,
        TurnState.COMMITTED,
    )
