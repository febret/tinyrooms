import { COLORS, STAGE_H, STAGE_W } from "./core.js";
import { createGame } from "./index.js";
import { createSkin } from "./skin.js";

export const CANCELLED_MESSAGE = "Challenge cancelled.";
const COUNTDOWN_STEPS = ["3", "2", "1", "Go!"];
const COUNTDOWN_STEP_SECONDS = 0.55;
const FINISH_HOLD_SECONDS = 0.9;
const MAX_FRAME_SECONDS = 0.05;

function logicalPoint(canvas, event) {
  const bounds = canvas.getBoundingClientRect();
  return {
    x: ((event.clientX - bounds.left) / bounds.width) * STAGE_W,
    y: ((event.clientY - bounds.top) / bounds.height) * STAGE_H,
  };
}

export function drawHud(ctx, game, params, skin = createSkin()) {
  const total = game.score.maxScore;
  const gap = 30;
  const startX = STAGE_W / 2 - ((total - 1) * gap) / 2;
  for (let index = 0; index < total; index += 1) {
    skin.pip(ctx, startX + index * gap, 26, 9, game.score.outcomes[index]);
  }
  ctx.fillStyle = COLORS.dim;
  ctx.font = skin.font(13);
  ctx.textAlign = "center";
  const label = params.payout
    ? `Score ${game.score.hits}/${total} — a bigger score pays more`
    : `Need ${params.required} of ${total}`;
  ctx.fillText(label, STAGE_W / 2, 52);
}

function drawCountdown(ctx, label, progress, skin) {
  ctx.save();
  ctx.fillStyle = "rgba(14, 10, 6, 0.55)";
  ctx.fillRect(0, 0, STAGE_W, STAGE_H);
  ctx.fillStyle = COLORS.ink;
  ctx.textAlign = "center";
  ctx.textBaseline = "middle";
  const size = 120 + (1 - progress) * 34;
  ctx.font = skin.font(size);
  ctx.globalAlpha = 0.35 + 0.65 * progress;
  ctx.fillText(label, STAGE_W / 2, STAGE_H / 2);
  ctx.restore();
}

/** Low energy dims the edges and, for the drained, droops the eyelids now and then. */
export function drawDrowsy(ctx, fatigue, time, reducedMotion = false) {
  const level = Math.max(0, (Number(fatigue) - 0.3) / 0.7);
  if (!(level > 0)) return;
  ctx.save();
  const vignette = ctx.createRadialGradient(STAGE_W / 2, STAGE_H / 2, STAGE_H * 0.3, STAGE_W / 2, STAGE_H / 2, STAGE_W * 0.62);
  vignette.addColorStop(0, "rgba(20, 24, 48, 0)");
  vignette.addColorStop(1, `rgba(20, 24, 48, ${0.2 + level * 0.4})`);
  ctx.fillStyle = vignette;
  ctx.fillRect(0, 0, STAGE_W, STAGE_H);
  if (!reducedMotion && level > 0.35) {
    const droop = level * 0.15 * (0.5 + 0.5 * Math.sin(time * 1.3)) ** 2;
    const lid = STAGE_H * droop;
    if (lid > 1) {
      ctx.fillStyle = "rgba(8, 10, 22, 0.88)";
      ctx.fillRect(0, 0, STAGE_W, lid);
      ctx.fillRect(0, STAGE_H - lid, STAGE_W, lid);
    }
  }
  ctx.restore();
}

/**
 * Run one minigame inside `host`. Resolves with { score, elapsedMs, outcomes }.
 * `onResult(result)` fires for each scored tap so the caller can play sounds and
 * react; `onPhase(name, detail)` reports "countdown", "play", and "done".
 */
