下面这版作为 `Mind Runtime V0.1.4` 的开发总纲和需求基线。后续 Agent 做架构、实现、Review，都以本文件为上位约束；需求变化必须先更新 Decision Log / ADR，再更新 Contract 与 Golden Test，最后改实现。

# Mind Runtime V0.1.4

## 产品内核开发方案 + 需求演变记录

> **D7R authority overlay (ADR-0004):**
> `docs/adr/0004-compress-cognitive-topology.md` and
> `docs/superpowers/specs/2026-08-22-d7r-compressed-runtime-and-agent-onboarding-design.md`
> are the active authorities. This overlay supersedes conflicting topology clauses in
> this V0.1.4 document. D3-D7 trust
> boundaries remain preserved; D8 production work is blocked until the D7R
> contract and Golden integration gate closes.

文档状态：`BASELINE / V0.1.4 (2026-08-18)`  
OB 源码审计基线：`P0luz/Ombre-Brain` `main@6f7335d01c43f79a82d5ec999ec3c517f6b9c8a5`，仓库 VERSION=`3.2.0`。  
目标：在 V0.1.3 已冻结的第一 Product Slice 不扩张前提下，吸收 OB 3.2.0 源码审计结果，重新定义 MR-4 Memory Kernel 的研究与开发路线。

---

> ## V0.1.4 — OB-first Memory Reconstruction 修正说明
>
> V0.1.4 **不是新的功能扩张版**。MR-0～MR-3、D0～D11、Walking Skeleton、Factual/Mind 双事务、AppraisalRouter、ActionPolicy/ExpressionGuard 等 V0.1.3 主线继续冻结。
>
> 本次只修正 Memory 方向：此前把 OB 主要视为旧 Memory / migration provider 已不符合当前主干源码。OB 3.2.0 已同时包含 companion-oriented Memory Domain、混合检索/关系发现、SurfacePolicy、派生索引 outbox、command/event/projection、replay/crash-recovery 与单写者 replication contract 等能力。因此 MR-4 改为 **OB-first reconstruction**：以 OB 为第一源码研究对象，Mem0 作为 Retrieval/Entity/Temporal differential reference，MemoraX 作为 Turn/Writeback/Provider-runtime differential reference。
>
> **强制边界：OB-first reconstruction ≠ fork/refactor OB。** Mind Runtime 不 import OB package，不继承 bucket/breath/hold/grow/feel/dream 命名，不继承 Markdown/Vault 存储格式，也不把 OB 的 Raft、microkernel、Rust shadow kernel 等实验性架构搬进第一 Product Slice。
>
> V0.1.4 新增/修正的核心原则：
>
> 1. Memory 的 authoritative truth 与 embedding/BM25/relation/ranking/context bundle 等 derived projection 分离；派生索引失败不能回滚已提交 Memory。
> 2. `surfaced / retrieved / activated / used / reinforced` 必须分开；**被动浮现不等于强化**。
> 3. Memory 在进入 Situation/Appraisal 前必须经过 `MemorySurfacePolicy` / Context Compiler；禁止 raw provider dump 直塞 Agent。
> 4. 相似度+时间可以自动发现 `same_event / continuation / related`；**不得仅凭相似度自动推断因果**。
> 5. 自动关系、检索权重和阈值必须由真实多语言语料校准，不能复制 OB 常数或拍脑袋。
> 6. Exact quote / raw evidence 属于证据与 provenance 通道，不属于普通 semantic memory；谁选择保留原话必须可追溯。
> 7. Action artifact（如 letter）不是因为“持久化”就自动属于 Memory Domain。
> 8. Event sourcing / ledger-wins 作为 MR-4 重点候选机制，不升级为整个 Mind Runtime V0.x 的强制全局架构。
> 9. MR-4 的 backend/provider 选择推迟到真实 corpus benchmark 后；暂不预设 Mem0、OB-native 或 hybrid 谁胜出。
> 10. MR-4 Research Track 可以与 D3～D11 并行做源码/benchmark/contract 研究，但不得修改第一 Product Slice 的已冻结语义，除非 ADR + Golden Test 证明必要。
>
> 第一 Product Slice 仍然强制在 D11 停止并 Shadow 验证；Memory Kernel 只有 D11 产品信号成立后才能进入正式实现。

---

# 一、产品最终定义

Mind Runtime 是一个面向 Agent 的外置心智运行时。

> **V0.x 实证范围**：首个 Product Slice 只验证 Companion Agent 场景，Kayla first、Lara second；“通用 Agent Runtime”仍是 North Star，不视为 V0.x 已验证能力。

它解决的不是单独的“记忆”“情绪”“状态”“主动消息”，而是一个更高层的问题：

> 根据当前发生的事件、时间、用户状态、Agent 内部状态、关系历史、长期记忆和人格特征，持续计算“现在是什么情境、这件事意味着什么、Agent 当前发生了什么变化、下一步什么行为合理”。

核心闭环（North Star）：

```text
Reality / Interaction
        ↓
Evidence
        ↓
Observation
        ↓
Effective State
        ↓
Situation Abstraction ← Historical Context / Memory Activation
        ↓
Appraisal Resolution
        ↓
Affective / Relationship Dynamics
        ↓
Motivation
        ↓
ActionPolicy
        ↓
Decision Context
        ↓
Agent / LLM
        ↓
ExpressionGuard
        ↓
Action / Commit
        ↓
State / Memory / Relationship / Affect
        ↓
New Reality
```

Mind Runtime 不是：

```text
Statebar + 心潮 + OB + MemoraX
```

而是：

```text
Statebar 的状态思想
+
心潮的动态状态思想
+
Memory 的时间连续性
+
MemoraX 的 Runtime 工程纪律
        ↓
重新设计
        ↓
一个统一内核
```

这些技术来源最终都不应该成为新产品的一级产品边界。

---

# 二、需求演变记录

这是最重要的一部分。

后续如果有人问：

> 为什么不直接继续改心潮？  
> 为什么不把 Semantic Resolver 放 Statebar？  
> 为什么不直接接 OB？  
> 为什么不是固定 12 维？

必须回来看这里。

---

## DECISION-001：最初目标是“心潮产品化”

最初问题：

```text
心潮能产生主动消息
有情绪数字
有记忆
有做梦
有念头
```

因此早期直觉是：

> 在心潮现有项目上继续改，把它变成完整的 AI 情感系统。

后续源码拆解发现：

```text
OB / memory       → 外部项目
letter            → 外部继承
dream content     → OB + LLM
thought content   → LLM
LLM               → API
bridge            → 外围基础设施
```

心潮真正原创集中在：

```text
12维 drive/state
时间增长
ceil / satisfy
交叉抑制
settle
thought / obsession 的一些调度
主动触发
少量作息统计
```

冻结结论：

> 心潮不作为新产品代码基座。

它是：

```text
产品思想原型
+
Affective Dynamics 参考实现
```

而不是 Mind Runtime 的架构基础。

---

## DECISION-002：OB 不属于心潮核心能力

确认：

```text
Memory / vector retrieval / bucket / breath / hold
```

属于 OB。

因此：

> “心潮拥有记忆系统”这个需求描述作废。

新产品里 Memory 必须重新作为 Mind Runtime 原生认知对象设计。

不允许出现：

```text
Mind Runtime = 心潮 + OB
```

这种架构假设。

OB 未来最多是：

```text
Memory Provider / Migration Source
```

---

## DECISION-003：Statebar 被独立出来

Statebar 最初解决的问题：

> Agent 无法稳定理解用户此刻的状态。

形成：

```text
Signal
↓
Observation
↓
Inference
↓
Transition Intent
↓
Reconciler
↓
Canonical State
```

并明确：

```text
Observation ≠ State
```

Observation 是证据。

State 是当前结论。

这是第一条重要技术 primitive。

---

## DECISION-004：Observation 与 Action/Inference 必须分离

曾经出现过简化设计：

```text
LLM
↓
直接输出 State Action
```

后来明确否决。

原因：

```text
无法解释
无法 replay
无法多源融合
模型切换后不稳定
没有稳定 evidence boundary
```

最终冻结：

```text
Evidence
↓
Observation
↓
Inference
↓
Transition
```

同时：

> Assistant 输出不是事实来源。

禁止：

```text
Assistant:
“你可能有点累”

↓ 自动写入

user.tired = true
```

这是整个 Mind Runtime 都必须继承的系统级约束。

---

## DECISION-005：Statebar 的生命周期问题暴露“状态权威”问题

源码审计发现：

Statebar 当前并不是 Lifecycle 没接入，而是：

```text
Lifecycle 只完整进入 Snapshot read path
```

导致：

```text
DB: active
Snapshot: expired
Reconciler: 仍然认为 active
```

形成状态权威分裂。

由此冻结：

> “当前状态”必须是统一计算结果，不允许各消费者自行解释 raw state。

Statebar 下一代 primitive：

```text
Raw State
↓
EffectiveStateResolver
↓
Effective State
```

Snapshot、Reconciler、Context 等只能消费 Effective State。

---

## DECISION-006：State 生命周期与对话相关性分离

例如：

```text
下午写书法
→ cancelled
```

晚上以后不应该继续提醒。

但不能变成：

```text
cancelled → expired
```

因为：

`cancelled` 回答：

> 发生了什么？

`relevant_until` 回答：

> 现在还值得提吗？

冻结：

```text
Lifecycle status
≠
Validity
≠
Context relevance
```

三个概念永远禁止重新合并。

---

## DECISION-007：Statebar 不继续向高层语义扩张

曾经考虑在 Statebar 加：

```text
Semantic State Resolver
Policy Facts
Behavior Constraint
```

进一步分析后撤销。

Statebar 最终技术边界冻结为：

```text
Observation
↓
Canonical State
↓
Effective State
```

到这里结束。

例如 Statebar 可以知道：

```text
user.sleep.phase = awake
```

但不负责判断：

```text
因此现在不应该催睡
```

后者涉及：

```text
时间
用户状态
interaction
memory
persona
policy
```

已经属于 Mind Runtime。

---

## DECISION-008：Mind Runtime 成为真正的抽象整合层

最终确定：

Mind Runtime 接收：

```text
Effective User State
Agent State
Relationship State
Interaction State
Memory
Clock
World / Tool Evidence
Persona
```

计算：

```text
Situation
↓
Appraisal
↓
Dynamics
↓
Motivation
↓
Policy
↓
Decision Context
```

这是 Mind Runtime 相对于 Statebar 的核心产品价值。

---

## DECISION-009：心潮 12 维不能成为系统 Schema

心潮：

```text
固定 12 维
+
人工 growPerHour
+
ceil
+
固定公式
```

本质是一套具体人格参数。

而不是通用架构。

因此禁止：

```python
class MindState:
    longing
    ...
    # 固定12个
```

正确设计：

```text
Affective Dimension Definition
+
Persona Profile
+
Runtime Value
+
Dynamics Policy
```

人格决定：

```text
基础属性
成长倾向
敏感度
恢复速度
耦合方式
```

运行时决定：

```text
当前值
```

类似游戏：

```text
职业基础属性
+
成长系数
+
当前 Buff
+
环境
+
事件
=
当前属性
```

---

## DECISION-010：Persona ≠ Current State

必须严格拆分：

```text
Trait
```

和：

```text
State
```

例如：

```text
Persona:
attachment_sensitivity = high
recovery_rate = slow
```

不代表：

```text
current_attachment = high
current_anxiety = high
```

人格只决定：

> 在什么情况下，这个人容易如何变化。

不是决定：

> 她现在必须是什么心情。

---

## DECISION-011：事件不能直接改情绪

禁止退化成：

```python
if user_cancelled:
    disappointment += 0.2
```

正式模型：

```text
Observation
+
Current State
+
Memory
+
Relationship
+
Persona
+
Situation
        ↓
Appraisal
        ↓
Affective Transition
```

同一句：

> “今晚不来了。”

不同 Persona、不同关系背景、不同历史，应该得到不同 Appraisal。

然后才产生不同 affect transition。

---

## DECISION-012：MemoraX 不是第五个模块

早期容易形成：

```text
Statebar
Memory
心潮
MemoraX Runtime
```

这种模块拼装。

正式撤销。

MemoraX 的价值横向融入整个内核：

```text
Scope
Authority
Interaction Coordinator
Idempotency
Writeback
Reconcile
Trace
Replay
Fail Closed
```

因此未来不应该有一个庞大的：

```text
memorax/
```

业务子系统。

而应该看到它的原则分散在：

```text
interaction/
scope/
storage/
commit/
memory/
trace/
```

---

## DECISION-013：Mind Runtime 先做模块化单体，不做微服务拼装

当前 Kayla：

```text
gateway
心潮
OB
statebar
caddy
bridge
```

多个端口、进程、语言和健康状态。

Mind Runtime V0.x 禁止重演。

首版目标：

```text
1 runtime
1 authoritative persistence domain
1 public API/SDK
```

内部：

```text
state
memory
affect
semantics
policy
trace
```

是代码模块，不是独立服务。

Gateway、LLM、Embedding 可以作为外部 provider。

---

## DECISION-014：V0.x 只有一条 canonical pipeline

为避免不同实现者对 Product Slice 产生不同理解，V0.x 唯一 authoritative pipeline 冻结为：

```text
Interaction
↓
Evidence
↓
Observation
↓
Effective State
↓
Situation
↓
Appraisal Resolution
↓
Affective Dynamics
↓
Motivation
↓
ActionPolicy
↓
Decision Context
↓
Agent / LLM
↓
ExpressionGuard
↓
Commit
```

`Appraisal Resolution` 包含 deterministic、typed semantic mapping 和必要时的 LLM semantic appraisal；它**不等于一次 LLM 调用**。

---

## DECISION-015：SemanticAppraisal 与 ResolvedAppraisal 分离

LLM 最多负责回答：

> 这件事在语义上可能意味着什么？

因此定义：

```text
SemanticAppraisal {
    meanings[]
    valence
    relationship_relevance
    confidence
    evidence_refs[]
}
```

Runtime 再结合 Persona / Relationship / Historical Context / Situation 计算：

```text
ResolvedAppraisal {
    semantic_signal
    affective_impulses[]
    motivation_signals[]
    recurrence_modifier
    relationship_modifier
    confidence
    evidence_refs[]
}
```

冻结：

> LLM 负责解释意义，Runtime 负责计算后果。

---

## DECISION-016：Projected State ≠ Canonical State

`begin_turn()` 必须允许本轮新 Evidence 立即影响当前 Decision Context，但不能把所有推导出的心理变化直接写成最终状态。

正式引入：

```text
TransitionIntent
TurnProjection
ProjectedMindState
```

规则：

- Evidence / Observation 是已发生事实，可先持久化。
- **Evidence-backed factual transition**（典型为 user/world state）在通过 Reconciler/Authority 后可以在 ingest phase 提交；它不依赖 Agent 是否成功回复。
- Current-turn overlay 可在 factual transition 尚未落库前立即影响 Effective State / Situation。
- **Derived mind transition**（典型为 agent affect / relationship）必须先进入 Projection。
- `commit_turn()` 才提升 `commit_phase = turn_commit` 的投影变化。
- `TransitionIntent.commit_phase` 至少区分 `ingest | turn_commit`。
- turn 失败时必须可由持久化 Evidence/Observation replay/reconcile，不能靠内存保住半轮状态。

---

## DECISION-017：ActionPolicy ≠ ExpressionGuard

ActionPolicy 回答：

> 当前行为是否允许执行？

例如：cooldown、正在对话不插嘴、图片预算。

ExpressionGuard 回答：

> 已生成的表达是否真实、合规、不过度重复？

例如：固定开头去重、前 8 字重复、凌晨不能说晚霞。

两者不允许重新合并。

---

## DECISION-018：MR-2 只读历史上下文，MR-4 才拥有 Memory Engine

为了避免第一版工程量膨胀，MR-2 只能消费：

```text
HistoricalContextPort → HistoricalContextBundle
```

来源可以是 OB、旧记忆库、静态 fixture 或本地只读 adapter。V0.1.4 将旧名 `ExternalHistoricalContext` 废弃为兼容术语；核心 Contract 使用 provider-neutral `HistoricalContext*`。

MR-2 禁止实现：

```text
MemoryCandidate
Memory commit
consolidation
reinforcement
supersession
writeback lifecycle
```

这些统一归 MR-4。

---

## DECISION-019：Statebar 与 Mind Runtime 是双轨，不是迁移依赖链

Track A：`statebar-mcp`

```text
继续修 Lifecycle / Effective State / transaction / fail-closed
继续承担状态 primitive 的技术验证
不再扩成 Mind Runtime
```

Track B：`mind-runtime`

```text
重新定义并实现已验证 contract
不 import statebar package
不继承 statebar schema
不以 statebar P0 全部完成作为开工前置条件
```

冻结：

> Statebar 提供验证结论和 Golden Tests，Mind Runtime 不继承其产品边界。

---

## DECISION-020：Appraisal LLM 调用率只做可观测指标

禁止为了追求漂亮数字而把真实语义歧义硬编码成规则。

冻结：

```text
有 deterministic 结论 → 禁止调用 LLM
有可靠 typed semantic event → 参数化 appraisal
存在真实语义歧义 → 允许调用 Semantic Appraiser
```

