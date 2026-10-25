import { escapeHtml } from "../util.js";

export function renderRoomList(draft, selection, filter = "", quality = {}) {
  const rooms = draft?.rooms || {};
  const query = filter.trim().toLowerCase();
  const entries = Object.entries(rooms).filter(([id, room]) => {
    if (!query) return true;
    return id.toLowerCase().includes(query) || String(room.label || "").toLowerCase().includes(query);
  });
  const items = entries.map(([roomId, room]) => {
    const active = selection?.kind === "room" && selection.id === roomId;
    const issues = quality?.[roomId]?.issues || [];
    const warning = issues.length
      ? `<span class="room-item-warning" role="img" aria-label="Room quality warning: ${escapeHtml(issues.map(issue => issue.message).join("; "))}" title="${escapeHtml(issues.map(issue => issue.message).join("; "))}">&#9888;</span>`
      : "";
    return `
      <button type="button" class="room-item${active ? " is-active" : ""}" data-room="${escapeHtml(roomId)}">
        <span class="room-item-label">${escapeHtml(room.label || roomId)}</span>
        <span class="room-item-meta">${warning}<code class="room-item-id">${escapeHtml(roomId)}</code></span>
      </button>
    `;
  });
  return `
    <div class="room-list" role="list">
      ${items.length ? items.join("") : '<p class="empty-state">No matching rooms.</p>'}
    </div>
  `;
}
