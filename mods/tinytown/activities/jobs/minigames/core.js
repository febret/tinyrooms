// Shared helpers for the Job Office reflex minigames.
//
// Every minigame is a small deterministic state machine: `update(dt)` advances
// time, `press`/`release`/`key` apply input, and `draw` paints a 800x450 stage.
// Keeping rules separate from rendering lets the node tests drive each game
// with synthetic input.

export const STAGE_W = 800;
export const STAGE_H = 450;

export function mulberry32(seed) {
  let state = (Number(seed) || 1) >>> 0;
  return () => {
    state = (state + 0x6d2b79f5) >>> 0;
    let value = Math.imul(state ^ (state >>> 15), 1 | state);
    value = (value + Math.imul(value ^ (value >>> 7), 61 | value)) ^ value;
    return ((value ^ (value >>> 14)) >>> 0) / 4294967296;
  };
}

export function clamp(value, low, high) {
  return Math.max(low, Math.min(high, value));
}

/** Smallest signed difference between two angles, in radians. */
export function angleDiff(a, b) {
  const full = Math.PI * 2;
  let diff = (a - b) % full;
  if (diff > Math.PI) diff -= full;
  if (diff < -Math.PI) diff += full;
  return diff;
}

export function degToRad(degrees) {
  return (degrees * Math.PI) / 180;
}

/** Create the common outcome tracker every game uses for its HUD pips. */
export function createScore(maxScore) {
  return {
    maxScore,
    outcomes: [],
    penalty: 0,
    record(result) {
      this.outcomes.push(result === "hit" ? "hit" : "miss");
    },
    get hits() {
      return Math.max(0, this.outcomes.filter(entry => entry === "hit").length - this.penalty);
    },
  };
}

export function imageReady(image) {
  return Boolean(image && image.complete && image.naturalWidth > 0);
}

/** Draw a round-masked sprite centered on (x, y) with a given diameter. */
export function drawSprite(ctx, sprite, x, y, size, { alpha = 1, rotation = 0, tint = "", fallback = 0.94, outline = 0.06 } = {}) {
  ctx.save();
  ctx.globalAlpha = alpha;
  ctx.translate(x, y);
  if (rotation) ctx.rotate(rotation);
  const half = size / 2;
  if (imageReady(sprite)) {
    ctx.drawImage(sprite, -half, -half, size, size);
  } else if (sprite && typeof sprite.paint === "function") {
    sprite.paint(ctx, size);
  } else {
    ctx.fillStyle = "#f4e7c8";
    ctx.strokeStyle = "#3e2c1e";
    ctx.lineWidth = Math.max(2, size * outline);
    ctx.beginPath();
    ctx.arc(0, 0, half * fallback, 0, Math.PI * 2);
    ctx.fill();
    ctx.stroke();
  }
  if (tint) {
    ctx.globalCompositeOperation = "source-atop";
    ctx.fillStyle = tint;
    ctx.beginPath();
    ctx.arc(0, 0, half, 0, Math.PI * 2);
    ctx.fill();
  }
  ctx.restore();
}

export const COLORS = {
  ink: "#fff8e8",
  dim: "rgba(255, 248, 232, 0.55)",
};