必须记录：

```text
appraisal_path = deterministic | typed_mapping | llm
latency
cost
confidence
fallback_reason
```

真实 LLM 调用比例由运行数据决定。

---

## DECISION-021：Walking Skeleton 必须早于真实业务实现

V0.1.2 的 D0→D11 仍按横向层级组织，完整产品信号直到 D11 才出现，风险过高。

冻结：D2 Golden Harness 之后必须增加 `D2S — Vertical Walking Skeleton`。所有业务模块先用 typed stub 串通：

```text
begin_turn
→ ingest Evidence / Observation
→ EffectiveState stub
→ Situation stub
→ Appraisal stub
→ Dynamics stub
→ Motivation stub
→ ActionPolicy stub
→ DecisionContext
→ Fake Agent
→ ExpressionGuard stub
→ commit_turn / abort_turn
```

D2S 只验证接口、事务边界、Trace 和 read-your-writes，不验证业务算法。D2S 未通过，不得启动 D3 正式实现。

---

## DECISION-022：MR / D / W 三级执行模型

从 V0.1.3 起：

```text
MR = Architecture Milestone     # 架构里程碑
D  = Delivery Gate / Epic       # 一组能力的交付门
W  = Work Package               # 真正派给开发 Agent 的最小任务
```

D4、D8 等不再作为单次 Agent 工单。每个 W 必须有独立目标、允许修改范围、测试门禁和回传结果。默认要求单个 W 可在一个短开发循环中形成可观察产出；如果仍过大，执行 Agent 必须继续拆分，但不得改变 D-level Contract。

---

## DECISION-023：允许 Prework，不允许提前实现

为避免顺序 Gate 造成人力空转，建立两条 Lane：

```text
Implementation Lane：仅实现当前已解锁 W
Prework Lane：可提前写设计、truth table、fixture、规则 inventory、伪代码、benchmark 数据集
```

Prework 产物不得在前置 Contract merge 前变成生产实现，不得私自定义跨阶段 API。

---

## DECISION-024：Kayla 旧规则迁移必须先做 Legacy Contract Map

迁移不再允许写成“把 Kayla 规则迁过来”。D0 开始建立：

```text
KaylaLegacyRule {
    rule_id
    source_file_or_prompt
    source_location
    legacy_behavior
    edge_cases
    target_domain
    target_contract
    decision: preserve | generalize | change | drop
    golden_case
    shadow_metric
}
```

D9/D10 不得实现任何未进入该映射表的 legacy rule；D11 Shadow 比较以此表为兼容基准。

---

## DECISION-025：AppraisalRouter 显式拥有路由权

`ambiguous only → LLM` 不能依赖隐含 if。正式定义：

```text
AppraisalRouteDecision {
    path: deterministic | typed_mapping | llm
    ambiguity_score?
    confidence
    reason_codes[]
}
```

`AmbiguityAssessment` 可由规则、typed parser confidence、上下文冲突等信号构成，但 V0.x 不把一个未经验证的小模型设为中央路由器。

D11 必须记录 route、score、reason、human override。没有人工标注集前，不设 `ambiguous_accuracy` 硬 KPI；Shadow 后再建立 precision/recall 指标。

---

## DECISION-026：Replication 先冻结协议，不提前建死表

MR-0 必须冻结：

```text
ReplicationEnvelope
ReplicationPort
Ownership rules
Idempotency semantics
```

MR-1 只需要 `NullReplicationAdapter / InMemoryReplicationHarness` 验证 Scope/Authority/Ownership。

`replication_outbox / replication_inbox` 的物理 DDL、迁移和 transport 统一推迟到 MR-5。

---

## DECISION-027：Shadow 必须自动语义 Diff

D11 Phase A 不允许依靠人工扫 Trace。正式要求 `ShadowDiffReporter`，至少比较：

```text
EffectiveStateDiff
SituationDiff
BehaviorDecisionDiff
ExpressionConstraintDiff
AffectDirection/BandDiff
```

不要求复刻旧 schema 或旧心潮数值；比较的是语义与行为。必须支持 sampling、redaction、trace TTL。

---

## DECISION-028：Factual Plane 与 Mind Plane 分离

状态写入按因果来源分为两类：

```text
Factual Plane:
  user / world / interaction 的已验证事实
  → ingest transaction 可提交

Mind Plane:
  agent affect / relationship interpretation / motivation 等派生认知
  → TurnProjection
  → turn_commit 才成为 Canonical
```

例如用户明确说“我饿了”：`user.hunger=hungry` 在 Evidence/Observation 校验后可 ingest commit；Agent 因此产生的 `care_desire +0.08` 只能进入 Projection。

`current-turn factual overlay` 只是 ingest 完成前的 read-your-writes 视图，不是第三类 State。

---

## DECISION-029：外部 Action Side Effect 也必须 candidate/receipt/reconcile

TurnProjection 不能只解决数据库状态，还要覆盖“消息已经发出但 commit 前崩溃”的情况。D5 正式增加：

```text
TurnCheckpoint {
    interaction_id
    stage
    base_state_version
    projection_digest_or_ref
    action_id?
    delivery_status
    updated_at
}

ActionReceipt / DeliveryReceipt
```

恢复规则：

```text
未 dispatch                  → abort projection
已 dispatch + receipt         → reconcile + finish commit
dispatch unknown              → 按 idempotency/action receipt 查询后 reconcile
```

不得因为重启而静默丢失已经发生的外部行为。

---

## DECISION-030：Historical Provider 只返回模式事实，不拥有 recurrence 业务规则

正式定义：

```text
PatternQuery {
    signature
    scope
    time_window
    filters
}

PatternMatchSummary {
    match_count
    first_seen_at
    last_seen_at
    matched_refs[]
    confidence
}
```

Provider 负责查询；`match_count > N` 如何转化为 recurrence modifier / relationship threat 属于 Mind Runtime Domain，不得下沉到 OB/Memory Adapter。

---

## DECISION-031：V0.x 验证 Companion Agent，不提前宣称通用 Agent 已验证

North Star 保持“面向 Agent 的外置心智运行时”，但 V0.x 实证范围收缩：

```text
Primary validation:   Kayla companion agent
Secondary validation: Lara companion agent
溪月:                 Shared User State Consumer（当前）
```

溪月不因为出现在 Scope Matrix 就自动获得 affect / relationship / photo_share_desire 等模型。未来非陪伴 Agent 进入完整 pipeline 必须 ADR + 新 Golden Scenario。

---

## DECISION-032：Golden Tests 补双事务正向/负向边界，并加入最低数据治理

新增：

```text
G13b Factual Commit Survives Cognitive Abort
G16b Genuine Ambiguity Must Escalate
```

并冻结最低数据治理 Contract：

```text
DataSensitivity = public | personal | relationship_sensitive | secret
RetentionClass
RedactionPolicy
```

Shadow 前必须满足：secret 不进入普通日志、PII/relationship-sensitive trace 可 redaction、trace retention 可配置、跨 runtime transport（MR-5）必须加密。V0.x 不因此提前建设完整 KMS。

---

## DECISION-033：OB 3.2.0 从“迁移来源”重分类为 MR-4 第一源码参考

源码审计确认，当前 OB 已不只是旧式 bucket/vector memory：其主干同时存在 memory surfacing policy、混合 retrieval、自动 relation、embedding outbox、command/event/projection、replay/recovery 与 replication contract。

冻结：

```text
MR-4 Primary Source Reference = OB 3.2.x
Retrieval Differential Reference = Mem0
Runtime/Writeback Differential Reference = MemoraX
```

但：

```text
OB source
→ primitive extraction
→ contract evaluation
→ Mind Runtime reimplementation
```

禁止 `fork OB → 塞入 State/Affect → 改名 Mind Runtime`。

---

## DECISION-034：Memory Truth 与 Derived Projection 永久分离

OB 的 embedding outbox 明确把 memory bucket 作为真源，而 embedding 仅是可重试派生索引。Mind Runtime 吸收原则但不复制 Markdown 格式。

冻结：

```text
Canonical Memory Truth
├─ committed semantic record
├─ EvidenceRefs / provenance
└─ canonical lifecycle metadata

Derived Projections（可删除重建）
├─ embedding
├─ lexical/BM25 index
├─ entity/relation suggestions
├─ retrieval score cache
└─ compiled context bundle
```

派生服务失败不能让 canonical memory write 失败；rebuild 必须可验证。

---

## DECISION-035：Memory Surfacing ≠ Memory Reinforcement

OB 主动浮现路径刻意不自动 touch，否则系统会因为“自己想起”而无限强化同一记忆。

Mind Runtime 冻结事件语义：

```text
MemoryRetrieved   = 被查询命中
MemorySurfaced    = 被允许进入候选上下文
MemoryActivated   = 进入本轮认知上下文
MemoryUsed        = 实际参与 Appraisal/Decision
MemoryReinforced  = 满足 reinforcement policy 后改变长期权重
```

前四者均不得自动等价于 `Reinforced`。

---

## DECISION-036：Memory Read Path 必须先过 Surface Policy

Memory backend 返回候选不代表它有本轮认知权。

冻结：

```text
Provider Candidates
→ Scope/Authority gate
→ MemorySurfacePolicy
→ Budget/Ranking
→ HistoricalContextCompiler
→ HistoricalContextBundle
→ Situation/Appraisal
```

`dont_surface / private / archived / incompatible scope / budget overflow` 等规则属于 Runtime read policy，不下沉给 Provider 自由决定。

---

## DECISION-037：自动关系只发现“关联”，不猜“因果”

OB 3.2.0 使用向量相似度 + 时间窗自动建立 `same_event / continuation_of / related_to`，并明确禁止自动建立 `caused_by / causes`。

Mind Runtime 冻结：

```text
non_causal relation
→ 可由 deterministic / vector heuristic 自动建议

causal relation
→ 需要明确 Evidence、semantic rationale 或人工/高置信推断
→ 不允许 similarity-only inference
```

所有 auto relation 必须携带 `auto_discovered + score + algorithm_version`，可以整体重建或撤销。

---

## DECISION-038：Memory 阈值必须经过真实 Corpus Calibration

OB 3.2.0 的 relation threshold 是在 917 条真实记忆上重新扫描后上调，以避免大量桶撞上关系上限；这证明固定常数不能从参考项目直接复制。

MR-4 在确定 retrieval/relation 参数前必须建立真实 benchmark，至少覆盖：

```text
Chinese conversational memory
Portuguese conversational memory
English / mixed-language memory
person / place / date exact recall
current-vs-past temporal query
relationship event recurrence
false-positive spontaneous surfacing
relation over-linking
```

---

## DECISION-039：OB feel 只作为 Affective Residue 研究原型，不直接复制为 Memory Type

OB `feel` 把 Agent 对事件的第一人称感受作为独立记录，并让源记忆进入 digested 状态。这个思路值得研究，但不能直接把 `type=feel` 搬进 Kernel。

MR-4R 需要验证更通用的：

```text
MemoryReflection / AffectiveResidue
source_memory_refs[]
appraisal_snapshot_ref
agent_scope
created_at
```

它是“事件经过 Agent 处理后留下的长期解释/感受”，不等同于原事件，也不能修改用户事实。

---

## DECISION-040：Verbatim Evidence 与 Semantic Memory 分离

精确原话必须保留“谁决定保留、从哪段 Evidence 选出、是否允许检索”的 provenance。

冻结原则：

```text
Evidence / VerbatimQuote
≠ Semantic Memory
```

MR-4 不复制完整 transcript 到每条 memory；普通 semantic retrieval 默认不把全部原文证据当第二套检索面。

---

## DECISION-041：持久化的 Action Artifact 不自动属于 Memory

OB 3.2 把 letter 从主 memory connector 分离，理由是它有收件人、时间锁和面向未来的行为语义。

Mind Runtime 冻结：

> “会被保存”不是 Memory Domain 的充分条件。

`message draft / letter / reminder / scheduled action / tool receipt` 优先属于 Action/Artifact/Task Domain；只有其事实或后果需要长期认知时才生成 MemoryCandidate。

---

## DECISION-042：Event Sourcing 只在有收益的 Domain 采用，不全局教条化

OB 已提供 `MemoryCommand → EventSourcedEnvelope → ProjectionMutation` 与 ledger replay/recovery contract。

Mind Runtime 认可其“canonical event + rebuildable projection”价值，但 V0.x 第一 Product Slice 继续使用当前 transaction + trace/replay 设计。

MR-4 可选择：

```text
MemoryCommand
→ MemoryEvent ledger
→ Canonical Memory Projection
→ Index Projection Jobs
```

是否正式采用由 D12 Memory Kernel Contract 决定，不得因为 OB 有 event sourcing 就强迫 State/Affect 全部改写。

---

## DECISION-043：MR-4 Provider/Engine 选择推迟到 Benchmark 后

正式撤销任何“默认 Mem0 作为底层”或“默认 OB-native”假设。

候选：

```text
A. Native Memory Engine（吸收 OB primitives）
B. Mem0 provider + Mind Runtime authority/surface layer
C. Hybrid：native canonical domain + external retrieval provider
```

D17 以真实语料、成本、可重建性、scope、延迟和 failure mode 决定。

---

## DECISION-044：MR-4 Research Track 可并行，Implementation 仍受 D11 Stop Gate

从 D2S 后允许 `R4-*` 只读研究：源码审计、benchmark corpus、truth table、RFC、provider spike。

禁止：

```text
R4 prework
→ 偷偷 merge Native Memory write path
→ 修改 D3~D11 canonical pipeline
```

任何影响第一 Product Slice Contract 的发现必须先 ADR。

---

## DECISION-045：Single Writer / Rebuildable Projection 优先于 Full Consensus

OB replication contract 本身也要求 single canonical writer，并对“无必要理由的 full consensus”给出违规。

这与 Mind Runtime 已冻结 Ownership 方向一致：

```text
canonical private domain → single writer owner
shared observations      → authoritative event replication
read side                → rebuildable/multi-reader projections
```

MR-5 不因为 OB 出现 Raft 目录就提前引入全分布式共识。

---

## DECISION-046：Source Evidence 是 Memory 的证据锚点，不是第二套 Cognition

OB 的 source-evidence ADR 明确把原文证据定义成不可变、内容寻址、受门禁读取，而且不参与普通 surfacing、semantic indexing 或 decay。

Mind Runtime 已经拥有更上位的 `Evidence` Domain，因此 MR-4 不另造一套 OB source store 语义；Memory 通过 `evidence_refs[]` 绑定权威来源，必要时由 Evidence Store 提供受权限/预算控制的原文片段。

---

# 三、技术遗产如何进入新产品

V0.1.4 把 Memory 相关来源重新拆开，不再把 `OB / Memory` 合并成一行：

|来源|最值得毕业的 primitive / discipline|明确不继承|
|---|---|---|
|Statebar|Observation、Transition、Lifecycle、Effective State、semantic time、replay|UserStateService 产品边界、Snapshot-centric、MCP-centric|
|心潮|持续 Affect、time evolution、baseline、sensitivity、coupling、drive→motivation|固定 12 维、顾川/Kayla 写死参数、OB glue、prompt glue|
|**OB 3.2.x**|Companion Memory Domain、SurfacePolicy、decay/salience、feel/reflective residue 思路、hybrid retrieval、relation discovery、authoritative-vs-derived、embedding outbox、selected event/replay/recovery contracts|`bucket/breath/hold/grow/feel/dream` API 命名、Markdown/Vault 作为产品前提、MCP/Claude 绑定、Raft/microkernel/Rust shadow 全量搬运|
|**Mem0**|通用 extraction、entity linking、hybrid retrieval、temporal retrieval、provider 产品化与 benchmark 方法|其 Scope/Authority 假设、每轮提取即权威写入的使用方式|
|**MemoraX**|Turn Coordinator、authoritative turn materialization、candidate/commit、redaction、idempotency、writeback receipt/reconcile、多 client adapter discipline|独立 MemoraX 产品边界、后端 API 语义|

MR-4 的研究主次：

```text
OB        = Primary source reference
Mem0      = Retrieval / Entity / Temporal differential reference
MemoraX   = Turn / Writeback / Provider-runtime differential reference
```

核心原则继续冻结：

> **只迁移 primitive，不迁移旧产品边界；只吸收被源码/测试/真实数据证明有价值的机制，不以“参考项目已经做了”为充分理由。**

---

# 四、Mind Runtime 核心领域模型

## 4.1 Interaction

每次交互都是一等对象：

```text
Interaction {
    interaction_id

    scope

    channel
    session_id
    turn_id

    started_at
    committed_at

    status
}
```

它是所有因果关系的主索引。

---

# 4.2 Scope

至少支持：

```text
user
agent
relationship
interaction
world
```

结构：

```text
Scope {
    user_id?
    agent_id?
    persona_id?
    relationship_id?
    world_id?
}
```

