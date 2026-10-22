# 宿主提交与进程重启

[English](README.md) | [简体中文](README.zh-CN.md)

在仓库根目录安装运行时，再执行两个独立进程：

```bash
python -m pip install -e .
python examples/host_restart.py commit --db ./demo-data/host-restart.sqlite3
python examples/host_restart.py replay --db ./demo-data/host-restart.sqlite3
```

第一次输出 `status: committed`，第二次输出 `status: already_processed`，并带有
`no_reentry` 和 `payload_unverified`。两次进程 ID 不同，说明第二次没有复用第一个
adapter 的内存。首次提交命令拒绝使用已存在的数据库。

示例使用生产宿主 adapter、orchestrator 和 SQLite 提交标记，验证重启后阻止重复执行。
它使用合成输入，不调用真实模型，也不宣称恢复全部内存 trace。
`payload_unverified` 表示提交标记不能证明重放载荷完全相同，这是已有契约的限制。
真实宿主应为每个不同事件使用新的 interaction ID、保留原始来源时间，并在决定如何
交付响应后显式提交或中止。请使用专用演示数据库，不要指定生产数据库。
