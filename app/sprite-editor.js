(function () {
  let selectedSet = null;
  let selectedSpriteId = null;
  let selectedAnimId = null;
  let selectedFrameIndex = -1;   // position within animFrames array; -1 = append
  let currentDefinition = null;
  let loadedImage = null;
  let animFrames = [];           // working copy of the current animation's frames

  const setList = document.getElementById("setList");
  const spriteList = document.getElementById("spriteList");
  const animList = document.getElementById("animList");
  const setTitle = document.getElementById("setTitle");
  const setMeta = document.getElementById("setMeta");
  const spriteCanvas = document.getElementById("spriteCanvas");
  const ctx = spriteCanvas.getContext("2d");
  const imageHint = document.getElementById("imageHint");
  const frameWidth = document.getElementById("frameWidth");
  const frameHeight = document.getElementById("frameHeight");
  const backgroundColor = document.getElementById("backgroundColor");
  const statusBox = document.getElementById("statusBox");
  const animSpeed = document.getElementById("animSpeed");
  const animType = document.getElementById("animType");
  const animFrameStrip = document.getElementById("animFrameStrip");
  const animFramesHint = document.getElementById("animFramesHint");

  const THUMB_SIZE = 40;  // thumbnail cell size in px

  function setStatus(text) {
    statusBox.textContent = text || "";
  }

  async function api(path, options) {
    const response = await fetch(path, {
      ...options,
      headers: {
        "Content-Type": "application/json",
        ...(options?.headers || {}),
      },
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) {
      const detail = payload?.details ? `\n${payload.details.join("\n")}` : "";
      throw new Error((payload?.error || `HTTP ${response.status}`) + detail);
    }
    return payload;
  }

  // -------------------------------------------------------------------------
  // Canvas drawing
  // -------------------------------------------------------------------------

  function fw() { return Math.max(1, Number(frameWidth.value) || 32); }
  function fh() { return Math.max(1, Number(frameHeight.value) || 32); }

  function drawCanvas() {
    if (!loadedImage) return;
    spriteCanvas.width = loadedImage.naturalWidth;
    spriteCanvas.height = loadedImage.naturalHeight;
    ctx.drawImage(loadedImage, 0, 0);

    // Pink frame grid
    ctx.strokeStyle = "rgba(255, 105, 180, 0.9)";
    ctx.lineWidth = 1;
    ctx.beginPath();
    for (let x = fw(); x < spriteCanvas.width; x += fw()) {
      ctx.moveTo(x + 0.5, 0);
      ctx.lineTo(x + 0.5, spriteCanvas.height);
    }
    for (let y = fh(); y < spriteCanvas.height; y += fh()) {
      ctx.moveTo(0, y + 0.5);
      ctx.lineTo(spriteCanvas.width, y + 0.5);
    }
    ctx.stroke();
  }

  // Draw a single frame thumbnail onto an offscreen canvas, return it.
  function makeThumb(col, row) {
    const offscreen = document.createElement("canvas");
    offscreen.width = THUMB_SIZE;
    offscreen.height = THUMB_SIZE;
    const octx = offscreen.getContext("2d");
    if (loadedImage) {
      octx.drawImage(
        loadedImage,
        col * fw(), row * fh(), fw(), fh(),
        0, 0, THUMB_SIZE, THUMB_SIZE
      );
    }
    return offscreen;
  }

  // -------------------------------------------------------------------------
  // Animation frame strip rendering
  // -------------------------------------------------------------------------

  function parseFrameToken(token) {
    const parts = String(token || "0x0").split("x");
    return { col: parseInt(parts[0], 10) || 0, row: parseInt(parts[1], 10) || 0 };
  }

  function renderFrameStrip() {
    animFrameStrip.innerHTML = "";
    if (!selectedAnimId) {
      animFramesHint.textContent = "";
      return;
    }

    const insertPos = selectedFrameIndex >= 0 && selectedFrameIndex < animFrames.length
      ? selectedFrameIndex
      : animFrames.length;
    animFramesHint.textContent =
      animFrames.length === 0
        ? "(no frames)"
        : `${animFrames.length} frame(s) — inserting at position ${insertPos}`;

    animFrames.forEach((token, i) => {
      const { col, row } = parseFrameToken(token);
      const cell = document.createElement("div");
      cell.className = "frame-cell" + (i === selectedFrameIndex ? " frame-cell-selected" : "");
      cell.title = `Frame ${i}: ${token} (col ${col}, row ${row})`;

      const thumb = makeThumb(col, row);
      const img = document.createElement("img");
      img.src = thumb.toDataURL();
      img.width = THUMB_SIZE;
      img.height = THUMB_SIZE;
      cell.appendChild(img);

      const label = document.createElement("div");
      label.className = "frame-label";
      label.textContent = token;
      cell.appendChild(label);

      cell.addEventListener("click", () => {
        selectedFrameIndex = i;
        renderFrameStrip();
        setStatus(`Selected frame ${i} (${token}) — click image to insert after it, or use Remove/Move.`);
      });

      animFrameStrip.appendChild(cell);
    });

    // "append" slot — always shown at the end, selected when nothing else is
    const appendCell = document.createElement("div");
    appendCell.className = "frame-cell frame-cell-append" + (selectedFrameIndex === -1 || selectedFrameIndex >= animFrames.length ? " frame-cell-selected" : "");
    appendCell.title = "Append new frames here";
    appendCell.textContent = "+";
    appendCell.addEventListener("click", () => {
      selectedFrameIndex = -1;
      renderFrameStrip();
      setStatus("Click a cell on the sprite image to append a frame.");
    });
    animFrameStrip.appendChild(appendCell);
  }

  // -------------------------------------------------------------------------
  // Canvas click: pick color OR insert frame
  // -------------------------------------------------------------------------

  spriteCanvas.addEventListener("click", (e) => {
    if (!loadedImage) return;
    const rect = spriteCanvas.getBoundingClientRect();
    const scaleX = spriteCanvas.width / rect.width;
    const scaleY = spriteCanvas.height / rect.height;
    const px = Math.floor((e.clientX - rect.left) * scaleX);
    const py = Math.floor((e.clientY - rect.top) * scaleY);

    if (selectedAnimId) {
      // Insert a frame token at the selected position
      const col = Math.floor(px / fw());
      const row = Math.floor(py / fh());
      const token = `${col}x${row}`;
      const insertAt = selectedFrameIndex >= 0 && selectedFrameIndex < animFrames.length
        ? selectedFrameIndex + 1
        : animFrames.length;
      animFrames.splice(insertAt, 0, token);
      selectedFrameIndex = insertAt;
      renderFrameStrip();
      setStatus(`Inserted frame ${token} at position ${insertAt}. Click Save Animation to persist.`);
    } else {
      // Pick background color
      const pixel = ctx.getImageData(px, py, 1, 1).data;
      const hex = "#" + [pixel[0], pixel[1], pixel[2]]
        .map((v) => v.toString(16).padStart(2, "0"))
        .join("");
      backgroundColor.value = hex;
      setStatus(`Picked background color: ${hex} — click Save Set to apply.`);
    }
  });

  frameWidth.addEventListener("input", drawCanvas);
  frameHeight.addEventListener("input", drawCanvas);

  // -------------------------------------------------------------------------
  // Load / select sets
  // -------------------------------------------------------------------------

  async function loadSets() {
    const payload = await api("/api/sprite-editor/sets");
    setList.innerHTML = "";
    for (const item of payload.sets || []) {
      const btn = document.createElement("button");
      btn.textContent = `${item.scope}:${item.filename}${item.has_yaml ? "" : " (no yaml)"}`;
      btn.onclick = () => selectSet(item);
      setList.appendChild(btn);
    }
    setStatus(`Loaded ${payload.sets?.length || 0} sprite sets.`);
  }

  async function selectSet(setDef) {
    selectedSet = setDef;
    selectedSpriteId = null;
    selectedAnimId = null;
    selectedFrameIndex = -1;
    animFrames = [];
    const payload = await api(`/api/sprite-editor/sets/${setDef.scope}/${setDef.filename}`);
    currentDefinition = payload.definition;
    setTitle.textContent = `${setDef.scope}:${setDef.filename}`;
    setMeta.textContent = payload.set.yaml_error || "";

    loadedImage = null;
    spriteCanvas.width = 0;
    spriteCanvas.height = 0;
    imageHint.textContent = "";

    const imageUrl = payload.set.image_url || "";
    if (imageUrl) {
      const img = new Image();
      img.onload = () => {
        loadedImage = img;
        drawCanvas();
        imageHint.textContent = "Click on image to pick background color, or select an animation to insert frames.";
      };
      img.onerror = () => setStatus("Failed to load sprite image.");
      img.src = imageUrl;
    }

    if (!currentDefinition) {
      await api(`/api/sprite-editor/sets/${setDef.scope}/${setDef.filename}/create-definition`, {
        method: "POST",
        body: JSON.stringify({ frame_width: 32, frame_height: 32 }),
      });
      return selectSet(setDef);
    }
    frameWidth.value = currentDefinition.frame_width || 32;
    frameHeight.value = currentDefinition.frame_height || 32;
    backgroundColor.value = currentDefinition.background_color || "";
    renderSprites();
    renderFrameStrip();
  }

  // -------------------------------------------------------------------------
  // Sprites panel
  // -------------------------------------------------------------------------

  function renderSprites() {
    spriteList.innerHTML = "";
    animList.innerHTML = "";
    if (!currentDefinition?.sprites) return;
    Object.keys(currentDefinition.sprites).forEach((spriteId) => {
      const btn = document.createElement("button");
      btn.textContent = spriteId + (selectedSpriteId === spriteId ? " ✓" : "");
      btn.onclick = () => {
        selectedSpriteId = spriteId;
        selectedAnimId = null;
        selectedFrameIndex = -1;
        animFrames = [];
        renderSprites();
        renderAnims();
        renderFrameStrip();
      };
      spriteList.appendChild(btn);
    });
    renderAnims();
  }

  // -------------------------------------------------------------------------
  // Animations panel
  // -------------------------------------------------------------------------

  function renderAnims() {
    animList.innerHTML = "";
    if (!selectedSpriteId || !currentDefinition?.sprites?.[selectedSpriteId]) return;
    const anims = currentDefinition.sprites[selectedSpriteId].anims || {};
    Object.keys(anims).forEach((animId) => {
      const anim = anims[animId];
      const btn = document.createElement("button");
      btn.textContent = `${animId} (${anim.type}, ${anim.speed}s, ${(anim.frames || []).length}fr)` +
        (selectedAnimId === animId ? " ✓" : "");
      btn.onclick = () => {
        selectedAnimId = animId;
        animSpeed.value = Number(anim.speed || 0.5);
        animType.value = anim.type || "loop";
        animFrames = [...(anim.frames || [])];
        selectedFrameIndex = animFrames.length > 0 ? animFrames.length - 1 : -1;
        renderAnims();
        renderFrameStrip();
        setStatus(`Editing animation "${animId}". Click a sprite cell to insert frames.`);
      };
      animList.appendChild(btn);
    });
  }

  // -------------------------------------------------------------------------
  // Save set
  // -------------------------------------------------------------------------

  async function saveSet() {
    if (!selectedSet || !currentDefinition) return;
    currentDefinition.frame_width = Number(frameWidth.value || 32);
    currentDefinition.frame_height = Number(frameHeight.value || 32);
    const bg = String(backgroundColor.value || "").trim();
    currentDefinition.background_color = bg.length ? bg : null;
    await api(`/api/sprite-editor/sets/${selectedSet.scope}/${selectedSet.filename}`, {
      method: "PUT",
      body: JSON.stringify({ definition: currentDefinition }),
    });
    await selectSet(selectedSet);
    setStatus("Saved set.");
  }

  // -------------------------------------------------------------------------
  // Sprite CRUD
  // -------------------------------------------------------------------------

  async function addSprite() {
    if (!selectedSet) return;
    const spriteId = document.getElementById("newSpriteId").value.trim();
    if (!spriteId) return;
    await api(`/api/sprite-editor/sets/${selectedSet.scope}/${selectedSet.filename}/sprites`, {
      method: "POST",
      body: JSON.stringify({ sprite_id: spriteId, default_frame: "0x0" }),
    });
    await selectSet(selectedSet);
  }

  async function deleteSprite() {
    if (!selectedSet || !selectedSpriteId) return;
    await api(`/api/sprite-editor/sets/${selectedSet.scope}/${selectedSet.filename}/sprites/${selectedSpriteId}`, {
      method: "DELETE",
    });
    await selectSet(selectedSet);
  }

  async function renameSprite() {
    if (!selectedSet || !selectedSpriteId || !currentDefinition) return;
    const newId = document.getElementById("renameSpriteId").value.trim();
    if (!newId) return setStatus("Enter a new sprite id to rename to.");
    if (newId === selectedSpriteId) return;
    const sprites = currentDefinition.sprites || {};
    if (newId in sprites) return setStatus(`Sprite "${newId}" already exists.`);
    // Reorder-preserving rename: rebuild the sprites object with newId in the same position
    const reordered = {};
    for (const [k, v] of Object.entries(sprites)) {
      reordered[k === selectedSpriteId ? newId : k] = v;
    }
    currentDefinition.sprites = reordered;
    await api(`/api/sprite-editor/sets/${selectedSet.scope}/${selectedSet.filename}`, {
      method: "PUT",
      body: JSON.stringify({ definition: currentDefinition }),
    });
    selectedSpriteId = newId;
    document.getElementById("renameSpriteId").value = "";
    await selectSet(selectedSet);
    selectedSpriteId = newId;
    renderSprites();
    setStatus(`Renamed sprite to "${newId}".`);
  }

  // -------------------------------------------------------------------------
  // Animation CRUD
  // -------------------------------------------------------------------------

  async function addAnim() {
    if (!selectedSet || !selectedSpriteId) return;
    const animId = document.getElementById("newAnimId").value.trim();
    if (!animId) return;
    await api(`/api/sprite-editor/sets/${selectedSet.scope}/${selectedSet.filename}/sprites/${selectedSpriteId}/anims`, {
      method: "POST",
      body: JSON.stringify({ anim_id: animId, speed: 0.5, type: "loop", frames: ["0x0"] }),
    });
    await selectSet(selectedSet);
  }

  async function deleteAnim() {
    if (!selectedSet || !selectedSpriteId || !selectedAnimId) return;
    await api(`/api/sprite-editor/sets/${selectedSet.scope}/${selectedSet.filename}/sprites/${selectedSpriteId}/anims/${selectedAnimId}`, {
      method: "DELETE",
    });
    selectedAnimId = null;
    animFrames = [];
    selectedFrameIndex = -1;
    await selectSet(selectedSet);
  }

  async function renameAnim() {
    if (!selectedSet || !selectedSpriteId || !selectedAnimId || !currentDefinition) return;
    const newId = document.getElementById("renameAnimId").value.trim();
    if (!newId) return setStatus("Enter a new animation id to rename to.");
    if (newId === selectedAnimId) return;
    const anims = currentDefinition.sprites?.[selectedSpriteId]?.anims || {};
    if (newId in anims) return setStatus(`Animation "${newId}" already exists.`);
    const reordered = {};
    for (const [k, v] of Object.entries(anims)) {
      reordered[k === selectedAnimId ? newId : k] = v;
    }
    currentDefinition.sprites[selectedSpriteId].anims = reordered;
    await api(`/api/sprite-editor/sets/${selectedSet.scope}/${selectedSet.filename}`, {
      method: "PUT",
      body: JSON.stringify({ definition: currentDefinition }),
    });
    const savedSpriteId = selectedSpriteId;
    selectedAnimId = newId;
    document.getElementById("renameAnimId").value = "";
    await selectSet(selectedSet);
    selectedSpriteId = savedSpriteId;
    selectedAnimId = newId;
    const anim = currentDefinition?.sprites?.[savedSpriteId]?.anims?.[newId];
    if (anim) {
      animSpeed.value = Number(anim.speed || 0.5);
      animType.value = anim.type || "loop";
      animFrames = [...(anim.frames || [])];
      selectedFrameIndex = animFrames.length > 0 ? animFrames.length - 1 : -1;
    }
    renderSprites();
    renderFrameStrip();
    setStatus(`Renamed animation to "${newId}".`);
  }

  async function saveAnim() {
    if (!selectedSet || !selectedSpriteId || !selectedAnimId) return;
    const savedSpriteId = selectedSpriteId;
    const savedAnimId = selectedAnimId;
    const savedFrameIndex = selectedFrameIndex;
    await api(`/api/sprite-editor/sets/${selectedSet.scope}/${selectedSet.filename}/sprites/${savedSpriteId}/anims/${savedAnimId}`, {
      method: "PUT",
      body: JSON.stringify({
        speed: Number(animSpeed.value || 0.5),
        type: animType.value || "loop",
        frames: animFrames,
      }),
    });
    await selectSet(selectedSet);
    // Restore sprite + animation selection after reload
    selectedSpriteId = savedSpriteId;
    selectedAnimId = savedAnimId;
    const anim = currentDefinition?.sprites?.[savedSpriteId]?.anims?.[savedAnimId];
    if (anim) {
      animSpeed.value = Number(anim.speed || 0.5);
      animType.value = anim.type || "loop";
      animFrames = [...(anim.frames || [])];
      selectedFrameIndex = Math.min(savedFrameIndex, animFrames.length - 1);
    }
    renderSprites();
    renderFrameStrip();
    setStatus(`Saved animation "${savedAnimId}".`);
  }

  // -------------------------------------------------------------------------
  // Frame manipulation buttons
  // -------------------------------------------------------------------------

  document.getElementById("btnRemoveFrame").onclick = () => {
    if (selectedFrameIndex < 0 || selectedFrameIndex >= animFrames.length) {
      setStatus("No frame selected to remove.");
      return;
    }
    animFrames.splice(selectedFrameIndex, 1);
    if (selectedFrameIndex >= animFrames.length) selectedFrameIndex = animFrames.length - 1;
    renderFrameStrip();
    setStatus(`Removed frame. ${animFrames.length} frame(s) remaining.`);
  };

  document.getElementById("btnMoveFrameLeft").onclick = () => {
    if (selectedFrameIndex <= 0 || selectedFrameIndex >= animFrames.length) return;
    [animFrames[selectedFrameIndex - 1], animFrames[selectedFrameIndex]] =
      [animFrames[selectedFrameIndex], animFrames[selectedFrameIndex - 1]];
    selectedFrameIndex--;
    renderFrameStrip();
  };

  document.getElementById("btnMoveFrameRight").onclick = () => {
    if (selectedFrameIndex < 0 || selectedFrameIndex >= animFrames.length - 1) return;
    [animFrames[selectedFrameIndex], animFrames[selectedFrameIndex + 1]] =
      [animFrames[selectedFrameIndex + 1], animFrames[selectedFrameIndex]];
    selectedFrameIndex++;
    renderFrameStrip();
  };

  // -------------------------------------------------------------------------
  // Button wiring
  // -------------------------------------------------------------------------

  document.getElementById("btnLoadSets").onclick = () => loadSets().catch((err) => setStatus(err.message));
  document.getElementById("btnClearBackground").onclick = () => { backgroundColor.value = ""; };
  document.getElementById("btnSaveSet").onclick = () => saveSet().catch((err) => setStatus(err.message));
  document.getElementById("btnAddSprite").onclick = () => addSprite().catch((err) => setStatus(err.message));
  document.getElementById("btnRenameSprite").onclick = () => renameSprite().catch((err) => setStatus(err.message));
  document.getElementById("btnAddAnim").onclick = () => addAnim().catch((err) => setStatus(err.message));
  document.getElementById("btnRenameAnim").onclick = () => renameAnim().catch((err) => setStatus(err.message));
  document.getElementById("btnDeleteSprite").onclick = () => deleteSprite().catch((err) => setStatus(err.message));
  document.getElementById("btnDeleteAnim").onclick = () => deleteAnim().catch((err) => setStatus(err.message));
  document.getElementById("btnSaveAnim").onclick = () => saveAnim().catch((err) => setStatus(err.message));
})();