> **V0.1.2 冻结**：Scope 只回答“这是谁的数据”。
> 必须同时设计 **Authority / Ownership / Replication**——回答"谁拥有写权限、多个 runtime 怎么看到同一事实、两处同时修改怎么办"。
>
> **Scope Matrix（强制契约）**：
>
> | 数据 | Kayla | Lara | 溪月 |
> |---|--:|--:|--:|
> | 用户当前状态 | 共享 | 共享 | 只读/按权限消费 |
> | 用户长期稳定事实 | 共享 | 共享 | 只读/按权限消费 |
> | Kayla 内部情绪 | 私有 | 禁止 | 禁止 |
> | Lara 内部情绪 | 禁止 | 私有 | 禁止 |
> | Kayla-用户关系 | 私有 | 禁止 | 禁止 |
> | Lara-用户关系 | 禁止 | 私有 | 禁止 |
> | Agent 私人记忆 | 按 scope | 按 scope | 当前不进入完整 affective pipeline |
> | 世界事实 | 可共享 | 可共享 | 按权限消费 |
>
> 同一用户可以有 Kayla / Lara / 溪月多个 Agent：用户稳定事实可共享，但 Agent 内部情绪与关系域**绝不跨 scope 泄漏**。

例：

```text
user:jiasen
agent:kayla
relationship:jiasen:kayla
```

为什么必须现在做：

同一个用户以后可能有：

```text
Kayla
Lara
溪月
```

用户事实可以部分共享。

但：

```text
Kayla 对用户的依恋
```

绝不能泄漏到 Lara。

---

# 4.3 Evidence

事实来源：

```text
Evidence {
    id
    source_type
    source_id
    authority_level
    occurred_at
    received_at
    payload
}
```

允许成为事实源的包括：

```text
user message
tool result
device signal
world event
persistent transcript
validated system transition
```

Assistant 生成内容默认：

```text
authority = none
```

不能自动污染 State 或 Memory。

---

# 4.4 Observation

Observation 是 Evidence 的语义化结果：

```text
Observation {
    id
    interaction_id
    scope

    type
    key
    value

    confidence

    observed_at
    evidence_refs[]
}
```

必须保持不可变。

如果后来判断之前解释错了：

不修改 Observation。

产生：

```text
new Observation
+
新的 Transition
```

---

# 4.5 State Definition

这里开始替代心潮写死属性的问题。

```text
StateDimensionDefinition {
    key

    domain:
      user | agent | relationship | interaction

    value_type:
      categorical | boolean | scalar | structured

    dynamics_policy

    default_validity_policy?

    bounds?
}
```

例如：

```text
user.sleep.phase
agent.affect.longing
relationship.trust
interaction.engagement
```

---

# 4.6 Persona Dimension Profile

人格对某个维度的先天/长期参数：

```text
PersonaDimensionProfile {
    dimension

    baseline
    initial_value

    sensitivity
    recovery_rate

    ceiling
    floor

    growth_profile
    coupling_profile
}
```

这就是“职业基础属性 + 成长属性”。

Persona 不存 current。

---

# 4.7 Runtime State

```text
State {
    state_id
    scope
    dimension

    value
    status

    valid_from
    valid_until
    relevant_until

    last_observed_at

    evidence_refs[]
    transition_refs[]

    updated_at
}
```

# 4.8 TransitionIntent / TurnProjection

Mind Runtime 必须区分“本轮计算结果”和“已经成为 Canonical State 的结果”。

```text
TransitionIntent {
    intent_id
    interaction_id
    scope
    target_dimension

    before
    proposed_after

    cause_refs[]
    policy
    confidence
    commit_phase
}
```

```text
TurnProjection {
    interaction_id

    effective_state_before
    observations[]
    situation
    semantic_appraisal?
    resolved_appraisal?

    transition_intents[]
    projected_mind_state

    motivations[]
    action_permissions[]

    created_at
}
```

冻结：

```text
TurnProjection ≠ Canonical State
TransitionIntent ≠ Committed Transition
```

Evidence / Observation 作为已发生事实可以持久化；推导型 Agent/Relationship Mind Transition 先进入 Projection，由 `commit_turn()` 提升。

---

## 4.8 Factual Plane / Mind Plane / Commit Phase

```text
TransitionIntent.commit_phase = ingest | turn_commit
```

- `ingest`：仅用于通过 Authority/Reconciler 验证的外部事实性变化。
- `turn_commit`：用于 Appraisal/Dynamics 派生出的 Agent/Relationship/Motivation 等心智变化。
- `factual_overlay` 只是本 turn 的 read-your-writes projection，不拥有独立 persistence 语义。

## 4.9 TurnCheckpoint 与 ActionReceipt

`TurnCheckpoint` 用来恢复 `processing / dispatching / awaiting_commit` 等中间阶段；`ActionReceipt` 描述外部 side effect 是否实际发生。二者都是恢复/对账基础设施，不是新的业务状态。

## 4.10 PatternQuery / PatternMatchSummary

Historical Provider 只实现查询事实。任何 recurrence 阈值、人格敏感度和威胁解释都在 ResolvedAppraisal / Dynamics 域完成。

## 4.11 DataSensitivity / Retention / Redaction

所有 Evidence、Observation、Memory/History、Trace、Relationship/Affect 字段都可携带数据敏感度元信息；Trace renderer 和 Shadow reporter 必须遵循 RedactionPolicy。


# 五、Dynamics Policy

这是从心潮真正毕业出来的核心技术。

Mind Runtime 不提供一个万能公式。

提供一组 Dynamics Policy。

首批至少需要：

### categorical_lifecycle

用于：

```text
awake
sleeping
plan
activity
```

变化：

```text
A → B
```

---

### ttl_lifecycle

用于：

```text
headache active
temporary discomfort
temporary context
```

---

### continuous_return_to_baseline

主要用于 Agent affect：

```text
longing
irritation
anxiety
excitement
```

基本思想：

```text
当前值
↓
随时间向 Persona baseline 回归
+
event/appraisal impulse
+
memory resonance
+
relationship modifier
+
cross dimension effects
```

而不是简单：

```text
每小时固定 +0.105
```

---

### accumulator

用于慢变量：

```text
trust
resentment
closeness
confidence
```

通常：

```text
变化慢
恢复慢
单事件影响小
重复 pattern 影响大
```

---

### event_only

用于：

```text
relationship status
identity
explicit commitment
```

不能因为时间自己变化。

---

# 六、Effective State

必须从 Statebar 的教训里直接冻结一条硬规则：

> Runtime 业务代码禁止直接消费 Raw State。

统一：

```text
Raw State
+
Clock
+
Lifecycle Policy
        ↓
EffectiveStateResolver
        ↓
Effective State
```

`EffectiveStateResolver` 负责：

```text
TTL
状态合法性
supersession
有效性
reaffirm refresh
```

终态：

```text
resolved
completed
cancelled
superseded
```

永远不能被时间改写成 expired。

Context relevance 单独处理。

---

# 七、Semantic Abstraction

这是 Mind Runtime 的第一个真正高阶层。

输入：

```text
Effective State
Current Observation
Clock
Interaction
Memory Activation
World Context
```

输出：

```text
SituationModel
```

例如原始输入：

```text
time = 02:30
user.sleep.phase = awake
last awake observation = 30 min ago
interaction.current_turn = active
```

不是直接塞 Prompt。

形成：

```text
Situation {
    user_activity = awake_and_engaged
    conversation_mode = active
    schedule_norm_relevance = low
}
```

注意：

Situation 不是持久化事实。

它是：

> 这个时间点对当前事实组合的解释。

---

# 八、抽象层必须采用“确定性 + 模型语义”混合架构

不能什么都交 LLM。Appraisal 必须是分层 resolver，而不是一个“每轮调用一次模型”的 service。

## Level 1：Deterministic Derivation

能算的必须代码算：

```text
daypart
cooldown
elapsed_time
daily_budget
conversation_active
photo_count
TTL
recently_awake
```

例如：

```text
last proactive = 20 min ago
cooldown = 30 min
→ proactive_cooldown = blocked
```

不需要模型。

## Level 2：Typed Semantic Interpretation

例如：

```text
“今晚算了，我不去了”
```

解释成：

```text
plan.cancelled(target=X)
```

LLM 可以参与，但必须输出 typed semantic object。不能直接修改数据库，也不能直接决定 affect 数值。

## Level 3：Semantic Appraisal

仅在语义存在真实歧义时，模型回答：

> 这件事在当前上下文里可能意味着什么？

```text
SemanticAppraisal {
    meanings[]
    valence
    relationship_relevance
    confidence
    evidence_refs[]
}
```

例如 LLM 可以输出：

```text
meaning = possible_rejection
valence = negative
relationship_relevance = moderate
confidence = 0.71
```

禁止：

```text
anxiety = 0.78
longing = 0.91
```

## Level 4：Resolved Appraisal

Runtime 结合：

```text
SemanticAppraisal?
+ Persona
+ Relationship State
+ Situation
+ HistoricalContextBundle / Memory Activation
```

计算：

```text
ResolvedAppraisal {
    semantic_signal
    affective_impulses[]
    motivation_signals[]
    recurrence_modifier
    relationship_modifier
    confidence
    evidence_refs[]
}
```

然后 Dynamics Engine 决定实际 State 数值变化。

## AppraisalRouter

`AppraisalRouter` 必须显式输出：

```text
AppraisalRouteDecision {
    path: deterministic | typed_mapping | llm
    ambiguity_score?
    confidence
    reason_codes[]
}
```

路由原则：明确可算 → deterministic；可靠 typed semantic event → typed_mapping；只有 genuine ambiguity 才升级 LLM。

必须记录：

```text
appraisal_path
ambiguity_score
route_reason
latency
cost
confidence
human_override?
```

不设“90% 零 LLM”硬指标；目标是**可算的不交模型，真正歧义才交模型**。

---

# 九、Memory Kernel 的最终位置（V0.1.4）

Memory 不是 State，也不是 Prompt RAG。

```text
State
= 现在是什么

Memory
= 过去发生过什么、形成了什么长期认知，以及这些历史在什么条件下重新获得认知权
```

## 9.1 Canonical Memory 与派生层

North Star 不再把一个 `MemoryRecord` 同时当存储、索引、召回结果和关系图节点。

```text
Canonical Memory Truth
├─ MemoryRecord
├─ EvidenceRefs / provenance
├─ lifecycle / processing metadata
└─ manually/semantically confirmed relations

Derived / Rebuildable Projection
├─ vector embedding
├─ lexical/BM25 index
├─ auto relation candidates
├─ retrieval score/cache
└─ context compilation cache
```

建议的基础对象：

```text
MemoryRecord {
    id
    scope
    memory_kind
    proposition

    evidence_refs[]
    provenance

    confidence
    salience

    status
    created_at
    updated_at

    last_used_at?
    last_reinforced_at?
}
```

注意：`last_used_at` 与 `last_reinforced_at` 必须可不同。

## 9.2 Memory Admission

正式链路仍遵循 candidate/commit：

```text
Evidence / Observation / authoritative turn material
↓
MemoryCandidate
↓
Admission Policy
↓
validate / dedupe / link / reject / defer
↓
Committed Memory
```

冻结：

```text
MemoryCandidate ≠ Committed Memory
Memory ≠ State
Memory Relation ≠ State Transition
```

LLM 可以提出 MemoryCandidate，但不能直接拥有 commit 权限。

## 9.3 Memory Read 生命周期

V0.1.4 新增最重要的读侧区分：

```text
Retrieved
→ Surfaced
→ Activated
→ Used
→ Reinforced（可选）
```

定义：

- `Retrieved`：backend 找到候选。
- `Surfaced`：通过 Scope/SurfacePolicy/预算，允许进入候选上下文。
- `Activated`：本轮确实进入 HistoricalContextBundle。
- `Used`：Appraisal / Situation / Decision trace 表明它实际参与推导。
- `Reinforced`：长期权重/显著性被明确策略更新。

**前四步不自动触发第五步。** 被系统自己反复浮现的记忆不能因此永生。

## 9.4 MemorySurfacePolicy

所有 provider candidate 在进入 Cognition 前必须经过 Runtime policy：

```text
Provider Candidates
↓
Scope / Authority
↓
MemorySurfacePolicy(mode)
↓
Budget / Ranking
↓
HistoricalContextCompiler
↓
HistoricalContextBundle
```

首批 surface mode 建议只冻结语义，不冻结完整实现：

```text
SEARCH        # 用户/系统有显式查询意图
SPONTANEOUS   # 无显式 query 的主动浮现
REFLECTION    # 后台反思/整理候选
```

`DREAM` 不作为 Memory Kernel 基础 mode；如果以后有 Dream Process，应建立在 REFLECTION/Activation 之上。

## 9.5 MemoryRelation

```text
MemoryRelation {
    source_memory_id
    target_memory_id
    relation_type

    confidence
    evidence_refs[]

    auto_discovered
    algorithm_version?
    created_at
}
```

自动发现只允许非因果关系，例如：

```text
same_event
continuation_of
related_to
```

`causes / caused_by` 必须有额外 semantic/evidence justification，不能 similarity-only。

## 9.6 Affective Residue / Reflection

OB `feel` 给出的有效思想不是“再发明一个 feel bucket”，而是：事件被 Agent 消化后可能留下与原事件不同的长期第一人称解释。

MR-4R 研究对象：

```text
MemoryReflection / AffectiveResidue {
    id
    agent_scope
    source_memory_refs[]
    appraisal_snapshot_ref?
    proposition / residue
    created_at
}
```

它不能改写源 Evidence，不能把 Agent 感受写成用户事实，也不保证 V0.1.4 就正式进入 Kernel。

## 9.7 Verbatim / Source Evidence

精准原话属于 Evidence/Provenance 通道，不属于普通 semantic memory 本体：

```text
VerbatimSelection {
    evidence_ref
    selected_range
    selected_by
    selected_at
    purpose
}
```

普通 retrieval 不默认把整份 transcript 当第二套 memory index。需要原文时通过 Evidence 权限与预算门禁读取。

## 9.8 V0.x MR-2 的受限 Historical Context Port

为了不让 OB 研究反向膨胀第一 Product Slice，MR-2 仍然**不实现 Native Memory write**。

但原来的 `ExternalHistoricalContext` 升级为 provider-neutral typed read contract：

```text
HistoricalContextQuery {
    scope
    situation_hint?
    query_text?
    pattern_queries[]
    budget
}

HistoricalContextItem {
    external_id
    kind
    proposition
    source_refs[]
    confidence?
    relevance_hint?
}

HistoricalContextBundle {
    episodes[]
    stable_facts[]
    relationship_events[]
    pattern_summaries[]
    source_refs[]
    provider_trace
}
```

强制：

```text
read-only
no MemoryCandidate write
no touch/reinforce side effect
no provider-native raw dump
no provider-owned appraisal threshold
```

来源可以是现有 OB、旧 Memory、fixture 或未来 Mem0 adapter。Native Memory 从 MR-4 开始。

---

# 十、Memory / Historical Context 如何参与认知

长期目标不是：

```text
search top_k
→ raw dump into prompt
```

而是：

```text
Current Situation
↓
HistoricalContextQuery / MemoryActivationQuery
↓
Provider / Memory Engine candidates
↓
MemorySurfacePolicy
↓
HistoricalContextCompiler
↓
HistoricalContextBundle
↓
Appraisal Resolution
↓
Dynamics / Decision Context
```

MR-2 使用只读 `HistoricalContextPort`；MR-4 后由原生 Memory Kernel 实现同一 read contract，因此 D8 不绑定 OB/Mem0 API。

历史至少可以影响：

```text
Situation
ResolvedAppraisal
Dynamics
Decision Context
```

但它不能直接：

```text
mutate User State
mutate Agent Affect
revive old State
reinforce itself just because it was surfaced
```

### Pattern recurrence

Provider 只返回历史事实：

```text
PatternQuery(signature, scope, window)
→ PatternMatchSummary(
      match_count,
      first_seen_at,
      last_seen_at,
      matched_refs,
      confidence
  )
```

然后 Runtime 才计算：

```text
PatternMatchSummary
+ Persona
+ Relationship
+ Situation
→ recurrence_modifier
→ ResolvedAppraisal
```

例如同一个 `plan_cancelled`，第一次与第五次可以产生不同 Appraisal；但“超过 3 次算威胁”这类阈值永远不能藏在 OB/Mem0 adapter 里。

### Surfacing feedback loop protection

如果某条历史只是因为当前 affect 高而被主动浮现：

```text
Affect
→ Memory surfaced
→ Appraisal
→ Affect changes
```

必须 trace 这条闭环，并确保 `surfaced` 本身不增加该 Memory 的长期权重；只有符合显式 `ReinforcementPolicy` 的真实使用/新证据才允许强化。

冻结：Memory/Historical Context 只能作为新 Appraisal / Transition 的输入，不能直接“复活”旧 State。

---

# 十一、Appraisal

Appraisal 回答的是：

> 这件事情对于“当前这个 Agent”意味着什么？

必须分两层。

## 11.1 AppraisalRouter：先决定走哪条解释路径

`AppraisalRouter` 返回 `AppraisalRouteDecision`，显式记录 path / confidence / ambiguity_score / reason_codes。

路由顺序仍然是 deterministic → typed mapping → genuine ambiguity 才 LLM；路由本身必须 trace。

## 11.2 SemanticAppraisal：语义解释

例如用户临时取消约定，模型或 typed resolver 最多判断：

```text
meaning = schedule_change / possible_rejection
valence = negative
relationship_relevance = low | moderate | high
confidence = ...
```

它不读取或决定最终情绪数值。

