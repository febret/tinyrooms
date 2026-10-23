export const RESERVED_KEYS = ["origin", "source_name", "room_id", "random"];

export function isReservedKey(key) {
  return RESERVED_KEYS.includes(String(key || ""));
}

export function isPlayable(entry) {
  return Boolean(entry?.gates?.room && entry?.gates?.power && entry?.gates?.feature);
}

export function filterCutscenes(cutscenes, { query = "", tab = "all" } = {}) {
  const needle = String(query || "").trim().toLowerCase();
  return (Array.isArray(cutscenes) ? cutscenes : []).filter(entry => {
    if (tab === "playable" && !isPlayable(entry)) return false;
    if (tab === "hidden" && !entry.hidden) return false;
    if (tab === "gated" && isPlayable(entry)) return false;
    if (!needle) return true;
    const haystack = [entry.title, entry.id, entry.origin, ...(entry.aliases || [])]
      .map(part => String(part || "").toLowerCase())
      .join(" ");
    return haystack.includes(needle);
  });
}

export function placeholderRows(entry) {
  return Array.isArray(entry?.placeholders?.params) ? entry.placeholders.params : [];
}

export function cueTokens(entry) {
  return Array.isArray(entry?.placeholders?.cues) ? entry.placeholders.cues : [];
}

export function kindLabel(kind) {
  const labels = {
    me: "self sticker",
    user: "room user",
    peep: "NPC peep",
    sticker: "sticker",
    card: "card",
    prop: "prop",
  };
  return labels[kind] || kind || "value";
}

export function coerceScalar(text) {
  const raw = String(text ?? "");
  const lowered = raw.trim().toLowerCase();
  if (lowered === "true" || lowered === "yes") return true;
  if (lowered === "false" || lowered === "no") return false;
  const trimmed = raw.trim();
  if (trimmed !== "" && !Number.isNaN(Number(trimmed))) return Number(trimmed);
  return raw;
}

export function changedParams(entry, values) {
  const authored = entry?.params && typeof entry.params === "object" ? entry.params : {};
  const params = {};
  for (const [key, value] of Object.entries(values || {})) {
    const name = String(key || "").trim();
    if (!name || isReservedKey(name)) continue;
    const text = String(value ?? "");
    if (text === "") continue;
    if (name in authored && String(authored[name]) === text) continue;
    params[name] = coerceScalar(text);
  }
  return params;
}
