let objectEditorState = {
  mode: "closed",
  description: "",
  slots: [null, null, null, null],
  selectedSlot: -1,
  activeRequestId: null,
  batchRolling: false,
};

let objectCreatorPage;
let objectCreatorDescription;
let objectCreatorQueue;
let objectCreatorSlots;
let objectCreatorError;
let btnObjectCreatorRoll;
let btnObjectCreatorCancelRoll;
let btnObjectCreatorCreate;
let btnObjectCreatorClose;
let btnObjectCreatorDone;
let objectEditorInitialized = false;

let objectEditorSocket;
let objectEditorRestAuthToken;

function bindObjectEditorDomElements() {
  objectCreatorPage = document.getElementById("objectCreatorPage");
  objectCreatorDescription = document.getElementById("objectCreatorDescription");
  objectCreatorQueue = document.getElementById("objectCreatorQueue");
  objectCreatorSlots = document.getElementById("objectCreatorSlots");
  objectCreatorError = document.getElementById("objectCreatorError");
  btnObjectCreatorRoll = document.getElementById("btnObjectCreatorRoll");
  btnObjectCreatorCancelRoll = document.getElementById("btnObjectCreatorCancelRoll");
  btnObjectCreatorCreate = document.getElementById("btnObjectCreatorCreate");
  btnObjectCreatorClose = document.getElementById("btnObjectCreatorClose");
  btnObjectCreatorDone = document.getElementById("btnObjectCreatorDone");
  return !!(
    objectCreatorPage &&
    objectCreatorDescription &&
    objectCreatorQueue &&
    objectCreatorSlots &&
    objectCreatorError &&
    btnObjectCreatorRoll &&
    btnObjectCreatorCancelRoll &&
    btnObjectCreatorCreate &&
    btnObjectCreatorClose &&
    btnObjectCreatorDone
  );
}

function initObjectEditor(clientSocket, clientRestAuthToken) {
  objectEditorSocket = clientSocket;
  objectEditorRestAuthToken = clientRestAuthToken;
  if (!bindObjectEditorDomElements() || objectEditorInitialized) {
    return;
  }
  btnObjectCreatorRoll.addEventListener("click", startObjectRollBatch);
  btnObjectCreatorCancelRoll.addEventListener("click", cancelActiveObjectRoll);
  btnObjectCreatorCreate.addEventListener("click", createThingFromSelectedSlot);
  btnObjectCreatorClose.addEventListener("click", closeObjectCreator);
  btnObjectCreatorDone.addEventListener("click", createThingFromSelectedSlot);
  objectCreatorDescription.addEventListener("input", () => {
    objectEditorState.description = objectCreatorDescription.value;
  });
  objectEditorInitialized = true;
}

function resetObjectEditorState() {
  objectEditorState = {
    mode: "closed",
    description: "",
    slots: [null, null, null, null],
    selectedSlot: -1,
    activeRequestId: null,
    batchRolling: false,
  };
  if (!bindObjectEditorDomElements()) {
    return;
  }
  objectCreatorDescription.value = "";
  renderObjectCreator();
}

async function fetchObjectEditorJson(path, options = {}) {
  const headers = { ...(options.headers || {}) };
  if (objectEditorRestAuthToken) {
    headers["X-TR-Auth"] = objectEditorRestAuthToken;
  }
  const response = await fetch(path, { ...options, headers });
  const payload = await response.json();
  if (!response.ok || payload.ok === false) {
    throw new Error(payload.error || `request failed: ${response.status}`);
  }
  return payload;
}

