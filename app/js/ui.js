import { createApiClient } from "./api.js";
import { createActivityManager } from "./activities.js";
import { playSound } from "./audio.js";
import { createBoard } from "./board.js";
import { createCardsView, describeSelection, selectionActions } from "./cards.js";
import { COMMANDS, buildQuantityCommand, chatToCommand } from "./commands.js";
import { createDialogs } from "./dialogs.js";
import { createPeepsView } from "./peeps.js";
import { escapeHtml, updateMarkup } from "./presentation.js";
import { createSocketClient } from "./socket.js";
import { createStore } from "./state.js";

const store = createStore();
const api = createApiClient();
const $ = selector => document.querySelector(selector);
const root = $("#app");
const panelLayer = $("#panel-layer");
const detailLayer = $("#detail-layer");
const activityLayer = $("#activity-layer");
const authLayer = $("#auth-layer");
const chatInput = $("#chat-input");
const settings = $("#settings");
const dialogs = createDialogs($("#global-modal-layer"));
const timedToasts = new Set();
let socket = null;
let paletteClose = null;
let paletteShade = null;
let commandSearch = "";
let authKey = "";
let previousUser = null;
let previousRoom = null;
let previousView = null;
let previousDetails = null;
let renderRevision = 0;
let refreshPromise = null;

function playTone(kind = "tap") {
  playSound(kind, store.getState().ui.soundEnabled);
}

function toast(message, tone = "info") {
  store.dispatch({ type: "toast", message, tone });
}

function showError(error) {
  if (error?.name === "AbortError") return;
  const message = error instanceof Error ? error.message : String(error);
  if (store.getState().ui.toasts.some(item => item.tone === "error" && item.message === message)) return;
  toast(message, "error");
}

function connectSocket() {
  socket?.disconnect();
  socket = createSocketClient({
    onStatus(transport) { store.dispatch({ type: "transport", transport }); },
    onSnapshot(envelope) {
      store.dispatch({ type: "snapshot", room: { ...envelope.room, seq: envelope.seq } });
      if (envelope.room?.metadata?.note) toast(envelope.room.metadata.note);
    },
    onRoomEvent(envelope) {
      store.dispatch({ type: "room-event", event: envelope.event });
      if (["presence.enter", "presence.leave"].includes(envelope.event?.type)) socket?.requestSnapshot();
    },
    onSessionReplaced(envelope) { store.dispatch({ type: "session-replaced", message: envelope.message }); },
    onErrorEnvelope(envelope) { toast(envelope.message || "The room rejected that message.", "error"); },
    onResult(envelope) {
      store.dispatch({ type: "result", ok: envelope.ok, message: envelope.message, payload: envelope.payload, events: envelope.events, command: envelope.command });
    },
  });
  socket.connect();
}

async function refreshBootstrapAndConnect() {
  const bootstrap = await api.getBootstrap();
  store.dispatch({ type: "bootstrap", user: bootstrap.user });
  if (store.getState().user?.initialStickerComplete) connectSocket();
}

async function syncLoggedInState(session) {
  store.dispatch({ type: "session", loggedIn: session.logged_in, csrfToken: session.csrf_token || "", user: session.user || null });
  if (!session.logged_in) return;
  await refreshBootstrapAndConnect();
}

async function loadApp() {
  const [session, stickers] = await Promise.all([api.getSession(), api.listStickers()]);
  store.dispatch({ type: "stickers", stickers });
  await syncLoggedInState(session);
}

async function sendCommand(rawCommand) {
  let command = String(rawCommand || "").trim();
  if (!command) return null;
  if (command.startsWith(".play ") && store.getState().activities.length && !/\s(?:replace|--replace)\s*$/i.test(command)) {
    const accepted = await dialogs.confirm("Replace the current activity?", "Starting another activity closes the one that is already open.", "Replace");
    if (!accepted) throw new DOMException("Activity replacement cancelled.", "AbortError");
    command = `${command} replace`;
  }
  if (!socket || !store.getState().transport.connected) throw new Error("Connect to the room before sending commands.");
  return socket.sendCommand(command);
}

