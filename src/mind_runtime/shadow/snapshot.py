"""Emotion snapshot generator: summarizes recent shadow affect for xiyue.

Reads shadow_affect (built continuously by the shadow daemon) and writes a
compact JSON snapshot the persona can read when starting a session / before
tending to the user — this is the P2 "context assistance" read path.

Snapshot file: ~/.hermes/profiles/xiyue/state/emotion_snapshot.json
"""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

AFFECT_DB = Path.home() / ".hermes" / "profiles" / "xiyue" / "shadow_affect.db"
STATES_DB = Path.home() / ".hermes" / "profiles" / "xiyue" / "shadow_states_v2.db"
SNAPSHOT = Path.home() / ".hermes" / "profiles" / "xiyue" / "state" / "emotion_snapshot.json"

WINDOWS = {
    "day": timedelta(days=1),
    "week": timedelta(days=7),
    "month": timedelta(days=30),
}


def _window_counts(since: datetime) -> dict[str, int]:
    con = sqlite3.connect(str(AFFECT_DB))
    try:
        rows = con.execute(
            "SELECT dimension, COUNT(*) FROM shadow_affect "
            "WHERE sender='user' AND ts >= ? "
            "GROUP BY dimension ORDER BY COUNT(*) DESC",
            (since.isoformat(timespec="seconds"),),
        ).fetchall()
        return {dim: cnt for dim, cnt in rows}
    finally:
        con.close()


def _latest_user_message() -> tuple[str | None, str | None]:
    con = sqlite3.connect(str(AFFECT_DB))
    try:
        row = con.execute(
            "SELECT ts, dimension FROM shadow_affect WHERE sender='user' ORDER BY ts DESC LIMIT 1"
        ).fetchone()
        return (row[0], row[1]) if row else (None, None)
    finally:
        con.close()


def generate_snapshot() -> dict[str, object]:
    now = datetime.now(UTC)
    windows: dict[str, object] = {}
    snapshot: dict[str, object] = {
        "generated_at": now.isoformat(timespec="seconds"),
        "windows": windows,
        "latest_user": None,
    }
    for name, delta in WINDOWS.items():
        counts = _window_counts(now - delta)
        total = sum(counts.values())
        # dominant NON-neutral dimension is what matters to the persona;
        # neutral is the default baseline, not a signal.
        non_neutral = {k: v for k, v in counts.items() if k != "neutral"}
        top = max(non_neutral, key=lambda k: non_neutral[k]) if non_neutral else None
        windows[name] = {
            "total": total,
            "counts": counts,
            "top_non_neutral": top,
            "top_non_neutral_count": non_neutral.get(top, 0) if top else 0,
        }
    latest_ts, latest_dim = _latest_user_message()
    if latest_ts:
        snapshot["latest_user"] = {"ts": latest_ts, "dimension": latest_dim}
    # current situational states (statebar-style activity/body/sleep states)
    try:
        from mind_runtime.shadow.states import active_states

        seen: set[tuple[str, str]] = set()
        states: list[dict[str, str]] = []
        for s in active_states(STATES_DB):
            if (s[0], s[1]) in seen:
                continue
            seen.add((s[0], s[1]))
            states.append({"category": s[0], "key": s[1], "value": s[2], "valid_until": s[3]})
        snapshot["states"] = states
    except Exception:  # noqa: BLE001 - states optional in snapshot
        snapshot["states"] = []
    SNAPSHOT.parent.mkdir(parents=True, exist_ok=True)
    SNAPSHOT.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")
    return snapshot


if __name__ == "__main__":
    print(json.dumps(generate_snapshot(), ensure_ascii=False, indent=2))
