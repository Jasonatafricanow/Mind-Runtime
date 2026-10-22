"""Add native synchronization to an explicit, already MR-patched Hermes gateway."""

import argparse
from pathlib import Path

BEGIN = "                        _mr_handle, _mr_verdict = _mr_seam.begin_turn_clean("
COMMIT = "                            _active_adapter.commit_turn(_mr_handle)"
MARKER = "# MR-Mem native source synchronization"


def render(source, repo_root):
    if MARKER in source:
        if (source.count(MARKER) != 1 or source.count("_native_sync(") != 2
                or repr(str(repo_root.resolve())) not in source):
            raise ValueError("incomplete native memory patch or different repository")
        return source
    if source.count(BEGIN) != 1 or source.count(COMMIT) != 1:
        raise ValueError("Hermes MR seam drift; refusing to patch")
    newline = "\r\n" if "\r\n" in source else "\n"
    before = newline.join("                        " + line for line in (
        MARKER,
        "_mr_sys.path.insert(0, " + repr(str(repo_root.resolve())) + ")",
        "from xiyue.native_memory import sync_native_memory as _native_sync",
        "_native_sync(agent, source, session_id, _mr_seam.get_mr_adapter())",
    ))
    after = newline.join("                            " + line for line in (
        "_native_sync(agent, source, session_id, _active_adapter, compile_pending=True)",
    ))
    patched = source.replace(BEGIN, before + newline + BEGIN, 1)
    patched = patched.replace(COMMIT, COMMIT + newline + after, 1)
    compile(patched, "gateway/run.py", "exec")
    return patched


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--apply", action="store_true")
    parser.add_argument("--gateway-run-py", type=Path, required=True)
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    with args.gateway_run_py.open(encoding="utf-8", newline="") as stream:
        source = stream.read()
    patched = render(source, args.repo_root)
    if args.apply and source != patched:
        with args.gateway_run_py.open("w", encoding="utf-8", newline="") as stream:
            stream.write(patched)
    print("Native memory patch installed" if MARKER in source else "Native memory patch applicable")


if __name__ == "__main__":
    main()
