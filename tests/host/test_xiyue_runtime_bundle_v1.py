"""Tests for XIYUE-RUNTIME-BUNDLE-V1: Bounded Readiness + Ingress Hygiene.

Covers:
1. Pure read-only readiness evaluator (zero disk writes, byte-for-byte immutability).
2. Gateway-owned runtime epoch lifecycle (no accidental overwrite by other processes).
3. Separation of Gateway liveliness, 5 MR core components, and Observation Window.
4. Fail-closed ingress gating for profile 'xiyue' (no vanilla fallback on failure).
5. Outage backlog quarantine (source_occurred_at < runtime_ready_at -> PRE_READY_BACKLOG).
6. Supervisor crash recovery simulation (P1 -> P2 -> epoch refresh -> backlog quarantine).
7. Live admission for identical text when source_occurred_at >= runtime_ready_at.
"""

from __future__ import annotations

from datetime import datetime, timezone, timedelta
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import pytest

# Ensure the repository source tree is importable for the host integration test.
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_SRC_DIR = _REPO_ROOT / "src"

if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))

from xiyue import mr_seam


@pytest.fixture
def isolated_readiness_env(monkeypatch, tmp_path):
    """Set up an isolated readiness file in a temporary directory."""
    rf = tmp_path / "readiness.json"
    monkeypatch.setenv("MR_READINESS_PATH", str(rf))
    return rf


class TestPureReadinessEvaluator:
    """Requirement 1 & 5: evaluate_mr_core_readiness is pure and read-only."""

    def test_evaluator_leaves_readiness_json_byte_for_byte_unchanged(
        self, isolated_readiness_env, monkeypatch
    ):
        baseline_content = json.dumps(
            {
                "epoch_id": "epoch-baseline-12345",
                "gateway_pid": 99999,
                "gateway_started_at": "2026-09-05T12:00:00+00:00",
                "runtime_ready_at": "2026-09-05T12:01:00+00:00",
                "bundle_state": "READY",
                "core_ready": True,
                "ow_ready": True,
                "checks": {},
                "reasons": [],
            },
            indent=2,
        ).encode("utf-8")
        isolated_readiness_env.write_bytes(baseline_content)
        hash_before = hashlib.sha256(baseline_content).hexdigest()

        # Call evaluate_mr_core_readiness (and its alias evaluate_core_readiness)
        core_ok, checks, reasons = mr_seam.evaluate_mr_core_readiness()
        alias_ok, _, _ = mr_seam.evaluate_core_readiness()

        # Verify readiness.json byte-for-byte unchanged
        bytes_after = isolated_readiness_env.read_bytes()
        hash_after = hashlib.sha256(bytes_after).hexdigest()
        assert hash_before == hash_after, "readiness.json was modified by evaluate_mr_core_readiness!"

    def test_load_readiness_leaves_missing_file_untouched(self, isolated_readiness_env):
        assert not isolated_readiness_env.exists()
        res = mr_seam.load_readiness()
        assert not isolated_readiness_env.exists(), "load_readiness created a file on disk!"
        assert res.get("bundle_state") == "NOT_READY"
        assert res.get("core_ready") is False

    def test_evaluator_does_not_check_gateway_alive_via_current_process(self):
        """The 5 MR core components must not contain gateway_alive."""
        _, checks, _ = mr_seam.evaluate_mr_core_readiness()
        assert "gateway_alive" not in checks, "gateway_alive must not be in MR core checks!"
        expected_keys = {
            "mr_adapter_initialized",
            "runtime_db_available",
            "semantic_provider_available",
            "appraisal_provider_available",
            "slow_writer_active",
        }
        assert set(checks.keys()) == expected_keys


class TestGatewayEpochOwnership:
    """Requirement 2: Epoch creation is gateway-owned; foreign processes cannot mark ready."""

    def test_begin_runtime_epoch_initializes_not_ready(self, isolated_readiness_env):
        epoch_rec = mr_seam.begin_runtime_epoch(pid=1234, started_at="2026-09-05T12:00:00+00:00")
        assert epoch_rec["epoch_id"] == "epoch-1234-1788609600"
        assert epoch_rec["gateway_pid"] == 1234
        assert epoch_rec["runtime_ready_at"] is None
        assert epoch_rec["bundle_state"] == "NOT_READY"
        assert epoch_rec["core_ready"] is False

    def test_mark_runtime_ready_refuses_write_from_different_pid(
        self, isolated_readiness_env, monkeypatch
    ):
        # Established by PID 1111
        mr_seam.begin_runtime_epoch(pid=1111, started_at="2026-09-05T12:00:00+00:00")
        hash_before = hashlib.sha256(isolated_readiness_env.read_bytes()).hexdigest()

        # Current process PID is os.getpid() != 1111
        res = mr_seam.mark_runtime_ready()
        hash_after = hashlib.sha256(isolated_readiness_env.read_bytes()).hexdigest()

        assert hash_before == hash_after, "Non-gateway process marked foreign epoch ready!"
        assert res.get("gateway_pid") == 1111


