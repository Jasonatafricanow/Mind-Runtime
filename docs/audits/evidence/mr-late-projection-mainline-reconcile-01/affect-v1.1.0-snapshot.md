# MR-AFFECT-RUNTIME-CONTRACT-01: Disposition → Dynamics → Surface Affect Runtime Contract

> 这不是继续设计三层情绪，而是给现有 contract 做 R1 hardening。只解决四个 implementation blockers：PersonalityDisposition 的唯一 schema；Disposition 影响 Appraisal/Dynamics 的合法位置；Surface 上线后 Intent 的 raw-Dynamics 双重计权；Surface 上线后 Body 的 raw-Affect 双重解释。StateBar、Reality、LCE、Memory、OW Lab、shared semantic pass 均不扩展。

- **Document Version**: 1.1.0（取代 1.0.0 的冲突条款）
- **Date**: 2026-09-23
- **Status**: R1 CONTRACT HARDENED / ARCHITECTURE-ONLY
- **Authoritative Repository**: `C:/projects/mind-runtime-main-merge`
- **Branch / HEAD / origin/main**: `main` / `17772842aaffd44c4ff1a643e9fa4621fa9e6652` / 同 HEAD；远端只读核对一致。
- **Final Verdict**: `CONTRACT_ACCEPTABLE_FOR_IMPLEMENTATION`
- **Implementation evidence**: 本文新增 schema、Surface、迁移校验尚未生产实现；本裁决不是 GREEN、发布或部署批准。

## R1 Hardening Status

| Blocker | 冻结结果 | 定位 |
|---|---|---|
| R1-A Disposition schema | P2：唯一 PersonaProfile 下增加 behavioral_disposition；view 只读，无第二人格 authority | §3 |
| R1-B Appraisal influence | D1：accepted semantic payload 不变；单 projector 输出未乘 sensitivity 的 effects；DynamicsEngine 只乘一次 | §4 |
| R1-C Intent 去重 | I1 + schema A：保留 dimension_weights，增加 control_biases；静态 overlap 拒绝 + 运行时 snapshot 校验 | §6 |
| R1-D Body exposure | B1：SURFACE_V1 envelope 不暴露 raw affect 数值或其 bands；禁止旧 Host/style 路径重新补回 | §7 |

本版的“ACCEPT”表示 contract 裁决；所有数值例子均为 **CONTRACT EXAMPLE / EXPECTED TRACE / ACCEPTANCE SCENARIO**。后续必须 RED → implementation → GREEN → production-shaped causal test，不能引用本文作为 production proof。

## 0. 保留的冻结边界

```text
Reality / StateBar → Situation → Semantic Appraisal → Soul-owned Dynamics
  → Surface → Intent → ActionPolicy → DecisionContext → Body / Guard
```

Reality ≠ Appraisal；Appraisal ≠ Affect；Affect ≠ Intent；Intent ≠ Permission。LLM 只 understand/propose，runtime 才 accept/project/mutate。Surface 不执行 action，不决定 permission。ActionPolicy 和 ExpressionGuard 的现有职责不变。本文不重新设计事实 admission、历史存储、人格学习或外部集成。

ADR-0027 的唯一 AppraisalProjector ownership 按本次任务冻结。代码事实需另列：本地 main 的 ADR-0027 文件头仍为 PROPOSED；本仓库 `7780bdc` 已有 ACCEPTED 修订，W1 位于未合入分支。不能据本文说 main 已实现该 projector。本轮不改 ADR、不搬运 W1；正式生产 W 仍须按仓库 ADR → Contract/Golden → implementation 顺序集成 prerequisite，并保留唯一 owner。这里是集成前提，不是需要第二个架构决定。

## 1. 当前代码事实与纠正

以下路径相对于本页声明的权威仓库，行号固定于审计 HEAD。

| 当前位置 | 已有事实 | 本版不得误称 |
|---|---|---|
| `src/mind_runtime/dynamics/persona.py:15` PersonaProfile | persona_id、dimensions、version，immutable trait container | 当前已有四个 behavioral 字段 |
| `src/mind_runtime/contracts/affect.py:9` AffectiveDimensionProfile | baseline/initial_value/sensitivity/recovery/floor/ceiling/growth/coupling | 各维度都要再塞一份 attachment/restraint |
| `src/mind_runtime/persona_config.py:55` load_persona_profile | profile_version 目前只接受 1，并复制为 PersonaProfile.version | 当前格式已经区分 schema version 与内容 revision |
| `configs/personas/kayla.json` | 10 个 affect 维度；calibration_status=PROVISIONAL；没有 behavioral_disposition | 每一维都已有真实 Surface consumer；已有 personality calibration |
| `src/mind_runtime/emotional_transition/effects.py:112` EffectMapper.map | event impulse = base_amount × candidate.confidence；另带 appraisal.salience 给 gate；Slow absolute target verbatim | Fast 当前公式有 salience 乘数；EffectMapper 已经 delegate |
| `src/mind_runtime/dynamics/engine.py:85` DynamicsEngine.step | impulse.amount × profile.sensitivity，然后 coupling/clamp；恢复独立 | projector 可再乘同一 sensitivity |
| `src/mind_runtime/emotional_transition/appraisal.py:223,282` | Configured model 未按 behavioral traits 计算；model-backed payload 传 persona dimension 名称 | 已有可验证的 behavioral disposition → semantic salience causal rule |
| `src/mind_runtime/intents/engine.py:33,109` | base + dimension weights + event bonus，clamp/threshold；同 kind rule 唯一 | 已有 control_biases/overlap detection |
| `src/mind_runtime/contracts/behavior.py:15` | IntentEngineInput 没有 Surface | Surface 已影响真实 Intent |
| `src/mind_runtime/expression/context.py:220,452` | compile 调 _affect_items，AffectExpressionRule 将 raw value 变成 INTERNAL_STATE band | 只删原始浮点就能阻止 raw affect 行为解释；band 也是旧路径 |
| `src/mind_runtime/expression/context.py:487,511` | 另有 raw Slow items 和 persona_style_constraints | 新 Surface 加进去就自动替换旧影响 |
| `src/mind_runtime/host/runtime_adapter.py:189` | Host 自行拼 intent/Slow summary，未完整转发 Compiler items | Compiler GREEN 就等于外层 BODY 收到 Surface |
| `src/mind_runtime/cognition/tick.py` / `cognition/express.py` | tick、proactive expression 有独立 composition 入口，复用现有 engines | 只改 user-turn path 就完成主动行为迁移 |

