"""Run the public long-horizon failure suite.

The suite is intentionally small. It selects existing regression tests that
exercise MR's authority boundaries across turns, replay, pending state, and
memory admission.

Add a case only when it represents a distinct failure mode that is useful to
reviewers or contributors.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

CASES: tuple[str, ...] = (
    # Derived runtime artifacts must not authorize their own future evidence.
    "tests/pipeline/test_no_self_authorizing_feedback.py",
    # Replaying the same evidence across restart must not create a second memory.
    "tests/memory/test_admission.py::test_admission_on_commits_once_and_restart_replay_is_noop",
    # Rejected assistant-derived evidence is retained for audit but cannot create memory.
    "tests/memory/test_admission.py::test_rejected_evidence_never_creates_job_or_memory",
    # An extractor cannot fabricate scope/evidence/observation provenance.
    "tests/memory/test_admission.py::test_extractor_cannot_forge_provenance",
    # Pending interpretation is visible as pending, not canonical truth.
    "tests/pipeline/test_c9_w1b_pending_overlay.py::test_w1b2_pending_not_canonical",
    # Rejected pending state is cleared without promotion.
    "tests/pipeline/test_c9_w1b_pending_overlay.py::test_w1b4_reject_clears_without_promotion",
    # Aborted turns cannot silently promote pending state.
    "tests/pipeline/test_c9_w1b_pending_overlay.py::test_w1b7_abort_clears_pending_no_promotion",
    # Replaying one evidence event does not duplicate provenance.
    "tests/facts/test_provenance.py::test_provenance_recording_is_idempotent_per_event",
)


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    command = [sys.executable, "-m", "pytest", "-q", "--tb=short", *CASES]
    return subprocess.call(command, cwd=root)


if __name__ == "__main__":
    raise SystemExit(main())
