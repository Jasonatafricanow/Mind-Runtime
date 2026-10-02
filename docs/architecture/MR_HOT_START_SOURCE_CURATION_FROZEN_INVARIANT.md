# MR Hot-Start Source Curation — Frozen Invariant

Status: FROZEN  
Authority: 用户冻结规范  
Recorded: 2026-10-03 (Asia/Shanghai)

## 1. Authority

Hot Start 不等于：

```text
历史 Raw
→ 全量重新喂给 LLM
```

Hot Start 的正式定义为：

```text
Immutable Native Raw
        ↓
Historical Source Curation
        ↓
Eligible Semantic Stream
        ↓
Historical Semantic Compilation
        ↓
Canonical Memory Rebuild / Recovery
        ↓
Derived Projections
```

Raw 数据始终保留为最终证据 authority。

Source Curation 只决定：

> 哪些 Raw Record 有资格参与认知重建，以及以什么角色参与。

不得删除、修改或重写原始历史。

## 2. Hot-Start 强制顺序

任何 MR Hot Start / historical rebuild 必须严格执行：

```text
Stage 0  Native Raw Authority
        ↓
Stage 1  Source Curation
        ↓
Stage 2  Context Assembly
        ↓
Stage 3  AGY Semantic Compilation
        ↓
Stage 4  Validator + Semantic Closure
        ↓
Stage 5  MR-Mem Canonical Admission
        ↓
Stage 6  Embedding / Point Cloud
        ↓
Stage 7  Thread / LCE Projection
```

禁止绕过 Stage 1，直接：

```text
Raw History → AGY
```

## 3. Source Curation 三态

所有历史记录必须先投影成：

```text
COMPILE
CONTEXT_ONLY
IGNORE
```

三者仅表示 Hot-Start semantic eligibility。

它们不是 Memory 生命周期，也不是事实真假判断。

## 4. COMPILE

定义：

> 该 Source Record 本身可能承载用户新增、修正、撤销或确认的 cognition，需要进入 Semantic Compilation。

默认候选：

```text
USER-authored semantic content
```

典型包括：

- 用户决策；
- 偏好；
- 约束；
- 纠正；
- 状态变化；
- 长期目标；
- 项目设计决定；
- 用户明确接受/拒绝方案；
- 对旧 cognition 的 supersession；
- 可独立成立的观点或判断；
- 计划及其后续状态变化。

COMPILE 不代表一定生成 Memory。

最终仍由：

```text
AGY
→ SemanticDelta
→ Validator
→ Closure
```

决定。

## 5. CONTEXT_ONLY

定义：

> 该记录本身不得成为用户 canonical cognition，但可能是正确解释某个 COMPILE source 所必需的上下文。

默认包括：

```text
ASSISTANT messages
```

以及部分：

```text
tool evidence
system-provided reference context
```

例如：

```text
Assistant:
A = SourceRef
B = factual pair

User:
就按 A。
```

Assistant 记录：

```text
CONTEXT_ONLY
```

User 记录：

```text
COMPILE
```

最终可以编译：

```text
用户决定采用 native SourceRef 路线。
```

禁止把：

```text
Assistant 自己提出 A
```

直接写成：

```text
用户决定 A
```

## 6. IGNORE

定义：

> 该记录属于运行、开发、执行或传输流水，对用户长期 cognition 没有独立语义资格，也不需要作为当前语义解释上下文。

以下默认 IGNORE：

```text
agent progress log
tool-call mechanics
shell command
stdout / stderr
CI output
Git fetch / checkout / diff
patch progress
test runner progress
polling
retry status
HTTP transient errors
token accounting
latency telemetry
trace events
background task state
file read/write progress
temporary execution plans
```

典型例子：

```text
正在读取 compiler.py
Ran pytest
3912 passed
Killed task-992
Retry attempt 4
Patched lines 44-72
Workflow green
```

这些可以留在 Raw/Audit 层。

不得进入 canonical semantic stream。

## 7. 开发工作记录硬规则

MR Hot Start 必须区分：

```text
Development Process
≠
Development Decision
```

例如：

```text
Agent:
修改了 semantic_closure.py
```

→ IGNORE

```text
Tool:
CI green
```

→ IGNORE

```text
User:
cohabit/context 这个边界锁死，不要再改。
```

→ COMPILE

```text
User:
94% coverage 不是架构验收标准，不要为了 coverage 堆重复测试。
```

→ COMPILE

因此：

> 开发过程流水不进入长期 cognition；用户形成的开发原则、设计决定和约束可以进入。

## 8. Agent 工作记录硬规则

Agent 自己的：