## 11.3 ResolvedAppraisal：Runtime 后果解析

输入：

```text
SemanticAppraisal
+ Current Relationship
+ Persona
+ Situation
+ Historical Context / Memory
```

输出：

```text
ResolvedAppraisal {
    semantic_signal
    affective_impulses[]
    motivation_signals[]
    recurrence_modifier
    relationship_modifier
    confidence
    evidence_refs[]
}
```

同一句“今晚不来了”：

低 abandonment sensitivity、关系稳定、历史偶发时，可能得到：

```text
disappointment_impulse = moderate
relationship_threat = low
```

高 abandonment sensitivity、关系不稳、历史重复时，可能得到：

```text
disappointment_impulse = high
relationship_threat = moderate
recurrence_modifier = elevated
```

真正的人格差异发生在这里，而不是靠 Prompt 写“你容易吃醋”。

---

# 十二、Affective State

心潮的 12 维在这里重新获得正确位置。

不是产品 Schema。

而是一个 Persona 可以安装的：

```text
Affective Profile
```

允许：

```text
5维
12维
20维
自定义
```

例如陪伴 Agent 可以有：

```text
affection
longing
curiosity
worry
irritation
attachment
...
```

工作 Agent 可以有：

```text
focus
urgency
confidence
frustration
curiosity
```

内核完全不关心是不是 12。

---

# 十三、Affective Transition

建议统一模型：

```text
Current Affect
+
Elapsed Time
+
Appraisal
+
Memory Resonance
+
Relationship State
+
Persona Profile
+
Cross-Dimension Coupling
        ↓
Dynamics Engine
        ↓
New Affect
```

Trace 必须能解释：

```text
longing:
0.42
+ current event      +0.08
+ memory resonance   +0.04
- time recovery      -0.03
= 0.51
```

不能只留下：

```text
0.42 → 0.51
```

否则后续很难调参。

---

# 十四、Motivation

Affect 不应该直接决定 Action。

例如：

```text
longing = 0.82
```

不等于：

```text
必须发消息
```

应该产生：

```text
Motivation {
    contact_desire = 0.84
    reassurance_desire = 0.42
    share_desire = 0.61
}
```

然后 Policy 再决定：

```text
能不能做
```

---

# 十五、Behavior Control：ActionPolicy 与 ExpressionGuard

Kayla 手调规则不能继续散落在 Prompt、桥接器和心潮代码里，但也不能全部粗暴归成一个 Policy。

## 15.1 ActionPolicy

回答：

> 当前 Action 能不能执行？

典型规则：

```text
主动消息 cooldown 30m
currentTurn → 禁止插嘴
photo every N=3
daily photo limit=8
channel capability
resource budget
```

可以内部拆成：

```text
ActionCooldownPolicy
ConversationInterruptionPolicy
ResourceBudgetPolicy
MediaEligibilityPolicy
```

输出：

```text
ActionPermission {
    action_type
    allowed
    reasons[]
    constraints[]
}
```

## 15.2 ExpressionGuard

回答：

> 已生成的表达能不能发？

典型规则：

```text
禁用固定开头
前 8 字硬去重
当前是凌晨却描述晚霞
重复上一次主动消息角度
```

输出：

```text
ExpressionCheck {
    accepted
    violations[]
    rewrite_required
}
```

完整关系：

```text
Motivation
↓
ActionPolicy
↓
ActionIntent
↓
DecisionContext
↓
LLM
↓
ExpressionGuard
↓
accept / rewrite / reject
```

这是内部模块化，不是拆成多个服务。

---

# 十六、Kayla 现有规则如何映射

现状：

```text
drive ≥ 0.55
```

迁移为：

```text
Motivation activation threshold
```

现状：

```text
settle = 15m
```

迁移为：

```text
Dynamics scheduling / tick policy
```

现状：

```text
30m proactive cooldown
```

迁移为：

```text
ActionCooldownPolicy
```

现状：

```text
currentTurn != null → 不插嘴
```

迁移为：

```text
ConversationInterruptionPolicy
```

现状：

```text
每 3 条最多 1 图
每天 8 图
```

迁移为：

```text
MediaBudgetPolicy / MediaEligibilityPolicy
```

现状：

```text
禁止固定开头
前 8 字去重
```

迁移为：

```text
ExpressionGuard.dedup
```

现状：

```text
凌晨不能说晚霞
```

迁移为：

```text
Situation.time_context
+ ExpressionGuard.temporal_grounding
```

现状：

```text
“上次说了什么 + 禁止复述 + 换切入角度”
```

迁移为：

```text
DecisionContext.expression_context
+ ExpressionGuard.repetition_check
```

这样 Kayla 的规则成为可解释的 Runtime contract，而不是散落的 if 和 Prompt hack。

---

# 十七、Decision Context

LLM 最终不应该看到各系统输出的原始 dump。

禁止：

```text
STATEBAR: ...
MEMORY: ...
心潮: ...
RULE: ...
```

统一编译：

```text
DecisionContext {
    interaction
    situation

    effective_user_state
    projected_agent_state
    relationship_state

    historical_context

    semantic_appraisal?
    resolved_appraisal

    motivations[]
    action_permissions[]

    relevant_persona
    goals?

    expression_context
}
```

注意：

- `projected_agent_state` 是本轮用于决策的投影视图，不等于已提交 Canonical State。
- `action_permissions` 来自 ActionPolicy。
- `expression_context` 可以给生成提供约束，但最终仍必须经过 ExpressionGuard。

```text
DecisionContext
↓
Context Renderer
↓
LLM / Agent
↓
ExpressionGuard
```

这是 Mind Runtime 对 Agent 的真正消费接口。

---

# 十八、完整 Turn 生命周期

这是开发时必须实现的 authoritative call chain。

## 18.1 Begin Turn：事实进入 + 投影计算

```text
1. InteractionCoordinator.begin()
        ↓
2. Scope / Authority / Ownership resolve
        ↓
3. Evidence ingest（持久化）
        ↓
4. Observation extraction / validation（持久化）
        ↓
5. Factual Reconcile
   └─ Evidence-backed user/world transition 可在 ingest phase 提交
        ↓
6. EffectiveStateResolver + Current-turn overlay
        ↓
7. SituationBuilder
        ↓
8. HistoricalContextPort read（MR-2 可选，只读、无 touch/reinforce）
        ↓
9. AppraisalRouter / AmbiguityAssessment
   ├─ deterministic
   ├─ typed_mapping
   └─ semantic LLM（仅 genuine ambiguity）
        ↓
10. ResolvedAppraisal
        ↓
11. Dynamics → TransitionIntent[]
        ↓
12. TurnProjection / ProjectedMindState
        ↓
13. Motivation
        ↓
14. ActionPolicy
        ↓
15. DecisionContext compile
        ↓
16. Agent / LLM candidate output
        ↓
17. ExpressionGuard
```

本轮用户刚说：

> “我刚睡醒。”

即使最终心理 Transition 尚未 commit，本轮 DecisionContext 也必须立即看到：

```text
user.sleep.phase = awake
user_activity = awake_and_engaged
```

因此 `TurnProjection` 是正式 Runtime primitive，不再只是“推荐优化”。

## 18.2 权威边界

冻结：

```text
Evidence / Observation = 已发生事实，持久化
Factual Transition     = 可在 ingest phase 提交
TurnProjection         = 当前心智计算视图，不是 Canonical Mind State
Derived TransitionIntent = 候选心智变化，不是 Committed Transition
```

如果 Agent/bridge 在 turn 中途失败，系统至少拥有 Evidence / Observation，可以通过 replay/reconcile 恢复；不得依赖内存中的半轮状态。

---

# 十九、Commit Turn

Agent 产生候选行为并通过 ExpressionGuard 后，进入提交阶段：

```text
18. authoritative turn materialize
        ↓
19. validate TurnProjection / `commit_phase=turn_commit` TransitionIntent
        ↓
20. commit projected agent / relationship transitions
        ↓
21. commit Action / delivery outcome
        ↓
22. persist interaction trace
        ↓
23. append replication outbox events
        ↓
24. commit Unit of Work
```

MR-4 以后追加：

```text
25. create MemoryCandidate
26. persist writeback receipt / reconciliation state
```

Memory embedding / external provider 写入可以异步，但必须先本地持久化 candidate/receipt。

## Turn failure / abort

如果 LLM、bridge 或客户端失败：

```text
Interaction.status = failed / aborted
Evidence / Observation 保留
未提升的 TurnProjection 不得伪装成 Canonical Transition
后续可 replay / reconcile
```

这就是 `candidate != committed` 原则在 State/Affect 上的统一推广。

---

# 二十、主动性不再是独立 hack

Mind Runtime 支持：

```text
tick(now)
```

用于无新消息时的演化：

```text
time dynamics
pending goals
affective changes
memory resonance
unresolved interaction
motivation
policy
```

最终：

```text
ProactiveCandidate
```

再通过 Policy。

不是：

```text
心潮数值超过0.55
→ 直接发消息
```

而是：

```text
Dynamics
↓
Motivation
↓
ProactiveCandidate
↓
Policy
↓
allowed / blocked
↓
Action
```

---

# 二十一、Statebar 与 Mind Runtime 的双轨关系

Statebar 继续作为独立技术迭代线，但不再承担 Mind Runtime 产品扩张。

## Track A — statebar-mcp：技术验证

当前源码审计暴露的 P0 仍可继续修：

```text
P0-1 EffectiveStateResolver
P0-2 CURRENT_LIKE expiration
P0-3 terminal status protection
P0-4 reaffirm refresh temporal envelope
P0-5 Reconciler 使用 Effective State
P0-6 relevance 独立过滤
P0-7 lifecycle transition legality
P0-8 transaction
P0-9 ambiguous resolve/cancel fail closed
```

Statebar 边界冻结：

```text
Observation
→ Canonical State
→ Effective State
```

不继续加入 Appraisal、Persona、Affect、Memory、Policy。

## Track B — mind-runtime：新产品内核

Mind Runtime：

```text
只吸收 Statebar 已验证 primitive / contract / test
不 import statebar package
不继承 statebar schema
不要求 Statebar P0 全部完成才开始 MR-0/MR-1
```

两条线可以互相验证测试，但不存在“先把 Statebar 改成 Mind Runtime 再迁移”的依赖关系。

冻结：

> 旧项目负责证明技术能工作；新产品重新定义其领域边界与权威。

---

# 二十二、Mind Runtime 代码形态

V0.x 推荐模块化单体：

```text
mind_runtime/
│
├── interaction/
│   ├── coordinator
│   ├── scope
│   ├── authority
│   ├── ownership
│   ├── projection
│   └── transaction
│
├── evidence/
│   ├── models
│   └── ingest
│
├── observation/
│   ├── models
│   ├── extraction
│   └── validation
│
├── state/
│   ├── definitions
│   ├── reconciler
│   ├── lifecycle
│   ├── effective_resolver
│   ├── dynamics
│   └── transitions
│
├── history/                 # MR-2 只读历史 adapter
│   ├── context
│   └── providers
│
├── memory/                  # MR-4 才启用原生写入
│   ├── records
│   ├── candidates
│   ├── activation
│   ├── consolidation
│   └── providers
│
├── semantics/
│   ├── situation
│   ├── temporal
│   └── abstraction
│
├── appraisal/
│   ├── semantic
│   ├── resolver
│   ├── router
│   ├── ambiguity
│   └── models
│
├── motivation/
│
├── policy/
│   ├── action
│   └── expression_guard
│
├── persona/
│   ├── profile
│   └── dimensions
│
├── context/
│   ├── compiler
│   └── renderer
│
├── proactive/
│
├── replication/
│   ├── protocol
│   ├── null_adapter
│   ├── in_memory_harness
│   └── models
│
├── trace/
│
├── providers/
│   ├── llm
│   ├── embeddings
│   └── clock
│
└── storage/
```

注意不存在作为一级领域模块的：

```text
statebar/
xinchao/
memorax/
ob/
```

这四个名字只属于技术来源或 adapter，不属于新产品领域模型。

---

# 二十三、首版持久化

V0.x 推荐单 SQLite/Postgres authoritative persistence domain。

## MR-1~MR-3 必需

```text
interactions
evidence
observations

state_definitions
states
state_transitions
transition_intents / projection_trace

persona_profiles
persona_dimension_profiles

semantic_appraisals
resolved_appraisals
motivations

action_permissions
action_candidates
actions
expression_checks

turn_checkpoints
action_receipts

traces
```

`TurnProjection` 可以采用“持久化精简 trace + 可重算完整对象”的方式，不要求把每个派生字段都永久存表。

## MR-4 再加入（最终表名由 D12 Contract 冻结）

```text
memory_records
memory_candidates
memory_relations
memory_events?                 # 仅当 D12 采用 event ledger
memory_projection_jobs         # embedding / lexical / relation 等派生任务
memory_activation_trace
memory_reinforcement_events
memory_writeback_receipts
memory_reflections?            # 仅当 Affective Residue 试验通过
```

原则：canonical memory 与 derived index 不共用“成功/失败”语义；embedding/BM25/provider failure 不能回滚已提交 canonical memory。

必须可审计的最低集合：

```text
Interaction
Evidence
Observation
Committed Transition
Appraisal route / result
Action decision / delivery receipt
Turn checkpoint / recovery outcome
```

V0.x 不允许靠进程内变量维持关键 Persona / State / ownership 信息。

`replication_outbox / replication_inbox` 的物理表不在 MR-1~MR-3 建立；MR-5 再落 DDL。MR-1 仅提供 `ReplicationEnvelope/Port` 与 Null/InMemory harness。

真实 Shadow 环境前，Trace 必须支持 `DataSensitivity / RedactionPolicy / RetentionClass`。

---

# 二十四、对外 API

不要把内部模块暴露给 Agent。

核心生命周期接口：

```python
mind.begin_turn(...)
```

返回：

```text
TurnProjection
DecisionContext
```

```python
mind.commit_turn(...)
```

提交经过验证的 projected transitions / action outcome。

```python
mind.abort_turn(...)
```

记录失败/取消，不把未提交 Projection 伪装成 Canonical State。

```python
mind.tick(...)
```

处理时间演化与主动候选。

辅助：

```python
mind.ingest_event(...)
mind.inspect_state(...)
mind.trace(...)
mind.health(...)
```

MCP、HTTP、Hermes Adapter 都只是 transport。

---

# 二十五、开发阶段（V0.1.4 Product Slice）

> **终局架构不是连续 backlog。** 第一版只完成一条可运行闭环，然后停止扩展并进入真实环境验证。

V0.x canonical pipeline：

```text
Interaction
→ Evidence
→ Observation
→ Effective State
→ Situation
→ Appraisal Resolution
→ Affective Dynamics
→ Motivation
→ ActionPolicy
→ Decision Context
→ Agent / LLM
→ ExpressionGuard
→ Commit
```

完整 Memory consolidation、通用 Goal、复杂 proactive planning、多 Provider 产品化明确推迟。

## MR-0：冻结 Kernel Contract

必须冻结：

```text
Interaction
Scope
Authority
Ownership
Evidence Authority
Observation semantics
State / Transition semantics
TurnProjection / TransitionIntent
Dynamics Policy contract
Situation contract
AppraisalRouteDecision / AmbiguityAssessment
SemanticAppraisal / ResolvedAppraisal
PatternQuery / PatternMatchSummary
Motivation contract
ActionPolicy contract
ExpressionGuard contract
DecisionContext contract
TurnCheckpoint / ActionReceipt / DeliveryReceipt
DataSensitivity / RetentionClass / RedactionPolicy
Clock / Persistence
ReplicationEnvelope / ReplicationPort contract
```

同时建立 ADR / Decision Log。没有 MR-0，不开始大量业务代码。

## MR-0.5：Golden Scenario 骨架

在实现前建立 G1~G16 + G13b/G16b 测试入口和 fixture。

要求测试支持：

```text
FakeClock
固定 Persona
固定 Historical Context
固定 Evidence
可重复 replay
```

## MR-0.6：D2S Vertical Walking Skeleton

在任何真实业务算法实现前，用 typed stub 串通唯一 canonical pipeline。必须验证：

```text
begin_turn
→ ingest_commit factual evidence
→ projected mind state
→ DecisionContext
→ Fake Agent
→ ExpressionGuard
→ action receipt
→ commit_turn / abort_turn
→ trace / replay
```

D2S 是 D3 开工 Gate。

## MR-1：Stateful Runtime（State primitive 毕业）

实现：

```text
Interaction
Scope / Authority / Ownership
Clock
Evidence
Observation
Factual Reconciler / Transition
EffectiveStateResolver
Current-turn overlay
TurnProjection 基础结构
Unit of Work
TurnCheckpoint / ActionReceipt / DeliveryReceipt
Trace
Replication Protocol/Envelope + Null/InMemory harness（不建物理 Outbox/Inbox 表）
```

此阶段不做情绪、不做 Native Memory。

目标：

> 一轮事实状态可以完整 replay；业务代码只能消费 Effective State；投影与提交边界清晰。

## MR-2：Situation + Dynamic Persona

实现：

