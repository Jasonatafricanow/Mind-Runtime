/* OW-MULTI-AGENT-BINDING-W2E-V1 — Centralized Runtime URL Scope Presentation Seam.
 *
 * Provides authoritative URL query parsing, binding-aware API path adapter,
 * navigation link propagation, response identity verification, and central fetch seam.
 *
 * HARD CONSTRAINTS:
 * - Public binding_id grammar: ^[a-z0-9][a-z0-9-]{0,63}$
 * - Single query parameter cardinality: ?runtime=a&runtime=b fails closed (AMBIGUOUS_RUNTIME_SELECTION)
 * - Empty parameter: ?runtime= fails closed (EMPTY_RUNTIME_SELECTION)
 * - Absent parameter: LEGACY mode preserved; no W2-F default migration or redirect
 * - Response binding_id must match requested runtime: RUNTIME_IDENTITY_MISMATCH fail closed
 * - Read-only indicator: text-safe rendering, strictly NO selector/dropdown
 */

(function (global) {
  "use strict";

  var RUNTIME_GRAMMAR = /^[a-z0-9][a-z0-9-]{0,63}$/;

  /**
   * Parse runtime selection from URL search string.
   * @param {string} [searchString] - Defaults to window.location.search
   * @returns {{mode: 'LEGACY'|'SCOPED'|'INVALID', bindingId?: string|null, reason?: string, detail?: string}}
   */
  function parsePageRuntime(searchString) {
    if (searchString === undefined || searchString === null) {
      if (typeof window !== "undefined" && window.location) {
        searchString = window.location.search || "";
      } else {
        searchString = "";
      }
    }

    var str = String(searchString).trim();
    if (str.startsWith("?")) {
      str = str.slice(1);
    }
    if (!str) {
      return { mode: "LEGACY", bindingId: null };
    }

    // Split on '&' and parse keys/values
    var pairs = str.split("&");
    var runtimeValues = [];

    for (var i = 0; i < pairs.length; i++) {
      if (!pairs[i]) continue;
      var eqIdx = pairs[i].indexOf("=");
      var rawKey, rawVal;
      if (eqIdx >= 0) {
        rawKey = pairs[i].slice(0, eqIdx);
        rawVal = pairs[i].slice(eqIdx + 1);
      } else {
        rawKey = pairs[i];
        rawVal = "";
      }

      var key;
      try {
        key = decodeURIComponent(rawKey.replace(/\+/g, " "));
      } catch (e) {
        key = rawKey;
      }

      if (key === "runtime") {
        var val;
        try {
          val = decodeURIComponent(rawVal.replace(/\+/g, " "));
        } catch (e) {
          val = rawVal;
        }
        runtimeValues.push(val);
      }
    }

    if (runtimeValues.length === 0) {
      return { mode: "LEGACY", bindingId: null };
    }

    if (runtimeValues.length > 1) {
      return {
        mode: "INVALID",
        reason: "AMBIGUOUS_RUNTIME_SELECTION",
        detail: "Multiple runtime query parameters found in URL. Disambiguation is prohibited."
      };
    }

    var candidate = runtimeValues[0];
    if (candidate === "") {
      return {
        mode: "INVALID",
        reason: "EMPTY_RUNTIME_SELECTION",
        detail: "Runtime query parameter cannot be empty."
      };
    }

    if (!RUNTIME_GRAMMAR.test(candidate)) {
      return {
        mode: "INVALID",
        reason: "MALFORMED_RUNTIME_SELECTION",
        detail: "Runtime query parameter '" + candidate + "' does not match public grammar ^[a-z0-9][a-z0-9-]{0,63}$."
      };
    }

    return {
      mode: "SCOPED",
      bindingId: candidate
    };
  }

  /**
   * Build API path adapted for active runtime selection.
   * @param {Object} selection - PageRuntimeSelection from parsePageRuntime
   * @param {string} resourcePath - e.g. '/api/overview', '/api/turns?limit=20'
   * @returns {string}
   */
  function apiPath(selection, resourcePath) {
    if (!selection || selection.mode === "LEGACY") {
      return resourcePath;
    }
    if (selection.mode === "INVALID") {
      throw new Error("Cannot construct apiPath with INVALID runtime selection: " + (selection.reason || ""));
    }
    if (selection.mode === "SCOPED") {
      var encId = encodeURIComponent(selection.bindingId);
      if (resourcePath.startsWith("/api/")) {
        return "/api/runtime-bindings/" + encId + "/" + resourcePath.slice(5);
      } else if (resourcePath.startsWith("api/")) {
        return "api/runtime-bindings/" + encId + "/" + resourcePath.slice(4);
      } else if (resourcePath.startsWith("http://") || resourcePath.startsWith("https://")) {
        try {
          var u = new URL(resourcePath);
          if (u.pathname.startsWith("/api/")) {
            u.pathname = "/api/runtime-bindings/" + encId + "/" + u.pathname.slice(5);
            return u.toString();
          }
        } catch (e) {}
      }
      throw new Error("apiPath: resource path does not start with /api/: " + resourcePath);
    }
    return resourcePath;
  }

  /**
   * Return URL with runtime query parameter preserved / added.
   * Preserves existing query params and anchor hash.
   * @param {string} url - Target URL or href
   * @param {Object} selection - PageRuntimeSelection
   * @returns {string}
   */
  function withRuntime(url, selection) {
    if (!selection || selection.mode !== "SCOPED" || !selection.bindingId) {
      return url;
    }
    if (!url || typeof url !== "string") {
      return url;
    }
    if (url.startsWith("javascript:") || url.startsWith("mailto:") || url.startsWith("#")) {
      return url;
    }

    try {
      var isAbsolute = url.startsWith("http://") || url.startsWith("https://");
      var base = isAbsolute ? undefined : "http://dummy.local";
      var parsed = new URL(url, base);

      parsed.searchParams.set("runtime", selection.bindingId);

      if (isAbsolute) {
        return parsed.toString();
      }
      return parsed.pathname + parsed.search + parsed.hash;
    } catch (e) {
      return url;
    }
  }

  /**
   * Propagate runtime query to all internal links in the DOM.
   * @param {Object} selection - PageRuntimeSelection
   * @param {HTMLElement|Document} [root] - Defaults to document
   */
  function propagateNavigation(selection, root) {
    if (!selection || selection.mode !== "SCOPED") {
      return;
    }
    var doc = root || (typeof document !== "undefined" ? document : null);
    if (!doc || !doc.querySelectorAll) {
      return;
    }

    var links = doc.querySelectorAll("a[href]");
    for (var i = 0; i < links.length; i++) {
      var a = links[i];
      var rawHref = a.getAttribute("href");
      if (!rawHref) continue;
      if (
        rawHref.startsWith("http://") ||
        rawHref.startsWith("https://") ||
        rawHref.startsWith("javascript:") ||
        rawHref.startsWith("mailto:") ||
        rawHref.startsWith("#")
      ) {
        continue;
      }
      a.setAttribute("href", withRuntime(rawHref, selection));
    }
  }

  /**
   * Assert that a scoped response carries the expected binding_id.
   * @param {Object} payload - Response payload
   * @param {Object} selection - PageRuntimeSelection
   * @returns {{ok: boolean, error?: string, detail?: string}}
   */
  function assertResponseBinding(payload, selection) {
    if (!selection || selection.mode !== "SCOPED") {
      return { ok: true };
    }
    if (payload && typeof payload === "object" && Object.prototype.hasOwnProperty.call(payload, "binding_id")) {
      if (payload.binding_id !== selection.bindingId) {
        return {
          ok: false,
          error: "RUNTIME_IDENTITY_MISMATCH",
          detail: "Response binding_id ('" + payload.binding_id + "') does not match requested URL runtime ('" + selection.bindingId + "')."
        };
      }
    }
    return { ok: true };
  }

  /**
   * Central binding-aware fetch seam.
   * Fetches the resource, translates HTTP errors, enforces identity match, and parses JSON.
   * Fails closed on INVALID selection before issuing any network request.
   *
   * @param {Object} selection - PageRuntimeSelection
   * @param {string} legacyApiUrl - e.g. '/api/overview', '/api/trends?limit=30'
   * @param {RequestInit} [options] - Fetch options
   * @returns {Promise<any>}
   */
  async function runtimeFetch(selection, legacyApiUrl, options) {
    if (!selection) {
      selection = { mode: "LEGACY", bindingId: null };
    }

    if (selection.mode === "INVALID") {
      var invErr = new Error(selection.detail || "Invalid runtime selection");
      invErr.code = "INVALID_RUNTIME_SELECTION";
      invErr.reason = selection.reason || "INVALID_RUNTIME_SELECTION";
      invErr.status = 400;
      throw invErr;
    }

    var targetUrl = (selection.mode === "SCOPED")
      ? apiPath(selection, legacyApiUrl)
      : legacyApiUrl;

    var res;
    try {
      res = await fetch(targetUrl, options || {});
    } catch (netErr) {
      if (netErr && netErr.name === "AbortError") {
        throw netErr;
      }
      var netEx = new Error(netErr ? netErr.message : "Network error");
      netEx.code = "NETWORK_ERROR";
      throw netEx;
    }

    if (!res.ok) {
      var errDetail = "HTTP " + res.status;
      var errJson = null;
      try {
        errJson = await res.json();
        if (errJson) {
          errDetail = errJson.detail || errJson.error || errDetail;
        }
      } catch (e) {}

      var code = "HTTP_ERROR";
      if (res.status === 404) {
        code = "UNKNOWN_BINDING";
      } else if (res.status === 503) {
        var strDet = String(errDetail).toUpperCase();
        if (strDet.indexOf("REGISTRY") >= 0) {
          code = "BINDING_REGISTRY_UNAVAILABLE";
        } else {
          code = "BINDING_UNAVAILABLE";
        }
      }

      var httpErr = new Error(typeof errDetail === "string" ? errDetail : JSON.stringify(errDetail));
      httpErr.status = res.status;
      httpErr.code = code;
      httpErr.detail = errDetail;
      httpErr.payload = errJson;
      throw httpErr;
    }

    var data = await res.json();

    if (selection.mode === "SCOPED") {
      var assertion = assertResponseBinding(data, selection);
      if (!assertion.ok) {
        var mismatchErr = new Error(assertion.detail);
        mismatchErr.code = "RUNTIME_IDENTITY_MISMATCH";
        mismatchErr.detail = assertion.detail;
        throw mismatchErr;
      }
    }

    return data;
  }

  /**
   * Render read-only runtime indicator into target container.
   * Uses safe textContent only; strictly no dropdown/selector.
   * @param {HTMLElement} container
   * @param {Object} selection
   */
  function renderRuntimeIndicator(container, selection) {
    if (!container) return;
    if (selection && selection.mode === "SCOPED") {
      var label = "运行时";
      if (typeof global.OWDisplay !== "undefined" && typeof global.OWDisplay.displayLabel === "function") {
        label = global.OWDisplay.displayLabel("runtime") || "运行时";
      }
      container.textContent = label + " · " + selection.bindingId;
      container.style.display = "inline-flex";
    } else {
      container.textContent = "";
      container.style.display = "none";
    }
  }

  /**
   * Render prominent fail-closed runtime error card.
   * @param {HTMLElement} container - Container to render into (e.g. .layout or main area)
   * @param {string} errorType - INVALID | UNKNOWN_BINDING | BINDING_REGISTRY_UNAVAILABLE | BINDING_UNAVAILABLE | RUNTIME_IDENTITY_MISMATCH
   * @param {string} detail - Description/message
   * @param {string} [requestedRuntime] - Requested binding_id if any
   */
  function renderRuntimeError(container, errorType, detail, requestedRuntime) {
    if (!container) return;

    var titleZh = "运行时访问受阻";
    var subtitle = errorType;
    var bannerColor = "var(--red, #cf222e)";

    if (errorType === "INVALID" || errorType === "INVALID_RUNTIME_SELECTION") {
      titleZh = "无效运行时参数";
      subtitle = "INVALID_RUNTIME_SELECTION";
    } else if (errorType === "UNKNOWN_BINDING") {
      titleZh = "未知运行时";
      subtitle = "404 UNKNOWN_BINDING";
    } else if (errorType === "BINDING_REGISTRY_UNAVAILABLE") {
      titleZh = "注册表服务不可用";
      subtitle = "503 BINDING_REGISTRY_UNAVAILABLE";
    } else if (errorType === "BINDING_UNAVAILABLE") {
      titleZh = "运行时不可用";
      subtitle = "503 BINDING_UNAVAILABLE";
    } else if (errorType === "RUNTIME_IDENTITY_MISMATCH") {
      titleZh = "运行时身份不一致";
      subtitle = "RUNTIME_IDENTITY_MISMATCH";
    }

    var card = document.createElement("div");
    card.className = "card runtime-error-card";
    card.style.border = "2px solid " + bannerColor;
    card.style.background = "#22080a";
    card.style.padding = "20px";
    card.style.margin = "20px auto";
    card.style.maxWidth = "720px";
    card.style.borderRadius = "8px";

    var head = document.createElement("div");
    head.style.display = "flex";
    head.style.justifyContent = "space-between";
    head.style.alignItems = "center";
    head.style.marginBottom = "10px";

    var titleEl = document.createElement("span");
    titleEl.style.fontSize = "16px";
    titleEl.style.fontWeight = "700";
    titleEl.style.color = "#ff7b72";
    titleEl.textContent = "⚠️ " + titleZh;
    head.appendChild(titleEl);

    var codeEl = document.createElement("span");
    codeEl.className = "mono";
    codeEl.style.fontSize = "11px";
    codeEl.style.color = "#ff7b72";
    codeEl.textContent = subtitle;
    head.appendChild(codeEl);

    card.appendChild(head);

    if (requestedRuntime) {
      var reqRow = document.createElement("div");
      reqRow.style.fontSize = "12px";
      reqRow.style.marginBottom = "8px";
      reqRow.style.color = "#e6edf3";
      var reqLabel = document.createElement("span");
      reqLabel.style.color = "var(--dim, #8b949e)";
      reqLabel.textContent = "请求的运行时：";
      reqRow.appendChild(reqLabel);
      var reqCode = document.createElement("code");
      reqCode.className = "mono";
      reqCode.style.color = "var(--accent, #58a6ff)";
      reqCode.textContent = requestedRuntime;
      reqRow.appendChild(reqCode);
      card.appendChild(reqRow);
    }

    var descEl = document.createElement("div");
    descEl.style.fontSize = "12px";
    descEl.style.color = "#c9d1d9";
    descEl.style.lineHeight = "1.6";
    descEl.textContent = detail || "该请求已被拒绝，未发生向下游回退。";
    card.appendChild(descEl);

    container.innerHTML = "";
    container.appendChild(card);
  }

  var api = {
    parsePageRuntime: parsePageRuntime,
    apiPath: apiPath,
    withRuntime: withRuntime,
    propagateNavigation: propagateNavigation,
    assertResponseBinding: assertResponseBinding,
    runtimeFetch: runtimeFetch,
    renderRuntimeIndicator: renderRuntimeIndicator,
    renderRuntimeError: renderRuntimeError
  };

  if (typeof module !== "undefined" && module.exports) {
    module.exports = api;
  }
  global.OWRuntimeScope = api;
})(typeof window !== "undefined" ? window : globalThis);
