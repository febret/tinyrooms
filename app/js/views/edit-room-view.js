import { escapeHtml } from "../presentation.js";
import { libraryGridMarkup, libraryPropsetMarkup, libraryTagMarkup } from "../editing/prop-library.js";
import { availableLibrary, libraryEntry, selectedInstance } from "../editing/edit-reducer.js";

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

function selectionBlock(editor, selected) {
  const entry = libraryEntry(editor, selected.propId);
  const [x, y] = selected.position;
  return `
    <p class="editor-meta"><strong>${escapeHtml(entry?.label || selected.propId)}</strong>
      Position ${Math.round(x)}, ${Math.round(y)} · Rotation ${Math.round(selected.rotation[1])}° · Scale ${selected.scale.toFixed(2)}</p>
    <div class="editor-buttons">
      <button type="button" data-edit-action="rotate" data-edit-delta="-15">Rotate −15°</button>
      <button type="button" data-edit-action="rotate" data-edit-delta="15">Rotate +15°</button>
      <button type="button" data-edit-action="scale" data-edit-factor="0.87">Smaller</button>
      <button type="button" data-edit-action="scale" data-edit-factor="1.15">Larger</button>
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
  const library = availableLibrary(editor, state.user?.unlockedProps);
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
        <input type="search" class="editor-search" data-edit-search placeholder="Search props" aria-label="Search props">
        <button type="button" class="editor-shop-button" data-edit-action="prop-shop">🛒 Prop Shop</button>
        <button type="button" data-edit-action="undo" ${editor.undo.length ? "" : "disabled"}>Undo</button>
        <button type="button" data-edit-action="redo" ${editor.redo.length ? "" : "disabled"}>Redo</button>
        <button type="button" class="primary" data-edit-action="save" ${editor.dirty ? "" : "disabled"}>Save layout</button>
        <span class="editor-status" role="status">${escapeHtml(editor.error || editor.status || (editor.dirty ? "Unsaved changes" : "All changes saved"))}</span>
        <button type="button" class="quiet" data-close-view="1">Close</button>
        <div class="editor-heading-tags" role="group" aria-label="Filter by tag">
          ${libraryTagMarkup(library)}
          <span class="editor-library-count" role="status"></span>
        </div>
      </header>
      ${conflict}
      <div class="editor-workspace">
        <div class="editor-env">
          ${environmentRow(state, editor)}
          ${selected ? selectionBlock(editor, selected) : '<p class="editor-meta editor-meta-empty">Select a prop on the board to move, rotate, or scale it.</p>'}
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
