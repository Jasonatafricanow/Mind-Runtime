"""No-regression gate for the repository's historical Ruff debt.

The baseline is debt accounting, not a claim that the repository is lint-clean.
Existing counts may shrink. New (path, code) pairs or increases fail CI.
F821 (undefined name) is never grandfathered.
"""

from __future__ import annotations

import json
import subprocess
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASELINE_PATH = ROOT / "scripts" / "ruff-baseline.json"
FORBIDDEN_CODES = {"F821"}


def _run_ruff() -> list[dict[str, object]]:
    proc = subprocess.run(
        [sys.executable, "-m", "ruff", "check", "src", "tests", "--output-format=json"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode not in {0, 1}:
        sys.stderr.write(proc.stdout)
        sys.stderr.write(proc.stderr)
        raise SystemExit(proc.returncode)
    try:
        return json.loads(proc.stdout or "[]")
    except json.JSONDecodeError as exc:
        sys.stderr.write(proc.stdout)
        sys.stderr.write(proc.stderr)
        raise SystemExit(f"Could not parse Ruff JSON output: {exc}") from exc


def _key(item: dict[str, object]) -> str:
    filename = Path(str(item["filename"]))
    try:
        rel = filename.resolve().relative_to(ROOT.resolve())
    except ValueError:
        rel = filename
    code = str(item["code"])
    return f"{rel.as_posix()}|{code}"


def main() -> int:
    baseline_raw = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
    allowed = {str(k): int(v) for k, v in baseline_raw["entries"].items()}
    findings = _run_ruff()
    current = Counter(_key(item) for item in findings)

    forbidden = sorted(
        key for key, count in current.items()
        if count > 0 and key.rsplit("|", 1)[-1] in FORBIDDEN_CODES
    )
    regressions: list[tuple[str, int, int]] = []
    for key, count in sorted(current.items()):
        limit = allowed.get(key, 0)
        if count > limit:
            regressions.append((key, count, limit))

    baseline_total = sum(allowed.values())
    current_total = sum(current.values())
    print(f"Ruff debt: current={current_total}, baseline={baseline_total}")

    if forbidden:
        print("Forbidden Ruff findings:", file=sys.stderr)
        for key in forbidden:
            print(f"  {key}: {current[key]}", file=sys.stderr)

    if regressions:
        print("Ruff baseline regressions:", file=sys.stderr)
        regression_keys = {key for key, _, _ in regressions}
        for key, count, limit in regressions:
            print(f"  {key}: current={count}, allowed={limit}", file=sys.stderr)
        for item in findings:
            if _key(item) in regression_keys:
                print(json.dumps(item, sort_keys=True), file=sys.stderr)

    if forbidden or regressions:
        return 1

    reduced = baseline_total - current_total
    if reduced > 0:
        print(f"Historical Ruff debt reduced by {reduced} finding(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
