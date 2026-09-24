export function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

export function parseLines(value) {
  return String(value || "")
    .split("\n")
    .map(line => line.trim())
    .filter(Boolean);
}

export function parseCsv(value) {
  return String(value || "")
    .split(",")
    .map(item => item.trim())
    .filter(Boolean);
}

export function parseJson(value, fallback) {
  const text = String(value || "").trim();
  if (!text) return fallback;
  try {
    return JSON.parse(text);
  } catch {
    return fallback;
  }
}

export function numberOr(value, fallback) {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : fallback;
}

export function actionsToText(actions) {
  return (actions || [])
    .map(action => {
      if (Array.isArray(action)) return action.join(" | ");
      return `${action?.label ?? ""} | ${action?.command ?? ""}`;
    })
    .join("\n");
}

export function textToActions(value) {
  return parseLines(value).map(line => {
    const [label, command] = line.split("|").map(part => part.trim());
    return [label, command || ""];
  });
}

export function cardLabel(catalog, cardId) {
  const entry = (catalog?.cards || []).find(card => card.id === cardId);
  return entry ? entry.label : cardId;
}

export function selectOptions(options, selected) {
  return options
    .map(option => {
      const value = typeof option === "string" ? option : option.value;
      const label = typeof option === "string" ? option : option.label;
      const isSelected = value === selected ? " selected" : "";
      return `<option value="${escapeHtml(value)}"${isSelected}>${escapeHtml(label)}</option>`;
    })
    .join("");
}
