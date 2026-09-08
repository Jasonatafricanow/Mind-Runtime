"""C2.10 daemon/application-loop tests: real source -> real cognition.

Chain under test is the REAL one end to end: crafted Hermes state.db ->
sync/backfill (source persistence + acquisition cursor) -> shadow rows ->
runtime_loop.process_pending -> source_bridge -> REAL TurnOrchestrator with
durable SQLite facts/state backends. Mocks only at allowed boundaries:
external Hermes files, crash injection, the daemon's subprocess edges, and
legacy heuristics.
"""

from __future__ import annotations

import json
import sqlite3
import subprocess as sp
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import pytest
from tests.support.fake_clock import FakeClock

from mind_runtime.contracts import EmotionalTransitionInput, EmotionalTransitionResult
from mind_runtime.facts.service import FactIngestService
from mind_runtime.pipeline.orchestrator import TurnOrchestrator, TurnState
from mind_runtime.pipeline.stubs import StubEmotionalTransition
from mind_runtime.shadow import daemon as daemon_mod
from mind_runtime.shadow import runtime_loop
from mind_runtime.shadow.backfill import run_backfill
from mind_runtime.shadow.runtime_loop import (
    BlockedSourceStore,
    build_runtime_stack,
    process_pending,
)
from mind_runtime.shadow.source_bridge import (
    AdmissionMode,
    BridgeOutcome,
    HermesProductionBridge,
    SourceRecord,
)

FIXED_NOW = datetime(2026, 8, 27, 12, 0, tzinfo=UTC)
OLD_EPOCH = 1735689600.0  # 2025-01-01Z — historical event time


# ── builders ───────────────────────────────────────────────────────────────


def _clock() -> FakeClock:
    return FakeClock(FIXED_NOW)


def _service(orchestrator: TurnOrchestrator) -> FactIngestService:
    service = orchestrator.fact_ingest
    assert isinstance(service, FactIngestService)
    return service


def _make_hermes_db(path: Path, rows: list[tuple[int, float, str, str]]) -> str:
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
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    rows: list[tuple[int, float, str, str]],
) -> tuple[Path, int]:
    """Run the REAL Hermes->shadow acquisition leg into the tmp shadow db."""
    monkeypatch.setenv("MIND_RUNTIME_SHADOW_DB", str(tmp_path / "shadow.db"))
    state_db = _make_hermes_db(tmp_path / "hermes_state.db", rows)
    shadow_db = tmp_path / "shadow.db"
    stats = run_backfill(
        state_db,
        dry_run=False,
        cursor=0.0,
        limit=500,
        known_names=("嘉森", "嘻嘻"),
        keep_names=True,
    )
    assert stats["recorded"] == len(rows)
    return shadow_db, int(stats["recorded"])


@dataclass
class _Stack:
    """One durable production stack bound to a tmp directory."""

    orchestrator: TurnOrchestrator
    bridge: HermesProductionBridge
    clock: FakeClock
    user_id: str = "user-a"


def _stack(tmp_path: Path, user_id: str = "user-a") -> _Stack:
    clock = _clock()
    orchestrator, bridge = build_runtime_stack(
        clock=clock,
        facts_db=tmp_path / f"facts-{user_id}.sqlite",
        state_db=tmp_path / f"cognition-{user_id}.sqlite",
        origin_runtime_id="kayla",
        user_id=user_id,
    )
    return _Stack(orchestrator=orchestrator, bridge=bridge, clock=clock, user_id=user_id)


def _pass(stack: _Stack, shadow_db: Path) -> runtime_loop.RuntimePassReport:
    report = process_pending(
        stack.orchestrator,
        stack.bridge,
        shadow_db=str(shadow_db),
        blocked_store_path=str(shadow_db.parent / f"blocked-{stack.user_id}.sqlite3"),
    )
    assert isinstance(report, runtime_loop.RuntimePassReport)
    return report


def _fingerprint(orchestrator: TurnOrchestrator) -> tuple[tuple[str, int], ...]:
    return tuple(sorted((s.state_id, s.version) for s in orchestrator.canonical))


