# MR ARCHITECTURE LOCK v1.1

**Base HEAD:** `9dc8469` — `feat(c8b): C8B-R 黑箱还原完成`
**Branch:** `w/c7a-delivery-contract`
**Freeze Date:** 2026-09-01
**Supersedes:** MR-ARCH-LOCK-v1 (无正式文件，以 `docs/docs/MindRuntime_最终边界与开发总纲_2026-08-27.md` 为准)
**Authority Source Hierarchy:**
1. repo current code
2. tests / current runtime config
3. accepted ADR/spec
4. 《Mind Runtime 开发纠错核心哲学》
5. 《Mind Runtime 道级账本 v0》(research evidence boundary，非工程完成权威)
6. historical docs
7. chat report

> 《道级账本》是 research evidence boundary，不是 roadmap / engineering completion authority。
> 账本中的 `ACTIVE_SIGNAL`、`ARCHITECTURAL_CLUE`、`OPEN_QUESTION` 不得自动转换为工程任务或完成状态。

---

## 1. Product Ontology 产品本体冻结

### 正式定义

**Mind Runtime ≠ 以下任何一项：**
- 通用认知运行时（generic cognitive runtime）
- Agent 框架（Agent Framework）
- 第二套 Agent 操作系统（second Agent OS）

**Mind Runtime =**

> 一个以认知记忆为核心，能够因长期互动产生和保存内在情感、关系和经验内化变化，并可被携带、迁移和挂载到不同 Foundation Model / Agent Body 上，持续影响其理解、动机、判断与表达的情感 Harness。

### 核心产品问题

| 问题 | 含义 |
|------|------|
| 持续真实互动后，内部世界是否改变？ | Internalization 机制是否成立 |
| 内部世界改变后，是否在后续行为中持续产生可测影响？ | State→Decision→Body 因果链是否成立 |
| 更换 Body 后，这些变化是否仍可保留？ | Cross-Body Portability 是否成立 |

### MR 不是为了

> "让 Agent 更守规则"。

### MR 要验证的是

> "经历能否变成持续内在世界"。

### 五个永久校准问题

1. 它记住了什么？
2. 它感受到了什么？
3. 为什么这件经历让它发生变化？
4. 这个变化以后真的影响它了吗？
5. 换一个 Body，这些东西还能不能继续存在？

---

## 2. Soul / Body Authority Boundary

### Soul / MR owns

- identity continuity（身份连续性）
- cognitive memory（认知记忆）
- relationship continuity（关系连续性）
- appraisal（评估）
- affect（情感）
- slow dynamics（慢动力学）
- internalization（内化）
- learned values（习得价值）
- internalized rules（内化规则）
- sensitivities（敏感点）
- relationship expectations（关系期待）
- situation meaning（情境意义）
- motivation / intent tendency（动机/意图倾向）
- cognitive ActionPolicy（认知行为策略）
- DecisionContext / MindProjection（决策上下文/心灵投射）
- proactive desire / wake semantics（主动欲望/唤醒语义）

### Body / Agent Host owns

- current turn reasoning（当前轮次推理）
- final language generation（最终语言生成）
- planning（规划）
- tools（工具）
- tool permission（工具权限）
- tool execution（工具执行）
- carrier/channel selection（载体/通道选择）
- credentials（凭证）
- recipient addressing（接收方寻址）
- final execution safety（最终执行安全）
- real-world side effects（真实世界副作用）
- session / channel runtime（会话/通道运行时）
- execution responsibility（执行责任）

### 冻结

**Soul cognitive authority ≠ Body execution authority**

MR may say:
- "I want X"（我想做 X）
- "I believe X matters"（我认为 X 重要）
- "I would prefer X"（我更倾向于 X）
- "Cognitively X is allowed"（认知上允许 X）

Body still decides:
- "Can I actually execute X?"（我真的能执行 X 吗？）
- "How?"（怎么做？）
- "With which tool/channel?"（用什么工具/通道？）
- "Under which safety constraints?"（在什么安全约束下？）

### 强制约束

MR ActionPolicy **MUST NOT** silently become:
- Tool Safety Policy
- Carrier Policy
- Execution Permission System

---

## 3. Bipolar Loop 正极 / 负极模型

### 规范拓扑

```
WORLD
  ↓
Positive Pole / Perception Boundary（正极/感知边界）
  ↓
Statebar / Probes（外部感觉器官）
  ↓
Evidence / Observation / Effective State / Situation
  ↓
SOUL / MR
  ↓
MindProjection / Intent / Wake / DecisionContext
  ↓
Negative Pole / Feedback Boundary（负极/反馈边界）
  ↓
SSE / Adapter / Context Injection / IPC / HTTP bridge
  ↓
BODY
  ↓
Output / Tool / Action
  ↓
WORLD
  ↓（再次经过 Positive Pole）
```

