import { PLAYER_SPRITE_WORLD_HEIGHT, backingStoreSize, cameraOffset, clamp, easeInOutQuad, explosionParticles, fadeAlpha, hashId, moveCircle, normalizeVector, stepVelocity, stickVector, viewScale } from "./arena.js";
import { INTERP_DELAY_MS, applyActivityDelta, createParticipantInterpolator, createServerClock, projectilePosition } from "./sync.js";
import { renderPodium } from "./podium.js";

const Tiny = window.TinyActivity;
const canvas = document.querySelector("#arena");
const context = canvas.getContext("2d");
const connection = document.querySelector("#connection");
const statusView = document.querySelector("#status");
const scoreboardView = document.querySelector("#scoreboard");
const streakView = document.querySelector("#streak");
const streakCountView = document.querySelector("#streak-count");
const streakBestView = document.querySelector("#streak-best");
const podium = document.querySelector("#podium");

const FIELD_IMAGES = {
  neon: "/activities/paintball/assets/field-neon.png",
  jungle: "/activities/paintball/assets/field-jungle.png",
  desert: "/activities/paintball/assets/field-desert.png",
  urban: "/activities/paintball/assets/field-urban.png",
};
const OBSTACLE_IMAGES = {
  barrel: "/activities/paintball/assets/obstacle-barrel.png",
  bunker: "/activities/paintball/assets/obstacle-bunker.png",
  spool: "/activities/paintball/assets/obstacle-spool.png",
  rock: "/activities/paintball/assets/obstacle-rock.png",
};

let host = null;
let width = 0;
let height = 0;
let scale = 1;
let offsetX = 0;
let offsetY = 0;
let keys = new Set();
let mouseArena = null;
let mouseFire = false;
let sticks = new Map();
let localPlayer = null;
let sprites = new Map();
let arenaState = null;
let arenaSeq = 0;
const interpolator = createParticipantInterpolator({ delayMs: INTERP_DELAY_MS });
const serverClock = createServerClock();
let lastInputPacket = "";
let lastInputSentAt = 0;
let lastInputError = "";
let lastInputErrorAt = 0;
let lastHudAt = 0;
let lastFrame = 0;
let lastPodiumKey = "";
let hitEffects = [];
let seenHitIds = new Set();
let seenProjectileIds = new Set();
let projectilesPrimed = false;
let lastSplatSoundAt = 0;
let roundFeeRound = 0;
let roundFeePending = 0;
let roundFeeFailed = 0;
let lastSoundPhase = "";
let lastSoundRound = 0;
let streakValue = 0;
let streakBest = 0;
let streakRound = 0;
let streakSeeded = false;
let lastLocalHits = 0;
let lastLocalRespawn = 0;
let streakPopTimer = 0;
let respawnGlide = null;
let respawnFade = null;

function activityState() {
  const activity = host?.room?.activities?.paintball;
  if (!activity || activity.kind !== "paintball") return null;
  return activity.state && typeof activity.state === "object" ? activity.state : null;
}

function controller() {
  const value = host?.room?.activities?.paintball?.controller;
  return typeof value === "string" && value ? value : "";
}

function tuning(state) {
  return {
    radius: Number(state?.tuning?.player_radius) || 1.8,
    playerSpeed: Number(state?.tuning?.player_speed) || 24,
    projectileDrag: Number(state?.tuning?.projectile_drag) || 0,
    moveAccel: Number(state?.tuning?.move_accel) || 160,
    moveFriction: Number(state?.tuning?.move_friction) || 220,
    fireCooldown: Number(state?.tuning?.fire_cooldown) || 0.45,
  };
}

function arenaSize(state) {
  return {
    width: Number(state?.arena?.width) || 100,
    height: Number(state?.arena?.height) || 100,
  };
}

function obstacles(state) {
  return Array.isArray(state?.obstacles) ? state.obstacles : [];
}

function spriteImage(url) {
  if (!url) return null;
  let record = sprites.get(url);
  if (!record) {
    const image = new Image();
    image.decoding = "async";
    image.src = url;
    record = { image, ready: false };
    image.addEventListener("load", () => { record.ready = true; });
    sprites.set(url, record);
  }
  return record.ready ? record.image : null;
}

function occupantSticker(participantId) {
  const occupants = host?.room?.occupants;
  if (!Array.isArray(occupants)) return "";
  const occupant = occupants.find(entry => String(entry?.id) === String(participantId));
  return occupant?.stickerUrl || "";
}

function participantSprite(participant) {
  if (participant.kind === "bot" && participant.sprite) {
    const worldId = host?.user?.worldId || "";
    if (worldId) return spriteImage(Tiny.image(`/assets/world/${worldId}/peeps/${participant.sprite}.png`));
  }
  if (participant.kind !== "bot") {
    const sticker = occupantSticker(participant.id);
    if (sticker) return spriteImage(sticker);
  }
  return null;
}

function fieldImage(state) {
  const name = String(state?.field || "");
  if (!FIELD_IMAGES[name]) return null;
  return spriteImage(Tiny.image(FIELD_IMAGES[name]));
}

function obstacleImage(obstacle) {
  const name = String(obstacle?.sprite || "");
  if (!OBSTACLE_IMAGES[name]) return null;
  return spriteImage(Tiny.image(OBSTACLE_IMAGES[name]));
}

function podiumImageUrl(entry) {
  if (!entry) return "";
  const id = String(entry.id || "");
  if (entry.bot || id.startsWith("paintbot-")) {
    const sprite = String(entry.sprite || id);
    const worldId = host?.user?.worldId || "";
    if (sprite && worldId) return Tiny.image(`/assets/world/${worldId}/peeps/${sprite}.png`);
    return "";
  }
  return occupantSticker(id);
}

function isImmune(participant) {
  return Boolean(participant?.immune_until) && Date.parse(String(participant.immune_until)) > Date.now();
}

function reducedMotion() {
  return Boolean(host?.config?.reducedMotion);
}

function roundFeeStorageKey() {
  return `tinyrooms:paintball:round-fee:${Tiny.activityId || "local"}`;
}

function storedPaidRound() {
  try {
    return Math.max(0, Number(window.sessionStorage.getItem(roundFeeStorageKey()) || 0));
  } catch {
    return 0;
  }
}

