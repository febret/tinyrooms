import { WHITEBOARD_HEIGHT, WHITEBOARD_WIDTH, loadWhiteboardArtwork } from "../../app/js/surface-canvas.js";
import {
  drawWhiteboardFrame,
  frameLayout,
  normalizeColor,
  normalizeFrame,
} from "../../app/js/whiteboard-frame.js";
import { BRUSHES, BRUSH_BY_ID, dabSpacing, interpolatePoints, mulberry32, pressureForEvent } from "./brushes.js";
import { createPalette } from "./palette.js";
import { createFramePanel } from "./frame-panel.js";

const WIDTH = WHITEBOARD_WIDTH;
const HEIGHT = WHITEBOARD_HEIGHT;
const AUTO_SAVE_MS = 5000;
const UNDO_LIMIT = 16;
const BOARD_BACKGROUND = "#fbfbf7";
const DEFAULT_COLOR = "#1f2933";

const board = document.querySelector("#board");
const display = board.getContext("2d");
const stage = document.querySelector("#board-stage");
const shell = document.querySelector("#board-shell");
const paintShell = document.querySelector(".paint-shell");
const frameCanvas = document.querySelector("#frame-canvas");
const frameContext = frameCanvas.getContext("2d");
const status = document.querySelector("#status");
const lockNote = document.querySelector("#lock-note");
const brushRail = document.querySelector("#brush-rail");
const eraserButton = document.querySelector("#eraser");
const undoButton = document.querySelector("#undo");
const redoButton = document.querySelector("#redo");
const clearButton = document.querySelector("#clear");
const sizeInput = document.querySelector("#brush-size");
const opacityInput = document.querySelector("#brush-opacity");
const paletteToggle = document.querySelector("#palette-toggle");
const frameToggle = document.querySelector("#frame-toggle");
const swatchPreview = document.querySelector("#current-swatch");
const sidePanel = document.querySelector("#side-panel");
const paletteRoot = document.querySelector("#palette-root");
const frameRoot = document.querySelector("#frame-root");

const layer = document.createElement("canvas");
layer.width = WIDTH;
layer.height = HEIGHT;
const paint = layer.getContext("2d");

let instanceId = "";
let locked = false;
let loadingImage = false;
let revision = 0;
let frame = normalizeFrame({});
let palette = null;
let framePanel = null;

let brushId = "marker";
let brushSize = BRUSHES[0].size;
let brushOpacity = BRUSHES[0].opacity;
let color = DEFAULT_COLOR;
let erasing = false;

let activeStroke = null;
let paintQueued = false;
let dirty = false;
let editGeneration = 0;
let savePromise = null;

const undoStack = [];
const redoStack = [];

function activeBrush() {
  return BRUSH_BY_ID[brushId] || BRUSHES[0];
}

function hexToRgba(hex, alpha) {
  const red = parseInt(hex.slice(1, 3), 16);
  const green = parseInt(hex.slice(3, 5), 16);
  const blue = parseInt(hex.slice(5, 7), 16);
  return `rgba(${red}, ${green}, ${blue}, ${Math.max(0, Math.min(1, alpha))})`;
}

function setStatus(message) {
  if (status.textContent !== message) status.textContent = message;
}

function paintDisplay() {
  paintQueued = false;
  if (!display) return;
  display.save();
  display.globalCompositeOperation = "source-over";
  display.globalAlpha = 1;
  display.fillStyle = BOARD_BACKGROUND;
  display.fillRect(0, 0, WIDTH, HEIGHT);
  display.drawImage(layer, 0, 0);
  display.restore();
}

function requestPaint() {
  if (paintQueued) return;
  paintQueued = true;
  requestAnimationFrame(paintDisplay);
}

