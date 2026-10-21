/*
 * Zero-build boot guard for Tinyrooms.
 *
 * The application entrypoint is an ES module (app/js/ui.js), which requires a
 * modern JavaScript engine. On older browsers the module script is silently
 * ignored, leaving an empty shell with no visible error. This file is written
 * in plain ES5 and contains no modern syntax or DOM APIs so that it can run on
 * the same engines that cannot run the application, probe what is missing, and
 * render a readable diagnostic instead of a blank page.
 */
(function () {
  "use strict";

  var BOOT_TIMEOUT_MS = 20000;
  var POLL_INTERVAL_MS = 250;

  var captures = [];
  var shown = false;
  var pollTimer = null;
  var timeoutTimer = null;

  function textOf(value) {
    if (value === null || value === undefined) return "";
    return String(value);
  }

  function getEntryScript() {
    return document.getElementById("tinyrooms-entry");
  }

  function getEntrySource() {
    var entry = getEntryScript();
    return entry ? textOf(entry.getAttribute("src")) : "";
  }

  function addCapture(kind, message, source, line, column, stack) {
    captures.push({
      kind: textOf(kind),
      message: textOf(message),
      source: textOf(source),
      line: line ? Number(line) : 0,
      column: column ? Number(column) : 0,
      stack: textOf(stack)
    });
  }

  function errorHandler(event) {
    addCapture(
      "error",
      event && event.message ? event.message : "Uncaught error",
      event ? event.filename : "",
      event ? event.lineno : 0,
      event ? event.colno : 0,
      event && event.error ? event.error.stack : ""
    );
    if (!appHasBooted()) evaluateFailures();
  }

  function rejectionHandler(event) {
    var reason = event ? event.reason : null;
    addCapture(
      "unhandledrejection",
      reason && reason.message ? reason.message : textOf(reason),
      "",
      0,
      0,
      reason && reason.stack ? reason.stack : ""
    );
  }

  function entryErrorHandler() {
    addCapture(
      "module",
      "The application module script could not be loaded or parsed.",
      getEntrySource(),
      0,
      0,
      ""
    );
    evaluateFailures();
  }

  function supportsCss(property, value) {
    if (typeof CSS === "undefined" || typeof CSS.supports !== "function") return false;
    try {
      return value ? CSS.supports(property, value) : CSS.supports(property);
    } catch (error) {
      return false;
    }
  }

  function probeSyntax(body) {
    if (!evalAvailable()) {
      return { supported: true, detail: "not probed (eval unavailable, possibly blocked by CSP)" };
    }
    try {
      new Function(body);
      return { supported: true, detail: "" };
    } catch (error) {
      return { supported: false, detail: error && error.message ? error.message : textOf(error) };
    }
  }

  var evalAvailability = null;

  function evalAvailable() {
    if (evalAvailability !== null) return evalAvailability;
    try {
      new Function("return 1");
      evalAvailability = true;
    } catch (error) {
      evalAvailability = false;
    }
    return evalAvailability;
  }

  function probeCall(test) {
    try {
      return { supported: Boolean(test()), detail: "" };
    } catch (error) {
      return { supported: false, detail: error && error.message ? error.message : textOf(error) };
    }
  }

  function moduleSupport() {
    return probeCall(function () {
      return typeof HTMLScriptElement !== "undefined" && "noModule" in HTMLScriptElement.prototype;
    });
  }

  var SYNTAX_PROBES = [
    ["optional-chaining", "Optional chaining (?. )", "80", "var value = source?.item;"],
    ["nullish-coalescing", "Nullish coalescing (??)", "80", "var value = source ?? fallback;"],
    ["logical-assignment", "Logical assignment (||=, &&=, ??=)", "85", "value ||= fallback;"],
    ["optional-catch-binding", "Optional catch binding (catch {})", "66", "try { value(); } catch { }"],
    ["numeric-separators", "Numeric separators (1_000)", "75", "var value = 1_000;"]
  ];

  var API_PROBES = [
    ["crypto-random-uuid", "crypto.randomUUID()", "92", function () {
      return typeof crypto !== "undefined" && typeof crypto.randomUUID === "function";
    }],
    ["array-at", "Array.prototype.at()", "92", function () {
      return typeof Array.prototype.at === "function";
    }],
    ["string-replace-all", "String.prototype.replaceAll()", "85", function () {
      return typeof String.prototype.replaceAll === "function";
    }],
    ["object-from-entries", "Object.fromEntries()", "73", function () {
      return typeof Object.fromEntries === "function";
    }],
    ["promise-finally", "Promise.prototype.finally()", "63", function () {
      return typeof Promise !== "undefined" && typeof Promise.prototype.finally === "function";
    }],
    ["array-flat-map", "Array.prototype.flatMap()", "69", function () {
      return typeof Array.prototype.flatMap === "function";
    }],
    ["resize-observer", "ResizeObserver", "64", function () {
      return typeof ResizeObserver === "function";
    }]
  ];

  var OPTIONAL_PROBES = [
    ["inert", "HTMLElement.inert", "102", function () {
      return typeof HTMLElement !== "undefined" && "inert" in HTMLElement.prototype;
    }],
    ["structured-clone", "structuredClone()", "98", function () {
      return typeof structuredClone === "function";
    }],
    ["dvh", "100dvh CSS unit", "108", function () {
      return supportsCss("height", "100dvh");
    }],
    ["has-selector", ":has() CSS selector", "105", function () {
      return supportsCss("selector(:has(*))", "");
    }]
  ];

  function addSyntaxProbes(target) {
    for (var index = 0; index < SYNTAX_PROBES.length; index++) {
      var probe = SYNTAX_PROBES[index];
      var result = probeSyntax(probe[3]);
      target.push({
        id: probe[0],
        label: probe[1],
        minVersion: probe[2],
        required: true,
        supported: result.supported,
        detail: result.detail
      });
    }
  }

  function addCallProbes(target, probes, required) {
    for (var index = 0; index < probes.length; index++) {
      var probe = probes[index];
      var result = probeCall(probe[3]);
      target.push({
        id: probe[0],
        label: probe[1],
        minVersion: probe[2],
        required: required,
        supported: result.supported,
        detail: result.detail
      });
    }
  }

  function runProbes() {
    var results = [];
    var modules = moduleSupport();
    results.push({
      id: "modules",
      label: "ES modules (<script type=\"module\">)",
      minVersion: "61",
      required: true,
      supported: modules.supported,
      detail: modules.detail
    });
    addSyntaxProbes(results);
    addCallProbes(results, API_PROBES, true);
    addCallProbes(results, OPTIONAL_PROBES, false);
    return results;
  }

  var COMPILE_TIME_PROBES = {
    "modules": true,
    "optional-chaining": true,
    "nullish-coalescing": true,
    "logical-assignment": true,
    "optional-catch-binding": true,
    "numeric-separators": true
  };

  function firstCompileTimeBlocker() {
    var probes = runProbes();
    for (var index = 0; index < probes.length; index++) {
      var probe = probes[index];
      if (probe.required && !probe.supported && COMPILE_TIME_PROBES[probe.id]) return probe.id;
    }
    return "";
  }

  function describeBrowser() {
    var userAgent = textOf(navigator.userAgent);
    var brands = [];
    var match;
    var patterns = [
      ["Samsung Internet", /SamsungBrowser\/([0-9.]+)/],
      ["Edge", /Edg\/([0-9.]+)/],
      ["Chrome", /(?:Chrome|CriOS)\/([0-9.]+)/],
      ["Firefox", /(?:Firefox|FxiOS)\/([0-9.]+)/],
      ["Safari", /Version\/([0-9.]+).*Safari/]
    ];
    for (var index = 0; index < patterns.length; index++) {
      match = patterns[index][1].exec(userAgent);
      if (match) {
        brands.push(patterns[index][0] + " " + match[1]);
        break;
      }
    }
    if (navigator.userAgentData && navigator.userAgentData.brands) {
      for (var brandIndex = 0; brandIndex < navigator.userAgentData.brands.length; brandIndex++) {
        var brand = navigator.userAgentData.brands[brandIndex];
        if (brand && brand.brand !== "Not A;Brand") brands.push(brand.brand + " " + brand.version);
      }
    }
    if (!brands.length) brands.push("Unrecognized engine");
    return {
      browser: brands.join(", "),
      userAgent: userAgent,
      appVersion: textOf(navigator.appVersion),
      platform: textOf(navigator.platform),
      language: textOf(navigator.language)
    };
  }

  function describeDevice() {
    var webgl = detectWebGL();
    return {
      screen: textOf(window.screen ? window.screen.width + " x " + window.screen.height : ""),
      devicePixelRatio: textOf(window.devicePixelRatio),
      cores: textOf(navigator.hardwareConcurrency),
      memory: textOf(navigator.deviceMemory),
      online: textOf(navigator.onLine),
      webgl: webgl
    };
  }

  function detectWebGL() {
    try {
      var canvas = document.createElement("canvas");
      var context = canvas.getContext("webgl2") || canvas.getContext("webgl") || canvas.getContext("experimental-webgl");
      if (!context) return "unavailable";
      var version = context.getParameter(context.VERSION);
      return textOf(version);
    } catch (error) {
      return "error: " + textOf(error && error.message ? error.message : error);
    }
  }

  function inferJavaScriptLevel(probes) {
    var supported = {};
    for (var index = 0; index < probes.length; index++) supported[probes[index].id] = probes[index].supported;
    if (!supported.modules) return "pre-modules (older than ES2015 modules)";
    if (!supported["optional-chaining"] || !supported["nullish-coalescing"]) return "ES2019 or earlier";
    if (!supported["logical-assignment"]) return "ES2020";
    if (!supported["string-replace-all"]) return "ES2020";
    if (!supported["crypto-random-uuid"] || !supported["array-at"]) return "ES2021";
    return "ES2022 or later";
  }

  function rootCause(reason, missing) {
    if (reason === "modules" || missing.indexOf("modules") !== -1) {
      return "This browser does not support JavaScript ES modules (<script type=\"module\">), which Tinyrooms requires. The application cannot start.";
    }
    if (missing.length) {
      return "This browser is missing JavaScript features Tinyrooms requires: " + missing.join(", ") + ".";
    }
    if (reason === "timeout") {
      return "Tinyrooms did not finish starting. The browser may be too old or the connection may have been interrupted.";
    }
    return "Tinyrooms could not start because a script error occurred.";
  }

  function appHasBooted() {
    var app = document.getElementById("app");
    if (app) {
      var auth = app.getAttribute("data-auth");
      if (auth && auth !== "booting") return true;
    }
    var authLayer = document.getElementById("auth-layer");
    if (authLayer && authLayer.childNodes && authLayer.childNodes.length > 0) return true;
    return false;
  }

  function evaluateFailures() {
    if (shown || appHasBooted()) return;
    if (!captures.length) return;
    showOverlay("error");
  }

  function stopTimers() {
    if (pollTimer !== null) {
      clearInterval(pollTimer);
      pollTimer = null;
    }
    if (timeoutTimer !== null) {
      clearTimeout(timeoutTimer);
      timeoutTimer = null;
    }
  }

  function showOverlay(reason) {
    if (shown) return;
    shown = true;
    stopTimers();
    var probes = runProbes();
    var missing = [];
    var optionalFailures = [];
    for (var index = 0; index < probes.length; index++) {
      if (probes[index].supported) continue;
      if (probes[index].required) missing.push(probes[index].id);
      else optionalFailures.push(probes[index].id);
    }
    renderOverlay(reason, probes, missing, optionalFailures);
  }

  function element(tag, className, text) {
    var node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined && text !== null) node.textContent = text;
    return node;
  }

  function addRow(list, label, value) {
    if (!value) return;
    var row = element("li", "boot-guard-row");
    row.appendChild(element("span", "boot-guard-key", label));
    row.appendChild(element("span", "boot-guard-value", value));
    list.appendChild(row);
  }

  function addSection(parent, title) {
    var section = element("section", "boot-guard-section");
    section.appendChild(element("h2", null, title));
    var list = element("ul", "boot-guard-list");
    section.appendChild(list);
    parent.appendChild(section);
    return list;
  }

  function formatCaptures() {
    if (!captures.length) return ["No script error was reported; the module script likely never executed."];
    var lines = [];
    for (var index = 0; index < captures.length; index++) {
      var entry = captures[index];
      var location = entry.source ? " (" + entry.source + (entry.line ? ":" + entry.line + (entry.column ? ":" + entry.column : "") : "") + ")" : "";
      lines.push(entry.kind + ": " + entry.message + location);
      if (entry.stack) lines.push(entry.stack);
    }
    return lines;
  }

  function buildReport(reason, probes, missing, optionalFailures) {
    var browser = describeBrowser();
    var device = describeDevice();
    var lines = [];
    lines.push("Tinyrooms boot diagnostic");
    lines.push("Reason: " + reason);
    lines.push("Root cause: " + rootCause(reason, missing));
    lines.push("");
    lines.push("Browser: " + browser.browser);
    lines.push("User agent: " + browser.userAgent);
    lines.push("App version: " + browser.appVersion);
    lines.push("Platform: " + browser.platform);
    lines.push("Language: " + browser.language);
    lines.push("JavaScript level: " + inferJavaScriptLevel(probes));
    lines.push("");
    lines.push("Device: screen " + device.screen + ", dpr " + device.devicePixelRatio + ", cores " + device.cores + ", memory " + device.memory + ", online " + device.online);
    lines.push("WebGL: " + device.webgl);
    lines.push("");
    lines.push("Feature probes:");
    for (var index = 0; index < probes.length; index++) {
      var probe = probes[index];
      lines.push("  [" + (probe.supported ? "supported" : "MISSING") + "] " + probe.label + " (Chrome " + probe.minVersion + "+)" + (probe.detail ? " - " + probe.detail : ""));
    }
    lines.push("");
    lines.push("Missing required: " + (missing.length ? missing.join(", ") : "none"));
    lines.push("Degraded optional: " + (optionalFailures.length ? optionalFailures.join(", ") : "none"));
    lines.push("");
    lines.push("Reported errors:");
    var errorLines = formatCaptures();
    for (var errorIndex = 0; errorIndex < errorLines.length; errorIndex++) lines.push("  " + errorLines[errorIndex]);
    return lines.join("\n");
  }

  function renderOverlay(reason, probes, missing, optionalFailures) {
    var overlay = element("section", "boot-guard");
    overlay.id = "boot-guard";
    overlay.setAttribute("data-boot-guard", "visible");
    overlay.setAttribute("data-reason", reason);
    overlay.setAttribute("data-missing", missing.join(" "));
    overlay.setAttribute("role", "alertdialog");
    overlay.setAttribute("aria-labelledby", "boot-guard-title");

    var card = element("div", "boot-guard-card");
    overlay.appendChild(card);

    var heading = element("h1", null, "Tinyrooms can't start in this browser");
    heading.id = "boot-guard-title";
    card.appendChild(heading);
    card.appendChild(element("p", "boot-guard-lead", rootCause(reason, missing)));

    var browser = describeBrowser();
    var device = describeDevice();

    var browserList = addSection(card, "Browser");
    addRow(browserList, "Engine", browser.browser);
    addRow(browserList, "JavaScript level", inferJavaScriptLevel(probes));
    addRow(browserList, "User agent", browser.userAgent);
    addRow(browserList, "Platform", browser.platform);
    addRow(browserList, "Language", browser.language);

    var deviceList = addSection(card, "Device");
    addRow(deviceList, "Screen", device.screen);
    addRow(deviceList, "Pixel ratio", device.devicePixelRatio);
    addRow(deviceList, "CPU cores", device.cores);
    addRow(deviceList, "Device memory", device.memory);
    addRow(deviceList, "WebGL", device.webgl);

    var featureList = addSection(card, "JavaScript feature support");
    for (var index = 0; index < probes.length; index++) {
      var probe = probes[index];
      var status = probe.supported ? "supported" : probe.required ? "MISSING" : "missing (degraded)";
      var detail = probe.detail ? " - " + probe.detail : "";
      addRow(featureList, probe.label, status + " (needs Chrome " + probe.minVersion + "+)" + detail);
    }

    var errorList = addSection(card, "Reported error");
    var errorLines = formatCaptures();
    for (var errorIndex = 0; errorIndex < errorLines.length; errorIndex++) {
      errorList.appendChild(element("li", "boot-guard-row", errorLines[errorIndex]));
    }

    var report = buildReport(reason, probes, missing, optionalFailures);
    var actions = element("div", "boot-guard-actions");
    var copyButton = element("button", "boot-guard-copy", "Copy details");
    copyButton.type = "button";
    copyButton.onclick = function () { copyReport(report, copyButton); };
    actions.appendChild(copyButton);
    card.appendChild(actions);

    var textarea = element("textarea", "boot-guard-report");
    textarea.readOnly = true;
    textarea.setAttribute("aria-label", "Diagnostic report");
    textarea.value = report;
    card.appendChild(textarea);

    var target = document.body || document.documentElement;
    target.appendChild(overlay);
  }

  function selectReport() {
    var textarea = document.querySelector(".boot-guard-report");
    if (textarea && typeof textarea.select === "function") {
      textarea.focus();
      textarea.select();
    }
  }

  function copyReport(report, button) {
    function done() {
      button.textContent = "Copied";
      setTimeout(function () { button.textContent = "Copy details"; }, 2000);
    }
    try {
      if (navigator.clipboard && typeof navigator.clipboard.writeText === "function") {
        navigator.clipboard.writeText(report).then(done, selectReport);
        return;
      }
    } catch (error) {
      selectReport();
      return;
    }
    selectReport();
  }

  function start() {
    try {
      window.addEventListener("error", errorHandler, false);
    } catch (error) {
      /* Exception capture unavailable; the probe report still works. */
    }
    try {
      window.addEventListener("unhandledrejection", rejectionHandler, false);
    } catch (error) {
      /* Exception capture unavailable; the probe report still works. */
    }

    var entry = getEntryScript();
    if (entry && entry.addEventListener) entry.addEventListener("error", entryErrorHandler, false);

    var blocker = firstCompileTimeBlocker();
    if (blocker) {
      showOverlay(blocker === "modules" ? "modules" : "syntax");
      return;
    }

    evaluateFailures();
    if (shown) return;

    pollTimer = setInterval(function () {
      if (appHasBooted()) {
        stopTimers();
        return;
      }
      evaluateFailures();
    }, POLL_INTERVAL_MS);

    timeoutTimer = setTimeout(function () {
      if (!appHasBooted()) showOverlay("timeout");
    }, BOOT_TIMEOUT_MS);
  }

  if (document.body && getEntryScript()) {
    start();
  } else if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", start, false);
  } else {
    start();
  }
})();
