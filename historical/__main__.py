"""Offline entry point; no online imports or production cutover."""

import argparse
import json
from pathlib import Path

from mr_mem import Scope, ScopeDomain

from historical.agy_adapter import ExternalAGYAdapter
from historical.rebuild import HistoricalRebuild
from historical.source_iterator import HistoricalSourceIterator


def main():
    parser = argparse.ArgumentParser(description="Offline curated native-source MR-Mem rebuild")
    parser.add_argument("--raw-db", required=True)
    parser.add_argument("--owner", required=True)
    parser.add_argument("--namespace", required=True)
    parser.add_argument("--rebuild-root", required=True, help="fresh independent directory")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--selection-file", type=Path)
    parser.add_argument(
        "--worker-command-json", required=True, help="argv with one {output} placeholder"
    )
    args = parser.parse_args()
    if args.limit is not None and args.limit < 1:
        parser.error("--limit must be positive")
    plan = (
        json.loads(args.selection_file.read_text(encoding="utf-8")) if args.selection_file else {}
    )
    sources = HistoricalSourceIterator(
        args.raw_db,
        scope=Scope(ScopeDomain.USER, args.owner),
        namespace=args.namespace,
        user_id=args.owner,
    )

    def selection(source, _rebuild):
        selected = plan.get(source.source_ref.record_id, {})
        refs = []
        for record_id in selected.get("context_record_ids", []):
            rows = sources._query(record_id=record_id, session_id=source.source_ref.session_id)
            items = tuple(sources._source(row) for row in rows)
            if len(items) != 1:
                raise ValueError("selected context record missing or out of scope")
            refs.append(items[0].source_ref)
        return {
            "context_refs": tuple(refs),
            "activated_memory_ids": tuple(selected.get("activated_memory_ids", [])),
        }

    try:
        with HistoricalRebuild(
            args.rebuild_root,
            sources=sources,
            resume=args.resume,
            worker=ExternalAGYAdapter(json.loads(args.worker_command_json), cwd=Path.cwd()),
        ) as rebuild:
            state = rebuild.run(selection=selection, limit=args.limit)
            print(json.dumps(state, ensure_ascii=False, indent=2))
    finally:
        sources.close()


if __name__ == "__main__":
    main()