function layoutFrame() {
  const rect = stage.getBoundingClientRect();
  if (!rect.width || !rect.height || !frameContext) return;
  const layout = frameLayout(frame);
  const padding = 14;
  const availableWidth = Math.max(180, rect.width - padding * 2);
  const availableHeight = Math.max(180, rect.height - padding * 2);
  const scale = Math.min(availableWidth / layout.width, availableHeight / layout.height);
  const shellWidth = Math.max(1, Math.floor(layout.width * scale));
  const shellHeight = Math.max(1, Math.floor(layout.height * scale));
  shell.style.width = `${shellWidth}px`;
  shell.style.height = `${shellHeight}px`;
  const ratio = Math.min(2, window.devicePixelRatio || 1);
  frameCanvas.width = Math.max(1, Math.round(shellWidth * ratio));
  frameCanvas.height = Math.max(1, Math.round(shellHeight * ratio));
  drawWhiteboardFrame(frameContext, frame, frameCanvas.width, frameCanvas.height);
  const artWidth = (layout.artWidth / layout.width) * shellWidth;
  const artHeight = (layout.artHeight / layout.height) * shellHeight;
  board.style.width = `${artWidth}px`;
  board.style.height = `${artHeight}px`;
  board.style.left = `${(layout.artX / layout.width) * shellWidth}px`;
  board.style.top = `${(layout.artY / layout.height) * shellHeight}px`;
}

function markDirty() {
  if (locked) return;
  editGeneration += 1;
  dirty = true;
  setStatus("Unsaved changes");
  renderControls();
}

function snapshot() {
  return paint.getImageData(0, 0, WIDTH, HEIGHT);
}

function pushUndo() {
  undoStack.push(snapshot());
  if (undoStack.length > UNDO_LIMIT) undoStack.shift();
  redoStack.length = 0;
}

function restore(image) {
  paint.save();
  paint.globalCompositeOperation = "source-over";
  paint.globalAlpha = 1;
  paint.clearRect(0, 0, WIDTH, HEIGHT);
  paint.putImageData(image, 0, 0);
  paint.restore();
  requestPaint();
}

function pointFor(event) {
  const rect = board.getBoundingClientRect();
  return [
    Math.min(WIDTH, Math.max(0, ((event.clientX - rect.left) / rect.width) * WIDTH)),
    Math.min(HEIGHT, Math.max(0, ((event.clientY - rect.top) / rect.height) * HEIGHT)),
  ];
}

function stampRound(x, y, radius, alpha) {
  paint.beginPath();
  paint.arc(x, y, Math.max(0.4, radius), 0, Math.PI * 2);
  paint.fillStyle = hexToRgba(color, alpha);
  paint.fill();
}

function stampSoft(x, y, radius, alpha) {
  const gradient = paint.createRadialGradient(x, y, 0, x, y, Math.max(1, radius));
  gradient.addColorStop(0, hexToRgba(color, alpha));
  gradient.addColorStop(0.62, hexToRgba(color, alpha * 0.48));
  gradient.addColorStop(1, hexToRgba(color, 0));
  paint.fillStyle = gradient;
  paint.beginPath();
  paint.arc(x, y, Math.max(1, radius), 0, Math.PI * 2);
  paint.fill();
}

function stampFlat(x, y, radius, alpha, angle) {
  paint.save();
  paint.translate(x, y);
  paint.rotate(angle - 0.62);
  paint.fillStyle = hexToRgba(color, alpha);
  paint.beginPath();
  paint.ellipse(0, 0, Math.max(0.6, radius), Math.max(0.4, radius * 0.42), 0, 0, Math.PI * 2);
  paint.fill();
  paint.restore();
}

function stampGrain(x, y, radius, alpha, random) {
  paint.fillStyle = hexToRgba(color, alpha * 0.42);
  paint.beginPath();
  paint.arc(x, y, Math.max(0.5, radius * 0.72), 0, Math.PI * 2);
  paint.fill();
  const specks = Math.max(4, Math.min(30, Math.round(radius * 1.5)));
  for (let index = 0; index < specks; index += 1) {
    const angle = random() * Math.PI * 2;
    const distance = Math.sqrt(random()) * radius;
    paint.fillStyle = hexToRgba(color, alpha * (0.35 + random() * 0.55));
    paint.beginPath();
    paint.arc(x + Math.cos(angle) * distance, y + Math.sin(angle) * distance, Math.max(0.4, radius * 0.13), 0, Math.PI * 2);
    paint.fill();
  }
}

