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
var btnCharacterEditorTrigger = document.getElementById("btnCharacterEditor");
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
bindInventoryDropHandlers();
bindInventoryListPickUpHandler();
initTouchDragHandlers();


var myUsername = null;
var lastPassword = null;
var selectedActions = [];
var connectionState = "connecting";
var connectionTime = null;
var TOUCH_DRAG_THRESHOLD_PX = 8;
var CHAT_MESSAGE_TTL_MS = 30000;
var CHAT_MAX_VISIBLE = 10;
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
  mainPage.style.display = "grid";
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
    if (r.ok) {
      worldEditorAvailable = true;
      document.getElementById("btnWorldEditor").style.display = "";
      renderActionPalette();
    }
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
  activityPanel.innerHTML = `
    <div class="activity-panel-header">
      <div class="room-header-title">${title}</div>
      <button id="btnActivityPanelDismiss" class="activity-panel-dismiss" title="Dismiss">✕</button>
    </div>
    <div class="activity-panel-content">${content}</div>
  `;
  attachRefEventHandlers(activityPanel);
  const dismissBtn = document.getElementById("btnActivityPanelDismiss");
  if (dismissBtn) {
    dismissBtn.onclick = () => {
      activityPanel.style.display = "none";
    };
  }
});

socket.on("inventory_update", data => {
  renderInventoryPanel(data.items || []);
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
  const nextFloorHeight = Number(roomState.stage.floor_height);
  roomState.cameraFloorHeight = Number.isFinite(nextFloorHeight) && nextFloorHeight > 0
    ? nextFloorHeight
    : 100;
  roomState.canEditProps = !!data.can_edit_props;
  roomState.backgroundPath = data.background || "";
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
    pixiRemoveEntity(key);
    return;
  }
  roomState.entities.set(key, entity);
  pixiRenderForegroundEntity(entity);
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
