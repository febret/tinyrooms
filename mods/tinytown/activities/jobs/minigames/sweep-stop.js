import { STAGE_H, STAGE_W, angleDiff, createScore, degToRad, drawSprite, mulberry32 } from "./core.js";
import { createSkin } from "./skin.js";

// Tap to stop a sweeping needle inside the marked arcs.

const CENTER_X = STAGE_W / 2;
const CENTER_Y = STAGE_H / 2 + 8;
const RADIUS = 150;
const MAX_SECONDS = 16;
const TAU = Math.PI * 2;

export function createSweepStop(params) {
  const rng = mulberry32(params.seed);
  const arcWidth = degToRad(params.arc_deg);
  const sector = TAU / 3;
  const slack = Math.max(0, sector / 2 - arcWidth / 2 - degToRad(8));
  // Angles run clockwise from the top of the dial.
  const arcs = [0, 1, 2].map(index => ({
    center: index * sector + sector / 2 + (rng() * 2 - 1) * slack,
    claimed: false,
  }));
  const startAngle = rng() * TAU;
  const score = createScore(params.max_score);
  const state = { time: 0, stops: 0, finished: false, flash: null };

  function needle(time = state.time) {
    return (startAngle + time * params.rev_per_sec * TAU) % TAU;
  }

  function finishIfDone() {
    if (state.stops >= params.stops) state.finished = true;
  }

  return {
    id: "sweep-stop",
    score,
    arcs,
    needle,
    get finished() {
      return state.finished;
    },
    get time() {
      return state.time;
    },
    update(dt) {
      if (state.finished) return;
      state.time += dt;
      if (state.time >= MAX_SECONDS) {
        while (state.stops < params.stops) {
          state.stops += 1;
          score.record("miss");
        }
        state.finished = true;
      }
    },
    press() {
      if (state.finished) return null;
      state.stops += 1;
      const angle = needle();
      const arc = arcs.find(entry => !entry.claimed && Math.abs(angleDiff(angle, entry.center)) <= arcWidth / 2);
      let result = "miss";
      if (arc) {
        arc.claimed = true;
        result = "hit";
      }
      score.record(result);
      state.flash = { at: state.time, angle, result };
      finishIfDone();
      return result;
    },
    release() {},
    draw(ctx, sprite, { skin = createSkin() } = {}) {
      const half = 15;
      ctx.save();
      ctx.translate(CENTER_X, CENTER_Y);
      ctx.lineCap = "round";
      ctx.strokeStyle = "rgba(255, 248, 232, 0.2)";
      ctx.lineWidth = half * 2;
      ctx.beginPath();
      ctx.arc(0, 0, RADIUS, 0, TAU);
      ctx.stroke();
      for (const arc of arcs) {
        const from = arc.center - arcWidth / 2 - Math.PI / 2;
        const trace = c => {
          c.beginPath();
          c.arc(0, 0, RADIUS + half, from, from + arcWidth);
          c.arc(0, 0, RADIUS - half, from + arcWidth, from, true);
          c.closePath();
        };
        ctx.save();
        ctx.globalAlpha = arc.claimed ? 0.35 : 1;
        trace(ctx);
        ctx.fillStyle = skin.fill(ctx);
        ctx.fill();
        skin.edgePath(ctx, trace, 3);
        ctx.restore();
      }
      const angle = needle() - Math.PI / 2;
      ctx.strokeStyle = skin.ink;
      ctx.lineWidth = 4;
      ctx.beginPath();
      ctx.moveTo(0, 0);
      ctx.lineTo(Math.cos(angle) * (RADIUS - 34), Math.sin(angle) * (RADIUS - 34));
      ctx.stroke();
      skin.marker(ctx, Math.cos(angle) * (RADIUS - 40), Math.sin(angle) * (RADIUS - 40), 12, angle);
      ctx.restore();
      drawSprite(ctx, sprite, CENTER_X + Math.cos(angle) * RADIUS, CENTER_Y + Math.sin(angle) * RADIUS, 58);
      ctx.fillStyle = skin.ink;
      ctx.beginPath();
      ctx.arc(CENTER_X, CENTER_Y, 10, 0, TAU);
      ctx.fill();
      if (state.flash && state.time - state.flash.at < 0.5) {
        const fade = 1 - (state.time - state.flash.at) / 0.5;
        const flashAngle = state.flash.angle - Math.PI / 2;
        ctx.save();
        ctx.globalAlpha = fade;
        ctx.fillStyle = state.flash.result === "hit" ? skin.good : skin.bad;
        ctx.beginPath();
        ctx.arc(CENTER_X + Math.cos(flashAngle) * RADIUS, CENTER_Y + Math.sin(flashAngle) * RADIUS, 26 + (1 - fade) * 22, 0, TAU);
        ctx.fill();
        ctx.restore();
      }
    },
  };
}