def _row_count(shadow_db: Path) -> int:
    with sqlite3.connect(str(shadow_db)) as con:
        row = con.execute("SELECT COUNT(*) FROM shadow_events").fetchone()
    return int(row[0])


def _blocked(tmp_path: Path, user_id: str = "user-a") -> BlockedSourceStore:
    return BlockedSourceStore(tmp_path / f"blocked-{user_id}.sqlite3")


# ── DL1 — new message reaches canonical cognition automatically ───────────


def test_dl1_new_source_flows_to_canonical_effect_with_event_time(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    shadow_db, _ = _acquire(
        tmp_path,
        monkeypatch,
        [(11, OLD_EPOCH, "user", "嘻嘻晚饭吃了烤串"), (12, OLD_EPOCH + 60, "user", "嘉森加班")],
    )
    # ADR-0012 §2: original event time persisted alongside ingestion ts
    with sqlite3.connect(str(shadow_db)) as con:
        stored_event_ts = con.execute(
            "SELECT event_ts FROM shadow_events WHERE content_id=11"
        ).fetchone()[0]
    assert stored_event_ts == datetime.fromtimestamp(OLD_EPOCH, tz=UTC).isoformat(
        timespec="seconds"
    )

    stack = _stack(tmp_path)
    report = _pass(stack, shadow_db)

    assert report.processed == 2
    assert report.failed == 0 and report.blocked == 0
    assert stack.orchestrator.state is TurnState.COMMITTED
    assert [s.dimension for s in stack.orchestrator.canonical] == ["user.affect.stub"]
    evidence_ids = sorted(e.id for e in _service(stack.orchestrator).evidence.all())
    assert evidence_ids == ["hermes:11", "hermes:12"]
    expected_by_id = {
        "hermes:11": datetime.fromtimestamp(OLD_EPOCH, tz=UTC),
        "hermes:12": datetime.fromtimestamp(OLD_EPOCH + 60, tz=UTC),
    }
    for e in _service(stack.orchestrator).evidence.all():
        assert e.occurred_at == expected_by_id[e.id]
        assert e.received_at == FIXED_NOW


# ── DL2 — idle pass is a no-op ─────────────────────────────────────────────


def test_dl2_second_pass_without_new_source_does_not_duplicate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    shadow_db, _ = _acquire(tmp_path, monkeypatch, [(20, OLD_EPOCH, "user", "第二条消息")])
    stack = _stack(tmp_path)
    first = _pass(stack, shadow_db)
    after_first = _fingerprint(stack.orchestrator)

    second = _pass(stack, shadow_db)
    assert first.processed == 1
    assert second.processed == 0
    assert second.replayed == 1
    assert second.considered == 0
    assert _fingerprint(stack.orchestrator) == after_first
    assert _service(stack.orchestrator).evidence.count() == 1


# ── Crash Window A — persisted but never bridged ──────────────────────────


class _CrashBeforeBridge(HermesProductionBridge):
    # crash injection: this override never returns
    def process(self, record: SourceRecord, **kwargs: object) -> BridgeOutcome:
        raise RuntimeError("crash before bridge")


def test_dl3_crash_before_bridge_recovers_on_restart(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    shadow_db, _ = _acquire(tmp_path, monkeypatch, [(55, OLD_EPOCH, "user", "持久化后崩溃")])
    crashed_stack = _stack(tmp_path)
    crashed_stack.bridge = _CrashBeforeBridge(
        crashed_stack.orchestrator,
        clock=crashed_stack.clock,
        origin_runtime_id="kayla",
        user_id="user-a",
    )
    report = _pass(crashed_stack, shadow_db)
    assert report.failed == 1 and report.processed == 0
    # nothing was admitted; source row survived untouched
    assert _service(crashed_stack.orchestrator).evidence.count() == 0
    assert _row_count(shadow_db) == 1

    # restart: a healthy stack over the same acquisition processes once
    fresh = _stack(tmp_path)
    recovered = _pass(fresh, shadow_db)
    assert recovered.processed == 1
    ids = [e.id for e in _service(fresh.orchestrator).evidence.all()]
    assert ids == ["hermes:55"]


# ── Crash Window B — committed, marker lost, idempotent convergence ───────


def test_dl4_commit_marker_loss_converges_via_replay(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    shadow_db, _ = _acquire(tmp_path, monkeypatch, [(70, OLD_EPOCH, "user", "已提交后标记丢失")])
    committed = _stack(tmp_path)
    _pass(committed, shadow_db)
    after_commit = _fingerprint(committed.orchestrator)

    # brand-new stack over the same durable planes: no local markers exist
    resumed = _stack(tmp_path)
    report = _pass(resumed, shadow_db)

    assert report.processed == 0
    assert report.replayed == 1
    assert not report.failed
    assert _service(resumed.orchestrator).evidence.count() == 1
    assert _fingerprint(resumed.orchestrator) == after_commit


# ── DL5 — assistant record blocked once, queue not poisoned ───────────────


def test_dl5_assistant_blocked_once_and_user_still_processed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    shadow_db, _ = _acquire(
        tmp_path,
        monkeypatch,
        [
            (80, OLD_EPOCH, "assistant", "你现在在睡觉"),
            (81, OLD_EPOCH + 30, "user", "补一条用户消息"),
        ],
    )
    stack = _stack(tmp_path)
    report = _pass(stack, shadow_db)

    stages = [o.stage for o in stack.bridge.outcomes]
    assert stages == ["blocked", "committed"]
    assert (report.blocked, report.processed) == (1, 1)
    blocked_store = BlockedSourceStore(tmp_path / "blocked-user-a.sqlite3")
    assert blocked_store.is_blocked("80") is True
    assert blocked_store.is_blocked("81") is False

    second = _pass(stack, shadow_db)
    assert second.already_blocked_skipped == 1
    assert len(stack.bridge.outcomes) == 2  # blocked row skipped BEFORE bridge
    assert second.processed == 0 and second.replayed == 1 and second.blocked == 0


# ── DL6 / DL9 — runtime failure retries; source stays intact ──────────────


class _ExplodingTransition(StubEmotionalTransition):
    # crash injection: this override never returns
    def transition(
        self,
        transition_input: EmotionalTransitionInput,
    ) -> EmotionalTransitionResult:
        raise RuntimeError("runtime down")


def test_dl6_retryable_failure_then_recovery(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    shadow_db, _ = _acquire(tmp_path, monkeypatch, [(90, OLD_EPOCH, "user", "先炸后修")])
    broken_stack = _stack(tmp_path)
    exploding = _ExplodingTransition(clock=broken_stack.clock)
    assert isinstance(exploding, StubEmotionalTransition)
    broken_stack.orchestrator.emotional_transition = exploding

    failed_report = _pass(broken_stack, shadow_db)
    assert failed_report.failed == 1
    assert any(r.startswith("failed:90") for r in failed_report.reason_codes)
    # fact plane kept the admission even though cognition aborted (G13b)
    assert _service(broken_stack.orchestrator).evidence.count() == 1

    # DL9: source durability unaffected + not poisoned into BLOCKED
    assert _row_count(shadow_db) == 1
    store = BlockedSourceStore(tmp_path / "blocked-user-a.sqlite3")
    assert store.is_blocked("90") is False

    repaired = _stack(tmp_path)
    retry = _pass(repaired, shadow_db)
    assert retry.processed == 1
    assert [e.id for e in _service(repaired.orchestrator).evidence.all()] == ["hermes:90"]


# ── DL7 — same-timestamp records in deterministic stable order ────────────


def test_dl7_same_timestamp_ties_processed_in_id_order(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    shadow_db, _ = _acquire(
        tmp_path,
        monkeypatch,
        [
            (31, OLD_EPOCH, "user", "同秒甲"),
            (30, OLD_EPOCH, "user", "同秒乙"),
            (32, OLD_EPOCH, "user", "同秒丙"),
        ],
    )
    # equalize the persisted ts so ordering must ride on the id tiebreak
    with sqlite3.connect(str(shadow_db)) as con:
        con.execute("UPDATE shadow_events SET ts='2026-08-27T00:00:00+00:00'")
        con.commit()

    stack = _stack(tmp_path)
    report = _pass(stack, shadow_db)

    order = [o.source_record_id for o in stack.bridge.outcomes]
    assert order == ["30", "31", "32"]
    assert report.processed == 3
    # event_ts order ALSO collides; stable outcome regardless of insert order
    assert _service(stack.orchestrator).evidence.count() == 3


# ── DL8 — legacy heuristics cannot undo canonical success ─────────────────


def test_dl8_legacy_failure_leaves_canonical_committed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    shadow_db, _ = _acquire(tmp_path, monkeypatch, [(95, OLD_EPOCH, "user", "隔离验证")])
    stack = _stack(tmp_path)
    _pass(stack, shadow_db)
    canonical_after_success = _fingerprint(stack.orchestrator)

    def _boom(*args: object, **kwargs: object) -> None:
        raise RuntimeError("states extraction exploded")

    # _legacy_metrics imports at call time from the states module; patch there
    import mind_runtime.shadow.states as states_mod

    monkeypatch.setattr(states_mod, "extract_states", _boom)
    note = daemon_mod._legacy_metrics()
    assert "states error" in note
    # canonical runtime untouched by the legacy-layer failure
    assert _fingerprint(stack.orchestrator) == canonical_after_success
    monkeypatch.setattr(states_mod, "extract_states", lambda *a, **k: None)
    snapshot_note = daemon_mod._legacy_metrics()
    assert isinstance(snapshot_note, str)


# ── main() gate + defaults coverage ────────────────────────────────────────


def test_production_ingest_gate_matrix(monkeypatch: pytest.MonkeyPatch) -> None:
    for raw, expected in [("1", True), ("true", True), ("ON", True), ("0", False), ("junk", False)]:
        monkeypatch.setenv(daemon_mod.PRODUCTION_INGEST_ENV, raw)
        assert daemon_mod._production_ingest_enabled() is expected
    monkeypatch.delenv(daemon_mod.PRODUCTION_INGEST_ENV, raising=False)
    assert daemon_mod._production_ingest_enabled() is False


def test_loop_main_gate_off_writes_nothing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    facts_flag = tmp_path / "never.sqlite"
    code = runtime_loop.main(
        [
            "--shadow-db",
            str(tmp_path / "shadow.db"),
            "--facts-db",
            str(facts_flag),
            "--cognition-db",
            str(tmp_path / "cog.sqlite"),
            "--blocked-db",
            str(tmp_path / "blocked.sqlite3"),
        ]
    )
    payload = json.loads(capsys.readouterr().out)
    assert code == 0 and payload == {"gate": "off"}
    assert not facts_flag.exists()


def test_loop_main_gate_on_processes_pending_and_prints_counters(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    shadow_db, _ = _acquire(tmp_path, monkeypatch, [(99, OLD_EPOCH, "user", "入口直跑")])
    monkeypatch.setenv(daemon_mod.PRODUCTION_INGEST_ENV, "1")
    monkeypatch.setattr(runtime_loop, "DEFAULT_RUNTIME_DIR", tmp_path / "rt")
    code = runtime_loop.main(
        [
            "--shadow-db",
            str(shadow_db),
            "--facts-db",
            str(tmp_path / "facts.sqlite"),
            "--cognition-db",
            str(tmp_path / "cognition_state.sqlite"),
            "--blocked-db",
            str(tmp_path / "blocked.sqlite3"),
            "--user-id",
            "user-a",
            "--limit",
            "50",
        ]
    )
    payload = json.loads(capsys.readouterr().out)
    assert code == 0
    assert payload["runtime"]["processed"] == 1
    assert (tmp_path / "facts.sqlite").exists()


def test_loop_main_default_paths_branch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """No flags: env-config gate + module default dirs/DBs are exercised."""
    empty_shadow = tmp_path / "empty-shadow.db"
    from mind_runtime.shadow.redaction import init_store

    init_store(empty_shadow)
    monkeypatch.setenv(daemon_mod.PRODUCTION_INGEST_ENV, "yes")
    monkeypatch.setattr(runtime_loop, "DEFAULT_RUNTIME_DIR", tmp_path / "rt-defaults")
    monkeypatch.setattr(runtime_loop, "_DEFAULT_SHADOW_DB", empty_shadow)
    code = runtime_loop.main([])
    payload = json.loads(capsys.readouterr().out)
    assert code == 0
    assert payload["runtime"]["considered"] == 0
    assert (tmp_path / "rt-defaults" / "facts.sqlite").exists()


# ── daemon subprocess-edge tests (no real child python spawned) ────────────


def test_daemon_pass_reports_production_summary_when_enabled(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[list[str]] = []

    def fake_run(cmd: list[str], **kwargs: object) -> sp.CompletedProcess[str]:
        calls.append(list(cmd))
        if any("sync" in part for part in cmd):
            return sp.CompletedProcess(cmd, 0, stdout="", stderr="")
        return sp.CompletedProcess(cmd, 0, stdout='{"runtime": {"processed": 3}}', stderr="")

    monkeypatch.setattr("subprocess.run", fake_run)
    monkeypatch.delenv(daemon_mod.PRODUCTION_INGEST_ENV, raising=False)
    ok_off, msg_off = daemon_mod.one_pass()
    assert ok_off and "prod=" not in msg_off
    assert len(calls) == 2  # sync + snapshot only

    monkeypatch.setenv(daemon_mod.PRODUCTION_INGEST_ENV, "1")
    ok_on, msg_on = daemon_mod.one_pass()
    assert ok_on and '"runtime"' in msg_on
    loop_cmd = next(c for c in calls if any("runtime_loop" in p for p in c))
    assert "mind_runtime.shadow.runtime_loop" in loop_cmd


def test_daemon_production_failure_short_circuits(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run(cmd: list[str], **kwargs: object) -> sp.CompletedProcess[str]:
        if any("runtime_loop" in part for part in cmd):
            return sp.CompletedProcess(cmd, 3, stdout="", stderr="loop exploded")
        return sp.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr("subprocess.run", fake_run)
    monkeypatch.setenv(daemon_mod.PRODUCTION_INGEST_ENV, "1")
    ok, msg = daemon_mod.one_pass()
    assert not ok and "production ingest error" in msg and "rc=3" in msg


# ── daemon operational behaviors (log / corrupt-db / sync failure / main) ──


def test_daemon_log_appends_timestamped_lines(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    log_dir = tmp_path / "logs"
    monkeypatch.setattr(daemon_mod, "LOG_DIR", log_dir)
    monkeypatch.setattr(daemon_mod, "LOG", log_dir / "daemon.log")
    daemon_mod._log("hello")
    daemon_mod._log("second")
    text = (log_dir / "daemon.log").read_text(encoding="utf-8")
    assert "hello" in text and "second" in text
    assert text.count("\n") == 2


def test_daemon_affect_count_survives_corrupt_db(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    corrupt = tmp_path / "corrupt.db"
    corrupt.write_bytes(b"this is not a sqlite database")
    monkeypatch.setattr(daemon_mod, "AFFECT_DB", corrupt)
    assert daemon_mod._affect_count() == 0


def test_daemon_one_pass_sync_failure_short_circuits(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run(cmd: list[str], **kwargs: object) -> sp.CompletedProcess[str]:
        assert any("shadow.sync" in part for part in cmd)
        return sp.CompletedProcess(cmd, 9, stdout="", stderr="sync exploded")

    monkeypatch.setattr("subprocess.run", fake_run)
    ok, msg = daemon_mod.one_pass()
    assert not ok and "sync error rc=9" in msg


def test_daemon_one_pass_reports_legacy_snapshot_note_hermetically(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Legacy-layer failure note flows into the pass summary without failing."""
    from mind_runtime.shadow.redaction import init_store

    shadow_db = tmp_path / "legacy-source.db"
    init_store(shadow_db)  # no events table rows; extract still fine
    states_db = tmp_path / "states.db"
    monkeypatch.setenv("MIND_RUNTIME_SHADOW_DB", str(shadow_db))
    monkeypatch.setattr(daemon_mod, "STATES_DB", states_db)

    calls = 0

    def fake_run(cmd: list[str], **kwargs: object) -> sp.CompletedProcess[str]:
        nonlocal calls
        calls += 1
        if any("snapshot" in part for part in cmd):
            raise RuntimeError("snapshot subprocess exploded")
        return sp.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr("subprocess.run", fake_run)
    monkeypatch.delenv(daemon_mod.PRODUCTION_INGEST_ENV, raising=False)

    import mind_runtime.shadow.states as states_mod

    def _boom(*args: object, **kwargs: object) -> None:
        raise RuntimeError("states layer down")

    monkeypatch.setattr(states_mod, "extract_states", _boom)
    ok, msg = daemon_mod.one_pass()
    assert ok is True
    assert "snapshot error" in msg
    assert "snapshot subprocess exploded" in msg
    del calls


def test_daemon_main_once_prints_and_returns_zero(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def fake_run(cmd: list[str], **kwargs: object) -> sp.CompletedProcess[str]:
        return sp.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr("subprocess.run", fake_run)
    monkeypatch.delenv(daemon_mod.PRODUCTION_INGEST_ENV, raising=False)
    monkeypatch.setattr(sys, "argv", ["shadow-daemon", "--once"])
    code = daemon_mod.main()
    out = capsys.readouterr().out
    assert code == 0 and "synced" in out


def test_loop_requires_fact_ingest_service_admission(tmp_path: Path) -> None:
    class _FakeOrchestrator:
        fact_ingest = object()

    class _FakeBridge:
        @property
        def scope(self) -> object:  # pragma: no cover - never reached
            return None

    with pytest.raises(TypeError, match="FactIngestService"):
        runtime_loop.process_pending(
            _FakeOrchestrator(),  # type: ignore[arg-type]
            _FakeBridge(),  # type: ignore[arg-type]
            shadow_db=str(tmp_path / "s.db"),
            blocked_store_path=str(tmp_path / "b.sqlite3"),
        )


def test_loop_fallback_time_rows_surface_reason_codes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """NULL and blank event_ts (pre-ADR-0012/corrupt rows) are flagged, not faked as fresh."""
    from mind_runtime.shadow.redaction import init_store

    shadow_db = tmp_path / "shadow.db"
    init_store(shadow_db)
    monkeypatch.setenv("MIND_RUNTIME_SHADOW_DB", str(shadow_db))
    with sqlite3.connect(str(shadow_db)) as con:
        con.executemany(
            "INSERT INTO shadow_events "
            "(content_id, ts, user_hash, session_hash, channel, sender, "
            "trigger, source_domain, redacted_text, event_ts) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)",
            [
                (
                    301,
                    "2026-08-26T00:00:00+00:00",
                    "u",
                    "h",
                    "telegram",
                    "user",
                    "message",
                    "kayla_persona",
                    "旧数据一",
                    None,
                ),
                (
                    302,
                    "2026-08-26T01:00:00+00:00",
                    "u",
                    "h",
                    "telegram",
                    "user",
                    "message",
                    "kayla_persona",
                    "旧数据二",
                    "",
                ),
            ],
        )
        con.commit()

    stack = _stack(tmp_path)
    report = process_pending(
        stack.orchestrator,
        stack.bridge,
        shadow_db=str(shadow_db),
        blocked_store_path=str(tmp_path / "blocked.sqlite3"),
    )
    assert report.fallback_time_rows == 2
    assert report.processed == 2
    fallback_codes = [r for r in report.reason_codes if r.startswith("occurred_fallback_persisted")]
    assert len(fallback_codes) == 2
    # original event time NOT fabricated: occurred_at fell back to persisted ts
    for e in _service(stack.orchestrator).evidence.all():
        assert e.occurred_at.isoformat() in {
            "2026-08-26T00:00:00+00:00",
            "2026-08-26T01:00:00+00:00",
        }


def test_fold_outcome_pure_audit_counts_as_replayed() -> None:
    """A no-op audit turn never inflates the processed counter."""
    outcome = BridgeOutcome(
        mode=AdmissionMode.REPLAY,
        source_record_id="1",
        evidence_id="hermes:1",
        interaction_id="hermes-1",
        scope_user_id="user-a",
        disposition="replay",
        stage="committed",
        blocked_reason=None,
        projection_committed=False,
        downstream_evidence_refs=(),
        reason_codes=("admission_replay",),
    )
    report = runtime_loop.RuntimePassReport()
    runtime_loop._fold_outcome(report, outcome, cognitive_effect=False)
    assert (report.processed, report.replayed) == (0, 1)
