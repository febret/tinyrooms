var socket = io();

var usernameInput = document.getElementById("username");
var passwordInput = document.getElementById("password");
var btnLogin = document.getElementById("btnLogin");
var btnRegister = document.getElementById("btnRegister");
var loginStatus = document.getElementById("loginStatus");
var mainPage = document.getElementById("mainPage");
var statusDisplay = document.getElementById("statusDisplay");
var messagesDiv = document.getElementById("messages");
var chatLogList = document.getElementById("chatLogList");
var msgInput = document.getElementById("msgInput");
var sendBtn = document.getElementById("sendBtn");
var btnLogout = document.getElementById("btnLogout");
var connectionIndicator = document.getElementById("connectionIndicator");
var roomTitleOverlay = document.getElementById("roomTitleOverlay");
var roomCanvas = document.getElementById("roomCanvas");
var roomExits = document.getElementById("roomExits");
var lookBox = document.getElementById("lookBox");
var actionPalette = document.getElementById("actionPalette");
var activityPanel = document.getElementById("activityPanel");


var myUsername = null;
var lastPassword = null;
var selectedActions = [];
var connectionState = "connecting";
var connectionTime = null;
var paletteMode = "main";
var knownActions = {};
var selectedTarget = null;
var TOUCH_DRAG_THRESHOLD_PX = 8;
var CHAT_MESSAGE_TTL_MS = 30000;
var CHAT_MAX_VISIBLE = 10;
var activeTouchDrag = null;
var roomState = {
  roomId: null,
  canEditProps: false,
  stage: { width: 256, height: 512 },
  backgroundPath: "",
  entities: new Map(),
  props: new Map(),
  propLibrary: new Map(),
  propLibraryWorldId: null,
};
var roomEditor = {
  enabled: false,
  saving: false,
  draftProps: new Map(),
};

var heartbeatStarted = false;
var saveLoopStarted = false;
var restAuthToken = null;
var spriteAnimationState = new Map();

socket.on("connect", () => {
  const u = usernameInput.value.trim();
  const p = lastPassword || passwordInput.value;
  if (myUsername && u && p) {
    socket.emit("login", { username: u, password: p });
  }
  if (!heartbeatStarted) {
    heartbeatStarted = true;
    setInterval(() => socket.emit("heartbeat", { timestamp: Date.now() }), 1000);
  }
  if (!saveLoopStarted) {
    saveLoopStarted = true;
    setInterval(() => saveMessagesToStorage(), 1000);
  }
});

socket.on("disconnect", () => setConnectionState("disconnected"));
socket.on("connect_error", () => setConnectionState("disconnected"));
socket.on("connected", () => setConnectionState("connected"));

socket.on("actions_def", data => {
  knownActions = data.actions || {};
  renderActionPalette();
});

socket.on("login_success", data => {
  myUsername = data.username;
  restAuthToken = data.rest_token || null;
  loginStatus.style.color = "green";
  loginStatus.textContent = "Login successful — welcome " + myUsername;
  document.getElementById("loginPage").style.display = "none";
  mainPage.style.display = "block";
  saveCredentials(usernameInput.value.trim(), lastPassword || passwordInput.value);
  loadMessagesFromStorage();
  loadInputState();
  initCharacterEditor(socket, restAuthToken);
  resetCharacterEditorState();
  initObjectEditor(socket, restAuthToken);
  resetObjectEditorState();
  ensurePropLibraryLoaded(true);
});

socket.on("login_failed", data => {
  loginStatus.style.color = "red";
  loginStatus.textContent = "Login failed: " + (data.error || "unknown");
});

socket.on("message", data => {
  const safeText = escapeHtml(data.text || "");
  addMessage(formatText(safeText));
});

socket.on("activity_panel", data => {
  const title = escapeHtml(data.title || "");
  const content = formatText(escapeHtml(data.content || ""));
  activityPanel.style.display = "block";
  activityPanel.innerHTML = `<div class="room-header-title">${title}</div><div>${content}</div>`;
});

socket.on("reload_styles", () => reloadStyle());
socket.on("reload_client", () => {
  saveInputState();
  window.location.reload();
});