现有 tests 已断言 confidence/sensitivity 各一次、raw dimension score、raw affect→band。它们是 migration 的兼容基线，不是 Surface 的验收证据。

## 2. 最终唯一架构与 ownership

```text
AcceptedAppraisal (immutable semantic authority)
       + PersonalityDispositionView (same PersonaProfile version)
       ↓
AppraisalProjector (ONE appraisal projection seam)
       ↓ AffectEffectProposal / AppraisalProjectionResult.effects
       ├─ FAST unscaled Impulse → DynamicsEngine
       │       ↓ agent.affect.* current projected vector
       │       │  canonical publication ONLY through existing commit/backend
       │       ↓
       │   SurfaceAffectProjector + PersonalityDispositionView
       │       ↓ AffectBehaviorControls (derived, same snapshot)
       │       ↓ IntentEngine → ActionPolicy
       │                          ↓ ALLOW only
       │                       DecisionContext → Body / Guard
       └─ LONGITUDINAL absolute target → HomeostasisGate → Slow writer
               ↓ Longitudinal / Relationship State (separate canonical class)
               └─ NO Surface V1 input

AcceptedAppraisal → bounded Semantic Meaning → DecisionContext (read-only)
Reality facts / bounded history → existing bounded DecisionContext inputs
```

Surface 可读取当前 turn 合法 projected Fast；尚未 commit 必须标 projected，不能说已 canonical。tick 也使用其同一次 Dynamics 结果。投影不要求先提交，不额外 step Dynamics。中止时不把 projected 状态/Surface 发布成 canonical。SurfaceAffectProjector 只将 state→controls，不接受 appraisal，不竞争 AppraisalProjector。

| Object | Authority | Persisted? | Writer | Consumer |
|---|---|---|---|---|
| AcceptedAppraisal | Semantic Appraisal authority | journal（ADR-0027 接入前提） | producer/admission；runtime journal | AppraisalProjector、bounded cognition |
| PersonaProfile | ONE Persona authority | config/versioned | explicit config author + validated loader | Dynamics、AppraisalProjector、Surface |
| PersonalityDispositionView | derived read view | no | none；从同一 profile 构造 | projector、Surface |
| Emotion Dynamics | canonical runtime | yes（commit 后） | DynamicsEngine 拥有 transition 数学；现有 orchestrator/backend 提交 | Surface、runtime/现有观测；legacy Intent |
| Longitudinal State | canonical slow runtime | yes | Slow writer + 既有 gate/commit | existing bounded consumers；不进入 Surface V1 |
| Surface Affect | derived | no independent state | deterministic SurfaceAffectProjector | Intent、DecisionContext |
| Intent | canonical lifecycle | yes（admission 后） | Intent engine/lifecycle | Policy |
| ActionPolicy | permission authority | decision record/现有 trace lifecycle | policy | downstream execution |

不把“数值计算 owner”和“SQL writer”混同；不建立新的 StateBackend、Disposition writer 或 Surface persistence authority。

## 3. R1-A：唯一 PersonalityDisposition schema

### 3.1 P1/P2/P3 裁决

| Option | Recommendation | Verdict | 理由 |
|---|---|---|---|
| P1 仅 dimension traits | DEFERRED（作为完整 Surface V1 方案）；保留 legacy 读取 | DEFER | 现有 traits 可以解释 Dynamics 差异，不能独立表达相同 Dynamics 下 attachment/restraint 的行为差异 |
| P2 PersonaProfile 内独立 behavioral_disposition | RECOMMENDED | ACCEPT | 唯一 owner 下增加四个静态 trait，不污染每个 dimension，不产生第二人格 |
| P3 独立人格 store/system | REJECTED | REJECT | 与 ONE Persona authority 冲突 |

### 3.2 规范 schema（拟议，不是当前 Python implementation）

