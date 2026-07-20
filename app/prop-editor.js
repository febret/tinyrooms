"use strict";

// ---------------------------------------------------------------------------
// State
// ---------------------------------------------------------------------------

const state = {
  sets: [],
  selectedSet: null,      // PropSetRecord
  definition: null,       // full definition dict from API
  selectedPropId: null,
  selectedFrameIdx: null,
  canvasClickAddsFrame: false,
  canvasClickPicksBg: false,
  image: null,            // HTMLImageElement
  zoom: 1,
};

// ---------------------------------------------------------------------------
// DOM refs
// ---------------------------------------------------------------------------

const setList = document.getElementById("setList");
const setTitle = document.getElementById("setTitle");
const imageHint = document.getElementById("imageHint");
const zoomSlider = document.getElementById("zoomSlider");
const zoomLabel = document.getElementById("zoomLabel");
const propCanvas = document.getElementById("propCanvas");
const overlayCanvas = document.getElementById("overlayCanvas");
const propList = document.getElementById("propList");
const newPropId = document.getElementById("newPropId");
const propWidth = document.getElementById("propWidth");
const propHeight = document.getElementById("propHeight");
const frameX = document.getElementById("frameX");
const frameY = document.getElementById("frameY");
const propAnimSpeed = document.getElementById("propAnimSpeed");
const bgColorText = document.getElementById("bgColorText");
const bgColorSwatch = document.getElementById("bgColorSwatch");
const framesStrip = document.getElementById("framesStrip");
const statusBox = document.getElementById("statusBox");

const ctx = propCanvas.getContext("2d");
const octx = overlayCanvas.getContext("2d");

// ---------------------------------------------------------------------------
// API helpers
// ---------------------------------------------------------------------------

async function apiGet(url) {
  const res = await fetch(url);
  if (!res.ok) throw new Error(`HTTP ${res.status}: ${await res.text()}`);
  return res.json();
}

async function apiPost(url, body) {
  const res = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(`HTTP ${res.status}: ${await res.text()}`);
  return res.json();
}

