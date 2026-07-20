(function () {
  let selectedSet = null;
  let selectedSpriteId = null;
  let selectedAnimId = null;
  let currentDefinition = null;
  let loadedImage = null;

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
  const animFrames = document.getElementById("animFrames");

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

  function setKey(setDef) {
    return `${setDef.scope}/${setDef.filename}`;
  }

  function drawCanvas() {
    if (!loadedImage) return;
    const fw = Math.max(1, Number(frameWidth.value) || 32);
    const fh = Math.max(1, Number(frameHeight.value) || 32);
    spriteCanvas.width = loadedImage.naturalWidth;
    spriteCanvas.height = loadedImage.naturalHeight;
    ctx.drawImage(loadedImage, 0, 0);

    ctx.strokeStyle = "rgba(255, 105, 180, 0.9)";
    ctx.lineWidth = 1;
    ctx.beginPath();
    for (let x = fw; x < spriteCanvas.width; x += fw) {
      ctx.moveTo(x + 0.5, 0);
      ctx.lineTo(x + 0.5, spriteCanvas.height);
    }
    for (let y = fh; y < spriteCanvas.height; y += fh) {
      ctx.moveTo(0, y + 0.5);
      ctx.lineTo(spriteCanvas.width, y + 0.5);
    }
    ctx.stroke();
  }

  spriteCanvas.addEventListener("click", (e) => {
    if (!loadedImage) return;
    const rect = spriteCanvas.getBoundingClientRect();
    const scaleX = spriteCanvas.width / rect.width;
    const scaleY = spriteCanvas.height / rect.height;
    const x = Math.floor((e.clientX - rect.left) * scaleX);
    const y = Math.floor((e.clientY - rect.top) * scaleY);
    const pixel = ctx.getImageData(x, y, 1, 1).data;
    const hex = "#" + [pixel[0], pixel[1], pixel[2]]
      .map((v) => v.toString(16).padStart(2, "0"))
      .join("");
    backgroundColor.value = hex;
    setStatus(`Picked background color: ${hex} — click Save Set to apply.`);
  });

  frameWidth.addEventListener("input", drawCanvas);
  frameHeight.addEventListener("input", drawCanvas);

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
        imageHint.textContent = "Click on image to pick background color.";
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
  }

  function renderSprites() {
    spriteList.innerHTML = "";
    animList.innerHTML = "";
    if (!currentDefinition || !currentDefinition.sprites) {
      return;
    }
    Object.keys(currentDefinition.sprites).forEach((spriteId) => {
      const btn = document.createElement("button");
      btn.textContent = spriteId + (selectedSpriteId === spriteId ? " ✓" : "");
      btn.onclick = () => {
        selectedSpriteId = spriteId;
        selectedAnimId = null;
        renderSprites();
        renderAnims();
      };
      spriteList.appendChild(btn);
    });
    renderAnims();
  }

  function renderAnims() {
    animList.innerHTML = "";
    if (!selectedSpriteId || !currentDefinition?.sprites?.[selectedSpriteId]) {
      return;
    }
    const anims = currentDefinition.sprites[selectedSpriteId].anims || {};
    Object.keys(anims).forEach((animId) => {
      const btn = document.createElement("button");
      btn.textContent = `${animId} (${anims[animId].type}, ${anims[animId].speed}s)` + (selectedAnimId === animId ? " ✓" : "");
      btn.onclick = () => {
        selectedAnimId = animId;
        animSpeed.value = Number(anims[animId].speed || 0.5);
        animType.value = anims[animId].type || "loop";
        animFrames.value = (anims[animId].frames || []).join(", ");
        setStatus(`Editing animation ${animId}`);
      };
      animList.appendChild(btn);
    });
  }

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

  async function deleteSprite() {
    if (!selectedSet || !selectedSpriteId) return;
    await api(`/api/sprite-editor/sets/${selectedSet.scope}/${selectedSet.filename}/sprites/${selectedSpriteId}`, {
      method: "DELETE",
    });
    await selectSet(selectedSet);
  }

  async function deleteAnim() {
    if (!selectedSet || !selectedSpriteId || !selectedAnimId) return;
    await api(`/api/sprite-editor/sets/${selectedSet.scope}/${selectedSet.filename}/sprites/${selectedSpriteId}/anims/${selectedAnimId}`, {
      method: "DELETE",
    });
    await selectSet(selectedSet);
  }

  async function saveAnim() {
    if (!selectedSet || !selectedSpriteId || !selectedAnimId) return;
    const frames = String(animFrames.value || "")
      .split(",")
      .map((value) => value.trim())
      .filter((value) => value.length > 0);
    await api(`/api/sprite-editor/sets/${selectedSet.scope}/${selectedSet.filename}/sprites/${selectedSpriteId}/anims/${selectedAnimId}`, {
      method: "PUT",
      body: JSON.stringify({
        speed: Number(animSpeed.value || 0.5),
        type: animType.value || "loop",
        frames,
      }),
    });
    await selectSet(selectedSet);
  }

  document.getElementById("btnLoadSets").onclick = () => loadSets().catch((err) => setStatus(err.message));
  document.getElementById("btnClearBackground").onclick = () => {
    backgroundColor.value = "";
  };
  document.getElementById("btnSaveSet").onclick = () => saveSet().catch((err) => setStatus(err.message));
  document.getElementById("btnAddSprite").onclick = () => addSprite().catch((err) => setStatus(err.message));
  document.getElementById("btnAddAnim").onclick = () => addAnim().catch((err) => setStatus(err.message));
  document.getElementById("btnDeleteSprite").onclick = () => deleteSprite().catch((err) => setStatus(err.message));
  document.getElementById("btnDeleteAnim").onclick = () => deleteAnim().catch((err) => setStatus(err.message));
  document.getElementById("btnSaveAnim").onclick = () => saveAnim().catch((err) => setStatus(err.message));
})();
