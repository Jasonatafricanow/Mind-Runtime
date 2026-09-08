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
    "agent.longitudinal.relationship_security": "关系安全感"
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
    "C1 slow read": "C1 慢状态读取"
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
    "not_in_state_db": "不在状态数据库中"
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
    "runtimeSelector": "Runtime / 运行时"
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
      REASONS: REASONS
    }
  };
})(window);
