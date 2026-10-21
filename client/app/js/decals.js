/** Generic persistent decal overlays for board sprites and sidebar peep chips. */

export const PAINT_DECAL_KIND = "paint";
export const DECAL_COLORS = Object.freeze(["#ff4d6d", "#4ea8ff", "#5cf29a", "#ffe066", "#c77dff"]);

const canvasCache = new Map();
const dataUrlCache = new Map();

function hashText(text) {
  let hash = 2166136261;
  for (let index = 0; index < text.length; index += 1) {
    hash ^= text.charCodeAt(index);
    hash = Math.imul(hash, 16777619);
  }
  return hash >>> 0;
}

/** Normalize a server decal list for rendering. */
export function normalizeDecals(raw) {
  if (!Array.isArray(raw)) return [];
  return raw
    .filter(entry => entry && typeof entry === "object")
    .map(entry => ({
      id: String(entry.id || ""),
      kind: String(entry.kind || ""),
      count: Math.max(1, Math.min(99, Number(entry.count) || 1)),
      color: String(entry.color || ""),
      data: entry.data && typeof entry.data === "object" ? { ...entry.data } : {},
    }))
    .filter(entry => entry.id && entry.kind);
}

/** Return whether a decal list contains a given kind. */
export function hasDecalKind(raw, kind) {
  return normalizeDecals(raw).some(entry => entry.kind === kind);
}

/** Return the number of paint splats represented by a decal list. */
export function paintDecalCount(raw) {
  const paint = normalizeDecals(raw).find(entry => entry.kind === PAINT_DECAL_KIND);
  return paint ? Math.min(3, Math.max(1, paint.count)) : 0;
}

function drawSplat(painter, centerX, centerY, radius, color, seed) {
  painter.fillStyle = color;
  const blobs = 5 + (seed % 3);
  for (let index = 0; index < blobs; index += 1) {
    const angle = (index / blobs) * Math.PI * 2 + (seed % 17) * 0.07;
    const distance = radius * (0.18 + (index % 3) * 0.24);
    const size = radius * (0.34 + ((seed >>> (index % 12)) & 3) * 0.08);
    painter.beginPath();
    painter.arc(centerX + Math.cos(angle) * distance, centerY + Math.sin(angle) * distance, size, 0, Math.PI * 2);
    painter.fill();
  }
  for (let index = 0; index < 7; index += 1) {
    const angle = (index / 7) * Math.PI * 2 + 0.4;
    const distance = radius * (0.92 + (index % 3) * 0.18);
    painter.beginPath();
    painter.arc(centerX + Math.cos(angle) * distance, centerY + Math.sin(angle) * distance, radius * (0.07 + (index % 2) * 0.04), 0, Math.PI * 2);
    painter.fill();
  }
}

/** Build a transparent sticker-sized canvas from a peep's decals. */
export function decalCanvas(peepId, rawDecals) {
  const id = String(peepId || "peep");
  const decals = normalizeDecals(rawDecals);
  const paint = decals.find(entry => entry.kind === PAINT_DECAL_KIND);
  const count = paint ? Math.min(3, Math.max(1, paint.count)) : 0;
  if (!count) return null;
  const key = `${id}:${count}:${paint.color}`;
  const cached = canvasCache.get(key);
  if (cached) return cached;
  const canvas = document.createElement("canvas");
  canvas.width = 256;
  canvas.height = 256;
  const painter = canvas.getContext("2d");
  if (!painter) return canvas;
  const seed = hashText(id);
  const palette = paint.color ? [paint.color, ...DECAL_COLORS.filter(color => color !== paint.color)] : DECAL_COLORS;
  const centers = [
    [92, 112],
    [164, 96],
    [142, 170],
  ];
  for (let index = 0; index < count; index += 1) {
    const [baseX, baseY] = centers[index];
    const jitterX = ((seed >>> (index * 5 + 2)) & 15) - 7;
    const jitterY = ((seed >>> (index * 5 + 6)) & 15) - 7;
    drawSplat(
      painter,
      baseX + jitterX,
      baseY + jitterY,
      24 + ((seed >>> (index * 3)) & 7) * 2,
      palette[(seed + index * 2) % palette.length],
      seed + index * 31,
    );
  }
  canvasCache.set(key, canvas);
  return canvas;
}

/** Return a cached data URL for DOM overlays, or an empty string. */
export function decalDataUrl(peepId, rawDecals) {
  const id = String(peepId || "peep");
  const decals = normalizeDecals(rawDecals);
  const paint = decals.find(entry => entry.kind === PAINT_DECAL_KIND);
  if (!paint) return "";
  const count = Math.min(3, Math.max(1, paint.count));
  const key = `${id}:${count}:${paint.color}`;
  const cached = dataUrlCache.get(key);
  if (cached) return cached;
  const canvas = decalCanvas(id, decals);
  if (!canvas) return "";
  const url = canvas.toDataURL("image/png");
  dataUrlCache.set(key, url);
  return url;
}