function rememberPaidRound(round) {
  try {
    window.sessionStorage.setItem(roundFeeStorageKey(), String(round));
  } catch {
    // Storage is optional; the in-memory guard still covers this window.
  }
}

roundFeeRound = storedPaidRound();

function roundEntryCost() {
  return Math.max(0, Number(host?.activity?.config?.start_cost ?? 0));
}

function roundEntryPaid(state) {
  const cost = roundEntryCost();
  if (cost <= 0) return true;
  return roundFeeRound === Number(state?.round || 0);
}

function chargeRoundEntry(state) {
  const cost = roundEntryCost();
  const round = Number(state?.round || 0);
  if (cost <= 0 || state?.phase !== "active" || round <= 0) return;
  if (roundFeeRound === round || roundFeePending === round || roundFeeFailed === round) return;
  roundFeePending = round;
  void Tiny.command(".activity_start")
    .then(reply => {
      roundFeeRound = round;
      rememberPaidRound(round);
      const charged = Number(reply?.payload?.round?.charged || 0);
      if (charged > 0) Tiny.toast(`Round entry cost ${charged} Energy.`, false, false);
    })
    .catch(error => {
      roundFeeFailed = round;
      Tiny.toast(error instanceof Error ? error.message : String(error), true);
    })
    .finally(() => {
      if (roundFeePending === round) roundFeePending = 0;
    });
}

function observeShots(state) {
  const projectiles = Array.isArray(state?.projectiles) ? state.projectiles : [];
  const localId = String(host?.user?.id || "");
  if (!projectilesPrimed) {
    for (const projectile of projectiles) seenProjectileIds.add(String(projectile?.id || ""));
    projectilesPrimed = true;
    return;
  }
  for (const projectile of projectiles) {
    const id = String(projectile?.id || "");
    if (!id || seenProjectileIds.has(id)) continue;
    seenProjectileIds.add(id);
    if (localId && String(projectile?.owner || "") === localId) Tiny.sound("paintballShot");
  }
  if (seenProjectileIds.size > 512) {
    seenProjectileIds = new Set(projectiles.map(projectile => String(projectile?.id || "")));
  }
}

function announceRoundSound(state) {
  const phase = String(state?.phase || "");
  const round = Number(state?.round || 0);
  if (phase === "active" && round > 0 && (lastSoundPhase !== "active" || lastSoundRound !== round)) {
    Tiny.sound("paintballRound");
    seenProjectileIds.clear();
    projectilesPrimed = false;
  } else if (phase !== "active" && lastSoundPhase === "active") {
    Tiny.sound("success");
  }
  lastSoundPhase = phase;
  lastSoundRound = round;
}

function showStreakPop(amount) {
  if (reducedMotion() || !streakView) return;
  streakView.querySelector(".paint-streak-pop")?.remove();
  const pop = document.createElement("span");
  pop.className = "paint-streak-pop";
  pop.textContent = `+${amount}`;
  pop.setAttribute("aria-hidden", "true");
  streakView.append(pop);
  clearTimeout(streakPopTimer);
  streakPopTimer = window.setTimeout(() => pop.remove(), 850);
}

function setStreak(value, { bump = 0, reset = false, silent = false } = {}) {
  if (!streakView || !streakCountView || !streakBestView) return;
  const previous = streakValue;
  streakValue = Math.max(0, Number(value) || 0);
  streakBest = Math.max(streakBest, streakValue);
  streakCountView.textContent = String(streakValue);
  streakBestView.textContent = `Best ${streakBest}`;
  streakView.dataset.streak = String(streakValue);
  streakView.setAttribute("aria-label", `Hit streak: ${streakValue}`);
  streakView.classList.toggle("is-hot", streakValue >= 3);
  streakView.classList.toggle("is-blazing", streakValue >= 5);
  streakView.classList.toggle("is-legendary", streakValue >= 10);
  if (silent) return;
  if (reset && previous > 0) {
    streakView.classList.remove("is-reset");
    void streakView.offsetWidth;
    streakView.classList.add("is-reset");
  }
  if (bump > 0) {
    streakView.classList.remove("is-bump");
    void streakView.offsetWidth;
    streakView.classList.add("is-bump");
    showStreakPop(bump);
  }
}

function updateHitStreak(state, me) {
  const round = Number(state?.round || 0);
  const score = (state.scoreboard || []).find(entry => String(entry?.id) === String(host?.user?.id));
  const hits = Math.max(0, Number(score?.hits || 0));
  const respawn = Math.max(0, Number(me?.respawn || 0));
  if (!streakSeeded || round !== streakRound) {
    streakRound = round;
    lastLocalHits = hits;
    lastLocalRespawn = respawn;
    streakSeeded = true;
    setStreak(0, { silent: true });
    return;
  }
  if (respawn !== lastLocalRespawn) {
    lastLocalRespawn = respawn;
    lastLocalHits = hits;
    setStreak(0, { reset: true });
    return;
  }
  if (hits > lastLocalHits) {
    const gained = hits - lastLocalHits;
    lastLocalHits = hits;
    setStreak(streakValue + gained, { bump: gained });
  } else if (hits < lastLocalHits) {
    lastLocalHits = hits;
  }
}

function drawShieldShimmer(x, y, bodyH) {
  const centerY = y - bodyH * 0.4;
  const seconds = performance.now() / 1000;
  const pulse = reducedMotion() ? 0.5 : 0.5 + 0.5 * Math.sin(seconds * 5.2);
  const glowR = bodyH * (0.72 + 0.08 * pulse);
  context.save();
  context.globalAlpha = 0.5 + 0.25 * pulse;
  const halo = context.createRadialGradient(x, centerY, bodyH * 0.28, x, centerY, glowR);
  halo.addColorStop(0, "rgba(25,227,255,0)");
  halo.addColorStop(0.72, "rgba(25,227,255,0.16)");
  halo.addColorStop(1, "rgba(25,227,255,0.42)");
  context.fillStyle = halo;
  context.beginPath();
  context.arc(x, centerY, glowR, 0, Math.PI * 2);
  context.fill();
  context.restore();
  if (reducedMotion()) return;
  context.save();
  context.beginPath();
  context.arc(x, centerY, glowR * 0.94, 0, Math.PI * 2);
  context.clip();
  context.translate(x, centerY);
  context.rotate(Math.sin(seconds * 1.7) * 0.9);
  const sweep = Math.sin(seconds * 2.3) * 0.5 + 0.5;
  const band = context.createLinearGradient(-glowR * 1.2, 0, glowR * 1.2, 0);
  band.addColorStop(Math.max(0, sweep - 0.28), "rgba(255,255,255,0)");
  band.addColorStop(sweep, "rgba(255,255,255,0.34)");
  band.addColorStop(Math.min(1, sweep + 0.28), "rgba(255,255,255,0)");
  context.fillStyle = band;
  context.fillRect(-glowR * 1.2, -glowR * 1.2, glowR * 2.4, glowR * 2.4);
  context.restore();
}

