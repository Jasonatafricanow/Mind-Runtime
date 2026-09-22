# MR-LATE-PROJECTION-MAINLINE-RECONCILE-01

不要重新设计 Late Projection。恢复 ADR-0027 ACCEPTED revision、MR-LATE-PROJECTION W1、current main、Reality/StateBar 最新边界与 MR-AFFECT-RUNTIME-CONTRACT-01 v1.1.0 的真实代码关系，消除 authority/version drift。重点验证 ONE AppraisalProjector、AcceptedAppraisal immutable、projector 输出 pre-sensitivity effect、DynamicsEngine sensitivity exactly once，以及 W1 journal/replay/cognition seam 在最新 main 下仍是否合法。最终输出唯一 mainline integration plan 和 W2 剩余范围。

日期：2026-09-23。最终裁决：**NEEDS_TARGETED_FIX**。

唯一推荐路线是 current main `1777284` 上恢复 accepted ADR，再重放 W1 两个代码提交，完成本文 F1/F2 的有界校验修复后冻结 W2 base。不是回到旧 W1 分支开发，也不是重开 ADR 决策。已实际完成无冲突重放，未修改生产实现、未 merge/push/deploy。W2 和 Surface 均未实施。

## 1. Authority / topology

执行入口 `C:/projects/mind-runtime-main-merge`，GitHub remote 为 `https://github.com/Jasonatafricanow/Mind-Runtime.git`。未使用 `C:/projects/Mind Runtime`。开工 branch=`main`，HEAD 和本地 origin/main 均为 `17772842aaffd44c4ff1a643e9fa4621fa9e6652`；本轮 `git ls-remote origin refs/heads/main` 返回相同 SHA（不是只相信远端跟踪 ref）。

开工无 tracked modifications；以下均为原有 untracked，未覆盖、删除或纳入本轮提交：

- `docs/architecture/MR_AFFECT_RUNTIME_CONTRACT_01.md`
- `docs/architecture/MR_REALITY_OBSERVATION_CONTRACT_01.md`
- `docs/audits/MR_AFFECT_DYNAMIC_HARNESS_IMPLEMENTATION_AUDIT_2026-09-22.md`
- `docs/audits/MR_AFFECT_RUNTIME_CONTRACT_01_R1_REPORT.md`
- `docs/audits/MR_BASELINE_RECONCILE_01_DISCOVERY.md`
- `docs/audits/evidence/`

完整 local branches、refs、worktrees、main status 固定在 [evidence](evidence/mr-late-projection-mainline-reconcile-01/)。本轮新 worktree 也在快照中明确列出，不冒充初始存在。

| Authority | 精确 revision / 状态 |
|---|---|
| main | `17772842aaffd44c4ff1a643e9fa4621fa9e6652` |
| W1 与 main merge-base / W1 base | `7e9119fc582567fc6ad104c55f25e14a3bf1fa05` |
| accepted ADR | `7780bdc77adbbb3f4666f0823d12b74869af27dd` |
| open vendor implementation | `bf53e9ff1f5add0877a14c4f929aa82b465da125` |
| W1 foundation implementation | `637bd43355b4642868a77c1c2cf1a1de2e868d53` |
| W1 audit/report commit / branch HEAD | `d1cd5ab2f28867f76f9de74c4f6d04813753fa72` |
| W1 branch/worktree | `w/mr-late-projection-01-w1` / `C:/projects/mr-late-projection-01-w1`，开工 clean |
| main baseline repair | `94348a3cf1c3054c3d150a1c92f2007dd8fb7d0a`，已在 main ancestry |
| StateBar binding | `w/statebar-mr-binding-01 @ a7fb24d491f0f3917c3fa2e5bcd0c7e6689849d8`，只有 design doc |
| StateBar reuse | `w/mr-statebar-reuse-01 @ bac449f9163b2f6b5b8ab3e78bd9b850a733f380`；实现 `141fae073eb41558ec17d9b90ffd33c39755ef2d` |
| Reality hardening | `w/mr-reality-input-hardening-01 @ a1005d9b6d30267ba8776dfce171cbcba8afd423` |
| latest Reality replay/terminal | `w/mr-reality-eligibility-replay-stability-01 @ 14154a52848906b67ad200ce39f0094b2d06e0e5` |

