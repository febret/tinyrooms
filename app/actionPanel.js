var activePaletteTab = "actions";
var knownActions = {};
var knownEmotes = {};
var selectedTarget = null;
var inventoryItems = [];
var selectedInventoryObjId = null;
var worldEditorAvailable = false;

function renderInventoryPanel(items) {
  const inventoryList = document.getElementById("inventoryList");
  if (!inventoryList) return;
  inventoryItems = items;
  if (selectedInventoryObjId && !items.some(item => item.obj_id === selectedInventoryObjId)) {
    selectedInventoryObjId = null;
  }
  if (!selectedInventoryObjId && items.length > 0) {
    selectedInventoryObjId = items[0].obj_id;
  }
  inventoryList.innerHTML = "";
  if (items.length === 0) {
    inventoryList.innerHTML = '<div class="inventory-empty">Empty</div>';
    renderActionPalette();
    return;
  }
  for (const item of items) {
    const row = document.createElement("button");
    row.type = "button";
    row.className = "inventory-item";
    if (item.obj_id === selectedInventoryObjId) row.classList.add("is-selected");
    row.title = item.label || item.obj_id || "Item";
    row.draggable = true;
    row.addEventListener("click", () => {
      selectedInventoryObjId = item.obj_id;
      renderInventoryPanel(inventoryItems);
      renderActionPalette();
    });
    row.addEventListener("dragstart", ev => {
      selectedInventoryObjId = item.obj_id;
      renderActionPalette();
      if (!ev.dataTransfer) return;
      ev.dataTransfer.effectAllowed = "move";
      ev.dataTransfer.setData("text/x-tinyrooms-inventory-obj", item.obj_id);
      ev.dataTransfer.setData("text/plain", item.obj_id);
    });

    const icon = document.createElement("div");
    icon.className = "inventory-item-icon";
    const iconUrl = item.display && (item.display.icon || item.display.img || item.display.sprite);
    if (iconUrl) {
      const img = document.createElement("img");
      img.src = resolveAssetUrl(iconUrl);
      img.alt = item.label || "";
      icon.appendChild(img);
    } else {
      icon.textContent = "📦";
    }
    row.appendChild(icon);

    inventoryList.appendChild(row);
  }
  renderActionPalette();
}

function getSelectedInventoryItem() {
  if (!selectedInventoryObjId) return null;
  return inventoryItems.find(item => item.obj_id === selectedInventoryObjId) || null;
}

function dropInventoryObject(objId, point) {
  if (!objId) return;
  const payload = { obj_id: objId };
  if (point && Number.isFinite(point.x) && Number.isFinite(point.y)) {
    payload.x = Math.round(point.x);
    payload.y = Math.round(point.y);
  }
  socket.emit("room_drop_object", payload);
}

function dropSelectedInventoryObject() {
  if (!selectedInventoryObjId) return;
  dropInventoryObject(selectedInventoryObjId, null);
}

function getInventoryDragObjectId(event) {
  if (!event.dataTransfer) return "";
  const directId = (event.dataTransfer.getData("text/x-tinyrooms-inventory-obj") || "").trim();
  if (directId.length) return directId;
  const plainText = (event.dataTransfer.getData("text/plain") || "").trim();
  if (!plainText.length) return "";
  return inventoryItems.some(item => item.obj_id === plainText) ? plainText : "";
}

function bindInventoryDropHandlers() {
  if (!roomCanvas || roomCanvas.dataset.inventoryDropBound === "1") return;
  roomCanvas.dataset.inventoryDropBound = "1";
  roomCanvas.addEventListener("dragover", event => {
    const objId = getInventoryDragObjectId(event);
    if (!objId) return;
    event.preventDefault();
    if (event.dataTransfer) event.dataTransfer.dropEffect = "move";
  });
  roomCanvas.addEventListener("drop", event => {
    const objId = getInventoryDragObjectId(event);
    if (!objId) return;
    event.preventDefault();
    selectedInventoryObjId = objId;
    const point = getStagePoint(event.clientX, event.clientY, true);
    dropInventoryObject(objId, point || null);
  });
}

