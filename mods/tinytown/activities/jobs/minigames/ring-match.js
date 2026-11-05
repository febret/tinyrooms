import { STAGE_H, STAGE_W, createScore, drawSprite, mulberry32 } from "./core.js";
import { createSkin } from "./skin.js";

// Tap each circle as it expands to fill its marked outline.

const MAX_RADIUS = 112;
const TARGET_RADIUS = 70;
const GROWTH_PER_SPEED = 113;
const STAGGER = 0.7;
const FIRST_START = 0.5;
const PICK_REACH = MAX_RADIUS + 24;

export function createRingMatch(params) {
  const rng = mulberry32(params.seed);
  const score = createScore(params.max_score);
  const columns = [170, STAGE_W / 2, STAGE_W - 170];
  const order = columns.map((x, index) => ({ x, index, sort: rng() })).sort((a, b) => a.sort - b.sort);
  const rings = order.slice(0, params.rings).map((slot, k) => ({
    x: slot.x + (rng() * 2 - 1) * 26,
    y: STAGE_H / 2 + (rng() * 2 - 1) * 46,
    start: FIRST_START + k * STAGGER,
    state: "grow",
    resolvedAt: 0,
    radiusAtResolve: 0,
  }));
  const growth = params.speed * GROWTH_PER_SPEED;
  const state = { time: 0, finished: false };

  function radius(ring) {
    return Math.max(0, (state.time - ring.start) * growth);
  }

  function resolve(ring, result) {
    ring.state = result;
    ring.resolvedAt = state.time;
    ring.radiusAtResolve = radius(ring);
    score.record(result);
    if (rings.every(entry => entry.state !== "grow")) state.finished = true;
  }

  return {
    id: "ring-match",
    score,
    rings,
    radius,
    get finished() {
      return state.finished;
    },
    get time() {
      return state.time;
    },
    update(dt) {
      if (state.finished) return;
      state.time += dt;
      for (const ring of rings) {
        if (ring.state !== "grow" || state.time < ring.start) continue;
        if (radius(ring) > TARGET_RADIUS + params.tolerance + 2) resolve(ring, "miss");
      }
    },
    press(point) {
      if (state.finished) return null;
      const active = rings.filter(ring => ring.state === "grow" && state.time >= ring.start);
      if (!active.length) return null;
      let target = null;
      if (point) {
        let best = Infinity;
        for (const ring of active) {
          const distance = Math.hypot(point.x - ring.x, point.y - ring.y);
          if (distance <= PICK_REACH && distance < best) {
            best = distance;
            target = ring;
          }
        }
      } else {
        target = active[0];
      }
      if (!target) return null;
      const result = Math.abs(radius(target) - TARGET_RADIUS) <= params.tolerance ? "hit" : "miss";
      resolve(target, result);
      return result;
    },
    release() {},
    draw(ctx, sprite, { reducedMotion = false, skin = createSkin() } = {}) {
      const inner = Math.max(6, TARGET_RADIUS - params.tolerance);
      const outer = TARGET_RADIUS + params.tolerance;
      for (const ring of rings) {
        if (state.time < ring.start - 0.25) continue;
        const live = ring.state === "grow";
        const age = state.time - ring.resolvedAt;
        if (!live && age > 0.6) continue;
        const fade = live ? 1 : 1 - age / 0.6;
        ctx.save();
        ctx.globalAlpha = Math.min(1, (state.time - (ring.start - 0.25)) / 0.25) * fade;
        const zone = c => {
          c.beginPath();
          c.arc(ring.x, ring.y, outer, 0, Math.PI * 2);
          c.arc(ring.x, ring.y, inner, 0, Math.PI * 2, true);
        };
        zone(ctx);
        ctx.fillStyle = skin.fill(ctx);
        ctx.fill("evenodd");
        skin.edgePath(ctx, c => {
          c.beginPath();
          c.arc(ring.x, ring.y, outer, 0, Math.PI * 2);
        }, 3.5);
        const current = live ? radius(ring) : ring.radiusAtResolve;
        if (current > 2) {
          const tint = !live ? (ring.state === "hit" ? "" : skin.badSoft) : "";
          drawSprite(ctx, sprite, ring.x, ring.y, current * 2, { tint });
          ctx.strokeStyle = ring.state === "hit" ? skin.good : ring.state === "miss" ? skin.bad : skin.ink;
          ctx.lineWidth = 5;
          ctx.beginPath();
          ctx.arc(ring.x, ring.y, current, 0, Math.PI * 2);
          ctx.stroke();
        }
        if (ring.state === "hit" && !reducedMotion) {
          ctx.strokeStyle = skin.good;
          ctx.lineWidth = 3;
          ctx.beginPath();
          ctx.arc(ring.x, ring.y, TARGET_RADIUS + age * 90, 0, Math.PI * 2);
          ctx.stroke();
        }
        ctx.restore();
      }
    },
  };
}
