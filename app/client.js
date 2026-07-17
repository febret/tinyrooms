const socket = io();

const usernameInput = document.getElementById("username");
const passwordInput = document.getElementById("password");
const btnLogin = document.getElementById("btnLogin");
const btnRegister = document.getElementById("btnRegister");
const loginStatus = document.getElementById("loginStatus");
const mainPage = document.getElementById("mainPage");
const statusDisplay = document.getElementById("statusDisplay");
const messagesDiv = document.getElementById("messages");
const msgInput = document.getElementById("msgInput");
const sendBtn = document.getElementById("sendBtn");
const btnLogout = document.getElementById("btnLogout");
const connectionIndicator = document.getElementById("connectionIndicator");
const roomHeader = document.getElementById("roomHeader");
const roomCanvas = document.getElementById("roomCanvas");
const roomExits = document.getElementById("roomExits");
const lookBox = document.getElementById("lookBox");
const actionPalette = document.getElementById("actionPalette");
const activityPanel = document.getElementById("activityPanel");

let myUsername = null;
let lastPassword = null;
let selectedActions = [];
let connectionState = "connecting";
let connectionTime = null;
let paletteMode = "main";
let knownActions = {};
let selectedTarget = null;
let roomState = {
  roomId: null,
  canEditProps: false,
  stage: { width: 256, height: 512 },
  entities: new Map(),
  props: new Map(),
};

let heartbeatStarted = false;
let saveLoopStarted = false;

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
  loginStatus.style.color = "green";
  loginStatus.textContent = "Login successful — welcome " + myUsername;
  document.getElementById("loginPage").style.display = "none";
  mainPage.style.display = "block";
  saveCredentials(usernameInput.value.trim(), lastPassword || passwordInput.value);
  loadMessagesFromStorage();
  loadInputState();
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
  addMessage("<span style='color:red'>Error: " + escapeHtml(data.error || "") + "</span>");
});

function handleHeaderUpdate(data) {
  roomState.roomId = data.room_id || null;
  roomState.canEditProps = !!data.can_edit_props;
  const label = formatText(escapeHtml(data.label || ""));
  const description = formatText(escapeHtml(data.short_description || ""));
  roomHeader.innerHTML = `<div class="room-header-title">${label}</div><div>${description}</div>`;
}

function handleRoomStageUpdate(data) {
  roomState.stage = data.stage || { width: 256, height: 512 };
  roomState.canEditProps = !!data.can_edit_props;
  roomCanvas.style.width = `${roomState.stage.width}px`;
  roomCanvas.style.height = `${roomState.stage.height}px`;
  roomState.props.clear();
  for (const prop of (data.props || [])) {
    roomState.props.set(prop.prop_instance_id, prop);
  }
  renderRoomStage(data.background || "");
}