function ghostImage(hit) {
  if (!hit) return null;
  return participantSprite({
    id: hit.victim,
    kind: hit.kind,
    sprite: hit.sprite,
    color: hit.color,
  });
}

function observeHits(state) {
  const now = performance.now();
  const reducedMotion = Boolean(host?.config?.reducedMotion);
  for (const hit of state?.hits || []) {
    const id = String(hit?.id || "");
    if (!id || seenHitIds.has(id)) continue;
    seenHitIds.add(id);
    if (seenHitIds.size > 64) seenHitIds.delete(seenHitIds.values().next().value);
    if (now - lastSplatSoundAt > 120) {
      lastSplatSoundAt = now;
      Tiny.sound("paintballSplat");
    }
    hitEffects.push({
      id,
      x: Number(hit.x) || 0,
      y: Number(hit.y) || 0,
      color: String(hit.color || "#ff4d6d"),
      ghost: {
        id: String(hit.victim || ""),
        kind: String(hit.kind || "user"),
        sprite: String(hit.sprite || ""),
        color: String(hit.color || "#ff4d6d"),
      },
      seed: hashId(id),
      bornAt: now,
      particles: reducedMotion ? [] : explosionParticles(hashId(id)),
      ghostMs: reducedMotion ? 320 : 900,
      blastMs: reducedMotion ? 260 : 650,
    });
  }
  hitEffects = hitEffects.filter(effect => now - effect.bornAt < Math.max(effect.ghostMs, effect.blastMs));
}

function drawHitEffects() {
  const now = performance.now();
  const bodyH = Math.max(40, scale * PLAYER_SPRITE_WORLD_HEIGHT);
  for (const effect of hitEffects) {
    const age = now - effect.bornAt;
    const ghostProgress = Math.min(1, age / effect.ghostMs);
    const blastProgress = Math.min(1, age / effect.blastMs);
    const [x, y] = project(effect.x, effect.y);
    if (ghostProgress < 1) {
      const alpha = 1 - ghostProgress;
      const lift = ghostProgress * bodyH * 0.35;
      context.save();
      context.globalAlpha = Math.max(0, alpha);
      const image = ghostImage(effect.ghost);
      if (image) {
        const aspect = (image.naturalWidth || 1) / (image.naturalHeight || 1);
        const w = bodyH * aspect;
        context.drawImage(image, x - w / 2, y - bodyH + bodyH * 0.03 - lift, w, bodyH);
      } else {
        drawPeepToken(x, y - lift, bodyH, { color: effect.ghost.color, aim: [1, 0] });
      }
      context.restore();
    }
    if (blastProgress < 1) {
      const radius = bodyH * (0.35 + blastProgress * 1.1);
      context.save();
      context.globalAlpha = 0.85 * (1 - blastProgress);
      context.strokeStyle = effect.color;
      context.lineWidth = Math.max(2, bodyH * 0.08 * (1 - blastProgress));
      context.beginPath();
      context.arc(x, y - bodyH * 0.35, radius, 0, Math.PI * 2);
      context.stroke();
      context.globalAlpha = 0.5 * (1 - blastProgress);
      context.fillStyle = "#ffffff";
      context.beginPath();
      context.arc(x, y - bodyH * 0.35, Math.max(1.5, radius * 0.18), 0, Math.PI * 2);
      context.fill();
      for (const particle of effect.particles) {
        const travel = bodyH * particle.distance * (0.25 + blastProgress * 1.15);
        const px = x + Math.cos(particle.angle + particle.drift * blastProgress) * travel;
        const py = y - bodyH * 0.35 + Math.sin(particle.angle + particle.drift * blastProgress) * travel;
        context.globalAlpha = 0.9 * (1 - blastProgress);
        context.fillStyle = particle.drift > 0 ? effect.color : shade(effect.color, 1.25);
        context.beginPath();
        context.arc(px, py, Math.max(1, bodyH * particle.size * (1 - blastProgress * 0.6)), 0, Math.PI * 2);
        context.fill();
      }
      context.restore();
    }
  }
}

function currentState() {
  return arenaState;
}

function sendInputPacket(packet) {
  const target = controller();
  if (!target) return;
  const now = performance.now();
  const changed = packet !== lastInputPacket;
  if (!changed && now - lastInputSentAt < 250) return;
  lastInputPacket = packet;
  lastInputSentAt = now;
  void Tiny.command(`.activity_input ${packet} @prop:${target}`).catch(error => {
    const message = error instanceof Error ? error.message : String(error);
    if (message !== lastInputError || now - lastInputErrorAt > 5000) {
      lastInputError = message;
      lastInputErrorAt = now;
      Tiny.toast(message, true);
    }
  });
}

function currentMoveVector() {
  let x = 0;
  let y = 0;
  if (keys.has("a") || keys.has("arrowleft")) x -= 1;
  if (keys.has("d") || keys.has("arrowright")) x += 1;
  if (keys.has("w") || keys.has("arrowup")) y -= 1;
  if (keys.has("s") || keys.has("arrowdown")) y += 1;
  for (const stick of sticks.values()) {
    if (stick.role === "move" && stick.vector.active) {
      x += stick.vector.x;
      y += stick.vector.y;
    }
  }
  return normalizeVector(x, y);
}

