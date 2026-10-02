"""Check/apply the bounded Body-call patch to an explicit Hermes 0.19.0 gateway."""

import argparse
from pathlib import Path

ANCHOR = (
    "                    result = agent.run_conversation(_api_run_message, **_conversation_kwargs)"
)
MARKER = "# Semantic Delta V1: sibling outputs at the existing Body call"


def render(source, repo_root):
    if MARKER in source:
        if source.count(MARKER) != 1 or "result = _delta_run_gateway_turn(" not in source:
            raise ValueError("incomplete Semantic Delta patch")
        return source
    if source.count(ANCHOR) != 1 or "# --- end Xiyue MR begin seam ---" not in source:
        raise ValueError("Hermes 0.19.0/MR Body anchor drift; refusing to patch")
    newline = "\r\n" if "\r\n" in source else "\n"
    prefix = "                    "
    lines = [
        MARKER,
        "if _mr_os.environ.get('SEMANTIC_DELTA_V1_ENABLED', 'false').strip().lower() "
        "in ('1', 'true', 'yes', 'on'):",
        "    _mr_sys.path.insert(0, " + repr(str(repo_root.resolve())) + ")",
        "    from xiyue.semantic_delta_gateway import run_gateway_turn as _delta_run_gateway_turn",
        "    result = _delta_run_gateway_turn(",
        "        agent, _api_run_message, seam=_mr_seam, handle=_mr_handle, source=source,",
        "        session_id=session_id, message_id=event_message_id, **_conversation_kwargs)",
        "else:",
        "    result = agent.run_conversation(_api_run_message, **_conversation_kwargs)",
    ]
    patched = source.replace(ANCHOR, newline.join(prefix + line for line in lines), 1)
    compile(patched, "gateway/run.py", "exec")
    return patched


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--check", action="store_true")
    modes.add_argument("--apply", action="store_true")
    parser.add_argument("--gateway-run-py", type=Path, required=True)
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    with args.gateway_run_py.open(encoding="utf-8", newline="") as stream:
        source = stream.read()
    patched = render(source, args.repo_root)
    if args.apply and patched != source:
        with args.gateway_run_py.open("w", encoding="utf-8", newline="") as stream:
            stream.write(patched)
    print(
        "Semantic Delta patch installed" if MARKER in source else "Semantic Delta patch applicable"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
