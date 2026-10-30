import { escapeHtml } from "../../app/js/presentation.js";

export { escapeHtml };

export function clone(value) {
  return typeof structuredClone === "function"
    ? structuredClone(value)
    : JSON.parse(JSON.stringify(value));
}

export function parseCsv(value) {
  return String(value || "")
    .split(",")
    .map(item => item.trim())
    .filter(Boolean);
}

export function parseLines(value) {
  return String(value || "")
    .split("\n")
    .map(line => line.trim())
    .filter(Boolean);
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

export function numberOr(value, fallback) {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : fallback;
}

/** True when the file-level CONFIG differs from its saved snapshot. Only `scale_adjust` is editable. */
export function configScaleDirty(file, fileSnapshot) {
  if (!file || !fileSnapshot) return false;
  return file.scale_adjust !== fileSnapshot.scale_adjust;
}

export function getPath(object, path) {
  return path.split(".").reduce((cursor, key) => {
    if (cursor == null) return undefined;
    return cursor[/^\d+$/.test(key) ? Number(key) : key];
  }, object);
}

export function setPath(object, path, value) {
  const parts = path.split(".");
  let cursor = object;
  for (let index = 0; index < parts.length - 1; index += 1) {
    const key = /^\d+$/.test(parts[index]) ? Number(parts[index]) : parts[index];
    const nextIsIndex = /^\d+$/.test(parts[index + 1]);
    if (cursor[key] == null || typeof cursor[key] !== "object") {
      cursor[key] = nextIsIndex ? [] : {};
    }
    cursor = cursor[key];
  }
  const last = parts[parts.length - 1];
  cursor[/^\d+$/.test(last) ? Number(last) : last] = value;
}

export function selectOptions(options, selected) {
  return (options || [])
    .map(option => {
      const value = typeof option === "string" ? option : option.value;
      const label = typeof option === "string" ? option : option.label;
      const isSelected = value === selected ? " selected" : "";
      return `<option value="${escapeHtml(value)}"${isSelected}>${escapeHtml(label)}</option>`;
    })
    .join("");
}

export function field(label, input) {
  return `<label class="pe-field"><span>${escapeHtml(label)}</span>${input}</label>`;
}

export function textInput(value, attrs, placeholder = "") {
  return `<input type="text" ${attrs} value="${escapeHtml(value ?? "")}" placeholder="${escapeHtml(placeholder)}">`;
}

export function numberInput(value, attrs, step = "0.05") {
  return `<input type="number" ${attrs} step="${step}" value="${escapeHtml(value ?? 0)}">`;
}

export function textarea(value, attrs, rows = 3) {
  return `<textarea ${attrs} rows="${rows}">${escapeHtml(value ?? "")}</textarea>`;
}

export function checkbox(checked, attrs) {
  return `<input type="checkbox" ${attrs}${checked ? " checked" : ""}>`;
}

export function panelHeader(title, subtitle) {
  return `<header class="pe-panel-head"><h2>${escapeHtml(title)}</h2><p>${escapeHtml(subtitle || "")}</p></header>`;
}

export function pathAttr(prefix, path, kind) {
  return `data-pe-${prefix}="${escapeHtml(path)}" data-pe-kind="${kind}"`;
}