function currentAimVector(player) {
  for (const stick of sticks.values()) {
    if (stick.role === "aim" && stick.vector.active) return normalizeVector(stick.vector.x, stick.vector.y);
  }
  if (mouseArena && player) {
    return normalizeVector(mouseArena.x - player.x, mouseArena.y - player.y);
  }
  if (player?.aim) return normalizeVector(player.aim[0], player.aim[1]);
  return [1, 0];
}

function currentFire() {
  if (mouseFire) return true;
  if (keys.has(" ")) return true;
  for (const stick of sticks.values()) {
    if (stick.role === "aim" && stick.vector.active) return true;
  }
  return false;
}

function arenaPoint(clientX, clientY) {
  const rect = canvas.getBoundingClientRect();
  const x = (clientX - rect.left - offsetX) / scale;
  const y = (clientY - rect.top - offsetY) / scale;
  return { x, y };
}

function canvasPoint(clientX, clientY) {
  const rect = canvas.getBoundingClientRect();
  return { x: clientX - rect.left, y: clientY - rect.top };
}

function stickCenter(role) {
  const rect = canvas.getBoundingClientRect();
  const radius = Math.max(40, Math.min(rect.width, rect.height) * 0.11);
  if (role === "move") return { x: radius * 1.25, y: rect.height - radius * 1.35, radius };
  return { x: rect.width - radius * 1.25, y: rect.height - radius * 1.35, radius };
}

function pointerRole(point) {
  const move = stickCenter("move");
  const aim = stickCenter("aim");
  if (Math.hypot(point.x - move.x, point.y - move.y) <= move.radius * 1.7) return "move";
  if (Math.hypot(point.x - aim.x, point.y - aim.y) <= aim.radius * 1.7) return "aim";
  return "mouse";
}

canvas.addEventListener("pointerdown", event => {
  canvas.setPointerCapture?.(event.pointerId);
  const point = canvasPoint(event.clientX, event.clientY);
  const role = pointerRole(point);
  if (role === "mouse") {
    mouseArena = arenaPoint(event.clientX, event.clientY);
    mouseFire = true;
    return;
  }
  const center = stickCenter(role);
  sticks.set(event.pointerId, { role, center, vector: stickVector(center.x, center.y, point.x, point.y, center.radius) });
});

canvas.addEventListener("pointermove", event => {
  const stick = sticks.get(event.pointerId);
  if (stick) {
    const point = canvasPoint(event.clientX, event.clientY);
    stick.vector = stickVector(stick.center.x, stick.center.y, point.x, point.y, stick.center.radius);
    return;
  }
  if (event.pointerType === "mouse") mouseArena = arenaPoint(event.clientX, event.clientY);
});

function endPointer(event) {
  sticks.delete(event.pointerId);
  if ([...sticks.values()].every(stick => stick.role !== "aim")) {
    if (event.pointerType !== "mouse" || event.type === "pointerup") mouseFire = false;
  }
}

canvas.addEventListener("pointerup", endPointer);
canvas.addEventListener("pointercancel", endPointer);
canvas.addEventListener("pointerleave", event => {
  if (!sticks.has(event.pointerId)) {
    mouseFire = false;
    mouseArena = null;
  }
});

window.addEventListener("keydown", event => {
  const key = event.key.toLowerCase();
  if (["arrowup", "arrowdown", "arrowleft", "arrowright", " "].includes(key)) event.preventDefault();
  keys.add(key);
});

window.addEventListener("keyup", event => {
  keys.delete(event.key.toLowerCase());
});

window.addEventListener("blur", () => {
  keys.clear();
  sticks.clear();
  mouseFire = false;
});

function resize() {
  const rect = canvas.getBoundingClientRect();
  const store = backingStoreSize(rect.width, rect.height, window.devicePixelRatio);
  if (canvas.width !== store.width || canvas.height !== store.height) {
    canvas.width = store.width;
    canvas.height = store.height;
  }
  context.setTransform(store.ratio, 0, 0, store.ratio, 0, 0);
  width = store.cssWidth;
  height = store.cssHeight;
}

function project(x, y) {
  return [offsetX + x * scale, offsetY + y * scale];
}

function drawBackground(arena, state) {
  context.fillStyle = "#070113";
  context.fillRect(0, 0, width, height);
  const [left, top] = project(0, 0);
  const [right, bottom] = project(arena.width, arena.height);
  const image = fieldImage(state);
  if (image) {
    context.drawImage(image, left, top, right - left, bottom - top);
    context.fillStyle = "#07011333";
    context.fillRect(left, top, right - left, bottom - top);
  } else {
    const gradient = context.createLinearGradient(0, 0, 0, height);
    gradient.addColorStop(0, "#0c0324");
    gradient.addColorStop(1, "#070113");
    context.fillStyle = gradient;
    context.fillRect(0, 0, width, height);
    const step = 5 * scale;
    context.save();
    context.strokeStyle = "#3d1c74";
    context.lineWidth = Math.max(1, scale * 0.15);
    context.beginPath();
    for (let x = offsetX % step; x <= width; x += step) {
      context.moveTo(x, 0);
      context.lineTo(x, height);
    }
    for (let y = offsetY % step; y <= height; y += step) {
      context.moveTo(0, y);
      context.lineTo(width, y);
    }
    context.stroke();
    context.restore();
  }
  context.save();
  context.strokeStyle = "#19e3ff";
  context.lineWidth = Math.max(2, scale * 0.45);
  context.shadowColor = "#19e3ff";
  context.shadowBlur = scale * 2;
  context.strokeRect(left, top, right - left, bottom - top);
  context.restore();
}

function shade(hex, factor) {
  const match = /^#([0-9a-f]{6})$/i.exec(String(hex || ""));
  if (!match) return String(hex || "#ff4d6d");
  const value = parseInt(match[1], 16);
  const channel = shift => Math.min(255, Math.max(0, Math.round(((value >> shift) & 255) * factor)));
  return `#${channel(16).toString(16).padStart(2, "0")}${channel(8).toString(16).padStart(2, "0")}${channel(0).toString(16).padStart(2, "0")}`;
}

function seededRandom(seed, salt) {
  let hash = (Number(seed) ^ Math.imul(Number(salt) || 0, 2654435761)) >>> 0;
  hash = Math.imul(hash ^ (hash >>> 15), 2246822519);
  hash ^= hash >>> 13;
  return ((hash >>> 0) % 10000) / 10000;
}