```python
BehavioralDisposition:  # immutable, owned ONLY by PersonaProfile
    attachment_approach: float
    confrontation_readiness: float
    expressive_restraint: float
    expressive_warmth_bias: float

PersonaProfile:
    persona_id: str
    dimensions: tuple[AffectiveDimensionProfile, ...]  # unchanged
    version: int                                    # content revision
    behavioral_disposition: BehavioralDisposition | None = None

PersonalityDispositionView:  # immutable references/values from ONE profile
    persona_id: str
    persona_version: int
    affective_dimension_traits: tuple[AffectiveDimensionProfile, ...]
    behavioral_disposition: BehavioralDisposition | None
```

四个 behavioral 值均 finite、非 bool、[0,1]；不含 current state。attachment_approach 是趋近倾向，confrontation_readiness 是直面分歧倾向，expressive_restraint 是克制倾向，expressive_warmth_bias 是表达亲和基准。不得另增 threat_sensitivity/attachment_style aliases 或在 view 上自造默认心理参数。`trait.expressive_restraint` 与 `control.expressive_restraint` 必须带不同 typed namespace。

view 不持久化、不修改 profile、不拥有参数默认值、不接受第二份 override；跨 persona/version 混用失败。AppraisalProjector、DynamicsEngine 与 Surface 使用同一个 profile snapshot。View 中没有 current_value、学习率、运行时 mutation 或模型更新能力。

### 3.3 Serialization、version、defaults、missing

- **Canonical/config owner**：`dynamics/persona.py` 的 PersonaProfile；behavioral DTO 可放在已有 `contracts/affect.py`；唯一生产入口仍为 `persona_config.load_persona_profile()`。
- **位置**：`configs/personas/<id>.json` 根级 `behavioral_disposition`，与 `dimensions` 同级；不单建配置文件、DB 或 profile overlay。
- **格式/内容分离**：未来新格式增加 `schema_version: 2`；`profile_version` 是正整数内容 revision，映射 PersonaProfile.version。legacy 缺 schema_version 的现存 version-1 文件按 schema 1 解码，behavioral_disposition=None。schema 1 不接受新 behavioral 字段；未知 schema 拒绝。
- **显式迁移**：Kayla 将来迁移到 schema 2、profile_version=2；此后任一 trait 内容变化递增 profile_version。本文不修改 Kayla、不填入未经校准的四个数值。新格式同 id/version 不得接受不同 canonical 内容；snapshot/digest 包含完整有效参数，防止“忘 bump 但 cache 命中”。
- **Defaults**：唯一兼容默认是整个 behavioral_disposition=None；没有逐字段 0.5/1.0 fallback。schema 2 的 behavioral block 若存在，必须完整给四项，unknown keys、部分缺失、null 数值、NaN/Inf、bool、越界均拒绝。
- **模式**：legacy profile 可在明确 LEGACY 模式运行；SURFACE_V1 要求完整 behavioral block 和所有 enabled formula 所需 dimension/bounds，否则启动配置失败。运行时 snapshot 缺失则该 Surface evaluation unavailable，不能转回 raw 行为通道或悄悄零值补齐。
- **版本独立**：文档 1.1.0、persona schema 2、Persona 内容 revision、Surface recipe version 是不同概念，不相互冒用。

## 4. R1-B：D1 与 ADR-0027 唯一投影

| Option | Verdict | V1 决定 |
|---|---|---|
| D1 accepted appraisal → personality-conditioned numeric response | ACCEPT | 唯一路径；不改变 accepted meaning/confidence/salience |
| D2 新 behavioral traits 参与 acceptance 前 semantic interpretation | DEFER | 另需 PERSONA-CONDITIONED-APPRAISAL-CONTRACT；本版不扩展 Producer 输入 |
| D3 新 traits 同时影响 semantic salience 与 numeric gain | REJECT | 本版没有两个作用点的独立因果标定，不能据变量名不同宣称不重复 |

既有 SemanticAppraisalContext 已携带 Persona dimension context，ADR-0019 允许 agent-relative appraisal；本版不撤销它，也不宣称所有历史 appraisal 都人格无关。D1 冻结的是 **此次新增 behavioral disposition 的接入范围**：不得将新增四项/新 sensitivity bias 注入 Producer 或修改已接受结果。对同一个 AcceptedAppraisal 的反事实测试必须固定其完整 payload；不能先重跑模型再归因到 projector。

### 4.1 数值 ownership / gain-once

```text
compatibility recipe:
  unscaled_fast_amount = recipe.base_amount * candidate.confidence
  Dynamics impulse contribution = unscaled_fast_amount * dimension.sensitivity
  recovery + coupling + clamp = existing DynamicsEngine responsibility

salience = immutable accepted semantic value
  → existing Gate / authorized Slow weighting semantics
  ≠ new global Fast multiplier
```

以上是现有 event compatibility 分支；bounded-history contributions 仍按自己的原有规则与上限分别归因，不能揉成四因子公式。Slow proposed_value 为 absolute target，不乘 sensitivity，不当 Fast delta。本版不改 ADR-0017/0018、阈值、窗口或 Dynamics 数学。

AppraisalProjector 可以读取版本化 Persona/state definition，验证 dimension/owner 与 recipe dependency；V1 compatibility output 必须是 **pre-sensitivity** amount。`DynamicsEngine.step()` 继续是 sensitivity gain 的唯一应用点。Projector 不能先乘 sensitivity、再交给原 engine。依赖 digest 包含实际消费的 Persona 参数/版本，trace 分开 raw recipe amount 与 engine gain；不能另设 disposition gain。