### 正极（Positive Pole）

> Reality → Soul

### 负极（Negative Pole）

> Soul → Body

### 关键说明

- **Statebar = 外部感觉器官**。不是推理引擎，不是决策模块。
- **SSE / Adapter = Soul 对 Body 的作用通路**。是导线，不是主动意识来源。
- **SSE 是导线，不是主动意识来源。**

### 主动性归属

例如心潮（proactive intent）：
1. elapsed time（时间流逝）
2. affect / relationship / situation dynamics（情感/关系/情境动力学）
3. proactive intent（主动意图）
4. cognitive policy（认知策略）
5. WakeSignal（唤醒信号）
6. SSE（传导）
7. Body starts Agent turn（Body 开始执行）

**结论：主动性属于 Soul。执行属于 Body。**

---

## 4. Operational vs Experiential Feedback 双平面反馈分离

> **这是 v1.1 的关键修正。禁止把 Body execution acknowledgement 和 real experiential feedback 混为一谈。**

### 4A. Operational Feedback（操作反馈）

**定义：** Body 对某个 request 做了什么（操作层）。

**典型内容：**
- request accepted
- request rejected
- execution unknown
- tool call completed
- message transport acknowledged
- DeliveryReceipt settled

**用途：**
- handoff lifecycle
- retry/reconcile
- dedupe
- execution status
- operational counters

**它只证明：** "Body 对某个 request 做了什么。"

**它不自动证明：**
- 用户喜欢
- 用户生气
- 关系变好
- 行为值得强化
- Soul 应形成新的价值

### 4B. Experiential Feedback（经验反馈）

**必须路径：**
```
Body action
→ World
→ user/environment reaction
→ Statebar / Probe
→ Evidence
→ Appraisal
→ Affect / Relationship / Memory / Internalization
```

**禁止模式（v1.1 新增强制约束）：**

```
❌ Body says "send succeeded" → relationship reinforced
❌ settled DeliveryReceipt → affect reinforcement
```

除非出现**新的 authoritative external Evidence**，操作反馈不得进入情感/关系/记忆强化路径。

---

## 5. Authority Model 权威模型

### 权威来源等级（降序）

1. **New authoritative external Evidence** — 唯一合法的权威升级路径
2. **Deterministic elapsed-time dynamics** — 时间推进带来的确定性变化（如 decay、recovery）
3. **Explicit authority-bearing canonical commit** — 显式声明的权威提交

### 禁止自我授权

以下内部生成产物**不得仅因被检索、呈现、复述、投射、再次消费或存储为审计日志，就获得更多**：
- factual authority（事实权威）
- cognitive authority（认知权威）
- affective weight（情感权重）
- decision influence（决策影响）

### 禁止自我授权的具体边界

| 内部产物 | 禁止行为 |
|----------|----------|
| Body output | = Evidence |
| MR candidate | = Evidence |
| ShadowRunRecord | = Evidence |
| DecisionContext | = Canonical |
| Projection | = Canonical |
| Retrieved memory | = new Evidence |
| Operational receipt | = experiential Evidence |

**Authority escalation only via:**
- new authoritative external Evidence
- deterministic elapsed-time dynamics
- explicit authority-bearing canonical commit

---

## 6. Core Experience→Internalization Chain 核心因果链

> Architecture Lock **MUST NOT** reduce MR to: State → Intent → Policy → DecisionContext

### 规范 Soul 链

```
Experience（经历）
  ↓
Situation / Evidence（情境/证据）
  ↓
Appraisal（评估）
"这件事对用户、我和关系意味着什么？"
  ↓
Affect（情感）
  ↓
Relationship update（关系更新）
  ↓
Memory（记忆）
  ↓
Internalization（内化）
  ↓
learned values（习得价值）
internalized rules（内化规则）
sensitivities（敏感点）
expectations（期待）
behavioural bias（行为偏差）
  ↓
Future Situation（未来情境）
  ↓
context activation（上下文激活）
  ↓
Motivation / Intent / Decision Bias（动机/意图/决策偏差）
  ↓
MindProjection（心灵投射）
  ↓
Body expression / behaviour（Body 表达/行为）
```

### 关键声明

**Internalization 不是可选的、靠后的记忆功能。它是 MR 的核心机制。**

---

## 7. External vs Internalized Rules 外部规则 vs 内化规则

### 禁止冻结

- Rules outside MR（MR 外部的规则）
- Personality inside MR（"MR 内部人格"作为一个固定实体）

### 应冻结的区分

| 类型 | 定义 | 示例 |
|------|------|------|
| Hard Engineering Rule（硬工程规则） | 确定性安全机制，写入代码，无例外 | append-only 数据不可破坏性覆盖 |
| Internalized Affective Rule（内化情感规则） | 经历→情感后果→长期行为倾向 | 过去破坏用户重要数据→user reaction→appraisal→guilt/fear/relationship damage→future similar situations produce stronger confirmation/backup tendency |

