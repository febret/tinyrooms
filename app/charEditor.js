// Character Editor Module
// Manages the character creation/editing interface

let characterEditorState = {
  mode: "closed",
  descriptorClasses: {},
  appearance: {},
  slots: [null, null, null, null],
  selectedSlot: -1,
  activeRequestId: null,
  batchRolling: false,
};

// DOM elements
let btnCharacterEditor;
let characterEditorPage;
let characterEditorDescriptors;
let characterEditorQueue;
let characterEditorSlots;
let characterEditorError;
let btnCharacterRoll;
let btnCharacterCancelRoll;
let btnCharacterSave;
let btnCharacterEditorClose;
let btnCharacterEditorDone;
let characterEditorInitialized = false;

// References to client globals (injected by initCharacterEditor)
let characterEditorSocket;
let characterEditorRestAuthToken;

function bindCharacterEditorDomElements() {
  btnCharacterEditor = document.getElementById("btnCharacterEditor");
  characterEditorPage = document.getElementById("characterEditorPage");
  characterEditorDescriptors = document.getElementById("characterEditorDescriptors");
  characterEditorQueue = document.getElementById("characterEditorQueue");
  characterEditorSlots = document.getElementById("characterEditorSlots");
  characterEditorError = document.getElementById("characterEditorError");
  btnCharacterRoll = document.getElementById("btnCharacterRoll");
  btnCharacterCancelRoll = document.getElementById("btnCharacterCancelRoll");
  btnCharacterSave = document.getElementById("btnCharacterSave");
  btnCharacterEditorClose = document.getElementById("btnCharacterEditorClose");
  btnCharacterEditorDone = document.getElementById("btnCharacterEditorDone");
  return !!(
    btnCharacterEditor &&
    characterEditorPage &&
    characterEditorDescriptors &&
    characterEditorQueue &&
    characterEditorSlots &&
    characterEditorError &&
    btnCharacterRoll &&
    btnCharacterCancelRoll &&
    btnCharacterSave &&
    btnCharacterEditorClose &&
    btnCharacterEditorDone
  );
}

function initCharacterEditor(clientSocket, clientRestAuthToken) {
  characterEditorSocket = clientSocket;
  characterEditorRestAuthToken = clientRestAuthToken;
  if (!bindCharacterEditorDomElements() || characterEditorInitialized) {
    return;
  }

  // Attach event listeners
  btnCharacterEditor.addEventListener("click", openCharacterEditor);
  btnCharacterEditorClose.addEventListener("click", closeCharacterEditor);
  btnCharacterEditorDone.addEventListener("click", closeCharacterEditor);
  btnCharacterRoll.addEventListener("click", startRollBatch);
  btnCharacterCancelRoll.addEventListener("click", cancelActiveRoll);
  btnCharacterSave.addEventListener("click", saveSelectedCharacterSprite);
  characterEditorInitialized = true;
}

function resetCharacterEditorState() {
  characterEditorState = {
    mode: "closed",
    descriptorClasses: {},
    appearance: {},
    slots: [null, null, null, null],
    selectedSlot: -1,
    activeRequestId: null,
    batchRolling: false,
  };
  if (!bindCharacterEditorDomElements()) {
    return;
  }
  renderCharacterEditor();
}

async function fetchJsonOrThrow(path, options = {}) {
  const headers = { ...(options.headers || {}) };
  if (characterEditorRestAuthToken) {
    headers["X-TR-Auth"] = characterEditorRestAuthToken;
  }
  const response = await fetch(path, { ...options, headers });
  const payload = await response.json();
  if (!response.ok || payload.ok === false) {
    throw new Error(payload.error || `request failed: ${response.status}`);
  }
  return payload;
}

async function openCharacterEditor() {
  characterEditorState.mode = "editing";
  characterEditorState.batchRolling = false;
  characterEditorError.textContent = "";
  characterEditorPage.style.display = "flex";
  renderCharacterEditor();
  try {
    const profile = await fetchJsonOrThrow("/api/char-editor/profile");
    characterEditorState.descriptorClasses = profile.descriptor_classes || {};
    characterEditorState.appearance = { ...(profile.char?.appearance || {}) };
    characterEditorState.slots = [null, null, null, null];
    const sprites = profile.sprites || [];
    for (let i = 0; i < 4 && i < sprites.length; i++) {
      characterEditorState.slots[i] = sprites[i];
    }
    characterEditorState.selectedSlot = -1;
    characterEditorState.activeRequestId = profile.queue?.active_request_id || null;
    if (characterEditorState.activeRequestId) {
      characterEditorState.mode = "rolling";
      pollCharacterRequest();
    }
    renderCharacterEditor(profile.queue || null);
  } catch (err) {
    characterEditorError.textContent = err.message;
    characterEditorState.mode = "editing";
    renderCharacterEditor();
  }
}