```text
我准备……
我接下来……
我先检查……
发现……
正在处理……
```

默认：

```text
IGNORE
```

Agent 的 conclusion 默认也不能直接成为用户 cognition。

只有用户后续明确：

```text
认可
修正
采用
拒绝
引用
```

时，才由相应 USER Source 产生 cognition。

## 9. Tool Result 规则

Tool Result 默认：

```text
IGNORE
```

如果它对解释当前用户表达是必要证据，则：

```text
CONTEXT_ONLY
```

Tool Result 永远不能因为“看起来很重要”直接变成用户 Memory。

例如：

```text
Tool:
测试显示 closure failure
```

不能直接写：

```text
用户认为 closure 有问题
```

只有用户表达才拥有该 commitment。

## 10. Assistant 规则

Assistant 默认：

```text
CONTEXT_ONLY
```

绝不默认：

```text
COMPILE
```

原因：

Assistant 产生的是模型输出，不是用户 commitment。

只有在用户后续 adoption 时，相关内容才能通过 USER source 被重新语义化。

## 11. 用户短回复不得按长度清洗

禁止规则：

```text
len(text) < N → IGNORE
```

例如：

```text
对
就这个
A
继续
不是
```

都可能承载强 cognition。

必须结合 CONTEXT_ONLY window 判断。

例如：

```text
Assistant:
以后是否禁用 Full-History recompilation？

User:
对。
```

该 USER Source 必须：

```text
COMPILE
```

并解析为完整 commitment。

## 12. Context Window 原则

Source Curation 后：

```text
COMPILE source
```

可以获取必要的：

```text
CONTEXT_ONLY records
+
already compiled SemanticBlocks
```

但不得重新恢复整个 transcript。

规则：

> 只提供足够完成当前 source 语义闭包的最小上下文。

## 13. Historical AGY 输出仍必须是 Delta

Hot Start 不授权 Full-History Semantic Recompilation。

对每个历史 COMPILE source：

```text
current historical source
+
necessary context
+
previous canonical state
↓
AGY
↓
current SemanticDelta
```

禁止：

```text
重述此前全部历史 SemanticBlocks
```

## 14. Raw / Semantic / Projection 三层不可混淆

必须保持：

```text
Raw
= Ultimate Evidence

SemanticBlock
= Compiled Cognition

Thread / LCE
= Derived Projection
```

Source Curation 不改变 Raw。

AGY 不修改 Raw。

Thread/LCE 不反向成为 canonical semantic authority。

## 15. Hot-Start Rebuild 默认目标

完整历史重建时优先：

```text
Native Raw
↓
fresh empty MR-Mem rebuild DB
```

而不是在旧混杂 Memory DB 上边清洗边覆盖。

旧：

- RuleBased Memory；
- 实验 SemanticBlock；
- Agent-generated records；
- legacy memory；

不得默认作为新 canonical rebuild 输入。

## 16. 时间轴

历史重跑必须保留：

```text
occurred_at
```

来源于原始事件时间。

重建行为本身不得把历史事件改写成当前发生。

`known_at` 与 recompilation/recovery 语义继续遵循现有双时间轴 authority。

## 17. Curation 优先 deterministic

首先使用机器已知 provenance：

```text
role
record_type
source_type
tool marker
agent execution marker
transport metadata
```

完成确定性分类。

禁止为了判断：

```text
tool log 是不是 tool log
```

调用 AGY。

只有无法通过 provenance 明确判断、且该判断会影响 semantic eligibility 时，才能进入更高层处理。

## 18. Hot-Start 不重演 MR Affect Runtime

Historical Semantic Rebuild：

```text
不是 Runtime Replay
```

不得因为重建 Memory 而逐条重新运行：

```text
Affect
Homeostasis
Decision
Expression
```

Historical AGY 的任务是：

```text
Semantic Compilation
```

不是重新模拟过去每一轮 Agent 心理状态。

## 19. Fail-Closed

任何无法确认 eligibility 的记录：

不得直接写 canonical memory。

优先：

```text
CONTEXT_ONLY
```

或者保留 Raw 等待后续处理。

禁止：

```text
“不确定但大概有用”
→ COMPILE → canonical
```

## 20. MR Hot-Start Invariant

最终冻结为一句：

> **Hot Start 必须先把历史 Raw 从“运行流水”压缩成“可语义编译的信息流”，再进行 Semantic Compilation；Operational history 不得因存在于 transcript 中就自动获得 cognition 资格。**

该规则属于 MR Hot-Start 基础规范。

任何新的：

- Host；
- Memory backend；
- AGY；
- historical importer；
- migration；
- restart recovery；

都必须遵守。
