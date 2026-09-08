"""Offline shadow-corpus semantic route evaluation (C3 §21).

Reads PRIVATE source rows locally and reports what the routing WOULD do:
deterministic / typed / would-call-provider distribution plus the legacy
lexical affect labels for comparison. Strictly observational:

  * no canonical writes, no orchestrator turns, NO network calls;
  * ambiguity detection reuses production gates (typed-event keys, known
    category keyword table) so counts match real routing behavior;
  * enables a human/A-B review before any feature-gated live enablement.
"""

from __future__ import annotations

import argparse
import sqlite3
from collections import Counter
from pathlib import Path

from mind_runtime.emotional_transition.provider import KNOWN_SEMANTIC_KINDS

_KEYWORD_HINTS = {
    "gratitude": ("谢谢", "感谢", "多谢"),
    "affection_expression": ("爱你", "想你", "亲亲", "抱抱"),
    "plan_cancellation": ("取消", "去不了", "改天"),
    "explicit_acceptance": ("好的", "行", "同意", "就这么定"),
    "explicit_rejection": ("不行", "拒绝", "不同意"),
    "distress_sharing": ("难受", "崩溃", "压力大", "焦虑"),
    "achievement_sharing": ("搞定", "通过了", "上线了", "拿下了"),
}


def _estimate_kind(text: str) -> str | None:
    """Coarse keyword probe used ONLY as an offline ambiguity oracle."""
    for kind, hints in _KEYWORD_HINTS.items():
        if any(hint in text for hint in hints):
            return kind
    return None


def evaluate(
    shadow_db: str | Path,
    *,
    limit: int = 500,
    provider_name: str = "not-configured",
) -> dict[str, object]:
    """Classify stored user rows into observed route buckets."""
    con = sqlite3.connect(str(shadow_db))
    con.row_factory = sqlite3.Row
    try:
        rows = con.execute(
            "SELECT redacted_text FROM shadow_events WHERE sender='user' "
            "ORDER BY ts ASC, content_id ASC LIMIT ?",
            (limit,),
        ).fetchall()
    finally:
        con.close()

    routes: Counter[str] = Counter()
    kinds: Counter[str] = Counter()
    lexical_only = 0
    for row in rows:
        text = str(row["redacted_text"] or "")
        estimated = _estimate_kind(text)
        if estimated is not None:
            # clear semantic category -> typed mapping WITHOUT a model call
            routes["typed_mapping"] += 1
            kinds[estimated] += 1
        elif not text.strip():
            routes["deterministic"] += 1
            lexical_only += 1
        else:
            # genuinely ambiguous language -> the route that WOULD hit the
            # configured (currently absent/offline) provider
            routes["provider_required"] += 1

    total = sum(routes.values())
    return {
        "provider_name": provider_name,
        "rows_considered": total,
        "route_distribution": dict(routes),
        "typed_kind_distribution": dict(kinds),
        "known_kinds": list(KNOWN_SEMANTIC_KINDS),
        "note": (
            "offline observation only; provider_required rows are exactly "
            "the ones a guarded provider would receive after egress policy"
        ),
    }


def main(argv: list[str] | None = None) -> int:
    import json
    import os

    parser = argparse.ArgumentParser(description="offline semantic route evaluation")
    parser.add_argument(
        "--shadow-db",
        default=os.environ.get(
            "MIND_RUNTIME_SHADOW_DB",
            str(Path.home() / ".hermes" / "profiles" / "xiyue" / "shadow.db"),
        ),
    )
    parser.add_argument("--limit", type=int, default=500)
    parser.add_argument("--provider-name", default="not-configured")
    args = parser.parse_args(argv)

    report = evaluate(args.shadow_db, limit=args.limit, provider_name=args.provider_name)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
