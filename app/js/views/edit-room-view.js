import { escapeHtml } from "../presentation.js";
import { libraryMarkup } from "../editing/prop-library.js";
import { libraryEntry, selectedInstance } from "../editing/edit-reducer.js";

const BOARD_STYLES = ["stretch", "tile", "tile-w", "tile-h"];

function paletteOf(state, editor) {
  const current = editor.environment.palette || state.room?.board?.palette || [];
  const colors = Array.isArray(current) ? [...current] : [];
  while (colors.length < 3) colors.push("#d4be94");
  return colors.slice(0, 3);
}

function selectionSection(editor, selected) {
  const entry = libraryEntry(editor, selected.propId);
  const [x, y] = selected.position;
  return `
    <section class="editor-section editor-selection">
      <h3>${escapeHtml(entry?.label || selected.propId)}</h3>
      <p class="editor-meta">Position ${Math.round(x)}, ${Math.round(y)} · Rotation ${Math.round(selected.rotation[1])}° · Scale ${selected.scale.toFixed(2)}</p>
      <div class="editor-buttons">
        <button type="button" data-edit-action="rotate" data-edit-delta="-15">Rotate −15°</button>
        <button type="button" data-edit-action="rotate" data-edit-delta="15">Rotate +15°</button>
        <button type="button" data-edit-action="scale" data-edit-factor="0.87">Smaller</button>
        <button type="button" data-edit-action="scale" data-edit-factor="1.15">Larger</button>
        <button type="button" class="negative" data-edit-action="remove">Remove</button>
      </div>
    </section>
  `;
}

function environmentSection(state, editor) {
  const whitelist = editor.environmentWhitelist;
  if (!whitelist.length) return "";
  const colors = paletteOf(state, editor);
  const style = editor.environment.board_image_style || state.room?.board?.imageStyle || "stretch";
  return `
    <section class="editor-section editor-environment">
      <h3>Environment</h3>
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
    </section>
  `;
}

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
  const selected = selectedInstance(editor);
  const conflict = editor.conflict
    ? `<div class="editor-conflict" role="alert">
        <span>This room changed while you were editing.</span>
        <button type="button" data-edit-action="reload">Reload from server</button>
        <button type="button" class="primary" data-edit-action="reapply">Reapply my changes</button>
      </div>`
    : "";
  return `
    <section class="edit-room-view editor-dock-panel" role="region" aria-label="Edit Room">
      <header class="editor-dock-header">
        <strong>Edit Room</strong>
        <button type="button" data-edit-action="undo" ${editor.undo.length ? "" : "disabled"}>Undo</button>
        <button type="button" data-edit-action="redo" ${editor.redo.length ? "" : "disabled"}>Redo</button>
        <label class="editor-toggle"><input type="checkbox" data-edit-snap="position" ${editor.snapPosition ? "checked" : ""}> Snap position</label>
        <label class="editor-toggle"><input type="checkbox" data-edit-snap="rotation" ${editor.snapRotation ? "checked" : ""}> Snap rotation</label>
        <span class="editor-status" role="status">${escapeHtml(editor.error || editor.status || (editor.dirty ? "Unsaved changes" : "All changes saved"))}</span>
        <button type="button" class="primary" data-edit-action="save" ${editor.dirty ? "" : "disabled"}>Save layout</button>
        <button type="button" class="quiet" data-close-view="1">Close</button>
      </header>
      ${conflict}
      <div class="editor-dock-body">
        <section class="editor-section editor-library-section">
          <h3>Add a prop</h3>
          ${libraryMarkup(editor)}
        </section>
        ${selected ? selectionSection(editor, selected) : '<section class="editor-section editor-selection"><p class="empty-state">Select a prop on the board to move, rotate, or scale it.</p></section>'}
        ${environmentSection(state, editor)}
      </div>
    </section>
  `;
}