### 共存原则

两者可以同时存在：
- **安全机制不替代心理内化**
- **心理内化不替代确定性安全机制**

---

## 8. Engineering Spine 工程主线 E1–E8

> 回答："MR 能否被安全、可靠、可观测地运行？"

---

### E1 — Perception Foundation（感知基础）

**ENTRY:** Clean evidence ingestion contract + canonical admission path
**GOAL:** Evidence → Observation → Effective State → Situation 可靠运行，含 authority、privacy、trace
**EXIT:** Evidence admit/reject/log 全部可观测；无 authority 泄漏；无 private data 泄漏
**FORBIDDEN:** Assistant output 直接成为 Evidence；Body 输出直接绕过 admission gate
**BLOCKING DEFECTS:** Authority boundary violation；private data leakage；admission bypass
**NON-BLOCKING DEBT:** Trace format 变更；命名规范

---

### E2 — Soul Runtime Foundation（灵魂运行时基础）

**ENTRY:** E1 完成 + Persona contract 冻结 + Relationship contract 冻结
**GOAL:** Appraisal、Dynamic、Affect、Intent、ActionPolicy、DecisionContext 全链路可运行
**EXIT:** 固定输入产生确定性 Appraisal；dynamics 可观测；无未声明的 LLM numeric affect authority
**FORBIDDEN:** LLM 直接写 numeric affect；Appraisal 旁路；Personality 硬编码为 12D
**BLOCKING DEFECTS:** Affect injection from LLM；Appraisal contract drift；Unowned dynamics
**NON-BLOCKING DEBT:** C3 production wiring（当前 effect_rules=()）；C4 Kayla fixture 替换

> **Important: Engineering existence ≠ causal mechanism proven.**

---

### E3 — Soul↔Body Handoff Foundation（灵魂-身体交接基础）

**ENTRY:** E2 完成 + DecisionContext compiler 冻结 + ExpressionGuard 冻结
**GOAL:** durable intent/action handoff、logical identity、outcome acknowledgement、replay、idempotency
**EXIT:** handoff 有唯一因果索引；失败原子性 abort；unknown delivery 有 reconcile 路径
**FORBIDDEN:** 平行认知流水线；MR 直接执行；未声明的 carrier authority
**BLOCKING DEFECTS:** Idempotency violation；crash-consistency violation；parallel cognition pipeline
**NON-BLOCKING DEBT:** C7D carrier adapter（无 Telegram/Weixin 实现，SOURCE_MISSING）

> **NO real carrier inside MR.**

---

### E4 — Shadow Infrastructure（影子基础设施）

#### E4A — SafeShadowRunner

**ENTRY:** E3 完成 + C8A shadow contract 冻结
**GOAL:** SafeShadowRunner wrapper + ShadowRunRecord 持久化
**EXIT:** C8B 黑箱还原完成，59 测试全绿
**STATUS:** ✅ **COMPLETE**（commit `9dc8469`）

#### E4B — Durable Audit/Restart

**ENTRY:** E4A 完成
**GOAL:** shadow run 持久化 + restart 恢复 + C8B-R 闭环
**EXIT:** orchestrator 生命周期 hardened；abord_turn 正确丢弃 projection
**STATUS:** ✅ **COMPLETE**

#### E4B-R — C8B-R Shadow Audit/Restart Closure

**ENTRY:** E4B 完成
**GOAL:** C8B-R final closure report
**EXIT:** C8B-R 报告已接受
**STATUS:** ✅ **COMPLETE**（commit `aed7cbc`）

#### E4C — Continuous Production Shadow

**ENTRY:** E4B-R 完成 + production Persona active + C8C contract 冻结
**GOAL:** 持续生产影子调用 + comparison corpus + metrics
**STATUS:** ⬜ **HOLD**（C8C contract 尚未冻结）

---

### E5 — Assist Mode（辅助模式）

**ENTRY:** E4B-R 完成 + DecisionContext compiler 可用 + C9 contract 冻结
**GOAL:** Body 读取 MR cognition（Situation、Intent、Policy、DecisionContext、Relationship/Affect relevance）
**EXIT:** MR cognition 正确传递给 Body；Body 保留决策/执行权威
**FORBIDDEN:** MR cognition 成为 Body 唯一决策来源；Body authority 被 MR override
**STATUS:** ⬜ **NOT STARTED**

---

### E6 — Controlled Cognitive Adoption（受控认知采纳）

**ENTRY:** E5 完成 + SSE/IPC/HTTP bridge 可用
**GOAL:** Body 正式接受选定的 Intent、Wake、Policy、DecisionContext 建议
**EXIT:** 采纳路径有 trace；拒绝路径有日志；SSE 可用但 MR 不执行
**STATUS:** ⬜ **NOT STARTED**