function stampBristle(x, y, radius, alpha, angle, random) {
  const normal = angle + Math.PI / 2;
  paint.lineCap = "round";
  for (let strand = -2; strand <= 2; strand += 1) {
    const offset = strand * radius * 0.24 + (random() - 0.5) * radius * 0.12;
    const length = radius * (1.05 + random() * 0.5);
    paint.strokeStyle = hexToRgba(color, alpha * (0.42 + random() * 0.4));
    paint.lineWidth = Math.max(0.7, radius * 0.15);
    paint.beginPath();
    paint.moveTo(
      x + Math.cos(normal) * offset - Math.cos(angle) * length / 2,
      y + Math.sin(normal) * offset - Math.sin(angle) * length / 2,
    );
    paint.lineTo(
      x + Math.cos(normal) * offset + Math.cos(angle) * length / 2,
      y + Math.sin(normal) * offset + Math.sin(angle) * length / 2,
    );
    paint.stroke();
  }
}

function stampSpray(x, y, radius, alpha, random) {
  const dots = Math.max(6, Math.min(64, Math.round(radius * 1.25)));
  for (let index = 0; index < dots; index += 1) {
    const angle = random() * Math.PI * 2;
    const distance = Math.sqrt(random()) * radius;
    paint.fillStyle = hexToRgba(color, alpha * (0.25 + random() * 0.55));
    paint.beginPath();
    paint.arc(x + Math.cos(angle) * distance, y + Math.sin(angle) * distance, Math.max(0.4, radius * 0.075), 0, Math.PI * 2);
    paint.fill();
  }
}

function stampWash(x, y, radius, alpha, random) {
  const drift = (random() - 0.5) * radius * 0.22;
  const halo = paint.createRadialGradient(x + drift, y - drift, 0, x + drift, y - drift, radius * 1.3);
  halo.addColorStop(0, hexToRgba(color, alpha * 0.5));
  halo.addColorStop(0.68, hexToRgba(color, alpha * 0.24));
  halo.addColorStop(1, hexToRgba(color, 0));
  paint.fillStyle = halo;
  paint.beginPath();
  paint.arc(x + drift, y - drift, Math.max(1, radius * 1.3), 0, Math.PI * 2);
  paint.fill();
  paint.fillStyle = hexToRgba(color, alpha * 0.62);
  paint.beginPath();
  paint.arc(x, y, Math.max(0.5, radius * 0.52), 0, Math.PI * 2);
  paint.fill();
}

function stampHighlight(x, y, radius, alpha) {
  paint.fillStyle = hexToRgba(color, alpha * 0.52);
  paint.beginPath();
  paint.arc(x, y, Math.max(1, radius * 0.9), 0, Math.PI * 2);
  paint.fill();
}

function stampEraser(x, y, radius, alpha) {
  const gradient = paint.createRadialGradient(x, y, 0, x, y, Math.max(1, radius));
  gradient.addColorStop(0, `rgba(0, 0, 0, ${alpha})`);
  gradient.addColorStop(0.68, `rgba(0, 0, 0, ${alpha * 0.55})`);
  gradient.addColorStop(1, "rgba(0, 0, 0, 0)");
  paint.fillStyle = gradient;
  paint.beginPath();
  paint.arc(x, y, Math.max(1, radius), 0, Math.PI * 2);
  paint.fill();
}