async function apiPut(url, body) {
  const res = await fetch(url, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(`HTTP ${res.status}: ${await res.text()}`);
  return res.json();
}

async function apiDelete(url) {
  const res = await fetch(url, { method: "DELETE" });
  if (!res.ok) throw new Error(`HTTP ${res.status}: ${await res.text()}`);
  return res.json();
}

// ---------------------------------------------------------------------------
// Status / feedback
// ---------------------------------------------------------------------------

function setStatus(msg, isError) {
  statusBox.textContent = msg;
  statusBox.style.color = isError ? "#f44" : "#4f4";
}

// ---------------------------------------------------------------------------
// Rendering helpers
// ---------------------------------------------------------------------------

function loadImage(url) {
  return new Promise((resolve, reject) => {
    const img = new Image();
    img.onload = () => resolve(img);
    img.onerror = () => reject(new Error(`Failed to load image: ${url}`));
    img.src = url;
  });
}

function drawCanvas() {
  if (!state.image) return;
  propCanvas.width = state.image.naturalWidth;
  propCanvas.height = state.image.naturalHeight;
  overlayCanvas.width = propCanvas.width;
  overlayCanvas.height = propCanvas.height;
  applyZoom();
  ctx.clearRect(0, 0, propCanvas.width, propCanvas.height);
  ctx.drawImage(state.image, 0, 0);
  drawOverlay();
}

function applyZoom() {
  const z = state.zoom;
  const w = propCanvas.width * z;
  const h = propCanvas.height * z;
  propCanvas.style.width = w + "px";
  propCanvas.style.height = h + "px";
  overlayCanvas.style.width = w + "px";
  overlayCanvas.style.height = h + "px";
}

function drawOverlay() {
  if (!overlayCanvas) return;
  octx.clearRect(0, 0, overlayCanvas.width, overlayCanvas.height);
  const prop = selectedProp();
  if (!prop || state.selectedFrameIdx === null) return;
  const frames = prop.frames || [];
  if (state.selectedFrameIdx >= frames.length) return;
  const [fx, fy] = frames[state.selectedFrameIdx];
  const w = prop.width || 32;
  const h = prop.height || 32;
  // Scale line width inversely so it appears ~2px on screen regardless of zoom
  octx.strokeStyle = "#ff69b4";
  octx.lineWidth = Math.max(0.5, 2 / state.zoom);
  octx.strokeRect(fx + 0.5, fy + 0.5, w - 1, h - 1);
  octx.fillStyle = "rgba(255,105,180,0.15)";
  octx.fillRect(fx, fy, w, h);
}

function selectedProp() {
  if (!state.definition || !state.selectedPropId) return null;
  return (state.definition.props || {})[state.selectedPropId] || null;
}

// ---------------------------------------------------------------------------
// Background color helpers
// ---------------------------------------------------------------------------

function parseBgColor(hexStr) {
  if (!hexStr) return null;
  const s = hexStr.trim();
  const m = s.match(/^#?([0-9a-f]{2})([0-9a-f]{2})([0-9a-f]{2})$/i);
  if (!m) return null;
  return [parseInt(m[1], 16), parseInt(m[2], 16), parseInt(m[3], 16)];
}

function currentBgRgb() {
  return parseBgColor(state.definition?.background_color || "");
}

function updateBgSwatch() {
  const v = bgColorText.value.trim();
  const rgb = parseBgColor(v);
  bgColorSwatch.style.background = rgb ? `rgb(${rgb[0]},${rgb[1]},${rgb[2]})` : "transparent";
  bgColorSwatch.style.border = rgb ? "1px solid #555" : "1px dashed #555";
}

// Draw prop image onto a canvas, removing background color pixels.
// srcImg: HTMLImageElement, sx/sy: source top-left in image, sw/sh: source size,
// canvas: target canvas (already sized), tolerance: 0-255 per channel
function drawPropThumb(canvas, srcImg, sx, sy, sw, sh, tolerance = 10) {
  const tc = canvas.getContext("2d");
  const dw = canvas.width;
  const dh = canvas.height;
  tc.clearRect(0, 0, dw, dh);
  if (!srcImg) return;

  // Draw source frame into a temp canvas at native size
  const tmp = document.createElement("canvas");
  tmp.width = sw;
  tmp.height = sh;
  const tmpc = tmp.getContext("2d");
  tmpc.drawImage(srcImg, sx, sy, sw, sh, 0, 0, sw, sh);

  const rgb = currentBgRgb();
  if (rgb) {
    const id = tmpc.getImageData(0, 0, sw, sh);
    const d = id.data;
    const [tr, tg, tb] = rgb;
    for (let i = 0; i < d.length; i += 4) {
      if (
        Math.abs(d[i] - tr) <= tolerance &&
        Math.abs(d[i + 1] - tg) <= tolerance &&
        Math.abs(d[i + 2] - tb) <= tolerance
      ) {
        d[i + 3] = 0;
      }
    }
    tmpc.putImageData(id, 0, 0);
  }

  // Scale into target canvas preserving aspect ratio, centered
  const scale = Math.min(dw / sw, dh / sh, 1);
  const scaledW = Math.round(sw * scale);
  const scaledH = Math.round(sh * scale);
  const dx = Math.floor((dw - scaledW) / 2);
  const dy = Math.floor((dh - scaledH) / 2);
  tc.drawImage(tmp, 0, 0, sw, sh, dx, dy, scaledW, scaledH);
}

// ---------------------------------------------------------------------------
// Render prop set list
// ---------------------------------------------------------------------------

function renderSetList() {
  setList.innerHTML = "";
  for (const rec of state.sets) {
    const btn = document.createElement("button");
    const badge = rec.has_yaml ? "" : " ⚠ no yaml";
    const errBadge = rec.yaml_error ? " ❌" : "";
    btn.textContent = `${rec.scope === "server" ? "[S]" : "[W]"} ${rec.filename}${badge}${errBadge}`;
    btn.title = rec.yaml_error || rec.filename;
    if (state.selectedSet && state.selectedSet.scope === rec.scope && state.selectedSet.filename === rec.filename) {
      btn.style.borderColor = "#ff69b4";
    }
    btn.addEventListener("click", () => selectSet(rec));

    if (!rec.has_yaml) {
      const createBtn = document.createElement("button");
      createBtn.textContent = "Create def";
      createBtn.style.marginLeft = "4px";
      createBtn.addEventListener("click", (e) => { e.stopPropagation(); createDefinition(rec); });
      const row = document.createElement("div");
      row.style.display = "flex";
      row.style.gap = "4px";
      row.appendChild(btn);
      row.appendChild(createBtn);
      setList.appendChild(row);
    } else {
      setList.appendChild(btn);
    }
  }
}

// ---------------------------------------------------------------------------
// Render props panel
// ---------------------------------------------------------------------------

function renderPropList() {
  propList.innerHTML = "";
  if (!state.definition) return;
  const props = state.definition.props || {};
  for (const pid of Object.keys(props)) {
    const prop = props[pid];
    const btn = document.createElement("button");
    btn.className = "prop-btn" + (pid === state.selectedPropId ? " selected" : "");

    // Thumbnail canvas
    const THUMB = 32;
    const thumb = document.createElement("canvas");
    thumb.width = THUMB;
    thumb.height = THUMB;
    thumb.className = "prop-btn-thumb";
    if (state.image && prop.frames && prop.frames.length > 0) {
      const [fx, fy] = prop.frames[0];
      const pw = prop.width || 32;
      const ph = prop.height || 32;
      drawPropThumb(thumb, state.image, fx, fy, pw, ph);
    }

    const label = document.createElement("span");
    label.textContent = pid;

    btn.appendChild(thumb);
    btn.appendChild(label);
    btn.addEventListener("click", () => selectPropEntry(pid));
    propList.appendChild(btn);
  }
}

// ---------------------------------------------------------------------------
// Render prop details
// ---------------------------------------------------------------------------

function renderPropDetails() {
  const prop = selectedProp();
  if (!prop) {
    propWidth.value = "";
    propHeight.value = "";
    frameX.value = "";
    frameY.value = "";
    propAnimSpeed.value = "";
    return;
  }
  propWidth.value = prop.width ?? "";
  propHeight.value = prop.height ?? "";
  propAnimSpeed.value = (prop.anim_speed != null && prop.anim_speed !== undefined) ? prop.anim_speed : "";
  const frames = prop.frames || [];
  if (state.selectedFrameIdx !== null && state.selectedFrameIdx < frames.length) {
    const [fx, fy] = frames[state.selectedFrameIdx];
    frameX.value = fx;
    frameY.value = fy;
  } else {
    frameX.value = "";
    frameY.value = "";
  }
}

// ---------------------------------------------------------------------------
// Render frame sequence
// ---------------------------------------------------------------------------

function renderFrames() {
  framesStrip.innerHTML = "";
  const prop = selectedProp();
  if (!prop) return;
  const frames = prop.frames || [];
  const pw = prop.width || 32;
  const ph = prop.height || 32;
  const maxDim = 64;
  const scale = Math.min(maxDim / pw, maxDim / ph, 1);
  const thumbW = Math.round(pw * scale);
  const thumbH = Math.round(ph * scale);

  frames.forEach(([fx, fy], idx) => {
    const cell = document.createElement("div");
    cell.className = "frame-thumb" + (idx === state.selectedFrameIdx ? " selected" : "");
    cell.dataset.idx = idx;

    const thumb = document.createElement("canvas");
    thumb.width = thumbW;
    thumb.height = thumbH;
    if (state.image) {
      drawPropThumb(thumb, state.image, fx, fy, pw, ph);
    }

    const coord = document.createElement("div");
    coord.className = "frame-coord";
    coord.textContent = `${fx},${fy}`;

    cell.appendChild(thumb);
    cell.appendChild(coord);
    cell.addEventListener("click", () => {
      state.selectedFrameIdx = idx;
      renderFrames();
      renderPropDetails();
      drawOverlay();
    });
    framesStrip.appendChild(cell);
  });
}

// ---------------------------------------------------------------------------
// Actions
// ---------------------------------------------------------------------------

async function loadSets() {
  try {
    const data = await apiGet("/api/prop-editor/sets");
    state.sets = data.sets || [];
    renderSetList();
    setStatus(`Loaded ${state.sets.length} prop set(s).`);
  } catch (err) {
    setStatus(`Error loading sets: ${err.message}`, true);
  }
}

async function selectSet(rec) {
  try {
    const data = await apiGet(`/api/prop-editor/sets/${rec.scope}/${rec.filename}`);
    state.selectedSet = data.set;
    state.definition = data.definition || null;
    state.selectedPropId = null;
    state.selectedFrameIdx = null;
    setTitle.textContent = `${rec.scope}/${rec.filename}`;
    bgColorText.value = state.definition?.background_color || "";
    updateBgSwatch();
    renderSetList();
    renderPropList();
    renderPropDetails();
    renderFrames();
    imageHint.textContent = "";
    if (data.set.image_url) {
      try {
        state.image = await loadImage(data.set.image_url);
        drawCanvas();
      } catch (imgErr) {
        state.image = null;
        ctx.clearRect(0, 0, propCanvas.width, propCanvas.height);
        imageHint.textContent = `Image not available: ${imgErr.message}`;
      }
    } else {
      state.image = null;
      imageHint.textContent = "No image associated with this set.";
    }
    setStatus("Set loaded.");
  } catch (err) {
    setStatus(`Error loading set: ${err.message}`, true);
  }
}

async function createDefinition(rec) {
  const propId = prompt("Prop ID for new definition:", "prop_1");
  if (!propId) return;
  try {
    await apiPost(`/api/prop-editor/sets/${rec.scope}/${rec.filename}/create-definition`, { prop_id: propId });
    setStatus("Definition created.");
    await loadSets();
    const updated = state.sets.find(s => s.scope === rec.scope && s.filename === rec.filename);
    if (updated) await selectSet(updated);
  } catch (err) {
    setStatus(`Error: ${err.message}`, true);
  }
}

function selectPropEntry(pid) {
  state.selectedPropId = pid;
  state.selectedFrameIdx = 0;
  renderPropList();
  renderPropDetails();
  renderFrames();
  drawOverlay();
}

async function addProp() {
  const pid = newPropId.value.trim();
  if (!pid || !state.selectedSet) return;
  try {
    await apiPost(`/api/prop-editor/sets/${state.selectedSet.scope}/${state.selectedSet.filename}/props`, {
      prop_id: pid, width: 32, height: 32, frames: [[0, 0]],
    });
    setStatus(`Prop '${pid}' added.`);
    newPropId.value = "";
    await reloadCurrentSet();
    selectPropEntry(pid);
  } catch (err) {
    setStatus(`Error: ${err.message}`, true);
  }
}

async function deleteProp() {
  if (!state.selectedPropId || !state.selectedSet) return;
  if (!confirm(`Delete prop '${state.selectedPropId}'?`)) return;
  try {
    await apiDelete(`/api/prop-editor/sets/${state.selectedSet.scope}/${state.selectedSet.filename}/props/${state.selectedPropId}`);
    state.selectedPropId = null;
    state.selectedFrameIdx = null;
    setStatus("Prop deleted.");
    await reloadCurrentSet();
  } catch (err) {
    setStatus(`Error: ${err.message}`, true);
  }
}

function renameProp() {
  if (!state.selectedPropId || !state.definition) {
    setStatus("Select a prop to rename.", true);
    return;
  }
  const oldId = state.selectedPropId;
  const newId = prompt(`Rename prop '${oldId}' to:`, oldId);
  if (!newId || newId === oldId) return;
  const newIdTrimmed = newId.trim();
  if (!newIdTrimmed) return;
  const props = state.definition.props;
  if (newIdTrimmed in props) {
    setStatus(`A prop named '${newIdTrimmed}' already exists.`, true);
    return;
  }
  // Insert under new key preserving order
  const reordered = {};
  for (const [k, v] of Object.entries(props)) {
    reordered[k === oldId ? newIdTrimmed : k] = v;
  }
  state.definition.props = reordered;
  state.selectedPropId = newIdTrimmed;
  renderPropList();
  setStatus(`Prop renamed to '${newIdTrimmed}'. Don't forget to save.`);
}

async function saveSet() {
  if (!state.selectedSet || !state.definition) return;
  // Commit background color
  const bg = bgColorText.value.trim();
  state.definition.background_color = bg.length ? bg : null;
  // Commit edited prop details back into definition
  const prop = selectedProp();
  if (prop) {
    const w = parseInt(propWidth.value, 10);
    const h = parseInt(propHeight.value, 10);
    if (!isNaN(w) && w > 0) prop.width = w;
    if (!isNaN(h) && h > 0) prop.height = h;
    const animSpeedVal = propAnimSpeed.value.trim();
    if (animSpeedVal === "" || animSpeedVal === null) {
      delete prop.anim_speed;
    } else {
      const s = parseFloat(animSpeedVal);
      if (!isNaN(s) && s > 0) prop.anim_speed = s;
    }
  }
  try {
    await apiPut(`/api/prop-editor/sets/${state.selectedSet.scope}/${state.selectedSet.filename}`, {
      definition: state.definition,
    });
    setStatus("Saved successfully.");
    await reloadCurrentSet();
  } catch (err) {
    setStatus(`Save error: ${err.message}`, true);
  }
}

async function reloadCurrentSet() {
  if (!state.selectedSet) return;
  const data = await apiGet(`/api/prop-editor/sets/${state.selectedSet.scope}/${state.selectedSet.filename}`);
  state.selectedSet = data.set;
  state.definition = data.definition || null;
  renderSetList();
  renderPropList();
  renderPropDetails();
  renderFrames();
  drawOverlay();
}

// ---------------------------------------------------------------------------
// Canvas click — move selected frame or add new frame
// ---------------------------------------------------------------------------

propCanvas.addEventListener("click", (ev) => {
  const rect = propCanvas.getBoundingClientRect();
  const scaleX = propCanvas.width / rect.width;
  const scaleY = propCanvas.height / rect.height;
  const cx = Math.floor((ev.clientX - rect.left) * scaleX);
  const cy = Math.floor((ev.clientY - rect.top) * scaleY);

  if (state.canvasClickPicksBg) {
    const pixel = ctx.getImageData(cx, cy, 1, 1).data;
    const hex = "#" + [pixel[0], pixel[1], pixel[2]]
      .map(v => v.toString(16).padStart(2, "0")).join("");
    bgColorText.value = hex;
    updateBgSwatch();
    // Exit pick mode
    state.canvasClickPicksBg = false;
    document.getElementById("btnPickBgColor").style.borderColor = "";
    imageHint.textContent = "";
    renderPropList();
    renderFrames();
    setStatus(`Background color set to ${hex}. Don't forget to save.`);
    return;
  }

  const prop = selectedProp();
  if (!prop) return;

  if (state.canvasClickAddsFrame) {
    if (!prop.frames) prop.frames = [];
    prop.frames.push([cx, cy]);
    state.selectedFrameIdx = prop.frames.length - 1;
    renderFrames();
    renderPropDetails();
    drawOverlay();
    setStatus(`Added frame at [${cx}, ${cy}]. Don't forget to save.`);
  } else if (state.selectedFrameIdx !== null) {
    const frames = prop.frames || [];
    if (state.selectedFrameIdx < frames.length) {
      frames[state.selectedFrameIdx] = [cx, cy];
      renderFrames();
      renderPropDetails();
      drawOverlay();
      setStatus(`Moved frame to [${cx}, ${cy}]. Don't forget to save.`);
    }
  }
});

// ---------------------------------------------------------------------------
// Frame actions
// ---------------------------------------------------------------------------

function removeSelectedFrame() {
  const prop = selectedProp();
  if (!prop || state.selectedFrameIdx === null) return;
  const frames = prop.frames || [];
  if (frames.length <= 1) {
    setStatus("A prop must have at least one frame.", true);
    return;
  }
  frames.splice(state.selectedFrameIdx, 1);
  state.selectedFrameIdx = Math.min(state.selectedFrameIdx, frames.length - 1);
  renderFrames();
  drawOverlay();
}

function moveFrameLeft() {
  const prop = selectedProp();
  if (!prop || state.selectedFrameIdx === null || state.selectedFrameIdx === 0) return;
  const frames = prop.frames;
  const i = state.selectedFrameIdx;
  [frames[i - 1], frames[i]] = [frames[i], frames[i - 1]];
  state.selectedFrameIdx = i - 1;
  renderFrames();
  drawOverlay();
}

function moveFrameRight() {
  const prop = selectedProp();
  if (!prop || state.selectedFrameIdx === null) return;
  const frames = prop.frames;
  const i = state.selectedFrameIdx;
  if (i >= frames.length - 1) return;
  [frames[i], frames[i + 1]] = [frames[i + 1], frames[i]];
  state.selectedFrameIdx = i + 1;
  renderFrames();
  drawOverlay();
}

// ---------------------------------------------------------------------------
// Toggle add-frame mode
// ---------------------------------------------------------------------------

const btnAddFrameFromCanvas = document.getElementById("btnAddFrameFromCanvas");

btnAddFrameFromCanvas.addEventListener("click", () => {
  // Cancel bg pick mode if active
  if (state.canvasClickPicksBg) {
    state.canvasClickPicksBg = false;
    document.getElementById("btnPickBgColor").style.borderColor = "";
  }
  state.canvasClickAddsFrame = !state.canvasClickAddsFrame;
  btnAddFrameFromCanvas.style.borderColor = state.canvasClickAddsFrame ? "#ff69b4" : "";
  imageHint.textContent = state.canvasClickAddsFrame
    ? "Click on the image to add a frame at that position."
    : "";
});

// ---------------------------------------------------------------------------
// Live overlay updates from detail inputs
// ---------------------------------------------------------------------------

propWidth.addEventListener("input", () => {
  const prop = selectedProp();
  if (!prop) return;
  const w = parseInt(propWidth.value, 10);
  if (!isNaN(w) && w > 0) {
    prop.width = w;
    renderFrames();
    drawOverlay();
  }
});

propHeight.addEventListener("input", () => {
  const prop = selectedProp();
  if (!prop) return;
  const h = parseInt(propHeight.value, 10);
  if (!isNaN(h) && h > 0) {
    prop.height = h;
    renderFrames();
    drawOverlay();
  }
});

frameX.addEventListener("input", () => {
  const prop = selectedProp();
  if (!prop || state.selectedFrameIdx === null) return;
  const frames = prop.frames || [];
  if (state.selectedFrameIdx >= frames.length) return;
  const x = parseInt(frameX.value, 10);
  if (!isNaN(x) && x >= 0) {
    frames[state.selectedFrameIdx] = [x, frames[state.selectedFrameIdx][1]];
    renderFrames();
    drawOverlay();
  }
});

frameY.addEventListener("input", () => {
  const prop = selectedProp();
  if (!prop || state.selectedFrameIdx === null) return;
  const frames = prop.frames || [];
  if (state.selectedFrameIdx >= frames.length) return;
  const y = parseInt(frameY.value, 10);
  if (!isNaN(y) && y >= 0) {
    frames[state.selectedFrameIdx] = [frames[state.selectedFrameIdx][0], y];
    renderFrames();
    drawOverlay();
  }
});

// ---------------------------------------------------------------------------
// Background color controls
// ---------------------------------------------------------------------------

bgColorText.addEventListener("input", () => {
  updateBgSwatch();
  if (state.definition) {
    const bg = bgColorText.value.trim();
    state.definition.background_color = bg.length ? bg : null;
    renderPropList();
    renderFrames();
  }
});

document.getElementById("btnPickBgColor").addEventListener("click", () => {
  // Toggle off add-frame mode to avoid conflicts
  if (state.canvasClickAddsFrame) {
    state.canvasClickAddsFrame = false;
    document.getElementById("btnAddFrameFromCanvas").style.borderColor = "";
  }
  state.canvasClickPicksBg = !state.canvasClickPicksBg;
  document.getElementById("btnPickBgColor").style.borderColor = state.canvasClickPicksBg ? "#ff69b4" : "";
  imageHint.textContent = state.canvasClickPicksBg
    ? "Click a pixel on the image to set the background color."
    : "";
});

document.getElementById("btnClearBgColor").addEventListener("click", () => {
  bgColorText.value = "";
  updateBgSwatch();
  if (state.definition) state.definition.background_color = null;
  renderPropList();
  renderFrames();
  setStatus("Background color cleared. Don't forget to save.");
});

// ---------------------------------------------------------------------------
// Zoom controls
// ---------------------------------------------------------------------------

function setZoom(z) {
  state.zoom = Math.max(1, Math.min(8, z));
  zoomSlider.value = state.zoom;
  zoomLabel.textContent = state.zoom + "×";
  applyZoom();
  drawOverlay();
}

zoomSlider.addEventListener("input", () => setZoom(parseInt(zoomSlider.value, 10)));
document.getElementById("btnZoomIn").addEventListener("click", () => setZoom(state.zoom + 1));
document.getElementById("btnZoomOut").addEventListener("click", () => setZoom(state.zoom - 1));

// ---------------------------------------------------------------------------
// Wire up buttons
// ---------------------------------------------------------------------------

document.getElementById("btnLoadSets").addEventListener("click", loadSets);
document.getElementById("btnAddProp").addEventListener("click", addProp);
document.getElementById("btnDeleteProp").addEventListener("click", deleteProp);
document.getElementById("btnRenameProp").addEventListener("click", renameProp);
document.getElementById("btnSaveSet").addEventListener("click", saveSet);
document.getElementById("btnRemoveFrame").addEventListener("click", removeSelectedFrame);
document.getElementById("btnMoveFrameLeft").addEventListener("click", moveFrameLeft);
document.getElementById("btnMoveFrameRight").addEventListener("click", moveFrameRight);

// Auto-load on page open
loadSets();