function handleRoomExitsUpdate(data) {
  roomState.exits = data.exits || [];
  renderActionPalette();
}

function clearRoomSelection() {
  for (const key of pixiEntityNodes.keys()) {
    pixiSetEntitySelected(key, false);
  }
}

function navigateExit(wayId) {
  socket.emit("navigate", { way_id: wayId });
  selectedTarget = null;
  clearRoomSelection();
  renderActionPalette();
}

function selectTarget(target, node) {
  selectedTarget = target;
  clearRoomSelection();
  if (target.type === "peep" || target.type === "object") {
    const key = `${target.type}:${target.id}`;
    pixiSetEntitySelected(key, true);
  }
  lookBox.innerHTML = `<strong>${escapeHtml(target.label || "")}</strong>: ${escapeHtml(target.description || "")}`;
  renderActionPalette();
}

function getEntityThumbnailUrl(entity) {
  if (!entity) return "";
  const display = entity.display || {};
  const iconUrl = display.icon || display.img || display.sprite || "";
  return iconUrl ? resolveAssetUrl(iconUrl) : "";
}

function getRoomEntitiesByType(entityType) {
  const entities = [];
  for (const entity of roomState.entities.values()) {
    if (entity.entity_type === entityType) {
      entities.push(entity);
    }
  }
  entities.sort((a, b) => (a.label || a.entity_id || "").localeCompare(b.label || b.entity_id || ""));
  return entities;
}

function pickUpSelectedObject() {
  if (!selectedTarget || selectedTarget.type !== "object") return;
  socket.emit("room_pick_object", { entity_id: selectedTarget.id });
  selectedTarget = null;
  clearRoomSelection();
  renderActionPalette();
}

function renderActionPalette() {
  actionPalette.innerHTML = "";
  const layout = document.createElement("div");
  layout.className = "palette-layout";

  const tabsEl = document.createElement("div");
  tabsEl.className = "palette-tabs";
  const tabs = [
    { id: "actions", emoji: "🤚", title: "Actions" },
    { id: "directions", emoji: "🧭", title: "Directions" },
    { id: "objects", emoji: "📦", title: "Objects" },
    { id: "peeps", emoji: "🧑", title: "Peeps" },
    { id: "emotes", emoji: "😀", title: "Emotes" },
    { id: "tools", emoji: "🧰", title: "Tools" },
  ];
  for (const tab of tabs) {
    const tabBtn = document.createElement("button");
    tabBtn.className = `palette-tab-btn${activePaletteTab === tab.id ? " is-active" : ""}`;
    tabBtn.textContent = tab.emoji;
    tabBtn.title = tab.title;
    tabBtn.onclick = () => {
      activePaletteTab = tab.id;
      renderActionPalette();
    };
    if (tab.id === "objects") {
      tabBtn.addEventListener("dragenter", ev => {
        if (ev.dataTransfer && ev.dataTransfer.types.includes("text/x-tinyrooms-inventory-obj")) {
          ev.preventDefault();
          activePaletteTab = "objects";
          renderActionPalette();
        }
      });
      tabBtn.addEventListener("dragover", ev => {
        if (ev.dataTransfer && ev.dataTransfer.types.includes("text/x-tinyrooms-inventory-obj")) {
          ev.preventDefault();
          ev.dataTransfer.dropEffect = "move";
          tabBtn.classList.add("is-drag-over");
        }
      });
      tabBtn.addEventListener("dragleave", () => tabBtn.classList.remove("is-drag-over"));
      tabBtn.addEventListener("drop", ev => {
        tabBtn.classList.remove("is-drag-over");
        if (!ev.dataTransfer) return;
        const objId = (ev.dataTransfer.getData("text/x-tinyrooms-inventory-obj") || "").trim();
        if (!objId) return;
        ev.preventDefault();
        dropInventoryObject(objId, null);
      });
    }
    tabsEl.appendChild(tabBtn);
  }

  const buttonsEl = document.createElement("div");
  buttonsEl.className = "palette-buttons";
  const entries = getPaletteEntriesForTab(activePaletteTab);
  for (const item of entries) {
    const btn = document.createElement("button");
    btn.className = `palette-btn${item.iconUrl ? " palette-btn-thumb" : ""}${item.selected ? " is-selected" : ""}`;
    btn.disabled = !!item.disabled;
    if (item.title) btn.title = item.title;
    if (item.iconUrl) {
      const img = document.createElement("img");
      img.src = item.iconUrl;
      img.alt = item.label || item.title || "";
      img.className = "palette-btn-thumb-image";
      btn.appendChild(img);
    } else {
      btn.textContent = item.label;
    }
    btn.onclick = item.onClick || null;
    if (item.entityId) {
      btn.draggable = true;
      btn.addEventListener("dragstart", ev => {
        if (!ev.dataTransfer) return;
        ev.dataTransfer.effectAllowed = "move";
        ev.dataTransfer.setData("text/x-tinyrooms-room-obj", item.entityId);
        ev.dataTransfer.setData("text/plain", item.entityId);
      });
    }
    buttonsEl.appendChild(btn);
  }

  if (activePaletteTab === "objects") {
    buttonsEl.addEventListener("dragover", ev => {
      if (ev.dataTransfer && ev.dataTransfer.types.includes("text/x-tinyrooms-inventory-obj")) {
        ev.preventDefault();
        ev.dataTransfer.dropEffect = "move";
        buttonsEl.classList.add("is-drag-over");
      }
    });
    buttonsEl.addEventListener("dragleave", ev => {
      if (!buttonsEl.contains(ev.relatedTarget)) {
        buttonsEl.classList.remove("is-drag-over");
      }
    });
    buttonsEl.addEventListener("drop", ev => {
      buttonsEl.classList.remove("is-drag-over");
      if (!ev.dataTransfer) return;
      const objId = (ev.dataTransfer.getData("text/x-tinyrooms-inventory-obj") || "").trim();
      if (!objId) return;
      ev.preventDefault();
      dropInventoryObject(objId, null);
    });
  }

  layout.appendChild(tabsEl);
  layout.appendChild(buttonsEl);
  actionPalette.appendChild(layout);
}