function handleRoomObjectUpdate(data) {
  const entity = data.entity || {};
  const key = `${entity.entity_type}:${entity.entity_id}`;
  if (data.change === "remove") {
    roomState.entities.delete(key);
    const node = document.getElementById(`room-${key.replace(":", "-")}`);
    if (node) node.remove();
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

function renderRoomStage(backgroundPath) {
  roomCanvas.innerHTML = "";
  const stageLayer = document.createElement("div");
  stageLayer.className = "room-layer";
  if (backgroundPath) {
    const bg = document.createElement("img");
    bg.className = "room-background";
    bg.src = "/world/images/" + backgroundPath;
    stageLayer.appendChild(bg);
  }
  for (const prop of roomState.props.values()) {
    stageLayer.appendChild(makePropNode(prop));
  }
  const fgLayer = document.createElement("div");
  fgLayer.className = "room-layer";
  fgLayer.id = "foregroundLayer";
  roomCanvas.appendChild(stageLayer);
  roomCanvas.appendChild(fgLayer);
  roomCanvas.ondragover = e => e.preventDefault();
  roomCanvas.ondrop = handleRoomDrop;
  for (const entity of roomState.entities.values()) {
    renderForegroundEntity(entity);
  }
}

function makePropNode(prop) {
  const node = document.createElement("div");
  node.className = "room-prop room-selectable";
  node.id = `prop-${prop.prop_instance_id}`;
  node.style.left = `${prop.position?.x || 0}px`;
  node.style.top = `${prop.position?.y || 0}px`;
  node.style.zIndex = `${prop.position?.z_order || 0}`;
  const img = document.createElement("img");
  img.src = "/world/" + (prop.display?.sprite || prop.display?.img || "");
  img.alt = prop.label || "";
  node.appendChild(img);
  node.addEventListener("click", () => selectTarget({
    type: "prop",
    id: prop.prop_instance_id,
    label: prop.label || "prop",
    description: prop.description || "",
  }, node));
  if (roomState.canEditProps) {
    node.draggable = true;
    node.addEventListener("dragstart", ev => beginDrag(ev, "prop", prop.prop_instance_id));
  }
  return node;
}

function renderForegroundEntity(entity) {
  const layer = document.getElementById("foregroundLayer");
  if (!layer) return;
  const key = `${entity.entity_type}:${entity.entity_id}`;
  const domId = `room-${key.replace(":", "-")}`;
  let node = document.getElementById(domId);
  if (!node) {
    node = document.createElement("div");
    node.id = domId;
    node.className = "room-entity room-selectable";
    const img = document.createElement("img");
    node.appendChild(img);
    layer.appendChild(node);
  }

  node.className = "room-entity room-selectable" + (entity.is_self ? " self" : "");
  node.style.left = `${entity.position?.x || 0}px`;
  node.style.top = `${entity.position?.y || 0}px`;
  node.style.zIndex = `${entity.position?.z_order || 0}`;
  const img = node.querySelector("img");
  img.src = "/world/" + (entity.display?.sprite || entity.display?.img || "");
  img.alt = entity.label || "";
  node.onclick = () => selectTarget({
    type: entity.entity_type,
    id: entity.entity_id,
    label: entity.label || entity.entity_id,
    description: entity.description || "",
  }, node);

  node.draggable = canDragEntity(entity);
  if (node.draggable) {
    node.ondragstart = ev => beginDrag(ev, entity.entity_type, entity.entity_id);
  }
}

function canDragEntity(entity) {
  if (entity.entity_type === "object") {
    return true;
  }
  if (entity.entity_type === "peep") {
    return entity.owner_username === myUsername || roomState.canEditProps;
  }
  return false;
}

function beginDrag(ev, entityType, entityId) {
  const ghost = ev.target.cloneNode(true);
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
  const rect = roomCanvas.getBoundingClientRect();
  const x = Math.max(0, Math.round((ev.clientX - rect.left) * (roomState.stage.width / rect.width)));
  const y = Math.max(0, Math.round((ev.clientY - rect.top) * (roomState.stage.height / rect.height)));

  if (payload.entityType === "prop") {
    socket.emit("room_edit_prop", { prop_instance_id: payload.entityId, x, y });
    return;
  }
  socket.emit("room_move_entity", {
    entity_type: payload.entityType,
    entity_id: payload.entityId,
    x,
    y,
  });
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
      { label: "Placeholder", onClick: () => showLocalActivity("extras", "TODO: extras set customization is unspecified.") },
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
  const div = document.createElement("div");
  div.className = "msg " + (cls || "");
  div.innerHTML = text;
  messagesDiv.appendChild(div);
  const allMessages = messagesDiv.querySelectorAll(".msg");
  if (allMessages.length > 50) {
    const removeCount = allMessages.length - 50;
    for (let i = 0; i < removeCount; i++) {
      allMessages[i].remove();
    }
  }
  const selfSpans = div.querySelectorAll("span.self");
  selfSpans.forEach(span => {
    span.textContent = "you";
  });
  attachRefEventHandlers(div);
  messagesDiv.scrollTop = messagesDiv.scrollHeight;
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