---

### E7 — Reliability Certification（可靠性认证）

**ENTRY:** E4B-R 完成 + production deployment
**GOAL:** restart、crash、replay、soak、authority leakage、self-authorization、Host/Soul inversion 全覆盖
**EXIT:** D11 product certification
**FORBIDDEN:** Authority escalation from internal artifact；Host/Soul inversion
**BLOCKING DEFECTS:**
- Authority violation
- Idempotency/crash-consistency violation
- Safety/core-contract violation

**NON-BLOCKING DEBT:** Naming debt；file size；documentation drift
**STATUS:** ⬜ **NOT STARTED**

---

### E8 — Native Memory Authority Completion（原生记忆权威完成）

**ENTRY:** D11 明确 GO + E7 完成 + Memory Kernel contract 冻结
**GOAL:** Evidence → MemoryCandidate → Admission → Committed Memory → Activation → HistoricalContext → Used/Reinforcement 全链路
**EXIT:** MR-owned canonical long-term memory authority becomes complete
**FORBIDDEN:** Host long-term memory 仍为 authoritative writer
**STATUS:** ⬜ **NOT STARTED**

> **This is NOT "memory first appears". It is: MR-owned canonical long-term memory authority becomes complete.**

---

## 9. Research Spine 研究主线 R1–R7

> 回答："我们做出来的东西到底是不是 MR 的核心机制？"
> **Do NOT infer research completion from engineering green.**

---

### R1 — Grounded Experience（立足经历）

**研究主张：** interaction role、Situation、现实条件可靠
**子类别：**
- System-development interaction（系统开发交互）
- Real relational interaction（真实关系交互）
- Mixed interaction（混合交互）

**禁止推断：**
- 用户说过的话 = 人格训练数据
- 开发期交互 = 真实情感经历

**当前状态：** partial（开发期数据已积累；真实情感交互数据边界待厘清）

---

### R2 — Situated Appraisal（情境化评估）

**研究主张：** 同样 interaction，仅现实 Situation 不同 → typed Appraisal 是否发生可解释变化？
**当前状态：** **OPEN**（生产 bridge 已知缺失；C2 阶段工程存在但 situated appraisal 因果效应未验证）

**必须从账本读取当前状态，不得假设完整。**

---

### R3 — Affective Dynamics（情感动力学）

**研究主张：** accumulation、decay、reinforcement、recovery、conflict、hysteresis、relationship specificity 成立
**特别关注：**
- many low-intensity events vs one high-intensity impulse（多低强度事件 vs 单高强度脉冲）
**当前状态：** partial/open（J8 确认 semantic provider 缺失时 S0→S1 delta = 0；dynamics 组件存在但生产 wiring 未完成）

---

### R4 — Internalization（内化）

**研究主张：** Experience → affective consequence → durable learned values/rules/sensitivities
**必须区分：**
- external prompt rule（外部提示规则）
- internalized rule（内化规则）
**当前状态:** **DEFERRED pending R5 causal bridge**（内化是因果链末端，依赖 R5 先成立）

---

### R5 — State→Decision Causal Bridge（状态→决策因果桥）

**研究主张（核心反事实）：**
```
same Body
+ same input
+ same Situation
+ same model
+ same sampling controls
+ only legal MR state differs
→ typed decision bias differs
```
**不能只看最终文本。**
**当前状态:** **OPEN**（配置耦合已有 bounded negative result；完整因果桥未验证）

---

### R6 — Decision→Body Influence（决策→Body 影响）

**研究主张：** MR state → appraisal/motivation → typed Intent/decision → Body input → systematic expression/behaviour effect
**禁止证据：** "文本看起来不一样" 不是充分证据
**当前状态:** **OPEN**

---

### R7 — Cross-Body Portability（跨身体可迁移性）

**前提：** single-Body causal chain（R5+R6）已成立
**研究主张：** same consolidated Soul state → Body A vs Body B → 应保留 relationship direction、learned values、affective tendencies、internalized rules；同时允许语言风格、表面推理风格、能力随 Body 改变
**当前状态:** **DEFERRED**（产品定义级 proof，依赖 R5+R6 先成立）

---

## 10. Engineering vs Research Status Model 工程/研究双栏模型

> 每个大模块必须双栏描述。禁止：pytest PASS → mechanism proven。

### 示例格式

| 模块 | Engineering Status | Research Status |
|------|-------------------|-----------------|
| State/Appraisal subsystem | contract exists / wired / tested | situated appraisal causal effect: **OPEN** |
| Affective Dynamics | dynamics engine exists | accumulation/decay/reinforcement: **partial/open** |
| Shadow Run | C8B-R ✅ complete | cognition mechanism proven: **NO** |

### 强制约束

