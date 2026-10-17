"""Per-run AML storage ownership and deterministic cleanup."""

from __future__ import annotations

import hashlib
import shutil
from pathlib import Path


def run_root(base: Path | str, run_id: str) -> Path:
    if not isinstance(run_id, str) or not run_id.strip():
        raise ValueError("run_id must be nonempty")
    digest = hashlib.sha256(run_id.encode("utf-8")).hexdigest()[:24]
    return Path(base) / f"aml-run-{digest}"


def delete_run_namespace(base: Path | str, run_id: str) -> bool:
    """Delete only the addressed competition namespace.

    The caller owns AML retention policy (for example, deletion after an
    evaluation finishes). MR production namespaces are never inferred here.
    """
    target = run_root(base, run_id)
    if not target.exists():
        return False
    shutil.rmtree(target)
    return True
