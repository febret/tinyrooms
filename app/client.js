var socket = io();

var usernameInput = document.getElementById("username");
var passwordInput = document.getElementById("password");
var btnLogin = document.getElementById("btnLogin");
var btnRegister = document.getElementById("btnRegister");
var loginStatus = document.getElementById("loginStatus");
var mainPage = document.getElementById("mainPage");
var statusDisplay = document.getElementById("statusDisplay");
var statusNameBtn = document.getElementById("statusName");
var statusNameText = document.getElementById("statusNameText");
var statusKudosBar = document.getElementById("statusKudosBar");
var statusKudosText = document.getElementById("statusKudosText");
var statusKudosProgress = document.getElementById("statusKudosProgress");
var statusKudosGive = document.getElementById("statusKudosGive");
var statusKudosGiveText = document.getElementById("statusKudosGiveText");
var statusJuice = document.getElementById("statusJuice");
var statusJuiceText = document.getElementById("statusJuiceText");
var statusConfigBtn = document.getElementById("statusConfig");
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
var lookBox = document.getElementById("lookBox");
var interactionPanel = document.getElementById("interactionPanel");
var actionPalette = document.getElementById("actionPalette");
var activityPanel = document.getElementById("activityPanel");
var roomDescriptionHtml = "";
var mobileViewportBaselineHeight = null;

if (btnWorldEditor) {
  btnWorldEditor.addEventListener("click", () => {
    const roomId = typeof roomState !== "undefined" ? roomState.roomId : null;
    const url = roomId
      ? `/world-editor?room=${encodeURIComponent(roomId)}`
      : "/world-editor";
    window.open(url, "_blank");
  });
}
bindInventoryDropHandlers();
bindInventoryListPickUpHandler();
initTouchDragHandlers();


var myUsername = null;
var lastPassword = null;
var selectedActions = [];
var connectionState = "connecting";
var connectionTime = null;
var CHAT_MESSAGE_TTL_MS = 30000;
var CHAT_MAX_VISIBLE = 10;
var CHAT_DECORATOR_MAX_CHARS = 31;
var CHAT_DECORATOR_TTL_MS = 15000;
var activeChatDecoratorHandle = null;
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
var CLIENT_COLOR_THEMES = ["default", "ocean", "sunset", "forest"];
var clientConfig = {
  showOwnChatDecorators: true,
  showTextBubbles: true,
  colorTheme: "default",
};

function normalizeClientConfig(raw) {
  const normalized = {
    showOwnChatDecorators: true,
    showTextBubbles: true,
    colorTheme: "default",
  };
  if (!raw || typeof raw !== "object") return normalized;
  if (typeof raw.show_own_chat_decorators === "boolean") {
    normalized.showOwnChatDecorators = raw.show_own_chat_decorators;
  } else if (typeof raw.showOwnChatDecorators === "boolean") {
    normalized.showOwnChatDecorators = raw.showOwnChatDecorators;
  }
  if (typeof raw.show_text_bubbles === "boolean") {
    normalized.showTextBubbles = raw.show_text_bubbles;
  } else if (typeof raw.showTextBubbles === "boolean") {
    normalized.showTextBubbles = raw.showTextBubbles;
  }
  const themeName = typeof raw.color_theme === "string"
    ? raw.color_theme
    : (typeof raw.colorTheme === "string" ? raw.colorTheme : "");
  if (CLIENT_COLOR_THEMES.includes(themeName)) {
    normalized.colorTheme = themeName;
  }
  return normalized;
}

function applyClientColorTheme(themeName) {
  const resolvedTheme = CLIENT_COLOR_THEMES.includes(themeName) ? themeName : "default";
  document.body.setAttribute("data-client-theme", resolvedTheme);
}

function applyClientConfig(rawConfig) {
  clientConfig = normalizeClientConfig(rawConfig);
  applyClientColorTheme(clientConfig.colorTheme);
  if (!clientConfig.showTextBubbles && activeChatDecoratorHandle && typeof activeChatDecoratorHandle.remove === "function") {
    activeChatDecoratorHandle.remove();
    activeChatDecoratorHandle = null;
  }
}

