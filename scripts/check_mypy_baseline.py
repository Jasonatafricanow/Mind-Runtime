"""No-regression gate for historical mypy debt.

The baseline is debt accounting, not a claim that the repository is type-clean.
Existing (path, error-code) counts may shrink; new pairs or increases fail CI.

The baseline was generated from the two shipped source packages. Run mypy from
`src/` so each file has one stable module identity (for example
`observation_window.foo`, never both that and `src.observation_window.foo`).
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = ROOT / "src"
CONFIG_PATH = ROOT / "pyproject.toml"
BASELINE_PATH = ROOT / "scripts" / "mypy-baseline.json"
ERROR_RE = re.compile(r"^(.*?\.py):\d+(?::\d+)?: error: .*  \[([^\]]+)\]$")


def _run_mypy(args: list[str], *, cwd: Path) -> tuple[Counter[str], str, int]:
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "mypy",
            "--config-file",
            str(CONFIG_PATH),
            *args,
        ],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
    )
    output = "\n".join(part for part in (proc.stdout, proc.stderr) if part)
    counts: Counter[str] = Counter()
    for line in output.splitlines():
        match = ERROR_RE.match(line)
        if not match:
            continue
        path = Path(match.group(1))
        if not path.is_absolute():
            path = cwd / path
        try:
            rel = path.resolve().relative_to(ROOT.resolve())
        except ValueError:
            rel = path
        counts[f"{rel.as_posix()}|{match.group(2)}"] += 1
    return counts, output, proc.returncode


def main() -> int:
    baseline_raw = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
    allowed = Counter({str(k): int(v) for k, v in baseline_raw["entries"].items()})

    current, output, returncode = _run_mypy(
        ["-p", "mind_runtime", "-p", "observation_window"],
        cwd=SRC_ROOT,
    )
    if returncode not in {0, 1}:
        sys.stderr.write(output)
        return returncode

    regressions: list[tuple[str, int, int]] = []
    for key, count in sorted(current.items()):
        limit = allowed.get(key, 0)
        if count > limit:
            regressions.append((key, count, limit))

    baseline_total = sum(allowed.values())
    current_total = sum(current.values())
    print(f"Mypy debt: current={current_total}, baseline={baseline_total}")

    if regressions:
        print("Mypy baseline regressions:", file=sys.stderr)
        for key, count, limit in regressions:
            print(f"  {key}: current={count}, allowed={limit}", file=sys.stderr)
        if output:
            print("\nRaw mypy output:", file=sys.stderr)
            print(output, file=sys.stderr)
        return 1

    reduced = baseline_total - current_total
    if reduced > 0:
        print(f"Historical mypy debt reduced by {reduced} finding(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