后三个实现工作区位于 canonical `.worktrees/` 的同名目录；Reality latest 包含 hardening 和 StateBar reuse ancestry，均未进入本轮 main。不可把 main 的 StateBar 架构文档当成这些生产分支已合并。

main 相对 W1 base 只增加 baseline repair（测试/pytest 配置）和 StateBar architecture 文档；`git diff 7e9119f..1777284 -- src` 为空。因此不存在必须回滚 main production 才能搬运 W1 的理由。

### Affect contract 的文件 authority

`docs/architecture/MR_AFFECT_RUNTIME_CONTRACT_01.md` 是用户指定的冻结 v1.1.0，本轮直接读取，Status 为 R1 CONTRACT HARDENED / ARCHITECTURE-ONLY。它尚未被 Git 跟踪，不能赋予虚构的 commit。SHA256：

`2E8C53F74BE19297CBB2E6A91FE8A512F973A41DA2327602C8514C82E88763DD`

原样副本为 [affect-v1.1.0-snapshot.md](evidence/mr-late-projection-mainline-reconcile-01/affect-v1.1.0-snapshot.md)。该副本是证据，不设第二合同 owner；正式集成应把相同字节纳入 architecture canonical path，并固定其提交。

### 独立 review 证据的强度

Git 中不存在单独命名的 W1 review implementation commit；`d1cd5ab` 是独立 review PASS 及当时全量阻塞的报告载体，不是实现。不能从它推断今天仍然 PASS。本轮按 AGENTS.md 独立 review 要求另行进行了只读代码复核，审查对象为 `6e027cd`，独立运行 `tests/late_projection` 为 68 passed；发现 F1/F2，主审已复现 F1。历史 raw `.artifacts/mr-late-projection-01` 包含 RED/focused/full logs，但不以旧摘要替代此次判断。

## 2. ADR-0027 reconciliation

1. main 文件头仍为 **PROPOSED**。这只是落后文件，不是重新请求 architecture acceptance 的理由。
2. `git log --all -- docs/adr/0027-late-bound-appraisal-projection.md` 只找到迁移基线与 `7780bdc`；后者仍是最新 accepted ADR revision。diff 仅将状态改 ACCEPTED、添加日期和 user authorization；没有暗改设计。
3. StateBar/Reality 后续文档没有撤销 ONE projector、meaning 保留、journal、W2 cognition 或 existing commit ownership。新增事实形态是上游适配要求，不是第二 affect authority。
4. Affect v1.1 §4 对 D1/gain-once 作更明确约束，与 ADR 的 legacy numerical equivalence、immutable semantics 兼容。v1.1 取代 v1.0 的冲突条款；不把本来属于 Dynamics 的 sensitivity 搬到 projector。新增 behavioral traits 只在未来 Surface 消费，不注入 Producer，也没有新 disposition gain。
5. 搬运方式：直接 cherry-pick `7780bdc`，不 recreate accepted 决策；保留 ADR 原文主体。其历史小节标题含 “proposed for acceptance” 是旧措辞，不推翻已接受文件头。另在 reconciliation 文档明确 v1.1 §4 的适用关系即可。

## 3. W1 逐项真实状态

代码行号固定于模拟 integration source `6e027cd`；该 source 与 W1 生产文件相同。

