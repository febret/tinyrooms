const Tiny = window.TinyActivity;

const canvas = document.querySelector("#stage");
const context = canvas.getContext("2d");
const connection = document.querySelector("#connection");
const energyView = document.querySelector("#energy");
const timerView = document.querySelector("#timer");
const personalView = document.querySelector("#personal-best");
const worldView = document.querySelector("#world-best");
const overlay = document.querySelector("#overlay");
const overlayTitle = document.querySelector("#overlay-title");
const overlayMessage = document.querySelector("#overlay-message");
const startButton = document.querySelector("#start");

const MOLLY_ASPECT = 158 / 202;
const MOLLY_IMAGE = new Image();
MOLLY_IMAGE.decoding = "async";

let width = 0;
let height = 0;
let unit = 0;
let state = null;
let round = null;
let pointerDown = false;
let recordsLoaded = false;
let mollyReady = false;
let mollyRequested = false;

function clamp(value, minimum, maximum) {
  return Math.max(minimum, Math.min(maximum, value));
}

function mollyHome() {
  return { x: width * 0.16, y: height * 0.74 };
}

function laserHome() {
  return { x: width * 0.82, y: height * 0.26 };
}

function mollySize() {
  return unit * 0.24;
}

function mollyRadius() {
  return mollySize() * 0.3;
}

function laserRadius() {
  return Math.max(5, unit * 0.02);
}

function baseSpeed() {
  return unit * 0.24;
}

function acceleration() {
  return unit * 0.13;
}

function updateEnergy(value) {
  const energy = Number(value);
  energyView.textContent = Number.isFinite(energy) ? String(Math.round(energy)) : "—";
}

function updateRecords(records) {
  if (!records) return;
  personalView.textContent = records.personal_best == null ? "—" : `${Number(records.personal_best).toFixed(1)}s`;
  worldView.textContent = records.world_best == null ? "—" : `${Number(records.world_best).toFixed(1)}s`;
}

function showOverlay(title, message, label, busy) {
  overlay.hidden = false;
  overlayTitle.textContent = title;
  overlayMessage.textContent = message;
  startButton.textContent = label;
  startButton.disabled = Boolean(busy);
}

function hideOverlay() {
  overlay.hidden = true;
}

function drawBackground() {
  context.fillStyle = "#05060e";
  context.fillRect(0, 0, width, height);
  const step = Math.max(26, Math.round(unit / 14));
  context.lineWidth = 1;
  context.strokeStyle = "#0e3b3a";
  context.beginPath();
  for (let x = step; x < width; x += step) {
    context.moveTo(x + 0.5, 0);
    context.lineTo(x + 0.5, height);
  }
  for (let y = step; y < height; y += step) {
    context.moveTo(0, y + 0.5);
    context.lineTo(width, y + 0.5);
  }
  context.stroke();
}

function drawLaser(position) {
  const radius = laserRadius();
  const arm = radius * 2.4;
  context.save();
  context.shadowColor = "#ff2d95";
  context.shadowBlur = 16;
  context.fillStyle = "#ff2d95";
  context.beginPath();
  context.arc(position.x, position.y, radius, 0, Math.PI * 2);
  context.fill();
  context.shadowBlur = 0;
  context.fillStyle = "#ffffff";
  context.fillRect(position.x - 2, position.y - 2, 4, 4);
  context.strokeStyle = "#ffe600";
  context.lineWidth = 2;
  context.beginPath();
  context.moveTo(position.x - arm, position.y);
  context.lineTo(position.x - radius - 2, position.y);
  context.moveTo(position.x + radius + 2, position.y);
  context.lineTo(position.x + arm, position.y);
  context.moveTo(position.x, position.y - arm);
  context.lineTo(position.x, position.y - radius - 2);
  context.moveTo(position.x, position.y + radius + 2);
  context.lineTo(position.x, position.y + arm);
  context.stroke();
  context.restore();
}

function drawMolly(molly, target) {
  const spriteHeight = mollySize();
  const spriteWidth = spriteHeight * MOLLY_ASPECT;
  context.save();
  context.translate(molly.x, molly.y);
  if (target.x < molly.x) context.scale(-1, 1);
  if (mollyReady) {
    context.imageSmoothingEnabled = false;
    context.drawImage(MOLLY_IMAGE, -spriteWidth / 2, -spriteHeight / 2, spriteWidth, spriteHeight);
  } else {
    context.shadowColor = "#39ff14";
    context.shadowBlur = 12;
    context.fillStyle = "#39ff14";
    context.beginPath();
    context.arc(0, 0, mollyRadius(), 0, Math.PI * 2);
    context.fill();
  }
  context.restore();
}

function draw() {
  if (width <= 0 || height <= 0) return;
  drawBackground();
  const laser = round ? round.laser : laserHome();
  const molly = round ? round.molly : mollyHome();
  drawLaser(laser);
  drawMolly(molly, laser);
}

function resizeCanvas() {
  const rect = canvas.getBoundingClientRect();
  const nextWidth = Math.max(1, Math.round(rect.width));
  const nextHeight = Math.max(1, Math.round(rect.height));
  if (nextWidth === width && nextHeight === height) return;
  width = nextWidth;
  height = nextHeight;
  unit = Math.min(width, height);
  canvas.width = width;
  canvas.height = height;
  if (round) {
    round.molly.x = clamp(round.molly.x, 0, width);
    round.molly.y = clamp(round.molly.y, 0, height);
    round.laser.x = clamp(round.laser.x, 0, width);
    round.laser.y = clamp(round.laser.y, 0, height);
  }
  draw();
}