function getPaletteEntriesForTab(tabId) {
  if (tabId === "emotes") {
    const emotes = Object.entries(knownEmotes).filter(([id]) => id !== "say");
    if (emotes.length === 0) {
      return [{ label: "No emotes", disabled: true, onClick: null }];
    }
    return emotes.map(([id, def]) => ({
      label: def.label || id,
      onClick: () => sendEmote(id),
    }));
  }
  if (tabId === "directions") {
    if (!roomState.exits.length) {
      return [{ label: "No exits", disabled: true, onClick: null }];
    }
    return roomState.exits.map(exit => ({
      label: exit.label || exit.id,
      onClick: () => navigateExit(exit.id),
    }));
  }
  if (tabId === "objects") {
    const objects = getRoomEntitiesByType("object");
    if (!objects.length) {
      return [{ label: "No objects", disabled: true, onClick: null }];
    }
    return objects.map(entity => ({
      label: entity.label || entity.entity_id || "object",
      title: entity.label || entity.entity_id || "object",
      iconUrl: getEntityThumbnailUrl(entity),
      entityId: entity.entity_id,
      selected: selectedTarget && selectedTarget.type === "object" && selectedTarget.id === entity.entity_id,
      onClick: () => selectTarget({
        type: "object",
        id: entity.entity_id,
        label: entity.label || entity.entity_id,
        description: entity.description || "",
      }, null),
    }));
  }
  if (tabId === "peeps") {
    const peeps = getRoomEntitiesByType("peep");
    if (!peeps.length) {
      return [{ label: "No peeps", disabled: true, onClick: null }];
    }
    return peeps.map(entity => ({
      label: entity.label || entity.entity_id || "peep",
      title: entity.is_self ? "You" : (entity.label || entity.entity_id || "peep"),
      iconUrl: getEntityThumbnailUrl(entity),
      selected: selectedTarget && selectedTarget.type === "peep" && selectedTarget.id === entity.entity_id,
      onClick: () => selectTarget({
        type: "peep",
        id: entity.entity_id,
        label: entity.label || entity.entity_id,
        description: entity.description || "",
      }, null),
    }));
  }
  if (tabId === "tools") {
    const entries = [
      { label: "Create Thing", onClick: () => openObjectCreator() },
      { label: roomEditor.enabled ? "Editing Room" : "Edit Room", onClick: () => enableRoomEditMode() },
      { label: "Modify Character", onClick: () => btnCharacterEditorTrigger && btnCharacterEditorTrigger.click() },
    ];
    if (worldEditorAvailable) {
      entries.push({ label: "World Editor", onClick: () => btnWorldEditor && btnWorldEditor.click() });
    }
    if (roomState.stage.type === 'standard') {
      entries.push({ label: "Camera Near", onClick: () => setCameraFloorHeight(200) });
      entries.push({ label: "Camera Mid", onClick: () => setCameraFloorHeight(100) });
      entries.push({ label: "Camera Far", onClick: () => setCameraFloorHeight(10) });
    }
    return entries;
  }
  return [
    { label: "Look", onClick: () => sendAction("basic.look") },
    { label: "Use", onClick: () => sendAction("basic.use") },
    {
      label: "Drop",
      disabled: !selectedInventoryObjId,
      title: selectedInventoryObjId
        ? `Drop ${getSelectedInventoryItem()?.label || selectedInventoryObjId}`
        : "Select an inventory item to drop",
      onClick: () => dropSelectedInventoryObject(),
    },
    { label: "Equip", onClick: () => requestActivity("equip") },
    { label: "Move", onClick: () => { activePaletteTab = "directions"; renderActionPalette(); } },
    { label: "Self", onClick: () => requestActivity("self") },
    ...(selectedTarget && selectedTarget.type === "object"
      ? [{ label: "Pick Up", onClick: () => pickUpSelectedObject() }]
      : []),
    ...(selectedTarget && selectedTarget.type === "prop" && selectedTarget.exit_way_id
      ? [{ label: `Go: ${selectedTarget.exit_label || "Exit"}`, onClick: () => navigateExit(selectedTarget.exit_way_id) }]
      : []),
  ];
}

