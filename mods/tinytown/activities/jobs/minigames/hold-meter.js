import { STAGE_H, STAGE_W, createScore, drawSprite, mulberry32 } from "./core.js";
import { createSkin } from "./skin.js";

// Hold to fill the meter, release inside the marked band.

const METER_X = 130;
const METER_W = STAGE_W - 260;
const METER_Y = STAGE_H / 2 - 26;
const METER_H = 52;
const IDLE_LIMIT = 8;
const PAUSE_AFTER = 0.7;

export function createHoldMeter(params) {
  const rng = mulberry32(params.seed);
  const score = createScore(params.max_score);
  const bands = [];
  for (let round = 0; round < params.holds; round += 1) {
    const low = 0.32 + round * 0.04;
    const high = 0.88 - params.band;
    bands.push(low + rng() * Math.max(0.02, high - low));
  }
  const state = {
    time: 0,
    round: 0,
    phase: "wait", // wait | holding | pause
    holdStart: 0,
    roundStart: 0,
    pauseUntil: 0,
    level: 0,
    result: "",
    finished: false,
  };

  function level() {
    if (state.phase === "holding") return Math.min(1, (state.time - state.holdStart) * params.fill);
    return state.level;
  }

  function finishRound(result, finalLevel) {
    state.level = finalLevel;
    state.result = result;
    score.record(result);
    state.phase = "pause";
    state.pauseUntil = state.time + PAUSE_AFTER;
  }

  function nextRound() {
    state.round += 1;
    state.level = 0;
    state.result = "";
    if (state.round >= params.holds) {
      state.finished = true;
      return;
    }
    state.phase = "wait";
    state.roundStart = state.time;
  }

  return {
    id: "hold-meter",
    score,
    bands,
    get finished() {
      return state.finished;
    },
    get time() {
      return state.time;
    },
    get round() {
      return state.round;
    },
    level,
    update(dt) {
      if (state.finished) return;
      state.time += dt;
      if (state.phase === "holding" && level() >= 1) finishRound("miss", 1);
      else if (state.phase === "wait" && state.time - state.roundStart > IDLE_LIMIT) finishRound("miss", 0);
      else if (state.phase === "pause" && state.time >= state.pauseUntil) nextRound();
    },
    press() {
      if (state.finished || state.phase !== "wait") return null;
      state.phase = "holding";
      state.holdStart = state.time;
      return null;
    },
    release() {
      if (state.finished || state.phase !== "holding") return null;
      const value = level();
      const low = bands[state.round];
      const result = value >= low && value <= low + params.band ? "hit" : "miss";
      finishRound(result, value);
      return result;
    },
    draw(ctx, sprite, { skin = createSkin() } = {}) {
      const low = bands[Math.min(state.round, bands.length - 1)];
      ctx.save();
      ctx.fillStyle = "rgba(10, 8, 6, 0.5)";
      ctx.beginPath();
      ctx.roundRect(METER_X, METER_Y, METER_W, METER_H, 26);
      ctx.fill();
      ctx.strokeStyle = "rgba(255, 248, 232, 0.25)";
      ctx.lineWidth = 2;
      ctx.stroke();
      const value = level();
      const color = state.result === "hit" ? skin.good : state.result === "miss" ? skin.bad : skin.accent;
      ctx.fillStyle = color;
      ctx.beginPath();
      ctx.roundRect(METER_X, METER_Y, Math.max(0, value * METER_W), METER_H, 26);
      ctx.fill();
      ctx.restore();
      const bandX = METER_X + low * METER_W;
      const bandW = params.band * METER_W;
      ctx.save();
      ctx.globalAlpha = 0.9;
      skin.fillRect(ctx, bandX, METER_Y - 6, bandW, METER_H + 12);
      ctx.restore();
      skin.edgeRect(ctx, bandX, METER_Y - 6, bandW, METER_H + 12, 3.5);
      drawSprite(ctx, sprite, METER_X + value * METER_W, METER_Y + METER_H / 2 - (state.phase === "holding" ? 6 : 0), 76);
      ctx.fillStyle = "rgba(255, 248, 232, 0.6)";
      ctx.font = skin.font(16);
      ctx.textAlign = "center";
      const caption = state.phase === "holding" ? "Release in the marked zone" : state.phase === "wait" ? "Press and hold" : state.result === "hit" ? "Nailed it" : "Missed";
      ctx.fillText(caption, STAGE_W / 2, METER_Y + METER_H + 58);
      ctx.fillText(`Round ${Math.min(state.round + 1, params.holds)} of ${params.holds}`, STAGE_W / 2, METER_Y - 36);
    },
  };
}