function pointerPosition(event) {
  const rect = canvas.getBoundingClientRect();
  const scaleX = width / (rect.width || width);
  const scaleY = height / (rect.height || height);
  return { x: (event.clientX - rect.left) * scaleX, y: (event.clientY - rect.top) * scaleY };
}

function moveLaser(event) {
  if (!round || round.finished) return;
  const position = pointerPosition(event);
  if (position.x < 0 || position.y < 0 || position.x > width || position.y > height) return;
  round.laser = position;
}

function advance(now) {
  const elapsed = Math.max(0, now - round.startedAt);
  const last = round.lastUpdate ?? round.startedAt;
  const delta = Math.max(0, now - last);
  round.lastUpdate = now;
  round.elapsed = elapsed;
  const dx = round.laser.x - round.molly.x;
  const dy = round.laser.y - round.molly.y;
  const distance = Math.hypot(dx, dy);
  const reach = distance - mollyRadius();
  if (distance <= mollyRadius()) {
    finishRound(elapsed);
    return;
  }
  const travel = (baseSpeed() + acceleration() * elapsed) * delta;
  if (travel >= reach) {
    round.molly.x += (dx / distance) * reach;
    round.molly.y += (dy / distance) * reach;
    finishRound(elapsed);
    return;
  }
  round.molly.x += (dx / distance) * travel;
  round.molly.y += (dy / distance) * travel;
  timerView.textContent = `${elapsed.toFixed(1)}s`;
}

function frame(timestamp) {
  window.requestAnimationFrame(frame);
  const now = timestamp / 1000;
  if (round && !round.finished) advance(now);
  draw();
}

async function finishRound(elapsed) {
  round.finished = true;
  timerView.textContent = `${elapsed.toFixed(1)}s`;
  showOverlay("Caught!", "Saving your round…", "Play Again", true);
  try {
    const reply = await Tiny.result({ result: { seconds: elapsed, captured: true } });
    const seconds = Number(reply?.payload?.seconds ?? elapsed);
    updateRecords(reply?.payload?.records || null);
    showOverlay("Caught!", `Molly caught the laser after ${seconds.toFixed(1)}s.`, "Play Again", false);
    Tiny.sound("success");
  } catch (error) {
    showOverlay("Round ended", error instanceof Error ? error.message : String(error), "Play Again", false);
    Tiny.toast(error instanceof Error ? error.message : String(error), true);
  }
}

function beginRound() {
  const now = performance.now() / 1000;
  round = {
    startedAt: now,
    lastUpdate: now,
    elapsed: 0,
    finished: false,
    molly: mollyHome(),
    laser: laserHome(),
  };
  timerView.textContent = "0.0s";
  hideOverlay();
}

async function startRound() {
  if (!state?.activity || state.activity.kind !== "lazor-rush") {
    Tiny.toast("Open Lazor Rush from Tinyrooms first.", true);
    return;
  }
  const cost = Number(state.activity.config?.start_cost ?? 1);
  startButton.disabled = true;
  try {
    const reply = await Tiny.command(".activity_start");
    updateEnergy(reply?.payload?.round?.energy ?? state?.user?.counters?.energy);
    updateRecords(reply?.payload?.records || null);
    beginRound();
  } catch (error) {
    showOverlay("Lazor Rush", `Starting a round costs ${cost} Energy. ${error instanceof Error ? error.message : ""}`.trim(), "Start", false);
    Tiny.toast(error instanceof Error ? error.message : String(error), true);
  } finally {
    startButton.disabled = false;
  }
}

async function refreshRecords() {
  if (!state?.activity || state.activity.kind !== "lazor-rush") return;
  try {
    const reply = await Tiny.command(".activity_records lazor-rush");
    updateRecords(reply?.payload?.records || null);
  } catch {
    // Records are optional; the round still plays without them.
  }
}

function loadMolly() {
  if (mollyRequested) return;
  const worldId = state?.user?.worldId;
  if (!worldId) return;
  mollyRequested = true;
  MOLLY_IMAGE.addEventListener("load", () => {
    mollyReady = true;
    canvas.setAttribute("data-molly-ready", "true");
    draw();
  });
  MOLLY_IMAGE.addEventListener("error", () => {
    // Keep the fallback sprite if the peep image cannot load.
  });
  MOLLY_IMAGE.src = `/assets/world/${encodeURIComponent(worldId)}/peeps/molly.png`;
}

canvas.addEventListener("pointerdown", event => {
  pointerDown = true;
  try {
    canvas.setPointerCapture(event.pointerId);
  } catch {
    // Pointer capture is optional; dragging still works without it.
  }
  moveLaser(event);
});
canvas.addEventListener("pointermove", event => {
  if (event.pointerType !== "mouse" && !pointerDown) return;
  moveLaser(event);
});
canvas.addEventListener("pointerup", () => {
  pointerDown = false;
});
canvas.addEventListener("pointercancel", () => {
  pointerDown = false;
});
canvas.addEventListener("pointerleave", () => {
  pointerDown = false;
});
startButton.addEventListener("click", () => {
  void startRound();
});

Tiny.subscribe(next => {
  state = next;
  connection.textContent = "";
  updateEnergy(next?.user?.counters?.energy);
  loadMolly();
  if (!recordsLoaded) {
    recordsLoaded = true;
    void refreshRecords();
  }
});

new ResizeObserver(resizeCanvas).observe(canvas);
resizeCanvas();
window.requestAnimationFrame(frame);