新增四个 behavioral traits **只在 Surface 层消费**；旧 dimension sensitivity/recovery/coupling/baseline 留在原有 Dynamics owner。它们分别回答“内部反应如何演化”和“相同内部状态如何表现”，不通过 Producer 的新 salience multiplier 放大同一事件。

### 4.2 不可变与 delegation

AppraisalProjector 输出仅 effects/impulses/status/reasons/provenance。禁止 `appraisal.salience *= persona_factor`、copy/replace 后重新标 ACCEPTED、修改 meaning/confidence、伪造新 acceptance。接受记录序列化前后必须一致。

EffectMapper 若保留名称，只做参数适配并 delegate 到 AppraisalProjector；legacy EventEffectRule 必须成为同一 projector 的 versioned compatibility recipes，不得 facade 外再查旧规则或 fallback 调第二 mapper。无 recipe = UNMAPPED，零 appraisal-caused effects，语义按 ADR-0027 保留；不是禁止合法 elapsed recovery。REJECTED/ABSTAINED 与 UNMAPPED 分开。

不新增 DispositionProjector、ThreeLayerProjector、BehaviorProjector 来处理 appraisal。SurfaceAffectProjector 不读 AcceptedAppraisal，也不写 Dynamics。

## 5. Surface V1、依赖与 Slow 分类

### 5.1 S2 / S3

**S2 = f(EmotionDynamics, Disposition)：ACCEPT。S3 = f(EmotionDynamics, Disposition, bounded LongitudinalView)：DEFER。** 四个必需场景不需要 Slow，因此 V1 不消费它。

`agent.affect.*` 表示 Emotion Dynamics；`agent.slow.*` 和现有注册的 `agent.longitudinal.*` 表示 Longitudinal / Relationship / Slow Plasticity State。StateDefinition/registry 决定 owner，前缀不是 admission authority。1.0.0 中 `agent.slow.trust/intimacy` 不是已确认的 Kayla 配置字段；不得将其列为 Emotion Dynamics，或声称 trust 能解禁动作。既有 Slow 持久化/消费者保持其原有 authority；SURFACE_V1 Body profile 的数值暴露策略见 §7。

### 5.2 七项的准确地位

总称 **PROPOSED_V1_CONTROL_BASIS**，不是 proven consumer-driven minimal basis。以下“consumer”均为明确的迁移目标，非已经存在的 production Surface consumers。五项 ACCEPT 表示可实现的 schema/依赖与消费方向；不表示系数已生产校准。两项 DEFER 不进入 enabled controls、不填 0.5。

`D.x` 表示 `agent.affect.x` 的当前 snapshot 值；`P.x` 表示同 Persona 的 behavioral trait。

| Control / verdict | Target consumer | 为什么不能直接用 raw Dynamics / 预期差异 | 完整直接依赖（overlap roots） | Migration impact |
|---|---|---|---|---|
| contact_seeking / ACCEPT | Intent 联系类候选，如 contact_user/reach_out；tick复用 | 同 longing 下趋近与克制不同，联系候选分数不同 | D.longing、D.closeness_craving、D.anger；P.attachment_approach、P.expressive_restraint | 使用它的 rule 移除上述 raw weights |
| initiative / ACCEPT | Intent 发起话题/推进候选 | sharing/curiosity/低sadness 的组合表示启动倾向，单个情绪不代表启动 | D.sharing_urge、D.curiosity、D.sadness | 替换重叠 raw；不改 scheduler clock/permission |
| withdrawal / DEFER | 拟议回避候选/表达距离 | 与低 contact/initiative 的增量区别尚无明确 consumer 和独立公式 | 尚未冻结；禁止激活，禁止 opaque function | V1无字段值/权重/表达映射 |
| confrontation / ACCEPT | Intent 澄清分歧；Body表达直接程度 | 高anger配高restraint仍能低对峙，不让Body自解anger | D.anger；P.confrontation_readiness、P.expressive_restraint | 相关Intent去anger直权重；Body只见control |
| reassurance_seeking / DEFER | 拟议寻求确认候选 | anxiety只是兼容维度，当前无法区分确认事实与索取安慰的必要性 | 尚未冻结；禁止激活 | 不新增anxiety生产维度，不启用权重 |
| expressive_warmth / ACCEPT | DecisionContext bounded语气 | 表达亲和由trait与当前情绪共同决定，非closeness直译 | D.closeness_craving、D.anger、D.sadness；P.expressive_warmth_bias | 替换亲和类affect bands/static人格语气override |
| expressive_restraint / ACCEPT | DecisionContext bounded克制；现有Guard仍独立 | 同anger下表达克制不同，trait不是当前anger数值 | D.diligence_pressure；P.expressive_restraint | 替换克制类raw/style；不承诺Guard已支持连续control |

### 5.3 可执行配置的依赖规范

