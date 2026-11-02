export const INTERP_DELAY_MS = 90;
// Keep in sync with server MAX_SPLATS and MAX_HIT_EVENTS (paintball.py) and
// MAX_ACTIVITY_SPLATS (client/app/js/normalize.js).
export const MAX_SPLATS = 80;
export const MAX_HITS = 8;

export function isDeltaApplicable(state, delta) {
  if (!state || typeof state !== "object" || !delta || typeof delta !== "object") return false;
  const current = Number(state.seq || 0);
  const from = Number(delta.from);
  if (!Number.isFinite(current) || !Number.isFinite(from)) return false;
  return current === from;
}

function mergeParticipantList(current, updates, removed) {
  const next = new Map();
  for (const entry of current || []) {
    if (entry && typeof entry === "object" && entry.id !== undefined) next.set(String(entry.id), { ...entry });
  }
  for (const id of removed || []) next.delete(String(id));
  for (const update of updates || []) {
    if (!update || typeof update !== "object" || update.id === undefined) continue;
    const id = String(update.id);
    const before = next.get(id) || {};
    next.set(id, { ...before, ...update, id: before.id ?? update.id });
  }
  return [...next.values()];
}

function mergeProjectileList(current, added, removed) {
  const gone = new Set((removed || []).map(value => String(value)));
  const next = [];
  for (const entry of current || []) {
    if (entry && typeof entry === "object" && !gone.has(String(entry.id))) next.push({ ...entry });
  }
  for (const entry of added || []) {
    if (!entry || typeof entry !== "object") continue;
    next.push({ ...entry });
  }
  return next;
}

export function applyActivityDelta(state, delta) {
  if (!isDeltaApplicable(state, delta)) return null;
  const next = {
    ...state,
    seq: Number(delta.seq),
    t: Number(delta.t ?? state.t ?? 0),
  };
  for (const key of ["phase", "round", "phase_ends_at", "seconds_left", "status", "field", "scoreboard"]) {
    if (delta[key] !== undefined) next[key] = delta[key];
  }
  if (delta.participants || delta.participants_remove) {
    next.participants = mergeParticipantList(state.participants, delta.participants, delta.participants_remove);
  }
  if (delta.projectiles_add || delta.projectiles_remove) {
    next.projectiles = mergeProjectileList(state.projectiles, delta.projectiles_add, delta.projectiles_remove);
  }
  if (delta.splats_add) {
    next.splats = [...(Array.isArray(state.splats) ? state.splats : []), ...delta.splats_add].slice(-MAX_SPLATS);
  }
  if (delta.hits_add) {
    next.hits = [...(Array.isArray(state.hits) ? state.hits : []), ...delta.hits_add].slice(-MAX_HITS);
  }
  return next;
}

export function projectilePosition(projectile, renderTimeMs, drag = 0) {
  const x0 = Number(projectile?.x) || 0;
  const y0 = Number(projectile?.y) || 0;
  const vx = Number(projectile?.vx) || 0;
  const vy = Number(projectile?.vy) || 0;
  const t0 = Number(projectile?.spawnT);
  const age = Math.max(0, (Number(renderTimeMs) - (Number.isFinite(t0) ? t0 : Number(renderTimeMs))) / 1000);
  const ttl = Number(projectile?.ttl);
  if (Number.isFinite(ttl) && ttl >= 0 && age > ttl) return null;
  const k = Number(drag) || 0;
  if (k <= 1e-6) return [x0 + vx * age, y0 + vy * age];
  const travel = (1 - Math.exp(-k * age)) / k;
  return [x0 + vx * travel, y0 + vy * travel];
}

export function createServerClock() {
  let offset = 0;
  let ready = false;
  return {
    observe(serverTimeMs) {
      const sample = Date.now() - Number(serverTimeMs);
      if (!Number.isFinite(sample)) return;
      if (!ready || sample < offset) {
        offset = sample;
        ready = true;
      }
    },
    now() {
      return Date.now() - offset;
    },
  };
}

export function createParticipantInterpolator({ delayMs = INTERP_DELAY_MS, historyMs = 1000 } = {}) {
  const samples = new Map();
  function push(participants, serverTimeMs) {
    const t = Number(serverTimeMs);
    if (!Number.isFinite(t)) return;
    for (const entry of participants || []) {
      if (!entry || typeof entry !== "object" || entry.id === undefined) continue;
      const x = Number(entry.x);
      const y = Number(entry.y);
      if (!Number.isFinite(x) || !Number.isFinite(y)) continue;
      const id = String(entry.id);
      const list = samples.get(id) || [];
      const last = list[list.length - 1];
      if (last && last.t === t) {
        last.x = x;
        last.y = y;
      } else {
        list.push({ t, x, y });
      }
      while (list.length > 1 && t - list[0].t > historyMs) list.shift();
      samples.set(id, list);
    }
  }
  function forget(ids) {
    for (const id of ids || []) samples.delete(String(id));
  }
  function reset(participants, serverTimeMs) {
    samples.clear();
    push(participants, serverTimeMs);
  }
  function sample(id, renderTimeMs) {
    const list = samples.get(String(id));
    if (!list || !list.length) return null;
    const t = Number(renderTimeMs);
    if (list.length === 1 || t <= list[0].t) return [list[0].x, list[0].y];
    for (let index = 1; index < list.length; index += 1) {
      if (list[index].t >= t) {
        const before = list[index - 1];
        const after = list[index];
        const span = after.t - before.t;
        const alpha = span <= 0 ? 1 : (t - before.t) / span;
        return [before.x + (after.x - before.x) * alpha, before.y + (after.y - before.y) * alpha];
      }
    }
    return [list[list.length - 1].x, list[list.length - 1].y];
  }
  return { push, forget, reset, sample, delayMs };
}