function setActivityPanelContent(title, contentHtml, mode) {
  if (!activityPanel) return;
  activityPanel.style.display = "flex";
  activityPanel.dataset.mode = mode || "";
  activityPanel.innerHTML = `
    <div class="activity-panel-header">
      <div class="room-header-title">${title || ""}</div>
      <button id="btnActivityPanelDismiss" class="activity-panel-dismiss" title="Dismiss">✕</button>
    </div>
    <div class="activity-panel-content">${contentHtml || ""}</div>
  `;
  attachRefEventHandlers(activityPanel);
  const dismissBtn = document.getElementById("btnActivityPanelDismiss");
  if (dismissBtn) {
    dismissBtn.onclick = () => {
      activityPanel.style.display = "none";
      activityPanel.dataset.mode = "";
    };
  }
}

function openClientConfigPanel() {
  const checkedOwn = clientConfig.showOwnChatDecorators ? " checked" : "";
  const checkedBubbles = clientConfig.showTextBubbles ? " checked" : "";
  const themeOptions = CLIENT_COLOR_THEMES
    .map(themeName => `<option value="${themeName}"${clientConfig.colorTheme === themeName ? " selected" : ""}>${themeName}</option>`)
    .join("");
  setActivityPanelContent("Client Configuration", `
    <div class="config-panel">
      <label class="config-panel-row">
        <input id="cfgShowOwnDecorators" type="checkbox"${checkedOwn}>
        <span>Show my own chat decorators</span>
      </label>
      <label class="config-panel-row">
        <input id="cfgShowTextBubbles" type="checkbox"${checkedBubbles}>
        <span>Show chat text bubbles</span>
      </label>
      <label class="config-panel-field">
        <span>Color theme</span>
        <select id="cfgColorTheme">${themeOptions}</select>
      </label>
      <div class="config-panel-actions">
        <button id="cfgSaveBtn" type="button">Save</button>
      </div>
    </div>
  `, "client-config");
  const saveBtn = document.getElementById("cfgSaveBtn");
  if (!saveBtn) return;
  saveBtn.onclick = () => {
    const showOwnDecoratorsInput = document.getElementById("cfgShowOwnDecorators");
    const showTextBubblesInput = document.getElementById("cfgShowTextBubbles");
    const colorThemeInput = document.getElementById("cfgColorTheme");
    if (!(showOwnDecoratorsInput instanceof HTMLInputElement)) return;
    if (!(showTextBubblesInput instanceof HTMLInputElement)) return;
    if (!(colorThemeInput instanceof HTMLSelectElement)) return;
    const payload = {
      show_own_chat_decorators: showOwnDecoratorsInput.checked,
      show_text_bubbles: showTextBubblesInput.checked,
      color_theme: colorThemeInput.value,
    };
    socket.emit("set_client_config", payload);
  };
}

applyClientConfig(clientConfig);

// ---------------------------------------------------------------------------
// Status bar click handlers
// ---------------------------------------------------------------------------

function _emitStatusCommand(cmd) {
  socket.emit("message", { text: cmd });
}

if (statusNameBtn) {
  statusNameBtn.addEventListener("click", () => {
    _emitStatusCommand(":level-info");
  });
}
if (statusKudosBar) {
  statusKudosBar.addEventListener("click", () => {
    _emitStatusCommand(":level-info");
  });
}
if (statusKudosGive) {
  statusKudosGive.addEventListener("click", () => {
    _emitStatusCommand(":kudos-status");
  });
}
if (statusJuice) {
  statusJuice.addEventListener("click", () => {
    _emitStatusCommand(":juice-status");
  });
}
if (statusConfigBtn) {
  statusConfigBtn.addEventListener("click", () => {
    openClientConfigPanel();
  });
}

function setLookBoxContent(contentHtml) {
  if (!lookBox) return;
  const html = (contentHtml || "").trim();
  if (!html) {
    lookBox.replaceChildren();
    lookBox.classList.remove("is-expanded");
    return;
  }

  const content = document.createElement("div");
  content.className = "look-box-content";
  content.innerHTML = html;

  const toggle = document.createElement("button");
  toggle.type = "button";
  toggle.className = "look-box-toggle";
  toggle.title = "Expand";
  toggle.textContent = "🔽";
  toggle.setAttribute("aria-label", "Expand room text");
  toggle.setAttribute("aria-expanded", "false");
  toggle.addEventListener("click", () => {
    const isExpanded = lookBox.classList.toggle("is-expanded");
    toggle.setAttribute("aria-expanded", isExpanded ? "true" : "false");
    toggle.title = isExpanded ? "Collapse" : "Expand";
  });

  lookBox.classList.remove("is-expanded");
  lookBox.replaceChildren(content, toggle);
  attachRefEventHandlers(content);
}

