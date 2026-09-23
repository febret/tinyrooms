import { escapeHtml } from "../presentation.js";

/** Render the approved decorative prop library as add-on-click tiles. */
export function libraryMarkup(editor) {
  const entries = editor?.library || [];
  if (!entries.length) {
    return '<p class="empty-state">No approved props are available for this room.</p>';
  }
  return `
    <div class="editor-library" role="list" aria-label="Approved decorative props">
      ${entries.map(entry => `
        <button type="button" class="editor-library-item" role="listitem"
          data-edit-add="${escapeHtml(entry.propId)}" aria-label="Add ${escapeHtml(entry.label)}"
          title="${escapeHtml(entry.label)}">
          <img class="editor-thumb" data-thumb-model="${escapeHtml(entry.modelUrl)}"
            data-thumb-scale="${escapeHtml(entry.baseScale)}" alt="" aria-hidden="true">
          <span>${escapeHtml(entry.label)}</span>
        </button>
      `).join("")}
    </div>
  `;
}
