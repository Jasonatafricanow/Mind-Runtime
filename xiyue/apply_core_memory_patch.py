"""Patch an explicit Hermes gateway at its existing MR lifecycle boundaries."""

import argparse
from pathlib import Path

BEGIN = "                        _mr_handle, _mr_verdict = _mr_seam.begin_turn_clean("
COMMIT = "                            _active_adapter.commit_turn(_mr_handle)"
MARKER = "# MR-Mem core HTTP synchronization"


def render(source, repo_root):
    root = repr(str(repo_root.resolve()))
    if MARKER in source:
        if source.count(MARKER) != 1 or source.count("_core_sync(") != 2 or root not in source:
            raise ValueError("incomplete core memory patch or different repository")
        return source
    if (source.count(BEGIN) != 1 or source.count(COMMIT) != 1
            or "# MR-Mem native source synchronization" in source):
        raise ValueError("Hermes MR seam drift or competing native writer")
    newline = "\r\n" if "\r\n" in source else "\n"
    before = newline.join("                        " + line for line in (
        MARKER,
        "_mr_sys.path.insert(0, " + root + ")",
        "from xiyue.core_memory import sync_core_memory as _core_sync",
        "_core_sync(agent, source, session_id, _mr_seam.get_mr_adapter())",
    ))
    committed = newline.join((
        "                            if _active_adapter.commit_turn(_mr_handle):",
        "                                _core_sync(agent, source, session_id, "
        "_active_adapter, after_commit=True)",
    ))
    patched = source.replace(BEGIN, before + newline + BEGIN, 1)
    patched = patched.replace(COMMIT, committed, 1)
    compile(patched, "gateway/run.py", "exec")
    return patched


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--apply", action="store_true")
    parser.add_argument("--gateway-run-py", type=Path, required=True)
    args = parser.parse_args()
    with args.gateway_run_py.open(encoding="utf-8", newline="") as stream:
        source = stream.read()
    patched = render(source, Path(__file__).resolve().parents[1])
    if args.apply and source != patched:
        with args.gateway_run_py.open("w", encoding="utf-8", newline="") as stream:
            stream.write(patched)
    print("Core memory patch installed" if MARKER in source else "Core memory patch applicable")


if __name__ == "__main__":
    main()