| Engineering 证据 | 不能推断 Research 结论 |
|-----------------|---------------------|
| pytest PASS | mechanism proven |
| coverage 100% | affective mechanism proven |
| merge | research signal confirmed |
| Shadow divergence | Soul cognition validated |

**C8 只能提供：**
- production-safe measurement infrastructure
- comparison corpus
- rollout evidence

**C8 不能自动证明：** Affect / Internalization / Personality 成立。

---

## 11. Existing Asset Mapping 现有资产映射

### C-Phase 映射

| Phase | 名称 | Engineering Spine | Research Relevance | Engineering Status | Research Status | Authority Owner | Classification |
|-------|------|-------------------|-------------------|-------------------|----------------|-----------------|---------------|
| C0 | Recon | — | — | Completed | — | — | KEEP |
| C0.5 | Dirty Tree Fix | E1 | N/A | Completed | N/A | — | KEEP |
| C1 | Private Canonical Data Boundary | E1 | N/A | Completed（ADR-0011） | N/A | Runtime | KEEP |
| C1.5 | C1 Regression | E1 | N/A | Completed | N/A | — | KEEP |
| C2 | Real Learning Loop | E1 | R1 | Completed（ADR-0012, sync cursor 修复） | partial | Runtime | KEEP |
| C2.10 | C2 Full Audit | E1 | R1 | Completed | partial | Runtime | KEEP |
| C3 | Semantic EmotionalTransition Provider | E2 | R3 | **partial**（provider exists，effect_rules=() 生产 wiring 缺失） | partial/open | Provider | DEBT |
| C4A/B/C | Kayla Production Persona | E2 | R1 | partial（kayla_v0 fixture-only） | partial | Runtime | DEBT |
| C5A/B/C | Autonomous Proactive Runtime | E2 | R3 | ✅ Completed（CognitiveTicker，59 测试全绿） | partial | Runtime | KEEP |
| C6A/B | Legacy Rule Ownership | E2 | R3 | partial（settle 已知；angle repetition unowned） | partial | Runtime | DEBT |
| C7A | Delivery Contract | E3 | R6 | Completed | partial | Runtime | KEEP |
| C7B | DeliveryPort Protocol | E3 | R6 | Completed | N/A | Runtime | KEEP |
| C7C | SettledActionProjector | E3 | R6 | Completed | partial | Runtime | KEEP |
| C7C-R | C7C Review Fix | E3 | R6 | Completed | partial | Runtime | KEEP |
| C7C-R3 | ExternalMemoryAuthority | E3 | R6 | Completed（ADR-0006） | partial | Runtime | KEEP |
| C7D | Carrier Adapter | E3 | R6 | **BLOCKED**（SOURCE_MISSING，无 Telegram/Weixin 实现） | N/A | — | **OUT_OF_MR_SCOPE** |
| C8A | Phase A Shadow Contract | E4A | R5/R6 | Completed | partial | Runtime | KEEP |
| C8A-R | C8A Closure Report | E4A | R5/R6 | Completed | partial | Runtime | KEEP |
| C8B | SafeShadowRunner | E4A | R5/R6 | Completed | partial | Runtime | KEEP |
| C8B-R | C8B-R Black Box Restore | E4B | R5/R6 | ✅ COMPLETE（59 测试全绿） | partial | Runtime | KEEP |
| C8C | Continuous Production Shadow | E4C | R5/R6 | ⬜ **HOLD** | partial | Runtime | HOLD |
| C9 | DecisionContext Assist | E5 | R5/R6 | ⬜ NOT STARTED | OPEN | Runtime | KEEP |
| C10 | Phase C Behavior Controlled | E6 | R5/R6 | ⬜ NOT STARTED | OPEN | Runtime | KEEP |
| C11 | Live Recovery / Soak | E7 | R5/R6 | ⬜ NOT STARTED | OPEN | Runtime | KEEP |
| C12 | D11 Final Certification | E7 | ALL | ⬜ NOT STARTED | OPEN | Runtime | KEEP |
| D12–D20 | Native Memory | E8 | R1–R7 | ⬜ NOT STARTED | OPEN | Runtime | KEEP |
| O1–O5 | Distribution | — | — | ⬜ NOT STARTED | N/A | — | KEEP |
| PUB | Publication | — | — | ⬜ NOT STARTED | N/A | — | KEEP |

---

## 12. C7 Reinterpretation C7 重新诠释

### 核心重新诠释

> C7 durable mechanics primarily represent: Soul↔Body operational handoff + execution acknowledgement
> **NOT:** MR-owned carrier

### 按字段分类

