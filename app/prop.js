function clonePropState(prop) {
  return {
    prop_instance_id: prop.prop_instance_id,
    prop_id: prop.prop_id,
    position: { ...(prop.position || {}) },
  };
}

function orientationToTransform(orientation) {
  if (orientation === "left") return "rotate(270deg)";
  if (orientation === "right") return "rotate(90deg)";
  if (orientation === "back") return "rotate(180deg)";
  return "rotate(0deg)";
}

function cycleOrientation(orientation) {
  if (orientation === "front") return "right";
  if (orientation === "right") return "back";
  if (orientation === "back") return "left";
  return "front";
}

function nextDraftZOrder() {
  let maxZ = 0;
  for (const prop of roomEditor.draftProps.values()) {
    const z = Number(prop.position?.z_order || 0);
    if (z > maxZ) maxZ = z;
  }
  return maxZ + 1;
}

function resolveBackgroundUrlFromCanvas() {
  return roomState.backgroundPath || "";
}

function getEditableProps() {
  return roomEditor.enabled ? roomEditor.draftProps : roomState.props;
}

function setPropLibrary(props) {
  const nextLibrary = new Map();
  for (const def of (props || [])) {
    if (def?.prop_id) {
      nextLibrary.set(def.prop_id, def);
    }
  }
  roomState.propLibrary = nextLibrary;
}

async function ensurePropLibraryLoaded(force) {
  if (!restAuthToken) {
    return;
  }
  if (!force && roomState.propLibrary.size > 0) {
    return;
  }
  try {
    const response = await fetch("/api/props/library", {
      headers: { "X-TR-Auth": restAuthToken },
    });
    if (!response.ok) {
      addMessage("<span style='color:red'>Error: failed to load prop library</span>");
      return;
    }
    const payload = await response.json();
    roomState.propLibraryWorldId = payload.world_id || null;
    setPropLibrary(payload.props || []);
    if (roomEditor.enabled) {
      renderRoomEditorActivity();
    }
    renderRoomStage(roomState.backgroundPath);
  } catch (err) {
    const reason = err instanceof Error ? err.message : String(err);
    addMessage(`<span style='color:red'>Error: failed to load prop library (${escapeHtml(reason)})</span>`);
  }
}

function resolvePropLibraryDef(prop) {
  return roomState.propLibrary.get(prop.prop_id) || null;
}

function enableRoomEditMode() {
  if (!roomState.canEditProps) {
    addMessage("<span style='color:red'>Error: only room owner can edit props</span>");
    return;
  }
  if (roomEditor.enabled) {
    return;
  }
  roomEditor.enabled = true;
  roomEditor.saving = false;
  roomEditor.draftProps = new Map();
  for (const [propId, prop] of roomState.props.entries()) {
    roomEditor.draftProps.set(propId, clonePropState(prop));
  }
  activityPanel.style.display = "block";
  renderActionPalette();
  renderRoomStage(roomState.backgroundPath);
}

function disableRoomEditMode() {
  roomEditor.enabled = false;
  roomEditor.saving = false;
  roomEditor.draftProps = new Map();
  activityPanel.style.display = "none";
  renderActionPalette();
}

function cancelRoomEdits() {
  disableRoomEditMode();
  renderRoomStage(roomState.backgroundPath);
}

function rotateDraftProp(propInstanceId) {
  const prop = roomEditor.draftProps.get(propInstanceId);
  if (!prop) return;
  const current = prop.position?.orientation || "front";
  prop.position.orientation = cycleOrientation(current);
  prop.position.z_order = nextDraftZOrder();
  roomEditor.draftProps.set(propInstanceId, prop);
  renderRoomStage(roomState.backgroundPath);
}

function deleteDraftProp(propInstanceId) {
  roomEditor.draftProps.delete(propInstanceId);
  if (selectedTarget?.type === "prop" && selectedTarget.id === propInstanceId) {
    selectedTarget = null;
    lookBox.textContent = "";
  }
  renderRoomStage(roomState.backgroundPath);
}

function addDraftProp(propId) {
  const propDef = roomState.propLibrary.get(propId);
  if (!propDef) return;
  const instanceId = `${roomState.roomId}-${propId}-${Date.now().toString(36)}${Math.floor(Math.random() * 1000).toString(36)}`;
  const x = Math.round(roomState.stage.width / 2);
  const y = Math.round(roomState.stage.height / 2);
  const nextProp = {
    prop_instance_id: instanceId,
    prop_id: propId,
    position: { x, y, orientation: "front", layer: 0, z_order: nextDraftZOrder() },
  };
  roomEditor.draftProps.set(instanceId, nextProp);
  renderRoomStage(roomState.backgroundPath);
}

function saveRoomEdits() {
  if (!roomEditor.enabled || roomEditor.saving) {
    return;
  }
  roomEditor.saving = true;
  renderRoomEditorActivity();
  const payloadProps = [];
  for (const prop of roomEditor.draftProps.values()) {
    payloadProps.push({
      prop_instance_id: prop.prop_instance_id,
      prop_id: prop.prop_id,
      x: Number(prop.position?.x || 0),
      y: Number(prop.position?.y || 0),
      orientation: prop.position?.orientation || "front",
    });
  }
  socket.emit("room_save_props", { props: payloadProps });
}

