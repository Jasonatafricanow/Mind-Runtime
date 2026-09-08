"""C8C-B — Continuous production shadow wiring tests.

Architecture Lock v1.2 / C8C-A audit:
  docs/architecture/MR_ARCHITECTURE_LOCK_v1_2_COMPLETE.md
  docs/research/c8c/C8C_AUDIT_v1.md

C8C-B acceptance:
  B1  default OFF exact old behavior
  B2  enabled invokes exactly once per logical interaction
  B3  runner failure isolated from production
  B4  store failure isolated from production
  B5  zero canonical shadow commit
  B6  zero C7 / body side effect
  B7  durable replay / idempotency
  B8  correct same-turn snapshot semantics
  B9  agent / soul scope preserved
  B10 ModelEgressPolicy unchanged
  B11 HostOutcome optional / unavailable handled without Host changes
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from tests.support.fake_clock import FakeClock

from mind_runtime.contracts import (
    Interaction,
    InteractionStatus,
    Scope,
    ScopeDomain,
)
from mind_runtime.facts.service import FactIngestService
from mind_runtime.pipeline.orchestrator import TurnOrchestrator, TurnState
from mind_runtime.pipeline.trace import TraceRecorder
from mind_runtime.shadow import (
    HostOutcome,
    InMemoryShadowRecordStore,
    SafeShadowRunner,
    ShadowPersistenceError,
    ShadowRunResult,
    ShadowStatus,
)
from mind_runtime.shadow.backfill import run_backfill
from mind_runtime.shadow.production_wiring import (
    ProductionShadowTap,
    production_shadow_enabled,
)
from mind_runtime.shadow.runtime_loop import (
    build_runtime_stack,
    process_pending,
)

FIXED_NOW = datetime(2026, 8, 27, 12, 0, tzinfo=UTC)
OLD_EPOCH = 1735689600.0


# ── builders ────────────────────────────────────────────────────────────────


def _clock() -> FakeClock:
    return FakeClock(FIXED_NOW)


def _interaction(interaction_id: str = "it-c8c-b") -> Interaction:
    return Interaction(
        interaction_id=interaction_id,
        scope=Scope(domain=ScopeDomain.USER, user_id="user-a"),
        channel="telegram",
        session_id="session-1",
        turn_id="turn-1",
        started_at=FIXED_NOW,
        committed_at=None,
        status=InteractionStatus.OPEN,
    )


def _stack(tmp_path: Path, user_id: str = "user-a") -> tuple[TurnOrchestrator, object]:
    orchestrator, bridge = build_runtime_stack(
        clock=_clock(),
        facts_db=tmp_path / f"facts-{user_id}.sqlite",
        state_db=tmp_path / f"cognition-{user_id}.sqlite",
        origin_runtime_id="kayla",
        user_id=user_id,
    )
    return orchestrator, bridge


def _make_hermes_db(
    path: Path, rows: list[tuple[int, float, str, str]]
) -> str:
    con = sqlite3.connect(str(path))
    try:
        con.executescript(
            "CREATE TABLE sessions (id INTEGER PRIMARY KEY, source TEXT, session_key TEXT);"
            "CREATE TABLE messages (id INTEGER PRIMARY KEY, session_id INTEGER,"
            " timestamp REAL, role TEXT, content TEXT);"
        )
        con.execute("INSERT INTO sessions VALUES (1, 'telegram', 'chat/1')")
        con.executemany("INSERT INTO messages VALUES (?, 1, ?, ?, ?)", rows)
        con.commit()
    finally:
        con.close()
    return str(path)


def _acquire(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, rows: list[tuple[int, float, str, str]]
) -> Path:
    monkeypatch.setenv("MIND_RUNTIME_SHADOW_DB", str(tmp_path / "shadow.db"))
    state_db = _make_hermes_db(tmp_path / "hermes_state.db", rows)
    run_backfill(
        state_db,
        dry_run=False,
        cursor=0.0,
        limit=500,
        known_names=("嘉森", "嘻嘻"),
        keep_names=True,
    )
    return tmp_path / "shadow.db"


# ── B1: default OFF preserves old behavior ──────────────────────────────────


def test_b1_default_off_returns_false(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Default OFF (no env) — gate helper returns False."""
    monkeypatch.delenv("MIND_RUNTIME_PRODUCTION_SHADOW", raising=False)
    assert production_shadow_enabled() is False


