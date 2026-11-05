import { STAGE_H, STAGE_W, createScore, drawSprite, mulberry32 } from "./core.js";
import { createSkin } from "./skin.js";

// Tap as each item reaches the glowing line.

const HIT_X = 170;
const LANE_Y = STAGE_H / 2 + 10;
const SPAWN_X = STAGE_W + 60;
const NOTE_SIZE = 64;

export function createRhythmLane(params) {
  const rng = mulberry32(params.seed);
  const score = createScore(params.max_score);
  const grace = params.window_ms / 1000;
  const speed = (SPAWN_X - HIT_X) / params.travel;
  const notes = [];
  let at = params.travel * 0.85 + 0.35;
  for (let index = 0; index < params.notes; index += 1) {
    notes.push({ index, time: at, state: "wait", effectAt: 0 });
    at += params.gap * (rng() < 0.25 ? 1.5 : 1);
  }
  const state = { time: 0, finished: false, pulse: 0 };

  function noteX(note) {
    return HIT_X + (note.time - state.time) * speed;
  }

  function resolve(note, result) {
    note.state = result;
    note.effectAt = state.time;
    score.record(result);
    if (result === "hit") state.pulse = state.time;
    if (notes.every(entry => entry.state === "hit" || entry.state === "miss")) state.finished = true;
  }

  return {
    id: "rhythm-lane",
    score,
    notes,
    get finished() {
      return state.finished;
    },
    get time() {
      return state.time;
    },
    update(dt) {
      if (state.finished) return;
      state.time += dt;
      for (const note of notes) {
        if (note.state === "wait" && state.time > note.time + grace) resolve(note, "miss");
      }
    },
    press() {
      if (state.finished) return null;
      let target = null;
      let best = Infinity;
      for (const note of notes) {
        if (note.state !== "wait") continue;
        const distance = Math.abs(state.time - note.time);
        if (distance < best) {
          best = distance;
          target = note;
        }
      }
      if (!target) return null;
      if (best <= grace) {
        resolve(target, "hit");
        return "hit";
      }
      if (best <= grace * 2.4) {
        resolve(target, "miss");
        return "miss";
      }
      return null;
    },
    release() {},
    draw(ctx, sprite, { reducedMotion = false, skin = createSkin() } = {}) {
      ctx.save();
      ctx.fillStyle = "rgba(10, 8, 6, 0.42)";
      ctx.fillRect(0, LANE_Y - 44, STAGE_W, 88);
      ctx.strokeStyle = "rgba(255, 248, 232, 0.3)";
      ctx.lineWidth = 2;
      ctx.beginPath();
      ctx.moveTo(0, LANE_Y - 44);
      ctx.lineTo(STAGE_W, LANE_Y - 44);
      ctx.moveTo(0, LANE_Y + 44);
      ctx.lineTo(STAGE_W, LANE_Y + 44);
      ctx.stroke();
      ctx.restore();
      const pulse = reducedMotion ? 0 : Math.max(0, 1 - (state.time - state.pulse) / 0.25);
      const zoneX = HIT_X - grace * speed;
      const zoneW = grace * speed * 2;
      skin.fillRect(ctx, zoneX, LANE_Y - 60, zoneW, 120);
      skin.edgeRect(ctx, zoneX, LANE_Y - 60, zoneW, 120, 3);
      ctx.save();
      ctx.strokeStyle = skin.good;
      ctx.lineWidth = 3 + pulse * 5;
      ctx.beginPath();
      ctx.moveTo(HIT_X, LANE_Y - 60);
      ctx.lineTo(HIT_X, LANE_Y + 60);
      ctx.stroke();
      ctx.beginPath();
      ctx.arc(HIT_X, LANE_Y, NOTE_SIZE / 2 + 8 + pulse * 10, 0, Math.PI * 2);
      ctx.stroke();
      ctx.restore();
      skin.marker(ctx, HIT_X, LANE_Y - 76, 9, Math.PI / 2);
      skin.marker(ctx, HIT_X, LANE_Y + 76, 9, -Math.PI / 2);
      for (const note of notes) {
        const x = noteX(note);
        if (note.state === "wait") {
          if (x < SPAWN_X + 40) drawSprite(ctx, sprite, x, LANE_Y, NOTE_SIZE);
          continue;
        }
        const age = state.time - note.effectAt;
        if (age > 0.45) continue;
        const fade = 1 - age / 0.45;
        if (note.state === "hit") {
          const size = NOTE_SIZE * (reducedMotion ? 1 : 1 + age * 1.1);
          drawSprite(ctx, sprite, HIT_X, LANE_Y - (reducedMotion ? 0 : age * 36), size, { alpha: fade });
        } else {
          drawSprite(ctx, sprite, x, LANE_Y + age * 30, NOTE_SIZE, { alpha: fade * 0.8, tint: skin.badSoft });
        }
      }
    },
  };
}