function drawObstacle(obstacle) {
  const image = obstacleImage(obstacle);
  context.save();
  if (obstacle.kind === "circle") {
    const [x, y] = project(obstacle.x, obstacle.y);
    const radius = obstacle.r * scale;
    if (image) {
      context.fillStyle = "#00000088";
      context.beginPath();
      context.ellipse(x, y + radius * 0.92, radius * 0.9, radius * 0.24, 0, 0, Math.PI * 2);
      context.fill();
      context.beginPath();
      context.arc(x, y, radius, 0, Math.PI * 2);
      context.clip();
      context.drawImage(image, x - radius, y - radius, radius * 2, radius * 2);
      context.strokeStyle = "#0a061833";
      context.lineWidth = Math.max(1.5, scale * 0.28);
      context.beginPath();
      context.arc(x, y, radius * 0.985, 0, Math.PI * 2);
      context.stroke();
      context.restore();
      return;
    }
    const seed = hashId(obstacle.id);
    context.fillStyle = "#00000088";
    context.beginPath();
    context.ellipse(x, y + radius * 0.92, radius * 0.9, radius * 0.24, 0, 0, Math.PI * 2);
    context.fill();
    const gradient = context.createRadialGradient(x - radius * 0.35, y - radius * 0.4, radius * 0.1, x, y, radius);
    gradient.addColorStop(0, "#6b74b8");
    gradient.addColorStop(0.55, "#2c2f55");
    gradient.addColorStop(1, "#12101f");
    context.fillStyle = gradient;
    context.beginPath();
    context.arc(x, y, radius, 0, Math.PI * 2);
    context.fill();
    context.fillStyle = "#aab4ff33";
    for (let dot = 0; dot < 14; dot += 1) {
      const angle = seededRandom(seed, dot * 2 + 1) * Math.PI * 2;
      const distance = seededRandom(seed, dot * 2 + 2) * radius * 0.8;
      context.beginPath();
      context.arc(x + Math.cos(angle) * distance, y + Math.sin(angle) * distance, Math.max(1, radius * 0.045), 0, Math.PI * 2);
      context.fill();
    }
    const core = context.createRadialGradient(x, y, 0, x, y, radius * 0.42);
    core.addColorStop(0, "#19e3ff66");
    core.addColorStop(1, "transparent");
    context.fillStyle = core;
    context.beginPath();
    context.arc(x, y, radius * 0.42, 0, Math.PI * 2);
    context.fill();
    context.strokeStyle = "#19e3ff88";
    context.lineWidth = Math.max(1.5, scale * 0.3);
    context.beginPath();
    context.arc(x, y, radius * 0.97, Math.PI * 1.05, Math.PI * 1.75);
    context.stroke();
  } else {
    const [px, py] = project(obstacle.x, obstacle.y);
    const w = obstacle.w * scale;
    const h = obstacle.h * scale;
    const left = px;
    const top = py;
    const cx = left + w / 2;
    const radius = Math.min(10 * scale, w / 5, h / 5);
    context.fillStyle = "#00000088";
    context.beginPath();
    context.roundRect(left + 2, top + 4, w, h, radius);
    context.fill();
    const gradient = context.createLinearGradient(left, top, left, top + h);
    gradient.addColorStop(0, "#472a8f");
    gradient.addColorStop(0.5, "#2a1658");
    gradient.addColorStop(1, "#150a30");
    context.fillStyle = gradient;
    context.strokeStyle = "#ff2d9577";
    context.lineWidth = Math.max(1.5, scale * 0.28);
    context.beginPath();
    context.roundRect(left, top, w, h, radius);
    context.fill();
    context.stroke();
    context.fillStyle = "#ffffff14";
    context.beginPath();
    context.roundRect(left + 2, top + 2, w - 4, Math.max(2, h * 0.12), [radius, radius, 0, 0]);
    context.fill();
    const inset = Math.min(w, h) * 0.14;
    context.strokeStyle = "#19e3ff44";
    context.lineWidth = Math.max(1, scale * 0.2);
    context.beginPath();
    context.roundRect(left + inset, top + inset, w - inset * 2, h - inset * 2, Math.max(2, radius - inset / 2));
    context.stroke();
    const boltR = Math.max(2, scale * 0.4);
    const boltInset = inset * 0.55;
    for (const [bx, by] of [
      [left + boltInset, top + boltInset],
      [left + w - boltInset, top + boltInset],
      [left + boltInset, top + h - boltInset],
      [left + w - boltInset, top + h - boltInset],
    ]) {
      context.fillStyle = "#8f7fd6";
      context.beginPath();
      context.arc(bx, by, boltR, 0, Math.PI * 2);
      context.fill();
      context.fillStyle = "#e6dcff";
      context.beginPath();
      context.arc(bx - boltR * 0.25, by - boltR * 0.25, boltR * 0.35, 0, Math.PI * 2);
      context.fill();
    }
    context.save();
    context.beginPath();
    context.roundRect(left + inset, top + inset, w - inset * 2, h - inset * 2, Math.max(2, radius - inset / 2));
    context.clip();
    context.strokeStyle = "#ff2d9540";
    context.lineWidth = Math.max(2, scale * 0.45);
    context.lineCap = "round";
    context.beginPath();
    for (let stripe = -h; stripe < w + h; stripe += 7 * scale) {
      context.moveTo(cx - w / 2 + stripe, top + h - 2 * scale);
      context.lineTo(cx - w / 2 + stripe + 4 * scale, top + h - 2 * scale - 4 * scale);
    }
    context.stroke();
    context.restore();
  }
  context.restore();
}