async function bridgeActivity(activity, type, payload = {}) {
  const response = await api.bridgeActivity(activity, type, payload);
  const events = response.closed ? [{ type: "activity.closed", activity: response.closed, reason: response.reason || "cancelled" }] : [];
  store.dispatch({ type: "result", ok: true, message: "", payload: { activity: response.activity || null }, events });
  return response;
}

async function confirmSticker(sticker) {
  await api.confirmSticker(sticker);
  await refreshBootstrapAndConnect();
  toast("Sticker confirmed.", "success");
}

async function openCommands() {
  playTone("tap");
  settings.open = false;
  store.dispatch({ type: "command-palette", open: true });
  if (!store.getState().commandCatalog.length && store.getState().transport.connected) {
    try { await sendCommand(".help"); } catch (error) { showError(error); }
  }
}

function renderLook(state) {
  const description = describeSelection(state);
  const preview = state.selection.kind === "peep" && description.imageUrl
    ? `<img class="look-preview" src="${escapeHtml(description.imageUrl)}" alt="">` : "";
  const look = $("#look-bar");
  if (!updateMarkup(look, `${preview}<div class="look-copy">
    <strong class="look-name" title="${escapeHtml(description.title)}">${escapeHtml(description.title)}</strong>
    <button type="button" class="look-description" data-focus-key="description" title="${escapeHtml(description.description)}" aria-label="Read full description">${escapeHtml(description.description)}</button>
    </div>`)) return;
  look.querySelector("button").onclick = () => dialogs.description(description.title, description.description);
}

async function handleAction(action) {
  if (!action) return;
  playTone("tap");
  if (action.local) action = action.local;
  if (action.command) {
    try { await sendCommand(action.command); } catch (error) { showError(error); }
    return;
  }
  if (action.type === "open-view" || action.type === "core-toggle") {
    const view = action.view || action.id;
    store.dispatch({ type: store.getState().views.main === view ? "close-view" : "open-view", view });
    playTone("flip");
  } else if (["close-view", "close-details", "toggle-core"].includes(action.type)) {
    store.dispatch({ type: action.type });
  } else if (action.type === "open-details") {
    store.dispatch({ type: "open-details", stackId: action.stackId });
  } else if (action.type === "quantity") {
    const quantity = await dialogs.quantity(action.intent, action.max);
    if (quantity === null) return;
    try { await sendCommand(buildQuantityCommand(action.intent, action.stackId, quantity)); } catch (error) { showError(error); }
  }
}

function renderActions(state) {
  const actions = selectionActions(state);
  const bar = $("#actions-bar");
  const markup = actions.length ? actions.map((action, index) => {
    const tone = action.label === "Inspect" || action.label.startsWith("Open") ? "neutral" : action.label === "Close" ? "cancel" : action.tone || "neutral";
    return `<button type="button" class="${tone}" data-action-index="${index}" data-focus-key="${escapeHtml(action.command || action.label)}" ${action.disabled ? "disabled" : ""}>${escapeHtml(action.label)}</button>`;
  }).join("") : `<span class="actions-empty">${state.room ? "Select a card or peep to see its actions." : "Welcome to Tinyrooms."}</span>`;
  if (!updateMarkup(bar, markup)) return;
  bar.querySelectorAll("button").forEach(button => {
    button.onclick = () => { void handleAction(selectionActions(store.getState())[Number(button.dataset.actionIndex)]); };
  });
}

async function toggleLog() {
  try { await sendCommand(`.settings action-log ${store.getState().ui.actionLogVisible ? "off" : "on"}`); }
  catch (error) { showError(error); }
}

