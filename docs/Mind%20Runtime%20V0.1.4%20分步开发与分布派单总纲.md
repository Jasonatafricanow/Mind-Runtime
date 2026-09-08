# Mind Runtime V0.1.4 分步开发与分布派单总纲

> **D7R authority overlay (ADR-0004):**
> `docs/adr/0004-compress-cognitive-topology.md` and
> `docs/superpowers/specs/2026-08-22-d7r-compressed-runtime-and-agent-onboarding-design.md`
> are the active authorities. This overlay supersedes conflicting topology clauses in
> this V0.1.4 document. D3-D7 trust
> boundaries remain preserved; D8 production work is blocked until the D7R
> contract and Golden integration gate closes.

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