socket.on("set_skin", data => {
  const skinName = data.skin || "base";
  const links = document.getElementsByTagName("link");
  for (let i = 0; i < links.length; i++) {
    const link = links[i];
    if (link.rel === "stylesheet" && link.id === "skin-style") {
      link.href = "/app/" + skinName + ".css?" + Date.now();
      break;
    }
  }
});

socket.on("update_status", data => {
  statusDisplay.innerHTML = "";
  for (const item of Object.values(data || {})) {
    const div = document.createElement("div");
    div.className = "status-item";
    div.textContent = item.label || "";
    statusDisplay.appendChild(div);
  }
});

socket.on("update_view", data => {
  const viewName = data.view;
  if (!viewName) {
    return;
  }
  if (viewName === "header") {
    handleHeaderUpdate(data);
    return;
  }
  if (viewName === "room-stage") {
    handleRoomStageUpdate(data);
    return;
  }
  if (viewName === "room-object") {
    handleRoomObjectUpdate(data);
    return;
  }
  if (viewName === "room-exits") {
    handleRoomExitsUpdate(data);
  }
});

socket.on("error", data => {
  if (roomEditor.enabled && roomEditor.saving) {
    roomEditor.saving = false;
    renderRoomEditorActivity();
  }
  addMessage("<span style='color:red'>Error: " + escapeHtml(data.error || "") + "</span>");
});

function handleHeaderUpdate(data) {
  const nextRoomId = data.room_id || null;
  const enteringRoom = roomState.roomId !== nextRoomId;
  if (enteringRoom) {
    resetRoomEntityState();
    disableRoomEditMode();
  }
  roomState.roomId = nextRoomId;
  roomState.canEditProps = !!data.can_edit_props;
  const label = formatText(escapeHtml(data.label || ""));
  const description = formatText(escapeHtml(data.short_description || ""));
  roomTitleOverlay.innerHTML = label;
  if (enteringRoom && description) {
    lookBox.innerHTML = description;
  }
}

function handleRoomStageUpdate(data) {
  roomState.stage = data.stage || { width: 256, height: 512 };
  roomState.canEditProps = !!data.can_edit_props;
  roomState.backgroundPath = data.background || "";
  roomCanvas.style.width = `${roomState.stage.width}px`;
  roomCanvas.style.height = `${roomState.stage.height}px`;
  const nextProps = new Map();
  for (const prop of (data.props || [])) {
    nextProps.set(prop.prop_instance_id, clonePropState(prop));
  }
  roomState.props = nextProps;
  if (roomEditor.enabled && roomEditor.saving) {
    disableRoomEditMode();
  } else if (!roomEditor.enabled) {
    roomEditor.draftProps = new Map();
  }
  if (roomState.propLibrary.size === 0) {
    ensurePropLibraryLoaded(false);
  }
  renderRoomStage(roomState.backgroundPath);
}

function handleRoomObjectUpdate(data) {
  const entity = data.entity || {};
  const key = `${entity.entity_type}:${entity.entity_id}`;
  if (data.change === "remove") {
    roomState.entities.delete(key);
    const domId = `room-${key.replace(":", "-")}`;
    const node = document.getElementById(domId);
    if (node) node.remove();
    _stopSpriteAnimation(domId);
    return;
  }
  roomState.entities.set(key, entity);
  renderForegroundEntity(entity);
}

function handleRoomExitsUpdate(data) {
  roomExits.innerHTML = "";
  for (const exitDef of (data.exits || [])) {
    const btn = document.createElement("button");
    btn.className = "room-exit-btn";
    btn.textContent = exitDef.label || exitDef.id;
    btn.addEventListener("click", () => socket.emit("message", { text: `.go @way:${exitDef.id}` }));
    roomExits.appendChild(btn);
  }
}

function resolveBackgroundUrl(backgroundPath) {
  if (!backgroundPath) return "";
  if (backgroundPath.startsWith("/") || backgroundPath.startsWith("http://") || backgroundPath.startsWith("https://")) {
    return backgroundPath;
  }
  return "/world/images/" + backgroundPath;
}

function resolveAssetUrl(assetPath) {
  if (!assetPath) return "";
  if (assetPath.startsWith("/") || assetPath.startsWith("http://") || assetPath.startsWith("https://")) {
    return assetPath;
  }
  return "/world/" + assetPath;
}

