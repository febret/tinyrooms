import { drawWhiteboard } from "../../app/js/surface-canvas.js";

const WIDTH = 1024;
const HEIGHT = 640;
const DEFAULT_COLORS = ["#1f2933", "#d64545", "#2f6fdb", "#2f8f5b", "#e08a1e"];
const ERASER_COLOR = "#fbfbf7";

const canvas = document.querySelector("#board");
const context = canvas.getContext("2d");
const connection = document.querySelector("#connection");
const status = document.querySelector("#status");
const colorsRoot = document.querySelector("#colors");
const brushSize = document.querySelector("#brush-size");
const eraserButton = document.querySelector("#eraser");
const textValue = document.querySelector("#text-value");
const textButton = document.querySelector("#text-mode");
const saveButton = document.querySelector("#save");
const lockNote = document.querySelector("#lock-note");
const shell = document.querySelector(".whiteboard-shell");

let content = { strokes: [], texts: [] };
let locked = false;
let revision = 0;
let instanceId = "";
let dirty = false;
let activeColor = DEFAULT_COLORS[0];
let erasing = false;
let textMode = false;
let drawing = null;
let pendingFrame = 0;
const undoStack = [];
const redoStack = [];

function clone(value) {
  return JSON.parse(JSON.stringify(value));
}

function render() {
  pendingFrame = 0;
  drawWhiteboard(context, content);
  saveButton.disabled = !instanceId || locked;
  saveButton.textContent = locked ? "Signed print" : (dirty ? "Save whiteboard" : "Saved");
  document.querySelector("#undo").disabled = locked || !undoStack.length;
  document.querySelector("#redo").disabled = locked || !redoStack.length;
  document.querySelector("#clear").disabled = locked;
  document.querySelector("#eraser").disabled = locked;
  document.querySelector("#text-mode").disabled = locked;
  brushSize.disabled = locked;
  textValue.disabled = locked;
}

function requestRender() {
  if (pendingFrame) return;
  pendingFrame = requestAnimationFrame(render);
}

function pushUndo() {
  undoStack.push(clone(content));
  if (undoStack.length > 40) undoStack.shift();
  redoStack.length = 0;
}

function markDirty() {
  if (locked) return;
  dirty = true;
  status.textContent = "Unsaved changes";
  requestRender();
}

function pointFor(event) {
  const rect = canvas.getBoundingClientRect();
  const scale = Math.min(rect.width / WIDTH, rect.height / HEIGHT) || 1;
  const left = rect.left + (rect.width - WIDTH * scale) / 2;
  const top = rect.top + (rect.height - HEIGHT * scale) / 2;
  return [
    Math.min(WIDTH, Math.max(0, ((event.clientX - left) / scale))),
    Math.min(HEIGHT, Math.max(0, ((event.clientY - top) / scale))),
  ];
}

function beginStroke(event) {
  if (!instanceId || locked) return;
  if (textMode) {
    const text = textValue.value.trim();
    if (!text) {
      TinyActivity.toast("Type a note first.", true);
      textValue.focus();
      return;
    }
    pushUndo();
    const [x, y] = pointFor(event);
    content.texts.push({
      text: text.slice(0, 160),
      x,
      y,
      size: Math.max(18, Number(brushSize.value) * 4),
      color: activeColor,
    });
    textValue.value = "";
    markDirty();
    return;
  }
  pushUndo();
  const [x, y] = pointFor(event);
  const width = erasing ? Math.max(18, Number(brushSize.value) * 2.5) : Number(brushSize.value);
  drawing = {
    color: erasing ? ERASER_COLOR : activeColor,
    width,
    points: [[x, y]],
  };
  content.strokes.push(drawing);
  canvas.setPointerCapture?.(event.pointerId);
  markDirty();
}

function continueStroke(event) {
  if (!drawing) return;
  const [x, y] = pointFor(event);
  const last = drawing.points[drawing.points.length - 1];
  if (Math.hypot(x - last[0], y - last[1]) < 1.5) return;
  drawing.points.push([x, y]);
  requestRender();
}

function endStroke() {
  drawing = null;
}

function setColors(colors) {
  colorsRoot.replaceChildren();
  const list = Array.isArray(colors) && colors.length ? colors : DEFAULT_COLORS;
  for (const color of list) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "marker";
    button.dataset.color = color;
    button.style.background = color;
    button.setAttribute("aria-label", `Marker ${color}`);
    button.setAttribute("aria-pressed", String(color === activeColor));
    button.onclick = () => {
      activeColor = color;
      erasing = false;
      eraserButton.setAttribute("aria-pressed", "false");
      colorsRoot.querySelectorAll(".marker").forEach(marker => {
        marker.setAttribute("aria-pressed", String(marker.dataset.color === activeColor));
      });
    };
    colorsRoot.append(button);
  }
}

