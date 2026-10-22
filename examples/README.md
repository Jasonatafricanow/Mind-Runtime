# Host commit and process restart

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

中文：在仓库根目录按上面三条命令执行。两次运行属于独立进程，第一次提交，第二次
从同一 SQLite 文件识别已处理事件，不再次进入运行链。输出中的 `payload_unverified`
表示持久提交标记不能证明重放载荷完全相同。本例使用合成输入，不调用真实模型，也不
宣称恢复全部内存 trace。请使用专用演示数据库，不要指定生产数据库。
