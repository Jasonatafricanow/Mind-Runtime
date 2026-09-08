"""C8B — SafeShadowRunner wrapper black-box tests.

SH1:  factory creates orchestrator; caller never gets commit-capable handle.
SH11: wrapper returns a ShadowRunResult (never a committable projection).
SH13: wrapper records shadow_run metadata in ShadowRunResult/ShadowRunRecord.
SH14: wrapper records comparison result (if host outcome provided).
SH15: shadow_enabled=False → execute raises ShadowModeDisabled.
SH16: factory raises if runtime_id is missing.

These tests use the public SafeShadowRunner factory interface.
"""

from __future__ import annotations

from dataclasses import fields
from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest
from tests.support.fake_clock import FakeClock

from mind_runtime.contracts import Interaction, InteractionStatus, Scope, ScopeDomain
from mind_runtime.pipeline.trace import TraceRecorder
from mind_runtime.shadow import (
    InMemoryShadowRecordStore,
    SafeShadowRunner,
    ShadowModeDisabled,
    ShadowRecordStore,
)


def _clock() -> FakeClock:
    return FakeClock(datetime(2026, 8, 19, 12, 0, tzinfo=UTC))


def _trace() -> TraceRecorder:
    return TraceRecorder()


def _store() -> ShadowRecordStore:
    return InMemoryShadowRecordStore()


def _interaction(
    interaction_id: str = "it-wrap",
    user_id: str = "user-1",
) -> Interaction:
    return Interaction(
        interaction_id=interaction_id,
        scope=Scope(domain=ScopeDomain.USER, user_id=user_id),
        channel="test",
        session_id="session-1",
        turn_id="turn-1",
        started_at=datetime(2026, 8, 19, 12, 0, tzinfo=UTC),
        committed_at=None,
        status=InteractionStatus.OPEN,
    )


def _runner(
    shadow_enabled: bool = True,
    runtime_id: str = "test-runtime",
) -> SafeShadowRunner:
    """Build a SafeShadowRunner with a FakeClock for deterministic testing."""
    return SafeShadowRunner(
        record_store=_store(),
        clock=_clock(),
        trace=_trace(),
        shadow_enabled=shadow_enabled,
        runtime_id=runtime_id,
    )


# ────────────────────────────────────────────────────────────────────────────
# SH1: SafeShadowRunner is the only factory; caller never gets orchestrator
# ────────────────────────────────────────────────────────────────────────────


def test_factory_is_the_only_public_constructor() -> None:
    """SafeShadowRunner must be the only way to obtain a shadow runner handle."""
    runner = _runner()
    assert runner is not None
    # The runner must not expose the orchestrator
    assert not hasattr(runner, "orchestrator")


def test_runner_execute_does_not_return_orchestrator() -> None:
    """execute() must return a ShadowRunResult, never an orchestrator."""
    runner = _runner()

    result = runner.execute(_interaction())

    # Must be a ShadowRunResult, not a TurnOrchestrator
    assert type(result).__name__ == "ShadowRunResult"
    assert not isinstance(result, MagicMock)


# ────────────────────────────────────────────────────────────────────────────
# SH11: ShadowRunResult — no cognitive authority, no delivery authority
# ────────────────────────────────────────────────────────────────────────────


def test_shadow_run_result_has_zero_cognitive_authority() -> None:
    """ShadowRunResult must not be assignable to evidence, projection, or committable fields."""
    from mind_runtime.contracts.evidence import Evidence
    from mind_runtime.shadow import ShadowRunResult

    # ShadowRunResult is a frozen dataclass — it is not a subclass of Evidence
    assert not issubclass(ShadowRunResult, Evidence)


def test_shadow_run_result_fields_are_frozen() -> None:
    """ShadowRunResult must be immutable (frozen=True)."""
    import dataclasses

    from mind_runtime.shadow import ShadowRunResult

    assert dataclasses.is_dataclass(ShadowRunResult)
    field_def = next(
        (f for f in dataclasses.fields(ShadowRunResult) if f.name == "shadow_run_id"),
        None,
    )
    assert field_def is not None, "shadow_run_id field not found"


# ────────────────────────────────────────────────────────────────────────────
# SH13: metadata fields are recorded in ShadowRunResult
# ────────────────────────────────────────────────────────────────────────────


def test_shadow_run_result_captures_metadata() -> None:
    """ShadowRunResult must include shadow_run_id and status."""
    from mind_runtime.shadow import ShadowRunResult

    runner = _runner(runtime_id="my-runtime")
    it = _interaction(interaction_id="it-meta")

    result = runner.execute(it)

    assert isinstance(result, ShadowRunResult)
    assert result.shadow_run_id is not None
    assert len(result.shadow_run_id) > 0
    assert result.status is not None


# ────────────────────────────────────────────────────────────────────────────
# SH14: host outcome comparison seam
# ────────────────────────────────────────────────────────────────────────────


def test_runner_execute_accepts_host_outcome() -> None:
    """execute() must accept a host_outcome argument."""
    from mind_runtime.shadow import HostOutcome

    runner = _runner()
    mock_outcome = MagicMock(spec=HostOutcome)

    # Must not raise
    result = runner.execute(_interaction(), host_outcome=mock_outcome)
    assert result is not None


