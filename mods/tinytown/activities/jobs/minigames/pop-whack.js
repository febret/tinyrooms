import { STAGE_H, STAGE_W, createScore, drawSprite, mulberry32 } from "./core.js";
import { createSkin } from "./skin.js";

// Tap the good ones before they hide. Leave the red-ringed decoys alone.

const HOLE_RADIUS = 56;
const SPRITE_SIZE = 84;
const RISE = 0.14;
const GRID = [
  [0, 0], [1, 0], [2, 0],
  [0, 1], [1, 1], [2, 1],
  [0, 2], [1, 2], [2, 2],
].map(([col, row]) => ({
  x: STAGE_W / 2 + (col - 1) * 190,
  y: STAGE_H / 2 + (row - 1) * 118 + 12,
}));

export function createPopWhack(params) {
  const rng = mulberry32(params.seed);
  const score = createScore(params.max_score);
  const slots = [];
  for (let index = 0; index < params.targets; index += 1) slots.push("good");
  for (let index = 0; index < params.decoys; index += 1) slots.push("decoy");
  for (let index = slots.length - 1; index > 0; index -= 1) {
    const swap = Math.floor(rng() * (index + 1));
    [slots[index], slots[swap]] = [slots[swap], slots[index]];
  }
  const spacing = params.visible * 0.75 + 0.3;
  const events = [];
  const busy = new Map();
  slots.forEach((kind, index) => {
    const spawn = 0.6 + index * spacing;
    let hole = Math.floor(rng() * GRID.length);
    for (let attempt = 0; attempt < GRID.length; attempt += 1) {
      const free = [...busy.entries()].every(([other, until]) => other !== hole || until <= spawn);
      if (free) break;
      hole = (hole + 1) % GRID.length;
    }
    busy.set(hole, spawn + params.visible);
    events.push({ index, kind, hole, spawn, expire: spawn + params.visible, state: "wait", effectAt: 0 });
  });
  const state = { time: 0, finished: false, wrong: 0 };

  function isActive(event) {
    return event.state === "wait" && state.time >= event.spawn && state.time < event.expire;
  }

  function finishIfDone() {
    if (events.every(event => event.state !== "wait")) state.finished = true;
  }

  function tapHole(hole) {
    const event = events.filter(entry => entry.hole === hole && isActive(entry)).pop();
    if (!event) return null;
    event.effectAt = state.time;
    if (event.kind === "good") {
      event.state = "hit";
      score.record("hit");
      finishIfDone();
      return "hit";
    }
    event.state = "decoy-tapped";
    score.penalty += 1;
    state.wrong = state.time;
    finishIfDone();
    return "miss";
  }

  return {
    id: "pop-whack",
    score,
    events,
    holes: GRID,
    get finished() {
      return state.finished;
    },
    get time() {
      return state.time;
    },
    update(dt) {
      if (state.finished) return;
      state.time += dt;
      for (const event of events) {
        if (event.state === "wait" && state.time >= event.expire) {
          event.state = "gone";
          event.effectAt = state.time;
          if (event.kind === "good") score.record("miss");
        }
      }
      finishIfDone();
    },
    press(point) {
      if (state.finished || !point) return null;
      let best = -1;
      let bestDistance = Infinity;
      GRID.forEach((hole, index) => {
        const distance = Math.hypot(point.x - hole.x, point.y - hole.y);
        if (distance <= HOLE_RADIUS + 12 && distance < bestDistance) {
          best = index;
          bestDistance = distance;
        }
      });
      return best < 0 ? null : tapHole(best);
    },
    key(key) {
      if (state.finished) return null;
      const number = Number.parseInt(key, 10);
      if (!(number >= 1 && number <= 9)) return null;
      return tapHole(number - 1);
    },
    release() {},
    draw(ctx, sprite, { reducedMotion = false, skin = createSkin() } = {}) {
      GRID.forEach(hole => {
        const mound = c => {
          c.beginPath();
          c.ellipse(hole.x, hole.y + 22, HOLE_RADIUS + 9, 31, 0, 0, Math.PI * 2);
        };
        ctx.save();
        mound(ctx);
        ctx.fillStyle = skin.fill(ctx);
        ctx.fill();
        skin.edgePath(ctx, mound, 2.6);
        ctx.fillStyle = "rgba(10, 7, 4, 0.78)";
        ctx.beginPath();
        ctx.ellipse(hole.x, hole.y + 22, HOLE_RADIUS - 2, 20, 0, 0, Math.PI * 2);
        ctx.fill();
        ctx.restore();
      });
      for (const event of events) {
        const hole = GRID[event.hole];
        const age = state.time - event.spawn;
        if (age < 0) continue;
        let lift = Math.min(1, age / RISE);
        let alpha = 1;
        if (event.state === "wait") {
          const remaining = event.expire - state.time;
          lift = Math.min(lift, Math.max(0, remaining / RISE));
        } else {
          const after = state.time - event.effectAt;
          if (after > 0.35) continue;
          lift = Math.max(0, 1 - after / 0.35);
          alpha = lift;
        }
        const y = hole.y + 22 - lift * (SPRITE_SIZE * 0.55 + 22);
        ctx.save();
        ctx.beginPath();
        ctx.rect(hole.x - HOLE_RADIUS - 10, hole.y - SPRITE_SIZE - 20, HOLE_RADIUS * 2 + 20, SPRITE_SIZE + 42);
        ctx.clip();
        drawSprite(ctx, sprite, hole.x, y, SPRITE_SIZE, { alpha });
        if (event.kind === "decoy") {
          ctx.strokeStyle = skin.bad;
          ctx.lineWidth = 7;
          ctx.beginPath();
          ctx.arc(hole.x, y, SPRITE_SIZE / 2 + 2, 0, Math.PI * 2);
          ctx.stroke();
          ctx.beginPath();
          ctx.moveTo(hole.x - 26, y - 26);
          ctx.lineTo(hole.x + 26, y + 26);
          ctx.stroke();
        }
        ctx.restore();
        if (event.state === "hit" && !reducedMotion) {
          const after = state.time - event.effectAt;
          ctx.save();
          ctx.globalAlpha = Math.max(0, 1 - after / 0.35);
          ctx.strokeStyle = skin.good;
          ctx.lineWidth = 4;
          ctx.beginPath();
          ctx.arc(hole.x, hole.y - 20, 40 + after * 120, 0, Math.PI * 2);
          ctx.stroke();
          ctx.restore();
        }
      }
      GRID.forEach((hole, index) => {
        ctx.fillStyle = "rgba(255, 248, 232, 0.45)";
        ctx.font = skin.font(14);
        ctx.textAlign = "center";
        ctx.fillText(String(index + 1), hole.x, hole.y + 52);
      });
    },
  };
}