| 字段/概念 | 当前分类 | 重新诠释 |
|-----------|----------|----------|
| DeliveryRequest | KEEP | Soul→Body operational request，Soul 有认知权但无执行权 |
| DeliveryReceipt | KEEP | Execution acknowledgement，不自动成为 experiential Evidence |
| DeliveryPort | KEEP（Protocol） | MR 定义接口，不持有实现；carrier 由 Body/Host 提供 |
| durable state | KEEP | Operational counters（last_proactive_at 等），非情感状态 |
| UNKNOWN delivery | KEEP | 操作层 reconcile 路径，非情感强化路径 |
| retry | KEEP | 操作层幂等重试，非情感重复强化 |
| kill switch | KEEP | Body execution safety，MR 只提供认知建议 |
| settled projection | REINTERPRET | settlement 只证明操作完成，不证明用户接受/关系强化 |
| frozen replay | KEEP | 操作层 replay，非情感层 replay |

### C7D 特殊处理

> C7D real Telegram/Weixin carrier should not remain MR blocker.

**源码证据：**
- `DeliveryPort` Protocol 有零个具体实现
- 无 Telegram、Weixin、WhatsApp 发送代码
- ADR-0014: `SOURCE_MISSING`，LEVEL 0 capability

**分类：**

```
C7D → OUT_OF_MR_SCOPE
     或
C7D → HOST_INTEGRATION_FUTURE
```

**不删除现有文档/代码。**

---

## 13. C8 Repositioning C8 重新定位

### 冻结定义

> C8 = Production Shadow Validation + Causal Measurement Infrastructure
> **NOT:** "证明 Soul 已经正确"

| Sub-phase | 角色 |
|-----------|------|
| C8A | contract/readiness audit |
| C8B | safe shadow execution |
| C8B-R | durable audit/restart closure ✅ |
| C8C | continuous production shadow + comparison corpus + metrics（HOLD） |

### ShadowRunRecord 冻结

- **audit only**
- **observability only**
- **rollout evidence only**
- **ZERO cognition authority**

### 强制约束

C8 不能自动证明：Affect / Internalization / Personality 成立。

---

## 14. Interaction Role Governance 交互角色治理

### 三种角色

| 角色 | 定义 | 例子 |
|------|------|------|
| A. System-development interaction | 系统开发/调试交互 | 测试对话、fixture 交互、开发者模拟 |
| B. Real relational / experiential interaction | 真实关系/经验交互 | 真实用户情感表达、真实关系事件 |
| C. Mixed | 混合 | 真实用户同时进行系统反馈和情感表达 |

### 混合交互处理

**禁止：** 机械丢弃所有开发期交互数据。

**示例：** "为什么把我的日记覆盖了，我很生气" 同时包含：
- 工程证据（系统行为 bug）
- 真实关系后果（情感伤害）

**未来提取/学习必须保留此区分：**

```
需求来源 ≠ 情感经历 ≠ 人格训练数据
```

---

## 15. Phase Gates 阶段门

### 每个工程阶段必须包含

| 字段 | 含义 |
|------|------|
| ENTRY | 进入该阶段的前置条件 |
| GOAL | 该阶段的目标 |
| EXIT | 退出该阶段的标准 |
| FORBIDDEN | 该阶段明确禁止的行为 |
| BLOCKING DEFECTS | 必须解决的阻塞缺陷 |
| NON-BLOCKING DEBT | 可记录的债务，不导致路线回滚 |

### 三种强制 STOP / REVIEW 触发器

1. **Authority violation**（权威违规）
2. **Idempotency/crash-consistency violation**（幂等性/崩溃一致性违规）
3. **Safety/core-contract violation**（安全/核心契约违规）

### 非阻塞债务（不导致路线振荡）

- Naming debt（命名债务）
- File size（文件大小）
- Old helper（旧辅助函数）
- Documentation drift（文档漂移）
- Non-critical wiring（次要 wiring）

### Research 负面结果处理

> **VALID_NEGATIVE 只更新它覆盖的具体主张。它不会自动将工程路线回滚。**

---

## 16. Development Ticket Gate 开发工单门控

### 每个未来实现工单必须回答

```
ENGINEERING PHASE: E1–E8?
RESEARCH CLAIM:    Which R1–R7 claim, if any?
LOCATION:          Positive / Soul / Negative / Body?
AUTHORITY OWNER:   Who owns final authority?
EXECUTION CHECK:   Does this accidentally give MR Body power?
FEEDBACK CHECK:    Is operational acknowledgement being confused with experiential Evidence?
SELF-AUTHORIZATION CHECK: Can an internal artifact increase its own authority?
INTERNALIZATION CHECK: Does this change experience→internalization semantics?
EXIT CRITERION:    Which exact Engineering exit criterion does this close?
```

**如果以上全部为"无"：DO NOT IMPLEMENT。**

---

## 17. Final Product Proof 最终产品证明

### 不能仅定义为

> "P6 engineering certification passed."

### 最终产品证明需要两者

**ENGINEERING（工程）：**
稳定、安全、可迁移的 harness