function stampDab(stroke, x, y, radius, pressure, angle) {
  const brush = stroke.brush;
  const alpha = Math.max(0.02, Math.min(1, (stroke.opacity / 100) * brush.flow));
  if (stroke.erase) {
    stampEraser(x, y, radius, alpha);
    return;
  }
  if (brush.kind === "soft") stampSoft(x, y, radius, alpha);
  else if (brush.kind === "flat") stampFlat(x, y, radius, alpha, angle);
  else if (brush.kind === "grain") stampGrain(x, y, radius, alpha, stroke.random);
  else if (brush.kind === "bristle") stampBristle(x, y, radius, alpha, angle, stroke.random);
  else if (brush.kind === "spray") stampSpray(x, y, radius, alpha, stroke.random);
  else if (brush.kind === "wash") stampWash(x, y, radius, alpha, stroke.random);
  else if (brush.kind === "highlight") stampHighlight(x, y, radius, alpha);
  else stampRound(x, y, radius, alpha);
}

function dabRadius(stroke, pressure) {
  const brush = stroke.brush;
  const dynamic = 1 - brush.pressureSize * (1 - pressure);
  return Math.max(0.5, (stroke.size * dynamic) / 2);
}

function beginStroke(event) {
  if (!instanceId || locked || loadingImage) return;
  const [x, y] = pointFor(event);
  pushUndo();
  paint.save();
  paint.globalCompositeOperation = erasing ? "destination-out" : "source-over";
  const brush = activeBrush();
  activeStroke = {
    brush,
    color,
    size: brushSize,
    opacity: brushOpacity,
    erase: erasing,
    random: mulberry32((Date.now() ^ ((x * 31 + y * 17) | 0)) >>> 0),
    last: { x, y, time: event.timeStamp || performance.now() },
  };
  stampDab(activeStroke, x, y, dabRadius(activeStroke, 0.72), 0.72, 0);
  requestPaint();
  markDirty();
  board.setPointerCapture?.(event.pointerId);
}

function continueStroke(event) {
  if (!activeStroke) return;
  const now = event.timeStamp || performance.now();
  const [x, y] = pointFor(event);
  const last = activeStroke.last;
  const distance = Math.hypot(x - last.x, y - last.y);
  const speed = distance / Math.max(1, now - last.time) * 1000;
  const pressure = pressureForEvent(event, speed);
  const radius = dabRadius(activeStroke, pressure);
  const angle = Math.atan2(y - last.y, x - last.x);
  const dabs = interpolatePoints([last.x, last.y], [x, y], dabSpacing(radius, activeStroke.brush.spacing));
  for (const [dabX, dabY] of dabs) {
    stampDab(activeStroke, dabX, dabY, radius, pressure, angle);
  }
  activeStroke.last = { x, y, time: now };
  requestPaint();
}

function endStroke() {
  if (!activeStroke) return;
  activeStroke = null;
  paint.restore();
  requestPaint();
  markDirty();
}

function exportImage() {
  const output = document.createElement("canvas");
  output.width = WIDTH;
  output.height = HEIGHT;
  const context = output.getContext("2d");
  context.fillStyle = BOARD_BACKGROUND;
  context.fillRect(0, 0, WIDTH, HEIGHT);
  context.drawImage(layer, 0, 0);
  return output.toDataURL("image/png");
}

async function saveNow() {
  if (!instanceId || locked || loadingImage || !dirty || savePromise) {
    return savePromise;
  }
  const generation = editGeneration;
  const payload = { image: exportImage(), frame: { ...frame } };
  setStatus("Saving…");
  renderControls();
  savePromise = (async () => {
    try {
      const response = await TinyActivity.saveSurface(payload);
      const surface = response?.payload?.surface;
      if (surface) revision = Number(surface.revision ?? revision);
      if (generation === editGeneration) {
        dirty = false;
        setStatus(revision ? `Saved revision ${revision}` : "Saved");
      } else {
        dirty = true;
        setStatus(revision ? `Saved revision ${revision}; newer edits not yet saved` : "Unsaved changes");
      }
    } catch (error) {
      dirty = true;
      const message = error instanceof Error ? error.message : String(error);
      setStatus(`Could not save — retrying every 5 seconds. ${message}`);
    } finally {
      savePromise = null;
      renderControls();
    }
  })();
  return savePromise;
}

