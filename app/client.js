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
var btnWorldEditor = document.getElementById("btnWorldEditor");
var connectionIndicator = document.getElementById("connectionIndicator");
var roomTitleOverlay = document.getElementById("roomTitleOverlay");
var roomCanvas = document.getElementById("roomCanvas");
var roomExits = document.getElementById("roomExits");
var lookBox = document.getElementById("lookBox");
var actionPalette = document.getElementById("actionPalette");
var activityPanel = document.getElementById("activityPanel");

if (btnWorldEditor) {
  btnWorldEditor.addEventListener("click", () => window.open("/world-editor", "_blank"));
}


var myUsername = null;
var lastPassword = null;
var selectedActions = [];
var connectionState = "connecting";
var connectionTime = null;
var paletteMode = "main";
var knownActions = {};
var knownEmotes = {};
var selectedTarget = null;
var TOUCH_DRAG_THRESHOLD_PX = 8;
var CHAT_MESSAGE_TTL_MS = 30000;
var CHAT_MAX_VISIBLE = 10;
var activeTouchDrag = null;
var roomState = {
  roomId: null,
  canEditProps: false,
  canClaimRoom: false,
  stage: {
    type: 'basic',
    width: 400,
    height: 300,
    bg_height: 200,
    floor_height: 100,
    background_mode: 'tile',
    floor_image: '',
  },
  cameraFloorHeight: 100,
  backgroundPath: "",
  entities: new Map(),
  props: new Map(),
  propLibrary: new Map(),
  propLibraryWorldId: null,
  exits: [],
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

socket.on("emotes_def", data => {
  knownEmotes = data.emotes || {};
  renderActionPalette();
});

socket.on("login_success", data => {
  myUsername = data.username;
  restAuthToken = data.rest_token || null;
  if (restAuthToken) {
    localStorage.setItem("tr_rest_auth_token", restAuthToken);
  }
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
  // Show World Editor button if the feature is available
  fetch("/world-editor", { method: "HEAD" }).then(r => {
    if (r.ok) document.getElementById("btnWorldEditor").style.display = "";
  }).catch(() => {});
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

socket.on("inventory_update", data => {
  renderInventoryPanel(data.items || []);
});

function renderInventoryPanel(items) {
  const inventoryList = document.getElementById("inventoryList");
  if (!inventoryList) return;
  inventoryList.innerHTML = "";
  if (items.length === 0) {
    inventoryList.innerHTML = '<div class="inventory-empty">Empty</div>';
    return;
  }
  for (const item of items) {
    const row = document.createElement("div");
    row.className = "inventory-item";

    const icon = document.createElement("div");
    icon.className = "inventory-item-icon";
    const iconUrl = item.display && (item.display.icon || item.display.img || item.display.sprite);
    if (iconUrl) {
      const img = document.createElement("img");
      img.src = resolveAssetUrl(iconUrl);
      img.alt = item.label || "";
      icon.appendChild(img);
    }
    row.appendChild(icon);

    const info = document.createElement("div");
    info.className = "inventory-item-info";
    const labelEl = document.createElement("div");
    labelEl.className = "inventory-item-label";
    labelEl.textContent = item.label || item.obj_id;
    info.appendChild(labelEl);
    row.appendChild(info);

    const dropBtn = document.createElement("button");
    dropBtn.className = "inventory-drop-btn";
    dropBtn.textContent = "Drop";
    dropBtn.addEventListener("click", () => {
      socket.emit("room_drop_object", { obj_id: item.obj_id });
    });
    row.appendChild(dropBtn);

    inventoryList.appendChild(row);
  }
}

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
  roomState.canClaimRoom = !!data.can_claim_room;
  const label = formatText(escapeHtml(data.label || ""));
  const description = formatText(escapeHtml(data.short_description || ""));
  roomTitleOverlay.innerHTML = label;
  if (enteringRoom && description) {
    lookBox.innerHTML = description;
  }
}

function handleRoomStageUpdate(data) {
  roomState.stage = data.stage || {
    type: 'basic', width: 400, height: 300, bg_height: 200,
    floor_height: 100, background_mode: 'tile', floor_image: '',
  };
  roomState.cameraFloorHeight = roomState.stage.floor_height || 100;
  roomState.canEditProps = !!data.can_edit_props;
  roomState.backgroundPath = data.background || "";
  const totalHeight = getStageTotalHeight(roomState.stage, roomState.cameraFloorHeight);
  roomCanvas.style.width = `${roomState.stage.width}px`;
  roomCanvas.style.height = `${totalHeight}px`;
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
  // Store exits for the room editor; no longer render overlay buttons.
  roomState.exits = data.exits || [];
}

function clearRoomSelection() {
  document.querySelectorAll(".room-selected").forEach(el => el.classList.remove("room-selected"));
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
  if (node) node.classList.add("room-selected");
  lookBox.innerHTML = `<strong>${escapeHtml(target.label || "")}</strong>: ${escapeHtml(target.description || "")}`;
  if (paletteMode === "main") renderActionPalette();
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
    const emotes = Object.entries(knownEmotes).filter(([id]) => id !== "say");
    const buttons = emotes.map(([id, def]) => ({
      label: def.label || id,
      onClick: () => sendEmote(id),
    }));
    buttons.push({ label: "Back", onClick: () => { paletteMode = "main"; renderActionPalette(); } });
    return buttons;
  }
  if (paletteMode === "extras") {
    const entries = [
      { label: "Create Thing", onClick: () => openObjectCreator() },
      { label: roomEditor.enabled ? "Editing Room" : "Edit Room", onClick: () => enableRoomEditMode() },
    ];
    if (roomState.stage.type === 'standard') {
      entries.push({ label: "Camera Near", onClick: () => { setCameraFloorHeight(200); paletteMode = "main"; renderActionPalette(); } });
      entries.push({ label: "Camera Mid", onClick: () => { setCameraFloorHeight(100); paletteMode = "main"; renderActionPalette(); } });
      entries.push({ label: "Camera Far", onClick: () => { setCameraFloorHeight(10); paletteMode = "main"; renderActionPalette(); } });
    }
    entries.push({ label: "Back", onClick: () => { paletteMode = "main"; renderActionPalette(); } });
    return entries;
  }
  return [
    { label: "Look", onClick: () => sendAction("basic.look") },
    { label: "Use", onClick: () => sendAction("basic.use") },
    ...(selectedTarget && selectedTarget.type === "object"
      ? [{ label: "Pick Up", onClick: () => pickUpSelectedObject() }]
      : []),
    ...(selectedTarget && selectedTarget.type === "prop" && selectedTarget.exit_way_id
      ? [{ label: `Go: ${selectedTarget.exit_label || "Exit"}`, onClick: () => navigateExit(selectedTarget.exit_way_id) }]
      : []),
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

function sendEmote(emoteId) {
  let cmd = `.${emoteId}`;
  if (selectedTarget) {
    if (selectedTarget.type === "peep") cmd += `@${selectedTarget.id}`;
    else if (selectedTarget.type === "object") cmd += ` @obj:${selectedTarget.id}`;
    else if (selectedTarget.type === "prop") cmd += ` @prop:${selectedTarget.id}`;
  }
  paletteMode = "main";
  renderActionPalette();
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

function addMessage(text, cls, scroll = true) {
  const div = createChatMessageNode(text, cls);
  chatLogList.appendChild(div);
  window.setTimeout(() => beginMessageExit(div), CHAT_MESSAGE_TTL_MS);
  trimVisibleMessages();
  if (scroll) messagesDiv.scrollTop = messagesDiv.scrollHeight;
}

function restoreChatMessage(text, cls) {
  addMessage(text, cls, false);
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

function getRestToken() {
  return restAuthToken;
}

async function fetchJson(path, options = {}, token) {
  const headers = { ...(options.headers || {}) };
  const authToken = token !== undefined ? token : restAuthToken;
  if (authToken) {
    headers["X-TR-Auth"] = authToken;
  }
  const response = await fetch(path, { ...options, headers });
  const payload = await response.json();
  if (!response.ok || payload.ok === false) {
    throw new Error(payload.error || `request failed: ${response.status}`);
  }
  return payload;
}

function createSpritePreview(option) {
  const preview = document.createElement("div");
  preview.className = "character-sprite-preview";
  if (option.frame) {
    preview.classList.add("character-sprite-preview-frame");
    preview.style.width = `${option.frame.width || 32}px`;
    preview.style.height = `${option.frame.height || 32}px`;
    preview.style.backgroundImage = `url("${resolveAssetUrl(option.image_url || "")}")`;
    preview.style.backgroundPosition = `-${option.frame.x || 0}px -${option.frame.y || 0}px`;
    if (option.background_color) {
      preview.style.backgroundColor = option.background_color;
    }
    return preview;
  }
  const img = document.createElement("img");
  img.src = resolveAssetUrl(option.image_url || "");
  img.alt = option.label || option.sprite_id || "sprite";
  preview.appendChild(img);
  return preview;
}

function createSpriteCard(option, isSelected, onSelect, disabled) {
  const card = document.createElement("button");
  card.type = "button";
  card.className = "character-sprite-card";
  if (isSelected) card.classList.add("selected");
  card.disabled = !!disabled;
  card.addEventListener("click", () => onSelect(option));
  card.appendChild(createSpritePreview(option));
  const label = document.createElement("div");
  label.className = "character-sprite-label";
  label.textContent = option.label || option.sprite_id || option.filename || "sprite";
  card.appendChild(label);
  const meta = document.createElement("div");
  meta.className = "character-sprite-meta";
  meta.textContent = `${option.scope}:${option.filename}/${option.sprite_id}`;
  card.appendChild(meta);
  return card;
}

async function withEditorBusy(stateRef, flagKey, errorEl, renderFn, asyncFn) {
  errorEl.textContent = "";
  stateRef[flagKey] = true;
  renderFn();
  try {
    await asyncFn();
  } catch (err) {
    errorEl.textContent = err.message;
  } finally {
    stateRef[flagKey] = false;
    renderFn();
  }
}