function showRoomDescriptionInLookBox() {
  if (roomDescriptionHtml) {
    setLookBoxContent(roomDescriptionHtml);
  }
}

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
  applyClientConfig(data.client_config || null);
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
  initCharacterEditor();
  resetCharacterEditorState();
  initObjectEditor();
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
  const rawText = String(data.text || "");
  const safeText = escapeHtml(rawText);
  const formattedText = formatText(safeText);
  addMessage(formattedText);
  maybeAttachChatDecorator(formattedText);
});

socket.on("activity_panel", data => {
  const title = escapeHtml(data.title || "");
  const content = formatText(escapeHtml(data.content || ""));
  setActivityPanelContent(title, content, data.mode || "");
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

socket.on("client_config", data => {
  applyClientConfig(data || null);
});

socket.on("update_status", data => {
  if (!data) return;

  // Username + level button
  const levelIcon = data.level_icon || "";
  const levelTitle = data.level_title || "";
  const username = data.username || myUsername || "—";
  if (statusNameText) {
    statusNameText.textContent = `${levelIcon} ${username} · ${levelTitle}`.trim();
  }

  // Kudos progress bar
  const kudosReceived = data.kudos_received || 0;
  const kudosNext = data.kudos_next_level;
  if (statusKudosText) {
    statusKudosText.textContent = `✨ ${kudosReceived}`;
  }
  if (statusKudosProgress) {
    statusKudosProgress.value = kudosReceived;
    statusKudosProgress.max = kudosNext != null ? kudosNext : kudosReceived || 1;
  }

  // Kudos-to-give indicator
  const kudosGiveRemaining = data.daily_given_remaining || 0;
  if (statusKudosGiveText) {
    statusKudosGiveText.textContent = `✨→ ${kudosGiveRemaining}`;
    if (statusKudosGive) {
      statusKudosGive.classList.toggle("kudos-give-active", kudosGiveRemaining > 0);
    }
  }

  // Juice indicator
  const juice = data.juice != null ? data.juice : 0;
  const maxJuice = data.max_juice != null ? data.max_juice : 100;
  const juicePct = maxJuice > 0 ? juice / maxJuice : 0;
  if (statusJuiceText) {
    statusJuiceText.textContent = `🧃 ${Math.floor(juice)}`;
  }
  if (statusJuice) {
    statusJuice.classList.remove("juice-high", "juice-medium", "juice-low", "juice-empty");
    if (juicePct <= 0) statusJuice.classList.add("juice-empty");
    else if (juicePct <= 0.25) statusJuice.classList.add("juice-low");
    else if (juicePct <= 0.6) statusJuice.classList.add("juice-medium");
    else statusJuice.classList.add("juice-high");
  }

  // Low-juice visual on room canvas
  if (roomCanvas) {
    roomCanvas.classList.toggle("low-juice", juicePct < 0.25 && juicePct > 0);
    roomCanvas.classList.toggle("no-juice", juicePct <= 0);
  }

  // Store for click handlers
  window._lastStatusData = data;
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
  roomDescriptionHtml = formatText(escapeHtml(data.short_description || ""));
  if (roomDescriptionHtml) {
    roomTitleOverlay.innerHTML = `<button id="roomTitleButton" class="room-title-button" type="button" title="Show room description">${label}</button>`;
    const roomTitleButton = document.getElementById("roomTitleButton");
    if (roomTitleButton) {
      roomTitleButton.addEventListener("click", showRoomDescriptionInLookBox);
    }
  } else {
    roomTitleOverlay.innerHTML = label;
  }
  if (enteringRoom && roomDescriptionHtml) {
    setLookBoxContent(roomDescriptionHtml);
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

function parseChatDecoratorCandidate(formattedText) {
  if (!formattedText) return null;
  const probe = document.createElement("div");
  probe.innerHTML = formattedText;
  const plain = (probe.textContent || "").replace(/\s+/g, " ").trim();
  if (!plain) return null;
  const refNodes = Array.from(probe.querySelectorAll("span.ref[id]"));
  const refIds = refNodes
    .map((node) => String(node.id || "").trim())
    .filter(Boolean);
  const match = plain.match(/^(.+?)\s+say(?:s)?(?: to .+?)?[:,-]\s*(.+)$/i);
  if (match) {
    const speakerLabel = (match[1] || "").trim();
    const quotedFallback = plain.match(/["“](.+?)["”]\s*$/);
    const chatText = (match[2] || quotedFallback?.[1] || plain).trim();
    return { refIds, speakerLabel, chatText };
  }
  const emoteCandidate = parseEmoteDecoratorCandidate(plain);
  if (!emoteCandidate) return null;
  return { refIds, speakerLabel: emoteCandidate.speakerLabel, chatText: emoteCandidate.chatText };
}

function escapeRegExp(text) {
  return String(text || "").replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function parseEmoteDecoratorCandidate(plainText) {
  const plain = String(plainText || "").trim();
  if (!plain) return null;
  const emoteDefs = knownEmotes && typeof knownEmotes === "object" ? Object.values(knownEmotes) : [];
  if (emoteDefs.length === 0) return null;

  const normalizedLower = plain.toLowerCase();
  const firstPersonVerbs = [];
  const thirdPersonVerbCores = [];
  for (const emoteDef of emoteDefs) {
    if (!emoteDef || typeof emoteDef !== "object") continue;
    const msgDefs = Array.isArray(emoteDef.msg) ? emoteDef.msg : [];
    for (const msgDef of msgDefs) {
      const verbs = Array.isArray(msgDef?.verb)
        ? msgDef.verb
        : (typeof msgDef?.verb === "string" ? [msgDef.verb] : []);
      const firstVerb = String(verbs[0] || "").trim();
      if (firstVerb) {
        firstPersonVerbs.push(firstVerb.toLowerCase());
      }
      const thirdVerb = String(verbs[1] || "").trim();
      if (thirdVerb && thirdVerb.includes("$0")) {
        const core = thirdVerb
          .replace(/\$0/g, "")
          .replace(/\$-?\d+/g, "")
          .replace(/\$\*/g, "")
          .replace(/\s+/g, " ")
          .trim();
        if (core) {
          thirdPersonVerbCores.push(core.toLowerCase());
        }
      }
    }
  }

  for (const firstVerbLower of firstPersonVerbs) {
    if (!firstVerbLower) continue;
    if (normalizedLower === firstVerbLower || normalizedLower.startsWith(`${firstVerbLower} `) || normalizedLower.startsWith(`${firstVerbLower}.`) || normalizedLower.startsWith(`${firstVerbLower},`) || normalizedLower.startsWith(`${firstVerbLower}!`) || normalizedLower.startsWith(`${firstVerbLower}?`)) {
      return { speakerLabel: "you", chatText: plain };
    }
  }

  for (const coreLower of thirdPersonVerbCores) {
    if (!coreLower) continue;
    const regex = new RegExp(`^(.+?)\\s+${escapeRegExp(coreLower)}(?:\\b|[\\s\\.,!?;:].*)$`, "i");
    const match = plain.match(regex);
    if (match) {
      return {
        speakerLabel: String(match[1] || "").trim(),
        chatText: plain,
      };
    }
  }
  return null;
}

function extractEmojiDecorators(text) {
  if (!text) return [];
  const emojiPattern = /\p{Extended_Pictographic}(?:\uFE0F|\uFE0E)?(?:\p{Emoji_Modifier})?(?:\u200D\p{Extended_Pictographic}(?:\uFE0F|\uFE0E)?(?:\p{Emoji_Modifier})?)*/gu;
  return Array.from(String(text).matchAll(emojiPattern), (match) => match[0]).filter(Boolean);
}

function resolveSpeakerPeepId(candidate) {
  if (!candidate) return "";
  if (Array.isArray(candidate.refIds)) {
    for (const refId of candidate.refIds) {
      const byIdKey = `peep:${refId}`;
      if (roomState.entities.has(byIdKey)) {
        return refId;
      }
      if (refId === "you" && myUsername && roomState.entities.has(`peep:${myUsername}`)) {
        return myUsername;
      }
    }
  }
  const labelSearch = (candidate.speakerLabel || "").trim().toLowerCase();
  if (!labelSearch) return "";
  if (labelSearch === "you" && myUsername) {
    return myUsername;
  }
  for (const entity of roomState.entities.values()) {
    if (entity.entity_type !== "peep") continue;
    const entityLabel = String(entity.label || entity.entity_id || "").trim().toLowerCase();
    if (entityLabel === labelSearch) {
      return String(entity.entity_id || "");
    }
  }
  return "";
}

function maybeAttachChatDecorator(formattedText) {
  if (!clientConfig.showTextBubbles) return;
  const candidate = parseChatDecoratorCandidate(formattedText);
  if (!candidate) return;
  const peepId = resolveSpeakerPeepId(candidate);
  if (!peepId) return;
  if (!clientConfig.showOwnChatDecorators && myUsername && String(peepId) === String(myUsername)) {
    return;
  }
  const emojis = extractEmojiDecorators(candidate.chatText);
  const decoratorText = emojis.length > 0
    ? emojis.slice(0, 3).join("")
    : candidate.chatText;
  if (!decoratorText) return;
  if (emojis.length === 0 && decoratorText.length > CHAT_DECORATOR_MAX_CHARS) {
    return;
  }
  if (activeChatDecoratorHandle && typeof activeChatDecoratorHandle.remove === "function") {
    activeChatDecoratorHandle.remove();
    activeChatDecoratorHandle = null;
  }
  const nextHandle = pixiAddFloatingTextToEntity("peep", peepId, decoratorText, {
    durationMs: CHAT_DECORATOR_TTL_MS,
    risePx: 0,
    fontSize: 14,
    bubble: true,
    pointerTipOffsetY: -2,
    dismissOnMove: true,
  });
  activeChatDecoratorHandle = nextHandle && typeof nextHandle.remove === "function"
    ? nextHandle
    : null;
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

function isMobileLayout() {
  return window.matchMedia("(max-width: 900px)").matches || window.matchMedia("(pointer: coarse)").matches;
}

function isKeyboardLikelyVisible() {
  if (!window.visualViewport || mobileViewportBaselineHeight == null) {
    return false;
  }
  return (mobileViewportBaselineHeight - window.visualViewport.height) > 120;
}

function updateMobileKeyboardUiState() {
  if (!interactionPanel || !msgInput) return;
  const inputFocused = document.activeElement === msgInput;
  const shouldCollapseInteractionPanel = isMobileLayout() && inputFocused && (
    !window.visualViewport || isKeyboardLikelyVisible()
  );
  document.body.classList.toggle("mobile-keyboard-open", shouldCollapseInteractionPanel);
}

if (window.visualViewport) {
  mobileViewportBaselineHeight = window.visualViewport.height;
  window.visualViewport.addEventListener("resize", () => {
    if (document.activeElement !== msgInput) {
      mobileViewportBaselineHeight = Math.max(mobileViewportBaselineHeight || 0, window.visualViewport.height);
    }
    updateMobileKeyboardUiState();
  });
}

msgInput.addEventListener("focus", () => {
  updateMobileKeyboardUiState();
});

msgInput.addEventListener("blur", () => {
  document.body.classList.remove("mobile-keyboard-open");
  if (window.visualViewport) {
    mobileViewportBaselineHeight = Math.max(mobileViewportBaselineHeight || 0, window.visualViewport.height);
  }
});

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
    const frameW = Math.max(1, Number(option.frame.width || 32));
    const frameH = Math.max(1, Number(option.frame.height || 32));
    const boxSize = 88;
    preview.style.width = `${boxSize}px`;
    preview.style.height = `${boxSize}px`;
    const canvas = document.createElement("canvas");
    canvas.width = boxSize;
    canvas.height = boxSize;
    preview.appendChild(canvas);

    const imageUrl = resolveAssetUrl(option.image_url || "");
    loadImage(imageUrl).then((img) => {
      drawSpriteThumb(
        canvas,
        img,
        Number(option.frame.x || 0),
        Number(option.frame.y || 0),
        frameW,
        frameH,
        parseBgColor(option.background_color || ""),
        10,
        true,
      );
    }).catch(() => {
      preview.style.backgroundImage = `url("${imageUrl}")`;
      preview.style.backgroundPosition = `-${option.frame.x || 0}px -${option.frame.y || 0}px`;
    });
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
  meta.textContent = option.set_label || option.label || option.sprite_id || "";
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