function drawSplat(splat) {
  const seed = hashId(splat.id);
  const color = String(splat.color || "#ff4d6d");
  const [x, y] = project(splat.x, splat.y);
  const radius = (splat.size || 1) * scale * 2.4;
  const blobs = [];
  for (let blob = 0; blob < 9; blob += 1) {
    const angle = seededRandom(seed, blob * 3 + 1) * Math.PI * 2;
    const distance = radius * (0.15 + seededRandom(seed, blob * 3 + 2) * 0.45);
    const size = radius * (0.24 + seededRandom(seed, blob * 3 + 3) * 0.3);
    blobs.push({ dx: Math.cos(angle) * distance, dy: Math.sin(angle) * distance, size });
  }
  context.save();
  context.lineCap = "round";
  context.fillStyle = shade(color, 0.42);
  context.globalAlpha = 0.95;
  for (const blob of blobs) {
    context.beginPath();
    context.arc(x + blob.dx, y + blob.dy, blob.size * 1.18, 0, Math.PI * 2);
    context.fill();
  }
  context.fillStyle = color;
  context.globalAlpha = 0.92;
  for (const blob of blobs) {
    context.beginPath();
    context.arc(x + blob.dx, y + blob.dy, blob.size, 0, Math.PI * 2);
    context.fill();
  }
  context.globalAlpha = 0.3;
  context.fillStyle = "#ffffff";
  context.beginPath();
  context.ellipse(x - radius * 0.25, y - radius * 0.3, radius * 0.32, radius * 0.2, -0.5, 0, Math.PI * 2);
  context.fill();
  context.globalAlpha = 0.85;
  context.strokeStyle = shade(color, 0.62);
  context.lineWidth = Math.max(1.5, radius * 0.2);
  for (let drip = 0; drip < 2; drip += 1) {
    const angle = seededRandom(seed, 100 + drip) * Math.PI * 2;
    const length = radius * (1.1 + seededRandom(seed, 200 + drip) * 0.7);
    context.beginPath();
    context.moveTo(x + Math.cos(angle) * radius * 0.3, y + Math.sin(angle) * radius * 0.3);
    context.lineTo(x + Math.cos(angle) * length, y + Math.sin(angle) * length);
    context.stroke();
  }
  context.restore();
}

function drawProjectile(projectile) {
  const [x, y] = project(projectile.x, projectile.y);
  const vx = Number(projectile.vx) || 0;
  const vy = Number(projectile.vy) || 0;
  const speed = Math.hypot(vx, vy);
  const angle = Math.atan2(vy, vx);
  const radius = Math.max(2.5, scale * 0.85);
  const stretch = clamp(1 + speed * 0.02, 1, 3.4);
  const color = String(projectile.color || "#ff4d6d");
  context.save();
  context.translate(x, y);
  context.rotate(angle);
  context.lineCap = "round";
  context.strokeStyle = color;
  context.globalAlpha = 0.5;
  context.lineWidth = radius * 0.85;
  context.beginPath();
  context.moveTo(-radius * 2.6 * stretch, 0);
  context.lineTo(-radius * 0.5, 0);
  context.stroke();
  const body = context.createLinearGradient(-radius * 1.6 * stretch, 0, radius * 1.2, 0);
  body.addColorStop(0, shade(color, 0.55));
  body.addColorStop(0.6, color);
  body.addColorStop(1, "#ffffff");
  context.globalAlpha = 1;
  context.fillStyle = body;
  context.beginPath();
  context.ellipse(0, 0, radius * 1.5 * Math.min(stretch, 2.4), radius * 0.78, 0, 0, Math.PI * 2);
  context.fill();
  const glow = context.createRadialGradient(0, 0, 0, 0, 0, radius * 1.7);
  glow.addColorStop(0, "#ffffffcc");
  glow.addColorStop(0.4, `${color}aa`);
  glow.addColorStop(1, "transparent");
  context.fillStyle = glow;
  context.beginPath();
  context.arc(0, 0, radius * 1.7, 0, Math.PI * 2);
  context.fill();
  context.restore();
}

function drawPeepToken(x, y, bodyH, participant) {
  const w = bodyH * 0.54;
  const top = y - bodyH;
  const gradient = context.createLinearGradient(x, top, x, y);
  gradient.addColorStop(0, "#ffffff");
  gradient.addColorStop(0.25, String(participant.color || "#ff4d6d"));
  gradient.addColorStop(1, shade(participant.color, 0.35));
  context.fillStyle = gradient;
  context.strokeStyle = "#0a0618";
  context.lineWidth = Math.max(1.5, bodyH * 0.03);
  context.beginPath();
  context.roundRect(x - w / 2, top, w, bodyH * 0.94, w / 2);
  context.fill();
  context.stroke();
  context.fillStyle = "#f4f0ff";
  context.beginPath();
  context.roundRect(x - w * 0.31, top + bodyH * 0.16, w * 0.62, bodyH * 0.13, bodyH * 0.06);
  context.fill();
  const aim = participant.aim;
  const aimAngle = Array.isArray(aim) && Math.hypot(aim[0] || 0, aim[1] || 0) > 1e-6
    ? Math.atan2(aim[1], aim[0])
    : 0;
  context.strokeStyle = "#0a0618";
  context.lineWidth = Math.max(2, bodyH * 0.05);
  context.lineCap = "round";
  context.beginPath();
  context.moveTo(x, y - bodyH * 0.45);
  context.lineTo(x + Math.cos(aimAngle) * w * 0.62, y - bodyH * 0.45 + Math.sin(aimAngle) * w * 0.62);
  context.stroke();
}