function _stopSpriteAnimation(key) {
  const state = spriteAnimationState.get(key);
  if (state && state.timer) {
    clearInterval(state.timer);
  }
  spriteAnimationState.delete(key);
}

function _applyFrameToNode(frameNode, frame) {
  if (!frameNode || !frame) return;
  frameNode.style.width = `${frame.width || 32}px`;
  frameNode.style.height = `${frame.height || 32}px`;
  frameNode.style.backgroundPosition = `-${frame.x || 0}px -${frame.y || 0}px`;
}

function _renderEntityDisplay(node, entity, domKey) {
  const display = entity.display || {};
  const spriteMeta = display.sprite_meta || display.img_meta || null;
  const imageUrl = resolveAssetUrl(display.sprite || display.img || "");
  if (!spriteMeta || !spriteMeta.frame) {
    _stopSpriteAnimation(domKey);
    let img = node.querySelector("img");
    if (!img) {
      img = document.createElement("img");
      node.innerHTML = "";
      node.appendChild(img);
    }
    img.src = imageUrl;
    img.alt = entity.label || "";
    return;
  }

  let spriteNode = node.querySelector(".room-entity-sprite");
  if (!spriteNode) {
    spriteNode = document.createElement("div");
    spriteNode.className = "room-entity-sprite";
    node.innerHTML = "";
    node.appendChild(spriteNode);
  }
  spriteNode.style.backgroundImage = `url("${imageUrl}")`;
  spriteNode.style.backgroundRepeat = "no-repeat";
  _applyFrameToNode(spriteNode, spriteMeta.frame);

  const anim = spriteMeta.animation;
  if (!anim || !Array.isArray(anim.frames) || anim.frames.length <= 1) {
    _stopSpriteAnimation(domKey);
    return;
  }
  _stopSpriteAnimation(domKey);
  let index = 0;
  let direction = 1;
  const intervalMs = Math.max(40, Number(anim.speed || 0.5) * 1000);
  const timer = setInterval(() => {
    const frames = anim.frames;
    if (!frames.length) return;
    if (anim.type === "random") {
      index = Math.floor(Math.random() * frames.length);
    } else if (anim.type === "bounce") {
      index += direction;
      if (index >= frames.length) {
        index = Math.max(0, frames.length - 2);
        direction = -1;
      } else if (index < 0) {
        index = Math.min(frames.length - 1, 1);
        direction = 1;
      }
    } else {
      index = (index + 1) % frames.length;
    }
    _applyFrameToNode(spriteNode, frames[index]);
  }, intervalMs);
  spriteAnimationState.set(domKey, { timer });
}

function renderRoomStage(backgroundPath) {
  spriteAnimationState.forEach((_value, key) => _stopSpriteAnimation(key));
  roomCanvas.innerHTML = "";
  const stageLayer = document.createElement("div");
  stageLayer.className = "room-layer";
  if (backgroundPath) {
    const bg = document.createElement("img");
    bg.className = "room-background";
    bg.src = resolveBackgroundUrl(backgroundPath);
    stageLayer.appendChild(bg);
  }
  for (const prop of getEditableProps().values()) {
    stageLayer.appendChild(makePropNode(prop));
  }
  const fgLayer = document.createElement("div");
  fgLayer.className = "room-layer";
  fgLayer.id = "foregroundLayer";
  if (roomEditor.enabled) {
    fgLayer.style.pointerEvents = "none";
  }
  roomCanvas.appendChild(stageLayer);
  roomCanvas.appendChild(fgLayer);
  roomCanvas.ondragover = e => e.preventDefault();
  roomCanvas.ondrop = handleRoomDrop;
  if (!roomEditor.enabled) {
    for (const entity of roomState.entities.values()) {
      renderForegroundEntity(entity);
    }
  }
  renderRoomEditorActivity();
}