```text
Persona Base               # Trait ≠ State
Affective Dimension Profile # 不固定 12 维
Dynamics Policy
  continuous_return_to_baseline
  accumulator
  event_only

Situation Abstraction
  Temporal Semantics
  Derived Facts

HistoricalContextPort / Bundle（只读）
  episodes
  stable facts
  relationship events
  pattern summaries
  no read-side touch/reinforce

AppraisalRouter / AmbiguityAssessment
SemanticAppraisal
ResolvedAppraisal
PatternQuery / PatternMatchSummary
```

Appraisal 路由：

```text
deterministic → typed_mapping → 必要时 llm
```

LLM 只输出 meaning / valence / relationship_relevance / confidence。

禁止 MR-2 实现 MemoryCandidate / Memory commit / consolidation。

目标：

> 同一个事件在不同 Persona / Relationship / Historical Context 下产生不同、可追踪的 affective transition；Appraisal 路径与成本可观测。

## MR-3：Behavior Loop（首个可交付 Product Slice）

实现：

```text
Projected Affect
→ Motivation
→ ActionPolicy
→ DecisionContext
→ Context Renderer
→ Agent / LLM
→ ExpressionGuard
→ commit_turn
```

迁移 Kayla 当前真实规则：

```text
drive threshold
settle / tick
30m cooldown
正在对话不插嘴
图片预算
禁用开头
前 8 字去重
时间语境真实性
```

做到这里即形成第一版完整闭环：

```text
用户做了什么
↓
现在是什么状态
↓
现在是什么情境
↓
这件事意味着什么
↓
内部状态怎么变化
↓
想做什么
↓
能不能做
↓
怎么表达并校验
↓
提交
```

**MR-3 完成后停止扩展，进入真实环境试运行。**

## MR-4：OB-first Native Memory Continuity（条件式，D11 后才实现）

D11 证明第一 Product Slice 有产品价值后，才允许进入正式实现。MR-4 不再以“先写 MemoryCandidate + merge”开场，而先冻结 Memory Kernel Contract 与 benchmark。

正式顺序：

```text
R4 Research (可提前，只读)
↓
D12 Memory Kernel Contract Freeze
↓
D13 Memory Golden / Benchmark Harness
↓
D14 Admission + Canonical Commit
↓
D15 Derived Projection / Index Outbox
↓
D16 Surface / Activation / Reinforcement
↓
D17 Retrieval Benchmark + Engine/Provider Decision
↓
D18 Relation / Pattern Graph
↓
D19 Reflection / Context Compiler Integration
↓
D20 Migration / Cutover / Replay-Rebuild Recovery
```

### R4 Research Track（不阻塞 D3~D11）

```text
R4-1 OB 3.2 source decomposition
R4-2 Mem0 differential audit
R4-3 MemoraX differential audit
R4-4 multilingual corpus + benchmark design
R4-5 Memory Kernel RFC / KEEP-REWRITE-REJECT matrix
```

Research 可以提前完成，但 D11 前不得 merge Native Memory write path。

### MR-4 强制验收原则

```text
MemoryCandidate != Committed Memory
Canonical Memory != Derived Index
Memory Retrieved != Memory Reinforced
Memory Activation != State Resurrection
Surface Policy before Cognition
Similarity != Causality
Provider != Domain Authority
```

MR-2 的 `HistoricalContextPort` 在 MR-4 被原生 Memory Kernel 实现；上层 Situation/Appraisal 不因 backend 替换而改 Contract。

---

## MR-5：Distributed Runtime

把 MR-0/MR-1 已冻结的数据结构扩展为 transport：

```text
Local Commit
→ Outbox
→ Peer / Server Sync
→ Inbox
→ Idempotency
→ Authority Check
→ Ownership Check
→ Scope Check
→ Apply
```

原则：

- 优先复制 Evidence / Observation。
- Projected State 永不复制。
- Agent 私有 affect / relationship 单写者。
- 用户共享事实可由多个 Runtime 产生 Evidence，再由 State Engine reconcile。
- 不做 SQLite 全量双向复制，不在 V0.x 引入 CRDT。

## MR-6+：后续增强

明确推迟：

```text
复杂多轮 Appraisal / pattern learning
完整 proactive planning
Goal system
更多 Persona
SDK / MCP / HTTP / Hermes 产品化
容器 / observability / migration tooling
```

这些都不得阻塞 MR-3 的第一版 Product Slice。

---

# 二十六、必须建立的 Golden Tests

这些测试比普通 unit test 更重要。

### G1：凌晨刚醒

```text
02:30
用户：“刚睡醒”
持续聊天
```

必须得到：

```text
user awake
conversation active
sleep norm assumption suppressed
```

禁止：

> “这么晚你该睡了。”

---

### G2：状态 reaffirm

```text
08:00 headache
18:00 仍然头疼
21:00
```

21:00 仍应 active。

---

### G3：cancelled 不是 expired

```text
15:00 plan cancelled
18:00
```

可以作为 recently cancelled context。

之后 relevant_until 到期：

不再主动进入 context。

历史仍然：

```text
cancelled
```

---

### G4：想发但不能发

```text
longing = high
current conversation active
```

必须：

```text
contact motivation = high
proactive action = blocked
```

验证：

```text
Motivation ≠ Policy
```

---

### G5：图片预算

```text
photo motivation high
daily count = 8
```

必须允许：

```text
text message
```

但：

```text
photo = blocked
```

---

### G6：重复事件产生不同意义

第一次取消：

```text
relationship threat low
```

多次类似 Memory 激活后：

```text
pattern concern higher
```

验证 Memory 真正参与 Appraisal。

---

### G7：Persona 差异

同一个 Observation、同一关系状态。

Persona A：

```text
low abandonment sensitivity
```

Persona B：

```text
high abandonment sensitivity
```

最终 affect transition 必须不同。

---

### G8：Assistant 自污染防护

Assistant：

> “感觉你有点累。”

不能自动产生：

```text
user.tired = true
```

---

### G9：迟到事件

旧消息 delayed 到达。

不得回滚更新后的当前状态。

---

### G10：Replay

给定：

```text
相同 Evidence
相同 Clock
相同 Persona
相同 Memory snapshot
```

deterministic 部分必须产生相同：

```text
Effective State
Situation
Policy
```

LLM semantic 部分必须有结构化 trace。

---

### G11：Scope 隔离

Kayla：

```text
relationship.longing
```

不得进入 Lara scope。

用户稳定事实可以按明确规则共享。

---

### G12：重启恢复

进程重启后：

```text
State
Memory
Relationship
pending writeback
```

恢复一致。

不允许靠内存变量维持“人格”。

---

### G13：Projection 不得提前污染 Canonical State

```text
begin_turn
→ affect projection 0.42 → 0.55
→ Agent 调用失败
```

必须：

```text
Canonical affect 仍为 0.42
Evidence / Observation 仍可追踪
Projection 可 replay / reconcile
```

---

### G13b：Factual Commit 必须在 Cognitive Abort 后保留

```text
用户：“我刚睡醒”
ingest: user.sleep.phase = awake COMMITTED
turn: agent affect projection created
LLM failure → abort_turn
```

必须：

```text
user.sleep.phase = awake       保留
Evidence / Observation         保留
Projected agent affect         aborted/丢弃
Canonical agent affect         不变
```

---

### G14：ActionPolicy 与 ExpressionGuard 分离

```text
proactive action = allowed
LLM 生成文本与上一条前 8 字重复
```

必须：

```text
ActionPolicy = allowed
ExpressionGuard = rewrite_required
```

不得把整个主动行为错误判成 policy denied。

---

### G15：Replication Authority / Ownership

Lara Runtime 收到：

```text
scope = agent:kayla
object = affect.longing
operation = write
```

必须 fail closed。

共享的 `user:*` Observation 在通过 Authority / Scope 后才允许进入 Inbox apply。

---

### G16：AppraisalRouter 不做无意义 LLM 调用

给定：

```text
last proactive = 10min ago
cooldown = 30min
```

必须 deterministic 得出 blocked，且：

```text
appraisal_path != llm
llm_call_count = 0
```

同时对真正歧义语言允许走 `appraisal_path = llm` 并留下 trace。

### G16b：真正语义歧义必须升级到 LLM

给定一个经过 fixture 标注、同时合理支持 `possible_rejection` 与 `neutral_reschedule` 的模糊表达：

必须：

```text
AppraisalRouteDecision.path = llm
ambiguity_score >= configured_gate
SemanticAppraisal schema valid
trace 包含 route reason
LLM 输出不得含最终 affect 数值
```

该测试防止为了降低调用成本把所有歧义硬编码为 deterministic/typed mapping。

---

### G17（MR-4）：Passive Surfacing 不得自动 Reinforce

```text
memory M 被 SPONTANEOUS surface 10 次
但没有新 Evidence / explicit use / reinforcement condition
```

必须：

```text
last_reinforced_at unchanged
reinforcement_count unchanged
```

---

### G18（MR-4）：Derived Index Failure 不得丢失 Canonical Memory

```text
Memory commit 成功
embedding provider down
lexical index worker failure
```

必须：

```text
Canonical Memory committed
projection job pending/retryable
memory 可通过 canonical read 找到
```

恢复 provider 后 projection 可重建且 canonical id 不变。

---

### G19（MR-4）：Similarity 不得自动制造 Causal Relation

两条高度相似且时间接近的 Memory 可以得到：

```text
same_event / continuation_of / related_to
```

但无额外 Evidence/semantic rationale 时禁止自动得到：

```text
causes / caused_by
```

---

### G20（MR-4）：SurfacePolicy 优先级必须可解释

给定同一 Memory 同时存在多个 processing/lifecycle flags，SurfaceDecision 必须输出明确 reason code；禁止“静默少一条”而无 trace。

---

### G21（MR-4）：Verbatim Evidence 不得变成第二套普通 Recall

保存一段 exact quote / raw evidence 后：

```text
ordinary semantic memory search
```

不得因为原文存档而默认扩大召回面；显式 evidence/quote retrieval 才允许返回，并保留 provenance 与预算限制。

---

### G22（MR-4）：Projection Rebuild Equivalence

删除所有 derived embedding / lexical / auto-relation projection 后，从 canonical memory/event truth 重建。

必须：

```text
canonical memory set identical
manual/confirmed relations preserved
retrieval benchmark within accepted tolerance
```

---

### G23（MR-4）：Backend Swap 不改变 Domain Contract

同一组 fixture 分别由 legacy OB adapter、candidate Mem0 adapter、native test provider 返回历史候选。

必须：

```text
HistoricalContextBundle schema identical
Scope/SurfacePolicy semantics identical
Provider 不得返回最终 Appraisal/recurrence verdict
```

---

# 二十七、禁止事项

这部分应直接进入项目 `AGENTS.md`。

### 禁止 1
不允许把 Mind Runtime 做成升级版心潮。

### 禁止 2
不允许内核固定 12 维。

### 禁止 3
不允许把 OB API 语义变成 Memory Domain Model。

### 禁止 4
不允许业务层直接读 Raw State；统一消费 Effective State。

### 禁止 5
不允许 LLM 直接 mutate Canonical State 或直接输出最终 affect 数值。

### 禁止 6
不允许 Assistant Output 自动成为 Evidence。

### 禁止 7
不允许 Memory / Historical Context 直接复活旧 State。正确路径：

```text
Historical Context / Memory Activation
↓
Appraisal Resolution
↓
New Transition
```

### 禁止 8
不允许把业务规则只写在 Prompt。

### 禁止 9
不允许 `completed/cancelled/resolved/superseded` 因时间被改写成 `expired`。

### 禁止 10
V0.x 不拆微服务，除非出现明确性能/安全隔离证据并通过 ADR。

### 禁止 11
不允许把 `TurnProjection` 当作 Canonical State；Projected Transition 必须通过 commit/reconcile 边界。

### 禁止 12
不允许把 ActionPolicy 与 ExpressionGuard 合并成一个模糊“规则层”。

### 禁止 13
MR-2 不允许偷偷实现 Memory writeback / consolidation；只读 Historical Context。

### 禁止 14
不允许为了降低 LLM 调用率而把真实语义歧义硬编码成确定性规则。

### 禁止 15
不允许跨 Persona 写入私有 affect / relationship scope；Ownership 检查必须 fail closed。

### 禁止 16
不允许同步/复制未提交的 Projected State。

---

### 禁止 17
不允许把 OB 的 `bucket / breath / hold / grow / feel / dream` 名词直接变成 Mind Runtime 核心 Domain API。

### 禁止 18
不允许把 embedding、BM25、auto relation、retrieval cache 当 authoritative Memory truth；它们必须可重建。

### 禁止 19
不允许 `retrieved / surfaced / activated` 自动触发 memory reinforcement。

### 禁止 20
不允许 similarity-only 自动建立 causal relation。

### 禁止 21
不允许复制 OB 的阈值、decay 参数或 relation cap 后直接宣称适用于中文/葡语/英语语料；必须 benchmark/calibration。

### 禁止 22
不允许因为 OB 已经有 event sourcing / Raft / microkernel / Rust kernel，就把第一 Product Slice 改造成全局 event-sourced/distributed system。

### 禁止 23
不允许在 MR-4 provider benchmark 完成前锁死 Mem0、OB-native 或任意外部 backend 为唯一实现。

# 二十八、需求变更流程

以后任何 Agent 想改核心行为，必须增加 ADR。

模板固定：

```text
ADR-ID:
Date:

Problem:
当前问题是什么？

Previous Assumption:
之前为什么这么设计？

New Evidence:
什么实际情况证明原假设不足？

Decision:
现在冻结什么？

Rejected Alternatives:
为什么不选其他方案？

Affected Contracts:
影响哪些模型/API？

Migration:
旧数据/旧逻辑怎么处理？

Acceptance Tests:
新增哪些测试防止再次漂移？
```

没有 ADR，不允许改变：

```text
Observation semantics
State semantics
Memory semantics
Scope / Authority / Ownership
Replication contract
TurnProjection / commit boundary
Dynamics
SemanticAppraisal / ResolvedAppraisal boundary
ActionPolicy boundary
ExpressionGuard boundary
DecisionContext
```

需求变更顺序必须是：

```text
新证据 / 新需求
→ ADR
→ Contract / Golden Test
→ 实现
```

禁止代码先改完，再用文档追认。

---

# 二十九、当前冻结的产品边界

建议直接放 README 顶部：

> **Mind Runtime 是 Agent 的外置心智运行时。** 它将权威 Evidence 转化为 Observation 与 Effective State，把当前状态、时间、历史上下文、关系和 Persona 抽象为 Situation，经 Appraisal Resolution 与 Dynamics 形成可解释的 Projected Mind State，再通过 Motivation、ActionPolicy 和 Decision Context 参与 Agent 决策；生成结果还需经过 ExpressionGuard，最后由 Commit 边界提升为可审计的 Canonical Transition。LLM 负责语义理解与表达，但不拥有状态真相、记忆真相、生命周期控制权或最终数值计算权。

Statebar：

> 独立技术验证项目，负责探索 `Observation → Canonical State → Effective State`；不是 Mind Runtime 的前置依赖，也不继续扩成高阶认知层。

心潮：

> 历史参考项目，其核心价值是验证“Agent 拥有模型之外、持续存在并随时间演化的内部状态”这一产品洞察；固定 12 维和现有工程结构不构成 Mind Runtime 约束。

Memory：

> Memory 是 Mind Runtime 的时间连续性机制，不等同于 RAG。V0.x 第一 Product Slice 只通过 provider-neutral `HistoricalContextPort` 读取历史；MR-4 才拥有原生 Memory Kernel。

OB 3.2.x：

> MR-4 第一源码参考：重点吸收 SurfacePolicy、active resurfacing、decay/salience、authoritative-vs-derived、relation discovery、outbox/replay/recovery 等 primitive；不 fork、不 import、不继承其产品边界和存储格式。

Mem0：

> MR-4 的 Retrieval/Entity/Temporal differential reference 和候选 provider；是否成为 backend 必须由 D17 多语言 benchmark 决定。

MemoraX：

> 提供 Turn/Writeback/Provider-runtime 的 Scope、Authority、candidate/commit、redaction、idempotency、receipt/reconcile 等工程纪律，不作为独立产品模块。

---

# 三十、下一步实际派单顺序（V0.1.4）

执行结构：

```text
MR = Architecture Milestone
D  = Delivery Gate / Epic
W  = Agent Work Package
```

第一 Product Slice 顺序：

```text
D0    Repository / ADR / Legacy Rule Inventory
D1    Typed Kernel Contracts
D2    Golden Harness（G1~G16 + G13b/G16b）
D2S   Vertical Walking Skeleton
D3    Interaction / Evidence / Observation / Authority
D4    Effective State / Lifecycle
D5    TurnProjection / Checkpoint / ActionReceipt / Trace
D6    Situation / Temporal Semantics
D7    Persona / Dynamics
D8    AppraisalRouter / Historical Pattern / Affect Projection
D9    Motivation / ActionPolicy
D10   DecisionContext / Renderer / ExpressionGuard
D11   Kayla E2E / ShadowDiff / 灰度
```

真正派给开发 Agent 的不是整块 D，而是 `W`。例如 D4 拆成 D4.1~D4.8，D8 拆成 D8.1~D8.9；详见配套《V0.1.4 分步开发与分布派单总纲》。