class TestIngressAdmissionAndBacklogGating:
    """Requirements B, C, D: Fail-closed on xiyue, backlog quarantine before begin_turn."""

    def test_not_ready_fails_closed_for_profile_xiyue(self, isolated_readiness_env):
        # Epoch initialized as NOT_READY
        mr_seam.begin_runtime_epoch(pid=os.getpid(), started_at="2026-09-05T12:00:00+00:00")

        verdict = mr_seam.check_ingress_admission(
            profile="xiyue",
            source_occurred_at=datetime.now(timezone.utc),
        )
        assert not verdict.admitted
        assert verdict.status == "NOT_READY"
        assert verdict.error_message is not None

        # Non-xiyue profile passes through fail-soft
        other_verdict = mr_seam.check_ingress_admission(
            profile="default",
            source_occurred_at=datetime.now(timezone.utc),
        )
        assert other_verdict.admitted

    def test_outage_backlog_quarantined_strictly(self, isolated_readiness_env):
        now = datetime.now(timezone.utc)
        ready_time = now
        mr_seam.begin_runtime_epoch(pid=os.getpid(), started_at=(now - timedelta(seconds=60)).isoformat())

        # Force ready with a known runtime_ready_at
        ready_rec = mr_seam.load_readiness()
        ready_rec["core_ready"] = True
        ready_rec["bundle_state"] = "READY"
        ready_rec["runtime_ready_at"] = ready_time.isoformat()
        mr_seam.save_readiness(ready_rec)

        # Message sent before ready_time (e.g. 5 seconds earlier)
        outage_ts = ready_time - timedelta(seconds=5)
        v_backlog = mr_seam.check_ingress_admission(
            profile="xiyue",
            source_occurred_at=outage_ts,
        )
        assert not v_backlog.admitted
        assert v_backlog.status == "PRE_READY_BACKLOG"

        # Message sent after ready_time (e.g. 1 second later) with IDENTICAL text
        live_ts = ready_time + timedelta(seconds=1)
        v_live = mr_seam.check_ingress_admission(
            profile="xiyue",
            source_occurred_at=live_ts,
        )
        assert v_live.admitted
        assert v_live.status == "READY"

    def test_source_timestamp_coercion_never_synthesizes_now(self):
        # None -> None
        assert mr_seam.coerce_source_timestamp(None) is None
        # Invalid string -> None
        assert mr_seam.coerce_source_timestamp("invalid-date") is None
        # Int epoch seconds -> timezone-aware UTC datetime
        dt = mr_seam.coerce_source_timestamp(1788609600)
        assert dt is not None
        assert dt.tzinfo == timezone.utc
        assert dt.year == 2026


class TestSupervisorCrashRecoverySimulation:
    """TEST 6: Supervisor automatic crash recovery semantics."""

    def test_supervisor_crash_recovery_creates_new_epoch(self, isolated_readiness_env):
        # Initial state: Gateway P1 is running, epoch A is established and ready
        p1_pid = 10001
        p1_start = "2026-09-05T12:00:00+00:00"
        t1_ready = datetime(2026, 9, 5, 12, 1, 0, tzinfo=timezone.utc)

        mr_seam.begin_runtime_epoch(pid=p1_pid, started_at=p1_start)
        data_a = mr_seam.load_readiness()
        data_a["core_ready"] = True
        data_a["bundle_state"] = "READY"
        data_a["runtime_ready_at"] = t1_ready.isoformat()
        mr_seam.save_readiness(data_a)

        epoch_a_id = data_a["epoch_id"]
        assert epoch_a_id.startswith("epoch-10001-")

        # CRASH ACTION: P1 is killed. Supervisor starts P2 (pid 10002).
        p2_pid = 10002
        p2_start = "2026-09-05T12:05:00+00:00"
        t2_ready = datetime(2026, 9, 5, 12, 5, 30, tzinfo=timezone.utc)

        # Before P2 establishes its epoch or becomes ready:
        # A message arrives stamped during outage interval (e.g. 12:03:00)
        t_outage = datetime(2026, 9, 5, 12, 3, 0, tzinfo=timezone.utc)

        # P2 boots: on_gateway_process_startup initializes epoch B
        epoch_b_rec = mr_seam.begin_runtime_epoch(pid=p2_pid, started_at=p2_start)
        assert epoch_b_rec["epoch_id"] != epoch_a_id
        assert epoch_b_rec["gateway_pid"] == p2_pid
        assert epoch_b_rec["runtime_ready_at"] is None
        assert epoch_b_rec["bundle_state"] == "NOT_READY"

        # Message checked while P2 is NOT_READY -> rejected as NOT_READY
        v_pre = mr_seam.check_ingress_admission(profile="xiyue", source_occurred_at=t_outage)
        assert not v_pre.admitted
        assert v_pre.status == "NOT_READY"

        # P2 achieves MR Core readiness at T2
        epoch_b_rec["core_ready"] = True
        epoch_b_rec["bundle_state"] = "READY"
        epoch_b_rec["runtime_ready_at"] = t2_ready.isoformat()
        mr_seam.save_readiness(epoch_b_rec)

        # Message sent during outage (12:03:00) delivered after T2 (12:05:30)
        v_outage = mr_seam.check_ingress_admission(profile="xiyue", source_occurred_at=t_outage)
        assert not v_outage.admitted
        assert v_outage.status == "PRE_READY_BACKLOG"
        assert "source_occurred_at" in v_outage.reason

        # Message sent fresh after T2 (12:05:40) -> Admitted live
        t_fresh = datetime(2026, 9, 5, 12, 5, 40, tzinfo=timezone.utc)
        v_fresh = mr_seam.check_ingress_admission(profile="xiyue", source_occurred_at=t_fresh)
        assert v_fresh.admitted
        assert v_fresh.status == "READY"


