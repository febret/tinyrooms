function clonePropState(prop) {
  return {
    prop_instance_id: prop.prop_instance_id,
    prop_id: prop.prop_id,
    exit_way_id: prop.exit_way_id || null,
    position: { ...(prop.position || {}) },
  };
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
    addMessage("<span style='color:red'>Error: you do not have permission to edit this room</span>");
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

function claimRoom() {
  socket.emit("room_claim", {});
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

function cycleExitAssignment(propInstanceId) {
  const prop = roomEditor.draftProps.get(propInstanceId);
  if (!prop) return;
  const exits = roomState.exits || [];
  if (exits.length === 0) return;
  const currentId = prop.exit_way_id || null;
  const currentIdx = exits.findIndex(e => e.id === currentId);
  // Cycle: none → exits[0] → exits[1] → ... → none
  if (currentId === null) {
    prop.exit_way_id = exits[0].id;
  } else if (currentIdx >= 0 && currentIdx < exits.length - 1) {
    prop.exit_way_id = exits[currentIdx + 1].id;
  } else {
    prop.exit_way_id = null;
  }
  roomEditor.draftProps.set(propInstanceId, prop);
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
      exit_way_id: prop.exit_way_id || null,
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
  const exitsList = (roomState.exits || []).length > 0
    ? `<div style="margin-top:0.4rem;font-size:0.72rem;opacity:0.75;">Exits: ${
        roomState.exits.map(e => `<span>${escapeHtml(e.label || e.id)}</span>`).join(", ")
      } — use 🚪 on a prop to assign</div>`
    : "";
  const claimSection = roomState.canClaimRoom
    ? `<div style="margin-top:0.5rem;">
         <button id="btnRoomEditorClaim">Claim Room</button>
         <span style="font-size:0.72rem;opacity:0.75;margin-left:0.4rem;">No owner — become the owner</span>
       </div>`
    : "";
  activityPanel.innerHTML = `
    <div class="activity-panel-header">
      <div class="room-header-title">Room Editor</div>
      <button id="btnRoomEditorDismiss" class="activity-panel-dismiss" title="Dismiss">✕</button>
    </div>
    <div class="character-editor-actions">
      <button id="btnRoomEditorSave" ${saveDisabled}>Save Room</button>
      <button id="btnRoomEditorCancel" ${saveDisabled}>Cancel</button>
    </div>
    ${claimSection}
    <div>${roomEditor.saving ? "Saving room..." : "Add prop from library:"}</div>
    <div class="character-editor-actions">${propsList}</div>
    ${exitsList}
  `;
  const btnSave = document.getElementById("btnRoomEditorSave");
  if (btnSave) btnSave.onclick = saveRoomEdits;
  const btnCancel = document.getElementById("btnRoomEditorCancel");
  if (btnCancel) btnCancel.onclick = cancelRoomEdits;
  const btnDismiss = document.getElementById("btnRoomEditorDismiss");
  if (btnDismiss) btnDismiss.onclick = cancelRoomEdits;
  const btnClaim = document.getElementById("btnRoomEditorClaim");
  if (btnClaim) btnClaim.onclick = claimRoom;
  activityPanel.querySelectorAll("[data-prop-add]").forEach((node) => {
    node.addEventListener("click", () => {
      const propId = node.getAttribute("data-prop-add");
      if (propId) addDraftProp(propId);
    });
  });
}
