import { STAGE_H, STAGE_W, createScore, drawSprite, mulberry32 } from "./core.js";
import { createSkin } from "./skin.js";

// Tap when a falling item is inside the marked band.

const FALL_SCALE = 0.6;
const BAND_CENTER = 0.72;
const START_Y = -0.1;
const ITEM_SIZE = 62;

export function createDropCatch(params) {
  const rng = mulberry32(params.seed);
  const score = createScore(params.max_score);
  const bandHeight = params.band * STAGE_H;
  const bandY = BAND_CENTER * STAGE_H;
  const items = [];
  for (let index = 0; index < params.total; index += 1) {
    items.push({
      index,
      x: 110 + rng() * (STAGE_W - 220),
      spawn: 0.5 + index * params.interval,
      state: "fall",
      effectAt: 0,
    });
  }
  const state = { time: 0, finished: false, flash: 0 };

  function itemY(item) {
    return START_Y * STAGE_H + (state.time - item.spawn) * params.speed * FALL_SCALE * STAGE_H;
  }

  function resolve(item, result) {
    item.state = result;
    item.effectAt = state.time;
    score.record(result);
  }

  return {
    id: "drop-catch",
    score,
    get finished() {
      return state.finished;
    },
    get time() {
      return state.time;
    },
    items,
    itemY,
    band: { y: bandY, height: bandHeight },
    update(dt) {
      if (state.finished) return;
      state.time += dt;
      for (const item of items) {
        if (item.state !== "fall" || state.time < item.spawn) continue;
        if (itemY(item) > bandY + bandHeight / 2 + 4) resolve(item, "miss");
      }
      if (items.every(item => item.state !== "fall")) state.finished = true;
    },
    press() {
      if (state.finished) return null;
      let target = null;
      let best = Infinity;
      for (const item of items) {
        if (item.state !== "fall" || state.time < item.spawn) continue;
        const distance = Math.abs(itemY(item) - bandY);
        if (distance < best) {
          best = distance;
          target = item;
        }
      }
      if (!target) return null;
      const result = best <= bandHeight / 2 ? "hit" : "miss";
      resolve(target, result);
      if (items.every(item => item.state !== "fall")) state.finished = true;
      return result;
    },
    release() {},
    draw(ctx, sprite, { reducedMotion = false, skin = createSkin() } = {}) {
      const bandTop = bandY - bandHeight / 2;
      skin.fillRect(ctx, 10, bandTop, STAGE_W - 20, bandHeight);
      skin.edgeRect(ctx, 10, bandTop, STAGE_W - 20, bandHeight, 3);
      for (const item of items) {
        if (state.time < item.spawn) continue;
        const y = itemY(item);
        if (item.state === "fall") {
          drawSprite(ctx, sprite, item.x, y, ITEM_SIZE);
          continue;
        }
        const age = state.time - item.effectAt;
        if (age > 0.55) continue;
        const fade = 1 - age / 0.55;
        if (item.state === "hit") {
          const grow = reducedMotion ? 1 : 1 + age * 1.4;
          drawSprite(ctx, sprite, item.x, y, ITEM_SIZE * grow, { alpha: fade });
          ctx.save();
          ctx.globalAlpha = fade;
          ctx.strokeStyle = skin.good;
          ctx.lineWidth = 4;
          ctx.beginPath();
          ctx.arc(item.x, y, ITEM_SIZE * (0.6 + age * 1.2), 0, Math.PI * 2);
          ctx.stroke();
          ctx.restore();
        } else {
          drawSprite(ctx, sprite, item.x, y + age * 40, ITEM_SIZE, { alpha: fade * 0.8, tint: skin.badSoft });
        }
      }
    },
  };
}
