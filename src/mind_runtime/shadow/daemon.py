"""Shadow sync daemon: continuously syncs new Hermes messages into the
shadow store + affect trajectory, then sleeps.

Preferred over cron: watches continuously (≈30s latency), no per-tick
process spawn. Supervised by kayla-supervisor (proc check) so a crash
gets it restarted.

Usage:
    pythonw shadow_daemon.py        # background (no window)
    python shadow_daemon.py --once  # single pass (for manual checks)
"""

from __future__ import annotations

import argparse
import os
import sqlite3
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

LOG_DIR = Path.home() / ".hermes" / "profiles" / "xiyue" / "logs"
LOG = LOG_DIR / "shadow-daemon.log"
REPO = os.environ.get("MIND_RUNTIME_ROOT", str(Path(__file__).resolve().parents[3]))
VENV_PY = os.environ.get("MIND_RUNTIME_PYTHON", sys.executable)
AFFECT_DB = Path.home() / ".hermes" / "profiles" / "xiyue" / "shadow_affect.db"
STATES_DB = Path.home() / ".hermes" / "profiles" / "xiyue" / "shadow_states_v2.db"

POLL_SECONDS = 300  # sync cadence: 5 minutes (was 30s)
MAX_BACKFILL_LIMIT = 2000
# py launchers must not flash a console window (daemon runs via pythonw)
_CREATE_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0
# C2.10 gate (ADR-0012 §6): production cognition loop stays OFF unless the
# operator enables it explicitly; with it off, one_pass behaves exactly as
# it did before C2.10.
PRODUCTION_INGEST_ENV = "MIND_RUNTIME_PRODUCTION_INGEST"


def _production_ingest_enabled() -> bool:
    raw = os.environ.get(PRODUCTION_INGEST_ENV)
    return raw is not None and raw.strip().lower() in {"1", "true", "yes", "on"}


def _log(msg: str) -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    line = f"[{datetime.now(UTC).isoformat(timespec='seconds')}] {msg}"
    with LOG.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def _affect_count() -> int:
    try:
        con = sqlite3.connect(str(AFFECT_DB))
        try:
            row = con.execute("SELECT COUNT(*) FROM shadow_affect").fetchone()
            return int(row[0]) if row else 0
        finally:
            con.close()
    except sqlite3.Error:
        return 0


def one_pass() -> tuple[bool, str]:
    before = _affect_count()
    proc = subprocess.run(
        [VENV_PY, "-m", "mind_runtime.shadow.sync", "--limit", f"{MAX_BACKFILL_LIMIT}"],
        cwd=REPO,
        capture_output=True,
        text=True,
        timeout=240,
        creationflags=_CREATE_NO_WINDOW,
    )
    if proc.returncode != 0:
        return False, f"sync error rc={proc.returncode}: {proc.stderr[-200:]}"
    prod_note = ""
    if _production_ingest_enabled():
        # ADR-0012 sequencing: acquisition (done above) -> production
        # cognition -> legacy derived metrics. The loop subprocess carries
        # its own gate check and durable stack locations via env/flags.
        try:
            prod_note = f" prod={_run_production_ingest()}"
        except ProductionIngestError as exc:
            return False, f"production ingest error {exc}"
        # C5B (STEP 8): even with ZERO new Hermes source rows, the autonomous
        # cognitive tick must run — time drives cognition, not messages.
        # The tick subprocess carries its own fail-closed gate.
        if _proactive_tick_enabled():
            try:
                prod_note = f"{prod_note} tick={_run_proactive_tick()}"
            except ProductionIngestError as exc:
                return False, f"proactive tick error {exc}"
    after = _affect_count()
    snapshot_note = _legacy_metrics()
    if snapshot_note:
        return True, f"synced affect {before}->{after}; snapshot error {snapshot_note}{prod_note}"
    return True, f"synced; affect {before} -> {after}{prod_note}"


class ProductionIngestError(RuntimeError):
    """The production cognition loop subprocess failed."""


def _run_production_ingest() -> str:
    """One gated pass of the C2.10 loop; returns its stdout tail."""
    proc = subprocess.run(
        [
            VENV_PY,
            "-m",
            "mind_runtime.shadow.runtime_loop",
            "--limit",
            f"{MAX_BACKFILL_LIMIT}",
        ],
        cwd=REPO,
        capture_output=True,
        text=True,
        timeout=240,
        creationflags=_CREATE_NO_WINDOW,
    )
    if proc.returncode != 0:
        raise ProductionIngestError(f"rc={proc.returncode}: {prod_stderr_tail(proc)}")
    return proc.stdout.strip()[-200:]


def prod_stderr_tail(proc: subprocess.CompletedProcess[str]) -> str:
    return str(proc.stderr)[-200:]


# C5B (STEP 1): fail-closed proactive-tick gate. With it off, one_pass
# behaves byte-for-byte as the pre-C5B daemon.
PROACTIVE_TICK_ENV = "MIND_RUNTIME_PROACTIVE_TICK"


def _proactive_tick_enabled() -> bool:
    raw = os.environ.get(PROACTIVE_TICK_ENV)
    return raw is not None and raw.strip().lower() in {"1", "true", "yes", "on"}


def _run_proactive_tick() -> str:
    """One gated pass of the C5B cognitive tick; returns its stdout tail."""
    proc = subprocess.run(
        [
            VENV_PY,
            "-m",
            "mind_runtime.shadow.runtime_loop",
            "--proactive-tick",
            "--limit",
            "0",
        ],
        cwd=REPO,
        capture_output=True,
        text=True,
        timeout=240,
        creationflags=_CREATE_NO_WINDOW,
    )
    if proc.returncode != 0:
        raise ProductionIngestError(f"rc={proc.returncode}: {prod_stderr_tail(proc)}")
    return proc.stdout.strip()[-200:]


def _legacy_metrics() -> str:
    """Refresh shadow-derived projections; failures never fail the pass."""
    note = ""
    try:
        from mind_runtime.shadow.backfill import KNOWN_NAMES
        from mind_runtime.shadow.runner import shadow_db_path as _shadow_db_path
        from mind_runtime.shadow.states import extract_states

        extract_states(_shadow_db_path(), STATES_DB, known_names=KNOWN_NAMES)
    except Exception as exc:  # noqa: BLE001 - isolated layer (ADR-0012 §5)
        note += f" states error {exc!r};"
    try:
        subprocess.run(
            [VENV_PY, "-m", "mind_runtime.shadow.snapshot"],
            cwd=REPO,
            capture_output=True,
            text=True,
            timeout=60,
            creationflags=_CREATE_NO_WINDOW,
        )
    except Exception as exc:  # noqa: BLE001 - isolated layer (ADR-0012 §5)
        note += f" snapshot error {exc!r}"
    return note


def main() -> int:
    parser = argparse.ArgumentParser(description="shadow sync daemon")
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()

    if args.once:
        ok, msg = one_pass()
        print(msg)
        return 0 if ok else 1

    # Startup log runs only inside the live daemon right before the
    # unsupervisable loop below — same process-shell exemption.
    _log("shadow-daemon start")  # pragma: no cover - daemon shell, see loop
    # Genuine infinite supervision loop: exercised only by the live daemon
    # process; unit tests cover one_pass/_log/main(--once) directly instead.
    while True:  # pragma: no cover - long-running daemon shell
        try:
            ok, msg = one_pass()
            if not ok:
                _log(f"WARN {msg}")
            elif "->" in msg and "synced; affect" in msg:
                _log(msg)
        except Exception as exc:  # noqa: BLE001 - daemon must survive
            _log(f"ERROR {exc!r}")
        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    sys.exit(main())
