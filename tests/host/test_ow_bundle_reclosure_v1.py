"""Production-path regression tests for OW bundle re-closure."""

from __future__ import annotations

import json
import os
import sqlite3
import time
from pathlib import Path

import pytest


@pytest.fixture
def mr_repo_imports() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    for path in (repo_root / "xiyue", repo_root / "src"):
        if str(path) not in os.sys.path:
            os.sys.path.insert(0, str(path))


def test_production_ow_entrypoint_reaches_uvicorn_without_legacy_variables(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mr_repo_imports: None
) -> None:
    """Exercise BindingRegistry -> catalog -> resolved binding -> app composition."""
    from mind_runtime.binding_registry_composition import bootstrap_production_registry
    from mind_runtime.runtime_binding import production_binding
    from observation_window.web import runtime

    registry_dir = tmp_path / "registry"
    runtime_dir = tmp_path / "runtime"
    runtime_dir.mkdir()
    for database in (runtime_dir / "cognition_state.sqlite", runtime_dir / "facts.sqlite"):
        connection = sqlite3.connect(database)
        connection.close()
    bootstrap_production_registry(
        binding_id="xiyue-default",
        registry_dir=registry_dir,
        binding=production_binding("kayla_v0"),
    )
    captured: dict[str, object] = {}
    monkeypatch.setenv("MR_BINDING_REGISTRY_DIR", str(registry_dir))
    monkeypatch.delenv("MR_RUNTIME_BINDING", raising=False)
    monkeypatch.delenv("MR_FACTS_DB", raising=False)
    monkeypatch.delenv("MR_STATE_DB", raising=False)
    monkeypatch.setattr(
        runtime.uvicorn,
        "run",
        lambda app, **kwargs: captured.update(app=app, kwargs=kwargs),
    )

    rc = runtime.main(
        [
            "--runtime-dir",
            str(runtime_dir),
            "--port",
            "9876",
        ]
    )

    assert rc == 0
    assert captured["kwargs"] == {"host": "127.0.0.1", "port": 9876, "log_level": "info"}
    assert hasattr(captured["app"], "state")
    scoped = captured["app"].state.observation_binding_catalog.resolve_default()
    assert callable(scoped.context.live_trace_provider)


def test_gateway_reconciles_ow_late_start_without_moving_ingress_ready_at(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mr_repo_imports: None
) -> None:
    """T1 is DEGRADED; T4 OW health causes Gateway-owned READY refresh."""
    import mr_seam

    readiness = tmp_path / "readiness.json"
    monkeypatch.setenv("MR_READINESS_PATH", str(readiness))
    monkeypatch.setattr(
        mr_seam,
        "evaluate_mr_core_readiness",
        lambda adapter=None: (
            True,
            {
                "mr_adapter_initialized": True,
                "runtime_db_available": True,
                "semantic_provider_available": True,
                "appraisal_provider_available": True,
                "slow_writer_active": True,
            },
            [],
        ),
    )
    ow_is_healthy = {"value": False}
    monkeypatch.setattr(
        mr_seam,
        "check_observation_window_up",
        lambda port=8766: ow_is_healthy["value"],
    )

    mr_seam.begin_runtime_epoch(
        pid=os.getpid(),
        started_at="2026-09-09T00:00:00+00:00",
    )
    first = mr_seam.reconcile_bundle_readiness(adapter=object())
    assert first["core_ready"] is True
    assert first["ow_ready"] is False
    assert first["bundle_state"] == "DEGRADED"
    ingress_ready_at = first["runtime_ready_at"]

    stop_event = mr_seam.start_bundle_readiness_reconciler(
        adapter=object(), interval_s=0.01
    )
    try:
        ow_is_healthy["value"] = True
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            current = mr_seam.load_readiness()
            if current.get("bundle_state") == "READY":
                break
            time.sleep(0.01)
        current = mr_seam.load_readiness()
    finally:
        stop_event.set()
        mr_seam.stop_bundle_readiness_reconciler()

    assert current["core_ready"] is True
    assert current["ow_ready"] is True
    assert current["bundle_state"] == "READY"
    assert current["runtime_ready_at"] == ingress_ready_at


def test_process_alive_without_health_is_not_ow_ready(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mr_repo_imports: None
) -> None:
    """The bundle authority must use the HTTP health result, not a PID hint."""
    import mr_seam

    monkeypatch.setenv("MR_READINESS_PATH", str(tmp_path / "readiness.json"))
    monkeypatch.setattr(
        mr_seam,
        "evaluate_mr_core_readiness",
        lambda adapter=None: (True, {"core": True}, []),
    )
    monkeypatch.setattr(mr_seam, "check_observation_window_up", lambda port=8766: False)

    mr_seam.begin_runtime_epoch(pid=os.getpid(), started_at="2026-09-09T00:00:00+00:00")
    result = mr_seam.reconcile_bundle_readiness(adapter=object())

    assert result["core_ready"] is True
    assert result["ow_ready"] is False
    assert result["bundle_state"] == "DEGRADED"


def test_live_trace_projects_authoritative_bundle_and_production_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mr_repo_imports: None
) -> None:
    from observation_window import live_runtime_trace

    profile_dir = tmp_path / "profile"
    runtime_dir = profile_dir / "runtime"
    runtime_dir.mkdir(parents=True)
    (runtime_dir / "readiness.json").write_text(
        json.dumps(
            {
                "gateway_pid": 4242,
                "epoch_id": "epoch-test",
                "runtime_ready_at": "2026-09-09T01:00:00+08:00",
                "core_ready": True,
                "ow_ready": False,
                "bundle_state": "DEGRADED",
            }
        ),
        encoding="utf-8",
    )
    (profile_dir / "gateway.pid").write_text(json.dumps({"pid": 4242}), encoding="utf-8")
    (profile_dir / "config.yaml").write_text("", encoding="utf-8")

    class _FakeProcess:
        def cmdline(self):
            return ["python", "hermes_cli.main", "gateway"]

        def name(self):
            return "python.exe"

        def create_time(self):
            return 1_000.0

    monkeypatch.setattr(live_runtime_trace.psutil, "pid_exists", lambda pid: pid == 4242)
    monkeypatch.setattr(live_runtime_trace.psutil, "Process", lambda pid: _FakeProcess())
    monkeypatch.setattr(live_runtime_trace.psutil, "process_iter", lambda *args: [])

    repo_root = Path(__file__).resolve().parents[2]
    collector = live_runtime_trace.LiveRuntimeTraceCollector(
        repo_root=repo_root,
        hermes_profile_dir=profile_dir,
    )
    report = collector.collect()

    assert report.header.bundle_state == "DEGRADED"
    assert report.header.runtime_ready_at == "2026-09-09T01:00:00+08:00"
    assert report.header.epoch_id == "epoch-test"
    assert str(report.header.runtime_config_path).startswith(str(repo_root))