function closeCharacterEditor() {
  characterEditorState.batchRolling = false;
  characterEditorPage.style.display = "none";
  characterEditorState.mode = "closed";
}

function getDescriptorOptionId(option) {
  if (typeof option === "string") return option;
  return option.id || "";
}

function getDescriptorOptionLabel(option) {
  if (typeof option === "string") return option;
  return option.label || option.id || "";
}

function renderCharacterEditor(queueInfo = null) {
  if (!characterEditorDescriptors || !characterEditorQueue || !characterEditorSlots) {
    return;
  }
  const isGenerating = characterEditorState.mode === "rolling" || !!characterEditorState.activeRequestId;
  characterEditorDescriptors.innerHTML = "";
  for (const [descriptorKey, descriptorMeta] of Object.entries(characterEditorState.descriptorClasses)) {
    const section = document.createElement("div");
    section.className = "character-descriptor";
    const label = document.createElement("div");
    label.className = "character-descriptor-label";
    label.textContent = descriptorMeta.label || descriptorKey;
    section.appendChild(label);

    const optionsWrap = document.createElement("div");
    optionsWrap.className = "character-options";
    for (const option of (descriptorMeta.options || [])) {
      const optionId = getDescriptorOptionId(option);
      const optionLabel = getDescriptorOptionLabel(option);
      const button = document.createElement("button");
      button.type = "button";
      button.className = "character-option";
      if (descriptorMeta.type === "color") {
        button.classList.add("color-option");
        const swatch = document.createElement("span");
        swatch.className = "swatch";
        swatch.style.backgroundColor = option.swatch || optionId;
        button.appendChild(swatch);
        const txt = document.createElement("span");
        txt.textContent = optionLabel;
        button.appendChild(txt);
      } else {
        button.textContent = optionLabel;
      }
      if (characterEditorState.appearance[descriptorKey] === optionId) {
        button.classList.add("selected");
      }
      button.addEventListener("click", () => {
        characterEditorState.appearance[descriptorKey] = optionId;
        renderCharacterEditor(queueInfo);
      });
      optionsWrap.appendChild(button);
    }
    section.appendChild(optionsWrap);
    characterEditorDescriptors.appendChild(section);
  }

  characterEditorQueue.classList.toggle("generating", isGenerating);
  characterEditorQueue.textContent = "";
  if (queueInfo) {
    const ahead = queueInfo.items_ahead ?? 0;
    const queued = queueInfo.queued ?? 0;
    const running = queueInfo.running ?? 0;
    characterEditorQueue.textContent = `Queue: ${queued} queued, ${running} running. Items ahead of your request: ${ahead}`;
  }
  if (!queueInfo && characterEditorState.mode === "rolling") {
    characterEditorQueue.textContent = "Queue: preparing request status...";
  }

  characterEditorSlots.innerHTML = "";
  for (let i = 0; i < 4; i++) {
    const slot = document.createElement("div");
    slot.className = "character-slot";
    if (isGenerating && !characterEditorState.slots[i]) {
      slot.classList.add("generating");
    }
    if (i === characterEditorState.selectedSlot) {
      slot.classList.add("selected");
    }
    const sprite = characterEditorState.slots[i];
    if (sprite) {
      const img = document.createElement("img");
      img.src = sprite.sprite_url;
      img.alt = sprite.sprite_id || `sprite-${i + 1}`;
      slot.appendChild(img);
      const controls = document.createElement("div");
      const pick = document.createElement("button");
      pick.type = "button";
      pick.textContent = "Select";
      pick.addEventListener("click", async () => {
        await applyCharacterSpriteSelection(i, false);
      });
      controls.appendChild(pick);
      const discard = document.createElement("button");
      discard.type = "button";
      discard.textContent = "Discard";
      discard.addEventListener("click", async () => {
        await discardCharacterSlot(i);
      });
      controls.appendChild(discard);
      slot.appendChild(controls);
    } else {
      const empty = document.createElement("div");
      empty.className = "character-slot-empty";
      empty.textContent = "Empty";
      slot.appendChild(empty);
    }
    characterEditorSlots.appendChild(slot);
  }
}

function countFilledSlots() {
  return characterEditorState.slots.filter(slot => !!slot).length;
}

function firstEmptySlotIndex() {
  return characterEditorState.slots.findIndex(slot => !slot);
}