function renderForegroundEntity(entity) {
  if (roomEditor.enabled) {
    return;
  }
  const layer = document.getElementById("foregroundLayer");
  if (!layer) return;
  const key = `${entity.entity_type}:${entity.entity_id}`;
  const domId = `room-${key.replace(":", "-")}`;
  let node = document.getElementById(domId);
  if (!node) {
    node = document.createElement("div");
    node.id = domId;
    node.className = "room-entity room-selectable";
    layer.appendChild(node);
  }

  node.className = "room-entity room-selectable" + (entity.is_self ? " self" : "");
  node.style.left = `${entity.position?.x || 0}px`;
  node.style.top = `${entity.position?.y || 0}px`;
  node.style.zIndex = `${entity.position?.z_order || 0}`;
  _renderEntityDisplay(node, entity, domId);
  node.onclick = () => selectTarget({
    type: entity.entity_type,
    id: entity.entity_id,
    label: entity.label || entity.entity_id,
    description: entity.description || "",
  }, node);

  configureDragHandlers(node, entity.entity_type, entity.entity_id, canDragEntity(entity));
}

function canDragEntity(entity) {
  if (roomEditor.enabled) {
    return false;
  }
  if (entity.entity_type === "object") {
    return true;
  }
  if (entity.entity_type === "peep") {
    return entity.owner_username === myUsername || roomState.canEditProps;
  }
  return false;
}

function beginDrag(ev, entityType, entityId) {
  if (ev.target instanceof Element && ev.target.closest(".room-prop-controls")) {
    ev.preventDefault();
    return;
  }
  const dragSource = ev.currentTarget instanceof HTMLElement ? ev.currentTarget : ev.target;
  const ghost = dragSource.cloneNode(true);
  ghost.style.opacity = "0.45";
  ghost.style.position = "absolute";
  ghost.style.top = "-1000px";
  document.body.appendChild(ghost);
  ev.dataTransfer.setDragImage(ghost, ghost.clientWidth / 2, ghost.clientHeight / 2);
  setTimeout(() => ghost.remove(), 0);
  ev.dataTransfer.setData("text/plain", JSON.stringify({ entityType, entityId }));
}

function handleRoomDrop(ev) {
  ev.preventDefault();
  const raw = ev.dataTransfer.getData("text/plain");
  if (!raw) return;
  const payload = JSON.parse(raw);
  submitMovePayload(payload, ev.clientX, ev.clientY, false);
}

function resetRoomEntityState() {
  spriteAnimationState.forEach((_value, key) => _stopSpriteAnimation(key));
  roomState.entities.clear();
  selectedTarget = null;
  lookBox.textContent = "";
  document.querySelectorAll(".room-selected").forEach(el => el.classList.remove("room-selected"));
  const layer = document.getElementById("foregroundLayer");
  if (layer) {
    layer.innerHTML = "";
  }
}

function getStagePoint(clientX, clientY, requireInside) {
  const rect = roomCanvas.getBoundingClientRect();
  if (!rect.width || !rect.height) {
    return null;
  }
  const isInside = clientX >= rect.left && clientX <= rect.right && clientY >= rect.top && clientY <= rect.bottom;
  if (requireInside && !isInside) {
    return null;
  }
  const x = Math.round((clientX - rect.left) * (roomState.stage.width / rect.width));
  const y = Math.round((clientY - rect.top) * (roomState.stage.height / rect.height));
  return {
    x: Math.min(roomState.stage.width, Math.max(0, x)),
    y: Math.min(roomState.stage.height, Math.max(0, y)),
  };
}

function submitMovePayload(payload, clientX, clientY, requireInside) {
  const point = getStagePoint(clientX, clientY, requireInside);
  if (!point) return;
  if (payload.entityType === "prop") {
    if (roomEditor.enabled) {
      const draft = roomEditor.draftProps.get(payload.entityId);
      if (!draft) return;
      draft.position = draft.position || {};
      draft.position.x = point.x;
      draft.position.y = point.y;
      draft.position.z_order = nextDraftZOrder();
      roomEditor.draftProps.set(payload.entityId, draft);
      renderRoomStage(roomState.backgroundPath);
      return;
    }
    socket.emit("room_edit_prop", { prop_instance_id: payload.entityId, x: point.x, y: point.y });
    return;
  }
  socket.emit("room_move_entity", {
    entity_type: payload.entityType,
    entity_id: payload.entityId,
    x: point.x,
    y: point.y,
  });
}

