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
  image: null,            // HTMLImageElement
};

// ---------------------------------------------------------------------------
// DOM refs
// ---------------------------------------------------------------------------

const setList = document.getElementById("setList");
const setTitle = document.getElementById("setTitle");
const imageHint = document.getElementById("imageHint");
const propCanvas = document.getElementById("propCanvas");
const overlayCanvas = document.getElementById("overlayCanvas");
const propList = document.getElementById("propList");
const newPropId = document.getElementById("newPropId");
const propWidth = document.getElementById("propWidth");
const propHeight = document.getElementById("propHeight");
const propAnimSpeed = document.getElementById("propAnimSpeed");
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
  ctx.clearRect(0, 0, propCanvas.width, propCanvas.height);
  ctx.drawImage(state.image, 0, 0);
  drawOverlay();
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
  octx.strokeStyle = "#ff69b4";
  octx.lineWidth = 2;
  octx.strokeRect(fx + 0.5, fy + 0.5, w - 1, h - 1);
  octx.fillStyle = "rgba(255,105,180,0.15)";
  octx.fillRect(fx, fy, w, h);
}

function selectedProp() {
  if (!state.definition || !state.selectedPropId) return null;
  return (state.definition.props || {})[state.selectedPropId] || null;
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
    const btn = document.createElement("button");
    btn.textContent = pid;
    if (pid === state.selectedPropId) btn.style.borderColor = "#ff69b4";
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
    propAnimSpeed.value = "";
    return;
  }
  propWidth.value = prop.width ?? "";
  propHeight.value = prop.height ?? "";
  propAnimSpeed.value = (prop.anim_speed != null && prop.anim_speed !== undefined) ? prop.anim_speed : "";
}

// ---------------------------------------------------------------------------
// Render frame sequence
// ---------------------------------------------------------------------------

function renderFrames() {
  framesStrip.innerHTML = "";
  const prop = selectedProp();
  if (!prop) return;
  const frames = prop.frames || [];
  const w = Math.min(prop.width || 32, 64);
  const h = Math.min(prop.height || 32, 64);
  const scale = Math.min(w / (prop.width || 32), h / (prop.height || 32), 1);
  const thumbW = Math.round((prop.width || 32) * scale);
  const thumbH = Math.round((prop.height || 32) * scale);

  frames.forEach(([fx, fy], idx) => {
    const cell = document.createElement("div");
    cell.className = "frame-thumb" + (idx === state.selectedFrameIdx ? " selected" : "");
    cell.dataset.idx = idx;

    const thumb = document.createElement("canvas");
    thumb.width = thumbW;
    thumb.height = thumbH;
    if (state.image) {
      const tc = thumb.getContext("2d");
      tc.drawImage(state.image, fx, fy, prop.width || 32, prop.height || 32, 0, 0, thumbW, thumbH);
    }

    const coord = document.createElement("div");
    coord.className = "frame-coord";
    coord.textContent = `${fx},${fy}`;

    cell.appendChild(thumb);
    cell.appendChild(coord);
    cell.addEventListener("click", () => {
      state.selectedFrameIdx = idx;
      renderFrames();
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

async function saveSet() {
  if (!state.selectedSet || !state.definition) return;
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
// Canvas click — add frame
// ---------------------------------------------------------------------------

propCanvas.addEventListener("click", (ev) => {
  if (!state.canvasClickAddsFrame) return;
  const rect = propCanvas.getBoundingClientRect();
  const scaleX = propCanvas.width / rect.width;
  const scaleY = propCanvas.height / rect.height;
  const cx = Math.floor((ev.clientX - rect.left) * scaleX);
  const cy = Math.floor((ev.clientY - rect.top) * scaleY);
  const prop = selectedProp();
  if (!prop) return;
  if (!prop.frames) prop.frames = [];
  prop.frames.push([cx, cy]);
  state.selectedFrameIdx = prop.frames.length - 1;
  renderFrames();
  drawOverlay();
  setStatus(`Added frame at [${cx}, ${cy}]. Don't forget to save.`);
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
  state.canvasClickAddsFrame = !state.canvasClickAddsFrame;
  btnAddFrameFromCanvas.style.borderColor = state.canvasClickAddsFrame ? "#ff69b4" : "";
  imageHint.textContent = state.canvasClickAddsFrame
    ? "Click on the image to add a frame at that position."
    : "";
});

// ---------------------------------------------------------------------------
// Image upload
// ---------------------------------------------------------------------------

async function uploadImage() {
  const fileInput = document.getElementById("uploadFile");
  const scopeSelect = document.getElementById("uploadScope");
  const uploadStatus = document.getElementById("uploadStatus");
  const file = fileInput.files[0];
  if (!file) {
    uploadStatus.textContent = "Please select an image file first.";
    uploadStatus.style.color = "#f44";
    return;
  }
  const scope = scopeSelect.value;
  const formData = new FormData();
  formData.append("scope", scope);
  formData.append("image", file);
  uploadStatus.textContent = "Uploading…";
  uploadStatus.style.color = "#aaa";
  try {
    const res = await fetch("/api/prop-editor/upload-image", { method: "POST", body: formData });
    const data = await res.json();
    if (!res.ok || !data.ok) {
      uploadStatus.textContent = `Error: ${data.error || res.status}`;
      uploadStatus.style.color = "#f44";
      return;
    }
    uploadStatus.textContent = `Uploaded '${data.image_name}' to ${scope}.`;
    uploadStatus.style.color = "#4f4";
    fileInput.value = "";
    await loadSets();
    // Auto-select the newly uploaded set so user can immediately create a definition
    const newRec = state.sets.find(s => s.scope === data.scope && s.filename === data.filename);
    if (newRec) await selectSet(newRec);
  } catch (err) {
    uploadStatus.textContent = `Upload failed: ${err.message}`;
    uploadStatus.style.color = "#f44";
  }
}

// ---------------------------------------------------------------------------
// Wire up buttons
// ---------------------------------------------------------------------------

document.getElementById("btnLoadSets").addEventListener("click", loadSets);
document.getElementById("btnAddProp").addEventListener("click", addProp);
document.getElementById("btnDeleteProp").addEventListener("click", deleteProp);
document.getElementById("btnSaveSet").addEventListener("click", saveSet);
document.getElementById("btnRemoveFrame").addEventListener("click", removeSelectedFrame);
document.getElementById("btnMoveFrameLeft").addEventListener("click", moveFrameLeft);
document.getElementById("btnMoveFrameRight").addEventListener("click", moveFrameRight);
document.getElementById("btnUploadImage").addEventListener("click", uploadImage);

// Auto-load on page open
loadSets();
