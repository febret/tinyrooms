var activePaletteTab = "actions";
var knownActions = {};
var knownEmotes = {};
var selectedTarget = null;
var inventoryItems = [];
var worldEditorAvailable = false;

function renderInventoryPanel(items) {
  const inventoryList = document.getElementById("inventoryList");
  if (!inventoryList) return;
  inventoryItems = items;
  // Clear inventory selection if the selected item left the inventory
  if (selectedTarget && selectedTarget.type === "inventory" &&
      !items.some(item => item.obj_id === selectedTarget.id)) {
    selectedTarget = null;
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
    row.dataset.objId = item.obj_id;
    row.title = item.label || item.obj_id || "Item";
    row.draggable = true;
    row.addEventListener("click", () => {
      selectTarget({
        type: "inventory",
        id: item.obj_id,
        label: item.label || item.obj_id || "Item",
        description: item.description || "",
        display: item.display,
        inventory_actions: item.inventory_actions,
      }, null);
    });
    row.addEventListener("dragstart", ev => {
      selectTarget({
        type: "inventory",
        id: item.obj_id,
        label: item.label || item.obj_id || "Item",
        description: item.description || "",
        display: item.display,
        inventory_actions: item.inventory_actions,
      }, null);
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
  renderInventorySelection();
  renderActionPalette();
}

function dropInventoryObject(objId, point) {
  if (!objId) return;
  let cmd = `:drop @obj:${objId}`;
  if (point && Number.isFinite(point.x) && Number.isFinite(point.y)) {
    cmd += ` ${Math.round(point.x)} ${Math.round(point.y)}`;
  }
  socket.emit("message", { text: cmd });
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
  const roomPanel = document.getElementById("viewPanel");
  if (!roomCanvas || !roomPanel || roomCanvas.dataset.inventoryDropBound === "1") return;
  roomCanvas.dataset.inventoryDropBound = "1";
  roomPanel.dataset.inventoryDropBound = "1";

  roomPanel.addEventListener("dragover", event => {
    const objId = getInventoryDragObjectId(event);
    if (!objId) return;
    event.preventDefault();
    if (event.dataTransfer) event.dataTransfer.dropEffect = "move";
    roomPanel.classList.add("is-drag-over");
  });
  roomPanel.addEventListener("dragleave", event => {
    if (!roomPanel.contains(event.relatedTarget)) {
      roomPanel.classList.remove("is-drag-over");
    }
  });
  roomPanel.addEventListener("drop", event => {
    roomPanel.classList.remove("is-drag-over");
    const objId = getInventoryDragObjectId(event);
    if (!objId) return;
    event.preventDefault();
    const point = getStagePoint(event.clientX, event.clientY, true);
    dropInventoryObject(objId, point || null);
  });

  roomCanvas.addEventListener("dragover", event => {
    const objId = getInventoryDragObjectId(event);
    if (!objId) return;
    event.preventDefault();
    event.stopPropagation();
    if (event.dataTransfer) event.dataTransfer.dropEffect = "move";
  });
  roomCanvas.addEventListener("drop", event => {
    const objId = getInventoryDragObjectId(event);
    if (!objId) return;
    event.preventDefault();
    event.stopPropagation();
    roomPanel.classList.remove("is-drag-over");
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
  if (!wayId) return;
  socket.emit("message", { text: `:go @way:${wayId}` });
  clearSelectedTarget();
}

function selectTarget(target, node) {
  selectedTarget = target;
  // Only highlight on the pixi stage for room entities (not inventory items)
  if (target.type !== "inventory") {
    clearRoomSelection();
    if (target.type === "peep" || target.type === "object") {
      const key = `${target.type}:${target.id}`;
      pixiSetEntitySelected(key, true);
    }
  }
  lookBox.innerHTML = `<strong>${escapeHtml(target.label || "")}</strong>: ${escapeHtml(target.description || "")}`;
  renderActionPalette();
  renderInventorySelection();
}

function clearSelectedTarget() {
  selectedTarget = null;
  clearRoomSelection();
  lookBox.innerHTML = "";
  renderActionPalette();
  renderInventorySelection();
}

function renderInventorySelection() {
  const inventoryList = document.getElementById("inventoryList");
  if (!inventoryList) return;
  for (const row of inventoryList.querySelectorAll(".inventory-item")) {
    const objId = row.dataset.objId;
    row.classList.toggle("is-selected", selectedTarget?.type === "inventory" && selectedTarget.id === objId);
  }
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
  socket.emit("message", { text: `:pick @obj:${selectedTarget.id}` });
  clearSelectedTarget();
}

function targetsMatch(left, right) {
  if (!left || !right) return false;
  return left.type === right.type && left.id === right.id;
}

function targetToCommandRef(target) {
  if (!target) return "";
  if (target.type === "object" || target.type === "inventory") return `@obj:${target.id}`;
  if (target.type === "peep") return `@${target.id}`;
  if (target.type === "prop") return `@prop:${target.id}`;
  return "";
}

function sendLookCommand(target) {
  const activeTarget = target || selectedTarget;
  const targetRef = targetToCommandRef(activeTarget);
  const text = targetRef ? `:look ${targetRef}` : ":look";
  socket.emit("message", { text });
}

function sendUseCommand(target) {
  const activeTarget = target || selectedTarget;
  const targetRef = targetToCommandRef(activeTarget);
  const text = targetRef ? `:use ${targetRef}` : ":use";
  socket.emit("message", { text });
}

function handleTargetTap(target) {
  if (!target) return;
  if (targetsMatch(selectedTarget, target)) {
    sendUseCommand(target);
    return;
  }
  selectTarget(target, null);
}

function handleTargetLook(target) {
  if (!target) return;
  selectTarget(target, null);
  sendLookCommand(target);
}

function executeInventoryAction(commandsText, objId) {
  const commandTemplate = String(commandsText || "").trim();
  if (!commandTemplate || !objId) return;
  const objRef = `@obj:${objId}`;
  const commands = commandTemplate
    .split(",")
    .map(command => command.trim())
    .filter(Boolean);
  for (const command of commands) {
    socket.emit("message", { text: command.replace(/\$0/g, objRef) });
  }
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
    tabBtn.dataset.tabId = tab.id;
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
      btn.dataset.entityId = item.entityId;
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
  // Actions tab — context-sensitive based on selectedTarget
  const invTarget = selectedTarget?.type === "inventory" ? selectedTarget : null;
  const roomObjTarget = selectedTarget?.type === "object" ? selectedTarget : null;
  const peepTarget = selectedTarget?.type === "peep" ? selectedTarget : null;
  const propTarget = selectedTarget?.type === "prop" ? selectedTarget : null;
  const hasAnyTarget = !!selectedTarget;

  const entries = [
    { label: "Look", onClick: () => sendLookCommand() },
    { label: "Use", onClick: () => sendUseCommand() },
    { label: "Equip", onClick: () => requestActivity("equip") },
    { label: "Self", onClick: () => requestActivity("self") },
  ];

  if (invTarget) {
    const customActions = Array.isArray(invTarget.inventory_actions) ? invTarget.inventory_actions : [];
    for (const action of customActions) {
      const commandTemplate = String(action?.commands || "").trim();
      if (!commandTemplate) continue;
      const actionLabel = String(action?.label || "Action").trim() || "Action";
      entries.push({
        label: actionLabel,
        title: `${actionLabel}: ${commandTemplate}`,
        onClick: () => executeInventoryAction(commandTemplate, invTarget.id),
      });
    }
  }

  if (invTarget) {
    entries.push({
      label: "Drop",
      title: `Drop ${invTarget.label || invTarget.id}`,
      onClick: () => dropInventoryObject(invTarget.id, null),
    });
  } else {
    entries.push({
      label: "Drop",
      disabled: true,
      title: "Select an inventory item to drop",
      onClick: null,
    });
  }

  if (roomObjTarget) {
    entries.push({ label: "Pick Up", onClick: () => pickUpSelectedObject() });
  }

  if (hasAnyTarget) {
    entries.push({ label: "Deselect", onClick: () => clearSelectedTarget() });
  }

  if (propTarget && propTarget.exit_way_id) {
    entries.push({ label: `Go: ${propTarget.exit_label || "Exit"}`, onClick: () => navigateExit(propTarget.exit_way_id) });
  }

  return entries;
}

function sendEmote(emoteId) {
  let cmd = `.${emoteId}`;
  if (selectedTarget) {
    if (selectedTarget.type === "peep") cmd += `@${selectedTarget.id}`;
    else if (selectedTarget.type === "object" || selectedTarget.type === "inventory") cmd += ` @obj:${selectedTarget.id}`;
    else if (selectedTarget.type === "prop") cmd += ` @prop:${selectedTarget.id}`;
  }
  socket.emit("message", { text: cmd });
}

function requestActivity(mode) {
  if (mode === "equip") {
    socket.emit("message", { text: ":equip" });
    return;
  }
  if (mode === "self") {
    socket.emit("message", { text: ":self" });
  }
}

function bindInventoryListPickUpHandler() {
  const inventoryList = document.getElementById("inventoryList");
  const inventoryPanel = document.getElementById("inventoryPanel");
  if (!inventoryList || !inventoryPanel || inventoryList.dataset.pickUpBound === "1") return;
  inventoryList.dataset.pickUpBound = "1";
  inventoryPanel.dataset.pickUpBound = "1";
  inventoryPanel.addEventListener("dragover", ev => {
    if (ev.dataTransfer && ev.dataTransfer.types.includes("text/x-tinyrooms-room-obj")) {
      ev.preventDefault();
      ev.dataTransfer.dropEffect = "move";
      inventoryPanel.classList.add("is-drag-over");
    }
  });
  inventoryPanel.addEventListener("dragleave", ev => {
    if (!inventoryPanel.contains(ev.relatedTarget)) {
      inventoryPanel.classList.remove("is-drag-over");
    }
  });
  inventoryPanel.addEventListener("drop", ev => {
    inventoryPanel.classList.remove("is-drag-over");
    if (!ev.dataTransfer) return;
    const entityId = (ev.dataTransfer.getData("text/x-tinyrooms-room-obj") || "").trim();
    if (!entityId) return;
    ev.preventDefault();
    socket.emit("message", { text: `:pick @obj:${entityId}` });
  });
  inventoryList.addEventListener("dragover", ev => {
    if (ev.dataTransfer && ev.dataTransfer.types.includes("text/x-tinyrooms-room-obj")) {
      ev.preventDefault();
      ev.stopPropagation();
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
    inventoryPanel.classList.remove("is-drag-over");
    if (!ev.dataTransfer) return;
    const entityId = (ev.dataTransfer.getData("text/x-tinyrooms-room-obj") || "").trim();
    if (!entityId) return;
    ev.preventDefault();
    ev.stopPropagation();
    socket.emit("message", { text: `:pick @obj:${entityId}` });
  });
}

// ─── Touch drag-and-drop manager ─────────────────────────────────────────────
// Mirrors the HTML5 drag/drop flows for touch devices.
// touchDrag state: { type, id, sourceEl, startX, startY, active, ghost }

var touchDrag = null;
var TOUCH_DRAG_THRESHOLD = 8;

function initTouchDragHandlers() {
  document.addEventListener("touchstart", _tdOnStart, { passive: false });
  document.addEventListener("touchmove", _tdOnMove, { passive: false });
  document.addEventListener("touchend", _tdOnEnd, { passive: false });
  document.addEventListener("touchcancel", _tdOnCancel);
}

function _tdOnStart(ev) {
  const el = ev.target;
  const invItem = el.closest(".inventory-item[data-obj-id]");
  if (invItem) {
    const t = ev.touches[0];
    touchDrag = { type: "inventory-obj", id: invItem.dataset.objId, sourceEl: invItem,
                  startX: t.clientX, startY: t.clientY, active: false, ghost: null };
    return;
  }
  const pBtn = el.closest(".palette-btn[data-entity-id]");
  if (pBtn) {
    const t = ev.touches[0];
    touchDrag = { type: "room-obj", id: pBtn.dataset.entityId, sourceEl: pBtn,
                  startX: t.clientX, startY: t.clientY, active: false, ghost: null };
    return;
  }
}

function _tdOnMove(ev) {
  if (!touchDrag) return;
  const t = ev.touches[0];
  const dx = t.clientX - touchDrag.startX;
  const dy = t.clientY - touchDrag.startY;
  const dist = Math.sqrt(dx * dx + dy * dy);
  if (!touchDrag.active && dist < TOUCH_DRAG_THRESHOLD) return;
  ev.preventDefault();
  if (!touchDrag.active) {
    touchDrag.active = true;
    const rect = touchDrag.sourceEl.getBoundingClientRect();
    const ghost = touchDrag.sourceEl.cloneNode(true);
    ghost.style.cssText = [
      "position:fixed", "pointer-events:none", "opacity:0.72", "z-index:9999",
      `width:${rect.width}px`, `height:${rect.height}px`,
      `left:${rect.left}px`, `top:${rect.top}px`, "margin:0", "transition:none",
    ].join(";") + ";";
    document.body.appendChild(ghost);
    touchDrag.ghost = ghost;
    touchDrag.halfW = rect.width / 2;
    touchDrag.halfH = rect.height / 2;
  }
  const g = touchDrag.ghost;
  g.style.left = (t.clientX - touchDrag.halfW) + "px";
  g.style.top  = (t.clientY - touchDrag.halfH) + "px";
  _tdUpdateHighlight(t.clientX, t.clientY);
}

function _tdOnEnd(ev) {
  if (!touchDrag) return;
  if (!touchDrag.active) { touchDrag = null; return; }
  ev.preventDefault();
  const t = ev.changedTouches[0];
  // Hide ghost so elementFromPoint sees what is underneath
  touchDrag.ghost.style.visibility = "hidden";
  const dropEl = document.elementFromPoint(t.clientX, t.clientY);
  touchDrag.ghost.remove();
  _tdClearHighlights();
  const { type, id } = touchDrag;
  touchDrag = null;
  if (type === "inventory-obj") _tdDropInventory(id, dropEl, t.clientX, t.clientY);
  else if (type === "room-obj") _tdDropRoomObj(id, dropEl);
}

function _tdOnCancel() {
  if (!touchDrag) return;
  if (touchDrag.ghost) touchDrag.ghost.remove();
  _tdClearHighlights();
  touchDrag = null;
}

function _tdDropInventory(objId, el, clientX, clientY) {
  if (!el) return;
  const roomPanel = el.closest("#viewPanel");
  if (roomPanel) {
    const point = getStagePoint(clientX, clientY, true);
    dropInventoryObject(objId, point || null);
    return;
  }
  // Drop on canvas → place at room coordinates
  if (el.closest("#roomCanvas")) {
    const point = getStagePoint(clientX, clientY, true);
    dropInventoryObject(objId, point || null);
    return;
  }
  // Drop on objects tab button → switch to objects tab then drop without coords
  const tabBtn = el.closest(".palette-tab-btn[data-tab-id='objects']");
  if (tabBtn) {
    activePaletteTab = "objects";
    renderActionPalette();
    dropInventoryObject(objId, null);
    return;
  }
  // Drop on palette buttons area when objects tab is active
  if (el.closest(".palette-buttons") && activePaletteTab === "objects") {
    dropInventoryObject(objId, null);
  }
}

function _tdDropRoomObj(entityId, el) {
  if (!el) return;
  if (el.closest("#inventoryPanel")) {
    socket.emit("message", { text: `:pick @obj:${entityId}` });
  }
}

function _tdUpdateHighlight(x, y) {
  _tdClearHighlights();
  if (!touchDrag || !touchDrag.ghost) return;
  touchDrag.ghost.style.visibility = "hidden";
  const el = document.elementFromPoint(x, y);
  touchDrag.ghost.style.visibility = "";
  if (!el) return;
  const zones = [
    touchDrag.type === "inventory-obj" ? (el.closest("#viewPanel") || el.closest("#roomCanvas")) : null,
    el.closest("#inventoryPanel") || el.closest("#inventoryList"),
    el.closest(".palette-buttons"),
    el.closest(".palette-tab-btn[data-tab-id='objects']"),
  ].filter(Boolean);
  for (const z of zones) z.classList.add("is-drag-over");
}

function _tdClearHighlights() {
  for (const el of document.querySelectorAll(".is-drag-over")) {
    el.classList.remove("is-drag-over");
  }
}