function sendAction(actionId) {
  let cmd = `.${actionId}`;
  if (selectedTarget) {
    if (selectedTarget.type === "object") cmd += ` @obj:${selectedTarget.id}`;
    else if (selectedTarget.type === "peep") cmd += ` @${selectedTarget.id}`;
    else if (selectedTarget.type === "prop") cmd += ` @prop:${selectedTarget.id}`;
  }
  socket.emit("message", { text: cmd });
}

function sendEmote(emoteId) {
  let cmd = `.${emoteId}`;
  if (selectedTarget) {
    if (selectedTarget.type === "peep") cmd += `@${selectedTarget.id}`;
    else if (selectedTarget.type === "object") cmd += ` @obj:${selectedTarget.id}`;
    else if (selectedTarget.type === "prop") cmd += ` @prop:${selectedTarget.id}`;
  }
  socket.emit("message", { text: cmd });
}

function requestActivity(mode) {
  socket.emit("request_activity_panel", { mode });
}

function bindInventoryListPickUpHandler() {
  const inventoryList = document.getElementById("inventoryList");
  if (!inventoryList || inventoryList.dataset.pickUpBound === "1") return;
  inventoryList.dataset.pickUpBound = "1";
  inventoryList.addEventListener("dragover", ev => {
    if (ev.dataTransfer && ev.dataTransfer.types.includes("text/x-tinyrooms-room-obj")) {
      ev.preventDefault();
      ev.dataTransfer.dropEffect = "move";
      inventoryList.classList.add("is-drag-over");
    }
  });
  inventoryList.addEventListener("dragleave", ev => {
    if (!inventoryList.contains(ev.relatedTarget)) {
      inventoryList.classList.remove("is-drag-over");
    }
  });
  inventoryList.addEventListener("drop", ev => {
    inventoryList.classList.remove("is-drag-over");
    if (!ev.dataTransfer) return;
    const entityId = (ev.dataTransfer.getData("text/x-tinyrooms-room-obj") || "").trim();
    if (!entityId) return;
    ev.preventDefault();
    socket.emit("room_pick_object", { entity_id: entityId });
  });
}