function configureDragHandlers(node, entityType, entityId, isEnabled) {
  node.draggable = !!isEnabled;
  node.ondragstart = null;
  node.onpointerdown = null;
  node.style.touchAction = isEnabled ? "none" : "";
  if (!isEnabled) {
    return;
  }
  node.ondragstart = ev => beginDrag(ev, entityType, entityId);
  node.onpointerdown = ev => beginTouchDrag(ev, entityType, entityId);
}

function beginTouchDrag(ev, entityType, entityId) {
  if (ev.pointerType !== "touch") return;
  ev.preventDefault();
  if (activeTouchDrag) {
    cleanupTouchDrag();
  }
  const node = ev.currentTarget;
  activeTouchDrag = {
    pointerId: ev.pointerId,
    startX: ev.clientX,
    startY: ev.clientY,
    entityType,
    entityId,
    node,
    moved: false,
    ghost: null,
  };
  if (node.setPointerCapture) {
    node.setPointerCapture(ev.pointerId);
  }
  document.addEventListener("pointermove", handleTouchDragMove, { passive: false });
  document.addEventListener("pointerup", handleTouchDragEnd, { passive: false });
  document.addEventListener("pointercancel", handleTouchDragCancel, { passive: false });
}

function ensureTouchDragGhost() {
  if (!activeTouchDrag || activeTouchDrag.ghost) return;
  const ghost = activeTouchDrag.node.cloneNode(true);
  ghost.style.position = "fixed";
  ghost.style.pointerEvents = "none";
  ghost.style.zIndex = "5000";
  ghost.style.opacity = "0.75";
  ghost.style.transform = "translate(-50%, -50%)";
  document.body.appendChild(ghost);
  activeTouchDrag.ghost = ghost;
}

function handleTouchDragMove(ev) {
  if (!activeTouchDrag || ev.pointerId !== activeTouchDrag.pointerId) return;
  ev.preventDefault();
  const movedDistance = Math.hypot(ev.clientX - activeTouchDrag.startX, ev.clientY - activeTouchDrag.startY);
  if (movedDistance >= TOUCH_DRAG_THRESHOLD_PX) {
    activeTouchDrag.moved = true;
    ensureTouchDragGhost();
  }
  if (activeTouchDrag.ghost) {
    activeTouchDrag.ghost.style.left = `${ev.clientX}px`;
    activeTouchDrag.ghost.style.top = `${ev.clientY}px`;
  }
}

function handleTouchDragEnd(ev) {
  if (!activeTouchDrag || ev.pointerId !== activeTouchDrag.pointerId) return;
  ev.preventDefault();
  const drag = activeTouchDrag;
  cleanupTouchDrag();
  if (drag.moved) {
    submitMovePayload({ entityType: drag.entityType, entityId: drag.entityId }, ev.clientX, ev.clientY, true);
    return;
  }
  drag.node.click();
}

function handleTouchDragCancel(ev) {
  if (!activeTouchDrag || ev.pointerId !== activeTouchDrag.pointerId) return;
  ev.preventDefault();
  cleanupTouchDrag();
}

function cleanupTouchDrag() {
  document.removeEventListener("pointermove", handleTouchDragMove);
  document.removeEventListener("pointerup", handleTouchDragEnd);
  document.removeEventListener("pointercancel", handleTouchDragCancel);
  if (activeTouchDrag?.ghost) {
    activeTouchDrag.ghost.remove();
  }
  activeTouchDrag = null;
}

function selectTarget(target, node) {
  selectedTarget = target;
  document.querySelectorAll(".room-selected").forEach(el => el.classList.remove("room-selected"));
  if (node) node.classList.add("room-selected");
  lookBox.innerHTML = `<strong>${escapeHtml(target.label || "")}</strong>: ${escapeHtml(target.description || "")}`;
}


function renderActionPalette() {
  actionPalette.innerHTML = "";
  const entries = getPaletteEntries();
  for (const item of entries) {
    const btn = document.createElement("button");
    btn.className = "palette-btn";
    btn.textContent = item.label;
    btn.onclick = item.onClick;
    actionPalette.appendChild(btn);
  }
}