function renderActionLog(state) {
  root.classList.toggle("log-open", state.ui.actionLogVisible);
  const log = $("#action-log");
  const oldLines = log.querySelector(".log-lines");
  const atBottom = !oldLines || oldLines.scrollTop + oldLines.clientHeight >= oldLines.scrollHeight - 8;
  const oldTop = oldLines?.scrollTop || 0;
  if (!updateMarkup(log, `<header class="panel-header"><h2>Room activity</h2>
    <button type="button" class="icon-button" aria-label="Hide activity log">&times;</button></header>
    <div class="log-lines">${(state.room?.chatHistory || []).slice(-50).map(entry =>
      `<p class="log-line ${entry.kind === "chat" ? "chat" : "system"}">${escapeHtml(entry.kind === "chat" ? `${entry.speaker}: ${entry.text}` : entry.text)}</p>`
    ).join("") || `<p class="empty-state">No room events yet.</p>`}</div>`)) return;
  log.querySelector("button").onclick = toggleLog;
  const lines = log.querySelector(".log-lines");
  lines.scrollTop = atBottom ? lines.scrollHeight : oldTop;
}

function renderTopBar(state) {
  const connection = $("#connection-status");
  connection.textContent = state.transport.message || "";
  connection.dataset.status = state.transport.status || "idle";
  const top = $("#top-actions");
  if (!updateMarkup(top, `
    <button type="button" class="quiet" data-top-action="log" aria-pressed="${state.ui.actionLogVisible}">${state.ui.actionLogVisible ? "Hide Log" : "Show Log"}</button>
    <button type="button" class="quiet" data-top-action="sound" aria-pressed="${state.ui.soundEnabled}">${state.ui.soundEnabled ? "Sound On" : "Sound Off"}</button>
    <button type="button" class="quiet" data-top-action="commands">Commands</button>
    ${state.loggedIn ? `<button type="button" class="quiet" data-top-action="logout">Log out</button>` : ""}
    ${state.loggedIn && !state.transport.connected && state.user?.initialStickerComplete ? `<button type="button" class="quiet" data-top-action="reconnect">Reconnect</button>` : ""}`)) return;
  top.querySelectorAll("button").forEach(button => {
    button.onclick = async () => {
      const which = button.dataset.topAction;
      if (which === "log") await toggleLog();
      if (which === "sound") store.dispatch({ type: "toggle-sound" });
      if (which === "commands") await openCommands();
      if (which === "reconnect" && !refreshPromise) {
        refreshPromise = api.getSession().then(syncLoggedInState).catch(showError).finally(() => { refreshPromise = null; });
      }
      if (which === "logout") {
        try {
          await api.logout();
          socket?.disconnect();
          settings.open = false;
          store.dispatch({ type: "session", loggedIn: false, csrfToken: "", user: null });
        } catch (error) { showError(error); }
      }
    };
  });
}

function renderCommandPalette(state) {
  if (!state.views.commandPalette) {
    paletteClose?.();
    paletteClose = null;
    paletteShade = null;
    return;
  }
  if (!paletteShade) {
    paletteClose = dialogs.open(`<section class="global-dialog command-palette" role="dialog" aria-modal="true" aria-labelledby="commands-title">
      <h2 id="commands-title">Commands</h2>
      <input class="command-search" type="search" placeholder="Search commands" aria-label="Search commands">
      <div class="command-list"></div>
      <div class="dialog-actions"><button type="button" class="quiet close-palette">Close</button></div></section>`,
    (shade, close, cancel) => {
      paletteShade = shade;
      const input = shade.querySelector("input");
      input.value = commandSearch;
      input.oninput = () => { commandSearch = input.value; renderCommandPalette(store.getState()); };
      shade.querySelector(".close-palette").onclick = cancel;
      input.focus();
    }, () => store.dispatch({ type: "command-palette", open: false }));
  }
  const catalog = state.commandCatalog.length ? state.commandCatalog : COMMANDS;
  const filtered = catalog.filter(command => `${command.name} ${command.summary}`.toLowerCase().includes(commandSearch.toLowerCase()));
  const list = paletteShade.querySelector(".command-list");
  if (!updateMarkup(list, filtered.map(command => `<button type="button" class="command-row" data-command="${escapeHtml(command.name)}"><strong>${escapeHtml(command.name)}</strong><span>${escapeHtml(command.summary)}</span></button>`).join("") || `<p class="empty-state">No matching commands.</p>`)) return;
  list.querySelectorAll("button").forEach(button => {
    button.onclick = () => {
      chatInput.value = button.dataset.command;
      store.dispatch({ type: "command-palette", open: false });
      chatInput.focus();
    };
  });
}

