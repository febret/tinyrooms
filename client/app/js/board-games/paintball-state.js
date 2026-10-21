/** Pure helpers for the paintball board renderer. No Three.js or DOM here. */

export const PAINTBALL_PHASES = Object.freeze({
  active: "LIVE",
  intermission: "NEXT ROUND",
});

/** Sort a game state's scoreboard into display order. */
export function scoreEntries(state) {
  const raw = Array.isArray(state?.scoreboard) ? state.scoreboard : [];
  return raw
    .map(entry => ({
      id: String(entry?.id || ""),
      name: String(entry?.name || "Peep"),
      hits: Math.max(0, Number(entry?.hits || 0)),
      shots: Math.max(0, Number(entry?.shots || 0)),
      accuracy: Number(entry?.accuracy || 0),
    }))
    .filter(entry => entry.id)
    .sort((a, b) => (b.hits - a.hits) || (b.accuracy - a.accuracy) || a.name.localeCompare(b.name));
}

/** Human-readable phase label for the scoreboard. */
export function phaseLabel(state) {
  return PAINTBALL_PHASES[state?.phase] || "WAITING";
}

/** Format seconds as M:SS, clamped at zero. */
export function formatClock(seconds) {
  const total = Math.max(0, Math.floor(Number(seconds) || 0));
  const minutes = Math.floor(total / 60);
  const remainder = total % 60;
  return `${minutes}:${String(remainder).padStart(2, "0")}`;
}

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