每个 enabled control 的 `SurfaceControlRule` 必须有 control_id、recipe_id/version、显式 `dynamics_dependencies`（全名）、`disposition_dependencies`（typed trait路径）、output range、typed formula。只允许输入引用、有限常数、加/减/乘、clamp 等已声明确定性运算；不允许 callback/custom_function/LLM/隐藏查询。解析 formula 的输入集合必须与声明集合完全一致，不能少报 anger 或 trait；无 cycles。V1 control 不依赖另一个 control，避免隐式串联；未来若允许必须展开传递闭包。

保留 1.0.0 的五个公式作为 **versioned reference recipe `surface-reference-v1`，PROVISIONAL / TEST CONFIG ONLY**，不作为全局心理学常数或默认生产配置：

```text
C = clamp[0,1]
contact_seeking = C((.5*D.longing + .3*D.closeness_craving + .2*P.attachment_approach)
                   * (1 - .5*D.anger*P.expressive_restraint))
initiative = C(.4*D.sharing_urge + .3*D.curiosity + .3*(1-D.sadness))
confrontation = C((.8*D.anger + .2*P.confrontation_readiness)
                 * (1-.6*P.expressive_restraint))
expressive_warmth = C(P.expressive_warmth_bias + .3*D.closeness_craving
                     - .4*D.anger - .2*D.sadness)
expressive_restraint = C(P.expressive_restraint + .1*D.diligence_pressure)
```

该 reference recipe 要求所用 state definition 的 range=[0,1]，不兼容者拒绝；不是任意尺度都套此公式。实际部署必须显式选择版本化 recipe/coefficients 和 matching consumer config，不能默默启用这组示例数字。改变系数改变 recipe version/digest；不改 accepted appraisal、不新增 state dimensions。

### 5.4 Derived payload 与 lineage

```text
AffectBehaviorControls:
  controls_id, runtime_id, owner_scope, interaction_or_tick_ref
  persona_id, persona_version, persona_content_digest
  source_projection_id, source_phase: projected | committed
  source_states: [(dimension, state_id, version, value_digest)]
  projector_id/version, recipe_digest, dependency_digest
  values: [(control_id, finite_value_0_to_1)]
  dependencies_by_control, evaluation_ref
```

有效值集合等于配置 enabled set；DEFERRED/unknown 不是0。不要用单个 `source_dynamics_version` 代表异步更新的整个向量。纯函数不读 clock/random/provider/I/O，时间记录由 caller 提供且不影响数值；ordered inputs/canonical serialization 固定。缺state、错scope、错Persona、旧recipe或不同projection输入拒绝；无 Surface→Dynamics feedback。

相同有效snapshot/配置得到相同结果和digest；支持的数值运行环境/序列化规则在Golden中固定。不承诺未经验证的跨平台浮点“完全比特级一致”或“亚毫秒”。可记录审计trace，不建立可独立更新/同步的Surface状态。

## 6. R1-C：Intent migration / no double counting

### 6.1 决策与最小 schema

| Option | Verdict | 结论 |
|---|---|---|
| I1 替换重叠 raw Dynamics | ACCEPT | Surface-aware rule 的相同 snapshot roots 不得重复入分 |
| I2 同时保留且声称正交 | DEFER | 无逐字段因果依据不允许 overlap 例外；名称不同不是正交证明 |
| I3 Surface只给Body | REJECT | 不能满足longing→Surface→Intent的本任务闭环 |

选择 **schema A**，避免把现有 `dimension_weights` 及全部 decoder 迁成通用输入DSL：

```python
IntentRule:
    # existing fields unchanged, including dimension_weights/event_bonus
    dimension_weights: tuple[tuple[str, float], ...]
    control_biases: tuple[tuple[str, float], ...] = ()
# composition owns ruleset_version + Surface ruleset binding
IntentEngineInput:
    # existing fields unchanged
    surface_controls: AffectBehaviorControls | None = None
```

V1 `control_biases` 只允许 contact_seeking/initiative/confrontation；warmth/restraint是表达控制，不顺手加Intent gain。nonempty biases = Surface-aware。legacy空bias规则保持原公式；所有现有threshold/clamp/stable sort/schedule/lifecycle不变。选统一typed `input_weights` 的方案 B：DEFER，当前无收益需要全量破坏兼容；不另造第三引擎。

### 6.2 overlap 是配置错误，不是运行时猜测

在 **composition配置加载/构建时** 取得确切 Surface recipe dependency manifest，逐 rule 校验：

```text
R = {dimension with nonzero dimension_weight}
U = union(declared Dynamics roots of each control with nonzero bias)
if R intersects U: reject SURFACE_DYNAMICS_OVERLAP
if multiple scored controls share Dynamics roots: reject SURFACE_CONTROL_OVERLAP
```

同时拒绝未知control、重复项、非finite/bool权重、无dependency manifest、错recipe版本。负权重同样重叠；不允许先加再减来规避。零权重不贡献，但仍校验名称/lineage，不以零权重携带未知维度。V1不提供 bypass/allow_overlap 开关。

作用域是 **同一个 Intent score**：不同候选可以合理读取同一state，不能为消除所有跨候选相关性重设计Intent。同一 kind 不得保留一个旧rule又添加Surface rule来分别入选；现有kind唯一校验保留。

运行时验证controls与本次projected snapshot、Persona、runtime、ruleset相同；缺失/失效时该Surface-aware rule不产候选，trace明确 `surface_unavailable`，不按0补值、不退回旧raw score。未依赖Surface的规则可继续。新配置不能在同一evaluation过程中热切换；profile/recipe更新需原子替换匹配ruleset并重新校验。

