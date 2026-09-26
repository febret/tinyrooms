import { escapeHtml } from "../presentation.js";
import { libraryGridMarkup, libraryPropsetMarkup, libraryTagMarkup } from "../editing/prop-library.js";
import { availableLibrary, libraryEntry } from "../editing/edit-reducer.js";

const BOARD_STYLES = ["stretch", "tile", "tile-w", "tile-h"];

function paletteOf(state, editor) {
  const current = editor.environment.palette || state.room?.board?.palette || [];
  const colors = Array.isArray(current) ? [...current] : [];
  while (colors.length < 3) colors.push("#d4be94");
  return colors.slice(0, 3);
}

function environmentRow(state, editor) {
  const whitelist = editor.environmentWhitelist;
  if (!whitelist.length) return "";
  const colors = paletteOf(state, editor);
  const style = editor.environment.board_image_style || state.room?.board?.imageStyle || "stretch";
  return `
    <div class="editor-env-row">
      ${whitelist.includes("palette") ? `
        <div class="editor-palette" role="group" aria-label="Board palette">
          ${colors.map((color, index) => `
            <label class="editor-color" title="Palette color ${index + 1}">
              <input type="color" value="${escapeHtml(color)}" data-edit-palette="${index}" aria-label="Palette color ${index + 1}">
            </label>
          `).join("")}
        </div>` : ""}
      ${whitelist.includes("board_image_style") ? `
        <label class="editor-style">Style
          <select data-edit-style>
            ${BOARD_STYLES.map(value => `<option value="${value}" ${value === style ? "selected" : ""}>${value}</option>`).join("")}
          </select>
        </label>` : ""}
    </div>
  `;
}

/** Text shown in the selected-prop meta line, or the empty prompt. */
export function editorMetaText(selected) {
  if (!selected) return "Select a prop on the board to move, rotate, or scale it.";
  const [x, y] = selected.position;
  return `Position ${Math.round(x)}, ${Math.round(y)} · Rotation ${Math.round(selected.rotation[1])}° · Scale ${selected.scale.toFixed(2)}`;
}

/** Display name of the current selection, or the empty placeholder. */
export function editorSelectedName(editor, selected) {
  if (!selected) return "No prop selected";
  return libraryEntry(editor, selected.propId)?.label || selected.propId;
}

/** Conflict banner markup; empty unless the server rejected a stale save. */
export function editorConflictMarkup(editor) {
  if (!editor.conflict) return "";
  return `<div class="editor-conflict" role="alert">
    <span>This room changed while you were editing.</span>
    <button type="button" data-edit-action="reload">Reload from server</button>
    <button type="button" class="primary" data-edit-action="reapply">Reapply my changes</button>
  </div>`;
}

function selectionMarkup() {
  return `
    <p class="editor-meta editor-meta-empty" data-editor-meta>${editorMetaText(null)}</p>
    <div class="editor-buttons" data-editor-buttons hidden>
      <button type="button" class="negative" data-edit-action="remove">Remove</button>
    </div>
  `;
}

function snapRow(editor) {
  return `
    <div class="editor-snaps">
      <label class="editor-toggle"><input type="checkbox" data-edit-snap="position" ${editor.snapPosition ? "checked" : ""}> Snap position</label>
      <label class="editor-toggle"><input type="checkbox" data-edit-snap="rotation" ${editor.snapRotation ? "checked" : ""}> Snap rotation</label>
    </div>
  `;
}

/**
 * Static editor shell.
 *
 * Prop-instance and selection data are deliberately excluded: the panel's
 * dynamic regions (selected name, meta line, undo/save chrome, conflict banner)
 * are patched in place by `cards.renderEditor` so the prop library, its image
 * tiles, and scroll/focus are mounted once per catalog change.
 */
export function editRoomView(state) {
  const canEdit = Boolean(state?.room?.canEditRoom);
  if (!canEdit) {
    return `
      <section class="edit-room-view editor-dock-panel locked-state" role="region" aria-label="Edit Room">
        <p class="empty-state">🔒 You do not have permission to edit this room.</p>
      </section>
    `;
  }
  const editor = state.editor;
  if (!editor) {
    return `
      <section class="edit-room-view editor-dock-panel" role="region" aria-label="Edit Room">
        <p class="empty-state">Loading the room editor…</p>
      </section>
    `;
  }
  const library = availableLibrary(editor, state.user?.unlockedProps);
  return `
    <section class="edit-room-view editor-dock-panel" role="region" aria-label="Edit Room">
      <header class="editor-dock-header">
        <strong>Edit Room</strong>
        <span class="editor-selected-name" data-edit-selected-name aria-live="polite">No prop selected</span>
        <input type="search" class="editor-search" data-edit-search placeholder="Search props" aria-label="Search props">
        <button type="button" class="editor-shop-button" data-edit-action="prop-shop">🛒 Prop Shop</button>
        <button type="button" data-editor-undo data-edit-action="undo" disabled>Undo</button>
        <button type="button" data-editor-redo data-edit-action="redo" disabled>Redo</button>
        <button type="button" class="primary" data-editor-save data-edit-action="save" disabled>Save layout</button>
        <span class="editor-status" role="status" data-editor-status>All changes saved</span>
        <button type="button" class="quiet" data-close-view="1">Close</button>
        <div class="editor-heading-tags" role="group" aria-label="Filter by tag">
          ${libraryTagMarkup(library)}
          <span class="editor-library-count" role="status"></span>
        </div>
      </header>
      <div data-editor-conflict>${editorConflictMarkup(editor)}</div>
      <div class="editor-workspace">
        <div class="editor-env">
          ${environmentRow(state, editor)}
          <div class="editor-selection" data-editor-selection>${selectionMarkup()}</div>
          ${snapRow(editor)}
        </div>
        <div class="editor-propsets" role="list" aria-label="Prop sets">
          ${libraryPropsetMarkup(library)}
        </div>
        <section class="editor-library-section">
          <div class="editor-library-grid" role="list" aria-label="Approved decorative props">
            ${libraryGridMarkup(library)}
          </div>
          <p class="editor-library-empty empty-state" hidden>No props match your filters.</p>
        </section>
      </div>
    </section>
  `;
}
