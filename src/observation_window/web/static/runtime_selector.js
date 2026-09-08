/* OW-MULTI-AGENT-SELECTOR-PHASE3-V1 — URL-authoritative runtime selector.
 *
 * The selector is intentionally thin: one catalog fetch during bootstrap,
 * canonical binding_id labels, and a full-document navigation on change.
 * It never owns runtime data, persistence, polling, or registry authority.
 */
(function (global) {
  "use strict";

  var RUNTIME_GRAMMAR = /^[a-z0-9][a-z0-9-]{0,63}$/;
  var BINDING_DEPENDENT_PARAMS = [
    "runtime",
    "interaction_id",
    "turn_id",
    "before",
    "dimension",
    "selected_moment",
    "selectedMoment",
    "moment_id",
    "causal",
    "causal_id",
    "causal_selection",
    "causalSelection"
  ];

  function projectCatalog(payload) {
    var bindings = payload && Array.isArray(payload.bindings) ? payload.bindings : [];
    var seen = Object.create(null);
    var ids = [];
    bindings.forEach(function (descriptor) {
      if (!descriptor || descriptor.environment !== "PRODUCTION") return;
      var id = descriptor.binding_id;
      if (typeof id !== "string" || !RUNTIME_GRAMMAR.test(id) || seen[id]) return;
      seen[id] = true;
      ids.push(id);
    });
    return ids;
  }

  function switchUrl(currentUrl, selectedBindingId) {
    if (typeof selectedBindingId !== "string" || !RUNTIME_GRAMMAR.test(selectedBindingId)) {
      throw new Error("invalid binding_id selected");
    }
    var isAbsolute = /^https?:\/\//.test(currentUrl);
    var parsed = new URL(currentUrl, isAbsolute ? undefined : "http://dummy.local");
    BINDING_DEPENDENT_PARAMS.forEach(function (key) {
      parsed.searchParams.delete(key);
    });
    parsed.searchParams.set("runtime", selectedBindingId);
    if (isAbsolute) return parsed.toString();
    return parsed.pathname + parsed.search + parsed.hash;
  }

  function optionModel(ids, selection) {
    var current = selection && selection.mode === "SCOPED" ? selection.bindingId : null;
    var currentKnown = current && ids.indexOf(current) !== -1;
    var model = [];
    if (current && !currentKnown) {
      model.push({
        value: "",
        label: current + " (not in registry)",
        disabled: true,
        selected: true
      });
    }
    ids.forEach(function (id) {
      model.push({
        value: id,
        label: id,
        disabled: false,
        selected: id === current
      });
    });
    return model;
  }

  function containerFor(options) {
    if (options && options.container) return options.container;
    if (typeof document !== "undefined") return document.getElementById("runtime-selector");
    return null;
  }

  function labelText() {
    if (global.OWDisplay && typeof global.OWDisplay.displayLabel === "function") {
      return global.OWDisplay.displayLabel("runtimeSelector") || "Runtime / 运行时";
    }
    return "Runtime / 运行时";
  }

  function disable(container, message) {
    if (!container) return;
    container.textContent = message || "Runtime / 运行时 unavailable";
    container.setAttribute("aria-disabled", "true");
    container.classList.add("runtime-selector-unavailable");
  }

  function render(container, ids, selection) {
    if (!container || typeof document === "undefined") return null;
    container.textContent = "";
    container.removeAttribute("aria-disabled");
    container.classList.remove("runtime-selector-unavailable");

    var label = document.createElement("label");
    label.className = "runtime-selector-label";
    label.textContent = labelText();
    var select = document.createElement("select");
    select.className = "runtime-selector-input";
    select.setAttribute("aria-label", labelText());

    var options = optionModel(ids, selection);
    options.forEach(function (item) {
      var option = document.createElement("option");
      option.value = item.value;
      option.textContent = item.label;
      option.disabled = item.disabled;
      option.selected = item.selected;
      select.appendChild(option);
    });
    var current = selection && selection.mode === "SCOPED" ? selection.bindingId : null;
    select.disabled = ids.length === 0 || !current || ids.indexOf(current) === -1;
    select.addEventListener("change", function () {
      if (!select.value || typeof global.location === "undefined") return;
      try {
        global.location.assign(switchUrl(global.location.href, select.value));
      } catch (err) {
        select.disabled = true;
        container.title = String(err && err.message ? err.message : err);
      }
    });
    label.appendChild(select);
    container.appendChild(label);
    return select;
  }

  async function bootstrap(selection, options) {
    var container = containerFor(options);
    if (selection && selection.mode === "INVALID") {
      disable(container, "Runtime / 运行时 unavailable: invalid URL selection");
      return { status: "INVALID_RUNTIME_SELECTION", fetched: false };
    }
    if (typeof global.fetch !== "function") {
      disable(container, "Runtime / 运行时 unavailable");
      return { status: "BINDING_REGISTRY_UNAVAILABLE", fetched: false };
    }
    try {
      var response = await global.fetch("/api/runtime-bindings");
      if (!response || !response.ok) throw new Error("catalog request failed");
      var ids = projectCatalog(await response.json());
      if (!ids.length) throw new Error("production binding catalog is empty");
      render(container, ids, selection);
      return { status: "READY", fetched: true, bindingIds: ids };
    } catch (err) {
      disable(container, "Runtime / 运行时 unavailable");
      return { status: "BINDING_REGISTRY_UNAVAILABLE", fetched: true };
    }
  }

  var api = {
    projectCatalog: projectCatalog,
    switchUrl: switchUrl,
    optionModel: optionModel,
    bootstrap: bootstrap,
    bindingDependentParams: BINDING_DEPENDENT_PARAMS.slice()
  };

  if (typeof module !== "undefined" && module.exports) module.exports = api;
  global.OWRuntimeSelector = api;
})(typeof window !== "undefined" ? window : globalThis);
