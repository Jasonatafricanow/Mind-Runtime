#!/usr/bin/env python3
"""Apply or verify the sanitized Hermes/MR seam patch.

The gateway package is external to this repository.  This tool therefore
requires an explicit gateway/run.py path and derives MR source paths from the
selected canonical checkout.  It never embeds the retired common-repository
path or credentials.

Usage:
    python xiyue/apply_mr_patch.py --check --gateway-run-py <path>
    python xiyue/apply_mr_patch.py --apply --gateway-run-py <path>

``--apply`` is idempotent for an already-patched gateway: it upgrades the
legacy duplicate bootstrap, removes the retired old-venv injection and
rewrites MR source/seam literals to the chosen checkout. For an unpatched
matching Hermes 0.19.0 gateway it renders and applies the repository-owned
patch template, failing closed on drift.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

LEGACY_ROOT = Path(r"C:\projects\Mind Runtime")
TEMPLATE = Path(__file__).resolve().parent / "patches" / "hermes-0.19.0-mr-current.patch.template"
BEGIN_MARKER = "Xiyue MR seam: begin_turn + inject bounded context (HI-2)"
COMMIT_MARKER = "Xiyue MR seam: commit/abort (HI-2)"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8", newline="")


def _write(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8", newline="")


def _literal(value: Path) -> str:
    return "r'" + str(value.resolve()).replace("'", "\\'") + "'"


def _contains_legacy_path(source: str) -> bool:
    needle = str(LEGACY_ROOT).replace("/", "\\").casefold()
    normalized = source.replace("/", "\\").casefold()
    return needle in normalized


def _rewrite_current(source: str, repo_root: Path, hermes_site_packages: Path) -> str:
    """Rewrite an already-installed seam without changing its behavior."""

    source = re.sub(
        (
            r"^\s*_mr_sys\.path\.insert\(0, r'C:\\projects\\Mind Runtime\\"
            r"\.venv\\Lib\\site-packages'\)\r?\n"
        ),
        lambda _: f"_mr_sys.path.insert(0, {_literal(hermes_site_packages)})\n",
        source,
        flags=re.MULTILINE,
    )
    source = source.replace(
        r"r'C:\projects\mind-runtime-main-merge\src'",
        _literal(repo_root / "src"),
    )
    source = source.replace(
        r"r'C:\projects\mind-runtime-main-merge\xiyue'",
        _literal(repo_root / "xiyue"),
    )
    return source


def _upgrade_legacy(source: str, repo_root: Path, hermes_site_packages: Path) -> str:
    """Replace the known HI-2 duplicate bootstrap without touching Hermes code."""

    marker = "# --- Xiyue MR seam bootstrap (HI-2) ---"
    end_marker = "# --- end Xiyue MR seam bootstrap ---"
    if source.count(marker) == 1 and source.count(end_marker) == 1:
        return source
    if source.count(marker) != 2 or source.count(end_marker) != 2:
        raise SystemExit("Unknown Hermes MR bootstrap layout; refusing to rewrite")
    line_ending = "\r\n" if "\r\n" in source else "\n"
    source = source.replace("\r\n", "\n")
    start = source.index(marker)
    first_end = source.index(end_marker, start) + len(end_marker)
    end = source.index(end_marker, first_end) + len(end_marker)
    old_bootstrap = source[start:end]
    if (
        "_mr_seam.on_gateway_process_startup()" not in old_bootstrap
        or "_mr_adapter = _mr_seam.get_mr_adapter()" not in old_bootstrap
    ):
        raise SystemExit("Unknown Hermes MR bootstrap behavior; refusing to rewrite")
    new_bootstrap = f'''{marker}
import os as _mr_os
import sys as _mr_sys

_mr_enabled = _mr_os.environ.get("MR_ENABLED", "false").strip().lower() in (
    "1", "true", "yes", "on"
)
_mr_seam = None
_mr_render_bounded = lambda b: None
if _mr_enabled:
    _mr_sys.path.insert(0, {_literal(hermes_site_packages)})
    _mr_sys.path.insert(0, {_literal(repo_root / "src")})
    _mr_sys.path.insert(0, {_literal(repo_root / "xiyue")})
    try:
        import mr_seam as _mr_seam
        _mr_seam._MR_SRC = {_literal(repo_root / "src")}
        _mr_render_bounded = _mr_seam.render_bounded
    except Exception:
        _mr_seam = None
{end_marker}'''
    source = source[:start] + new_bootstrap + source[end:]
    lock_anchor = "    atexit.register(release_gateway_runtime_lock)\n"
    gate_anchor = (
        '                if _mr_profile == "xiyue" and _mr_verdict is not None '
        'and not _mr_verdict.admitted and _mr_verdict.status in ("NOT_READY", "FAILED"):\n'
    )
    response_anchor = (
        '"final_response": _mr_verdict.error_message or '
        '"Mind Runtime is temporarily unavailable. (MR_NOT_READY)",'
    )
    adapter_anchor = (
        "                    _active_adapter = _mr_seam.get_mr_adapter() "
        "if _mr_seam else _mr_adapter\n"
    )
    for anchor in (lock_anchor, gate_anchor, response_anchor, adapter_anchor):
        if source.count(anchor) != 1:
            raise SystemExit("Unknown Hermes MR seam layout; refusing to rewrite")
    source = source.replace(
        lock_anchor,
        lock_anchor
        + "\n    # Establish this process's MR epoch only after the gateway "
        + "owns its runtime lock.\n"
        + "    if _mr_seam is not None:\n        _mr_seam.on_gateway_process_startup()\n",
        1,
    )
    source = source.replace(
        gate_anchor,
        '                if _mr_profile == "xiyue" and (\n'
        '                    (_mr_enabled and _mr_seam is None)\n'
        '                    or (_mr_verdict is not None and not _mr_verdict.admitted '
        'and _mr_verdict.status in ("NOT_READY", "FAILED"))\n'
        '                ):\n',
        1,
    )
    source = source.replace(
        response_anchor,
        '"final_response": (getattr(_mr_verdict, "error_message", None) '
        'if _mr_verdict is not None else None) or '
        '"Mind Runtime is temporarily unavailable. (MR_NOT_READY)",',
        1,
    )
    source = source.replace(
        adapter_anchor,
        "                    _active_adapter = _mr_seam.get_mr_adapter() if _mr_seam else None\n",
        1,
    )
    return source.replace("\n", line_ending)


def _render_template(repo_root: Path, hermes_site_packages: Path) -> str:
    template = _read(TEMPLATE)
    return (
        template.replace("__PATCH_CONTEXT_BLANK_1__", " ")
        .replace("__PATCH_CONTEXT_BLANK_13__", "             ")
        .replace("__MR_SRC_LITERAL__", _literal(repo_root / "src"))
        .replace("__MR_XIYUE_LITERAL__", _literal(repo_root / "xiyue"))
        .replace("__HERMES_SITE_PACKAGES_LITERAL__", _literal(hermes_site_packages))
    )


def _check(source: str, repo_root: Path) -> list[str]:
    errors: list[str] = []
    if _contains_legacy_path(source):
        errors.append(f"retired path present: {LEGACY_ROOT}")
    if BEGIN_MARKER not in source or COMMIT_MARKER not in source:
        errors.append("MR begin/commit seam markers are incomplete")
    expected_src = str((repo_root / "src").resolve()).replace("/", "\\").casefold()
    normalized = source.replace("/", "\\").casefold()
    if expected_src not in normalized:
        errors.append(f"canonical MR source is not present: {repo_root / 'src'}")
    if "result = agent.run_conversation(_api_run_message, **_conversation_kwargs)" not in source:
        errors.append("Hermes run anchor is missing")
    if 'final_response = result.get("final_response")' not in source:
        errors.append("Hermes commit anchor is missing")
    if source.count("# --- Xiyue MR seam bootstrap (HI-2) ---") != 1:
        errors.append("MR bootstrap must appear exactly once")
    if '_mr_os.environ.get("MR_ENABLED", "false")' not in source:
        errors.append("MR bootstrap must require explicit enablement")
    if "(_mr_enabled and _mr_seam is None)" not in source:
        errors.append("enabled MR import failure must block ingress")
    startup = source.find("_mr_seam.on_gateway_process_startup()")
    lock = source.find("atexit.register(release_gateway_runtime_lock)")
    if startup < 0 or lock < 0 or startup < lock:
        errors.append("MR epoch must start after the gateway runtime lock")
    if source.count("_mr_seam.on_gateway_process_startup()") != 1:
        errors.append("MR epoch must start exactly once")
    return errors


def _apply_template(gateway_run: Path, repo_root: Path, hermes_site_packages: Path) -> None:
    patch_text = _render_template(repo_root, hermes_site_packages)
    gateway_root = gateway_run.parent.parent
    check = subprocess.run(
        [
            "git", "apply", "--unsafe-paths", "--check", "--ignore-whitespace",
            "--whitespace=nowarn", "-",
        ],
        cwd=gateway_root,
        input=patch_text.encode("utf-8"),
        capture_output=True,
        check=False,
    )
    if check.returncode != 0:
        detail = (check.stderr or check.stdout).decode("utf-8", errors="replace").strip()
        raise SystemExit(
            "Hermes gateway patch preflight failed; version drift or wrong target:\n"
            + detail
        )
    applied = subprocess.run(
        ["git", "apply", "--unsafe-paths", "--ignore-whitespace", "--whitespace=nowarn", "-"],
        cwd=gateway_root,
        input=patch_text.encode("utf-8"),
        capture_output=True,
        check=False,
    )
    if applied.returncode != 0:
        detail = (applied.stderr or applied.stdout).decode("utf-8", errors="replace").strip()
        raise SystemExit(detail)


def main() -> int:
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--apply", action="store_true")
    parser.add_argument("--gateway-run-py", type=Path, required=True)
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
    )
    parser.add_argument(
        "--hermes-site-packages",
        type=Path,
        default=None,
        help="Hermes site-packages path; defaults to gateway/run.py's site-packages directory.",
    )
    args = parser.parse_args()

    gateway_run = args.gateway_run_py.resolve()
    repo_root = args.repo_root.resolve()
    hermes_site_packages = (
        args.hermes_site_packages.resolve()
        if args.hermes_site_packages is not None
        else gateway_run.parent.parent.resolve()
    )
    if not gateway_run.is_file():
        print(f"ERROR: gateway/run.py not found: {gateway_run}", file=sys.stderr)
        return 1

    source = _read(gateway_run)
    if args.apply:
        if BEGIN_MARKER in source and COMMIT_MARKER in source:
            source = _upgrade_legacy(source, repo_root, hermes_site_packages)
            rewritten = _rewrite_current(source, repo_root, hermes_site_packages)
            _write(gateway_run, rewritten)
        else:
            _apply_template(gateway_run, repo_root, hermes_site_packages)
        source = _read(gateway_run)

    errors = _check(source, repo_root)
    if errors:
        print("PATCH_CHECK=FAIL")
        for error in errors:
            print(f"- {error}")
        return 1
    print("PATCH_CHECK=PASS")
    print(f"gateway_run_py={gateway_run}")
    print(f"repo_root={repo_root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
