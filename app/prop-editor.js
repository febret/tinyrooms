"use strict";

(function () {
  const state = {
    sets: [],
    selectedSet: null,
    definition: null,
    image: null,
    selectedPropId: null,
    selectedFrameIdx: null,
    isDirty: false,
    zoom: 1,
    pickingBgColor: false,
    propNameQuery: "",
    propTagFilter: "",
  };

  const PROP_TAG_OPTIONS = ["avatar", "peep", "object", "item", "container", "consumable"];
  const THUMB_SIZE = 40;

  const setList = document.getElementById("setList");
  const setTitle = document.getElementById("setTitle");
  const imageHint = document.getElementById("imageHint");
  const zoomSlider = document.getElementById("zoomSlider");
  const zoomLabel = document.getElementById("zoomLabel");
  const propCanvas = document.getElementById("propCanvas");
  const overlayCanvas = document.getElementById("overlayCanvas");
  const canvasViewport = document.getElementById("canvasViewport");
  const propList = document.getElementById("propList");
  const newPropId = document.getElementById("newPropId");
  const renamePropId = document.getElementById("renamePropId");
  const propSearchInput = document.getElementById("propSearchInput");
  const propTagFilter = document.getElementById("propTagFilter");
  const propTagEditor = document.getElementById("propTagEditor");
  const propWidth = document.getElementById("propWidth");
  const propHeight = document.getElementById("propHeight");
  const frameX = document.getElementById("frameX");
  const frameY = document.getElementById("frameY");
  const propAnimSpeed = document.getElementById("propAnimSpeed");
  const bgColorText = document.getElementById("bgColorText");
  const bgColorSwatch = document.getElementById("bgColorSwatch");
  const framesStrip = document.getElementById("framesStrip");
  const statusBox = document.getElementById("statusBox");
  const btnSaveSet = document.getElementById("btnSaveSet");
  const btnPickBgColor = document.getElementById("btnPickBgColor");

  const ctx = propCanvas.getContext("2d");
  const octx = overlayCanvas.getContext("2d");

  function setStatus(msg, isError = false) {
    statusBox.textContent = msg || "";
    statusBox.style.color = isError ? "#f44" : "#4f4";
  }

  function setKey(setDef) {
    return `${setDef?.scope || ""}:${setDef?.filename || ""}`;
  }

  function selectedProp() {
    if (!state.definition || !state.selectedPropId) return null;
    return state.definition.props?.[state.selectedPropId] || null;
  }

  function updateHeader() {
    if (!state.selectedSet) {
      setTitle.textContent = "No set selected";
      return;
    }
    setTitle.textContent = `${state.selectedSet.scope}:${state.selectedSet.filename}${state.isDirty ? " *" : ""}`;
  }

  function setDirty(value) {
    state.isDirty = Boolean(value);
    btnSaveSet.textContent = state.isDirty ? "Save *" : "Save";
    btnSaveSet.disabled = !state.selectedSet || !state.definition;
    updateHeader();
  }

  function markDirty(statusText = "") {
    setDirty(true);
    if (statusText) setStatus(statusText);
  }

  function normalizePropTags(prop) {
    if (!prop || typeof prop !== "object") return [];
    const rawTags = Array.isArray(prop.tags) ? prop.tags : [];
    const tags = [];
    const seen = new Set();
    rawTags.forEach((rawTag) => {
      const tag = String(rawTag || "").trim().toLowerCase();
      if (!tag || seen.has(tag)) return;
      seen.add(tag);
      tags.push(tag);
    });
    prop.tags = tags;
    return tags;
  }

  function parsePositiveInt(value, fallback = 32) {
    const n = Number.parseInt(value, 10);
    return Number.isFinite(n) && n > 0 ? n : fallback;
  }

  function parseNonNegativeInt(value, fallback = 0) {
    const n = Number.parseInt(value, 10);
    return Number.isFinite(n) && n >= 0 ? n : fallback;
  }

  function currentBgRgb() {
    const raw = String(bgColorText.value || state.definition?.background_color || "").trim();
    return parseBgColor(raw);
  }

  function updateBgSwatch() {
    const rgb = parseBgColor(String(bgColorText.value || "").trim());
    bgColorSwatch.style.background = rgb ? `rgb(${rgb[0]},${rgb[1]},${rgb[2]})` : "transparent";
    bgColorSwatch.style.border = rgb ? "1px solid #555" : "1px dashed #555";
  }

  function normalizeZoom(value) {
    const raw = Number(value);
    if (!Number.isFinite(raw) || raw <= 0) return 1;
    const step = 0.25;
    const snapped = Math.round(raw / step) * step;
    return Math.min(8, Math.max(0.25, snapped));
  }

  function formatZoom(value) {
    return `${Number(value).toFixed(value % 1 === 0 ? 0 : 2)}×`;
  }

  function drawCanvas() {
    if (!state.image) {
      ctx.clearRect(0, 0, propCanvas.width, propCanvas.height);
      octx.clearRect(0, 0, overlayCanvas.width, overlayCanvas.height);
      return;
    }
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
    const width = propCanvas.width * state.zoom;
    const height = propCanvas.height * state.zoom;
    propCanvas.style.width = `${width}px`;
    propCanvas.style.height = `${height}px`;
    overlayCanvas.style.width = `${width}px`;
    overlayCanvas.style.height = `${height}px`;
    zoomSlider.value = String(state.zoom);
    zoomLabel.textContent = formatZoom(state.zoom);
  }

  function drawOverlay() {
    octx.clearRect(0, 0, overlayCanvas.width, overlayCanvas.height);
    const prop = selectedProp();
    if (!prop || state.selectedFrameIdx == null) return;
    const frames = prop.frames || [];
    if (state.selectedFrameIdx >= frames.length) return;
    const [fx, fy] = frames[state.selectedFrameIdx];
    const w = parsePositiveInt(prop.width, 32);
    const h = parsePositiveInt(prop.height, 32);
    octx.strokeStyle = "#ff69b4";
    octx.lineWidth = Math.max(0.5, 2 / state.zoom);
    octx.strokeRect(fx + 0.5, fy + 0.5, w - 1, h - 1);
    octx.fillStyle = "rgba(255,105,180,0.15)";
    octx.fillRect(fx, fy, w, h);
  }

  function createPropThumbImage(prop, frameIdx = 0, className = "thumb-image") {
    const canvas = document.createElement("canvas");
    canvas.width = THUMB_SIZE;
    canvas.height = THUMB_SIZE;
    canvas.className = className;
    if (!state.image || !Array.isArray(prop?.frames) || prop.frames.length === 0) {
      canvas.classList.add("thumb-placeholder");
      return canvas;
    }
    const safeIdx = Math.max(0, Math.min(frameIdx, prop.frames.length - 1));
    const frame = prop.frames[safeIdx];
    if (!Array.isArray(frame) || frame.length < 2) {
      canvas.classList.add("thumb-placeholder");
      return canvas;
    }
    drawSpriteThumb(
      canvas,
      state.image,
      parseNonNegativeInt(frame[0], 0),
      parseNonNegativeInt(frame[1], 0),
      parsePositiveInt(prop.width, 32),
      parsePositiveInt(prop.height, 32),
      currentBgRgb(),
    );
    return canvas;
  }

  function propMatchesFilters(propId, prop) {
    const tags = normalizePropTags(prop);
    if (state.propTagFilter && !tags.includes(state.propTagFilter)) return false;
    if (!state.propNameQuery) return true;
    const q = state.propNameQuery.toLowerCase();
    return String(propId || "").toLowerCase().includes(q) || tags.some((tag) => tag.includes(q));
  }

  function renderSetList() {
    setList.innerHTML = "";
    state.sets.forEach((rec) => {
      const rowWrap = document.createElement("div");
      rowWrap.className = "list-item-row";

      const btn = document.createElement("button");
      btn.className = "list-item-button" + (setKey(rec) === setKey(state.selectedSet) ? " list-item-selected" : "");

      const row = document.createElement("div");
      row.className = "list-item-row";

      const preview = document.createElement("img");
      preview.className = "set-preview";
      preview.alt = `${rec.filename} preview`;
      if (rec.image_url) {
        preview.src = rec.image_url;
      } else {
        preview.classList.add("thumb-placeholder");
      }
      row.appendChild(preview);

      const textWrap = document.createElement("div");
      textWrap.className = "list-item-text";
      const title = document.createElement("div");
      title.className = "list-item-title";
      title.textContent = `${rec.scope}:${rec.filename}`;
      textWrap.appendChild(title);
      const sub = document.createElement("div");
      sub.className = "list-item-subtitle";
      sub.textContent = rec.has_yaml ? "definition present" : "no yaml yet";
      textWrap.appendChild(sub);
      row.appendChild(textWrap);
      btn.appendChild(row);

      btn.addEventListener("click", () => {
        attemptSelectSet(rec).catch((err) => setStatus(err.message, true));
      });
      rowWrap.appendChild(btn);

      if (!rec.has_yaml) {
        const createBtn = document.createElement("button");
        createBtn.textContent = "Create";
        createBtn.addEventListener("click", (event) => {
          event.stopPropagation();
          createDefinition(rec).catch((err) => setStatus(err.message, true));
        });
        rowWrap.appendChild(createBtn);
      }
      setList.appendChild(rowWrap);
    });
  }

  function renderPropTagEditor() {
    propTagEditor.innerHTML = "";
    const prop = selectedProp();
    if (!prop) {
      const empty = document.createElement("div");
      empty.className = "tag-editor-empty";
      empty.textContent = "Select a prop to edit tags.";
      propTagEditor.appendChild(empty);
      return;
    }
    const selectedTags = normalizePropTags(prop);
    PROP_TAG_OPTIONS.forEach((tag) => {
      const label = document.createElement("label");
      label.className = "tag-option";
      const checkbox = document.createElement("input");
      checkbox.type = "checkbox";
      checkbox.checked = selectedTags.includes(tag);
      checkbox.addEventListener("change", () => {
        const next = new Set(normalizePropTags(prop));
        if (checkbox.checked) next.add(tag);
        else next.delete(tag);
        prop.tags = [...next];
        renderPropList();
        renderPropTagEditor();
        markDirty(`Updated tags for "${state.selectedPropId}".`);
      });
      label.appendChild(checkbox);
      const text = document.createElement("span");
      text.textContent = tag;
      label.appendChild(text);
      propTagEditor.appendChild(label);
    });
  }

  function renderPropList() {
    propList.innerHTML = "";
    if (!state.definition?.props) {
      renderPropTagEditor();
      return;
    }

    let visibleCount = 0;
    Object.keys(state.definition.props).forEach((propId) => {
      const prop = state.definition.props[propId];
      if (!propMatchesFilters(propId, prop)) return;
      visibleCount += 1;

      const btn = document.createElement("button");
      btn.className = "list-item-button" + (propId === state.selectedPropId ? " list-item-selected" : "");

      const row = document.createElement("div");
      row.className = "list-item-row";
      row.appendChild(createPropThumbImage(prop));

      const textWrap = document.createElement("div");
      textWrap.className = "list-item-text";
      const title = document.createElement("div");
      title.className = "list-item-title";
      title.textContent = propId;
      textWrap.appendChild(title);

      const tags = normalizePropTags(prop);
      const sub = document.createElement("div");
      sub.className = "list-item-subtitle";
      sub.textContent = `${(prop.frames || []).length} frame(s), ${parsePositiveInt(prop.width, 32)}x${parsePositiveInt(prop.height, 32)}`;
      textWrap.appendChild(sub);

      const tagsLine = document.createElement("div");
      tagsLine.className = "list-item-subtitle";
      tagsLine.textContent = `tags: ${tags.length > 0 ? tags.join(", ") : "no tags"}`;
      textWrap.appendChild(tagsLine);

      row.appendChild(textWrap);
      btn.appendChild(row);
      btn.addEventListener("click", () => {
        state.selectedPropId = propId;
        state.selectedFrameIdx = 0;
        renderPropList();
        renderPropDetails();
        renderFrames();
        drawOverlay();
      });
      propList.appendChild(btn);
    });

    if (visibleCount === 0) {
      const empty = document.createElement("div");
      empty.className = "tag-editor-empty";
      empty.textContent = "No props match the current name/tag filter.";
      propList.appendChild(empty);
    }

    if (
      state.selectedPropId &&
      (!state.definition.props[state.selectedPropId] || !propMatchesFilters(state.selectedPropId, state.definition.props[state.selectedPropId]))
    ) {
      state.selectedPropId = null;
      state.selectedFrameIdx = null;
    }
    renderPropTagEditor();
  }

  function renderPropDetails() {
    const prop = selectedProp();
    if (!prop) {
      propWidth.value = "";
      propHeight.value = "";
      propAnimSpeed.value = "";
      frameX.value = "";
      frameY.value = "";
      return;
    }

    propWidth.value = parsePositiveInt(prop.width, 32);
    propHeight.value = parsePositiveInt(prop.height, 32);
    propAnimSpeed.value = prop.anim_speed != null ? String(prop.anim_speed) : "";
    const frames = Array.isArray(prop.frames) ? prop.frames : [];
    if (state.selectedFrameIdx != null && state.selectedFrameIdx < frames.length) {
      frameX.value = parseNonNegativeInt(frames[state.selectedFrameIdx][0], 0);
      frameY.value = parseNonNegativeInt(frames[state.selectedFrameIdx][1], 0);
    } else {
      frameX.value = "";
      frameY.value = "";
    }
  }

  function renderFrames() {
    framesStrip.innerHTML = "";
    const prop = selectedProp();
    if (!prop) return;
    const frames = Array.isArray(prop.frames) ? prop.frames : [];
    const pw = parsePositiveInt(prop.width, 32);
    const ph = parsePositiveInt(prop.height, 32);
    const thumbW = Math.max(24, Math.min(72, pw));
    const thumbH = Math.max(24, Math.min(72, ph));

    if (frames.length === 0) {
      const empty = document.createElement("div");
      empty.className = "tag-editor-empty";
      empty.textContent = "No frames yet.";
      framesStrip.appendChild(empty);
      return;
    }

    frames.forEach((frame, idx) => {
      const [fx, fy] = frame;
      const cell = document.createElement("div");
      cell.className = "frame-thumb" + (idx === state.selectedFrameIdx ? " selected" : "");

      const thumb = document.createElement("canvas");
      thumb.width = thumbW;
      thumb.height = thumbH;
      if (state.image) {
        drawSpriteThumb(
          thumb,
          state.image,
          parseNonNegativeInt(fx, 0),
          parseNonNegativeInt(fy, 0),
          pw,
          ph,
          currentBgRgb(),
        );
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

  function updateSetFromInputs() {
    if (!state.definition) return;
    const bg = String(bgColorText.value || "").trim();
    state.definition.background_color = bg.length > 0 ? bg : null;
  }

  async function loadSets() {
    const payload = await editorApi("/api/prop-editor/sets");
    state.sets = payload.sets || [];
    renderSetList();
    setStatus(`Loaded ${state.sets.length} prop set(s).`);
  }

  async function createDefinition(rec) {
    const propId = (window.prompt("Prop id for new definition:", "prop_1") || "").trim();
    if (!propId) return;
    await editorApi(`/api/prop-editor/sets/${rec.scope}/${rec.filename}/create-definition`, {
      method: "POST",
      body: JSON.stringify({ prop_id: propId }),
    });
    setStatus(`Created definition for ${rec.scope}:${rec.filename}.`);
    await loadSets();
    const updated = state.sets.find((item) => item.scope === rec.scope && item.filename === rec.filename);
    if (updated) await selectSet(updated);
  }

  async function maybeSaveBeforeSwitch(nextSet) {
    if (!state.selectedSet || !state.isDirty) return true;
    if (setKey(nextSet) === setKey(state.selectedSet)) return true;
    const shouldSave = window.confirm("This propset has unsaved changes. Save before switching?");
    if (!shouldSave) return true;
    try {
      await saveSet();
      return true;
    } catch (err) {
      setStatus(err.message, true);
      return false;
    }
  }

  async function attemptSelectSet(rec) {
    const ok = await maybeSaveBeforeSwitch(rec);
    if (!ok) return;
    await selectSet(rec);
  }

  async function selectSet(rec) {
    state.selectedSet = rec;
    state.definition = null;
    state.selectedPropId = null;
    state.selectedFrameIdx = null;
    state.image = null;
    state.pickingBgColor = false;
    btnPickBgColor.style.borderColor = "";
    imageHint.textContent = "";
    setDirty(false);
    renderSetList();
    renderPropList();
    renderPropDetails();
    renderFrames();

    const payload = await editorApi(`/api/prop-editor/sets/${rec.scope}/${rec.filename}`);
    state.selectedSet = payload.set;
    state.definition = payload.definition;
    if (!state.definition) {
      renderSetList();
      setStatus("No definition yet. Click Create on this set.", true);
      return;
    }
    bgColorText.value = state.definition.background_color || "";
    updateBgSwatch();

    if (payload.set.image_url) {
      try {
        state.image = await loadImage(payload.set.image_url);
        drawCanvas();
      } catch (err) {
        state.image = null;
        setStatus(err.message, true);
      }
    }
    renderSetList();
    renderPropList();
    renderPropDetails();
    renderFrames();
    drawOverlay();
    setDirty(false);
    setStatus("Propset loaded.");
  }

  function createDefaultProp(frameXPos = 0, frameYPos = 0) {
    const width = parsePositiveInt(propWidth.value, 32);
    const height = parsePositiveInt(propHeight.value, 32);
    const speedRaw = String(propAnimSpeed.value || "").trim();
    const out = {
      width,
      height,
      frames: [[parseNonNegativeInt(frameXPos, 0), parseNonNegativeInt(frameYPos, 0)]],
      tags: [],
    };
    if (speedRaw.length > 0) {
      const speed = Number.parseFloat(speedRaw);
      if (Number.isFinite(speed) && speed > 0) out.anim_speed = speed;
    }
    return out;
  }

  function addPropWithFrame(propId, frameXPos = 0, frameYPos = 0) {
    if (!state.definition?.props) return false;
    const id = String(propId || "").trim();
    if (!id) {
      setStatus("Enter a prop id.", true);
      return false;
    }
    if (state.definition.props[id]) {
      setStatus(`Prop "${id}" already exists.`, true);
      return false;
    }
    state.definition.props[id] = createDefaultProp(frameXPos, frameYPos);
    newPropId.value = "";
    state.selectedPropId = id;
    state.selectedFrameIdx = 0;
    renderPropList();
    renderPropDetails();
    renderFrames();
    drawOverlay();
    markDirty(`Added prop "${id}".`);
    return true;
  }

  function addProp() {
    if (!state.definition) return;
    addPropWithFrame(newPropId.value, 0, 0);
  }

  function deleteProp() {
    if (!state.definition?.props || !state.selectedPropId) return;
    const ids = Object.keys(state.definition.props);
    if (ids.length <= 1) {
      setStatus("Prop set must contain at least one prop.", true);
      return;
    }
    if (!window.confirm(`Delete prop "${state.selectedPropId}"?`)) return;
    delete state.definition.props[state.selectedPropId];
    state.selectedPropId = null;
    state.selectedFrameIdx = null;
    renderPropList();
    renderPropDetails();
    renderFrames();
    drawOverlay();
    markDirty("Deleted prop.");
  }

  function renameProp() {
    if (!state.definition?.props || !state.selectedPropId) return;
    const nextId = String(renamePropId.value || "").trim();
    if (!nextId) {
      setStatus("Enter a new prop id to rename to.", true);
      return;
    }
    if (nextId === state.selectedPropId) return;
    if (state.definition.props[nextId]) {
      setStatus(`Prop "${nextId}" already exists.`, true);
      return;
    }
    state.definition.props = renameKeyInObject(state.definition.props, state.selectedPropId, nextId);
    state.selectedPropId = nextId;
    renamePropId.value = "";
    renderPropList();
    markDirty(`Renamed prop to "${nextId}".`);
  }

  async function saveSet() {
    if (!state.selectedSet || !state.definition) return;
    updateSetFromInputs();
    await editorApi(`/api/prop-editor/sets/${state.selectedSet.scope}/${state.selectedSet.filename}`, {
      method: "PUT",
      body: JSON.stringify({ definition: state.definition }),
    });
    setDirty(false);
    setStatus("Saved propset.");
  }

  function deleteSelectedFrame() {
    const prop = selectedProp();
    if (!prop) return;
    const frames = Array.isArray(prop.frames) ? prop.frames : [];
    if (frames.length <= 1) {
      setStatus("A prop must have at least one frame.", true);
      return;
    }
    if (state.selectedFrameIdx == null || state.selectedFrameIdx >= frames.length) {
      setStatus("Select a frame to delete first.", true);
      return;
    }
    const removed = frames.splice(state.selectedFrameIdx, 1)[0];
    const nextIdx = Math.min(state.selectedFrameIdx, frames.length - 1);
    state.selectedFrameIdx = nextIdx;
    renderFrames();
    renderPropDetails();
    drawOverlay();
    markDirty(`Deleted frame (${removed[0]},${removed[1]}).`);
  }

  function setZoom(nextZoom) {
    state.zoom = normalizeZoom(nextZoom);
    applyZoom();
    drawOverlay();
  }

  propCanvas.addEventListener("click", (event) => {
    if (!state.image) return;
    const rect = propCanvas.getBoundingClientRect();
    const scaleX = propCanvas.width / rect.width;
    const scaleY = propCanvas.height / rect.height;
    const cx = Math.floor((event.clientX - rect.left) * scaleX);
    const cy = Math.floor((event.clientY - rect.top) * scaleY);

    const pendingPropId = String(newPropId.value || "").trim();
    if (pendingPropId) {
      addPropWithFrame(pendingPropId, cx, cy);
      return;
    }

    if (state.pickingBgColor) {
      const pixel = ctx.getImageData(cx, cy, 1, 1).data;
      const hex = "#" + [pixel[0], pixel[1], pixel[2]].map((v) => v.toString(16).padStart(2, "0")).join("");
      bgColorText.value = hex;
      updateSetFromInputs();
      updateBgSwatch();
      state.pickingBgColor = false;
      btnPickBgColor.style.borderColor = "";
      renderPropList();
      renderFrames();
      markDirty(`Background color set to ${hex}.`);
      return;
    }

    const prop = selectedProp();
    if (!prop) {
      setStatus("Select a prop first, or enter a new prop id to create one from this frame.", true);
      return;
    }
    prop.frames = Array.isArray(prop.frames) ? prop.frames : [];
    prop.frames.push([cx, cy]);
    state.selectedFrameIdx = prop.frames.length - 1;
    renderFrames();
    renderPropDetails();
    renderPropList();
    drawOverlay();
    markDirty(`Appended frame (${cx},${cy}) to "${state.selectedPropId}".`);
  });

  propWidth.addEventListener("input", () => {
    const prop = selectedProp();
    if (!prop) return;
    prop.width = parsePositiveInt(propWidth.value, parsePositiveInt(prop.width, 32));
    renderFrames();
    renderPropList();
    drawOverlay();
    markDirty();
  });

  propHeight.addEventListener("input", () => {
    const prop = selectedProp();
    if (!prop) return;
    prop.height = parsePositiveInt(propHeight.value, parsePositiveInt(prop.height, 32));
    renderFrames();
    renderPropList();
    drawOverlay();
    markDirty();
  });

  frameX.addEventListener("input", () => {
    const prop = selectedProp();
    if (!prop || state.selectedFrameIdx == null) return;
    if (!Array.isArray(prop.frames) || state.selectedFrameIdx >= prop.frames.length) return;
    prop.frames[state.selectedFrameIdx][0] = parseNonNegativeInt(frameX.value, prop.frames[state.selectedFrameIdx][0]);
    renderFrames();
    drawOverlay();
    markDirty();
  });

  frameY.addEventListener("input", () => {
    const prop = selectedProp();
    if (!prop || state.selectedFrameIdx == null) return;
    if (!Array.isArray(prop.frames) || state.selectedFrameIdx >= prop.frames.length) return;
    prop.frames[state.selectedFrameIdx][1] = parseNonNegativeInt(frameY.value, prop.frames[state.selectedFrameIdx][1]);
    renderFrames();
    drawOverlay();
    markDirty();
  });

  propAnimSpeed.addEventListener("change", () => {
    const prop = selectedProp();
    if (!prop) return;
    const raw = String(propAnimSpeed.value || "").trim();
    if (!raw) {
      delete prop.anim_speed;
    } else {
      const speed = Number.parseFloat(raw);
      if (!Number.isFinite(speed) || speed <= 0) {
        setStatus("Animation speed must be > 0.", true);
        return;
      }
      prop.anim_speed = speed;
    }
    markDirty("Updated animation speed.");
  });

  bgColorText.addEventListener("change", () => {
    updateSetFromInputs();
    updateBgSwatch();
    renderPropList();
    renderFrames();
    markDirty("Updated background color.");
  });

  document.getElementById("btnLoadSets").addEventListener("click", () => loadSets().catch((err) => setStatus(err.message, true)));
  document.getElementById("btnAddProp").addEventListener("click", addProp);
  document.getElementById("btnDeleteProp").addEventListener("click", deleteProp);
  document.getElementById("btnRenameProp").addEventListener("click", renameProp);
  document.getElementById("btnSaveSet").addEventListener("click", () => saveSet().catch((err) => setStatus(err.message, true)));
  document.getElementById("btnDeleteFrame").addEventListener("click", deleteSelectedFrame);

  btnPickBgColor.addEventListener("click", () => {
    state.pickingBgColor = !state.pickingBgColor;
    btnPickBgColor.style.borderColor = state.pickingBgColor ? "#ff69b4" : "";
    if (state.pickingBgColor) {
      imageHint.textContent = "Click on the prop image to pick a background color.";
      return;
    }
    imageHint.textContent = "";
  });

  document.getElementById("btnClearBgColor").addEventListener("click", () => {
    bgColorText.value = "";
    updateSetFromInputs();
    updateBgSwatch();
    renderPropList();
    renderFrames();
    markDirty("Cleared background color.");
  });

  zoomSlider.addEventListener("input", () => setZoom(zoomSlider.value));
  document.getElementById("btnZoomIn").addEventListener("click", () => setZoom(state.zoom + 0.25));
  document.getElementById("btnZoomOut").addEventListener("click", () => setZoom(state.zoom - 0.25));

  propSearchInput.addEventListener("input", () => {
    state.propNameQuery = String(propSearchInput.value || "").trim();
    renderPropList();
  });

  propTagFilter.addEventListener("change", () => {
    state.propTagFilter = String(propTagFilter.value || "").trim().toLowerCase();
    renderPropList();
  });

  window.addEventListener("beforeunload", (event) => {
    if (!state.isDirty) return;
    event.preventDefault();
    event.returnValue = "";
  });

  setDirty(false);
  renderPropTagEditor();
  loadSets().catch((err) => setStatus(err.message, true));
})();