| 项目 | 状态 | 证据 / 边界 |
|---|---|---|
| accepted ADR | IMPLEMENTED | `7780bdc`；main 旧头为 SUPERSEDED |
| GLM/Zen bounded open vocabulary | IMPLEMENTED | vendor parser/prompt + `test_open_vendor_vocabulary.py` |
| 所有 provider 全部开放 | PARTIAL | current factory 选 GLM/Zen；`provider.py:107,211` 其他 provider 保留 finite kind，不能泛化 |
| AcceptedAppraisal / result / status contracts | IMPLEMENTED | `contracts/late_projection.py:56-143`，frozen records |
| single projector + delegate facade | IMPLEMENTED | `effects.py:101,392-401`；无独立 mapper recipe owner |
| producer-owned acceptance | IMPLEMENTED | `appraisal.py:116-208` 独立 API；生产端尚未消费 |
| accepted appraisal persistence | IMPLEMENTED | journal immutable rows/source payload；仅 API 被调用时持久化 |
| journal evaluation / restart materialization | IMPLEMENTED | `projection_journal.py:58-261`，三张 derived 表、缓存完整性及 supersession |
| projection target definition/operation validation | PARTIAL | F1：可输出非法 target-operation 的 MAPPED |
| versioned Persona dependency binding | PARTIAL | F2：有内容 hash，无明确 PersonaProfile.version/definition binding |
| MAPPED / UNMAPPED / ABSTAINED / REJECTED | IMPLEMENTED | `effects.py:157-199`；target 验证不足不应被 status 枚举掩盖 |
| production acceptance→journal wiring | MISSING | `dynamics/ports.py:209` assemble；`:265` legacy map；属于 W2 |
| production accepted→UNMAPPED result | PARTIAL | API 成立；端口仍以 impulses 决定 accepted_events，`:446-453` |
| cross-interaction application rejection | MISSING | acceptance identity 绑定 interaction 不是 application consumer check；无 effect receipt |
| exactly-once effect application | PARTIAL | 既有 turn marker 存在；无 appraisal/effect-group application identity |
| cognition contract | DOC_ONLY | ADR 冻结，源代码无 COGNITIVE_MEANING |
| W1 tests | IMPLEMENTED | 当前 W1 253 passed；68 个 late_projection tests，40 组旧 recipe samples |
| 独立 review | IMPLEMENTED | 历史报告存在；此次 fresh review 得到 NEEDS_TARGETED_FIX |
| 旧 full-suite blocker conclusion | SUPERSEDED | main `94348a3` 已修正 baseline ownership/optional gates；此次差分另见 §9 |

## 4. Affect v1.1 compatibility / targeted blockers

### A/B/C：ONE / D1 / Gain-once

ONE owner 已成立。EffectMapper 只构造 AppraisalProjector 并 delegate `.map()`。projector 的兼容路径和 accepted path 共用 `_map_legacy`，不是两套 recipe。

AcceptedAppraisal 及嵌套 SemanticAppraisal 为 immutable records；projector 不调用 accept/assemble/model、不改 meanings/confidence/salience。本轮固定序列化完整 accepted payload，改变 dimension sensitivity：

| sensitivity | projector amount | Dynamics impulse contribution |
|---|---:|---:|
| 0.5 | 0.16000000000000003 | 0.08000000000000002 |
| 1.5 | 0.16000000000000003 | 0.24000000000000005 |

两次 accepted bytes 相同。`effects.py:289` 是 base_amount × candidate.confidence，salience 仅透传 gate；`dynamics/engine.py:110` 才乘 sensitivity。无需修改 W1 数值公式以兼容 v1.1。

### D：合法 Slow 路径与 F1

合法 legacy Slow amount 在 `effects.py:309` 原样发送；result operation 在 `:211` 标为 proposed_value；`dynamics/ports.py:742-762` 将 longitudinal proposal 直接送 HomeostasisGate，`:864` CandidateStateDelta.proposed_value=amount。existing registered Slow dimensions 不在 affect Persona profiles 中，所以 engine 不消费它们。writer target 由 existing registry resolve。

**F1（合入前 targeted fix）：这条分离依赖合法配置，projector 并未验证。**

`EventEffectRule.__post_init__` (`effects.py:47-75`) 仅验证数字、字符串和 pair presence；`ProjectionEffect`/result 同样不验证 target/operation/definition ownership。本轮与独立 reviewer 均复现：

```python
EventEffectRule('plan_cancelled', 'agent.affect.anxiety', .1,
    longitudinal_target_dimension='agent.affect.anxiety', longitudinal_proposed_value=.8)
# MAPPED: affect anxiety delta=.08 AND affect anxiety proposed_value=.8

EventEffectRule('plan_cancelled', 'agent.slow.trust', .1)
# MAPPED: slow trust delta=.08
```

第一种错误配置经 legacy port 将全部 impulses 送 engine，若 target 与 affect profile 重合，absolute .8 也可能作为 additive impulse 乘 sensitivity。这是 baseline recipe validation 原先已存在的弱点，但 W1 新 first-class result 仍将其认证为 MAPPED，不能声称已满足最新 fail-closed target contract。正确 remedy 是依据已有 StateDefinition/owner/operation 进行目标验证，whole result fail closed；不改 AcceptedAppraisal，不新增 projector，不改变合法 recipes 数值。此任务只审计，不实施修复。

