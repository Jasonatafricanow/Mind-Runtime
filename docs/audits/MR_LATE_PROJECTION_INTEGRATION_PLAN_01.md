# MR-LATE-PROJECTION-INTEGRATION-PLAN-01

不要重新设计 Late Projection。恢复 ADR-0027 ACCEPTED revision、MR-LATE-PROJECTION W1、current main、Reality/StateBar 最新边界与 MR-AFFECT-RUNTIME-CONTRACT-01 v1.1.0 的真实代码关系，消除 authority/version drift。重点验证 ONE AppraisalProjector、AcceptedAppraisal immutable、projector 输出 pre-sensitivity effect、DynamicsEngine sensitivity exactly once，以及 W1 journal/replay/cognition seam 在最新 main 下仍是否合法。最终输出唯一 mainline integration plan 和 W2 剩余范围。

日期：2026-09-23。裁决 **NEEDS_TARGETED_FIX**。本计划由代码恢复和实际 cherry-pick simulation 得出，不授权 merge/push/deploy，也不实施 W2/Surface。

## 1. 唯一集成拓扑

```text
main 17772842aaffd44c4ff1a643e9fa4621fa9e6652
  [已含 94348a3 baseline reconciliation + StateBar design]
  ↓ cherry-pick 7780bdc77adbbb3f4666f0823d12b74869af27dd
2a2af13041bb0e676d13f2877816dfdfdb0a4d82  accepted ADR
  ↓ cherry-pick bf53e9ff1f5add0877a14c4f929aa82b465da125
f3196ebab35e2bcd9d4c4b1f972c70b7f0ebaf62  GLM/Zen open semantics
  ↓ cherry-pick 637bd43355b4642868a77c1c2cf1a1de2e868d53
6e027cdca5a947ee4537aa36a2702c9b86195b8c  W1 candidate foundation
  ↓ pin the exact Affect v1.1.0 file as canonical tracked architecture document
  ↓ F1 target/operation/owner validation: RED → bounded fix → GREEN
  ↓ F2 versioned Persona/definition dependency binding: RED → bounded fix → GREEN
  ↓ fresh targeted + canonical suite + independent source review
Y = exact post-fix reviewed commit (NOT YET CREATED; do not invent)
  ↓ only then start the bounded W2 work in §4
```

前三步已在本地临时分支实际执行，无冲突；commit SHA 是此次本地 replay 的真实 SHA，不能假定未来在别处分支重放会得到相同 SHA。source 文件相对旧 W1 没有额外改写；main repairs 未被回滚。

## 2. 保留、排除、superseded

| 项目 | 处理 |
|---|---|
| `7780bdc` | authority source，直接恢复；不得改为重新 PROPOSED/投票 |
| `bf53e9f`, `637bd43` | 保留全部 bounded W1 provider/foundation changes；不拆掉 journal 或 facade |
| `d1cd5ab` | 保留为历史证据，不机械 cherry-pick 旧 integration verdict；新 audit 取代今天的 gate 判断 |
| `94348a3` | 必须保留，baseline repair 已在 main；旧 missing helper/full-suite blocker 不能覆盖它 |
| main ADR 的 PROPOSED 头 | 被 accepted revision supersede |
| Affect v1.0 冲突条款 | 被 v1.1.0 supersede；不导入旧 salience/disposition multiplier |
| W1 code commits | 没有整颗 code commit 被判定 superseded；是增量 validation hardening，不是换掉 W1 |
| Reality/StateBar 分支 | 只保留边界约束；不纳入本次 replay，不能把未合入的不同 topology 假装成 main |
| unrelated remote packaging/naming branches | 本轮不是 current main，不混入 |

v1.1.0 exact file hash：`2E8C53F74BE19297CBB2E6A91FE8A512F973A41DA2327602C8514C82E88763DD`。原文件在 canonical main 工作区未跟踪，本轮保留原样证据快照；正式纳入时不重新改写该合同，不同时实施其 Surface sections。

## 3. 合入前只需哪些 targeted changes

### F1 — existing target authority 的 fail-closed validation

复用 StateDefinitionRegistry / longitudinal target resolution 与当前 affect definitions，验证 dimension、owner/scope、operation。Fast 必须是合法 affect delta；Slow 必须是合法 longitudinal absolute target，禁止通过 source_ref 前缀伪装。非法或 stale required target 整组拒绝，不返回含非法成员的 MAPPED。