class TestBundleConjunctionAndTurnFailClosed:
    """OW degradation and turn execution fail-closed semantics."""

    def test_bundle_state_ready_vs_degraded_based_on_ow(
        self, isolated_readiness_env, monkeypatch
    ):
        mr_seam.begin_runtime_epoch(pid=os.getpid(), started_at="2026-09-05T12:00:00+00:00")

        # Mock core ready = True
        monkeypatch.setattr(
            mr_seam,
            "evaluate_mr_core_readiness",
            lambda adapter=None: (True, {}, []),
        )

        # OW UP -> READY
        monkeypatch.setattr(mr_seam, "check_observation_window_up", lambda port=8766: True)
        res_ready = mr_seam.mark_runtime_ready(_allow_test_write=True)
        assert res_ready["bundle_state"] == "READY"
        assert res_ready["core_ready"] is True
        assert res_ready["ow_ready"] is True

        # OW DOWN -> DEGRADED
        monkeypatch.setattr(mr_seam, "check_observation_window_up", lambda port=8766: False)
        res_degraded = mr_seam.mark_runtime_ready(_allow_test_write=True)
        assert res_degraded["bundle_state"] == "DEGRADED"
        assert res_degraded["core_ready"] is True
        assert res_degraded["ow_ready"] is False

    def test_turn_fail_closed_on_profile_xiyue_when_adapter_throws(
        self, isolated_readiness_env, monkeypatch
    ):
        # Set bundle ready
        mr_seam.begin_runtime_epoch(pid=os.getpid(), started_at="2026-09-05T12:00:00+00:00")
        rec = mr_seam.load_readiness()
        rec["core_ready"] = True
        rec["bundle_state"] = "READY"
        rec["runtime_ready_at"] = "2026-09-05T12:00:00+00:00"
        mr_seam.save_readiness(rec)

        # Mock adapter throwing error
        class BrokenAdapter:
            def begin_turn(self, **kwargs):
                raise RuntimeError("LLM provider 503 Service Unavailable")

        monkeypatch.setattr(mr_seam, "get_mr_adapter", lambda: BrokenAdapter())

        # For profile="xiyue", must fail closed
        handle, verdict = mr_seam.begin_turn_clean(
            message="hello",
            channel="telegram",
            session_id="s1",
            occurred_at=datetime.now(timezone.utc),
            profile="xiyue",
        )
        assert handle is None
        assert not verdict.admitted
        assert verdict.status == "FAILED"
        assert "503" in verdict.reason
        assert "temporarily unavailable" in (verdict.error_message or "") or "failed" in (verdict.error_message or "")


class TestRequiredRuntimeFailureSeam:
    """TEST 7: Full gateway seam execution under required provider failure vs valid abstention control."""

    def test_required_provider_failure_fails_closed_and_aborts_cleanly(
        self, tmp_path, monkeypatch
    ):
        """Prove all 9 points of TEST 7 with actual Xiyue adapter and TurnOrchestrator."""
        from mind_runtime.contracts import Scope, ScopeDomain
        from mind_runtime.facts.persistence import SqliteFactBackend
        from mind_runtime.host.xiyue_adapter import default_adapter
        from mind_runtime.pipeline.orchestrator import TurnState
        from mind_runtime.state.persistence import SqliteStateBackend
