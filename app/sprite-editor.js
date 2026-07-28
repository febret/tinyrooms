(function () {
  let availableSets = [];
  let selectedSet = null;
  let selectedSpriteId = null;
  let selectedAnimId = null;
  let currentDefinition = null;
  let loadedImage = null;
  let animFrames = [];
  let isDirty = false;
  let spriteNameQuery = "";
  let spriteTagFilter = "";
  let browserTab = "sets";
  let globalSpriteQuery = "";
  let globalSpriteTagFilter = "";
  let spriteCatalog = [];
  let spriteCatalogLoading = false;
  const spriteCatalogImageCache = new Map();

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
  const spriteScale = document.getElementById("spriteScale");
  const backgroundColor = document.getElementById("backgroundColor");
  const statusBox = document.getElementById("statusBox");
  const animSpeed = document.getElementById("animSpeed");
  const animType = document.getElementById("animType");
  const animFrameStrip = document.getElementById("animFrameStrip");
  const animFramesHint = document.getElementById("animFramesHint");
  const spriteSearchInput = document.getElementById("spriteSearchInput");
  const spriteTagFilterSelect = document.getElementById("spriteTagFilter");
  const spriteTagEditor = document.getElementById("spriteTagEditor");
  const btnSetBrowserTab = document.getElementById("btnSetBrowserTab");
  const btnSpriteBrowserTab = document.getElementById("btnSpriteBrowserTab");
  const setBrowserPane = document.getElementById("setBrowserPane");
  const spriteBrowserPane = document.getElementById("spriteBrowserPane");
  const globalSpriteSearchInput = document.getElementById("globalSpriteSearchInput");
  const globalSpriteTagFilterSelect = document.getElementById("globalSpriteTagFilter");
  const globalSpriteBrowseStatus = document.getElementById("globalSpriteBrowseStatus");
  const globalSpriteGrid = document.getElementById("globalSpriteGrid");
  const btnSaveSet = document.getElementById("btnSaveSet");
  const THUMB_SIZE = 40;
  const SPRITE_TAG_OPTIONS = ["avatar", "peep", "object", "item", "container", "consumable"];

  function setStatus(text, isError = false) {
    statusBox.textContent = text || "";
    statusBox.style.color = isError ? "#f44" : "#4f4";
  }

  function setKey(setDef) {
    return `${setDef?.scope || ""}:${setDef?.filename || ""}`;
  }

  function fw() {
    return Math.max(1, Number(frameWidth.value) || 32);
  }

  function fh() {
    return Math.max(1, Number(frameHeight.value) || 32);
  }

  function scaleValue() {
    return Math.max(0.1, Number(spriteScale.value) || 1.0);
  }

  function updateHeader() {
    if (!selectedSet) {
      setTitle.textContent = "No set selected";
      return;
    }
    setTitle.textContent = `${selectedSet.scope}:${selectedSet.filename}${isDirty ? " *" : ""}`;
  }

  function setDirty(value) {
    isDirty = Boolean(value);
    btnSaveSet.disabled = !selectedSet || !currentDefinition;
    btnSaveSet.textContent = isDirty ? "Save *" : "Save";
    updateHeader();
  }

  function markDirty(statusText = "") {
    setDirty(true);
    if (statusText) setStatus(statusText);
  }

  function parseFrameToken(token) {
    const parts = String(token || "0x0").split("x");
    return { col: parseInt(parts[0], 10) || 0, row: parseInt(parts[1], 10) || 0 };
  }

  function normalizeSpriteTags(spriteDoc) {
    if (!spriteDoc || typeof spriteDoc !== "object") return [];
    const rawTags = Array.isArray(spriteDoc.tags) ? spriteDoc.tags : [];
    const tags = [];
    const seen = new Set();
    rawTags.forEach((rawTag) => {
      const tag = String(rawTag || "").trim().toLowerCase();
      if (!tag || seen.has(tag)) return;
      seen.add(tag);
      tags.push(tag);
    });
    spriteDoc.tags = tags;
    return tags;
  }

  function spriteMatchesFilters(spriteId, spriteDoc) {
    const tags = normalizeSpriteTags(spriteDoc);
    if (spriteTagFilter && !tags.includes(spriteTagFilter)) return false;
    if (!spriteNameQuery) return true;
    const q = spriteNameQuery.toLowerCase();
    return String(spriteId || "").toLowerCase().includes(q) || tags.some((tag) => tag.includes(q));
  }

  function renderSpriteTagEditor() {
    spriteTagEditor.innerHTML = "";
    const spriteDoc = getSelectedSpriteDoc();
    if (!spriteDoc) {
      const empty = document.createElement("div");
      empty.className = "tag-editor-empty";
      empty.textContent = "Select a sprite to edit tags.";
      spriteTagEditor.appendChild(empty);
      return;
    }
    const selectedTags = normalizeSpriteTags(spriteDoc);
    for (const tag of SPRITE_TAG_OPTIONS) {
      const label = document.createElement("label");
      label.className = "tag-option";
      const checkbox = document.createElement("input");
      checkbox.type = "checkbox";
      checkbox.checked = selectedTags.includes(tag);
      checkbox.addEventListener("change", () => {
        const nextTags = new Set(normalizeSpriteTags(spriteDoc));
        if (checkbox.checked) {
          nextTags.add(tag);
        } else {
          nextTags.delete(tag);
        }
        spriteDoc.tags = [...nextTags];
        renderSprites();
        renderSpriteTagEditor();
        markDirty(`Updated tags for "${selectedSpriteId}".`);
      });
      label.appendChild(checkbox);
      const text = document.createElement("span");
      text.textContent = tag;
      label.appendChild(text);
      spriteTagEditor.appendChild(label);
    }
  }

  function setBrowserTab(nextTab) {
    browserTab = nextTab === "sprites" ? "sprites" : "sets";
    const setsActive = browserTab === "sets";
    btnSetBrowserTab.classList.toggle("browser-tab-active", setsActive);
    btnSpriteBrowserTab.classList.toggle("browser-tab-active", !setsActive);
    setBrowserPane.hidden = !setsActive;
    spriteBrowserPane.hidden = setsActive;
    if (!setsActive) {
      ensureSpriteCatalog().catch((err) => setStatus(err.message, true));
    }
  }

  function invalidateSpriteCatalog() {
    spriteCatalog = [];
    spriteCatalogLoading = false;
    spriteCatalogImageCache.clear();
    globalSpriteBrowseStatus.textContent = "";
    globalSpriteGrid.innerHTML = "";
  }

  function normalizeTagsList(rawTags) {
    const tags = [];
    const seen = new Set();
    (Array.isArray(rawTags) ? rawTags : []).forEach((rawTag) => {
      const tag = String(rawTag || "").trim().toLowerCase();
      if (!tag || seen.has(tag)) return;
      seen.add(tag);
      tags.push(tag);
    });
    return tags;
  }

  function spriteCatalogMatchesFilters(entry) {
    if (globalSpriteTagFilter && !entry.tags.includes(globalSpriteTagFilter)) return false;
    if (!globalSpriteQuery) return true;
    const q = globalSpriteQuery.toLowerCase();
    return (
      entry.spriteId.toLowerCase().includes(q)
      || entry.filename.toLowerCase().includes(q)
      || entry.tags.some((tag) => tag.includes(q))
    );
  }

  function getCatalogImage(imageUrl) {
    if (!imageUrl) return Promise.resolve(null);
    if (!spriteCatalogImageCache.has(imageUrl)) {
      spriteCatalogImageCache.set(
        imageUrl,
        loadImage(imageUrl).catch(() => null),
      );
    }
    return spriteCatalogImageCache.get(imageUrl);
  }

  async function buildSpriteCatalog() {
    const nextCatalog = [];
    for (const setDef of availableSets) {
      if (!setDef?.has_yaml) continue;
      try {
        const payload = await editorApi(`/api/sprite-editor/sets/${setDef.scope}/${setDef.filename}`);
        const definition = payload.definition;
        if (!definition?.sprites) continue;
        for (const [spriteId, spriteDoc] of Object.entries(definition.sprites)) {
          const tags = normalizeTagsList(spriteDoc?.tags);
          nextCatalog.push({
            scope: setDef.scope,
            filename: setDef.filename,
            spriteId,
            tags,
            imageUrl: payload.set.image_url || "",
            backgroundColor: definition.background_color || "",
            frameWidth: Number(definition.frame_width) || 32,
            frameHeight: Number(definition.frame_height) || 32,
            thumbToken: getSpriteThumbToken(spriteDoc),
            animCount: Object.keys(spriteDoc?.anims || {}).length,
          });
        }
      } catch {
        // skip invalid/unloadable sets in the browser catalog
      }
    }
    spriteCatalog = nextCatalog;
  }

  function renderSpriteCatalogGrid() {
    globalSpriteGrid.innerHTML = "";
    const visible = spriteCatalog.filter(spriteCatalogMatchesFilters);
    globalSpriteBrowseStatus.textContent = spriteCatalogLoading
      ? "Loading sprites..."
      : `${visible.length} / ${spriteCatalog.length} sprite(s)`;

    if (!spriteCatalogLoading && visible.length === 0) {
      const empty = document.createElement("div");
      empty.className = "tag-editor-empty";
      empty.textContent = "No sprites match the current filters.";
      globalSpriteGrid.appendChild(empty);
      return;
    }

    visible.forEach((entry) => {
      const btn = document.createElement("button");
      btn.className = "list-item-button sprite-grid-item";
      btn.title = `${entry.scope}:${entry.filename}/${entry.spriteId}`;

      const canvas = document.createElement("canvas");
      canvas.width = 48;
      canvas.height = 48;
      canvas.className = "sprite-grid-thumb";
      btn.appendChild(canvas);
      const label = document.createElement("div");
      label.className = "sprite-grid-label";
      label.textContent = entry.spriteId;
      btn.appendChild(label);
      const meta = document.createElement("div");
      meta.className = "set-grid-meta";
      meta.textContent = `${entry.scope}:${entry.filename}`;
      btn.appendChild(meta);

      const { col, row } = parseFrameToken(entry.thumbToken);
      getCatalogImage(entry.imageUrl).then((img) => {
        if (!img) {
          canvas.classList.add("thumb-placeholder");
          return;
        }
        drawSpriteThumb(
          canvas,
          img,
          col * entry.frameWidth,
          row * entry.frameHeight,
          entry.frameWidth,
          entry.frameHeight,
          parseBgColor(entry.backgroundColor),
        );
      });

      btn.addEventListener("click", () => {
        openCatalogSprite(entry).catch((err) => setStatus(err.message, true));
      });
      globalSpriteGrid.appendChild(btn);
    });
  }

  async function ensureSpriteCatalog() {
    if (spriteCatalogLoading) return;
    if (spriteCatalog.length > 0) {
      renderSpriteCatalogGrid();
      return;
    }
    spriteCatalogLoading = true;
    renderSpriteCatalogGrid();
    try {
      await buildSpriteCatalog();
    } finally {
      spriteCatalogLoading = false;
      renderSpriteCatalogGrid();
    }
  }

  function getBgRgbForThumbs() {
    const color = String(backgroundColor.value || currentDefinition?.background_color || "").trim();
    return parseBgColor(color);
  }

  function makeThumbDataUrl(token, size = THUMB_SIZE) {
    if (!loadedImage) return "";
    const { col, row } = parseFrameToken(token);
    const offscreen = document.createElement("canvas");
    offscreen.width = size;
    offscreen.height = size;
    drawSpriteThumb(
      offscreen,
      loadedImage,
      col * fw(),
      row * fh(),
      fw(),
      fh(),
      getBgRgbForThumbs(),
    );
    return offscreen.toDataURL();
  }

  function createThumbImage(token, className = "thumb-image") {
    const src = makeThumbDataUrl(token);
    const img = document.createElement("img");
    img.className = className;
    img.width = THUMB_SIZE;
    img.height = THUMB_SIZE;
    img.alt = token;
    if (src) {
      img.src = src;
    } else {
      img.classList.add("thumb-placeholder");
    }
    return img;
  }

  function getSpriteThumbToken(spriteDoc) {
    const anims = spriteDoc?.anims || {};
    const frontAnim = anims.front;
    if (Array.isArray(frontAnim?.frames) && frontAnim.frames.length > 0) return String(frontAnim.frames[0]);
    for (const anim of Object.values(anims)) {
      if (Array.isArray(anim?.frames) && anim.frames.length > 0) return String(anim.frames[0]);
    }
    return String(spriteDoc?.default_frame || "0x0");
  }

  function getAnimThumbToken(animDoc, spriteDoc) {
    if (Array.isArray(animDoc?.frames) && animDoc.frames.length > 0) return String(animDoc.frames[0]);
    return String(spriteDoc?.default_frame || "0x0");
  }

  function drawCanvas() {
    if (!loadedImage) return;
    spriteCanvas.width = loadedImage.naturalWidth;
    spriteCanvas.height = loadedImage.naturalHeight;
    ctx.drawImage(loadedImage, 0, 0);

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

  function syncSetDefinitionFromInputs() {
    if (!currentDefinition) return;
    currentDefinition.frame_width = fw();
    currentDefinition.frame_height = fh();
    currentDefinition.scale = scaleValue();
    const bg = String(backgroundColor.value || "").trim();
    currentDefinition.background_color = bg.length ? bg : null;
  }

  function getSelectedSpriteDoc() {
    return currentDefinition?.sprites?.[selectedSpriteId] || null;
  }

  function getSelectedAnimDoc() {
    return getSelectedSpriteDoc()?.anims?.[selectedAnimId] || null;
  }

  function commitAnimFramesToDefinition() {
    const anim = getSelectedAnimDoc();
    if (!anim) return;
    anim.frames = [...animFrames];
  }

  function renderSetList() {
    setList.innerHTML = "";
    for (const item of availableSets) {
      const btn = document.createElement("button");
      btn.className = "list-item-button set-grid-item" + (setKey(item) === setKey(selectedSet) ? " list-item-selected" : "");
      btn.title = `${item.scope}:${item.filename} — ${item.has_yaml ? "definition present" : "no yaml yet"}`;
      const preview = document.createElement("img");
      preview.className = "set-preview set-grid-thumb";
      preview.alt = `${item.filename} preview`;
      if (item.image_url) {
        preview.src = item.image_url;
      } else {
        preview.classList.add("thumb-placeholder");
      }
      btn.appendChild(preview);

      const title = document.createElement("div");
      title.className = "set-grid-label";
      title.textContent = item.filename;
      btn.appendChild(title);

      const sub = document.createElement("div");
      sub.className = "set-grid-meta";
      sub.textContent = item.scope;
      btn.appendChild(sub);

      btn.addEventListener("click", () => {
        attemptSelectSet(item).catch((err) => setStatus(err.message, true));
      });
      setList.appendChild(btn);
    }
  }

  function renderSprites() {
    spriteList.innerHTML = "";
    animList.innerHTML = "";
    if (!currentDefinition?.sprites) {
      renderSpriteTagEditor();
      return;
    }

    let renderedCount = 0;
    for (const spriteId of Object.keys(currentDefinition.sprites)) {
      const spriteDoc = currentDefinition.sprites[spriteId];
      if (!spriteMatchesFilters(spriteId, spriteDoc)) continue;
      renderedCount += 1;
      const tags = normalizeSpriteTags(spriteDoc);
      const btn = document.createElement("button");
      btn.className = "list-item-button sprite-grid-item" + (selectedSpriteId === spriteId ? " list-item-selected" : "");
      btn.title = `${spriteId} — ${(spriteDoc?.anims ? Object.keys(spriteDoc.anims).length : 0)} anim(s) — tags: ${tags.length > 0 ? tags.join(", ") : "none"}`;

      const thumb = createThumbImage(getSpriteThumbToken(spriteDoc));
      thumb.classList.add("sprite-grid-thumb");
      btn.appendChild(thumb);

      const label = document.createElement("div");
      label.className = "sprite-grid-label";
      label.textContent = spriteId;
      btn.appendChild(label);
      btn.addEventListener("click", () => {
        selectedSpriteId = spriteId;
        selectedAnimId = null;
        animFrames = [];
        renderSprites();
        renderAnims();
        renderFrameStrip();
      });
      spriteList.appendChild(btn);
    }

    if (renderedCount === 0) {
      const empty = document.createElement("div");
      empty.className = "tag-editor-empty";
      empty.textContent = "No sprites match the current name/tag filter.";
      spriteList.appendChild(empty);
    }

    if (selectedSpriteId && !currentDefinition.sprites[selectedSpriteId]) {
      selectedSpriteId = null;
      selectedAnimId = null;
      animFrames = [];
    }

    renderSpriteTagEditor();
    renderAnims();
  }

  function renderAnims() {
    animList.innerHTML = "";
    const spriteDoc = getSelectedSpriteDoc();
    if (!spriteDoc) return;

    const anims = spriteDoc.anims || {};
    for (const animId of Object.keys(anims)) {
      const anim = anims[animId];
      const btn = document.createElement("button");
      btn.className = "list-item-button" + (selectedAnimId === animId ? " list-item-selected" : "");

      const row = document.createElement("div");
      row.className = "list-item-row";
      row.appendChild(createThumbImage(getAnimThumbToken(anim, spriteDoc)));

      const textWrap = document.createElement("div");
      textWrap.className = "list-item-text";
      const title = document.createElement("div");
      title.className = "list-item-title";
      title.textContent = animId;
      textWrap.appendChild(title);
      const sub = document.createElement("div");
      sub.className = "list-item-subtitle";
      sub.textContent = `${anim.type || "loop"}, ${(Number(anim.speed) || 0.2)}s, ${(anim.frames || []).length} fr`;
      textWrap.appendChild(sub);
      row.appendChild(textWrap);

      btn.appendChild(row);
      btn.addEventListener("click", () => {
        selectedAnimId = animId;
        animSpeed.value = Number(anim.speed || 0.2);
        animType.value = anim.type || "loop";
        animFrames = [...(anim.frames || [])];
        renderAnims();
        renderFrameStrip();
        setStatus(`Editing animation "${animId}". Click the image to append frames.`);
      });
      animList.appendChild(btn);
    }
  }

  function renderFrameStrip() {
    animFrameStrip.innerHTML = "";
    if (!selectedAnimId) {
      animFramesHint.textContent = "";
      return;
    }

    animFramesHint.textContent = `${animFrames.length} frame(s)`;

    animFrames.forEach((token, index) => {
      const cell = document.createElement("div");
      cell.className = "frame-cell";
      cell.title = `Frame ${index}: ${token}`;
      cell.appendChild(createThumbImage(token, "frame-thumb-image"));

      const label = document.createElement("div");
      label.className = "frame-label";
      label.textContent = token;
      cell.appendChild(label);
      animFrameStrip.appendChild(cell);
    });
  }

  async function loadSets() {
    const payload = await editorApi("/api/sprite-editor/sets");
    availableSets = payload.sets || [];
    invalidateSpriteCatalog();
    renderSetList();
    if (browserTab === "sprites") {
      ensureSpriteCatalog().catch((err) => setStatus(err.message, true));
    }
    setStatus(`Loaded ${availableSets.length} sprite sets.`);
  }

  async function maybeSaveBeforeSwitch(nextSet) {
    if (!selectedSet || !isDirty) return true;
    if (setKey(nextSet) === setKey(selectedSet)) return true;

    const shouldSave = window.confirm(
      "This spriteset has unsaved changes. Save before switching to another spriteset?",
    );
    if (!shouldSave) return true;

    try {
      await saveSet();
      return true;
    } catch (err) {
      setStatus(err.message, true);
      return false;
    }
  }

  async function attemptSelectSet(setDef, targetSpriteId = null) {
    const ok = await maybeSaveBeforeSwitch(setDef);
    if (!ok) return;
    await selectSet(setDef, targetSpriteId);
  }

  async function selectSet(setDef, targetSpriteId = null) {
    selectedSet = setDef;
    selectedSpriteId = null;
    selectedAnimId = null;
    animFrames = [];
    loadedImage = null;
    currentDefinition = null;
    spriteCanvas.width = 0;
    spriteCanvas.height = 0;
    imageHint.textContent = "";
    setMeta.textContent = "";
    setDirty(false);
    updateHeader();
    renderSetList();

    const payload = await editorApi(`/api/sprite-editor/sets/${setDef.scope}/${setDef.filename}`);
    currentDefinition = payload.definition;
    setMeta.textContent = payload.set.yaml_error || "";

    if (!currentDefinition) {
      await editorApi(`/api/sprite-editor/sets/${setDef.scope}/${setDef.filename}/create-definition`, {
        method: "POST",
        body: JSON.stringify({ frame_width: 32, frame_height: 32 }),
      });
      await selectSet(setDef, targetSpriteId);
      return;
    }

    frameWidth.value = currentDefinition.frame_width || 32;
    frameHeight.value = currentDefinition.frame_height || 32;
    spriteScale.value = Number(currentDefinition.scale || 1.0);
    backgroundColor.value = currentDefinition.background_color || "";

    const imageUrl = payload.set.image_url || "";
    if (imageUrl) {
      try {
        loadedImage = await loadImage(imageUrl);
        drawCanvas();
        imageHint.textContent = "Click image cells to pick background color or append animation frames.";
      } catch (err) {
        setStatus(err.message, true);
      }
    }

    renderSprites();
    if (targetSpriteId && currentDefinition.sprites?.[targetSpriteId]) {
      selectedSpriteId = targetSpriteId;
      selectedAnimId = null;
      animFrames = [];
      renderSprites();
      setStatus(`Opened ${setDef.scope}:${setDef.filename}/${targetSpriteId}.`);
    }
    renderFrameStrip();
    setDirty(false);
    renderSetList();
  }

  async function openCatalogSprite(entry) {
    const nextSet = availableSets.find((item) => item.scope === entry.scope && item.filename === entry.filename);
    if (!nextSet) {
      setStatus("Selected sprite set is no longer available. Reload sets.", true);
      return;
    }
    spriteNameQuery = "";
    spriteTagFilter = "";
    spriteSearchInput.value = "";
    spriteTagFilterSelect.value = "";
    await attemptSelectSet(nextSet, entry.spriteId);
  }

  async function saveSet() {
    if (!selectedSet || !currentDefinition) return;
    syncSetDefinitionFromInputs();
    commitAnimFramesToDefinition();
    await editorApi(`/api/sprite-editor/sets/${selectedSet.scope}/${selectedSet.filename}`, {
      method: "PUT",
      body: JSON.stringify({ definition: currentDefinition }),
    });
    invalidateSpriteCatalog();
    if (browserTab === "sprites") {
      ensureSpriteCatalog().catch((err) => setStatus(err.message, true));
    }
    setDirty(false);
    setStatus("Saved spriteset.");
  }

  function addSprite() {
    if (!currentDefinition) return;
    const spriteId = document.getElementById("newSpriteId").value.trim();
    if (!spriteId) {
      setStatus("Enter a sprite id.", true);
      return;
    }
    if (currentDefinition.sprites[spriteId]) {
      setStatus(`Sprite "${spriteId}" already exists.`, true);
      return;
    }
    currentDefinition.sprites[spriteId] = { default_frame: "0x0", tags: [], anims: {} };
    selectedSpriteId = spriteId;
    selectedAnimId = null;
    animFrames = [];
    document.getElementById("newSpriteId").value = "";
    renderSprites();
    renderFrameStrip();
    markDirty(`Added sprite "${spriteId}".`);
  }

  function addSpriteFromFrame(spriteId, frameToken) {
    if (!currentDefinition) return false;
    const id = String(spriteId || "").trim();
    if (!id) {
      setStatus("Enter a sprite id.", true);
      return false;
    }
    if (currentDefinition.sprites[id]) {
      setStatus(`Sprite "${id}" already exists.`, true);
      return false;
    }
    currentDefinition.sprites[id] = {
      default_frame: frameToken,
      tags: [],
      anims: {
        front: {
          speed: 0.2,
          type: "loop",
          frames: [frameToken],
        },
      },
    };
    selectedSpriteId = id;
    selectedAnimId = "front";
    animFrames = [frameToken];
    animSpeed.value = 0.2;
    animType.value = "loop";
    document.getElementById("newSpriteId").value = "";
    renderSprites();
    renderAnims();
    renderFrameStrip();
    markDirty(`Added sprite "${id}" at ${frameToken} with default 'front' animation.`);
    return true;
  }

  function deleteSprite() {
    if (!currentDefinition || !selectedSpriteId) return;
    const spriteIds = Object.keys(currentDefinition.sprites || {});
    if (spriteIds.length <= 1) {
      setStatus("Sprite set must contain at least one sprite.", true);
      return;
    }
    delete currentDefinition.sprites[selectedSpriteId];
    selectedSpriteId = null;
    selectedAnimId = null;
    animFrames = [];
    renderSprites();
    renderFrameStrip();
    markDirty("Deleted sprite.");
  }

  function renameSprite() {
    if (!currentDefinition || !selectedSpriteId) return;
    const newId = document.getElementById("renameSpriteId").value.trim();
    if (!newId) {
      setStatus("Enter a new sprite id to rename to.", true);
      return;
    }
    if (newId === selectedSpriteId) return;
    const sprites = currentDefinition.sprites || {};
    if (newId in sprites) {
      setStatus(`Sprite "${newId}" already exists.`, true);
      return;
    }
    currentDefinition.sprites = renameKeyInObject(sprites, selectedSpriteId, newId);
    selectedSpriteId = newId;
    document.getElementById("renameSpriteId").value = "";
    renderSprites();
    markDirty(`Renamed sprite to "${newId}".`);
  }

  function addAnim() {
    const spriteDoc = getSelectedSpriteDoc();
    if (!spriteDoc) return;
    const animId = document.getElementById("newAnimId").value.trim();
    if (!animId) {
      setStatus("Enter an animation id.", true);
      return;
    }
    if (spriteDoc.anims?.[animId]) {
      setStatus(`Animation "${animId}" already exists.`, true);
      return;
    }
    spriteDoc.anims = spriteDoc.anims || {};
    spriteDoc.anims[animId] = { speed: 0.2, type: "loop", frames: ["0x0"] };
    selectedAnimId = animId;
    animFrames = ["0x0"];
    animSpeed.value = 0.2;
    animType.value = "loop";
    document.getElementById("newAnimId").value = "";
    renderAnims();
    renderFrameStrip();
    markDirty(`Added animation "${animId}".`);
  }

  function deleteAnim() {
    const spriteDoc = getSelectedSpriteDoc();
    if (!spriteDoc || !selectedAnimId) return;
    delete spriteDoc.anims[selectedAnimId];
    selectedAnimId = null;
    animFrames = [];
    renderAnims();
    renderFrameStrip();
    markDirty("Deleted animation.");
  }

  function renameAnim() {
    const spriteDoc = getSelectedSpriteDoc();
    if (!spriteDoc || !selectedAnimId) return;
    const newId = document.getElementById("renameAnimId").value.trim();
    if (!newId) {
      setStatus("Enter a new animation id to rename to.", true);
      return;
    }
    if (newId === selectedAnimId) return;
    const anims = spriteDoc.anims || {};
    if (newId in anims) {
      setStatus(`Animation "${newId}" already exists.`, true);
      return;
    }
    spriteDoc.anims = renameKeyInObject(anims, selectedAnimId, newId);
    selectedAnimId = newId;
    document.getElementById("renameAnimId").value = "";
    renderAnims();
    markDirty(`Renamed animation to "${newId}".`);
  }

  spriteCanvas.addEventListener("click", (e) => {
    if (!loadedImage) return;
    const rect = spriteCanvas.getBoundingClientRect();
    const scaleX = spriteCanvas.width / rect.width;
    const scaleY = spriteCanvas.height / rect.height;
    const px = Math.floor((e.clientX - rect.left) * scaleX);
    const py = Math.floor((e.clientY - rect.top) * scaleY);

    const col = Math.floor(px / fw());
    const row = Math.floor(py / fh());
    const token = `${col}x${row}`;
    const newSpriteId = document.getElementById("newSpriteId").value.trim();

    if (newSpriteId) {
      addSpriteFromFrame(newSpriteId, token);
      return;
    }

    if (selectedAnimId) {
      animFrames.push(token);
      commitAnimFramesToDefinition();
      renderFrameStrip();
      renderAnims();
      markDirty(`Appended frame ${token} to "${selectedAnimId}".`);
      return;
    }

    const pixel = ctx.getImageData(px, py, 1, 1).data;
    const hex = "#" + [pixel[0], pixel[1], pixel[2]].map((v) => v.toString(16).padStart(2, "0")).join("");
    backgroundColor.value = hex;
    drawCanvas();
    renderSprites();
    renderAnims();
    renderFrameStrip();
    markDirty(`Picked background color: ${hex}`);
  });

  frameWidth.addEventListener("input", () => {
    syncSetDefinitionFromInputs();
    drawCanvas();
    renderSprites();
    renderAnims();
    renderFrameStrip();
    markDirty();
  });

  frameHeight.addEventListener("input", () => {
    syncSetDefinitionFromInputs();
    drawCanvas();
    renderSprites();
    renderAnims();
    renderFrameStrip();
    markDirty();
  });

  spriteScale.addEventListener("input", () => {
    syncSetDefinitionFromInputs();
    markDirty("Updated sprite scale.");
  });

  backgroundColor.addEventListener("change", () => {
    syncSetDefinitionFromInputs();
    renderSprites();
    renderAnims();
    renderFrameStrip();
    markDirty("Updated background color.");
  });

  animSpeed.addEventListener("change", () => {
    const anim = getSelectedAnimDoc();
    if (!anim) return;
    const value = Number(animSpeed.value || 0.2);
    anim.speed = value;
    renderAnims();
    markDirty(`Updated animation speed for "${selectedAnimId}".`);
  });

  animType.addEventListener("change", () => {
    const anim = getSelectedAnimDoc();
    if (!anim) return;
    anim.type = animType.value || "loop";
    renderAnims();
    markDirty(`Updated animation type for "${selectedAnimId}".`);
  });

  document.getElementById("btnRemoveFrame").onclick = () => {
    if (!selectedAnimId) {
      setStatus("Select an animation first.", true);
      return;
    }
    if (animFrames.length === 0) {
      setStatus("No frame to remove.", true);
      return;
    }
    const removed = animFrames.pop();
    commitAnimFramesToDefinition();
    renderFrameStrip();
    renderAnims();
    markDirty(`Removed last frame (${removed}).`);
  };

  document.getElementById("btnLoadSets").onclick = () => loadSets().catch((err) => setStatus(err.message, true));
  document.getElementById("btnClearBackground").onclick = () => {
    backgroundColor.value = "";
    syncSetDefinitionFromInputs();
    renderSprites();
    renderAnims();
    renderFrameStrip();
    markDirty("Cleared background color.");
  };
  document.getElementById("btnSaveSet").onclick = () => saveSet().catch((err) => setStatus(err.message, true));
  document.getElementById("btnAddSprite").onclick = () => addSprite();
  document.getElementById("btnRenameSprite").onclick = () => renameSprite();
  document.getElementById("btnAddAnim").onclick = () => addAnim();
  document.getElementById("btnRenameAnim").onclick = () => renameAnim();
  document.getElementById("btnDeleteSprite").onclick = () => deleteSprite();
  document.getElementById("btnDeleteAnim").onclick = () => deleteAnim();

  spriteSearchInput.addEventListener("input", () => {
    spriteNameQuery = String(spriteSearchInput.value || "").trim();
    renderSprites();
  });

  spriteTagFilterSelect.addEventListener("change", () => {
    spriteTagFilter = String(spriteTagFilterSelect.value || "").trim().toLowerCase();
    renderSprites();
  });

  btnSetBrowserTab.addEventListener("click", () => setBrowserTab("sets"));
  btnSpriteBrowserTab.addEventListener("click", () => setBrowserTab("sprites"));

  globalSpriteSearchInput.addEventListener("input", () => {
    globalSpriteQuery = String(globalSpriteSearchInput.value || "").trim();
    renderSpriteCatalogGrid();
  });

  globalSpriteTagFilterSelect.addEventListener("change", () => {
    globalSpriteTagFilter = String(globalSpriteTagFilterSelect.value || "").trim().toLowerCase();
    renderSpriteCatalogGrid();
  });

  setBrowserTab("sets");
  renderSpriteTagEditor();

  window.addEventListener("beforeunload", (event) => {
    if (!isDirty) return;
    event.preventDefault();
    event.returnValue = "";
  });
})();