async function startRollBatch() {
  if (characterEditorState.activeRequestId) {
    return;
  }
  characterEditorError.textContent = "";
  characterEditorState.batchRolling = true;
  await submitNextRollIfNeeded();
}

async function submitNextRollIfNeeded() {
  if (!characterEditorState.batchRolling) {
    return;
  }
  if (characterEditorState.activeRequestId) {
    return;
  }
  if (countFilledSlots() >= 4) {
    characterEditorState.batchRolling = false;
    characterEditorState.mode = "slots_ready";
    renderCharacterEditor();
    return;
  }
  try {
    const payload = await fetchJsonOrThrow("/api/char-editor/requests", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ descriptors: characterEditorState.appearance }),
    });
    characterEditorState.activeRequestId = payload.request.request_id;
    characterEditorState.mode = "rolling";
    renderCharacterEditor(payload.request.queue || null);
    pollCharacterRequest();
  } catch (err) {
    characterEditorState.batchRolling = false;
    characterEditorState.mode = "editing";
    characterEditorError.textContent = err.message;
    renderCharacterEditor();
  }
}

async function pollCharacterRequest() {
  if (!characterEditorState.activeRequestId) {
    return;
  }
  let keepPolling = true;
  while (keepPolling && characterEditorState.activeRequestId) {
    try {
      const payload = await fetchJsonOrThrow(`/api/char-editor/requests/${characterEditorState.activeRequestId}`);
      const req = payload.request;
      renderCharacterEditor(req.queue || null);
      if (req.status === "queued" || req.status === "running") {
        await new Promise(resolve => setTimeout(resolve, 10000));
        continue;
      }
      if (req.status === "done") {
        const idx = firstEmptySlotIndex();
        if (idx >= 0) {
          characterEditorState.slots[idx] = {
            sprite_id: req.sprite_id,
            sprite_path: req.sprite_path,
            sprite_url: req.sprite_url,
          };
        }
      } else if (req.status === "failed") {
        characterEditorError.textContent = req.error || "sprite generation failed";
      } else if (req.status === "cancelled") {
        characterEditorError.textContent = "Active generation request was cancelled.";
      }
      characterEditorState.activeRequestId = null;
      keepPolling = false;
    } catch (err) {
      characterEditorError.textContent = err.message;
      characterEditorState.activeRequestId = null;
      characterEditorState.batchRolling = false;
      keepPolling = false;
    }
  }

  if (characterEditorState.batchRolling) {
    await submitNextRollIfNeeded();
  } else {
    characterEditorState.mode = countFilledSlots() > 0 ? "slots_ready" : "editing";
    renderCharacterEditor();
  }
}

async function cancelActiveRoll() {
  characterEditorState.batchRolling = false;
  if (!characterEditorState.activeRequestId) {
    return;
  }
  try {
    await fetchJsonOrThrow(`/api/char-editor/requests/${characterEditorState.activeRequestId}`, { method: "DELETE" });
  } catch (err) {
    characterEditorError.textContent = err.message;
  } finally {
    characterEditorState.activeRequestId = null;
    characterEditorState.mode = "editing";
    renderCharacterEditor();
  }
}

async function discardCharacterSlot(index) {
  const sprite = characterEditorState.slots[index];
  if (!sprite) {
    return;
  }
  try {
    await fetchJsonOrThrow(`/api/char-editor/sprites/${encodeURIComponent(sprite.sprite_id)}`, { method: "DELETE" });
    characterEditorState.slots[index] = null;
    if (characterEditorState.selectedSlot === index) {
      characterEditorState.selectedSlot = -1;
    }
    renderCharacterEditor();
  } catch (err) {
    characterEditorError.textContent = err.message;
  }
}

async function saveSelectedCharacterSprite() {
  const idx = characterEditorState.selectedSlot;
  if (idx < 0 || !characterEditorState.slots[idx]) {
    characterEditorError.textContent = "Select one generated sprite before saving.";
    return;
  }
  await applyCharacterSpriteSelection(idx, true);
}

async function applyCharacterSpriteSelection(index, closeOnSuccess = false) {
  const sprite = characterEditorState.slots[index];
  if (!sprite) {
    characterEditorError.textContent = "Selected slot is empty.";
    return;
  }
  characterEditorState.selectedSlot = index;
  try {
    await fetchJsonOrThrow(`/api/char-editor/sprites/${encodeURIComponent(sprite.sprite_id)}/select`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ descriptors: characterEditorState.appearance }),
    });
    characterEditorError.textContent = "";
    renderCharacterEditor();
    if (closeOnSuccess) {
      closeCharacterEditor();
    }
  } catch (err) {
    characterEditorError.textContent = err.message;
  }
}
