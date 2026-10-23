# MR 与 MR-Mem 总装

[English](assembly.md)

总装复用 `get_mr_adapter → default_adapter → build_runtime_stack → TurnOrchestrator`。
不另建主流水线。宿主负责发送与交付，MR 负责投影、提交和中止，MR-Mem admission 负责语义记忆写入。

此前独立 MR-Mem 写入路径与 MR 默认读取旧 Memory 的路径分离。本次把独立库接入现有
`HistoricalContextPort`，让记忆进入 situation，再由已有 appraisal 和上下文流程消费。

配置 `MR_MEM_READ_ENABLED=true`、绝对路径 `MR_MEM_CANONICAL_DB=<MR-Mem data_dir>/memory.sqlite`
和与写入侧一致的 `MR_USER_ID`。单独启用读取不要求开启实验性 Semantic Delta 编译。
宿主代码可使用 `default_adapter(mr_mem_db=..., user_id=...)`。

总装入口初始化新的空库；已有文件只读检查，不把宿主原文数据库改造成记忆库。
独立 MR-Mem 与旧 Memory writer / retrieval provider / LCE / inspiration 配置互斥。
Hermes 接入会关闭旧 Memory writer；错误组合的旧 LCE 配置拒绝装配。

每轮重新读取，按用户 scope、生命周期、注意力抑制、known_at 和上下文预算筛选。
读取不写入原文或 canonical memory。[原生宿主接线](assembly-native-memory.md) 已在 MR 读取前
同步原文编辑/删除，在回合提交后处理新增消息；独立使用只读接口的宿主仍须调用 `invalidate_source`。
开启后库损坏应报错，不能当成“没有记忆”。

算法入口仍为 `SemanticCandidateProvider` 和
`SemanticAppraisalProducer(model=SemanticAppraisalModelPort)`。已有生产就绪门禁保留。
测试中的确定性默认组件只验证接线，不能证明认知算法已经完成。
本次没有采纳研究中的 Thread / Path A 语义算法，也没有自动合并研发分支。

仅 canonical 读取兼容 MR-Mem `0685a8a2498cc828c8d500be6f4673e53fa6dc24`；Line 图读出依赖
宿主 CI 工作流固定的配套开发提交。跨进程验证覆盖空库首轮、入库后读取、重建实例、重复交付、失效与用户隔离。
该变更遵循已有历史上下文边界和 ADR-0013，不赋予检索内容新的事实或状态写入权。

继续设置绝对路径 `MR_MEM_LINE_ROOT=<MR-Mem data_dir>/lce_tree`，即可读回已有树图的相邻推进步骤。
该路径复用 AML 的同一段只读实现，向 MR 提供 `memory.line` 历史上下文，不绕过 MR 的 scope、
known_at、生命周期和隐藏策略；最终上下文受条数和字符预算约束。
详细边界见 [Line 接入契约](assembly-line-context.md)。没有配置该目录时继续使用 canonical 读取。

Hermes 原生写入使用 `MR_MEM_NATIVE_ENABLED=true` 和 `MR_MEM_NATIVE_CONFIG`，与实验性
Semantic Delta writer 互斥。侧库只登记来源标识，不镜像宿主正文。编译器未配置时保留待处理批次，
返回 `compiler_not_configured`；重启后复用已接受的编译结果。原文变化会取消未完成的旧批次、
撤销其部分入库结果并重新登记当前输入，已完成批次中未受影响的记忆保留。
该路径完成工程接线；Path B 仍按既有设计保留为第二阶段，算法正确性没有因此被验收。
