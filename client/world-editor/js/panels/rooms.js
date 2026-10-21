import { escapeHtml } from "../util.js";

export function renderRoomList(draft, selection, filter = "") {
  const rooms = draft?.rooms || {};
  const query = filter.trim().toLowerCase();
  const entries = Object.entries(rooms).filter(([id, room]) => {
    if (!query) return true;
    return id.toLowerCase().includes(query) || String(room.label || "").toLowerCase().includes(query);
  });
  const items = entries.map(([roomId, room]) => {
    const active = selection?.kind === "room" && selection.id === roomId;
    return `
      <button type="button" class="room-item${active ? " is-active" : ""}" data-room="${escapeHtml(roomId)}">
        <span class="room-item-label">${escapeHtml(room.label || roomId)}</span>
        <code class="room-item-id">${escapeHtml(roomId)}</code>
      </button>
    `;
  });
  return `
    <div class="room-list" role="list">
      ${items.length ? items.join("") : '<p class="empty-state">No matching rooms.</p>'}
    </div>
  `;
}