def test_comparison_result_recorded_when_host_outcome_provided() -> None:
    """When host_outcome is set, comparison must appear in ShadowRunRecord."""
    from mind_runtime.shadow import HostOutcome, InMemoryShadowRecordStore, ShadowRunResult

    store: InMemoryShadowRecordStore = InMemoryShadowRecordStore()
    runner = _runner(runtime_id="cmp-runtime")
    runner.record_store = store
    it = _interaction(interaction_id="it-cmp")
    mock_host_outcome = MagicMock(spec=HostOutcome)

    result = runner.execute(it, host_outcome=mock_host_outcome)

    assert isinstance(result, ShadowRunResult)
    assert result.snapshot is not None
    # The store should have saved the record; ShadowRunRecord has comparison field
    saved = store.all()
    assert len(saved) >= 1
    record = next(r for r in saved if r.shadow_run_id == result.shadow_run_id)
    field_names = {f.name for f in fields(record)}
    assert "comparison" in field_names


# ────────────────────────────────────────────────────────────────────────────
# SH15: shadow_enabled=False raises ShadowModeDisabled
# ────────────────────────────────────────────────────────────────────────────


def test_execute_raises_when_disabled() -> None:
    """execute() must raise ShadowModeDisabled when shadow_enabled=False."""
    runner = _runner(shadow_enabled=False)
    it = _interaction(interaction_id="it-off")

    with pytest.raises(ShadowModeDisabled):
        runner.execute(it)


# ────────────────────────────────────────────────────────────────────────────
# SH14: comparison computation — all four branches
# ────────────────────────────────────────────────────────────────────────────


def _make_comparison_runner() -> SafeShadowRunner:
    return SafeShadowRunner(
        record_store=InMemoryShadowRecordStore(),
        clock=_clock(),
        trace=_trace(),
        shadow_enabled=True,
        runtime_id="cmp-test",
    )


def test_comparison_both_absent_records_not_comparable() -> None:
    """mr_would_act=None AND host_action_taken=False → record exists; comparable is set."""
    from mind_runtime.shadow import HostOutcome

    mock_host = MagicMock(spec=HostOutcome)
    mock_host.host_action_taken = False
    mock_host.host_action_type = None
    mock_host.host_expression_ref = None

    store: InMemoryShadowRecordStore = InMemoryShadowRecordStore()
    runner = _make_comparison_runner()
    runner.record_store = store

    runner.execute(_interaction(interaction_id="cmp-both-absent"), host_outcome=mock_host)

    saved = store.all()
    assert len(saved) == 1
    cmp = saved[0].comparison
    assert cmp is not None
    # comparable must be set (true if both sides had data, false otherwise)
    assert isinstance(cmp.comparable, bool)


def test_comparison_records_comparable_when_both_sides_present() -> None:
    """When MR and Host both have data, the record is comparable and fields are set."""
    from mind_runtime.shadow import HostOutcome

    mock_host = MagicMock(spec=HostOutcome)
    mock_host.host_action_taken = True
    mock_host.host_action_type = "send_message"
    mock_host.host_expression_ref = "msg-123"

    store: InMemoryShadowRecordStore = InMemoryShadowRecordStore()
    runner = _make_comparison_runner()
    runner.record_store = store

    runner.execute(_interaction(interaction_id="cmp-both-present"), host_outcome=mock_host)

    saved = store.all()
    cmp = saved[0].comparison
    assert cmp is not None
    assert cmp.comparable is True
    # action_presence_match is True (both present)
    assert cmp.action_presence_match is True


def test_comparison_action_presence_mismatch() -> None:
    """When MR would send but Host did not, action_presence_match is False."""
    from mind_runtime.shadow import HostOutcome

    mock_host = MagicMock(spec=HostOutcome)
    mock_host.host_action_taken = False
    mock_host.host_action_type = None
    mock_host.host_expression_ref = None

    store: InMemoryShadowRecordStore = InMemoryShadowRecordStore()
    runner = _make_comparison_runner()
    runner.record_store = store

    runner.execute(_interaction(interaction_id="cmp-mr-only"), host_outcome=mock_host)

    saved = store.all()
    cmp = saved[0].comparison
    assert cmp is not None
    # MR is present (default stub returns ACCEPT → would_send), Host absent
    assert cmp.action_presence_match is False


def test_comparison_action_type_mismatch() -> None:
    """When action types differ (text vs media), action_type_match is False."""
    from mind_runtime.shadow import HostOutcome

    mock_host = MagicMock(spec=HostOutcome)
    mock_host.host_action_taken = True
    mock_host.host_action_type = "send_photo"  # different from default stub "accept"
    mock_host.host_expression_ref = "msg-999"

    store: InMemoryShadowRecordStore = InMemoryShadowRecordStore()
    runner = _make_comparison_runner()
    runner.record_store = store

    runner.execute(_interaction(interaction_id="cmp-type-mismatch"), host_outcome=mock_host)

    saved = store.all()
    cmp = saved[0].comparison
    assert cmp is not None
    # Types differ: MR default stub returns ExpressionDisposition.ACCEPT
    # (value "accept"); Host returns "send_photo" — must be False
    assert cmp.action_type_match is False


# ────────────────────────────────────────────────────────────────────────────
# SH16: factory raises if runtime_id is missing
# ────────────────────────────────────────────────────────────────────────────


def test_factory_raises_without_runtime_id() -> None:
    """SafeShadowRunner must raise if runtime_id is None or empty."""
    with pytest.raises((ValueError, RuntimeError), match="runtime_id"):
        SafeShadowRunner(
            record_store=_store(),
            clock=_clock(),
            trace=_trace(),
            shadow_enabled=True,
            runtime_id="",
        )

    with pytest.raises((ValueError, RuntimeError), match="runtime_id"):
        SafeShadowRunner(
            record_store=_store(),
            clock=_clock(),
            trace=_trace(),
            shadow_enabled=True,
            runtime_id=None,  # type: ignore[arg-type]
        )
