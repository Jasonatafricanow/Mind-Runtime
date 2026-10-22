# Host commit and process restart

[English](README.md) | [简体中文](README.zh-CN.md)

From the repository root, install the runtime and run two separate processes:

```bash
python -m pip install -e .
python examples/host_restart.py commit --db ./demo-data/host-restart.sqlite3
python examples/host_restart.py replay --db ./demo-data/host-restart.sqlite3
```

The first command prints `status: committed`; the second prints
`status: already_processed` with `no_reentry` and `payload_unverified` reasons.
Different process IDs show that the second command did not reuse the first
adapter's memory. The commit command refuses an existing database.

This uses the production host adapter, orchestrator and SQLite commit marker.
It demonstrates durable replay prevention, not a live model conversation or
restoration of every in-memory trace. A durable marker does not prove payload
equality after restart: `payload_unverified` is an intentional limit. Use a new
interaction ID for each distinct real event, retain its original source time,
and let the host explicitly commit or abort after its delivery decision.

