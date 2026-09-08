"""Learn affect trajectory from the shadow corpus.

Usage:
    python -m mind_runtime.shadow.learn [--shadow-db PATH] [--affect-db PATH]
"""

from __future__ import annotations

import argparse
from pathlib import Path

from mind_runtime.shadow.affect import affect_summary, learn_corpus
from mind_runtime.shadow.runner import shadow_db_path

DEFAULT_AFFECT_DB = str(Path.home() / ".hermes" / "profiles" / "xiyue" / "shadow_affect.db")


def main() -> None:
    parser = argparse.ArgumentParser(description="D11L shadow affect learner")
    parser.add_argument("--shadow-db", default=str(shadow_db_path()))
    parser.add_argument("--affect-db", default=DEFAULT_AFFECT_DB)
    args = parser.parse_args()

    stats = learn_corpus(args.shadow_db, args.affect_db)
    print(f"learn: stats={stats}")
    print(f"affect summary: {affect_summary(args.affect_db)}")


if __name__ == "__main__":
    main()
