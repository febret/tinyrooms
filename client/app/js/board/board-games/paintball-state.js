/** Pure helpers for the paintball board renderer. No Three.js or DOM here. */

/** Deterministic per-splat rotation and scale derived from its id. */
export function splatTransform(id, fallbackIndex = 0) {
  const text = String(id ?? fallbackIndex);
  let hash = 2166136261;
  for (let index = 0; index < text.length; index += 1) {
    hash ^= text.charCodeAt(index);
    hash = Math.imul(hash, 16777619);
  }
  const normalized = (hash >>> 0) / 4294967295;
  return {
    rotation: normalized * Math.PI * 2,
    scale: 0.82 + ((hash >>> 8) % 100) / 100 * 0.34,
  };
}

/** Eased 0..1 flight progress for a server-authored shot. */
export function shotProgress(elapsedMs, flightMs) {
  const duration = Math.max(1, Number(flightMs) || 1);
  const ratio = Math.max(0, Math.min(1, Number(elapsedMs) / duration));
  return 1 - (1 - ratio) * (1 - ratio);
}

/** True when a shot is fresh enough to animate after a late snapshot. */
export function isFreshShot(shot, nowMs, windowMs = 2500) {
  const at = Date.parse(String(shot?.at || ""));
  if (!Number.isFinite(at)) return true;
  return nowMs - at <= windowMs;
}
