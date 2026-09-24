const COLUMNS = 4;
const CELL_W = 170;
const CELL_H = 120;
const NODE_W = 130;
const NODE_H = 54;
const PAD = 40;

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function layout(roomIds) {
  const positions = new Map();
  roomIds.forEach((roomId, index) => {
    const column = index % COLUMNS;
    const row = Math.floor(index / COLUMNS);
    positions.set(roomId, {
      x: PAD + column * CELL_W + NODE_W / 2,
      y: PAD + row * CELL_H + NODE_H / 2,
    });
  });
  return positions;
}

export function renderWorldMap(draft, selection) {
  const rooms = draft?.rooms || {};
  const roomIds = Object.keys(rooms);
  if (!roomIds.length) {
    return '<p class="empty-state">No rooms yet. Add a room to build the map.</p>';
  }
  const positions = layout(roomIds);
  const rows = Math.ceil(roomIds.length / COLUMNS);
  const width = PAD * 2 + COLUMNS * CELL_W;
  const height = PAD * 2 + rows * CELL_H;
  const edges = [];
  const nodes = [];
  for (const roomId of roomIds) {
    const room = rooms[roomId];
    const source = positions.get(roomId);
    for (const [exitId, exit] of Object.entries(room.exits || {})) {
      const target = positions.get(exit.target);
      if (!target) continue;
      const midX = (source.x + target.x) / 2;
      const midY = (source.y + target.y) / 2;
      const active = selection?.kind === "exit" && selection.id === roomId && selection.sub === exitId;
      edges.push(`
        <g class="map-edge${active ? " is-active" : ""}" data-map-exit="${escapeHtml(roomId)}:${escapeHtml(exitId)}">
          <line x1="${source.x}" y1="${source.y}" x2="${target.x}" y2="${target.y}" />
          <text x="${midX}" y="${midY - 4}">${escapeHtml(exit.label || exitId)}</text>
        </g>
      `);
    }
  }
  for (const roomId of roomIds) {
    const room = rooms[roomId];
    const point = positions.get(roomId);
    const active = selection?.kind === "room" && selection.id === roomId;
    nodes.push(`
      <g class="map-node${active ? " is-active" : ""}" data-map-room="${escapeHtml(roomId)}">
        <rect x="${point.x - NODE_W / 2}" y="${point.y - NODE_H / 2}" width="${NODE_W}" height="${NODE_H}" rx="10" />
        <text x="${point.x}" y="${point.y - 4}" class="map-node-title">${escapeHtml(room.label || roomId)}</text>
        <text x="${point.x}" y="${point.y + 14}" class="map-node-id">${escapeHtml(roomId)}</text>
      </g>
    `);
  }
  return `
    <svg class="world-map" viewBox="0 0 ${width} ${height}" role="img" aria-label="World map">
      <g class="map-edges">${edges.join("")}</g>
      <g class="map-nodes">${nodes.join("")}</g>
    </svg>
  `;
}
