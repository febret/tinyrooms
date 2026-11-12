import { escapeHtml } from "../presentation.js";
import { MACRO_MAX_LENGTH, MACRO_PAGES, MACROS_PER_PAGE } from "../macros.js";

function pageTab(page, active) {
  return `<button type="button" class="macro-tab${page === active ? " active" : ""}" role="tab"
    aria-selected="${page === active}" data-macro-page="${page}" title="Macro page ${page + 1}"
    aria-label="Macro page ${page + 1}">${page + 1}</button>`;
}

function macroEntry(index, text, editing) {
  if (editing) {
    return `<input class="macro-input" type="text" data-macro-index="${index}"
      data-focus-key="macro-${index}" value="${escapeHtml(text)}" maxlength="${MACRO_MAX_LENGTH}"
      autocomplete="off" placeholder="Empty macro" aria-label="Macro ${index + 1}">`;
  }
  const label = text ? `Send "${text}"` : "Empty macro";
  return `<button type="button" class="macro-entry${text ? "" : " empty"}" data-macro-send="${index}"
    ${text ? "" : "disabled"} aria-label="${escapeHtml(label)}" title="${escapeHtml(text || "Empty macro")}">
    ${escapeHtml(text || "＋")}
  </button>`;
}

/** Render the five-page macro popup anchored above the chat bar. */
export function macroMenuMarkup(state) {
  const page = Math.min(Math.max(Number(state.ui?.macroPage) || 0, 0), MACRO_PAGES - 1);
  const editing = Boolean(state.ui?.macroEditing);
  const macros = state.user?.macros || [];
  const start = page * MACROS_PER_PAGE;
  const entries = Array.from({ length: MACROS_PER_PAGE }, (_, slot) => {
    const index = start + slot;
    return macroEntry(index, String(macros[index] || ""), editing);
  }).join("");
  return `
    <header class="macro-menu-head">
      <h3 class="macro-heading">Macros</h3>
      <div class="macro-menu-actions">
        <button type="button" class="macro-action macro-keyboard" data-macro-keyboard="1"
          aria-label="Show the keyboard" title="Show the keyboard">Keyboard</button>
        <button type="button" class="macro-action${editing ? " active" : ""}" data-macro-edit="1"
          aria-pressed="${editing}" aria-label="${editing ? "Finish editing macros" : "Edit macros"}"
          title="${editing ? "Finish editing" : "Edit macros"}">${editing ? "Done" : "Edit"}</button>
      </div>
    </header>
    <div class="macro-tabs" role="tablist" aria-label="Macro pages">
      ${Array.from({ length: MACRO_PAGES }, (_, index) => pageTab(index, page)).join("")}
    </div>
    <div class="macro-grid" role="tabpanel" aria-label="Macro page ${page + 1}">
      ${entries}
    </div>
  `;
}
