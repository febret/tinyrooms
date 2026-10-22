/**
 * Pure layout helpers for the player-entry prop diorama.
 *
 * Keeping slot math, compact selection, and animation seeds free of Three.js
 * lets the composition be tested with Node's runner and keeps the WebGL module
 * focused on rendering.
 */

export const GRID_SIZE = 5;
export const GRID_SPACING = 2.35;

export const TILE_PALETTE = Object.freeze([
  { tile: "#ffd9a8", pedestal: "#ffb568", glow: "#ff9b3d" },
  { tile: "#ffc4c9", pedestal: "#ff8f9c", glow: "#ff6f85" },
  { tile: "#bfe8d7", pedestal: "#74d3b4", glow: "#38bd97" },
  { tile: "#c6e3ff", pedestal: "#86c5ff", glow: "#4aa8ff" },
  { tile: "#ded1ff", pedestal: "#b6a2ff", glow: "#8b7bff" },
  { tile: "#ffe8a8", pedestal: "#ffd166", glow: "#f7b32b" },
]);

/** Return a positive, stable 32-bit hash for an arbitrary prop id. */
export function hashString(value) {
  const text = String(value ?? "");
  let hash = 2166136261;
  for (let index = 0; index < text.length; index += 1) {
    hash ^= text.charCodeAt(index);
    hash = Math.imul(hash, 16777619);
  }
  return hash >>> 0;
}

/** Map an authored [col, row] slot to centered X/Z world coordinates. */
export function slotPosition(col, row, { gridSize = GRID_SIZE, spacing = GRID_SPACING } = {}) {
  const offset = (gridSize - 1) / 2;
  return {
    x: (Number(col) - offset) * spacing,
    z: (Number(row) - offset) * spacing,
  };
}

/** Keep the most important props on narrow screens without changing layout. */
export function selectShowcaseProps(props, { compact = false, limit = 7 } = {}) {
  const entries = (Array.isArray(props) ? props : []).filter(prop =>
    prop && typeof prop.model_url === "string" && Array.isArray(prop.slot) && prop.slot.length === 2
  );
  if (!compact) return entries;
  const preferred = entries.filter(prop => Number(prop.priority) <= 1);
  const selected = (preferred.length >= 5 ? preferred : entries).slice(0, limit);
  return selected.length ? selected : entries.slice(0, limit);
}

/**
 * Turn the server manifest into deterministic placement/animation data.
 * Server order is preserved except for the compact subset.
 */
export function planShowcase(props, { compact = false, gridSize = GRID_SIZE, spacing = GRID_SPACING } = {}) {
  return selectShowcaseProps(props, { compact }).map(prop => {
    const [col, row] = prop.slot.map(Number);
    const seed = hashString(prop.id);
    const palette = TILE_PALETTE[(seed + col * 2 + row * 3) % TILE_PALETTE.length];
    return {
      ...prop,
      col,
      row,
      seed,
      position: slotPosition(col, row, { gridSize, spacing }),
      palette,
      phase: ((seed % 628) / 100),
      spin: (0.22 + ((seed >>> 8) % 26) / 100) * (seed % 2 === 0 ? 1 : -1),
      bobPhase: ((seed >>> 3) % 628) / 100,
      bobAmount: 0.035 + ((seed >>> 5) % 4) * 0.012,
      targetHeight: 1.35 + ((seed >>> 11) % 5) * 0.13,
    };
  });
}