允许 Prework Lane：在当前 D 开发期间，后续 D 可提前制作 truth table、fixture、规则 inventory 和伪代码，但禁止提前 merge 业务实现。

新增 `R4 Memory Research Lane`：D2S 后即可继续做 OB/Mem0/MemoraX 源码对照、benchmark corpus 和 Memory RFC；它是 research artifact，不得绕过 D11 Stop Gate 落 Native Memory 写路径。

停止点纪律：**D11 / MR-3 是第一 Product Slice 的强制停止点。** Shadow 真实数据没有证明价值前，不进入 MR-4 implementation、Distributed Transport 或“通用 Agent”泛化。

最重要的一条开发纪律：

> **先用 Walking Skeleton 保证整条心智管线始终可运行，再逐层把 stub 替换成真实实现；每次替换都必须保留 replay、trace、Golden 和 Shadow 可比性。**


---

---

# 附录 A：Mind Runtime V0.1.4 分步开发与分布派单总纲

# Mind Runtime V0.1.4 分步开发与分布派单总纲

文档状态：`EXECUTION BASELINE / V0.1.4 / 2026-08-18`

配套上位文档：`Mind Runtime V0.1.4 开发总纲和需求基线.md`

本文件只解决一个问题：**如何把 V0.1.4 Product Slice 真正拆成可以按 W-level 逐单执行、逐单验收、逐单合并的开发工作。**

上位架构仍以 Kernel Baseline 为唯一权威；本文件不得自行修改领域语义。若执行中发现契约需要变化，必须先提交 ADR，再更新 Kernel Contract / Golden Test，最后修改代码。

---

# 0. 执行总原则

第一 Product Slice 的唯一闭环：

```text
Interaction
→ Evidence
→ Observation
→ Effective State
→ Situation
→ Appraisal Resolution
→ Affective Dynamics
→ Motivation
→ ActionPolicy
→ Decision Context
→ Agent / LLM
→ ExpressionGuard
→ Commit
```

开发管理采用三级结构：

```text
MR = Architecture Milestone
D  = Delivery Gate / Epic
W  = Work Package（真正派给开发 Agent）
```

第一 Product Slice 有 13 个 Gate（含 D2S Walking Skeleton）：

|Gate|所属 MR|核心目标|进入下一 Gate 的条件|
|---|---|---|---|
|D0|准备|仓库、ADR、Legacy Rule Inventory、质量门禁|仓库可复现；inventory 可追溯|
|D1|MR-0|冻结基础领域 Contract|Contract tests 全绿|
|D2|MR-0.5|建立 Golden Scenario 骨架|G1~G16 + G13b/G16b 可收集|
|D2S|MR-0.6|用 typed stub 串通全 pipeline|begin/commit/abort/replay 全链路通过|
|D3|MR-1A|Interaction / Evidence / Observation / Authority|事实 ingest 可重放、幂等、fail-closed|
|D4|MR-1B|State / Transition / EffectiveStateResolver|状态生命周期 Golden 通过|
|D5|MR-1C|TurnProjection / Checkpoint / Receipt / Trace|双事务与恢复边界通过|
|D6|MR-2A|Situation / Temporal / Derived Facts|G1/G16 deterministic 通过|
|D7|MR-2B|Persona / Dynamic Dimension / Dynamics|Persona 差异确定可解释|
|D8|MR-2C|AppraisalRouter / HistoricalContextPort / Affect Projection|G6/G7/G16/G16b 通过|
|D9|MR-3A|Motivation / ActionPolicy|G4/G5 通过|
|D10|MR-3B|DecisionContext / Renderer / ExpressionGuard|G14 通过|
|D11|MR-3C|Kayla E2E / ShadowDiff / 灰度|全 Golden + 真实指标门禁|

**MR-3 完成后必须停止功能扩张。** MR-4 Native Memory 与 MR-5 Distributed Runtime 不进入第一 Product Slice 的连续 backlog。

---

# 0.5 MR / D / W 与并行预研规则

## 0.5.1 真正派单单位

- MR：管理架构里程碑，不直接派开发。
- D：一组 Work Package 的 Delivery Gate，不建议一次交给单个 Agent。
- W：唯一默认的开发派单单位。

每个 W 必须：

```text
单一主目标
有限修改范围
明确测试入口
明确 Merge/Review Gate
不得改变上位 D Contract
```

如果 W 仍无法在一个短开发循环内产生可观察结果，执行 Agent必须继续拆 W.x.a/W.x.b，但先回报拆分，不得扩大 Scope。

## 0.5.2 Prework Lane

当前 Implementation Lane 开发时，允许后续 Gate 同步预研：

|当前实现|允许并行 Prework|只允许产物|禁止|
|---|---|---|---|
|D0/D1|D2 Golden fixture 草案、D6 Situation truth table|文档/fixture 草稿|实现未冻结 API|
|D2/D2S|D4 state edge-case matrix、D8 legacy/appraisal corpus|测试数据/伪代码|业务实现 merge|
|D3/D4|D6 temporal rules、D7 persona profile 草案、D11 shadow schema|truth table/config draft|依赖未来 Contract 的生产代码|
|D5/D6|D8 PatternQuery fixtures、Kayla legacy map 收口|fixture/mapping|Native Memory|
|D7/D8|D9/D10 policy/guard test vectors|测试向量|接 legacy bridge 的临时生产 guard|

## 0.5.3 R4 Memory Research Lane（只读预研）

D2S 之后允许与 D3~D11 并行进行：

```text
R4-1 OB 3.2 source decomposition
R4-2 Mem0 differential audit
R4-3 MemoraX differential audit
R4-4 multilingual benchmark corpus
R4-5 Memory Kernel RFC / adoption matrix
```

允许产物：源码审计、truth table、benchmark、provider spike、RFC、ADR draft。  
禁止产物：MR-4 canonical write path、Memory DDL、后台 index worker 进入主线。

Research 发现若要改变 D0~D11 Contract，必须单独 ADR + Golden evidence；不能以“OB 已经这样做”为理由直接修改主线。

---

## 0.5.4 Legacy Rule Inventory

D0 起持续维护 `docs/legacy/kayla-rule-map.md`，至少字段：

```text
rule_id
source_file_or_prompt
source_location
legacy_behavior
edge_cases
target_domain
target_contract
decision: preserve|generalize|change|drop
golden_case
shadow_metric
```

D9/D10 只允许实现已登记规则。

---

# 1. 通用派单协议

每一个开发工单都必须包含以下字段：

```text
任务编号
所属 MR
目标
上位契约
允许修改范围
禁止修改范围
具体实现任务
测试要求
验收门禁
提交要求
回传格式
```

统一要求：

1. 默认一个 W 一个 feature branch / worktree，不在 master 直接开发；同一 D 可由多个 W 依 Gate 合并。
2. 先测试后实现；至少先写该 W 新增契约测试、unit test 或 Golden fixture。
3. 不得“顺手”实现下一阶段功能。
4. 不得复制 `statebar-mcp`、心潮、OB、MemoraX 的目录结构进入新仓库。
5. 可以参考旧项目行为，但新代码必须服从 Mind Runtime Domain Contract。
6. 任何跨步骤 Contract 变化必须 ADR；禁止在实现代码中悄悄改变语义。
7. 每个 W 完成后独立 Review；D Gate 再做一次集成 Review。Review 只依据当前工单和 Kernel Baseline，不以“以后会补”作为放行理由。
8. 每个 W merge 前要求：目标测试通过、全量已有测试不回归、worktree clean、无未解释 TODO/skip。

推荐提交粒度：

```text
1. contract/test
2. minimal implementation
3. hardening / edge cases
4. docs / ADR（若有）
```

禁止用一个巨型 commit 完成整个步骤。

---

# 2. D0 — Repository Bootstrap / 执行基线建立

## 派单表

|字段|内容|
|---|---|
|任务编号|`MR-D0-BOOTSTRAP`|
|所属阶段|准备阶段|
|核心目标|建立独立 `mind-runtime` 仓库和所有后续步骤共用的工程门禁|
|前置条件|V0.1.4 Kernel Baseline 已冻结|
|输入|Kernel Baseline、G1~G16 + G13b/G16b 定义、禁止事项|
|主要产物|仓库骨架、`AGENTS.md`、`docs/adr/`、测试入口、CI/lint/typecheck 配置、统一 Clock/Test fixtures 接口|
|不做|任何业务状态逻辑、任何心潮 12 维迁移、任何 OB 写入|

### W 拆分

|W|任务|Merge Gate|
|---|---|---|
|D0.1|仓库/package/测试命令 bootstrap|空环境 install + test collect|
|D0.2|AGENTS.md + ADR template|禁止事项/变更流程可见|
|D0.3|Clock/FakeClock + lint/typecheck CI|基础工具链全绿|
|D0.4|Kayla Legacy Rule Inventory 初始扫描|规则有 source location + legacy behavior|
|D0.5|README 产品边界/验证范围|Kayla first / Lara second / 溪月 consumer 写明|

### 具体任务

- 新建独立仓库 `mind-runtime`。
- 建立最小 Python package（首版推荐统一 Python；除非 ADR 另行决定）。
- 建立目录骨架，但只创建必要空 package，不预写未来业务：

```text
mind_runtime/
  interaction/
  observation/
  state/
  semantics/
  persona/
  appraisal/
  dynamics/
  motivation/
  policy/
  context/
  expression/
  history/
  trace/
  storage/
tests/
  contract/
  golden/
  unit/
docs/
  adr/
  legacy/
```

- 建立 `AGENTS.md`，复制 V0.1.3 的禁止事项与变更顺序。
- 建 `docs/adr/0000-template.md`。
- 建 `docs/legacy/kayla-rule-map.md`，开始扫描旧心潮/bridge/Prompt 中的 Kayla 行为与表达规则；每条必须记录来源位置与现有真实行为。
- 建测试命令、lint/typecheck 命令、coverage 基础配置。
- 建统一 `Clock` protocol 与 `FakeClock`，但不实现业务时间语义。
- README 只写产品边界和 Product Slice，不写未来功能宣传。
- README 明确 V0.x 验证范围：Kayla first，Lara second；溪月当前仅 Shared User State Consumer。

### 测试/验收

```text
import mind_runtime                PASS
pytest --collect-only              PASS
lint                               PASS
typecheck                          PASS
FakeClock basic contract           PASS
```

### Merge Gate

- master 上可从空环境复现安装与测试。
- `AGENTS.md` 明确：LLM 非状态权威、Projection 非 Canonical、MR-2 不写 Memory、V0.x 不拆微服务。
- 不允许出现 `xinchao/`, `statebar/`, `ob/`, `memorax/` 一级业务目录。

### 回传格式

```text
D0 RESULT
HEAD:
FILES CREATED:
TEST COMMANDS:
TEST RESULT:
KNOWN GAPS:
CONTRACT CHANGES: none / ADR-xxx
READY FOR D1: YES/NO
```

---

# 3. D1 — MR-0 Typed Kernel Contracts

## 派单表

|字段|内容|
|---|---|
|任务编号|`MR-D1-CONTRACTS`|
|所属阶段|MR-0|
|核心目标|把架构文档变成 typed contracts；此阶段仍然不做真实业务实现|
|前置条件|D0 merged|
|主要产物|核心 dataclass/Pydantic/protocol/enums、contract tests|
|原则|Contract 是下一阶段的边界；实现不能反向改变 Contract|

### W 拆分

|W|任务|Merge Gate|
|---|---|---|
|D1.1|Interaction / Scope / Authority / Ownership contracts|scope/owner contract tests|
|D1.2|Evidence / Observation / State / Transition contracts|immutable + authority semantics|
|D1.3|Projection / Checkpoint / Receipt contracts|candidate/commit schema frozen|
|D1.4|Situation / Appraisal / Pattern contracts|LLM 无 final affect 权限|
|D1.5|Persona / Dynamics / Motivation / Policy contracts|Trait/State、Want/Can 分离|
|D1.6|DecisionContext / Expression / Trace / Data Governance contracts|renderer/guard/security boundary|
|D1.7|ReplicationEnvelope/Port contract|协议存在但无 DDL|

### 必须冻结的 Contract

1. `Interaction / InteractionStatus`
2. `Scope / ScopeDomain`
3. `Authority / AuthorityLevel`
4. `Ownership / WritePolicy`
5. `Evidence`
6. `Observation`
7. `StateDefinition / RuntimeState`
8. `TransitionIntent / StateTransition`
9. `TurnProjection / ProjectedMindState`
10. `Situation`
11. `SemanticAppraisal`
12. `ResolvedAppraisal`
13. `AffectiveDimensionProfile`
14. `DynamicsPolicy` protocol
15. `Motivation`
16. `ActionIntent / ActionPermission`
17. `ActionPolicyResult`
18. `ExpressionGuardResult`
19. `DecisionContext`
20. `ReplicationEnvelope / ReplicationPort`
21. `TraceRef / EvidenceRef`
22. `AppraisalRouteDecision / AmbiguityAssessment`
23. `HistoricalContextQuery / HistoricalContextItem / HistoricalContextBundle`
24. `PatternQuery / PatternMatchSummary`
25. `TurnCheckpoint / ActionReceipt / DeliveryReceipt`
26. `DataSensitivity / RetentionClass / RedactionPolicy`

### 强制语义

- `Observation` immutable。
- `Evidence` 与 `Observation` 可在 turn failure 后保留。
- `TurnProjection != Canonical State`。
- `SemanticAppraisal` 不含最终 affect 数值。
- `ResolvedAppraisal` 可以含结构化 impulse，但不是直接数据库写操作。
- `Motivation != ActionPermission`。
- `ActionPolicy != ExpressionGuard`。
- 所有可同步对象必须携带 `scope + origin_runtime_id + event/object id + version/idempotency key`。

### Contract Tests

至少验证：

- 不合法 scope 无法构造/验证。
- Agent 私有 scope 能表达 owner。
- SemanticAppraisal schema 无 `current_value/final_affect` 字段。
- Projection 必须显式标记 `committed=False` 或等价语义。
- ReplicationEnvelope 不接受 projected state object type。
- immutable object 修改失败。

### 禁止事项

- 不实现数据库。
- 不实现 State Resolver。
- 不调用 LLM。
- 不实现 Kayla 参数。
- 不实现 MemoryCandidate。

### Merge Gate

`tests/contract/` 全绿；所有跨模块 import 方向固定；若 Contract 与 V0.1.3 不一致必须先 ADR。

---

# 4. D2 — MR-0.5 Golden Scenario Harness

## 派单表

|字段|内容|
|---|---|
|任务编号|`MR-D2-GOLDEN-HARNESS`|
|所属阶段|MR-0.5|
|核心目标|在业务实现前把 G1~G16 + G13b/G16b 变成可执行验收入口|
|前置条件|D1 merged|
|主要产物|Golden fixtures、scenario runner、fake clock、fake LLM、fake historical provider|

### W 拆分

|W|任务|Merge Gate|
|---|---|---|
|D2.1|Scenario schema + runner|同一 fixture 可 run/replay|
|D2.2|G1~G5 fixtures|状态/Policy 基础场景可收集|
|D2.3|G6~G10 fixtures|history/persona/replay 场景可收集|
|D2.4|G11~G16 fixtures|scope/projection/appraisal route 可收集|
|D2.5|G13b/G16b fixtures|双事务与真正歧义边界可收集|
|D2.6|xfail ownership CI check|每个 xfail 绑定未来 W|

### 具体任务

- 每个 G1~G16 以及 G13b/G16b 独立 scenario fixture。
- 每个 scenario 显式固定：

```text
clock
runtime_id
scope
persona
initial canonical state
historical context
input evidence
expected deterministic outputs
expected allowed LLM path
expected canonical changes
expected projected changes
```

- 对尚未实现的场景使用明确 `xfail(reason="MR-Dx/Wx not implemented")`，禁止 `skip` 无原因。
- CI 增加 xfail 审计：每个 xfail 必须绑定未来 D/W 编号，禁止无 owner 的永久 xfail。
- 建 Scenario Runner 支持：

```text
run once
replay same input
restart-from-persistence
compare deterministic result
```

- Fake LLM 必须记录 `call_count / prompt_type / structured_response`。

### Gate

- G1~G16 + G13b/G16b 全部可收集。
- 每个 xfail 都明确绑定未来 D3~D11 的任务号。
- 不允许测试自己实现业务逻辑来“模拟通过”。

---

# 4.5 D2S — MR-0.6 Vertical Walking Skeleton

## 派单表

|字段|内容|
|---|---|
|任务编号|`MR-D2S-WALKING-SKELETON`|
|核心目标|在真实算法实现前，用 typed stub 串通完整 Product Slice 生命周期|
|前置条件|D1/D2 merged|
|主要产物|Stub pipeline、FakeAgent、begin/commit/abort harness、trace/replay smoke tests|
|不做|真实 State 生命周期、真实 Dynamics、真实 Appraisal、真实 Kayla Policy|

### 必须串通

```text
begin_turn
→ ingest Evidence/Observation
→ factual read-your-writes
→ stub EffectiveState
→ stub Situation
→ stub Appraisal
→ stub Dynamics
→ stub Motivation
→ stub ActionPolicy
→ DecisionContext
→ FakeAgent
→ stub ExpressionGuard
→ ActionReceipt
→ commit_turn / abort_turn
→ inspect/trace/replay
```