@pytest.mark.parametrize(
    "raw, expected",
    [
        (None, False),
        ("", False),
        ("0", False),
        ("false", False),
        ("FALSE", False),
        ("off", False),
        ("random-junk", False),
        ("1", True),
        ("true", True),
        ("yes", True),
        ("on", True),
    ],
)
def test_b1_production_shadow_gate_truth_table(
    monkeypatch: pytest.MonkeyPatch, raw: str | None, expected: bool
) -> None:
    if raw is None:
        monkeypatch.delenv("MIND_RUNTIME_PRODUCTION_SHADOW", raising=False)
    else:
        monkeypatch.setenv("MIND_RUNTIME_PRODUCTION_SHADOW", raw)
    assert production_shadow_enabled() is expected


def test_b1_default_off_preserves_old_pass_report(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With C8C disabled, process_pending behaves exactly as before:
    no shadow counters incremented, no ShadowRunRecord written.
    """
    monkeypatch.delenv("MIND_RUNTIME_PRODUCTION_SHADOW", raising=False)
    shadow_db = _acquire(
        tmp_path, monkeypatch, [(10, OLD_EPOCH, "user", "默认关闭应该不调用 shadow")]
    )
    orchestrator, bridge = _stack(tmp_path)
    report = process_pending(
        orchestrator,
        bridge,
        shadow_db=str(shadow_db),
        blocked_store_path=str(tmp_path / "blocked.sqlite3"),
    )
    # Production normal behavior: one record processed.
    assert report.processed == 1
    # C8C counters all zero.
    assert report.shadow_invoked == 0
    assert report.shadow_completed == 0
    assert report.shadow_failed == 0


# ── B2: enabled invokes exactly once per logical interaction ────────────────


def test_b2_enabled_tap_invokes_runner_once_per_logical_interaction(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MIND_RUNTIME_PRODUCTION_SHADOW", "1")
    shadow_db = _acquire(
        tmp_path, monkeypatch, [(20, OLD_EPOCH, "user", "首次应该 shadow 一次")]
    )
    orchestrator, bridge = _stack(tmp_path)
    shadow_store = InMemoryShadowRecordStore()
    tap = ProductionShadowTap.from_env(
        clock=_clock(),
        trace=TraceRecorder(),
        record_store=shadow_store,
        runtime_id="test-runtime",
    )
    assert tap.enabled is True
    report = process_pending(
        orchestrator,
        bridge,
        shadow_db=str(shadow_db),
        blocked_store_path=str(tmp_path / "blocked.sqlite3"),
        production_shadow_tap=tap,
    )
    assert report.processed == 1
    assert report.shadow_invoked == 1
    assert report.shadow_completed == 1
    assert report.shadow_failed == 0
    # Durable record exists.
    assert len(shadow_store.all()) == 1
    record = shadow_store.all()[0]
    assert record.status is ShadowStatus.COMPLETED
    assert record.source_interaction_id == "hermes-20"


def test_b2_disabled_tap_does_not_invoke(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Tap enabled=False means runner never executes, even when env is ON.

    Constructed with explicit enabled=False (overrides env).
    """
    monkeypatch.setenv("MIND_RUNTIME_PRODUCTION_SHADOW", "1")
    shadow_db = _acquire(
        tmp_path, monkeypatch, [(30, OLD_EPOCH, "user", "显式关闭")]
    )
    orchestrator, bridge = _stack(tmp_path)
    shadow_store = InMemoryShadowRecordStore()
    store = InMemoryShadowRecordStore()
    runner = SafeShadowRunner(
        clock=_clock(),
        trace=TraceRecorder(),
        record_store=store,
        runtime_id="rt",
        shadow_enabled=False,
    )
    tap = ProductionShadowTap(
        runner=runner,
        record_store=shadow_store,
        clock=_clock(),
        trace=TraceRecorder(),
        enabled=False,
    )
    report = process_pending(
        orchestrator,
        bridge,
        shadow_db=str(shadow_db),
        blocked_store_path=str(tmp_path / "blocked.sqlite3"),
        production_shadow_tap=tap,
    )
    assert report.processed == 1
    # Tap itself incremented shadow_invoked (probe), but runner is disabled
    # so shadow_completed is 0 and no record is written.
    assert report.shadow_invoked == 1
    assert report.shadow_completed == 0
    assert report.shadow_failed == 0
    assert len(shadow_store.all()) == 0


# ── B3: runner failure isolated from production ────────────────────────────


def test_b3_runner_exception_is_isolated(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Runner.execute() raises -> production commit_turn result preserved.

    The production turn's BridgeOutcome.stage must still be 'committed'
    even when the shadow tap fails.
    """
    monkeypatch.setenv("MIND_RUNTIME_PRODUCTION_SHADOW", "1")
    shadow_db = _acquire(
        tmp_path, monkeypatch, [(40, OLD_EPOCH, "user", "runner 失败应该隔离")]
    )
    orchestrator, bridge = _stack(tmp_path)
    shadow_store = InMemoryShadowRecordStore()
    runner = MagicMock(spec=SafeShadowRunner)
    runner.execute.side_effect = RuntimeError("simulated runner failure")
    tap = ProductionShadowTap(
        runner=runner,
        record_store=shadow_store,
        clock=_clock(),
        trace=TraceRecorder(),
        enabled=True,
    )
    report = process_pending(
        orchestrator,
        bridge,
        shadow_db=str(shadow_db),
        blocked_store_path=str(tmp_path / "blocked.sqlite3"),
        production_shadow_tap=tap,
    )
    # Production normal: one record committed.
    assert report.processed == 1
    assert report.failed == 0
    # Shadow tap recorded the failure.
    assert report.shadow_invoked == 1
    assert report.shadow_failed == 1
    assert report.shadow_completed == 0
    # FAILED record was written by the tap.
    failed_records = [r for r in shadow_store.all() if r.status is ShadowStatus.FAILED]
    assert len(failed_records) == 1
    assert "RuntimeError" in (failed_records[0].failure_reason or "")


# ── B4: store failure isolated from production ─────────────────────────────


def test_b4_store_failure_is_isolated(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Store.save() raises after runner completed — production not affected.

    SafeShadowRunner.execute() persists the record via its own
    record_store.save; we mock the runner to simulate the runner
    succeeding but persistence failing. Production commit_turn result
    is preserved.
    """
    monkeypatch.setenv("MIND_RUNTIME_PRODUCTION_SHADOW", "1")
    shadow_db = _acquire(
        tmp_path, monkeypatch, [(50, OLD_EPOCH, "user", "store 失败应隔离")]
    )
    orchestrator, bridge = _stack(tmp_path)
    shadow_store = InMemoryShadowRecordStore()
    runner = MagicMock(spec=SafeShadowRunner)
    # Runner succeeds internally but persistence fails
    runner.execute.side_effect = ShadowPersistenceError(
        "shadow record persistence failed"
    )
    tap = ProductionShadowTap(
        runner=runner,
        record_store=shadow_store,
        clock=_clock(),
        trace=TraceRecorder(),
        enabled=True,
    )
    report = process_pending(
        orchestrator,
        bridge,
        shadow_db=str(shadow_db),
        blocked_store_path=str(tmp_path / "blocked.sqlite3"),
        production_shadow_tap=tap,
    )
    # Production still committed.
    assert report.processed == 1
    assert report.failed == 0
    # Shadow recorded the failure.
    assert report.shadow_failed == 1
    assert report.shadow_completed == 0


# ── B5: zero canonical shadow commit ───────────────────────────────────────


def test_b5_shadow_cannot_produce_canonical_commit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """After a shadow tap, the production orchestrator's canonical
    state is unchanged from the production commit point.

    The shadow cognition lives inside SafeShadowRunner's own private
    TurnOrchestrator instance; it never touches the production
    orchestrator's _canonical dict.
    """
    monkeypatch.setenv("MIND_RUNTIME_PRODUCTION_SHADOW", "1")
    shadow_db = _acquire(
        tmp_path, monkeypatch, [(60, OLD_EPOCH, "user", "shadow 不应写 canonical")]
    )
    orchestrator, bridge = _stack(tmp_path)
    shadow_store = InMemoryShadowRecordStore()
    tap = ProductionShadowTap.from_env(
        clock=_clock(),
        trace=TraceRecorder(),
        record_store=shadow_store,
        runtime_id="rt",
    )
    canonical_before = dict(orchestrator._canonical)
    process_pending(
        orchestrator,
        bridge,
        shadow_db=str(shadow_db),
        blocked_store_path=str(tmp_path / "blocked.sqlite3"),
        production_shadow_tap=tap,
    )
    canonical_after = dict(orchestrator._canonical)
    # The production commit DID add canonical states (the user.affect.stub
    # record). The shadow must not add additional state.
    shadow_record = shadow_store.all()[0]
    snapshot = shadow_record.captured_snapshot
    assert snapshot is not None
    # The shadow snapshot is an audit-only copy. The production canonical
    # state is independent of any new shadow state.
    assert len(canonical_after) == len(canonical_before) + 1, (
        "Production canonical must change only by the production commit, "
        "not by the shadow."
    )
    # The snapshot's "shadow projections" are entirely within the runner's
    # own orchestrator; they were aborted.
    assert shadow_record.status is ShadowStatus.COMPLETED


# ── B6: zero C7 / body side effect ──────────────────────────────────────────


def test_b6_no_c7_or_body_side_effect(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No DeliveryPort, no DeliveryRequest, no delivery daemon reachable.

    The C8C tap code path does not import or instantiate any of:
      - DeliveryPort
      - DeliveryRequest
      - DeliveryReceipt
      - any carrier module
    """
    import inspect

    from mind_runtime.shadow import production_wiring

    src = inspect.getsource(production_wiring)
    forbidden = [
        "DeliveryPort",
        "DeliveryRequest",
        "DeliveryReceipt",
        "delivery.deliver",
        "DeliveryStatus.SENT",
        "settled",
        "real_carrier",
        "telegram",
        "weixin",
    ]
    for token in forbidden:
        assert token not in src, f"forbidden token {token!r} in production_wiring.py"


def test_b6_no_c7_reachability_from_runtime_loop(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """runtime_loop.process_pending does not reach C7 in the shadow path."""
    import inspect

    from mind_runtime.shadow import runtime_loop

    src = inspect.getsource(runtime_loop.process_pending)
    # DeliveryPort must not appear in the production-invocation path.
    assert "DeliveryPort" not in src
    assert "DeliveryRequest" not in src
    assert "delivery.deliver" not in src
    assert "settled" not in src


# ── B7: durable replay / idempotency ────────────────────────────────────────


def test_b7_durable_idempotency_uses_existing_c8b_r_semantics(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Same logical interaction re-run produces the same ShadowRunRecord.

    Reuses the existing C8B-R identity semantics; does NOT invent a
    second dedupe scheme. The tap delegates to SafeShadowRunner which
    generates the shadow_run_id from interaction_id + runtime_digest +
    started_at. Replay with identical content is a no-op via the
    durable store's idempotency check.
    """
    from mind_runtime.shadow import SqliteShadowRecordStore

    shadow_db = tmp_path / "shadow_records.sqlite"
    store = SqliteShadowRecordStore(shadow_db)
    interaction = _interaction()
    runner = SafeShadowRunner(
        clock=_clock(),
        trace=TraceRecorder(),
        record_store=store,
        runtime_id="rt",
        shadow_enabled=True,
    )
    tap = ProductionShadowTap(
        runner=runner,
        record_store=store,
        clock=_clock(),
        trace=TraceRecorder(),
        enabled=True,
    )
    first = tap.tap(interaction)
    assert first is not None
    assert first.succeeded
    first_count = len(store.all())

    # Replay with the same interaction (same started_at) — should be idempotent.
    second = tap.tap(interaction)
    # Same shadow_run_id, same content: store is a no-op.
    assert second is not None
    assert second.shadow_run_id == first.shadow_run_id
    assert len(store.all()) == first_count


# ── B8: same-turn snapshot semantics ───────────────────────────────────────


def test_b8_same_turn_snapshot_not_dual_executed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The shadow tap uses the SAME interaction_id as production.

    This is the C8C-A Section 11.2 concern: the tap must NOT
    accidentally trigger a second ingest/commit for the same evidence.
    The shadow lives in its own TurnOrchestrator instance owned by
    SafeShadowRunner; it only calls begin_turn + run_shadow, not
    ingest. No evidence reaches the production canonical plane twice.
    """
    monkeypatch.setenv("MIND_RUNTIME_PRODUCTION_SHADOW", "1")
    shadow_db = _acquire(
        tmp_path, monkeypatch, [(70, OLD_EPOCH, "user", "同一 evidence 不应被处理两遍")]
    )
    orchestrator, bridge = _stack(tmp_path)
    shadow_store = InMemoryShadowRecordStore()
    tap = ProductionShadowTap.from_env(
        clock=_clock(),
        trace=TraceRecorder(),
        record_store=shadow_store,
        runtime_id="rt",
    )
    process_pending(
        orchestrator,
        bridge,
        shadow_db=str(shadow_db),
        blocked_store_path=str(tmp_path / "blocked.sqlite3"),
        production_shadow_tap=tap,
    )
    # Production has exactly one committed record (one fact, one canonical change).
    facts_service = orchestrator.fact_ingest
    assert isinstance(facts_service, FactIngestService)
    assert facts_service.evidence.count() == 1
    # The production orchestrator's state is COMMITTED, not double-counted.
    assert orchestrator.state is TurnState.COMMITTED
    # The shadow record references the same source_interaction_id but
    # was produced by an isolated, now-aborted shadow orchestrator.
    record = shadow_store.all()[0]
    assert record.source_interaction_id == "hermes-70"
    # No second evidence exists in any persistence plane.
    assert facts_service.observations.count() == 1


# ── B9: agent / soul scope preserved ───────────────────────────────────────


def test_b9_scope_preserved_through_tap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The interaction's Scope is preserved end-to-end through the tap.

    The shadow record's `scope` field is derived from the
    Interaction's scope, not a global default. Multi-agent future
    routing is not implemented, but scope identity is not lost.
    """
    monkeypatch.setenv("MIND_RUNTIME_PRODUCTION_SHADOW", "1")
    shadow_db = _acquire(
        tmp_path, monkeypatch, [(80, OLD_EPOCH, "user", "scope 应保留")]
    )
    orchestrator, bridge = _stack(tmp_path, user_id="user-x")
    shadow_store = InMemoryShadowRecordStore()
    tap = ProductionShadowTap.from_env(
        clock=_clock(),
        trace=TraceRecorder(),
        record_store=shadow_store,
        runtime_id="rt",
    )
    process_pending(
        orchestrator,
        bridge,
        shadow_db=str(shadow_db),
        blocked_store_path=str(tmp_path / "blocked.sqlite3"),
        production_shadow_tap=tap,
    )
    record = shadow_store.all()[0]
    # scope is serialized as `domain@user_id`
    assert "user-x" in record.scope
    assert record.source_interaction_id == "hermes-80"


# ── B10: ModelEgressPolicy unchanged ───────────────────────────────────────


def test_b10_model_egress_policy_unchanged() -> None:
    """C8C does not weaken ModelEgressPolicy or add new egress surfaces.

    Static analysis: production_wiring imports do not include
    providers/transport, do not reference ModelEgressPolicy, and do
    not import any URL/endpoint construction.
    """
    import inspect

    from mind_runtime.shadow import production_wiring

    src = inspect.getsource(production_wiring)
    # No transport construction, no URL building, no API key handling.
    assert "ModelEgressPolicy" not in src
    assert "urllib" not in src
    assert "requests" not in src
    assert "post_json" not in src
    # SafeShadowRunner is composed; it owns its own transport decisions.
    # Tap only calls runner.execute().


# ── B11: HostOutcome optional / unavailable handled gracefully ──────────────


def test_b11_host_outcome_unavailable_does_not_block(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When HostOutcome is None, the tap still completes successfully.

    No new Host wiring is created in C8C-B; HostOutcome is optional
    in the SafeShadowRunner contract.
    """
    monkeypatch.setenv("MIND_RUNTIME_PRODUCTION_SHADOW", "1")
    shadow_db = _acquire(
        tmp_path, monkeypatch, [(90, OLD_EPOCH, "user", "host outcome 缺失可继续")]
    )
    orchestrator, bridge = _stack(tmp_path)
    shadow_store = InMemoryShadowRecordStore()
    tap = ProductionShadowTap.from_env(
        clock=_clock(),
        trace=TraceRecorder(),
        record_store=shadow_store,
        runtime_id="rt",
    )
    report = process_pending(
        orchestrator,
        bridge,
        shadow_db=str(shadow_db),
        blocked_store_path=str(tmp_path / "blocked.sqlite3"),
        production_shadow_tap=tap,
    )
    assert report.processed == 1
    assert report.shadow_completed == 1
    record = shadow_store.all()[0]
    # HostOutcome is None — no Host expression ref is needed.
    assert record.host_outcome is None


# ── Direct tap unit tests (white-box) ──────────────────────────────────────


def test_tap_disabled_returns_none_and_does_not_invoke_runner() -> None:
    runner = MagicMock(spec=SafeShadowRunner)
    tap = ProductionShadowTap(
        runner=runner,
        record_store=InMemoryShadowRecordStore(),
        clock=_clock(),
        trace=TraceRecorder(),
        enabled=False,
    )
    result = tap.tap(_interaction())
    assert result is None
    runner.execute.assert_not_called()


def test_tap_passes_host_outcome_through() -> None:
    runner = MagicMock(spec=SafeShadowRunner)
    runner.execute.return_value = MagicMock(spec=ShadowRunResult, succeeded=True)
    tap = ProductionShadowTap(
        runner=runner,
        record_store=InMemoryShadowRecordStore(),
        clock=_clock(),
        trace=TraceRecorder(),
        enabled=True,
    )
    host = HostOutcome(host_action_taken=True, host_action_type="text")
    tap.tap(_interaction(), host_outcome=host)
    runner.execute.assert_called_once()
    # host_outcome is passed as keyword argument
    kwargs = runner.execute.call_args.kwargs
    assert kwargs.get("host_outcome") is host


def test_tap_persists_failed_record_when_runner_raises() -> None:
    shadow_store = InMemoryShadowRecordStore()
    runner = MagicMock(spec=SafeShadowRunner)
    runner.execute.side_effect = RuntimeError("boom")
    tap = ProductionShadowTap(
        runner=runner,
        record_store=shadow_store,
        clock=_clock(),
        trace=TraceRecorder(),
        enabled=True,
    )
    result = tap.tap(_interaction("it-fail"))
    assert result is None
    failed = [r for r in shadow_store.all() if r.status is ShadowStatus.FAILED]
    assert len(failed) == 1
    assert "RuntimeError" in (failed[0].failure_reason or "")