```text
score = base + sum(allowed direct dimension terms)
             + sum(valid non-overlapping surface terms) + permitted event_bonus
strength = clamp(score, 0, 1)   # existing threshold/schedule follows
```

Surface-aware affect驱动rule在V1要求 `event_bonus=0`，避免同一个情绪事件又以奖励项重复放大；event_kind仍可用于已有schedule匹配。纯事件/任务规则（无Surface biases）保持legacy event bonus。未来确有独立任务奖励需要双源时，另做因果契约，不在本版放宽。

IntentScoreTrace 增加 typed surface contribution（control_id、controls_id、recipe/snapshot refs、amount）和 overlap validation manifest ref；保留raw各项/总分/clamp。审计trace只列实际加分项，不把被替换raw再写成隐藏bonus。

兼容编码：沿用 `IntentScoreContribution`，Surface 项使用 `source_kind="surface"`，`source_ref` 解析到本次 controls_id 下的 control_id；在 `IntentScoreTrace` 增加可空 `surface_controls_ref`、`surface_dependency_digest`、`overlap_validation_ref`，legacy均为None。非空Surface贡献必须具备这些引用，且关联同一versioned ruleset；禁止只写一个不可解析的control名字。无需另建score trace系统。

### 6.3 按字段的迁移表

| 当前 raw dimension | Surface-aware rule 的未来输入 | Legacy / non-overlapping direct input |
|---|---|---|
| longing | contact_seeking；删除 longing weight | 未迁移规则可保留；同kind不可并行双rule |
| closeness_craving | contact_seeking；删除 closeness weight | 其他无该control的规则保留 |
| anger | contact_seeking或confrontation，二者不能同rule重叠加分 | 无这两项control的legacy规则可保留 |
| sharing_urge | initiative；删除 sharing weight | 不消费initiative的规则保留 |
| curiosity | initiative；删除 curiosity weight | information-seeking若不消费initiative，可保留；“动机vs启动”命名不能豁免重叠 |
| sadness | initiative；删除 sadness weight | 不消费initiative的规则保留 |
| diligence_pressure | 本版无Intent control读取它（restraint仅表达） | keep direct；未来扩control时重新校验 |
| restlessness / social_pull / introspective_pull | 本版未入已启用Intent control公式 | keep direct；不得为了表面覆盖新增control |
| anxiety | reassurance_seeking DEFER | compatibility规则保留，不新建生产anxiety |
| 其他合法非重叠维度，如 agent.drive.photo_share | 不强制迁移 | keep direct；dependency manifest变动必须重验 |

user-turn orchestrator 与 CognitiveTicker 必须调用同一个Surface projection contract和同一规则验证；主动tick不得再在Intent score外加wake/initiative boost。Scheduler只wake/reconsider，外部动作仍需Policy。

## 7. R1-D：Body migration / single behavior interpretation path

本节 B1/B2/B3 编号采用 R1 任务定义，替代 1.0.0 的不同编号。

| Option | Verdict | 决策 |
|---|---|---|
| B1 Surface替换行为侧raw Affect | ACCEPT | SURFACE_V1 provider envelope 唯一情感行为入口 |
| B2 raw+Surface同时可见，靠prompt禁止重解 | REJECT | 标签不是信息隔离，无法消除重复行为解释路径 |
| B3逐维选择性主观自知 | DEFER | V1不暴露sadness等raw；以后须单独冻结逐维非行为用途 |

### 7.1 Body实际收到的六项

1. Selected Intent / selected action（已通过Policy）。
2. Policy constraints。
3. 有界 Semantic Meaning（appraisal data，不是事实或行为命令）。
4. Surface controls（有版本的bounded expression rendering）。
5. 现有合法 Reality facts。
6. 现有有界 history（data，不是新的情感命令）。

**不提供 full raw Persona、full raw Dynamics vector；SURFACE_V1 连已迁移raw的band/label也不提供。** Accepted meanings可保留“感到受挫”这样的原因语义；不得由Compiler/Host补写“anger high所以严厉”的第二规则。BODY仍负责当前理解与语言，Surface不是开放世界事实判断或ActionPolicy；“不重复解释”是隔离runtime供给的重复行为输入，不是声称能阻止模型一切自主推理。

### 7.2 最小暴露配置和字段迁移

`DecisionContextConfig.affect_exposure_mode = LEGACY | SURFACE_V1`。旧配置缺字段按LEGACY；进入SURFACE_V1必须显式迁移同一composition的Intent/renderer/Host。LEGACY不得带任何Surface item；SURFACE_V1禁止raw affect_rules与Surface共存，启动时报错，不依赖后置prompt。

