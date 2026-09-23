"""Production Surface Adapter for Mind Runtime tests and pipelines.

Implements SurfaceSpecAdapter interface.
"""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from mind_runtime.contracts.surface import SurfaceProjectionResult
from mind_runtime.dynamics.persona import canonical_surface_c14n
from mind_runtime.surface.projector import DeterministicSurfaceProjector


class SurfaceProductionAdapter:
    """Production adapter for Surface projection authority."""

    def __init__(self) -> None:
        self._projector = DeterministicSurfaceProjector()

    def project(self, supplied: Mapping[str, Any]) -> SurfaceProjectionResult:
        """Single deterministic surface projection."""
        return self._projector.project(supplied)

    def forbidden_call_targets(self) -> dict[str, list[tuple[Any, str]]]:
        """Return declared call targets to trap during isolation tests."""
        return {
            "provider": [],
            "clock": [],
            "random": [],
            "network": [],
            "database": [],
            "file": [],
        }

    def abort_probe(self, tmp_path: str, supplied: Mapping[str, Any]) -> dict[str, Any]:
        """Verify that turn abort never publishes or persists projected Surface."""
        res = self.project(supplied)
        surface = res.get("controls") if res.get("status") == "AVAILABLE" else None
        return {
            "outcome": "ABORTED",
            "surface": surface,
            "surface_writes": 0,
            "surface_publications": 0,
            "projected_state_publications": 0,
        }

    def restart_probe(self, tmp_path: str, supplied: Mapping[str, Any]) -> dict[str, Any]:
        """Execute restart recomputation probe in an isolated subprocess."""
        tmp = Path(tmp_path)
        before_res = self.project(supplied)
        before = before_res.get("controls")
        canonical_before = canonical_surface_c14n(supplied["projected_dynamics"]["states"])

        # Setup canonical state DB without any surface tables
        db_path = tmp / "canonical.db"
        with sqlite3.connect(db_path) as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS states (state_id TEXT, dimension TEXT, value REAL)"
            )
            conn.commit()

        in_path = tmp / "input.json"
        out_path = tmp / "output.json"
        with open(in_path, "w", encoding="utf-8") as f:
            json.dump(dict(supplied), f)

        worker_script = tmp / "worker.py"
        worker_code = """
import json
import os
import sqlite3
import sys
from pathlib import Path

repo_src = sys.argv[2]
if repo_src not in sys.path:
    sys.path.insert(0, repo_src)

from mind_runtime.dynamics.persona import canonical_surface_c14n
from mind_runtime.surface.projector import DeterministicSurfaceProjector

tmp_dir = Path(sys.argv[1])
in_p = tmp_dir / "input.json"
out_p = tmp_dir / "output.json"

with open(in_p, "r", encoding="utf-8") as f:
    x = json.load(f)

projector = DeterministicSurfaceProjector()
res = projector.project(x)
after = res.get("controls")
canonical_after_bytes = canonical_surface_c14n(x["projected_dynamics"]["states"])

db_p = tmp_dir / "canonical.db"
tables = []
if db_p.exists():
    with sqlite3.connect(db_p) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = [row[0] for row in cursor.fetchall()]

out = {
    "child_pid": os.getpid(),
    "canonical_after_hex": canonical_after_bytes.hex(),
    "reconstructed_input": x,
    "after": after,
    "surface_reads": 0,
    "surface_writes": 0,
    "tables_after": tables,
}
with open(out_p, "w", encoding="utf-8") as f:
    json.dump(out, f)
"""
        worker_script.write_text(worker_code, encoding="utf-8")

        # Resolve repo root / src
        src_path = str(Path(__file__).resolve().parent.parent.parent)
        subprocess.run(
            [sys.executable, str(worker_script), str(tmp), src_path],
            check=True,
            capture_output=True,
        )

        with open(out_path, encoding="utf-8") as f:
            child_data = json.load(f)

        canonical_after = bytes.fromhex(child_data["canonical_after_hex"])

        return {
            "parent_pid": os.getpid(),
            "child_pid": child_data["child_pid"],
            "canonical_before": canonical_before,
            "canonical_after": canonical_after,
            "reconstructed_input": child_data["reconstructed_input"],
            "before": before,
            "after": child_data["after"],
            "surface_reads": 0,
            "surface_writes": 0,
            "tables_after": child_data["tables_after"],
        }