export function runMinigame({
  host,
  gameId,
  params,
  sprite,
  theme = null,
  arena = null,
  skin = null,
  overlay = null,
  reducedMotion = false,
  onResult = () => {},
  onPhase = () => {},
}) {
  const game = createGame(gameId, params);
  const activeSkin = skin || createSkin(theme || undefined);
  let clock = 0;
  const canvas = document.createElement("canvas");
  canvas.className = "jobs-game-canvas";
  canvas.tabIndex = 0;
  canvas.setAttribute("aria-label", "Reflex challenge. Tap, click, or press Space.");
  host.replaceChildren(canvas);
  const ctx = canvas.getContext("2d");

  let frame = 0;
  let last = 0;
  let phase = "countdown";
  let phaseTime = 0;
  let elapsed = 0;
  let settled = false;
  let countdownIndex = -1;
  let resolvePromise = () => {};
  let rejectPromise = () => {};
  const promise = new Promise((resolve, reject) => {
    resolvePromise = resolve;
    rejectPromise = reject;
  });

  function resize() {
    const bounds = canvas.getBoundingClientRect();
    const ratio = Math.min(window.devicePixelRatio || 1, 2);
    const width = Math.max(1, Math.round(bounds.width * ratio));
    if (canvas.width !== width) {
      canvas.width = width;
      canvas.height = Math.round((width * STAGE_H) / STAGE_W);
    }
    ctx.setTransform(canvas.width / STAGE_W, 0, 0, canvas.width / STAGE_W, 0, 0);
  }

  let reported = 0;

  // Report every newly scored outcome (including ones the game scored on its own,
  // like a token falling past the band) plus penalty taps that add no pip.
  function report(pressResult = null) {
    const fresh = game.score.outcomes.slice(reported);
    reported = game.score.outcomes.length;
    for (const outcome of fresh) onResult(outcome);
    if (pressResult === "miss" && !fresh.length) onResult("miss");
  }

  function onPointerDown(event) {
    if (phase !== "play") return;
    event.preventDefault();
    canvas.setPointerCapture?.(event.pointerId);
    report(game.press(logicalPoint(canvas, event)));
  }

  function onPointerUp(event) {
    if (phase !== "play") return;
    event.preventDefault();
    report(game.release());
  }

  function onKeyDown(event) {
    if (phase !== "play" || event.repeat) return;
    if (event.key === " " || event.key === "Enter") {
      event.preventDefault();
      report(game.press(null));
      return;
    }
    if (game.key) report(game.key(event.key));
  }

  function onKeyUp(event) {
    if (phase !== "play") return;
    if (event.key === " " || event.key === "Enter") {
      event.preventDefault();
      report(game.release());
    }
  }

  function cleanup() {
    cancelAnimationFrame(frame);
    canvas.removeEventListener("pointerdown", onPointerDown);
    canvas.removeEventListener("pointerup", onPointerUp);
    canvas.removeEventListener("pointercancel", onPointerUp);
    document.removeEventListener("keydown", onKeyDown);
    document.removeEventListener("keyup", onKeyUp);
  }

  function finish() {
    if (settled) return;
    settled = true;
    cleanup();
    resolvePromise({
      score: game.score.hits,
      elapsedMs: Math.round(elapsed * 1000),
      outcomes: [...game.score.outcomes],
    });
  }

  function paint() {
    activeSkin.arena(ctx, arena, STAGE_W, STAGE_H);
    game.draw(ctx, sprite, { reducedMotion, skin: activeSkin });
    drawHud(ctx, game, params, activeSkin);
    activeSkin.frame(ctx, STAGE_W, STAGE_H);
    drawDrowsy(ctx, params.fatigue, clock, reducedMotion);
    overlay?.(ctx, {
      clock,
      phase,
      game,
      width: STAGE_W,
      height: STAGE_H,
      skin: activeSkin,
      reducedMotion,
    });
  }

  function tick(now) {
    if (settled) return;
    const dt = last ? Math.min(MAX_FRAME_SECONDS, (now - last) / 1000) : 0;
    last = now;
    resize();
    clock += dt;
    ctx.clearRect(0, 0, STAGE_W, STAGE_H);
    if (phase === "countdown") {
      phaseTime += dt;
      const index = Math.min(COUNTDOWN_STEPS.length - 1, Math.floor(phaseTime / COUNTDOWN_STEP_SECONDS));
      const within = (phaseTime % COUNTDOWN_STEP_SECONDS) / COUNTDOWN_STEP_SECONDS;
      if (index !== countdownIndex) {
        countdownIndex = index;
        onPhase("countdown", COUNTDOWN_STEPS[index]);
      }
      paint();
      drawCountdown(ctx, COUNTDOWN_STEPS[index], 1 - within, activeSkin);
      if (phaseTime >= COUNTDOWN_STEPS.length * COUNTDOWN_STEP_SECONDS) {
        phase = "play";
        phaseTime = 0;
        onPhase("play");
        canvas.focus({ preventScroll: true });
      }
    } else {
      if (phase === "play") {
        game.update(dt);
        report();
        elapsed += dt;
        if (game.finished) {
          phase = "done";
          phaseTime = 0;
          onPhase("done", { score: game.score.hits });
        }
      } else {
        phaseTime += dt;
        game.update(dt);
        report();
        if (phaseTime >= FINISH_HOLD_SECONDS) {
          finish();
          return;
        }
      }
      paint();
    }
    frame = requestAnimationFrame(tick);
  }

  canvas.addEventListener("pointerdown", onPointerDown);
  canvas.addEventListener("pointerup", onPointerUp);
  canvas.addEventListener("pointercancel", onPointerUp);
  document.addEventListener("keydown", onKeyDown);
  document.addEventListener("keyup", onKeyUp);
  frame = requestAnimationFrame(tick);

  return {
    promise,
    cancel() {
      if (settled) return;
      settled = true;
      cleanup();
      rejectPromise(new Error(CANCELLED_MESSAGE));
    },
  };
}
