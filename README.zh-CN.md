# Mind Runtime

[English](README.md) | [简体中文](README.zh-CN.md)

为 Agent 提供跨回合、跨进程重启的持久状态运行时。当前实现包括 facts/state/intents/checkpoints、
运行时身份与存储隔离、受限记忆检索、回合提交/中止、重启验证、遥测和只读 Observation Window。

## 总装入口

现有组合根为 `get_mr_adapter → default_adapter → build_runtime_stack → TurnOrchestrator`。
独立 MR-Mem 的 canonical 记忆和 Line 图通过历史上下文端口进入 situation / appraisal；
检索内容不会因此变成 MR 的直接事实写入权威。

Hermes 原生接入在 MR 读取前同步来源变化，在回合提交后登记并处理新增消息。原文留在宿主，
无编译器时保留待处理状态。详见 [总装说明](docs/assembly.zh-CN.md)、
[原生宿主接线](docs/assembly-native-memory.md) 和 [Line 接口](docs/assembly-line-context.md)。

## 安装与验证

```sh
python -m pip install -e ".[dev]"
python -m pytest -q
```

宿主集成测试需要工作流固定版本的 MR-Mem，入口为 `xiyue/tests`。公开 CI 包括干净安装、
覆盖率、Ruff 与 mypy 无回归门禁。开发约束见 [AGENTS.md](AGENTS.md)，历史来源见
[PROJECT-HISTORY.md](PROJECT-HISTORY.md)。

## 完成度边界

当前工程链路允许后续填入或替换语义候选、appraisal 与记忆编译算法。固定输入及编译夹具
仅验证持久化、接线、隔离和恢复；不证明真实推理质量。已有生产就绪门禁保留。
Path B 研究、完整历史策略重建及真实宿主长期运行没有被本轮工程验收代替。

宿主负责工具执行和消息交付；MR 不扩张为规划器、工具路由器或通用 Agent 平台。
