/** Generic persistent decal overlays for board sprites and sidebar peep chips. */

export const PAINT_DECAL_KIND = "paint";
export const STINK_DECAL_KIND = "stink";
export const DECAL_COLORS = Object.freeze(["#ff4d6d", "#4ea8ff", "#5cf29a", "#ffe066", "#c77dff"]);
export const STINK_COLORS = Object.freeze(["#63c74d", "#3f9142", "#8be07a"]);

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

/** Draw rough green crayon wisps rising around a sticker. */
function drawStinkLine(painter, points, color, width, seed) {
  painter.strokeStyle = color;
  painter.lineCap = "round";
  painter.lineJoin = "round";
  for (let pass = 0; pass < 3; pass += 1) {
    painter.globalAlpha = pass === 2 ? 0.86 : 0.32;
    painter.lineWidth = width - pass * 1.1;
    painter.beginPath();
    points.forEach(([baseX, baseY], position) => {
      const jitterX = (((seed >>> ((position * 3 + pass * 7) % 23)) & 7) - 3) * 1.2;
      const jitterY = (((seed >>> ((position * 5 + pass * 11) % 29)) & 7) - 3) * 0.9;
      const x = baseX + jitterX;
      const y = baseY + jitterY;
      if (position === 0) painter.moveTo(x, y);
      else painter.quadraticCurveTo(x - 8, y - 8, x, y - 14);
    });
    painter.stroke();
  }
  painter.globalAlpha = 1;
}

function stinkWisps(seed) {
  const lanes = [58, 104, 152, 198];
  return lanes.map((x, lane) => {
    const height = 84 + ((seed >>> (lane * 4)) & 15);
    const top = 34 + ((seed >>> (lane * 4 + 2)) & 11);
    return [
      [x, 96 + height * 0.48],
      [x + (lane % 2 ? 8 : -8), 78 + height * 0.30],
      [x + (lane % 2 ? -7 : 7), top + 26],
      [x + (lane % 2 ? 9 : -9), top + 8],
    ];
  });
}

/** Build a sticker-sized transparent canvas with green stink lines. */
export function stinkCanvas(peepId) {
  const id = String(peepId || "peep");
  const key = `stink:${id}`;
  const cached = canvasCache.get(key);
  if (cached) return cached;
  const canvas = document.createElement("canvas");
  canvas.width = 256;
  canvas.height = 256;
  const painter = canvas.getContext("2d");
  if (!painter) return canvas;
  const seed = hashText(key);
  stinkWisps(seed).forEach((points, lane) => {
    drawStinkLine(painter, points, STINK_COLORS[lane % STINK_COLORS.length], 7 - (lane % 2), seed + lane * 101);
  });
  for (let index = 0; index < 7; index += 1) {
    const x = 48 + ((seed >>> (index * 6)) & 127);
    const y = 36 + ((seed >>> (index * 6 + 3)) & 43);
    painter.fillStyle = STINK_COLORS[(seed + index) % STINK_COLORS.length];
    painter.globalAlpha = 0.62;
    painter.beginPath();
    painter.arc(x, y, 2.4 + (index % 3), 0, Math.PI * 2);
    painter.fill();
  }
  painter.globalAlpha = 1;
  canvasCache.set(key, canvas);
  return canvas;
}

/** Return a cached green-stink data URL, or an empty string. */
export function stinkDataUrl(peepId) {
  const id = String(peepId || "peep");
  const key = `stink:${id}`;
  const cached = dataUrlCache.get(key);
  if (cached) return cached;
  const url = stinkCanvas(id).toDataURL("image/png");
  dataUrlCache.set(key, url);
  return url;
}