function getPaletteEntries() {
  if (paletteMode === "emote") {
    const emotes = Object.entries(knownActions).filter(([id]) => id.startsWith("emotes.")).slice(0, 5);
    const buttons = emotes.map(([id, def]) => ({
      label: def.label || id,
      onClick: () => sendAction(id),
    }));
    buttons.push({ label: "Back", onClick: () => { paletteMode = "main"; renderActionPalette(); } });
    return buttons;
  }
  if (paletteMode === "extras") {
    return [
      { label: "Create Thing", onClick: () => openObjectCreator() },
      { label: roomEditor.enabled ? "Editing Room" : "Edit Room", onClick: () => enableRoomEditMode() },
      { label: "Back", onClick: () => { paletteMode = "main"; renderActionPalette(); } },
    ];
  }
  return [
    { label: "Look", onClick: () => sendAction("basic.look") },
    { label: "Use", onClick: () => sendAction("basic.use") },
    { label: "Emote", onClick: () => { paletteMode = "emote"; renderActionPalette(); } },
    { label: "Equip", onClick: () => requestActivity("equip") },
    { label: "Self", onClick: () => requestActivity("self") },
    { label: "Extras", onClick: () => { paletteMode = "extras"; renderActionPalette(); } },
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

function requestActivity(mode) {
  socket.emit("request_activity_panel", { mode });
}

function showLocalActivity(mode, text) {
  activityPanel.style.display = "block";
  activityPanel.innerHTML = `<div class="room-header-title">${escapeHtml(mode)}</div><div>${escapeHtml(text)}</div>`;
}

function reloadStyle() {
  const links = document.getElementsByTagName("link");
  for (let i = 0; i < links.length; i++) {
    const link = links[i];
    if (link.rel === "stylesheet") {
      link.href += "?";
    }
  }
}

function addMessage(text, cls) {
  const div = createChatMessageNode(text, cls);
  chatLogList.appendChild(div);
  window.setTimeout(() => beginMessageExit(div), CHAT_MESSAGE_TTL_MS);
  trimVisibleMessages();
  messagesDiv.scrollTop = messagesDiv.scrollHeight;
}

function restoreChatMessage(text, cls) {
  const div = createChatMessageNode(text, cls);
  chatLogList.appendChild(div);
  window.setTimeout(() => beginMessageExit(div), CHAT_MESSAGE_TTL_MS);
  trimVisibleMessages();
}

function createChatMessageNode(text, cls) {
  const div = document.createElement("div");
  div.className = `msg chat-log-message ${(cls || "").replace(/\bis-expiring\b/g, "").trim()}`.trim();
  div.innerHTML = text;
  const selfSpans = div.querySelectorAll("span.self");
  selfSpans.forEach(span => {
    span.textContent = "you";
  });
  attachRefEventHandlers(div);
  div.addEventListener("animationend", ev => {
    if (ev.animationName === "chatMessageOut" && div.classList.contains("is-expiring")) {
      div.remove();
    }
  });
  return div;
}

function trimVisibleMessages() {
  const visibleMessages = Array.from(chatLogList.querySelectorAll(".chat-log-message:not(.is-expiring)"));
  const overflow = visibleMessages.length - CHAT_MAX_VISIBLE;
  for (let i = 0; i < overflow; i++) {
    beginMessageExit(visibleMessages[i]);
  }
}

function beginMessageExit(node) {
  if (!node || !node.parentElement || node.classList.contains("is-expiring")) {
    return;
  }
  node.classList.add("is-expiring");
}

function setConnectionState(state) {
  connectionState = state;
  connectionIndicator.className = `connection-indicator ${state}`;
  if (state === "connected") {
    connectionTime = new Date();
  }
}

function showConnectionInfo() {
  let info = `<span class='system'>Connection Status: ${connectionState}</span>`;
  if (connectionState === "connected" && connectionTime) {
    const duration = Math.floor((new Date() - connectionTime) / 1000);
    info += `<br><span class='system'>Connected for ${duration} seconds</span>`;
  }
  if (socket.id) {
    info += `<br><span class='system'>Socket ID: ${socket.id}</span>`;
  }
  addMessage(info);
}

connectionIndicator.addEventListener("click", showConnectionInfo);

sendBtn.addEventListener("click", () => {
  const text = msgInput.value.trim();
  if (!text) return;
  playBopSound();
  socket.emit("message", { text });
  msgInput.value = "";
});

msgInput.addEventListener("keydown", ev => {
  if (ev.key === "Enter") {
    sendBtn.click();
  }
});
