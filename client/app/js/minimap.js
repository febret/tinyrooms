import { escapeHtml } from "./presentation.js";

export const MINIMAP_RADIUS = 2;
export const MINIMAP_DIRECTIONS = [
  { id: "north", glyph: "▲", label: "North" },
  { id: "east", glyph: "▶", label: "East" },
  { id: "south", glyph: "▼", label: "South" },
  { id: "west", glyph: "◀", label: "West" },
  { id: "up", glyph: "⬆", label: "Up" },
  { id: "down", glyph: "⬇", label: "Down" },
];

function validPosition(position) {
  return Array.isArray(position)
    && position.length === 3
    && position.every(Number.isInteger);
}

function tileCoordinates(tile, center, radius) {
  const dx = tile.position[0] - center[0];
  const dy = tile.position[1] - center[1];
  if (tile.position[2] !== center[2] || Math.abs(dx) > radius || Math.abs(dy) > radius) return null;
  return { column: dx + radius, row: radius - dy, dx, dy };
}

/** Reduce a room snapshot to the tiles, links, and exits needed by the minimap. */
export function minimapModel(room) {
  const center = validPosition(room?.grid) ? room.grid : null;
  const radius = Number(room?.minimap?.radius) > 0 ? Number(room.minimap.radius) : MINIMAP_RADIUS;
  const tiles = Array.isArray(room?.minimap?.rooms) ? room.minimap.rooms : [];
  if (!center || !tiles.length) return null;
  const placed = [];
  const byCell = new Map();
  for (const tile of tiles) {
    if (!tile || !validPosition(tile.position)) continue;
    const cell = tileCoordinates(tile, center, radius);
    if (!cell) continue;
    const key = `${cell.column}:${cell.row}`;
    if (byCell.has(key)) continue;
    const placedTile = { ...tile, ...cell, current: tile.id === room.id };
    byCell.set(key, placedTile);
    placed.push(placedTile);
  }
  if (!placed.some(tile => tile.current)) return null;
  const links = [];
  for (const tile of placed) {
    for (const [dx, dy] of [[1, 0], [0, 1]]) {
      const neighbor = byCell.get(`${tile.column + dx}:${tile.row + dy}`);
      if (neighbor) links.push([tile, neighbor]);
    }
  }
  const exits = new Map();
  for (const exit of room.exits || []) {
    if (exit?.direction && !exits.has(exit.direction)) exits.set(exit.direction, exit);
  }
  return { center, radius, tiles: placed, links, exits };
}

function tileMarkup(tile) {
  const fallback = Array.isArray(tile.palette) && tile.palette[0] ? `background-color:${escapeHtml(tile.palette[0])};` : "";
  const level = Number(tile.lighting?.level);
  const shade = Number.isFinite(level)
    ? `background-color:${escapeHtml(tile.lighting?.color || "#000000")};opacity:${Math.min(0.78, Math.max(0, (1 - level) * 0.72)).toFixed(2)};`
    : "";
  return `<span class="mini-cell is-room${tile.current ? " is-current" : ""}${tile.dark ? " is-dark" : ""}" style="--mini-column:${tile.column + 1};--mini-row:${tile.row + 1};${fallback}" title="${escapeHtml(tile.label)}">`
    + `${tile.imageUrl ? `<img class="mini-floor" src="${escapeHtml(tile.imageUrl)}" alt="" aria-hidden="true" draggable="false">` : ""}`
    + `<span class="mini-shade" style="${shade}" aria-hidden="true"></span>`
    + `</span>`;
}

function directionMarkup(direction, exit) {
  const classes = `mini-exit mini-exit-${direction.id}${exit ? "" : " is-disabled"}${exit?.locked ? " is-locked" : ""}`;
  const label = exit ? `${direction.label}: ${exit.label || exit.id}` : `${direction.label} exit unavailable`;
  const command = exit?.quickAction?.command || (exit ? `.go ${exit.id}` : "");
  return `<button type="button" class="${classes}" data-mini-command="${escapeHtml(command)}" data-focus-key="mini-${direction.id}" aria-label="${escapeHtml(label)}" title="${escapeHtml(label)}"${exit ? "" : " disabled"}><span aria-hidden="true">${direction.glyph}</span></button>`;
}

/** Render the room-selected 5x5 minimap shown above the look bar. */
export function minimapMarkup(room) {
  const model = minimapModel(room);
  if (!model) return "";
  const cells = [];
  const extent = model.radius * 2 + 1;
  for (let row = 0; row < extent; row += 1) {
    for (let column = 0; column < extent; column += 1) {
      const tile = model.tiles.find(entry => entry.column === column && entry.row === row);
      cells.push(tile ? tileMarkup(tile) : `<span class="mini-cell is-empty" style="--mini-column:${column + 1};--mini-row:${row + 1};" aria-hidden="true"></span>`);
    }
  }
  const links = model.links.map(([from, to]) => {
    const scale = 100 / (model.radius * 2 + 1);
    const points = [from, to].map(tile => `${((tile.column + 0.5) * scale).toFixed(2)},${((tile.row + 0.5) * scale).toFixed(2)}`).join(" ");
    return `<polyline points="${points}" />`;
  }).join("");
  const planar = MINIMAP_DIRECTIONS.slice(0, 4).map(direction => directionMarkup(direction, model.exits.get(direction.id))).join("");
  const vertical = MINIMAP_DIRECTIONS.slice(4).map(direction => directionMarkup(direction, model.exits.get(direction.id))).join("");
  return `<div class="look-minimap" role="group" aria-label="Nearby rooms">`
    + `<div class="mini-layout">${planar}`
    + `<div class="mini-grid" style="--mini-extent:${model.radius * 2 + 1};"><svg class="mini-links" viewBox="0 0 100 100" aria-hidden="true">${links}</svg>${cells.join("")}</div>`
    + `<div class="mini-vertical">${vertical}</div></div></div>`;
}