| 原输入/字段 | SURFACE_V1处理 | 保留位置 |
|---|---|---|
| longing / closeness_craving / sharing_urge / curiosity / sadness / anger | raw值及AffectExpressionRule输出全部RUNTIME_ONLY；由相应Surface表达/Intent承接 | Dynamics、诊断 |
| restlessness / social_pull / diligence_pressure / introspective_pull | 即便无Body control直接覆盖，也RUNTIME_ONLY；不等于删除state | runtime/legacy合法Intent、诊断 |
| anxiety / custom agent.affect.* | 默认RUNTIME_ONLY；不通过unknown/custom-rule绕过 | 兼容runtime/诊断 |
| 四个behavioral traits、dimension sensitivities/baselines | 不序列化到provider | 同一Persona/view、诊断 |
| expressive_warmth / expressive_restraint / confrontation | VISIBLE_TO_BODY，确定性有界control输出 | provider envelope + lineage diagnostics |
| contact_seeking / initiative | 供Intent评分；Body通过selected Intent知道目标，不再追加第二“主动行动”指令 | IntentScoreTrace/diagnostics |
| agent.slow.* / agent.longitudinal.* raw numbers | 不归类为Fast；此SURFACE_V1 Body profile不注入旧raw Slow summary，避免另一个数值行为解释入口 | canonical Slow和既有非Body消费者；LEGACY路径不变 |
| persona_style_constraints | 仅与情感行为不重叠的format/language constraints；warmth/restraint/directness/initiative类style禁止并存 | 非行为style可保留 |

V1不新增Slow→Surface/history编译；上述数值隐藏只限此Body exposure profile，不删除Slow、不重做Dynamic Harness。不能把raw值换名塞入Semantic Meaning/history/selected intent description。诊断引用留在diagnostic envelope，provider不能通过反序列化整个DecisionContext或state refs补回raw state。

### 7.3 Compiler、renderer、Host共同契约

- Compiler添加专用 `SURFACE_CONTROL` typed item；与现有INTERNAL_STATE区分，不能靠key前缀猜类型。未来对应 `contracts/expression.py` / renderer扩展，仍是一个Compiler。
- `SurfaceExpressionRule(control_id, output_key, bands, priority, version)`只将控制量转成受限表达标签；不得读取Dynamics/Persona再算一次。SURFACE_V1的behaviour keys只有这一个写入者。数值到标签的band是显式配置，不授权全局心理阈值。
- selected action、Policy constraints和本次必要Surface行为约束组成不可拆的minimum envelope。预算放不下时不调用Body并记录overflow；不得仅裁掉restraint留下对峙，也不得恢复raw affect。bounded meaning/history可按原规则整项省略。
- runtime snapshot缺失不回退raw表达；暂停该次Surface-dependent表达，保留诊断和既有状态处理。retry复用已编译的Surface/meaning，不重新step，不重新调用模型计算controls。
- 同时覆盖D10 renderer、proactive expression和Host `_bounded_context`/`render_bounded_context`。Host只转发同一已预算provider envelope，不再拼旧Slow summary或额外Persona行为卡；只改Compiler不是交付。
- ActionPolicy DENY/DEFER：不为该候选调用动作Body/发送；不能用高initiative触发旁路。Guard保留原权限边界，未实现连续Surface guard就不能称“已保证任何措辞都克制”。

## 8. Mandatory worked scenarios（全部 EXPECTED TRACE）

以下是 `surface-reference-v1` 和显式fixture Intent权重的可复算验收规范，不是生产运行记录。所需其余字段都提供合法固定值；事件/Appraisal差异不是这些反事实的隐藏变量。

### S1 — Same Dynamics, Different Disposition

固定同一Dynamics：longing=.8、closeness_craving=.6、anger=0；仅P.attachment_approach分别.2与.8，其余traits相同。

```text
A.contact = (.5*.8 + .3*.6 + .2*.2) * 1 = .62
B.contact = (.5*.8 + .3*.6 + .2*.8) * 1 = .74
```

应得到两个不同controls digest；原Dynamics向量相同且无写入。contract能表达同Dynamics下性格差异；不从此推出真实人类依恋规律，也不声称已实现。

### S2 — Longing → Contact Seeking → Intent（无raw重复）

使用S1的B；fixture contact rule：base=.1，control_biases=((contact_seeking,.8),)，dimension_weights=()，event_bonus=0，minimum=.65。

```text
contact=.74
score=.1 + .74*.8 = .692 → admitted
trace terms = [base .1, surface.contact_seeking .592]
```

若只把longing从.8降到.4，其余固定，contact=.54，score=.532，低于阈值。若再配置raw longing weight=.75，必须在evaluation前拒绝overlap，不能得到`.692+.8*.75`再clamp掩盖错误。若需要跨轮累积场景，先用已授权的真实Dynamics轨迹提供state，再走此链；不能把“用户未出现”直接发明成重复impulse。

### S3 — Irritation + Restraint，Body不重解raw anger

固定anger=.8、diligence_pressure=.4、P.confrontation_readiness=.5；仅trait restraint对比.9与.2。

```text
raw_confront = .8*.8 + .2*.5 = .74
high-restraint confrontation = .74*(1-.6*.9) = .3404
low-restraint confrontation  = .74*(1-.6*.2) = .6512
high-restraint control.expressive_restraint = .9 + .1*.4 = .94
```

两者anger始终相同。合法Policy ALLOW后的Body只收到bounded意味、选中Intent/constraints、confrontation/restraint/warmth表达controls；捕获最终provider bytes必须没有`anger=.8`、`anger high`或其别名raw band，也没有P.restraint原值。不能依靠一句“别按anger行为”通过验收。

### S4 — Policy denial

