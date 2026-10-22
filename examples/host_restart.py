"""Run commit and replay in separate processes against a dedicated demo database."""
import argparse
import json
import os
from datetime import UTC, datetime
from pathlib import Path

from mind_runtime.contracts import Scope, ScopeDomain
from mind_runtime.contracts.host import (
    HostCommitRequest,
    HostStatus,
    HostTurnRequest,
    HostTurnStatus,
)
from mind_runtime.host import MindRuntimeHostAdapter
from mind_runtime.pipeline.orchestrator import TurnOrchestrator
from mind_runtime.pipeline.trace import TraceRecorder
from mind_runtime.state.persistence import SqliteCommitMarkerStore, SqliteStateBackend


class UtcClock:
    def now(self) -> datetime:
        return datetime.now(UTC)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("commit", "replay"))
    parser.add_argument("--db", type=Path, required=True)
    args = parser.parse_args()
    if args.phase == "commit" and args.db.exists():
        parser.error("Use a new dedicated demo database for commit.")
    if args.phase == "replay" and not args.db.is_file():
        parser.error("Run commit first using the same database path.")
    args.db.parent.mkdir(parents=True, exist_ok=True)
    backend = SqliteStateBackend(args.db)
    markers = SqliteCommitMarkerStore(args.db)
    try:
        trace = TraceRecorder()
        orchestrator = TurnOrchestrator(
            clock=UtcClock(), trace=trace, state_backend=backend, commit_markers=markers,
        )
        host = MindRuntimeHostAdapter(orchestrator=orchestrator, trace=trace)
        # A synthetic host event, identical in both processes. Never reuse this ID
        # for distinct real interactions or replace source time with replay time.
        request = HostTurnRequest(
            interaction_id="restart-demo-1", runtime_id="demo-runtime",
            scope=Scope(domain=ScopeDomain.USER, user_id="demo-user"),
            occurred_at=datetime(2026, 1, 1, tzinfo=UTC),
            user_message="I just woke up.", channel="demo",
        )
        result = host.begin_turn(request)
        if args.phase == "commit":
            receipt = host.commit_turn(HostCommitRequest(
                turn_id=result.turn_id, interaction_id=result.interaction_id,
            ))
            if receipt.status is not HostStatus.OK:
                raise RuntimeError(f"Commit failed: {receipt.reason_codes}")
            status, reasons = "committed", receipt.reason_codes
        else:
            if result.status is not HostTurnStatus.ALREADY_PROCESSED:
                raise RuntimeError(f"Replay unexpectedly re-entered: {result.status}")
            status, reasons = result.status.value, result.reason_codes
        print(json.dumps({"pid": os.getpid(), "phase": args.phase, "status": status,
                          "interaction_id": request.interaction_id, "reasons": reasons}))
    finally:
        backend.close()
        markers.close()


if __name__ == "__main__":
    main()