function renderControls() {
  const editable = Boolean(instanceId) && !locked && !loadingImage;
  brushRail.querySelectorAll("button").forEach(button => {
    button.disabled = !editable;
    button.setAttribute("aria-pressed", String(button.dataset.brush === brushId && !erasing));
  });
  eraserButton.disabled = !editable;
  eraserButton.setAttribute("aria-pressed", String(erasing));
  undoButton.disabled = !editable || !undoStack.length;
  redoButton.disabled = !editable || !redoStack.length;
  clearButton.disabled = !editable;
  sizeInput.disabled = !editable;
  opacityInput.disabled = !editable;
  paletteToggle.disabled = locked;
  frameToggle.disabled = locked;
  board.setAttribute("aria-readonly", String(locked));
}

function buildBrushRail() {
  brushRail.replaceChildren();
  for (const brush of BRUSHES) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "brush";
    button.dataset.brush = brush.id;
    button.title = brush.label;
    button.setAttribute("aria-label", `${brush.label} brush`);
    button.innerHTML = `${brush.icon}<span>${brush.label}</span>`;
    button.onclick = () => selectBrush(brush.id);
    brushRail.append(button);
  }
}

function selectBrush(id) {
  const brush = BRUSH_BY_ID[id];
  if (!brush) return;
  brushId = brush.id;
  erasing = false;
  brushSize = brush.size;
  brushOpacity = brush.opacity;
  sizeInput.value = String(brush.size);
  opacityInput.value = String(brush.opacity);
  renderControls();
}

function setLocked(value) {
  locked = Boolean(value);
  paintShell.classList.toggle("is-locked", locked);
  lockNote.hidden = !locked;
  if (locked) {
    activeStroke = null;
    dirty = false;
    if (!instanceId) setStatus("Open a whiteboard prop from a room to draw here.");
    else setStatus("Signed print — this artwork cannot be modified");
  }
  renderControls();
}

function setPanel(name) {
  const showPalette = name === "palette";
  const showFrame = name === "frame";
  paletteRoot.hidden = !showPalette;
  frameRoot.hidden = !showFrame;
  sidePanel.hidden = !showPalette && !showFrame;
  paletteToggle.setAttribute("aria-expanded", String(showPalette));
  frameToggle.setAttribute("aria-expanded", String(showFrame));
  if (!sidePanel.hidden) layoutFrame();
}

function ensurePanels(options = {}) {
  if (!palette) {
    const initial = Array.isArray(options.colors) && options.colors.length
      ? options.colors
      : [DEFAULT_COLOR, "#d64545", "#2f6fdb", "#2f8f5b", "#e08a1e"];
    palette = createPalette({
      root: paletteRoot,
      initialColors: initial,
      onChange: next => {
        color = normalizeColor(next, DEFAULT_COLOR);
        swatchPreview.style.background = color;
        erasing = false;
        renderControls();
      },
    });
    color = palette.getColor();
    swatchPreview.style.background = color;
  }
  if (!framePanel) {
    framePanel = createFramePanel({
      root: frameRoot,
      options,
      initialFrame: frame,
      onChange: next => {
        frame = normalizeFrame(next);
        layoutFrame();
        markDirty();
      },
    });
  }
}

async function loadSurface(surface, force = false) {
  const nextRevision = Number(surface?.revision || 0);
  if (!force && nextRevision <= revision) return;
  loadingImage = true;
  renderControls();
  try {
    revision = nextRevision;
    frame = normalizeFrame(surface?.content?.frame);
    framePanel?.setFrame(frame);
    paint.save();
    paint.globalCompositeOperation = "source-over";
    paint.globalAlpha = 1;
    paint.clearRect(0, 0, WIDTH, HEIGHT);
    const artwork = await loadWhiteboardArtwork(surface?.content || {});
    if (artwork) paint.drawImage(artwork, 0, 0, WIDTH, HEIGHT);
    paint.restore();
    undoStack.length = 0;
    redoStack.length = 0;
    dirty = false;
    editGeneration += 1;
    setStatus(revision ? `Saved revision ${revision}` : "Blank whiteboard");
  } finally {
    loadingImage = false;
    requestPaint();
    layoutFrame();
    renderControls();
  }
}