RED 至少固定主报告两例：affect target 的 proposed_value，以及 Slow target 的 delta；再覆盖不存在的 definition、foreign owner/scope。确认合法四 recipe 和 history/Slow gate outputs 原样。不要改 AcceptedAppraisal；不要在 Dynamics 加猜测性的 target rewrite；不要增加第二 projector。

### F2 — dependency identity 的明确版本绑定

在 projector/journal input 绑定同一 existing Persona owner/version 与被消费 StateDefinitions/recipe revision。不能只靠 caller 传任意 tuple，也不能依赖默认空参数宣称已有版本失效。明确哪些 consumed definition 进入 key；版本变更建立新 evaluation，旧记录保留，绝不意味着 corrective effect application。

RED 覆盖 profile version/definition revision 变化的失效、相同绑定的跨进程/restart 复用、不相关 fast state/turn 不失效。可按已消费的版本语义明确测试；不动 accepted payload、不新增 behavioral schema、不实现新 gain。

### 原样保留的 numerical seam

`AppraisalProjector` event output = raw recipe amount × candidate confidence；history cap 独立；salience 原样给 gate；`DynamicsEngine` 乘 sensitivity 一次。Slow absolute target 原样送 HomeostasisGate/Slow writer。v1.1 不要求在 projector 新增 sensitivity/disposition multiplier，本次 probe 已验证现有合法路径。

## 4. Y 之后的 W2 工作包

1. 将生产 `assemble→legacy map` 接为已有 Producer-owned acceptance→journal→唯一 projector/result；保留 legacy no-appraisal 清晰标记。TransitionResult 携带 accepted appraisals 和 projection refs，脱离 impulses/accepted_events coverage gating。
2. 在既有 orchestrator/backend transaction 接 application identity/outcomes/receipts；对已授权 mixed group 做 validation/staging、failure rollback、post-commit publication。保留 legacy Slow gate denial 后 Fast-only 的行为；required-joint 组失败时全部不应用。
3. 同 interaction retry/restart 重用 evaluation，不重跑 semantic model、不重复 effect；跨 interaction 不能把旧 evaluation 当新 effect。故障注入覆盖 journal 失败、evaluation 已存但 state 未提交、receipt/state commit 前后、abort。
4. 按 accepted ADR 添加 bounded COGNITIVE_MEANING read view：compiler input、eligibility、source lineage、budget/deny reasons、renderer quoted semantic data、retry 同 item。验证 provider 可见 bytes，而非只看 telemetry 或 compiler object；Host/proactive 如有摘要截断只记录并补这条语义适配，不启动 live Xiyue。

这是原 ADR W2 的增量。当前已有 multi-effect proposal、evaluation restart cache、generic context budget/retry、vector commit、Slow staging、turn marker；复用这些，不能把它们写成 appraisal application exactly-once 已完成。详见主报告逐项 DONE/PARTIAL/NOT_STARTED 表。

Surface prerequisite status：**NOT SATISFIED**。本计划不改 Persona behavioral schema、Intent Surface controls、Body Surface exposure，不实现 Surface、Reality、LCE、Memory 或 OW。未来 Surface implementation 要另按 v1.1 的完整独立 gate 执行。

## 5. 验证与交付边界

- W1 原分支：`python -m pytest tests/late_projection tests/emotional_transition -q -rs`。
- 候选/修复分支：`python -m pytest tests/late_projection tests/emotional_transition tests/dynamics tests/expression -q -rs`，再补 F1/F2 RED→GREEN、D1/gain probe。
- main 和候选分支分别跑 `python -m pytest -q -rs`，对比 failures 的相同 node/reason，区分 ENVIRONMENT / BASELINE / NEW REGRESSION。
- review 必须读取最终修复 SHA，不以本轮 `6e027cd` 的 green tests 覆盖 F1/F2。任何 skip/xfail 保留 ownership；不改 main 使旧 W1 通过。

临时分支 `w/mr-late-projection-mainline-reconcile-01`，base `1777284`，source replay HEAD `6e027cd`。本轮审计文档及证据是附加非生产材料，最终工作区状态与 suite 输出见主报告。F1/F2 留给明确的 bounded fix；本轮没有 merge、push 或部署。

本轮实际 full-suite baseline：main 2889 passed；replay 3039 passed；两边均 11 skipped、4 deselected、1 existing G28 xfailed，exit 0。W1 targeted 253 passed，replay Appraisal/Effects/Dynamics/Expression/late_projection targeted 406 passed。既有 suite 无新增失败，但不覆盖已复现的 F1，因此不能提前将 `6e027cd` 或其 docs-only successor 认证为 Y。