### F2：dependency binding 的有界补齐

`effects.py:112-126` digest 包含 acceptance、history、调用者传入 persona、routing、recipes、projector version。`projection_journal.py:218` intended input 为 dimension profiles tuple，默认空；`PersonaProfile.version` 不在这个类型中。当前可证明参数内容变化导致 key 变化，不能证明 Persona/profile version 与 registry revision 的受约束失效规则。应在 projector/journal dependency seam 绑定现有版本化 owner/definitions 并测试失效；无需把 version 或 disposition 塞进 AcceptedAppraisal。不要让 future mutable fast-state 或无关 turn number成为无意 invalidator。

### E：Surface separation

W1 diff 没有 Surface、Intent/ActionPolicy permission、Persona behavioral schema、Body exposure 修改。D1 已冻结，不需要 second projector 或 LLM numeric delta。Surface implementation prerequisite **NOT SATISFIED**：ADR/W1 mainline integration 与 F1/F2 gate 尚未关闭，本轮不能认证其 prerequisites；cognition/receipts 是 W2 剩余项，本审计不额外规定 Surface 与全部 W2 工作的执行依赖。

## 5. Open semantics：离线真实 parser 链与 production 差别

本轮 [reconcile_probe.py](evidence/mr-late-projection-mainline-reconcile-01/reconcile_probe.py) 分别调用真实 GLM/Zen `propose_with_telemetry`，只替换网络返回；将其 novel candidate 送真实 Producer.accept → AppraisalProjector → SQLite journal → close/reopen，验证：

- `ACCEPTED`；meanings=`recognition, relief`；`UNMAPPED`；effects=[]。
- restart 返回相同 result，trap projector 重算；meaning 仍能从 acceptance record 解析。
- 固定时钟、零 elapsed、无 coupling/modifier，真实 Dynamics 数值及 contributions 不变。
- 无最近 emotion 猜测，无 novel-kind semantic rejection，无 live API call。

这是 offline composition evidence，appraisal model 为 fixture；**不是生产 orchestrator 路径或 live natural-language proof**。当前生产 `ports.py` 仍 assemble→legacy map，novel kind 在 `_map_legacy` 会有 `unknown_event_kind`；accepted API 的 projector 分支才将无 recipe 转为 UNMAPPED。W2 必须切换已有接缝，保留 legacy no-appraisal 分支明确标记，不能宣称 W1 已彻底移除生产 choke point。

## 6. Cognition seam

| 检查 | 当前事实 | 所属 |
|---|---|---|
| accepted→bounded COGNITIVE_MEANING 合同 | ADR:131-149 有冻结设计；无 typed implementation | W2 planned |
| durable source journal | W1 可读 acceptance/result；无 production read adapter | W1 foundation + W2 wiring |
| EmotionalTransitionResult accepted payload/projection refs | `contracts/emotional_transition.py:159` 仅 projected/accepted_events/trace | never implemented / W2 |
| compiler accepted input | `expression/context.py:160-179` 没有该字段 | never implemented / W2 |
| ExpressionContextKind | `contracts/expression.py:12-20` 无该 kind | never implemented / W2 |
| renderer labeled appraisal data | `expression/renderer.py:16-54` 无 section/trust treatment | never implemented / W2 |
| retry preserves same meaning item | generic retry :239 存在，meaning item 尚不存在 | generic only / W2 |
| admission policy/budget/deny | generic budgets 存在；meaning eligibility/omission reasons 未接 | generic only / W2 |
| provider-visible production rendering | D10 renderer 可复用；Host `runtime_adapter.py:189` 自拼摘要未转发该 item | W2 adapter proof required |

保持 FACT 与 appraisal data 分离；语义不授予 Intent/ActionPolicy permission。只需本轮 accepted meaning read view，不取历史 appraisal，不实现 Memory/LCE/OW。未来 Surface B1 envelope 的迁移属于另一个 scope，不能借此次 cognition seam 提前改 Body exposure。

## 7. Journal / exactly-once