function loadSurface(surface, force = false) {
  const nextRevision = Number(surface?.revision || 0);
  if (!force && nextRevision <= revision) return;
  revision = nextRevision;
  content = {
    strokes: Array.isArray(surface?.content?.strokes) ? clone(surface.content.strokes) : [],
    texts: Array.isArray(surface?.content?.texts) ? clone(surface.content.texts) : [],
  };
  dirty = false;
  undoStack.length = 0;
  redoStack.length = 0;
  status.textContent = revision ? `Saved revision ${revision}` : "Blank whiteboard";
  requestRender();
}

function surfaceFromState(state) {
  if (!instanceId) return null;
  return (state?.room?.props || []).find(prop => prop.id === instanceId)?.surface || null;
}

canvas.addEventListener("pointerdown", event => {
  if (event.button !== undefined && event.button !== 0) return;
  event.preventDefault();
  beginStroke(event);
});
canvas.addEventListener("pointermove", event => {
  if (!drawing) return;
  event.preventDefault();
  continueStroke(event);
});
canvas.addEventListener("pointerup", endStroke);
canvas.addEventListener("pointercancel", endStroke);
canvas.addEventListener("pointerleave", event => {
  if (drawing && event.buttons === 0) endStroke();
});

eraserButton.onclick = () => {
  erasing = !erasing;
  eraserButton.setAttribute("aria-pressed", String(erasing));
  if (erasing) textMode = false;
  updateTextMode();
};

textButton.onclick = () => {
  textMode = !textMode;
  if (textMode) erasing = false;
  eraserButton.setAttribute("aria-pressed", "false");
  updateTextMode();
};

function updateTextMode() {
  textButton.setAttribute("aria-pressed", String(textMode));
  canvas.classList.toggle("text-mode", textMode && !locked);
}

function setLocked(value) {
  locked = Boolean(value);
  shell.classList.toggle("is-locked", locked);
  lockNote.hidden = !locked;
  canvas.setAttribute("aria-readonly", String(locked));
  if (locked) {
    dirty = false;
    drawing = null;
    status.textContent = "Signed print � this artwork cannot be modified";
  }
  render();
}

document.querySelector("#undo").onclick = () => {
  const previous = undoStack.pop();
  if (!previous) return;
  redoStack.push(clone(content));
  content = previous;
  markDirty();
};

document.querySelector("#redo").onclick = () => {
  const next = redoStack.pop();
  if (!next) return;
  undoStack.push(clone(content));
  content = next;
  markDirty();
};

document.querySelector("#clear").onclick = () => {
  if (!content.strokes.length && !content.texts.length) return;
  pushUndo();
  content = { strokes: [], texts: [] };
  markDirty();
};

saveButton.onclick = async () => {
  if (!instanceId) return;
  const snapshot = clone(content);
  saveButton.disabled = true;
  status.textContent = "Saving whiteboard…";
  try {
    const response = await TinyActivity.saveSurface(content);
    const surface = response?.payload?.surface;
    if (surface) revision = Number(surface.revision ?? revision);
    if (JSON.stringify(content) === JSON.stringify(snapshot)) {
      if (surface) {
        content = {
          strokes: Array.isArray(surface.content?.strokes) ? clone(surface.content.strokes) : content.strokes,
          texts: Array.isArray(surface.content?.texts) ? clone(surface.content.texts) : content.texts,
        };
      }
      dirty = false;
      status.textContent = `Saved revision ${revision}`;
      TinyActivity.toast("Whiteboard saved.");
    } else {
      dirty = true;
      status.textContent = `Saved revision ${revision}; newer edits not yet saved`;
    }
    saveButton.disabled = false;
    requestRender();
  } catch (error) {
    saveButton.disabled = false;
    status.textContent = error instanceof Error ? error.message : String(error);
    TinyActivity.toast(status.textContent, true);
  }
};

TinyActivity.subscribe(state => {
  const config = state?.activity?.config || {};
  const nextInstance = String(config.prop_instance_id || "");
  if (nextInstance && nextInstance !== instanceId) {
    instanceId = nextInstance;
    setColors(config.whiteboard_options?.colors);
    const surface = config.surface || surfaceFromState(state);
    loadSurface(surface, true);
    setLocked(config.can_edit_surface === false || surface?.locked === true);
  }
  if (connection.textContent) connection.textContent = "";
  if (!instanceId) {
    status.textContent = "Open a whiteboard prop from a room to draw here.";
    return;
  }
  const surface = surfaceFromState(state) || config.surface;
  if (surface) setLocked(config.can_edit_surface === false || surface.locked === true);
  if (surface && Number(surface.revision || 0) > revision) {
    if (dirty) {
      status.textContent = "Someone saved a newer version. Save to overwrite it.";
    } else {
      loadSurface(surface);
    }
  }
});

setColors();
updateTextMode();
render();
if (!TinyActivity.state) status.textContent = "Loading whiteboard…";