### W 拆分

|W|任务|Merge Gate|
|---|---|---|
|D2S.1|Pipeline orchestrator + typed stub ports|所有 port 可注入 fake|
|D2S.2|ingest vs turn_commit skeleton|事实与心智 projection 两阶段可观察|
|D2S.3|FakeAgent + ActionReceipt skeleton|发送前后 stage 可区分|
|D2S.4|commit/abort/replay smoke tests|失败不污染 canonical fixture|

### Merge Gate

- 一条 scenario 可以从 `begin_turn()` 完整走到 `commit_turn()`。
- 另一条 scenario 在 FakeAgent 失败时走 `abort_turn()`。
- Trace 能按 interaction_id 还原每个阶段。
- 后续 D3~D10 只允许“替换 stub”，不得另造第二条 pipeline。

---

# 5. D3 — MR-1A Interaction / Evidence / Observation / Scope Authority

## 派单表

|字段|内容|
|---|---|
|任务编号|`MR-D3-FACT-INGEST`|
|所属阶段|MR-1A|
|核心目标|建立 Mind Runtime 的事实入口和 authority/scope 边界|
|前置条件|D2S merged|
|主要产物|InteractionCoordinator 基础、Evidence store、Observation ingest、idempotency、scope/authority validation|

### W 拆分

|W|任务|核心测试|
|---|---|---|
|D3.1|Interaction lifecycle / status|begin/processing/commit/abort 状态机|
|D3.2|Scope + Authority + Ownership gate|跨 persona 写入 fail-closed|
|D3.3|Evidence append-only + idempotency|重复 event 不重复写|
|D3.4|Observation immutable store|assistant output 不自污染|
|D3.5|Factual Plane classification/provenance|external fact 与 derived mind signal 分离|

### 具体任务

- 实现 `begin_interaction()` 基础对象创建。
- Evidence append-only 持久化。
- Observation append-only 持久化。
- `(scope, event_id)` 或冻结的 idempotency contract 生效。
- `occurred_at` 与 `received_at` 分离。
- Authority Validator：Assistant output 默认不能成为 user fact evidence。
- Ownership Validator：禁止 Lara runtime 写 `agent:kayla.*`。
- 为后续 replay 保存最小 provenance。

### 数据表首批

```text
interactions
evidence
observations
```

### 必须通过的 Golden 子集

- G8 Assistant 自污染防护。
- G9 delayed event 基础排序信息完整（此步不要求完整 reconcile）。
- G11 Scope 基础隔离。
- G15 Ownership fail-closed 的 ingest 部分。

### 禁止事项

- 不产生 affect。
- 不产生 Situation。
- 不做 LLM semantic extraction，除非使用 Fake/Stub 验证接口；首批 typed Observation 可以由 fixture 直接输入。

### Merge Gate

同一 Evidence 重放不产生重复 Observation；非法 owner 写操作 fail closed；原始事实可独立审计。

---

# 6. D4 — MR-1B Canonical State / EffectiveStateResolver

## 派单表

|字段|内容|
|---|---|
|任务编号|`MR-D4-EFFECTIVE-STATE`|
|所属阶段|MR-1B|
|核心目标|把 Statebar 已验证的状态 primitive 用新 Contract 重实现，建立唯一当前状态权威|
|前置条件|D3 merged|
|主要产物|Factual Reconciler、StateTransition、Lifecycle、EffectiveStateResolver、Current-turn factual overlay|

### W 拆分

|W|任务|关键 Gate|
|---|---|---|
|D4.1|RuntimeState + lifecycle enums|current-like/terminal 定义固定|
|D4.2|TTL / validity resolver|ACTIVE/IMPROVING 可到期|
|D4.3|reaffirm temporal envelope refresh|G2|
|D4.4|semantic supersession / explicit terminal transitions|单一 effective state|
|D4.5|delayed observation anti-rollback|G9|
|D4.6|lifecycle vs relevance separation|G3|
|D4.7|EffectiveState authoritative read gate|禁止 raw active 旁路|
|D4.8|factual overlay + ingest commit read-your-writes|G13b 前置语义|
|D4.9|D4 regression closure|Statebar 已验证 primitive 测试迁移完成|

### 具体任务

- 建 `states / state_transitions / state_definitions`。
- Reconciler 只消费有效状态视图，不直接按 raw `status` 做“当前状态”判断。
- 支持：
  - categorical supersession
  - explicit resolve/cancel/complete
  - TTL expiration for CURRENT_LIKE
  - reaffirm temporal envelope refresh
  - delayed observation anti-rollback
- terminal 状态永不被时间改写成 expired。
- `relevant_until` 与 lifecycle 分离。
- current-turn factual overlay：本轮刚确认的 user fact 在同一 turn 即时可见。
- Clock 全部注入，禁止业务代码直接调用系统时间。

### 必须通过

- G2 reaffirm。
- G3 cancelled != expired。
- G8。
- G9 delayed event。
- Statebar 对应的核心 lifecycle regression tests 迁成新 Domain test，但不得复制旧 schema。

### 特别审计点

Reviewer 必须 grep/检查：业务模块是否还有直接 `store.get_states()` + 自己筛 active 的路径。如果存在，拒绝 merge。

### Merge Gate

系统只有一个 `EffectiveStateResolver` 权威入口；terminal/relevance/validity 三维不混淆；fake clock replay 一致。

---

# 7. D5 — MR-1C TurnProjection / Commit Boundary / Checkpoint / Receipt / Trace

## 派单表

|字段|内容|
|---|---|
|任务编号|`MR-D5-PROJECTION-COMMIT`|
|所属阶段|MR-1C|
|核心目标|建立“已发生事实”和“本轮推导心智变化”的事务边界|
|前置条件|D4 merged|
|主要产物|TransitionIntent、TurnProjection、commit/abort、UnitOfWork、Trace、TurnCheckpoint、ActionReceipt/DeliveryReceipt、Replication Protocol Harness|

### W 拆分

|W|任务|核心测试|
|---|---|---|
|D5.1|TransitionIntent `commit_phase`|`ingest` vs `turn_commit` contract|
|D5.2|TurnProjection / ProjectedMindState|Projection != Canonical|
|D5.3|UnitOfWork commit / abort|G13 + G13b|
|D5.4|TurnCheckpoint state machine|processing/dispatching/awaiting_commit 可恢复|
|D5.5|ActionReceipt / DeliveryReceipt|已 dispatch 未 commit 可 reconcile|
|D5.6|Trace / replay|interaction_id 可还原因果链|
|D5.7|ReplicationEnvelope + Null/InMemory harness|G15；不建物理 outbox/inbox 表|

### 核心事务规则

```text
Evidence / Observation
= 已发生事实，可先 durable

Canonical factual state
= 根据事实 reconcile，可 durable

Derived agent affect / relationship transition
= begin_turn 中只 Projection

commit_turn()
= 才能提升为 Canonical Mind Transition
```

### 具体任务

- `TurnProjection` 带 interaction_id / source state version / intents / projected state。
- `commit_turn(projection_id)` 做 optimistic/staleness validation。
- `abort_turn()` 不提交 projected affect/relationship。
- Trace 能串起 Evidence → Observation → State → Intent → Projection。
- 不建 `replication_outbox / replication_inbox` 物理表；仅实现 `ReplicationEnvelope / ReplicationPort` 与 Null/InMemory harness。
- `TurnCheckpoint` 必须记录 interaction_id、stage、base_state_version、projection ref/digest、action_id、delivery_status。
- `ActionReceipt / DeliveryReceipt` 必须支持 idempotency/reconcile，区分未发送、已发送、发送状态未知。
- Replication payload allowlist：Evidence/Observation/Committed fact events；拒绝 projected state。

### 必须通过

- G10 Replay。
- G13 Projection failure 不污染 Canonical。
- G13b ingest 已提交事实在 cognitive abort 后仍保留。
- G15 Replication Ownership + projected reject。
- Restart 后未提交 Projection 不得被当 committed。
- Restart 遇到已 dispatch + receipt 的 turn 必须 reconcile 完成；unknown delivery 不得静默 abort。

### Merge Gate

Agent/Relationship derived state 在 begin_turn 阶段没有任何旁路写 canonical 的路径；外部事实 ingest commit 与 Mind turn commit 的边界、以及外部 action side effect 的恢复语义都有自动测试。

---

# 8. D6 — MR-2A Situation / Temporal Semantics / Derived Facts

## 派单表

|字段|内容|
|---|---|
|任务编号|`MR-D6-SITUATION`|
|所属阶段|MR-2A|
|核心目标|让 Runtime 第一次从“状态列表”升级成“现在是什么情境”|
|前置条件|D5 merged|
|主要产物|SituationBuilder、TemporalSemantics、DerivedFact rules|

### W 拆分

|W|任务|核心测试|
|---|---|---|
|D6.1|TemporalSemantics/daypart|固定 Clock 下可 replay|
|D6.2|recently_awake / engagement|G1|
|D6.3|cooldown / resource derived facts|G16 deterministic path inputs|
|D6.4|SituationBuilder aggregation|raw facts 不直接 dump 给 Agent|

### 第一批 Derived Facts

只实现真实产品必需的：

```text
time.daypart
user.recently_awake
conversation.active
conversation.idle
proactive.cooldown_ready
media.photo_budget_state
media.photo_frequency_eligible
recent_interaction_recency
```

### 原则

- 能由 clock/state/counter 确定的全部纯代码。
- Derived Fact 不写成 Canonical user fact；默认属于 Situation projection。
- `02:30 + recently_awake + active conversation` 不得推导“应该睡觉”。
- Situation Builder 输入只允许 Effective State + Interaction + Clock +明确 counters。

### 必须通过

- G1 deterministic situation 部分。
- G16 cooldown 不调用 LLM。

### 禁止事项

- 不实现人格情绪。
- 不做模糊语言意义判断。
- 不把 derived fact 落成长期 Memory。

### Merge Gate

相同 inputs + FakeClock → Situation 完全可 replay。

---

# 9. D7 — MR-2B Persona / Dynamic Dimensions / Dynamics Engine

## 派单表

|字段|内容|
|---|---|
|任务编号|`MR-D7-DYNAMICS`|
|所属阶段|MR-2B|
|核心目标|把“心潮 12 维思想”提升为可配置 Dynamic Persona，而不是复制固定 12 维|
|前置条件|D6 merged|
|主要产物|PersonaProfile、AffectiveDimensionDefinition/Profile、DynamicsEngine、首批 policies|

### W 拆分

|W|任务|核心测试|
|---|---|---|
|D7.1|Persona Trait/Profile models|Trait != Current State|
|D7.2|Dynamic Dimension registry|5/12/20/custom 可配置|
|D7.3|continuous_return_to_baseline|FakeClock 可 replay|
|D7.4|accumulator / event_only|慢变量与事件变量边界|
|D7.5|coupling + contribution trace|每个增量可解释且不越界|
|D7.6|Kayla compatibility profile fixture|参数在 config/fixture，不进入 kernel schema|

### 必须实现的 Dynamics Policy

```text
continuous_return_to_baseline
accumulator
event_only
```

State factual lifecycle policy 已在 D4，不在此重复。

### Persona 模型要求

每个 affect dimension 至少支持：

```text
key
baseline
initial_value
floor
ceiling
sensitivity
recovery_rate
optional coupling
```

- `current` 不存在 Persona Profile 里，只存在 runtime/projected state。
- 允许 5/12/20/custom 维。
- 提供 `kayla_v0` 测试 profile，但参数仅用于 fixture，不作为核心默认值。

### Dynamics 计算要求

输入：

```text
current projected/canonical affect
elapsed time
resolved appraisal impulses
persona profile
relationship modifiers（可先为 fixture/stub）
coupling
```

输出：`TransitionIntent[]` + 可解释 contribution trace。

### 测试

- baseline 回归。
- floor/ceiling。
- elapsed time 可重复。
- coupling 不产生越界。
- 同一 impulse 不同 persona sensitivity → 不同结果。

### Merge Gate

代码里不得出现“内核固定 12 个字段”；Reviewer 需要专门检查 schema / migration / renderer 是否偷偷固定 12 维。

---

# 10. D8 — MR-2C AppraisalRouter / HistoricalContextPort / Affect Projection

## 派单表

|字段|内容|
|---|---|
|任务编号|`MR-D8-APPRAISAL-HISTORY`|
|所属阶段|MR-2C|
|核心目标|实现 Situation + provider-neutral HistoricalContext → 语义意义 → ResolvedAppraisal → affect projection；继续禁止 Native Memory write|
|前置条件|D7 merged；D2S pipeline 持续全绿|
|主要产物|HistoricalContextPort、HistoricalContextCompiler、PatternQuery、AppraisalRouter、Semantic/ResolvedAppraisal、LLM semantic adapter、metrics|

### W 拆分

|W|任务|独立 Gate|
|---|---|---|
|D8.1|HistoricalContext contracts + provider-neutral adapter|无 OB/breath/hold 私有词泄漏|
|D8.2|Read-side Scope/Surface gate|不合 scope / policy 的历史不能进入 bundle|
|D8.3|PatternQuery / PatternMatchSummary|Provider 只返回历史事实|
|D8.4|Deterministic appraisal path|明确事件零 LLM|
|D8.5|Typed semantic mapping path|event × persona/relationship 参数化|
|D8.6|AppraisalRouter + AmbiguityAssessment|route/reason/score 可 trace|
|D8.7|LLM SemanticAppraisal adapter|只返回 meaning/valence/relevance/confidence|
|D8.8|ResolvedAppraisal + affect projection|数值由 Runtime Dynamics 计算|
|D8.9|Metrics + no-read-side-mutation assertions|retrieval/surface 不得 touch/reinforce provider|

### HistoricalContext read path

```text
HistoricalContextQuery
→ provider candidates
→ Scope / read policy gate
→ bounded HistoricalContextBundle
→ AppraisalRouter
```

MR-2 adapter 可以读取 OB / legacy memory / fixture；但：

```text
NO MemoryCandidate
NO Memory commit
NO consolidation
NO provider-native Appraisal verdict
NO touch/reinforce side effect on read
```

即使 legacy OB 的 read API 自带 activation/touch 语义，adapter 也必须选择无副作用路径或隔离副作用；第一 Product Slice 不允许因为“读历史”改变长期记忆权重。

### Appraisal 路由

```text
1. deterministic
2. typed semantic mapping
3. genuine ambiguity → LLM SemanticAppraisal
4. Runtime ResolvedAppraisal
5. DynamicsEngine → Projected Affect
```

LLM 允许返回：

```text
meaning
valence
relationship_relevance
confidence
```

禁止返回最终 affect 数值、State transition、write action。

### Metrics

至少：

```text
appraisal_path
ambiguity_score
route_reason_codes
llm_call_count
llm_latency
semantic_confidence
historical_items_considered
historical_items_surfaced
history_provider
history_read_mutation_detected   # 必须恒 false
```

### 必须通过

- G6 repeated historical context alters appraisal。
- G7 persona difference。
- G16 deterministic 不调 LLM。
- G16b 真歧义升级 LLM。
- G13/G13b affect 仍只 Projection，factual commit 不被 abort 回滚。
- provider read 不产生 reinforcement/touch side effect。

### Merge Gate

LLM 断开时 deterministic/typed 路径仍可运行；History provider 可替换；上层 Domain 不依赖 OB/Mem0 私有 schema；读取历史不会修改长期 memory 权重。

---

# 11. D9 — MR-3A Motivation / ActionPolicy

## 派单表

|字段|内容|
|---|---|
|任务编号|`MR-D9-BEHAVIOR-POLICY`|
|所属阶段|MR-3A|
|核心目标|把“想做什么”和“允许做什么”拆开，迁移 Kayla 行为级规则|
|前置条件|D8 merged|
|主要产物|MotivationEngine、ActionCandidate、ActionPolicy pipeline|

### W 拆分

|W|任务|核心测试|
|---|---|---|
|D9.1|Motivation model/engine|Affect != Action|
|D9.2|ActionCooldownPolicy|30m legacy mapping|
|D9.3|ConversationInterruptionPolicy|pending/current turn block|
|D9.4|MediaBudget/FrequencyPolicy|G5|
|D9.5|legacy action-rule closure|所有实现规则必须有 rule_id|

D9 开工前 `docs/legacy/kayla-rule-map.md` 中所有行为级规则必须已有 target contract 和 preserve/generalize/change/drop 决策。

### 第一批 Motivation

```text
contact_desire
share_desire
reassurance_desire
photo_share_desire
```

不要求成为最终通用 taxonomy；必须可配置扩展。

### 第一批 ActionPolicy

```text
ActionCooldownPolicy
ConversationInterruptionPolicy
MediaBudgetPolicy
MediaFrequencyPolicy
```

迁移 Kayla：

```text
drive/motivation threshold
30m proactive cooldown
currentTurn/pendingReply → no proactive interruption
每 N 条最多 1 图
每日图片上限
```

`settle=15m` 不作为 ActionPolicy；归 dynamics/tick scheduling。

### 必须通过

- G4 longing high + active conversation → motivation high but action blocked。
- G5 photo blocked but text action remains allowed。
- Policy result 必须有 machine-readable reason code。

### 禁止事项