| 内容 | 当前恢复结果 |
|---|---|
| projection identity | `projection-` + SHA256 dependency digest；immutable primary key |
| source lineage | acceptance id、appraisal/candidate refs、runtime/scope/interaction、trusted evidence + provenance |
| evaluation outcome | accepted status 独立于四种 projection status；journal 三表持久化 |
| integrity/currentness | decode/hash/identity checks、explicit supersession、current lookup conflict rejection |
| application outcome | **不存在** pending/committed/aborted application record |
| commit receipt | **不存在** appraisal/effect-group receipt；现有 interaction commit marker 不能冒充它 |
| same-input retry/restart | evaluation materialization 已验证；同一个 result ≠ effect 已应用 |
| cross-interaction | hash/lookup/supersession 限制有；canonical application consumer 尚无，不能证明拒绝旧 effect |
| crash recovery | evaluation row SQLite transaction 有；journal failure→no state write、receipt/state 原子提交尚无完整链 |

既有 `pipeline/orchestrator.py:1182-1334` 已有 staleness check、interaction replay guard、Slow prepare/execute/apply、state backend transaction 和 post-commit publication；并非从零实现 transaction。`tests/pipeline/test_atomic_cognitive_admission.py` 已含 fast/slow/marker happy path、rollback 和 replay cases。W2 应把 journal application identity/receipt 纳入同一现有 transaction，验证 shared connection 与 rollback；不能把 `with journal.connection` 独立提交或 process lock 当 cross-store atomicity。

## 8. Reality / StateBar 边界

main `STATEBAR_MR_INTEGRATION.md` 是架构记录。latest Reality branch 的 `facts/service.py:226-258,472` 做 reality namespace 验证，`reality/eligibility.py:54` 限 USER scope；extraction 经 RealityAdmissionPort→事实 admission，不调用 EffectMapper/Projector。`git diff` 显示 orchestrator 改动集中 ingest/replay/terminal eligibility，其 affect run/DecisionContext appraisal seam 没被取代。

没有发现 StateBar→direct affect effect authority collision。binding 分支只是文档，不能误称已有运行中的外部 snapshot 集成。latest Reality Observation 新增 modality/semantic_time/effective_window/semantic fields；未来集成要确保 eligibility-approved Observation 及其 evidence refs 经 Situation 送入 SemanticAppraisalContext。仍用同一个 appraisal producer；不得把 modality/observation labels 直接转换成 numeric affect。此处只记录 adapter requirement，不搬运 Reality 分支、不认证 Reality 完整交付。

## 9. Differential verification

解释：三次源代码对象不同，不能混写计数；全量使用当前默认 canonical `python -m pytest -q -rs`（pyproject 排除 live），未运行真实 provider/Host。主目录原有 untracked docs 不参与测试。

| 对象 | 命令/范围 | 本轮结果 |
|---|---|---|
| 原 W1 `d1cd5ab` | tests/late_projection tests/emotional_transition | 253 passed, 5 skipped |
| main `1777284` | tests/emotional_transition tests/dynamics tests/expression | 256 passed, 5 skipped |
| replay `6e027cd` | 上述 + tests/late_projection | 406 passed, 5 skipped |
| 独立 review replay | tests/late_projection | 68 passed |
| gain/open semantics/counterexamples | evidence/reconcile_probe.py | exit 0；F1 非法 MAPPED 复现，其他断言成立 |
| main canonical full | default entire suite | 2889 passed, 11 skipped, 4 deselected, 1 xfailed；1045.79s，exit 0 |
| replay canonical full | default entire suite | 3039 passed, 11 skipped, 4 deselected, 1 xfailed；1090.82s，exit 0 |

5 个 focused skips：4 个 curl_cffi-absent factory 分支因本环境已安装依赖而 skip；1 个 live provider opt-in 不启用。旧 W1 complete-suite 的 missing helper/fastembed 不可直接重用为今天失败：`94348a3` 已更换 deferred Memory assertion 并把可选 vector tests 显式 gating。不得重新补出被 deferred 的 Memory→FACT 行为。

