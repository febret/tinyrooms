// Pure helpers for the Hacker Collective client. No DOM, no network.

export function clamp(value, low, high) {
  return Math.max(low, Math.min(high, value));
}

export function formatClock(ms) {
  const total = Math.max(0, Math.ceil(Number(ms || 0) / 1000));
  const minutes = Math.floor(total / 60);
  const seconds = total % 60;
  return `${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}`;
}

export function hexToRgba(hex, alpha = 1) {
  const value = String(hex || "").replace("#", "");
  if (value.length !== 6) return `rgba(75, 255, 126, ${alpha})`;
  const red = parseInt(value.slice(0, 2), 16);
  const green = parseInt(value.slice(2, 4), 16);
  const blue = parseInt(value.slice(4, 6), 16);
  return `rgba(${red}, ${green}, ${blue}, ${alpha})`;
}

export function paletteStyle(palette = {}) {
  return {
    "--ph": palette.phosphor || "#4bff7e",
    "--ph-soft": hexToRgba(palette.phosphor || "#4bff7e", 0.22),
    "--ph-line": hexToRgba(palette.phosphor || "#4bff7e", 0.36),
    "--deep": palette.deep || "#0a2a16",
    "--ink": palette.ink || "#03110a",
    "--accent": palette.accent || "#b6ffc9",
  };
}

export function normaliseAnswer(value) {
  return String(value ?? "").trim().replace(/\s+/g, "");
}

export function answerPairs(answers = {}) {
  return Object.entries(answers)
    .filter(([, value]) => normaliseAnswer(value) !== "")
    .map(([key, value]) => `${key}=${normaliseAnswer(value)}`)
    .join(",");
}

export function localCheck(screen, answers = {}) {
  const expected = screen?.answers || {};
  const correct = {};
  for (const [key, value] of Object.entries(expected)) {
    correct[key] = normaliseAnswer(answers[key]) === normaliseAnswer(value);
  }
  return { passed: Object.keys(expected).length > 0 && Object.values(correct).every(Boolean), correct };
}

export function screenState(screens = []) {
  const total = screens.length;
  const done = screens.filter(screen => screen.passed).length;
  return { done, total, ready: total > 0 && done === total };
}

export function nextOpenIndex(screens = []) {
  const index = screens.findIndex(screen => !screen.passed);
  return index < 0 ? -1 : index;
}

export function nodeStatusLabel(status) {
  return { open: "OPEN", locked: "LOCKED", cleared: "CLEAN" }[status] || "LOCKED";
}

export function pickLine(banter = {}, event, seed = 0) {
  const lines = banter[event] || [];
  if (!lines.length) return "";
  return lines[Math.abs(Math.trunc(seed)) % lines.length];
}

export function totalScreens(run) {
  if (!run) return 0;
  return (run.nodes || []).length + 1;
}

export function clearedScreens(run) {
  return run ? (run.cleared || []).length : 0;
}

export function nodeKindLabel(kind) {
  return {
    firewall: "FIREWALL",
    database: "DATA VAULT",
    mail: "MAIL RELAY",
    maintenance: "MAINT BOT",
    legacy: "LEGACY BOX",
    core: "CENTRAL SERVER",
  }[kind] || "NODE";
}

export function pips(count) {
  const value = clamp(Math.round(Number(count) || 0), 0, 5);
  return "●".repeat(value) + "○".repeat(5 - value);
}

export function timeoutCopy(screen) {
  if (screen?.payload?.time_limit_ms) return "Too slow. A fresh set is loading.";
  return "That screen reset.";
}