- 禁用开头、前8字去重、凌晨晚霞，不得放在这里。
- Policy 不允许修改 affect state。

### Merge Gate

同一个 Motivation 可以因不同环境得到不同 ActionPermission；blocked 原因完整 trace。

---

# 12. D10 — MR-3B DecisionContext / Renderer / ExpressionGuard

## 派单表

|字段|内容|
|---|---|
|任务编号|`MR-D10-DECISION-EXPRESSION`|
|所属阶段|MR-3B|
|核心目标|形成 Agent 真正消费的统一 Context，并把表达后校验从 Prompt hack 提升为 Runtime guard|
|前置条件|D9 merged|
|主要产物|DecisionContextCompiler、ContextRenderer、ExpressionGuard chain、rewrite protocol|

### W 拆分

|W|任务|核心测试|
|---|---|---|
|D10.1|DecisionContextCompiler|不暴露 raw dump|
|D10.2|ContextRenderer|bounded、debug mode 隔离|
|D10.3|ForbiddenOpeningGuard|legacy rule ids|
|D10.4|PrefixDedupGuard|G14|
|D10.5|TemporalGroundingGuard|Situation 供事实、Guard 做最终校验|
|D10.6|rewrite protocol + retry cap|不回流 ActionPolicy|
|D10.7|legacy expression-rule closure|所有旧 Prompt 规则有明确处理结果|

### DecisionContext 必须至少包含

```text
situation
current_user_state
projected_agent_state
relationship_state/hints
resolved_appraisal
motivations
action_permissions
relevant_persona
external_historical_context（bounded）
```

禁止把原始 DB dump / OB raw result / Statebar snapshot 直接拼进去。

### 第一批 ExpressionGuard

```text
ForbiddenOpeningGuard
PrefixDedupGuard(prefix_len=8)
TemporalGroundingGuard
```

行为：

```text
accept
rewrite_required(reason)
reject
```

最多重写次数必须配置并 trace。

### Kayla 规则迁移

```text
禁用：刚忙完 / 刚闲下来 / 刚闲了 / 忙完了没 / 在干嘛
前8字硬去重
当前时间语境真实性（凌晨不写晚霞等明显冲突）
```

注意：时间语境由 Situation 提供事实，ExpressionGuard 负责最终输出校验。

### 必须通过

- G14 ActionPolicy allowed，但重复表达 → rewrite_required。
- ExpressionGuard rewrite 不得反向把 action 标记 policy denied。
- Renderer 不泄漏 internal raw numeric trace，除非 explicit debug mode。

### Merge Gate

业务约束不再只能依赖 prompt；LLM 输出不是最终可发送 action，必须过 guard。

---

# 13. D11 — MR-3C Kayla E2E / Product Slice 验收 / 灰度试运行

## 派单表

|字段|内容|
|---|---|
|任务编号|`MR-D11-KAYLA-E2E`|
|所属阶段|MR-3C|
|核心目标|把第一 Product Slice 接入真实 Kayla 环境，验证“连续状态→情境→情绪→行为”的产品价值|
|前置条件|D10 merged；G1~G16 + G13b/G16b 单项测试完成|
|主要产物|薄 Adapter、E2E harness、ShadowDiffReporter、灰度配置、metrics dashboard/log、回滚开关、retention/redaction 配置|

### W 拆分

|W|任务|核心测试/指标|
|---|---|---|
|D11.1|Kayla thin adapter + feature flag|旧/新可随时切换|
|D11.2|Shadow semantic normalizer|旧/new schema 转到可比语义|
|D11.3|ShadowDiffReporter|State/Situation/Behavior/Expression/Affect band diff|
|D11.4|Trace sampling/redaction/TTL|敏感数据不裸奔、数据量可控|
|D11.5|Appraisal route review corpus|建立 ambiguity 人工样本|
|D11.6|Phase A Shadow|不影响输出|
|D11.7|Phase B DecisionContext Assist|新 runtime 仅提供 context|
|D11.8|Phase C controlled takeover|可回滚|
|D11.9|D11 exit report|决定是否启动 MR-4/MR-5|

### 接入原则

- 不要求删掉旧心潮/OB/statebar；首轮用 feature flag / shadow / compare 模式。
- 第一 Product Slice 只验证 Kayla；Lara 为下一 companion profile。溪月只做共享 User State Consumer/Scope Authority 验证，不进入完整 affective E2E。
- Agent 对 Mind Runtime 只依赖薄接口：

```text
begin_turn
commit_turn
abort_turn
tick（若本阶段启用最小版）
inspect/trace（debug）
```

- Gateway/LLM provider 继续外部依赖。
- OB 首轮仅 Historical Context read-only。

### 推荐灰度模式

#### Phase A — Shadow

```text
旧系统正常回复
Mind Runtime 同步计算但不影响输出
```

`ShadowDiffReporter` 自动比较 state、situation、appraisal route、affect direction/band、behavior decision、expression constraint。禁止仅靠人工扫日志。

Shadow 必须支持 sampling、PII/relationship-sensitive redaction、trace retention TTL。

#### Phase B — DecisionContext Assist

Mind Runtime Context 参与回复，但主动行为仍由旧系统控制。

#### Phase C — Behavior Controlled

Mind Runtime Motivation + ActionPolicy 接管主动行为许可；旧系统保留 kill switch。

### 必须记录的真实指标

```text
1. stale-state incidence
2. wrong-state correction rate
3. appraisal_path distribution
4. appraisal LLM call rate / cost / latency
5. affect transition magnitude distribution
6. baseline return behavior
7. policy block rate + reason distribution
8. expression rewrite rate + reason
9. projection abort rate
10. replay mismatch rate
11. restart consistency
12. user-visible obvious-context-error count
```

### G1~G16 + G13b/G16b 最终 Gate

MR-3 release candidate 必须 G1~G16 + G13b/G16b 全绿；任何 xfail 都需 ADR 批准，否则不得称 Product Slice complete。

### 产品验收问题

试运行不是只看“没有 bug”，必须回答：

1. Kayla 是否比旧心潮更少出现时间/状态违和？
2. 同样事件在不同历史和 persona 条件下是否产生可感知差异？
3. affect 是否持续而非每轮重置？
4. motivation 是否能表达“想做但被 policy 阻止”？
5. debug trace 能否解释一次主动/不主动行为？
6. Appraisal LLM 成本是否在可接受范围？
7. Projection/Commit 是否在故障时保持 canonical consistency？

### Stop Gate

D11 完成后：

```text
STOP FEATURE DEVELOPMENT
```

至少完成一轮真实观察和复盘，才能开 MR-4 / MR-5。

---

# 14. MR-4 — OB-first Native Memory Continuity（条件式，不进入第一 Product Slice）

**正式实现仍然只能在 D11 Stop Gate 之后开启。** 但 R4 research 可在 D2S 后并行。

## 14.1 R4 — Source Research / RFC（可提前）

|Research W|产物|
|---|---|
|R4.1|OB 3.2 KEEP / REWRITE / REJECT / RESEARCH 矩阵|
|R4.2|Mem0 extraction/entity/temporal/retrieval differential matrix|
|R4.3|MemoraX turn/writeback/reconcile differential matrix|
|R4.4|中/葡/英真实 memory benchmark corpus + labels|
|R4.5|Memory Kernel RFC + provider decision criteria|

R4 不允许合并 Memory 业务代码。

## 14.2 D12 — Memory Kernel Contract Freeze

W：

```text
D12.1 MemoryRecord / MemoryCandidate
D12.2 Memory lifecycle + processing state separation
D12.3 MemoryRelation + provenance
D12.4 Retrieved/Surfaced/Activated/Used/Reinforced event semantics
D12.5 MemorySurfacePolicy contract
D12.6 Canonical-vs-Projection contract
D12.7 Verbatim Evidence / EvidenceRef boundary
D12.8 Event-ledger ADR（adopt/reject with evidence）
```

Gate：不能出现 OB API 名；backend/provider 未锁死。

## 14.3 D13 — Memory Golden + Benchmark Harness

W：

```text
D13.1 G17 passive surfacing != reinforce
D13.2 G18 index failure preserves canonical
D13.3 G19 similarity != causality
D13.4 G20 SurfacePolicy reason trace
D13.5 G21 verbatim evidence isolation
D13.6 G22 projection rebuild equivalence
D13.7 G23 backend swap contract
D13.8 multilingual retrieval benchmark runner
```

## 14.4 D14 — Admission / Canonical Commit

```text
Evidence / authoritative material
→ MemoryCandidate
→ AdmissionPolicy
→ Committed Memory
```

W：candidate extraction boundary、authority/scope validation、idempotency、dedupe identity、commit receipt、failure/replay tests。

禁止：LLM 直接 commit；index provider failure 影响 canonical transaction。

## 14.5 D15 — Derived Projection / Index Outbox

W：

```text
D15.1 ProjectionJob contract
D15.2 durable write-behind outbox
D15.3 embedding projection adapter
D15.4 lexical/BM25 projection adapter
D15.5 retry/backoff/circuit semantics
D15.6 projection rebuild command
D15.7 index poison-item isolation
```

目标：**canonical first, derived eventually consistent, indexes disposable/rebuildable**。

## 14.6 D16 — Surface / Activation / Reinforcement

W：

```text
D16.1 MemorySurfacePolicy
D16.2 SEARCH surfacing
D16.3 SPONTANEOUS surfacing
D16.4 REFLECTION candidate surfacing
D16.5 activation trace
D16.6 MemoryUsed detection
D16.7 ReinforcementPolicy
D16.8 self-amplification regression tests
```

核心 Gate：surface 100 次不能自动 reinforce 100 次。

## 14.7 D17 — Retrieval Benchmark / Engine Decision

候选至少比较：

```text
native OB-inspired retrieval
Mem0 provider
hybrid native canonical + external retrieval
```

指标：

```text
Recall@K / MRR / nDCG
exact entity/date recall
temporal current-vs-past accuracy
Chinese / Portuguese / mixed-language recall
false spontaneous surfacing rate
latency / token+LLM cost
provider outage degradation
scope leakage = 0
rebuildability
```

D17 结束才允许 ADR 锁定默认 Memory Engine/Provider。

## 14.8 D18 — Relation / Pattern Graph

W：

```text
D18.1 non-causal auto relation candidates
D18.2 same_event / continuation / related mapping
D18.3 causal relation authority gate
D18.4 algorithm_version + provenance
D18.5 over-link calibration + cap
D18.6 PatternQuery on relation/event history
D18.7 relation rebuild / rollback
```

禁止 similarity-only causal edge。

## 14.9 D19 — Reflection / Context Integration

分两条：

```text
A. HistoricalContextCompiler
   Memory candidates → SurfacePolicy → bounded bundle → Situation/Appraisal

B. Affective Residue experiment
   source memory + appraisal snapshot → reflection candidate
```

A 必做；B 必须通过单独实验 Gate 才能成为正式 Kernel capability，不能因为 OB 有 `feel` 就默认照搬。

## 14.10 D20 — Migration / Cutover / Recovery

W：

```text
D20.1 OB legacy read/migration mapper
D20.2 canonical backfill + EvidenceRefs
D20.3 derived projection rebuild
D20.4 replay/crash-recovery test
D20.5 dual-read shadow diff
D20.6 authoritative store cutover
D20.7 old writer disable / rollback plan
```

最终目标：OB/旧 Memory 只剩 migration/reference role，不能与新 Kernel 长期形成双 authoritative store。

### MR-4 强制原则

```text
MemoryCandidate ≠ Committed Memory
Canonical Memory ≠ Derived Index
Retrieved/Surfaced/Activated ≠ Reinforced
Memory Activation ≠ State Resurrection
SurfacePolicy before Cognition
Similarity ≠ Causality
Provider ≠ Domain Authority
```

---

# 15. MR-5 — Distributed Runtime（后续，契约已提前冻结）

Transport 后置，但 D1/D5 已经冻结对象和 schema。

建议拆为：

|后续步骤|目标|
|---|---|
|M5-1|Outbox publisher + retry|
|M5-2|Inbox consumer + idempotency|
|M5-3|Authority/Ownership/Scope apply gate|
|M5-4|multi-runtime convergence/replay tests|
|M5-5|Kayla/Lara/溪月真实跨机灰度|

禁止：

- 不同步 Projected State。
- 不做 SQLite 全量复制。
- 不先上 CRDT。
- Agent 私有 affect / relationship 继续单写者。

---

# 16. 依赖关系与并行规则

## 16.1 Implementation Gate

```text
D0 → D1 → D2 → D2S → D3 → D4 → D5 → D6 → D7 → D8 → D9 → D10 → D11
```

生产实现遵循 Gate，不允许跳过 D2S。

## 16.2 Prework Lane / R4 Research

后续 Gate 可提前进行无副作用预研；允许文档、fixture、truth table、benchmark、rule inventory、伪代码，不允许生产实现提前 merge。

## 16.3 审查独立性

D1 Contract 与 D2 Golden 可以处于同一 sprint 并行准备，但建议不同 PR/Gate review，不合并成一个“自己定义 contract 又自己一次性证明 contract 正确”的巨型 PR。

## 16.4 W 并行

同一 D 内只有在文件/契约互不冲突时允许 W 并行。例如 D10.3/D10.4 可并行写 pure guard + tests；D8.6 LLM adapter 可以在 D8.1 route contract merge 后与 D8.4 pattern adapter 并行。

---

# 17. 每步 Review 清单

Reviewer 每次至少回答：

```text
1. 是否严格在本工单 scope 内？
2. 是否修改上位 Contract？若是，ADR 在哪里？
3. 是否出现旧项目产品边界泄漏？
4. 是否新增 raw-state bypass？
5. 是否让 LLM 获得不该有的写权/数值权？
6. 是否混淆 Projection / Canonical？
7. 是否混淆 Motivation / ActionPolicy？
8. 是否混淆 ActionPolicy / ExpressionGuard？
9. 是否把 MR-4/MR-5 功能提前偷做？
10. 新增测试是否验证行为而不是验证实现细节？
11. FakeClock / replay 是否可重复？
12. 全量回归是否通过？
```

Review 输出只能是：

```text
READY_TO_MERGE
NOT_READY_TO_MERGE
```

若 NOT_READY，必须给 blocker + evidence，不接受模糊建议。

---

# 18. 每步开发 Agent 回传模板

```text
# TASK REPORT

Task:
Branch / Worktree:
Base HEAD:
Final HEAD:

## Implemented
- ...

## Contracts touched
- none / list + ADR

## Files changed
- ...

## Tests added
- ...

## Verification
Targeted:
Full suite:
Lint:
Typecheck:

## Golden scenarios affected
- Gx ...

## Explicitly not implemented
- ...

## Risks / known gaps
- ...

## Worktree status
clean / dirty

## Merge recommendation
READY_TO_MERGE / NOT_READY_TO_MERGE
```

---

# 19. 第一 Product Slice 完成定义

只有同时满足以下条件，才能宣布 `Mind Runtime V0.x Product Slice 1` 完成：

```text
[ ] D0~D11 全部 merge
[ ] G1~G16 + G13b/G16b 全绿
[ ] 无未解释 xfail/skip
[ ] Canonical/Projection 边界经过故障测试
[ ] State 只有一个 Effective Resolver 权威入口
[ ] Persona dimensions 非固定 12 维
[ ] deterministic appraisal 不依赖 LLM
[ ] LLM appraisal 无数值写权
[ ] Motivation / ActionPolicy / ExpressionGuard 三层分离
[ ] MR-2 无 Native Memory writeback
[ ] projected state 不进入 replication
[ ] Kayla shadow/灰度环境跑通
[ ] replay/restart consistency 有证据
[ ] metrics 可回答真实成本和行为分布
[ ] 完成一次试运行复盘 ADR/Report
```

不满足这些条件时，不因为“已经能聊天/能主动发消息”就宣称完成。

---

# 20. 最终执行纪律

> **MR 是架构阶段，D0~D11 才是实际派单单位。**

> **第一版本不是把 North Star 做完，而是把一条可解释、可回放、可提交的心智闭环做对。**

> **每一步都必须留下 Contract、Test、Trace 和 Merge Evidence；如果某个能力只能靠开发者记得“这里应该这样”，它就还没有产品化。**


# 21. W-level 真实派单模板

以后给开发 Agent 的实际 prompt 应只包含一个 W：

```text
TASK: D8.5 AppraisalRouter / AmbiguityAssessment

UPPER CONTRACT:
- V0.1.3 DECISION-015 / 020 / 025
- D8 Gate contract

GOAL:
- 实现 route decision，不实现 LLM semantic adapter 本身

ALLOWED:
- mind_runtime/appraisal/router.py
- mind_runtime/appraisal/models.py（仅既有 contract 允许的补充）
- tests/unit/appraisal/

FORBIDDEN:
- 修改 Dynamics 数值公式
- 写 Memory
- 修改 ActionPolicy
- 改 D1 frozen schema（除非 ADR）

TESTS:
- deterministic path
- typed_mapping path
- genuine ambiguity path
- trace reason codes

RETURN:
HEAD / commits / files / tests / known gaps / contract changes / READY FOR NEXT W
```

原则：**D 是 reviewer 的交付 Gate，W 才是 coding Agent 的任务边界。**