差分分类：**ENVIRONMENT** 为双方相同的可选 lce-core（1）、fastembed（4）、live profile DB（1）缺失，加上上述 factory/live skips；不构成本次 NEW REGRESSION。**BASELINE** 的 strict xfail 是 `tests/golden/test_golden_g24_g28.py:54`，owner=`MR-D11P` / G28，未改变。4 个 live tests 被默认 policy deselect。**NEW REGRESSION**：现有 canonical suite 检出 0；W1 增加 150 个 passing tests，skip/xfail 集合不变。F1/F2 是本轮超出现有 suite 的语义/契约发现，suite 绿色不能关闭它们。

Golden 影响：legacy recipe/Dynamics 与 vector commit 保持既有 Golden suite；G28 仍由 MR-D11P 持有，不是 W1 待修项。W2 后续需要 appraisal-specific receipt/cognition/group cases，不能改这些 baseline ownership。完整日志为 `main-full-suite.txt`、`integration-full-suite.txt`；Python/pytest/platform 固定于 `environment.txt`。本轮 suite 相比旧报告耗时更长不构成性能回归判定，两份同时运行，未做受控性能比较。

## 10. W2 exact remaining scope

| 工作 | 状态 | 必须补齐的实际增量 |
|---|---|---|
| 多 effect proposal | DONE | 现有 event+history+longitudinal tuple；仅代表 proposal，F1/F2 修复前不认证任意目标 |
| multi-effect application | PARTIAL | 复用当前 vector/group commit，添加 validated projection group consumption |
| mixed Fast/Slow atomicity | PARTIAL | 已有 prepare/transaction/post-commit seam；补 admission metadata、required-joint vs legacy-independent、任一必需成员失败全回滚 |
| journal ↔ state commit receipt | NOT_STARTED | application identity/outcome/receipt 与 state 同 transaction；不新增独立 writer |
| same-interaction retry | PARTIAL | evaluation cache 和旧 turn marker 分别存在；闭合 accepted reuse、禁止再 inference/reapply |
| crash recovery | PARTIAL | existing checkpoint/commit 恢复存在；补 evaluation-before-application、commit 前后故障注入 |
| restart | PARTIAL | journal cache/旧 state restart 各自已有；补一条跨层 receipt 重用链 |
| cross-interaction effect replay rejection | NOT_STARTED | caller/admission context + durable group uniqueness；不能靠只改 hash |
| DecisionContext cognition | NOT_STARTED | frozen ADR 的 additive kind/input/policy/budget/omission/read view |
| provider-visible rendering | NOT_STARTED | labeled/quoted appraisal section + retry same item；验证当前 Host/proactive adapter，不操作 live Xiyue |
| 重新设计 appraisal/第二 projector/重乘 gain | NO_LONGER_NEEDED | authority 已冻结；禁止实施 |

W2 不包含新 recipes、behavioral Persona schema、Surface/Intent controls/Body exposure migration、Reality 扩围、LCE/Memory/OW。W3 的观测 coverage/live LAB 未开工，不与 W2 DONE 混淆。

## 11. 最终 gate

**NEEDS_TARGETED_FIX**，并非 ARCHITECTURE_CONFLICT。F1/F2 都能在现有 projector dependency/validation seam 内修复，无需任一 STOP 条件中的 architecture 变更。

临时 branch=`w/mr-late-projection-mainline-reconcile-01`；base=`1777284`；worktree=`C:/projects/mind-runtime-main-merge/.worktrees/mr-late-projection-mainline-reconcile-01`。重放 source HEAD=`6e027cdca5a947ee4537aa36a2702c9b86195b8c` 只是 **candidate baseline**，不是被认证可开工的 W2 base。F1/F2 尚未实施，因此 **W2 exact authorized base commit = NOT YET CREATED**；给虚构 SHA 会掩盖 gate。具体唯一顺序见 [integration plan](MR_LATE_PROJECTION_INTEGRATION_PLAN_01.md)。

交付文件及 evidence 固定在该临时分支的后续 docs-only commit；`replay-commits.txt` 记录三颗 source replay commits。main HEAD 保持 `1777284`，原有 untracked 文件不变，原 W1 HEAD 保持 `d1cd5ab`。最终未 merge/push/deploy，没有 live provider 调用，没有生产 DB 操作或 protected schema 改动。该 docs-only commit 不构成 F1/F2 修复或 Y。
