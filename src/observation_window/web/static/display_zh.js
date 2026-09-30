/* OW-RESPONSIVE-I18N-ZH-V1 — Centralized zh-CN display vocabulary.
 *
 * HARD LOCALIZATION BOUNDARY (ticket §1/§2/§22):
 * - Canonical values (dimension keys, origin codes, stage codes, IDs,
 *   telemetry payloads) are NEVER mutated. Mappings here are display-only.
 * - Unknown canonical values fail safe: the raw canonical value is shown,
 *   never blank, never an invented translation.
 * - Adding future locales (en, pt) means adding a sibling dictionary
 *   module with the same interface — components keep calling these
 *   functions and never hardcode language into render logic.
 */
(function (global) {
  "use strict";

  /* Canonical dimension key → display name (§4/§5) */
  var DIMENSIONS = {
    "agent.affect.irritation": "烦躁",
    "agent.affect.anxiety": "焦虑",
    "agent.affect.excitement": "兴奋",
    "agent.affect.longing": "思念",
    "agent.affect.closeness_craving": "亲近渴望",
    "agent.affect.sharing_urge": "分享冲动",
    "agent.affect.curiosity": "好奇",
    "agent.affect.restlessness": "躁动",
    "agent.affect.social_pull": "社交牵引",
    "agent.affect.diligence_pressure": "责任压力",
    "agent.affect.introspective_pull": "内省牵引",
    "agent.affect.sadness": "悲伤",
    "agent.affect.anger": "愤怒",
    "agent.affect.fatigue": "疲劳",
    "agent.longitudinal.relationship_security": "关系安全感",
    "agent.longitudinal.trust": "信任",
    "agent.longitudinal.emotional_safety": "情感安全感",
    "agent.longitudinal.self_efficacy": "自我效能",
    "agent.longitudinal.curiosity_trait": "长期好奇倾向",
    "user.sleep.phase": "睡眠阶段",
    "user.location": "所在位置",
    "user.activity": "当前活动"
  };

  /* Provenance / status display projection (§6) */
  var ORIGINS = {
    "EVENT EFFECT": "事件效应",
    "DYNAMICS / RECOVERY": "动态恢复",
    "SLOW PLASTICITY": "慢状态塑性",
    "UNCHANGED": "未变化",
    "UNAVAILABLE": "不可用",
    "ABORTED": "已中止",
    "AVAILABLE": "可用",
    "COMMITTED": "已提交",
    "REJECT": "拒绝",
    "FAST_APPLY": "快状态应用",
    "SLOW_ACCEPT": "慢状态接受",
    "NOT PERSISTED": "未持久化",
    "UNAVAILABLE / NOT PERSISTED": "不可用 / 未持久化"
  };

  /* All visible statuses (OW-I18N-PROJECTION-COMPLETENESS-V1 §7) */
  var STATUS = {
    "active": "活跃",
    "improving": "改善中",
    "completed": "已完成",
    "cancelled": "已取消",
    "archived": "已归档",
    "open": "进行中",
    "abandoned": "已放弃",
    "candidate": "候选",
    "deferred": "已延后",
    "allowed": "已允许",
    "blocked": "已阻止",
    "idle": "空闲",
    "suppressed": "已抑制",
    "delivered": "已送达",
    "released": "已释放",
    "consumed": "已消费",
    "reserved": "已预留",
    "created": "已创建",
    "current": "当前",
    "past": "过去",
    "future": "未来",
    "unresolved": "未解析",
    "asserted": "已断言",
    "planned": "计划",
    "tentative": "暂定",
    "estimated": "估计",
    "inferred": "推断",
    "instant": "时点",
    "day": "日期",
    "daypart": "时段",
    "range": "时间范围",
    "morning": "上午",
    "afternoon": "下午",
    "evening": "傍晚",
    "night": "夜间",
    "point": "单点",
    "interval": "区间",
    "open_interval": "开放区间",
    "explicit_search": "显式检索",
    "automatic": "自动召回",
    "spontaneous": "自发召回",
    "lce": "LCE 纵向认知",
    "not established": "尚未建立",
    "NOT ESTABLISHED": "尚未建立",
    "superseded": "已取代",
    "resolved": "已解决",
    "expired": "已过期",
    "AVAILABLE": "可用",
    "UNAVAILABLE": "不可用",
    "NOT PERSISTED": "未持久化",
    "UNAVAILABLE / NOT PERSISTED": "不可用 / 未持久化",
    "ACCEPTED": "已接受",
    "PROPOSED": "已提议",
    "EXECUTED": "已执行",
    "COMMITTED": "已提交",
    "ABORTED": "已中止",
    "REJECT": "已拒绝",
    "REJECTED": "已拒绝",
    "ABSTAIN": "已弃权",
    "ABSTAINED": "已弃权",
    "UNKNOWN": "未知",
    /* debug surface statuses (zh-primary, raw stays in title/secondary) */
    "PASS": "通过",
    "NONE": "无",
    "NOT_RUN": "未运行",
    "NOT RUN": "未运行",
    "ERROR": "错误",
    "SKIPPED": "已跳过",
    "EMPTY": "空",
    "READY": "就绪",
    "DEGRADED": "降级",
    "NOT_READY": "未就绪",
    "ACTIVE": "运行中",
    "INACTIVE": "未启用",
    "ENABLED": "已启用",
    "DISABLED": "已禁用",
    "ABSENT": "未配置",
    "OFFLINE": "离线",
    "ONLINE": "在线",
    "IMPLEMENTED": "已实现",
    "NOT_IMPLEMENTED": "未实现",
    "IMPLEMENTED_EXPLICIT_WORKER": "已实现（显式后台工作器）",
    "PROVISIONAL": "暂定配置",
    "VALID": "有效",
    "INVALID": "无效",
    "NONE (NOT READY)": "无（未就绪）",
    "NOT RUNNING": "未运行",
    "PRESENT": "已持久化",
    "MISSING": "缺失",
    "RECORDED": "已记录",
    /* composition flags (§4) */
    "ON": "开启",
    "OFF": "关闭"
  };

  /* Causal pipeline stages (§7) */
  var STAGES = {
    "USER INPUT": "用户输入",
    "SEMANTIC INTERPRETATION": "语义识别",
    "APPRAISAL": "认知评估",
    "EFFECT / IMPULSES": "效应 / 冲量",
    "HOMEOSTASIS GATE": "稳态门控",
    "STATE DELTAS": "状态变化",
    "SLOW STATE DECISION": "慢状态决策",
    "ASSISTANT RESPONSE": "助手回复",
    "Slow state BEFORE": "慢状态 · 变化前",
    "Slow state AFTER": "慢状态 · 变化后",
    /* live-trace pipeline stage names (unknown names fail safe to raw) */
    "message received": "消息接收",
    "Observation": "观察写入",
    "SemanticCandidate": "语义候选",
    "SemanticAbstain": "语义弃权",
    "C1 slow read": "C1 慢状态读取",
    "USER_INGRESS": "用户输入接收",
    "BODY_SEMANTIC_INPUT": "Body 语义输入",
    "SEMANTIC_CANDIDATE": "语义候选",
    "SEMANTIC_ABSTAIN": "语义弃权",
    "SEMANTIC_ERROR": "语义错误",
    "SEMANTIC_EXECUTION": "语义执行",
    "REALITY_ELIGIBILITY": "现实状态准入",
    "APPRAISAL": "语义评估",
    "APPRAISAL_ERROR": "评估错误",
    "EFFECT": "情绪效应",
    "IMPULSE": "状态冲量",
    "AFFECT_CONTRIBUTION": "情绪贡献",
    "HOMEOSTASIS": "稳态门控",
    "SLOW_DECISION": "长期状态决策",
    "SLOW_WRITE": "长期状态写入",
    "STATE_TRANSITION": "状态转换",
    "MEMORY_RETRIEVAL": "记忆检索",
    "MEMORY_CONTEXT_SELECTION": "记忆上下文筛选",
    "THREAD_UPDATE": "主题线索更新",
    "THREAD_COMPILE": "主题线索编译",
    "LCE_BACKGROUND_PASS": "LCE 后台处理",
    "LCE_PROJECTION": "LCE 投影",
    "DECISION_MODEL": "决策模型",
    "CONTEXT_ASSEMBLY": "上下文装配",
    "INTENT_EVALUATION": "意图评估",
    "ACTION_POLICY": "行动策略",
    "INSPIRATION_RESERVATION": "灵感材料预留",
    "BODY_HANDOFF": "交给 Body",
    "ASSISTANT_RESPONSE": "助手回复",
    "TURN_COMMIT": "轮次提交",
    "TURN_ABORT": "轮次中止"
  };

  /* Disposition / gate outcomes (displayDisposition) */
  var DISPOSITIONS = {
    "ACCEPT": "接受",
    "REJECT": "拒绝",
    "ABSTAIN": "弃权",
    "ABSTAINED": "弃权",
    "APPLIED": "已应用",
    "PENDING": "待定"
  };

  /* Scope domains (displayScope) */
  var SCOPES = {
    "agent": "智能体",
    "user": "用户",
    "persona": "人设",
    "relationship": "关系",
    "world": "世界",
    "interaction": "交互"
  };

  /* Known semantic event kinds + trace stage codes (§8: zh label, raw secondary).
     Unknown kinds fail safe to the raw code. */
  var EVENT_KINDS = {
    "SEMANTIC_CANDIDATE": "语义事件",
    "SEMANTIC_ABSTAIN": "语义弃算",
    "TURN_ABORT": "轮次中止",
    "TURN_COMMIT": "轮次提交",
    "HOMEOSTASIS": "稳态门控",
    "APPRAISAL": "认知评估",
    "USER_APPRECIATION": "用户肯定",
    "USER_CORRECTION": "用户纠正",
    "DISTRESS_SHARING": "困扰倾诉",
    "RELIEF": "如释重负"
  };

  /* Backend canonical codes -> zh-CN display projection.
     These maps are presentation-only. Canonical values remain unchanged. */
  var MODALITY = {
    "asserted": "已断言",
    "planned": "计划",
    "tentative": "暂定",
    "estimated": "估计",
    "inferred": "推断"
  };

  var SEMANTIC_RELATIONS = {
    "current": "当前",
    "past": "过去",
    "future": "未来",
    "unresolved": "未解析"
  };

  var SEMANTIC_PRECISIONS = {
    "instant": "时点",
    "day": "日期",
    "daypart": "时段",
    "range": "时间范围",
    "unresolved": "未解析"
  };

  var DAYPARTS = {
    "morning": "上午",
    "afternoon": "下午",
    "evening": "傍晚",
    "night": "夜间"
  };

  var WINDOW_KINDS = {
    "point": "单点",
    "interval": "区间",
    "open_interval": "开放区间"
  };

  var MEMORY_LIFECYCLE = {
    "active": "活跃",
    "superseded": "已取代",
    "archived": "已归档"
  };

  var THREAD_STATUS = {
    "open": "进行中",
    "resolved": "已解决",
    "abandoned": "已放弃"
  };

  var INTENT_STATUS = {
    "candidate": "候选",
    "deferred": "已延后",
    "allowed": "已允许",
    "blocked": "已阻止",
    "expired": "已过期",
    "completed": "已完成",
    "superseded": "已取代"
  };

  var INTENT_KINDS = {
    "proactive_contact": "主动联系",
    "proactive_share": "主动分享",
    "inquiry": "探索提问",
    "inquiry_exploration": "探索提问",
    "follow_up": "后续跟进",
    "activity_wake": "活动唤醒",
    "boundary_confrontation": "边界回应",
    "initiative_suppression": "主动性抑制",
    "follow_up_persistence": "持续跟进",
    "creative_expression": "创意表达",
    "routine_maintenance": "日常维持"
  };

  var ACTION_DECISIONS = {
    "ALLOW": "允许",
    "DENY": "拒绝",
    "DEFER": "延后",
    "allow": "允许",
    "deny": "拒绝",
    "defer": "延后"
  };

  var COGNITIVE_MODES = {
    "active": "在线交互",
    "introspective": "内省",
    "daydream": "白日梦",
    "sleep": "睡眠",
    "dream": "梦境",
    "ACTIVE": "在线交互",
    "INTROSPECTIVE": "内省",
    "DAYDREAM": "白日梦",
    "SLEEP": "睡眠",
    "DREAM": "梦境"
  };

  var AUTHORITY_CLASSES = {
    "AUTHORITATIVE": "权威数据",
    "DERIVED": "派生认知",
    "TRANSIENT": "临时执行数据",
    "OPERATIONS": "运行数据",
    "OBSERVATION_ONLY": "仅观察",
    "CURRENT_LIKE": "当前有效",
    "TERMINAL": "终态",
    "VALIDITY_OUTCOME": "有效期结果"
  };

  var RUNTIME_COMPONENTS = {
    "xiyue / Hermes": "xiyue / Hermes",
    "MR Core": "MR 核心",
    "Memory": "记忆系统",
    "LCE Binding": "LCE 接入",
    "Observation Window": "观察窗",
    "DecisionModel": "决策模型",
    "Background LCE": "后台 LCE",
    "Cognitive Mode Ctrl": "认知模式控制器",
    "Semantic Provider": "语义提供器",
    "Appraisal Provider": "评估提供器",
    "Slow Writer": "长期状态写入器"
  };

  var SOURCE_KINDS = {
    "user_statement": "用户陈述",
    "assistant_statement": "助手陈述",
    "inference": "推断",
    "observation": "观察",
    "external": "外部来源"
  };

  var BOOLS = {
    "true": "是",
    "false": "否",
    "YES": "是",
    "NO": "否",
    "True": "是",
    "False": "否"
  };

  var PIPELINE_CODES = {
    "evidence": "证据",
    "observation": "观察",
    "transition": "状态转换",
    "appraisal": "评估",
    "action": "行动",
    "interaction": "交互",
    "event": "事件",
    "history": "历史",
    "recovery": "恢复",
    "rule": "规则",
    "decision": "决策",
    "contribution": "贡献",
    "fast_apply": "应用到快状态",
    "fast_only": "仅应用到快状态",
    "slow_accept": "接受为长期状态贡献",
    "slow_damp": "长期状态贡献衰减处理",
    "reject": "拒绝",
    "accept": "接受",
    "rewrite": "重写",
    "positive": "正向",
    "negative": "负向",
    "neutral": "中性",
    "unspecified": "未指定",
    "relational_security": "关系安全",
    "authoritative": "权威",
    "derived": "派生",
    "transient": "临时",
    "primary": "主要",
    "secondary": "次要",
    "direct": "直接",
    "indirect": "间接",
    "supported": "有支持",
    "unsupported": "无支持",
    "action": "行动",
    "fact": "事实",
    "cognitive_meaning": "认知含义",
    "inspiration": "灵感",
    "internal_state": "内部状态",
    "policy_constraint": "策略约束",
    "persona_style": "人设风格",
    "prior_expression": "先前表达",
    "rewrite_guidance": "重写指导",
    "surface_guidance": "表层表达指导",
    "surface_control": "表层表达控制"
  };

  /* Known reason codes → primary Chinese explanation (§6).
     Unknown reasons fail safe to the raw value — never guessed. */
  var REASONS = {
    "semantic_result_not_persisted_to_durable_schema": "语义结果未持久化到可回溯存储",
    "appraisal_details_not_persisted_to_durable_schema": "评估详情未持久化到可回溯存储",
    "not persisted to durable schema": "未持久化到可回溯存储",
    "HISTORICAL (telemetry journal was inactive for this turn)": "历史轮次（本轮发生时观察遥测日志尚未启用）",
    "HISTORICAL": "历史轮次",
    "pre-journal historical": "观察日志启用前的历史轮次",
    "assistant linkage unavailable": "助手回复链路不可用",
    "turn aborted": "轮次已中止",
    "Turn was aborted before commit": "轮次在提交前被中止",
    "valid semantic abstention": "有效语义弃权",
    "no impulses generated or not persisted": "未生成冲量或未持久化",
    "homeostasis disposition not persisted": "稳态门控结果未持久化",
    "Slow state BEFORE": "慢状态 · 变化前",
    "Slow state AFTER": "慢状态 · 变化后",
    /* pipeline negative reason codes (raw secondary kept at call site) */
    "no_prior_slow_state": "尚无先前慢状态",
    "no_slow_write": "本轮无慢状态写入",
    "not_in_state_db": "不在状态数据库中",
    "allowed": "策略允许执行",
    "origin_mismatch": "运行时来源不一致",
    "not_yet_earliest": "尚未到最早执行时间",
    "intent_expired": "意图已过期",
    "unsupported_intent_kind": "不支持的意图类型",
    "action_unavailable": "当前动作不可用",
    "required_resource_unavailable": "所需资源不可用",
    "duplicate_context_fact": "上下文事实重复",
    "active_conversation": "当前仍在对话中",
    "pending_reply": "仍有待回复消息",
    "proactive_cooldown": "主动联系仍在冷却期",
    "malformed_conversation_active": "对话状态字段无效",
    "malformed_pending_reply": "待回复状态字段无效",
    "malformed_last_proactive_at": "最近主动联系时间无效",
    "missing_media_counter": "缺少媒体计数",
    "malformed_media_counter": "媒体计数无效",
    "media_budget_exhausted": "媒体配额已用尽",
    "inactive_memory": "记忆已非活跃状态",
    "dont_surface": "已设置为不主动浮现",
    "digested": "已被更高层认知消化",
    "proactive_intent_allowed": "主动意图已获允许"
  };

  function displayReason(value) { return lookup(REASONS, value); }

  /* Prefix/fallback substring rules for long backend reason strings. */
  function displayReasonSmart(value) {
    if (value === null || value === undefined) return value;
    var key = String(value);
    var direct = lookup(REASONS, key);
    if (direct !== key) return direct;
    if (key.indexOf("telemetry journal was inactive") !== -1) return "历史轮次（本轮发生时观察遥测日志尚未启用）" + suffixParen(key);
    if (key.indexOf("HISTORICAL") !== -1) return "历史轮次" + suffixParen(key);
    if (key.indexOf("linkage unavailable") !== -1) return "助手回复链路不可用" + suffixParen(key);
    if (key.indexOf("not persisted to durable") !== -1) return "未持久化到可回溯存储" + suffixParen(key);
    return key;
  }

  function suffixParen(key) {
    var m = key.match(/\(([^)]*)\)\s*$/);
    return m ? "（" + m[1] + "）" : "";
  }

  /* Provenance badges (§8): DB filenames stay untranslated. */
  function displayProvenance(value) {
    if (value === null || value === undefined || value === "") return value;
    var v = String(value);
    var upper = v.toUpperCase();
    if (upper === "UNAVAILABLE") return "不可用";
    if (upper.indexOf("CANONICAL") === 0) {
      var rest = v.slice("CANONICAL".length).replace(/^[\s—―-]+/, "");
      var named = {
        "FACTS.SQLITE": "权威事实 · facts.sqlite",
        "COGNITION_STATE.SQLITE": "权威状态 · cognition_state.sqlite"
      }[rest.toUpperCase()];
      return named || ("权威 · " + rest.toLowerCase());
    }
    if (upper.indexOf("OBSERVER TELEMETRY") === 0) {
      var rest2 = v.slice("OBSERVER TELEMETRY".length).replace(/^[\s—―-]+/, "");
      return rest2 ? "观察遥测 · " + rest2 : "观察遥测";
    }
    return v;
  }

  /* Shared product UI labels for JS-rendered chrome (displayLabel) */
  var LABELS = {
    "state": "状态",
    "moments": "交互",
    "debug": "调试",
    "refresh": "刷新",
    "causalInspector": "因果检查器",
    "stateLedger": "状态台账",
    "liveTrace": "实时链路",
    "active": "运行中",
    "committedTurns": "已提交轮次",
    "lastTurn": "最近轮次",
    "focus": "单维度",
    "compare": "对比",
    "current": "当前",
    "lastDelta": "最近变化",
    "range": "范围",
    "selectedMoment": "关键轮次",
    "longTermState": "长期状态",
    "accumulatedSelf": "累积自我",
    "notEstablished": "尚未建立",
    "noStateChange": "本轮无状态变化",
    "inspectCausalTrace": "查看因果链",
    "canonicalSlowState": "规范化慢状态",
    "runtime": "运行时",
    "runtimeSelector": "运行时",
    "now": "现在",
    "turnExplorer": "交互",
    "memory": "记忆",
    "recall": "检索",
    "behaviour": "行为",
    "background": "后台",
    "state": "状态",
    "runtime": "运行",
    "logs": "日志",
    "debug": "调试",
    "readyAt": "就绪时间",
    "semanticProvider": "语义提供器",
    "appraisalProvider": "评估提供器",
    "slowWriter": "长期状态写入器",
    "observationWindow": "观察窗",
    "bodySemantics": "Body 语义",
    "canonicalMemory": "权威记忆",
    "threads": "主题线索",
    "lceBaselines": "LCE 纵向认知",
    "intent": "意图",
    "actionPolicy": "行动策略"
  };

  function lookup(map, value) {
    if (value === null || value === undefined) return value;
    var key = String(value);
    return Object.prototype.hasOwnProperty.call(map, key) ? map[key] : value;
  }

  function displayDimension(value) { return lookup(DIMENSIONS, value); }
  function displayOrigin(value) { return lookup(ORIGINS, value); }
  function displayStatus(value) { return lookup(STATUS, value); }
  function displayStage(value) { return lookup(STAGES, value); }
  function displayDisposition(value) { return lookup(DISPOSITIONS, value); }
  function displayScope(value) { return lookup(SCOPES, value); }
  function displayEventKind(value) { return lookup(EVENT_KINDS, value); }
  function displayLabel(key) { return lookup(LABELS, key); }

  /* Canonical short label for a long dimension key, e.g. "affect.烦躁" is NOT
     used — debug surfaces show the raw key; this helper is for compact
     product display only. Accepts both the full canonical key and the bare
     short segment (e.g. "irritation"), always failing safe to the input. */
  var SHORT_DIMENSIONS = {};
  Object.keys(DIMENSIONS).forEach(function (k) {
    SHORT_DIMENSIONS[k.split(".")[2]] = DIMENSIONS[k];
  });
  function shortDimension(value) {
    var d = displayDimension(value);
    if (d !== value) return d;
    var key = String(value || "");
    if (Object.prototype.hasOwnProperty.call(SHORT_DIMENSIONS, key)) {
      return SHORT_DIMENSIONS[key];
    }
    var parts = key.split(".");
    return parts[parts.length - 1] || value;
  }

  /* Text-level display projection: replaces known canonical dimension keys
     inside backend-provided summary strings (display only — the underlying
     payload is untouched). Unknown segments pass through unchanged. */
  function displayDimensionText(text) {
    if (text === null || text === undefined) return text;
    var out = String(text);
    Object.keys(DIMENSIONS).forEach(function (key) {
      var short = key.split(".")[2] || key;
      var escaped = short.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
      var re = new RegExp("\\b" + escaped + "\\b", "g");
      out = out.replace(re, DIMENSIONS[key]);
    });
    return out;
  }

  function displayModality(value) { return lookup(MODALITY, value); }
  function displaySemanticRelation(value) { return lookup(SEMANTIC_RELATIONS, value); }
  function displaySemanticPrecision(value) { return lookup(SEMANTIC_PRECISIONS, value); }
  function displayDaypart(value) { return lookup(DAYPARTS, value); }
  function displayWindowKind(value) { return lookup(WINDOW_KINDS, value); }
  function displayMemoryLifecycle(value) { return lookup(MEMORY_LIFECYCLE, value); }
  function displayThreadStatus(value) { return lookup(THREAD_STATUS, value); }
  function displayIntentStatus(value) { return lookup(INTENT_STATUS, value); }
  function displayIntentKind(value) { return lookup(INTENT_KINDS, value); }
  function displayActionDecision(value) { return lookup(ACTION_DECISIONS, value); }
  function displayCognitiveMode(value) { return lookup(COGNITIVE_MODES, value); }
  function displayAuthorityClass(value) { return lookup(AUTHORITY_CLASSES, value); }
  function displayRuntimeComponent(value) { return lookup(RUNTIME_COMPONENTS, value); }
  function displaySourceKind(value) { return lookup(SOURCE_KINDS, value); }
  function displayBoolean(value) { return lookup(BOOLS, value); }

  function displayCode(value) {
    if (value === null || value === undefined) return value;
    var maps = [
      DIMENSIONS, STATUS, STAGES, DISPOSITIONS, SCOPES, EVENT_KINDS,
      MODALITY, SEMANTIC_RELATIONS, SEMANTIC_PRECISIONS, DAYPARTS,
      WINDOW_KINDS, MEMORY_LIFECYCLE, THREAD_STATUS, INTENT_STATUS,
      INTENT_KINDS, ACTION_DECISIONS, COGNITIVE_MODES, AUTHORITY_CLASSES,
      RUNTIME_COMPONENTS, SOURCE_KINDS, BOOLS, PIPELINE_CODES, REASONS, ORIGINS
    ];
    var key = String(value);
    for (var i = 0; i < maps.length; i += 1) {
      if (Object.prototype.hasOwnProperty.call(maps[i], key)) return maps[i][key];
    }
    return value;
  }

  /* Chinese-friendly time presentation (§21): "2026-09-05T13:04:30..." →
     "09-05 13:04:30". Pure display slicing of the existing UTC ISO string —
     no timezone authority change, no Date re-interpretation. */
  function fmtTime(iso) {
    if (!iso) return "—";
    var s = String(iso).replace("T", " ");
    // "2026-09-05 13:04:30[.fff][+00:00]" → "09-05 13:04:30"
    var m = s.match(/^\d{4}-(\d{2}-\d{2}) (\d{2}:\d{2}:\d{2})/);
    return m ? (m[1] + " " + m[2]) : s;
  }

  global.OWDisplay = {
    displayDimension: displayDimension,
    displayOrigin: displayOrigin,
    displayStatus: displayStatus,
    displayStage: displayStage,
    displayDisposition: displayDisposition,
    displayScope: displayScope,
    displayEventKind: displayEventKind,
    displayLabel: displayLabel,
    displayReason: displayReasonSmart,
    displayProvenance: displayProvenance,
    displayCode: displayCode,
    displayModality: displayModality,
    displaySemanticRelation: displaySemanticRelation,
    displaySemanticPrecision: displaySemanticPrecision,
    displayDaypart: displayDaypart,
    displayWindowKind: displayWindowKind,
    displayMemoryLifecycle: displayMemoryLifecycle,
    displayThreadStatus: displayThreadStatus,
    displayIntentStatus: displayIntentStatus,
    displayIntentKind: displayIntentKind,
    displayActionDecision: displayActionDecision,
    displayCognitiveMode: displayCognitiveMode,
    displayAuthorityClass: displayAuthorityClass,
    displayRuntimeComponent: displayRuntimeComponent,
    displaySourceKind: displaySourceKind,
    displayBoolean: displayBoolean,
    shortDimension: shortDimension,
    displayDimensionText: displayDimensionText,
    fmtTime: fmtTime,
    /* Dictionaries exposed read-only for tests/debug */
    DICTS: {
      DIMENSIONS: DIMENSIONS,
      ORIGINS: ORIGINS,
      STATUS: STATUS,
      STAGES: STAGES,
      DISPOSITIONS: DISPOSITIONS,
      SCOPES: SCOPES,
      EVENT_KINDS: EVENT_KINDS,
      LABELS: LABELS,
      REASONS: REASONS,
      MODALITY: MODALITY,
      SEMANTIC_RELATIONS: SEMANTIC_RELATIONS,
      SEMANTIC_PRECISIONS: SEMANTIC_PRECISIONS,
      DAYPARTS: DAYPARTS,
      WINDOW_KINDS: WINDOW_KINDS,
      MEMORY_LIFECYCLE: MEMORY_LIFECYCLE,
      THREAD_STATUS: THREAD_STATUS,
      INTENT_STATUS: INTENT_STATUS,
      INTENT_KINDS: INTENT_KINDS,
      ACTION_DECISIONS: ACTION_DECISIONS,
      COGNITIVE_MODES: COGNITIVE_MODES,
      AUTHORITY_CLASSES: AUTHORITY_CLASSES,
      RUNTIME_COMPONENTS: RUNTIME_COMPONENTS,
      SOURCE_KINDS: SOURCE_KINDS,
      PIPELINE_CODES: PIPELINE_CODES
    }
  };
})(window);