function renderRoomEditorActivity() {
  if (!roomEditor.enabled) {
    return;
  }
  activityPanel.style.display = "block";
  const saveDisabled = roomEditor.saving ? "disabled" : "";
  const propsList = Array.from(roomState.propLibrary.values())
    .map((item) => {
      const safeId = escapeHtml(item.prop_id || "");
      const safeLabel = escapeHtml(item.label || item.prop_id || "");
      return `<button class="palette-btn room-editor-prop-btn" data-prop-add="${safeId}" ${saveDisabled}>+ ${safeLabel}</button>`;
    })
    .join("");
  activityPanel.innerHTML = `
    <div class="room-header-title">Room Editor</div>
    <div class="character-editor-actions">
      <button id="btnRoomEditorSave" ${saveDisabled}>Save Room</button>
      <button id="btnRoomEditorCancel" ${saveDisabled}>Cancel</button>
    </div>
    <div>${roomEditor.saving ? "Saving room..." : "Add prop from library:"}</div>
    <div class="character-editor-actions">${propsList}</div>
  `;
  const btnSave = document.getElementById("btnRoomEditorSave");
  if (btnSave) btnSave.onclick = saveRoomEdits;
  const btnCancel = document.getElementById("btnRoomEditorCancel");
  if (btnCancel) btnCancel.onclick = cancelRoomEdits;
  activityPanel.querySelectorAll("[data-prop-add]").forEach((node) => {
    node.addEventListener("click", () => {
      const propId = node.getAttribute("data-prop-add");
      if (propId) addDraftProp(propId);
    });
  });
}

function makePropNode(prop) {
  const node = document.createElement("div");
  node.className = "room-prop room-selectable";
  if (roomEditor.enabled) {
    node.classList.add("room-prop-outline");
  }
  node.id = `prop-${prop.prop_instance_id}`;
  node.style.left = `${prop.position?.x || 0}px`;
  node.style.top = `${prop.position?.y || 0}px`;
  node.style.zIndex = `${prop.position?.z_order || 0}`;
  const propDef = resolvePropLibraryDef(prop);
  const meta = propDef?.display?.prop_meta;
  let visualEl;
  if (meta) {
    // Frame-clipped rendering
    const frame = meta.frame || {};
    const w = frame.width || 32;
    const h = frame.height || 32;
    visualEl = document.createElement("div");
    visualEl.style.width = `${w}px`;
    visualEl.style.height = `${h}px`;
    visualEl.style.backgroundImage = `url(${resolveAssetUrl(meta.image_url || "")})`;
    visualEl.style.backgroundRepeat = "no-repeat";
    visualEl.style.backgroundPosition = `-${frame.x || 0}px -${frame.y || 0}px`;
    visualEl.style.transform = orientationToTransform(prop.position?.orientation);
    if (meta.offset_x || meta.offset_y) {
      visualEl.style.position = "relative";
      visualEl.style.left = `${meta.offset_x || 0}px`;
      visualEl.style.top = `${meta.offset_y || 0}px`;
    }
    // Animation
    if (meta.animation && meta.animation.speed > 0 && Array.isArray(meta.animation.frames) && meta.animation.frames.length > 1) {
      let frameIndex = 0;
      const frames = meta.animation.frames;
      const intervalMs = meta.animation.speed * 1000;
      const timerId = setInterval(() => {
        if (!document.contains(visualEl)) {
          clearInterval(timerId);
          return;
        }
        frameIndex = (frameIndex + 1) % frames.length;
        const f = frames[frameIndex];
        visualEl.style.backgroundPosition = `-${f.x || 0}px -${f.y || 0}px`;
      }, intervalMs);
    }
  } else {
    // Legacy <img> fallback
    visualEl = document.createElement("img");
    visualEl.src = resolveAssetUrl(propDef?.display?.sprite || propDef?.display?.img || "");
    visualEl.alt = propDef?.label || prop.prop_id || "";
    visualEl.style.transform = orientationToTransform(prop.position?.orientation);
  }
  node.appendChild(visualEl);
  if (roomEditor.enabled) {
    const controls = document.createElement("div");
    controls.className = "room-prop-controls";
    const rotateBtn = document.createElement("button");
    rotateBtn.type = "button";
    rotateBtn.className = "room-prop-control-btn";
    rotateBtn.textContent = "↻";
    rotateBtn.title = "Rotate";
    rotateBtn.addEventListener("click", ev => {
      ev.preventDefault();
      ev.stopPropagation();
      rotateDraftProp(prop.prop_instance_id);
    });
    const deleteBtn = document.createElement("button");
    deleteBtn.type = "button";
    deleteBtn.className = "room-prop-control-btn";
    deleteBtn.textContent = "✕";
    deleteBtn.title = "Delete";
    deleteBtn.addEventListener("click", ev => {
      ev.preventDefault();
      ev.stopPropagation();
      deleteDraftProp(prop.prop_instance_id);
    });
    controls.addEventListener("pointerdown", ev => {
      ev.stopPropagation();
    });
    controls.appendChild(rotateBtn);
    controls.appendChild(deleteBtn);
    node.appendChild(controls);
  }
  node.addEventListener("click", () => selectTarget({
    type: "prop",
    id: prop.prop_instance_id,
    label: propDef?.label || prop.prop_id || "prop",
    description: propDef?.description || "",
  }, node));
  configureDragHandlers(node, "prop", prop.prop_instance_id, roomState.canEditProps && roomEditor.enabled);
  return node;
}
