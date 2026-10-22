# Mind Runtime

[English](README.md) | [简体中文](README.zh-CN.md)

为长期运行的 Agent 提供持久状态运行时。把证据准入、已提交状态和只读观察分开，让 Agent 能在重启后从存储状态恢复。

## 已实现的部分

- 持久事实、身份与运行时绑定、提交和中止边界。
- 重启恢复及确定性认证夹具。
- 只读 Observation Window。
- 记忆检索和可选 LCE 接入；进入上下文前重新校验来源。

## 安装与验证

```bash
python -m pip install -e ".[dev]"
python -m pytest -q
```

公开 CI 还包含覆盖率、Ruff 和 mypy 无回归门禁。见[实现与验证说明](docs/IMPLEMENTATION.md)、[架构依据](AGENTS.md)和[项目历史](PROJECT-HISTORY.md)。

## 当前研究位置

独立的 [MR-Mem](https://github.com/Jasonatafricanow/MR-Mem) 围绕宿主原生历史开发语义记忆与派生认知 sidecar。本说明对应本仓库已提交实现，其他仓库的新设计不会自动成为这里已实现的功能。

可运行[宿主提交及进程重启示例](examples/README.zh-CN.md)，在两个独立进程中验证持久提交标记阻止重复执行。真实影子运行验证及当前观察窗截图仍未完成；历史 D7–D11 门禁词汇保留在研究记录中。

## 权利

尚未选择项目整体的复用许可证，权利由各自权利人保留；公开可见不等于授予开源许可。见 [NOTICE.md](NOTICE.md)。