async function openObjectCreator() {
  objectEditorState.mode = "editing";
  objectEditorState.batchRolling = false;
  objectCreatorError.textContent = "";
  objectCreatorPage.style.display = "flex";
  renderObjectCreator();
  try {
    const profile = await fetchObjectEditorJson("/api/object-editor/profile");
    objectEditorState.slots = [null, null, null, null];
    const icons = profile.icons || [];
    for (let i = 0; i < 4 && i < icons.length; i++) {
      objectEditorState.slots[i] = icons[i];
    }
    objectEditorState.selectedSlot = -1;
    objectEditorState.activeRequestId = profile.queue?.active_request_id || null;
    if (objectEditorState.activeRequestId) {
      objectEditorState.mode = "rolling";
      pollObjectRequest();
    }
    renderObjectCreator(profile.queue || null);
  } catch (err) {
    objectCreatorError.textContent = err.message;
    objectEditorState.mode = "editing";
    renderObjectCreator();
  }
}

function closeObjectCreator() {
  objectEditorState.batchRolling = false;
  objectCreatorPage.style.display = "none";
  objectEditorState.mode = "closed";
}

function renderObjectCreator(queueInfo = null) {
  if (!objectCreatorQueue || !objectCreatorSlots) {
    return;
  }
  const isGenerating = objectEditorState.mode === "rolling" || !!objectEditorState.activeRequestId;
  objectCreatorQueue.classList.toggle("generating", isGenerating);
  objectCreatorQueue.textContent = "";
  if (queueInfo) {
    const ahead = queueInfo.items_ahead ?? 0;
    const queued = queueInfo.queued ?? 0;
    const running = queueInfo.running ?? 0;
    objectCreatorQueue.textContent = `Queue: ${queued} queued, ${running} running. Items ahead of your request: ${ahead}`;
  } else if (objectEditorState.mode === "rolling") {
    objectCreatorQueue.textContent = "Queue: preparing request status...";
  }

  objectCreatorSlots.innerHTML = "";
  for (let i = 0; i < 4; i++) {
    const slot = document.createElement("div");
    slot.className = "character-slot";
    if (isGenerating && !objectEditorState.slots[i]) {
      slot.classList.add("generating");
    }
    if (i === objectEditorState.selectedSlot) {
      slot.classList.add("selected");
    }
    const icon = objectEditorState.slots[i];
    if (icon) {
      const img = document.createElement("img");
      img.src = icon.icon_url;
      img.alt = icon.icon_id || `icon-${i + 1}`;
      slot.appendChild(img);
      const controls = document.createElement("div");
      const pick = document.createElement("button");
      pick.type = "button";
      pick.textContent = "Select";
      pick.addEventListener("click", () => {
        objectEditorState.selectedSlot = i;
        renderObjectCreator(queueInfo);
      });
      controls.appendChild(pick);
      const discard = document.createElement("button");
      discard.type = "button";
      discard.textContent = "Discard";
      discard.addEventListener("click", async () => {
        await discardObjectIcon(i);
      });
      controls.appendChild(discard);
      slot.appendChild(controls);
    } else {
      const empty = document.createElement("div");
      empty.className = "character-slot-empty";
      empty.textContent = "Empty";
      slot.appendChild(empty);
    }
    objectCreatorSlots.appendChild(slot);
  }
}

function objectFilledSlotsCount() {
  return objectEditorState.slots.filter(slot => !!slot).length;
}

function objectFirstEmptySlot() {
  return objectEditorState.slots.findIndex(slot => !slot);
}

async function startObjectRollBatch() {
  if (objectEditorState.activeRequestId) {
    return;
  }
  objectCreatorError.textContent = "";
  objectEditorState.description = (objectCreatorDescription.value || "").trim();
  objectCreatorDescription.value = objectEditorState.description;
  objectEditorState.batchRolling = true;
  await submitNextObjectRollIfNeeded();
}