function drawParticipant(participant, local) {
  const [x, y] = project(participant.x, participant.y);
  const bodyH = Math.max(40, scale * PLAYER_SPRITE_WORLD_HEIGHT);
  const flashing = Boolean(participant.flash_until && Date.parse(participant.flash_until) > Date.now());
  const shielded = isImmune(participant);
  context.save();
  context.fillStyle = "#00000099";
  context.beginPath();
  context.ellipse(x, y + bodyH * 0.05, bodyH * 0.3, bodyH * 0.1, 0, 0, Math.PI * 2);
  context.fill();
  if (shielded) {
    context.shadowColor = "rgba(25,227,255,0.9)";
    context.shadowBlur = reducedMotion() ? 12 : 14 + 8 * (0.5 + 0.5 * Math.sin(performance.now() / 1000 * 5.2));
  }
  if (flashing) {
    try {
      context.filter = "brightness(1.8) saturate(0.5)";
    } catch {
      // Canvas filter is a progressive enhancement; the glow below still reads.
    }
  }
  const image = participantSprite(participant);
  if (image) {
    const aspect = (image.naturalWidth || 1) / (image.naturalHeight || 1);
    const w = bodyH * aspect;
    context.drawImage(image, x - w / 2, y - bodyH + bodyH * 0.03, w, bodyH);
  } else {
    drawPeepToken(x, y, bodyH, participant);
  }
  try {
    context.filter = "none";
  } catch {
    // Ignore runtimes without canvas filter support.
  }
  context.shadowColor = "transparent";
  context.shadowBlur = 0;
  if (shielded) drawShieldShimmer(x, y, bodyH);
  if (local) {
    context.fillStyle = "#19e3ff";
    context.globalAlpha = 0.95;
    const tipY = y - bodyH - 8;
    context.beginPath();
    context.moveTo(x - 7, tipY - 8);
    context.lineTo(x + 7, tipY - 8);
    context.lineTo(x, tipY);
    context.closePath();
    context.fill();
    context.globalAlpha = 1;
  }
  context.fillStyle = "#fff";
  context.font = `${Math.max(11, bodyH * 0.26)}px Arial`;
  context.textAlign = "center";
  context.fillText(participant.name.slice(0, 12), x, y - bodyH - (local ? 20 : 8));
  context.restore();
}

function drawSticks() {
  if (!sticks.size) {
    for (const role of ["move", "aim"]) {
      const center = stickCenter(role);
      context.save();
      context.globalAlpha = 0.28;
      context.strokeStyle = role === "move" ? "#19e3ff" : "#ff2d95";
      context.lineWidth = 2;
      context.setLineDash([6, 6]);
      context.beginPath();
      context.arc(center.x, center.y, center.radius, 0, Math.PI * 2);
      context.stroke();
      context.setLineDash([]);
      context.fillStyle = role === "move" ? "#19e3ff" : "#ff2d95";
      context.font = `${Math.max(10, center.radius * 0.3)}px Arial`;
      context.textAlign = "center";
      context.fillText(role === "move" ? "MOVE" : "AIM / FIRE", center.x, center.y + 4);
      context.restore();
    }
    return;
  }
  for (const stick of sticks.values()) {
    context.save();
    context.globalAlpha = 0.75;
    context.strokeStyle = stick.role === "move" ? "#19e3ff" : "#ff2d95";
    context.lineWidth = 3;
    context.beginPath();
    context.arc(stick.center.x, stick.center.y, stick.center.radius, 0, Math.PI * 2);
    context.stroke();
    context.fillStyle = stick.role === "move" ? "#19e3ff" : "#ff2d95";
    context.beginPath();
    context.arc(
      stick.center.x + stick.vector.x * stick.center.radius,
      stick.center.y + stick.vector.y * stick.center.radius,
      stick.center.radius * 0.38,
      0,
      Math.PI * 2,
    );
    context.fill();
    context.restore();
  }
}

function updateLocalPlayer(state, delta) {
  const me = state.participants.find(entry => String(entry.id) === String(host?.user?.id));
  if (!me) {
    localPlayer = null;
    respawnGlide = null;
    respawnFade = null;
    return null;
  }
  const { radius, playerSpeed, moveAccel, moveFriction } = tuning(state);
  const arena = arenaSize(state);
  if (!localPlayer || localPlayer.round !== state.round) {
    localPlayer = { x: me.x, y: me.y, vx: 0, vy: 0, round: state.round, respawn: Number(me.respawn || 0) };
    respawnGlide = null;
    respawnFade = null;
  }
  const serverRespawn = Number(me.respawn || 0);
  if (serverRespawn !== Number(localPlayer.respawn || 0)) {
    respawnGlide = { fromX: localPlayer.x, fromY: localPlayer.y, start: performance.now(), duration: 650 };
    respawnFade = null;
    localPlayer.vx = 0;
    localPlayer.vy = 0;
    localPlayer.round = state.round;
    localPlayer.respawn = serverRespawn;
  }
  if (respawnGlide) {
    const progress = Math.min(1, (performance.now() - respawnGlide.start) / respawnGlide.duration);
    const ease = easeInOutQuad(progress);
    localPlayer.x = respawnGlide.fromX + (me.x - respawnGlide.fromX) * ease;
    localPlayer.y = respawnGlide.fromY + (me.y - respawnGlide.fromY) * ease;
    if (progress >= 1) {
      respawnGlide = null;
      respawnFade = { start: performance.now(), duration: reducedMotion() ? 200 : 420 };
    }
    return { ...me, x: localPlayer.x, y: localPlayer.y };
  }
  const [moveX, moveY] = currentMoveVector();
  const [vx, vy] = stepVelocity(
    localPlayer.vx || 0, localPlayer.vy || 0,
    moveX * playerSpeed, moveY * playerSpeed,
    moveAccel, moveFriction, delta,
  );
  localPlayer.vx = vx;
  localPlayer.vy = vy;
  const next = moveCircle(localPlayer.x, localPlayer.y, vx * delta, vy * delta, radius, arena, obstacles(state));
  localPlayer.x = next[0];
  localPlayer.y = next[1];
  const error = Math.hypot(me.x - localPlayer.x, me.y - localPlayer.y);
  if (error > 12 || state.round !== localPlayer.round) {
    localPlayer.x = me.x;
    localPlayer.y = me.y;
    localPlayer.vx = 0;
    localPlayer.vy = 0;
    localPlayer.round = state.round;
    localPlayer.respawn = Number(me.respawn || 0);
  } else if (error > 0.75) {
    const blend = Math.min(1, delta * 6);
    localPlayer.x += (me.x - localPlayer.x) * blend;
    localPlayer.y += (me.y - localPlayer.y) * blend;
  }
  return { ...me, x: localPlayer.x, y: localPlayer.y };
}

function stampProjectiles(projectiles, previous, serverTimeMs) {
  const known = new Map((previous || []).map(entry => [String(entry?.id), entry]));
  return (projectiles || []).map(entry => {
    const spawnT = Number(known.get(String(entry?.id))?.spawnT);
    return { ...entry, spawnT: Number.isFinite(spawnT) ? spawnT : Number(serverTimeMs) };
  });
}

