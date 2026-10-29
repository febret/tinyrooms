/** Pure grid geometry shared by the renderer and its tests. */
export function gridConfig(config) {
  if (!config || typeof config !== "object") return null;
  const columns = Number(config.columns);
  const rows = Number(config.rows);
  const origin = Array.isArray(config.origin) ? config.origin.map(Number) : null;
  const size = Array.isArray(config.size) ? config.size.map(Number) : null;
  if (!Number.isInteger(columns) || columns < 1 || !Number.isInteger(rows) || rows < 1) return null;
  if (!origin || origin.length !== 2 || !origin.every(Number.isFinite)) return null;
  if (!size || size.length !== 2 || !size.every(Number.isFinite) || size[0] <= 0 || size[1] <= 0) return null;
  return { columns, rows, origin, size };
}

/** Convert a grid square to its authoritative board percentage position. */
export function squareToBoardPosition(config, square) {
  const grid = gridConfig(config);
  if (!grid || typeof square !== "string" || !/^[a-z]\d+$/.test(square)) return null;
  const file = square.charCodeAt(0) - 97;
  const rank = Number(square.slice(1));
  if (file < 0 || file >= grid.columns || rank < 1 || rank > grid.rows) return null;
  return [
    grid.origin[0] + (file + 0.5) * (grid.size[0] / grid.columns),
    grid.origin[1] + (grid.rows - rank + 0.5) * (grid.size[1] / grid.rows),
  ];
}

/** Convert an authoritative board percentage position to a grid square. */
export function boardPositionToSquare(config, position) {
  const grid = gridConfig(config);
  if (!grid || !Array.isArray(position)) return "";
  const cellWidth = grid.size[0] / grid.columns;
  const cellDepth = grid.size[1] / grid.rows;
  const file = Math.floor((position[0] - grid.origin[0]) / cellWidth);
  const row = Math.floor((position[1] - grid.origin[1]) / cellDepth);
  if (file < 0 || file >= grid.columns || row < 0 || row >= grid.rows) return "";
  return `${String.fromCharCode(97 + file)}${grid.rows - row}`;
}