async function submitNextObjectRollIfNeeded() {
  if (!objectEditorState.batchRolling || objectEditorState.activeRequestId) {
    return;
  }
  if (objectFilledSlotsCount() >= 4) {
    objectEditorState.batchRolling = false;
    objectEditorState.mode = "slots_ready";
    renderObjectCreator();
    return;
  }
  try {
    const payload = await fetchObjectEditorJson("/api/object-editor/requests", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ description: objectEditorState.description }),
    });
    objectEditorState.activeRequestId = payload.request.request_id;
    objectEditorState.mode = "rolling";
    renderObjectCreator(payload.request.queue || null);
    pollObjectRequest();
  } catch (err) {
    objectEditorState.batchRolling = false;
    objectEditorState.mode = "editing";
    objectCreatorError.textContent = err.message;
    renderObjectCreator();
  }
}

async function pollObjectRequest() {
  if (!objectEditorState.activeRequestId) {
    return;
  }
  let keepPolling = true;
  while (keepPolling && objectEditorState.activeRequestId) {
    try {
      const payload = await fetchObjectEditorJson(`/api/object-editor/requests/${objectEditorState.activeRequestId}`);
      const req = payload.request;
      renderObjectCreator(req.queue || null);
      if (req.status === "queued" || req.status === "running") {
        await new Promise(resolve => setTimeout(resolve, 10000));
        continue;
      }
      if (req.status === "done") {
        const idx = objectFirstEmptySlot();
        if (idx >= 0) {
          objectEditorState.slots[idx] = {
            icon_id: req.icon_id,
            icon_path: req.icon_path,
            icon_url: req.icon_url,
          };
        }
      } else if (req.status === "failed") {
        objectCreatorError.textContent = req.error || "icon generation failed";
      } else if (req.status === "cancelled") {
        objectCreatorError.textContent = "Active generation request was cancelled.";
      }
      objectEditorState.activeRequestId = null;
      keepPolling = false;
    } catch (err) {
      objectCreatorError.textContent = err.message;
      objectEditorState.activeRequestId = null;
      objectEditorState.batchRolling = false;
      keepPolling = false;
    }
  }

  if (objectEditorState.batchRolling) {
    await submitNextObjectRollIfNeeded();
  } else {
    objectEditorState.mode = objectFilledSlotsCount() > 0 ? "slots_ready" : "editing";
    renderObjectCreator();
  }
}

async function cancelActiveObjectRoll() {
  objectEditorState.batchRolling = false;
  if (!objectEditorState.activeRequestId) {
    return;
  }
  try {
    await fetchObjectEditorJson(`/api/object-editor/requests/${objectEditorState.activeRequestId}`, { method: "DELETE" });
  } catch (err) {
    objectCreatorError.textContent = err.message;
  } finally {
    objectEditorState.activeRequestId = null;
    objectEditorState.mode = "editing";
    renderObjectCreator();
  }
}

async function discardObjectIcon(index) {
  const icon = objectEditorState.slots[index];
  if (!icon) {
    return;
  }
  try {
    await fetchObjectEditorJson(`/api/object-editor/icons/${encodeURIComponent(icon.icon_id)}`, { method: "DELETE" });
    objectEditorState.slots[index] = null;
    if (objectEditorState.selectedSlot === index) {
      objectEditorState.selectedSlot = -1;
    }
    renderObjectCreator();
  } catch (err) {
    objectCreatorError.textContent = err.message;
  }
}

async function createThingFromSelectedSlot() {
  const idx = objectEditorState.selectedSlot;
  if (idx < 0 || !objectEditorState.slots[idx]) {
    objectCreatorError.textContent = "Select one generated icon before creating a thing.";
    return;
  }
  objectEditorState.description = (objectCreatorDescription.value || "").trim();
  objectCreatorDescription.value = objectEditorState.description;
  const icon = objectEditorState.slots[idx];
  try {
    await fetchObjectEditorJson(`/api/object-editor/icons/${encodeURIComponent(icon.icon_id)}/create`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ description: objectEditorState.description }),
    });
    objectCreatorError.textContent = "";
    closeObjectCreator();
  } catch (err) {
    objectCreatorError.textContent = err.message;
  }
}
