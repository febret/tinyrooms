export const PLAYER_SPRITE_WORLD_HEIGHT = 7.5;
export const VIEW_SPRITE_RADII = 5;

export function viewScale(width, height) {
  const view = Math.max(1, Math.min(Number(width) || 0, Number(height) || 0));
  return view / (2 * PLAYER_SPRITE_WORLD_HEIGHT * VIEW_SPRITE_RADII);
}

export function cameraOffset(width, height, scale, focusX, focusY) {
  return [Number(width) / 2 - Number(focusX) * scale, Number(height) / 2 - Number(focusY) * scale];
}

export function hash01(seed, salt) {
  let hash = (Number(seed) ^ Math.imul(Number(salt) || 0, 2654435761)) >>> 0;
  hash = Math.imul(hash ^ (hash >>> 15), 2246822519);
  hash ^= hash >>> 13;
  return ((hash >>> 0) % 10000) / 10000;
}

export function explosionParticles(seed, count = 26) {
  const total = Math.max(0, Math.min(64, Math.floor(Number(count) || 0)));
  const particles = [];
  for (let index = 0; index < total; index += 1) {
    particles.push({
      angle: hash01(seed, index * 4 + 1) * Math.PI * 2,
      distance: 0.25 + hash01(seed, index * 4 + 2) * 1.2,
      size: 0.08 + hash01(seed, index * 4 + 3) * 0.22,
      drift: (hash01(seed, index * 4 + 4) - 0.5) * 0.9,
    });
  }
  return particles;
}

export function backingStoreSize(rectWidth, rectHeight, devicePixelRatio = 1) {
  const ratio = Math.min(Math.max(Number(devicePixelRatio) || 1, 1), 2);
  const cssWidth = Math.max(1, Number(rectWidth) || 0);
  const cssHeight = Math.max(1, Number(rectHeight) || 0);
  return {
    width: Math.max(1, Math.round(cssWidth * ratio)),
    height: Math.max(1, Math.round(cssHeight * ratio)),
    cssWidth,
    cssHeight,
    ratio,
  };
}

export function easeInOutQuad(progress) {
  const t = Math.min(1, Math.max(0, Number(progress) || 0));
  return t < 0.5 ? 2 * t * t : 1 - ((-2 * t + 2) ** 2) / 2;
}

export function fadeAlpha(elapsedMs, durationMs) {
  const duration = Math.max(1, Number(durationMs) || 0);
  return Math.min(1, Math.max(0, Number(elapsedMs) / duration));
}

export function clamp(value, minimum, maximum) {
  return Math.max(minimum, Math.min(maximum, value));
}

export function normalizeVector(x, y) {
  const length = Math.hypot(x, y);
  if (length < 1e-6) return [0, 0];
  return [x / length, y / length];
}

export function stickVector(centerX, centerY, pointerX, pointerY, radius) {
  const dx = pointerX - centerX;
  const dy = pointerY - centerY;
  const distance = Math.hypot(dx, dy);
  if (distance < 1e-6) return { active: false, x: 0, y: 0, magnitude: 0 };
  const scale = Math.min(1, distance / radius);
  return { active: scale > 0.08, x: (dx / distance) * scale, y: (dy / distance) * scale, magnitude: scale };
}

export function hitsObstacles(x, y, radius, obstacles) {
  for (const obstacle of obstacles || []) {
    if (!obstacle || typeof obstacle !== "object") continue;
    if (Math.hypot(x - obstacle.x, y - obstacle.y) <= radius + (obstacle.r || 0)) return true;
  }
  return false;
}

export function moveCircle(x, y, dx, dy, radius, arena, obstacles) {
  let nextX = clamp(x + dx, radius, arena.width - radius);
  if (!hitsObstacles(nextX, y, radius, obstacles)) x = nextX;
  let nextY = clamp(y + dy, radius, arena.height - radius);
  if (!hitsObstacles(x, nextY, radius, obstacles)) y = nextY;
  return [x, y];
}

export function stepVelocity(vx, vy, targetX, targetY, accel, friction, dt) {
  const rate = targetX === 0 && targetY === 0 ? friction : accel;
  const dx = targetX - vx;
  const dy = targetY - vy;
  const distance = Math.hypot(dx, dy);
  const limit = Math.max(0, rate) * Math.max(0, dt);
  if (distance <= limit || distance < 1e-9) return [targetX, targetY];
  const scale = limit / distance;
  return [vx + dx * scale, vy + dy * scale];
}

export function hashId(value) {
  const text = String(value ?? "");
  let hash = 2166136261;
  for (let index = 0; index < text.length; index += 1) {
    hash ^= text.charCodeAt(index);
    hash = Math.imul(hash, 16777619);
  }
  return hash >>> 0;
}