**RESEARCH（研究）：**
可信因果证据，证明：
```
experience
→ internal state
→ internalization
→ future decision/expression
```

最终：
```
cross-body continuity（跨身体连续性）
```

### 五个永久校准问题

1. 它记住了什么？
2. 它感受到了什么？
3. 为什么这件经历让它发生变化？
4. 这个变化以后真的影响它了吗？
5. 换一个 Body，这些东西还能不能继续存在？

---

## 18. Anti-Oscillation 防止振荡

### 两种必须防止的跑偏

| 跑偏类型 | 定义 |
|----------|------|
| A | 把 MR 做成 Agent Framework / generic cognitive OS |
| B | 把工程闭环误认为 Soul / affective mechanism 已经成立 |

### 强制约束

| 约束 | 状态 |
|------|------|
| Internalization 是 MR 第一等概念 | **必须是** |
| Cross-body portability 是最终产品声明 | **必须是** |
| engineering PASS ≠ mechanism proven | **必须是** |
| Body 保留执行权威 | **必须是** |
| Experiential feedback 重新进入正极感知边界 | **必须是** |
| 历史工程交互不自动成为人格数据 | **必须是** |
| State→Decision→Body 仍为 open causal question | **必须是** |
| Situated appraisal 在账本声明处标记为 unproven | **必须是** |

---

## 19. Scope Freeze 范围冻结

### MR 不扩展到

- Agent Framework（Agent 框架）
- Planner（规划器）
- Workflow Engine（工作流引擎）
- Tool Router（工具路由器）
- Browser Agent（浏览器 Agent）
- Coding Agent（编码 Agent）
- Task Manager（任务管理器）
- Full Agent Orchestrator（完整 Agent 编排器）
- Model Gateway（模型网关）
- Carrier Platform（载体平台）
- Runtime Mesh（运行时网格）
- Control Plane（控制平面）
- Cloud Sync（云同步）
- Message Bus（消息总线）
- Multi-Agent Framework（多 Agent 框架）
- Persona Marketplace（人格市场）

### 例外条件

> minimal harness component is allowed **ONLY** if necessary for:
> - perception → Soul → projection
> **AND**
> it does not steal Body authority.

---

## 20. Current Position 当前状态

> **Do not assume status. Verify repo evidence.**

### Engineering Spine

| Phase | Status | Evidence |
|-------|--------|----------|
| E1 Perception Foundation | ✅ partial | C2 completed（ADR-0012）；C0.5 dirty tree fixed；1533 tests passing |
| E2 Soul Runtime Foundation | ✅ partial | C5B completed（CognitiveTicker）；C7A/B/C completed；C3 partial（effect_rules=()） |
| E3 Soul↔Body Handoff | ✅ foundation | C7A/B/C/R/R3 completed；C7D BLOCKED（SOURCE_MISSING） |
| E4A SafeShadowRunner | ✅ COMPLETE | C8B committed（`9dc8469`） |
| E4B Durable Audit/Restart | ✅ COMPLETE | C8B-R committed |
| E4B-R C8B-R Closure | ✅ COMPLETE | C8B-R report accepted |
| E4C Continuous Shadow | ⬜ **HOLD** | C8C not frozen |
| E5 Assist Mode | ⬜ NOT STARTED | C9 not started |
| E6 Controlled Adoption | ⬜ NOT STARTED | C10 not started |
| E7 Reliability Certification | ⬜ NOT STARTED | C11 not started |
| E8 Native Memory | ⬜ NOT STARTED | D12 not started |

### Research Spine

| Claim | Current Status | Evidence |
|-------|----------------|----------|
| R1 Grounded Experience | partial | Shadow corpus exists；real relational boundary unclear |
| R2 Situated Appraisal | **OPEN** | Production bridge absent；C2 engineering complete but situated effect unproven |
| R3 Affective Dynamics | partial/open | J8 confirmed semantic provider wiring missing → S0→S1 delta = 0 |
| R4 Internalization | **DEFERRED** | Pending R5 causal bridge |
| R5 State→Decision | **OPEN** | Some configured coupling has bounded negative result；complete causal bridge unverified |
| R6 Decision→Body | **OPEN** | Systematic expression effect unproven |
| R7 Cross-Body Portability | **DEFERRED** | Product-level experiment，pending R5+R6 |

---

## 21. Scope Violation Audit 静态范围审计

### 审计结果