function surfaceFromState(state) {
  if (!instanceId) return null;
  return (state?.room?.props || []).find(prop => prop.id === instanceId)?.surface || null;
}

board.addEventListener("pointerdown", event => {
  if (event.pointerType === "mouse" && event.button !== 0) return;
  event.preventDefault();
  beginStroke(event);
});
board.addEventListener("pointermove", event => {
  if (!activeStroke) return;
  event.preventDefault();
  if (typeof event.getCoalescedEvents === "function") {
    for (const coalesced of event.getCoalescedEvents()) continueStroke(coalesced);
  } else {
    continueStroke(event);
  }
});
board.addEventListener("pointerup", endStroke);
board.addEventListener("pointercancel", () => {
  if (!activeStroke) return;
  activeStroke = null;
  paint.restore();
  requestPaint();
});
board.addEventListener("pointerleave", event => {
  if (activeStroke && event.buttons === 0) endStroke();
});

eraserButton.onclick = () => {
  erasing = !erasing;
  renderControls();
};

undoButton.onclick = () => {
  const previous = undoStack.pop();
  if (!previous) return;
  redoStack.push(snapshot());
  restore(previous);
  markDirty();
};

redoButton.onclick = () => {
  const next = redoStack.pop();
  if (!next) return;
  undoStack.push(snapshot());
  restore(next);
  markDirty();
};

clearButton.onclick = () => {
  pushUndo();
  paint.save();
  paint.globalCompositeOperation = "source-over";
  paint.globalAlpha = 1;
  paint.clearRect(0, 0, WIDTH, HEIGHT);
  paint.restore();
  requestPaint();
  markDirty();
};

sizeInput.oninput = () => {
  brushSize = Number(sizeInput.value);
};
opacityInput.oninput = () => {
  brushOpacity = Number(opacityInput.value);
};
paletteToggle.onclick = () => setPanel(paletteRoot.hidden ? "palette" : "");
frameToggle.onclick = () => setPanel(frameRoot.hidden ? "frame" : "");

new ResizeObserver(() => layoutFrame()).observe(stage);

window.setInterval(() => {
  if (dirty) void saveNow();
}, AUTO_SAVE_MS);

document.addEventListener("visibilitychange", () => {
  if (document.visibilityState === "hidden") void saveNow();
});
window.addEventListener("pagehide", () => {
  void saveNow();
});
TinyActivity.onBeforeClose?.(async () => {
  if (savePromise) await savePromise;
  if (dirty) await saveNow();
  if (dirty) throw new Error("The whiteboard could not be saved before closing.");
});

TinyActivity.subscribe(state => {
  const config = state?.activity?.config || {};
  ensurePanels(config.whiteboard_options || {});
  const nextInstance = String(config.prop_instance_id || "");
  if (nextInstance && nextInstance !== instanceId) {
    instanceId = nextInstance;
    const surface = config.surface || surfaceFromState(state);
    void loadSurface(surface, true).then(() => {
      setLocked(config.can_edit_surface === false || surface?.locked === true);
    });
    return;
  }
  if (!instanceId) {
    setStatus("Open a whiteboard prop from a room to draw here.");
    renderControls();
    return;
  }
  const surface = surfaceFromState(state) || config.surface;
  if (surface) setLocked(config.can_edit_surface === false || surface.locked === true);
  if (surface && Number(surface.revision || 0) > revision) {
    if (dirty) {
      setStatus("Another artist saved a newer revision. Your unsaved work will overwrite it on the next save.");
    } else {
      void loadSurface(surface);
    }
  }
  renderControls();
});

buildBrushRail();
ensurePanels({});
setPanel("palette");
requestPaint();
layoutFrame();
renderControls();
if (!TinyActivity.state) setStatus("Loading whiteboard…");