function renderAuth(state) {
  const key = `${state.loggedIn}:${state.auth.mode}`;
  if (key === authKey) {
    const error = authLayer.querySelector(".auth-error");
    if (error) error.textContent = state.auth.error;
    const submit = authLayer.querySelector('button[type="submit"]');
    if (submit) {
      submit.disabled = state.auth.busy;
      submit.textContent = state.auth.busy ? "Working..." : state.auth.mode === "login" ? "Enter Tinyrooms" : "Create account";
    }
    return;
  }
  authKey = key;
  if (state.loggedIn) { authLayer.innerHTML = ""; return; }
  authLayer.innerHTML = `<section class="auth-card" role="dialog" aria-modal="true" aria-labelledby="auth-title">
    <header><h1 id="auth-title">Tinyrooms</h1><p>A little world. A place for you.</p></header>
    <div class="auth-tabs">
      <button type="button" class="${state.auth.mode === "login" ? "primary" : "quiet"}" data-auth-mode="login">Login</button>
      <button type="button" class="${state.auth.mode === "create" ? "primary" : "quiet"}" data-auth-mode="create">Create New Account</button>
    </div>
    <form class="auth-form">
      <label>Username<input name="username" autocomplete="username" minlength="3" maxlength="24" required></label>
      <label>Password<input name="password" type="password" autocomplete="${state.auth.mode === "login" ? "current-password" : "new-password"}" minlength="8" required></label>
      ${state.auth.mode === "create" ? `<label>Invitation passphrase<input name="passphrase" type="password" autocomplete="one-time-code" required></label>` : ""}
      <p class="auth-error" role="alert">${escapeHtml(state.auth.error)}</p>
      <button type="submit" class="primary">${state.auth.mode === "login" ? "Enter Tinyrooms" : "Create account"}</button>
    </form></section>`;
  authLayer.querySelectorAll("[data-auth-mode]").forEach(button => {
    button.onclick = () => store.dispatch({ type: "auth-mode", mode: button.dataset.authMode });
  });
  authLayer.querySelector("form").onsubmit = async event => {
    event.preventDefault();
    const payload = Object.fromEntries(new FormData(event.currentTarget).entries());
    store.dispatch({ type: "auth-busy", busy: true, error: "" });
    try {
      const response = state.auth.mode === "login" ? await api.login(payload) : await api.createAccount(payload);
      store.dispatch({ type: "session", loggedIn: true, csrfToken: response.csrf_token || api.getCsrfToken(), user: response.user });
      await refreshBootstrapAndConnect();
    } catch (error) {
      store.dispatch({ type: "auth-busy", busy: false, error: error instanceof Error ? error.message : String(error) });
    }
  };
  authLayer.querySelector('input[name="username"]').focus({ preventScroll: true });
}

function renderToasts(state) {
  updateMarkup($("#toast-stack"), state.ui.toasts.map(item =>
    `<article class="toast ${escapeHtml(item.tone)}">${escapeHtml(item.message)}</article>`).join(""));
  for (const item of state.ui.toasts) {
    if (timedToasts.has(item.id)) continue;
    timedToasts.add(item.id);
    playTone(item.tone === "error" ? "error" : item.tone === "success" ? "success" : "tap");
    setTimeout(() => {
      timedToasts.delete(item.id);
      store.dispatch({ type: "dismiss-toast", id: item.id });
    }, item.tone === "error" ? 7000 : 4200);
  }
}