fixture sharing_urge=.8、curiosity=.7、sadness=.1，则initiative=.4*.8+.3*.7+.3*.9=.8。推进候选base=.1、initiative bias=.8、无raw weights/bonus，score=.74，minimum=.65，得到候选。

已存在Policy规则返回DENY（或独立DEFER测试）时，候选转BLOCKED（或DEFERRED），该动作provider/send/tool调用数必须0。高分不是permission。Affect commit与dispatch按现有边界独立，不因deny反写Persona或Surface。不能把这些数字当真实部署的rule/threshold。

## 9. Contract验收与迁移检查

| ID | 必须先RED的断言 | GREEN必须覆盖的真实位置 |
|---|---|---|
| A1 | behavioral四项唯一holder；legacy缺失不造中性人格；NaN/Inf/bool/未知字段拒绝 | Persona loader/config roundtrip + view identity；禁止current state字段 |
| A2 | 内容变化必须新version；相同id/version冲突；view不同persona拒绝 | profile loader/composition + projection digests |
| B1 | fixed AcceptedAppraisal字节不变；不同sensitivity只有一次gain | Producer accepted record→唯一projector→现有DynamicsEngine；不是只测自写公式 |
| B2 | main四个legacy recipe及history/Slow精确兼容；UNMAPPED无appraisal effect | EffectMapper facade不保留规则；ADR-0027 compatibility/replay基线 |
| C1 | longing+contact拒绝；anger+contact也拒绝；负权重/别名/改recipe不能绕过 | 配置decoder + runtime constructor + trace；两个Surface共root也拒绝 |
| C2 | 合法non-overlap保留原score；missing/stale Surface不raw fallback | user turn与tick同规则、同snapshot；同kind不能双候选 |
| C3 | Surface rule非零event_bonus拒绝 | 源贡献逐项trace，防第三条隐藏加分通路 |
| D1 | raw float和band均从SURFACE_V1最终provider payload消失 | Compiler→renderer→Host/proactive实际bytes捕获；包含style/Slow旁路检查 |
| D2 | raw-only LEGACY与Surface-only模式隔离；retry/overflow不恢复raw | config validation、minimum envelope、fault injection |
| S1–S4 | 使用§8 fixture重演，Policy deny调用计数为0 | production-shaped orchestration causal tests；scripted语义不是live语义证明 |
| R1 | 相同version/snapshot重启derived重算一致；projected不冒充committed | existing state恢复 + Surface无独立state写入 |

实际实现只需要沿现有Persona、mapper/ADR-0027、Intent、expression与composition owners补契约；不引入第二套人格/情感写入链。相关未来文件面：`dynamics/persona.py`、`contracts/affect.py`、`persona_config.py`、Persona JSON、`emotional_transition/effects.py`（delegate）、ADR-0027 projector所在模块、`contracts/behavior.py`/`intent.py`、`intents/engine.py`、`expression/context.py`/`renderer.py`、`contracts/expression.py`、turn/tick/Host composition及严格config decoders。DynamicsEngine数学不改，Slow writer/Reality/ActionPolicy权限不改。具体生产diff必须在后续W中按RED逐项落地，本轮不实现。

## 10. Final contract verdicts

| 判定项 | Verdict | 冻结选择 |
|---|---|---|
| Personality schema | ACCEPT | P2；P1完整方案DEFER，P3 REJECT |
| Appraisal influence | ACCEPT | D1；D2 DEFER，D3 REJECT for V1 |
| Intent migration | ACCEPT | I1、schema A；I2 DEFER，I3 REJECT |
| Body migration | ACCEPT | B1；B2 REJECT，B3 DEFER |
| Slow-state dependency | ACCEPT | S2；S3 DEFER |
| 7-control basis | DEFER | 不接受“七项全是必要最小集”；五项可实施schema ACCEPT，两项DEFER；总称PROPOSED_V1_CONTROL_BASIS |

| PASS condition | R1 contract结果 |
|---|---|
| 唯一Personality canonical schema | 满足：§3 PersonaProfile唯一holder、版本和missing明确 |
| disposition作用点合法且不越权 | 满足：§4 accepted不变、numeric sensitivity一次、behavioral只进Surface |
| Intent无隐式raw+Surface双算 | 满足：§6 mandatory overlap rejection与same-snapshot检查 |
| Body无未约束raw+Surface双解释 | 满足：§7 provider隔离和所有出口迁移；不是prompt承诺 |
| Slow/Fast分类分开 | 满足：§2/5 S2不消费Longitudinal |
| controls dependency lineage | 满足：五项完整typed依赖；两项未定义所以禁用 |
| control basis无虚假production proof | 满足：proposed与contract acceptance分开 |
| examples无production verification声称 | 满足：§8仅EXPECTED TRACE，§9要求未来RED/GREEN |

**CONTRACT_ACCEPTABLE_FOR_IMPLEMENTATION**

这是对四个architecture blockers的裁决，不声称production已具备这些能力。ADR-0027 accepted修订/实现的主线集成、正式W的RED/独立review与部署校准仍是各自工程gate；不能以本文跳过。无须重做StateBar/Reality、第二Persona、第二Appraisal projector、修改AcceptedAppraisal、LLM计算Surface、Slow伪装Fast或LCE/Persona Genesis依赖；未触发任务STOP conditions。
