"""D11L shadow deployment unit — runner entry point (C2 minimal).

The runner is the deployable Mind Runtime shadow unit:
  * reads eligible traffic (one event per call or via --once), classifies,
    and (when the gate is on) mirrors the event into the shadow store.
  * fail-closed: gate OFF => refuse; classifier INELIGIBLE => skip.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from mind_runtime.shadow.classifier import EventMeta, classify


def shadow_db_path() -> Path:
    return Path(
        os.environ.get(
            "MIND_RUNTIME_SHADOW_DB",
            str(Path.home() / ".hermes" / "profiles" / "xiyue" / "shadow.db"),
        )
    )


def gate_enabled() -> bool:
    raw = os.environ.get("MIND_RUNTIME_SHADOW_ENABLED")
    if raw is None:
        return False
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def handle_event(
    meta: EventMeta, *, dry_run: bool = False, text: str = "", known_names: tuple[str, ...] = ()
) -> str:
    """Classify and mirror one event into the shadow store.

    Returns a status string for the caller/log:
      refused-gate | ineligible | eligible-recorded | eligible-dry
    """
    if not gate_enabled():
        return "refused-gate"
    if not classify(meta):
        return "ineligible"
    if dry_run:
        return "eligible-dry"
    from mind_runtime.shadow.redaction import init_store, store_record

    db = shadow_db_path()
    init_store(db)
    store_record(
        db,
        user_id=meta.session,
        session_id=meta.session,
        channel=meta.channel,
        sender=meta.sender,
        trigger=meta.trigger,
        source_domain=meta.source_domain,
        text=text,
        known_names=known_names,
    )
    return "eligible-recorded"


def main() -> None:
    parser = argparse.ArgumentParser(description="D11L shadow runner")
    parser.add_argument("--once", action="store_true", help="process one event then exit")
    parser.add_argument("--dry-run", action="store_true", help="classify only, no store")
    args = parser.parse_args()

    # The runner is intentionally minimal in this evidence iteration; the
    # message source adapter (telegram/weixin) is the environment-gate step.
    if args.once:
        print(
            f"shadow runner: gate={gate_enabled()} db={shadow_db_path()} "
            "(source adapter wiring pending)"
        )
    else:
        print("shadow runner: awaiting source adapter (env gate step)")


if __name__ == "__main__":
    main()