const peeps = createPeepsView({
  panel: $("#peeps-panel"), bubbleLayer: $("#bubble-layer"),
  onSelect: selection => store.dispatch({ type: "select", selection }),
  onDismiss: id => store.dispatch({ type: "dismiss-bubble", id }),
  onSound: () => playTone("flip"),
});
const board = createBoard({
  canvas: $("#board-canvas"), overlay: $("#board-overlay"),
  onSelect(selection) {
    const state = store.getState();
    if (state.views.main || state.views.details || dialogs.active || !state.user?.initialStickerComplete) return;
    store.dispatch({ type: "select", selection });
    playTone("flip");
  },
});
const cards = createCardsView({
  handRoot: $("#card-hand"), panelRoot: panelLayer, detailRoot: detailLayer,
  onSelect(selection) { store.dispatch({ type: "select", selection }); playTone("flip"); },
  onAction: action => { void handleAction(action); },
});
const activities = createActivityManager({
  layer: activityLayer, getState: () => store.getState(),
  onActivityBridge: bridgeActivity, onCommand: sendCommand,
  onStickerConfirm: confirmSticker, onToast: toast,
});

async function render(state) {
  const revision = ++renderRevision;
  if (previousUser !== state.user?.id || previousRoom !== state.room?.id) {
    previousUser = state.user?.id;
    previousRoom = state.room?.id;
    dialogs.closeAll();
    if (revision !== renderRevision) return;
  }
  root.dataset.auth = state.loggedIn ? "in" : "out";
  root.classList.toggle("onboarding", Boolean(state.loggedIn && !state.user?.initialStickerComplete));
  root.classList.toggle("has-view", Boolean(state.views.main));
  root.classList.toggle("has-details", Boolean(state.views.details));
  $("#board-canvas").inert = !state.loggedIn || Boolean(state.views.main || state.views.details);
  panelLayer.inert = Boolean(state.views.details);
  activityLayer.inert = Boolean(state.views.main || state.views.details);
  $(".bottom-stack").inert = !state.loggedIn || !state.user?.initialStickerComplete;
  settings.inert = !state.loggedIn || !state.user?.initialStickerComplete;
  peeps.render(state);
  renderLook(state);
  renderActions(state);
  renderActionLog(state);
  renderTopBar(state);
  renderAuth(state);
  renderToasts(state);
  cards.render(state);
  if (!dialogs.active) {
    if (state.views.details && previousDetails !== state.views.details) {
      detailLayer.querySelector("[data-close-details]")?.focus({ preventScroll: true });
    } else if (!state.views.details && previousDetails && state.views.main) {
      panelLayer.querySelector(`[data-stack-id="${CSS.escape(previousDetails)}"]`)?.focus({ preventScroll: true });
    } else if (state.views.main && previousView !== state.views.main) {
      panelLayer.querySelector("[data-close-view]")?.focus({ preventScroll: true });
    } else if (!state.views.main && previousView) {
      $("#card-hand").querySelector(`[data-core-id="${CSS.escape(previousView)}"]`)?.focus({ preventScroll: true });
    }
  }
  previousView = state.views.main;
  previousDetails = state.views.details;
  renderCommandPalette(state);
  // Iframes must not wait for room textures/models to finish loading.
  await activities.sync(state.activities);
  if (revision !== renderRevision) return;
  await board.render(state);
}

$("#command-button").onclick = openCommands;
$("#chat-form").onsubmit = async event => {
  event.preventDefault();
  const text = chatInput.value;
  const command = chatToCommand(text);
  if (!command) return;
  try {
    const result = await sendCommand(command);
    if (result) {
      playTone("tap");
      if (chatInput.value === text) chatInput.value = "";
    }
  } catch (error) { showError(error); }
};

document.addEventListener("pointerdown", event => {
  if (settings.open && !settings.contains(event.target)) settings.open = false;
});
document.addEventListener("keydown", event => {
  if (event.key !== "Escape") return;
  if (dialogs.active) { event.preventDefault(); dialogs.cancel(); return; }
  if (settings.open) { settings.open = false; settings.querySelector("summary").focus(); return; }
  const state = store.getState();
  if (state.views.details) store.dispatch({ type: "close-details" });
  else if (state.views.main) store.dispatch({ type: "close-view" });
});
store.subscribe(state => { void render(state).catch(showError); });
void loadApp().catch(showError);