| 类别 | 结果 | 证据 |
|------|------|------|
| Real Telegram send | **NO_VIOLATION** | 无 Telegram 发送代码 |
| Real Weixin/WeChat send | **NO_VIOLATION** | 无微信发送代码 |
| Real WhatsApp send | **NO_VIOLATION** | 无 WhatsApp 发送代码 |
| Carrier credentials | **NO_VIOLATION** | API key 通过环境变量传入，无硬编码 |
| Recipient ownership | **NO_VIOLATION** | `OwnershipValidator` 在 `facts/validators.py` 正确执行 |
| Tool executor | **NO_VIOLATION** | `FakeAgent` 为测试 double；`StubExpressionCoordinator` 为默认实现 |
| Browser executor | **NO_VIOLATION** | 无浏览器自动化代码 |
| Real carrier DeliveryPort | **NO_VIOLATION** | `NoopDeliveryReconciler` 为默认；零个 Protocol 实现 |
| Body output → Evidence | **NO_VIOLATION** | `RealLLMBodyAgent` 仅用于 LLM 推理；所有 evidence 经 `FactIngestService` |
| DeliveryReceipt → Affect | **NO_VIOLATION** | `SettledActionProjector` 只写 operational counters |
| DeliveryReceipt → Relationship | **NO_VIOLATION** | 无代码将 DeliveryReceipt 写入关系存储 |
| DeliveryReceipt → Memory | **NO_VIOLATION** | `ExternalMemoryAuthority` 与 delivery reconciliation 分离 |
| ShadowRunRecord → Cognition | **NO_VIOLATION** | SHADOW-5: "ShadowRunRecord has zero cognitive authority" |
| MR proactive → direct user side effect | **NO_VIOLATION** | `ActionPolicyPort` 需要显式 ALLOW；主动冷却通过 observation 执行 |
| Source bridge authority | **NO_VIOLATION** | `HermesProductionBridge` 拒绝 assistant-role records（line 281-296） |

**总体结论：NO_VIOLATION across all 15 categories.**

---

## 22. Self-Review Checklist 自我审查清单

### A. MR 被误读为通用认知 OS？
**答案：** 否。本文档第 1 节明确定义 MR ≠ generic cognitive runtime；第 19 节列出显式 scope freeze。

### B. C7 操作收据被误解为情感反馈？
**答案：** 否。第 4 节明确分离操作反馈与经验反馈；第 5 节禁止 DeliveryReceipt → Affect。

### C. 工程 PASS 被误解为机制证明？
**答案：** 否。第 10 节明确工程状态和研究状态必须双栏；第 8 节明确 Engineering existence ≠ causal mechanism proven。

### D. Internalization 是 MR 第一等概念？
**答案：** 是。第 6 节将 internalization 列为核心因果链的必要阶段，非可选记忆功能。

### E. Cross-body portability 保留为最终产品声明？
**答案：** 是。第 17 节和 R7 明确跨身体连续性是最终产品证明要求。

### F. Situated appraisal 在账本声明处标记为 unproven？
**答案：** 是。第 20 节 R2 状态为 OPEN；第 11 节 C3 research status 为 partial/open。

### G. State→Decision→Body 仍为 open causal question？
**答案：** 是。第 20 节 R5 状态为 OPEN。

### H. Body 保留执行权威？
**答案：** 是。第 2 节明确 Soul cognitive authority ≠ Body execution authority。

### I. Experiential feedback 重新进入正极感知边界？
**答案：** 是。第 3 节拓扑和第 4 节 4B 路径明确此要求。

### J. 历史工程交互不自动成为人格数据？
**答案：** 是。第 14 节 interaction role governance 明确三种角色区分和禁止规则。

---

## 23. Normative Source Hierarchy 规范性来源等级

1. **repo current code** — 最高权威
2. **tests / current runtime config** — 第二权威
3. **accepted ADR/spec** — 第三权威
4. **《Mind Runtime 开发纠错核心哲学》** — 指导原则
5. **《Mind Runtime 道级账本 v0》** — research evidence boundary，**非工程完成权威**
6. **historical docs** — 参考
7. **chat report** — 最低权威

### 道级账本状态保留

本文档显式保留账本当前边界：

| Signal | 状态 | 含义 |
|---------|------|------|
| MR-SIG-001 | local positive signal with confounds | 非完整机制证明 |
| MR-SIG-002 | local signal | 非持久内化证明 |
| MR-SIG-003 | component-level support | 非完整生产链 |
| MR-OPEN-001 | OPEN | 低强度积累问题开放 |
| MR-OPEN-002 | OPEN | situated appraisal 全机制开放 |
| MR-OPEN-003 | OPEN | state→decision→Body 核心开放 |
| MR-OPEN-004 | DEFERRED | affective rule internalization 待因果桥 |
| MR-OPEN-005 | DEFERRED | cross-body portability 待产品实验 |

**不得重新诠释账本状态。**

---

## RETURN

```
ARCH_LOCK_V1_1_READY_FOR_REVIEW
```

**Files Changed:** `docs/architecture/MR_ARCHITECTURE_LOCK_v1_1.md`（新建）
**Worktree:** `git status --short` 显示该文件为 `A`（新增）
**NO production code changes.**
**NO test modifications.**
**DO NOT IMPLEMENT C8C.**
