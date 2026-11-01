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
