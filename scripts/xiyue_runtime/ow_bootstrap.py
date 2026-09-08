"""Launch the production OW module from this checkout.

The shared host Python has editable-source entries for older Mind Runtime
checkouts.  This tiny operational bootstrap pins the OW import root to the
same checkout used by the Gateway composition seam before importing OW.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def _is_legacy_mr_path(entry: str) -> bool:
    """Reject host-level editable paths from the retired common repository."""

    normalized = str(Path(entry)).replace("/", "\\").rstrip("\\").casefold()
    legacy_root = str(Path(r"C:\projects\Mind Runtime")).replace("/", "\\").rstrip("\\").casefold()
    return normalized == legacy_root or normalized.startswith(legacy_root + "\\")


sys.path[:] = [entry for entry in sys.path if not _is_legacy_mr_path(entry)]
sys.path[:0] = [str(REPO_ROOT / "src"), str(REPO_ROOT / "xiyue")]

from observation_window.web.runtime import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
