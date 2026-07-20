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
  roomExits.innerHTML = "";
  for (const exitDef of (data.exits || [])) {
    const btn = document.createElement("button");
    btn.className = "room-exit-btn";
    btn.textContent = exitDef.label || exitDef.id;
    btn.addEventListener("click", () => socket.emit("message", { text: `.go @way:${exitDef.id}` }));
    roomExits.appendChild(btn);
  }
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