function renderStateSnapshot(state) {
  if (!state) return;
  const seq = Number(state.seq || 0);
  if (arenaState && seq <= arenaSeq) return;
  const t = Number(state.t || Date.now());
  arenaState = { ...state, projectiles: stampProjectiles(state.projectiles, arenaState?.projectiles, t) };
  arenaSeq = seq;
  serverClock.observe(t);
  interpolator.reset(arenaState.participants, t);
}

function applySnapshotDelta(delta) {
  if (!delta || typeof delta !== "object") return;
  if (!arenaState) return;
  const previous = new Map((arenaState.participants || []).map(entry => [String(entry?.id), entry]));
  const next = applyActivityDelta(arenaState, delta);
  if (!next) return;
  const spawnT = Number(delta.t ?? Date.now());
  next.projectiles = stampProjectiles(next.projectiles, arenaState.projectiles, spawnT);
  arenaState = next;
  arenaSeq = Number(next.seq || arenaSeq);
  serverClock.observe(spawnT);
  interpolator.push(delta.participants, spawnT);
  if (delta.participants_remove) interpolator.forget(delta.participants_remove);
  const teleports = (delta.participants || [])
    .filter(entry => entry && entry.respawn !== undefined && Number(entry.respawn) !== Number(previous.get(String(entry.id))?.respawn || 0))
    .map(entry => String(entry.id));
  if (teleports.length) interpolator.forget(teleports);
}

function draw(timestamp) {
  window.requestAnimationFrame(draw);
  resize();
  if (!host) return;
  const state = currentState();
  if (!state) return;
  const arena = arenaSize(state);
  const delta = Math.min(0.1, lastFrame ? (timestamp - lastFrame) / 1000 : 0.016);
  lastFrame = timestamp;
  const me = updateLocalPlayer(state, delta);
  scale = viewScale(width, height);
  const focusX = me ? localPlayer.x : arena.width / 2;
  const focusY = me ? localPlayer.y : arena.height / 2;
  [offsetX, offsetY] = cameraOffset(width, height, scale, focusX, focusY);
  const aim = me ? currentAimVector(me) : [1, 0];
  const move = currentMoveVector();
  observeShots(state);
  if (me) {
    if (state.phase === "active" && !roundEntryPaid(state)) {
      sendInputPacket("input:0:0:1000:0:0");
    } else {
      sendInputPacket(`input:${Math.round(move[0] * 1000)}:${Math.round(move[1] * 1000)}:${Math.round(aim[0] * 1000)}:${Math.round(aim[1] * 1000)}:${currentFire() ? 1 : 0}`);
    }
  }
  const renderTime = serverClock.now() - INTERP_DELAY_MS;
  const drag = tuning(state).projectileDrag;
  observeHits(state);
  context.clearRect(0, 0, width, height);
  drawBackground(arena, state);
  for (const obstacle of obstacles(state)) drawObstacle(obstacle);
  for (const splat of state.splats || []) drawSplat(splat);
  for (const projectile of state.projectiles || []) {
    const position = projectilePosition(projectile, renderTime, drag);
    if (!position) continue;
    drawProjectile({ ...projectile, x: position[0], y: position[1] });
  }
  for (const participant of state.participants || []) {
    const local = me && String(participant.id) === String(me.id);
    if (local) {
      if (respawnGlide) continue;
      if (respawnFade) {
        const alpha = fadeAlpha(performance.now() - respawnFade.start, respawnFade.duration);
        if (alpha < 1) {
          context.save();
          context.globalAlpha = alpha;
          drawParticipant({ ...participant, x: localPlayer.x, y: localPlayer.y, aim }, local);
          context.restore();
          continue;
        }
        respawnFade = null;
      }
      drawParticipant({ ...participant, x: localPlayer.x, y: localPlayer.y, aim }, local);
      continue;
    }
    const sample = interpolator.sample(participant.id, renderTime);
    drawParticipant(sample ? { ...participant, x: sample[0], y: sample[1] } : participant, local);
  }
  drawHitEffects();
  drawSticks();
}

function renderHud(state) {
  const seconds = Number(state.seconds_left || 0);
  const minutes = Math.floor(seconds / 60);
  const remainder = String(seconds % 60).padStart(2, "0");
  statusView.textContent = state.phase === "active"
    ? `Round ${state.round} — ${minutes}:${remainder}`
    : `Next round ${minutes}:${remainder}`;
  scoreboardView.textContent = (state.scoreboard || []).slice(0, 5).map(entry => `${entry.name} ${entry.hits}`).join(" · ");
  const me = (state.participants || []).find(entry => String(entry?.id) === String(host?.user?.id));
  if (me) {
    chargeRoundEntry(state);
    updateHitStreak(state, me);
  }
  announceRoundSound(state);
  const lastRound = state.last_round;
  if (state.phase === "active") {
    podium.hidden = true;
    lastPodiumKey = "";
  } else {
    podium.hidden = false;
    const top = Array.isArray(lastRound?.top) ? lastRound.top.slice(0, 3) : [];
    const key = `${state.phase}:${state.round}:${seconds}:${JSON.stringify(top)}`;
    if (key !== lastPodiumKey) {
      lastPodiumKey = key;
      renderPodium(podium, {
        top,
        round: Number(state.round || 0),
        seconds,
        imageFor: podiumImageUrl,
        reducedMotion: Boolean(host?.config?.reducedMotion),
      });
    }
  }
}

Tiny.subscribe(next => {
  host = next;
  connection.textContent = "";
  const state = activityState();
  if (!state) {
    statusView.textContent = "Paintball Arena";
    return;
  }
  renderStateSnapshot(state);
  const now = performance.now();
  if (now - lastHudAt > 100) {
    lastHudAt = now;
    renderHud(state);
  }
});

if (typeof Tiny.subscribeDelta === "function") {
  Tiny.subscribeDelta((kind, delta) => {
    if (String(kind || "") !== "paintball") return;
    applySnapshotDelta(delta);
    const state = currentState();
    if (!state) return;
    const now = performance.now();
    if (now - lastHudAt > 100 || delta.seconds_left !== undefined || delta.phase !== undefined || delta.scoreboard !== undefined) {
      lastHudAt = now;
      renderHud(state);
    }
  });
}

new ResizeObserver(resize).observe(canvas);
resize();
window.requestAnimationFrame(draw);
