import { createApiClient } from "./api.js";
import { createActivityManager } from "./activities.js";
import { playSound } from "./audio.js";
import { createBoard } from "./board.js";
import { createCardsView, describeSelection, dialogActions, selectionActions } from "./cards.js";
import { flyCoinReward } from "./coin-effects.js";
import {
  COMMANDS,
  buildEmoteCommand,
  buildFriendCommand,
  buildMergeCommand,
  buildQuantityCommand,
  buildSellCommand,
  buildSkillCommand,
  buildSplitCommand,
  buildSwapStickerCommand,
  buildUnskillCommand,
  chatToCommand,
} from "./commands.js";
import { createDialogs } from "./dialogs.js";
import { createCardMotion } from "./drag.js";
import { editorBoardProps, editablePropIds } from "./editing/edit-reducer.js";
import { createThumbnailManager } from "./editing/prop-thumbnails.js";
import { createPeepsView } from "./peeps.js";
import { escapeHtml, updateMarkup } from "./presentation.js";
import { createPropViewerManager } from "./prop-viewer.js";
import { createCardViewerManager } from "./card-viewer.js";
import { createSocketClient } from "./socket.js";
import { createStore } from "./state.js";

const store = createStore();
const api = createApiClient();
const $ = selector => document.querySelector(selector);
const root = $("#app");
const panelLayer = $("#panel-layer");
const detailLayer = $("#detail-layer");
const editorRoot = $("#editor-dock");
const shopRoot = $("#shop-dock");
const activityLayer = $("#activity-layer");
const authLayer = $("#auth-layer");
const chatInput = $("#chat-input");
const settings = $("#settings");
const dialogs = createDialogs($("#global-modal-layer"));
const timedToasts = new Set();
const consumedFeedback = new Set();
const feedbackLayer = document.createElement("div");
feedbackLayer.id = "feedback-layer";
feedbackLayer.setAttribute("aria-live", "polite");
root.append(feedbackLayer);
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

function playJournalOpen() {
  const book = panelLayer.querySelector(".journal-book");
  if (!book) return;
  book.classList.add("journal-opening");
  book.addEventListener("animationend", () => book.classList.remove("journal-opening"), { once: true });
}

function connectSocket() {
  socket?.disconnect();
  socket = createSocketClient({
    onStatus(transport) { store.dispatch({ type: "transport", transport }); },
    onSnapshot(envelope) {
      store.dispatch({ type: "snapshot", room: envelope.room });
      if (envelope.room?.metadata?.note) toast(envelope.room.metadata.note);
    },
    onRoomEvent(envelope) {
      if (envelope.event?.type === "shop.open") {
        void openShop();
        return;
      }
      store.dispatch({ type: "room-event", event: envelope.event });
      if (["presence.enter", "presence.leave"].includes(envelope.event?.type)) {
        peeps.noteMove(envelope.event);
        socket?.requestSnapshot();
      } else if (envelope.event?.type === "room.environment") {
        socket?.requestSnapshot();
      }
    },
    onSessionReplaced(envelope) { store.dispatch({ type: "session-replaced", message: envelope.message }); },
    onProfileResync() {
      api.getBootstrap()
        .then(bootstrap => {
          store.dispatch({ type: "bootstrap", user: bootstrap.user });
          toast("Profile data refreshed.");
        })
        .catch(() => {});
    },
    onErrorEnvelope(envelope) { toast(envelope.message || "The room rejected that message.", "error"); },
    onResult(envelope) {
      const events = Array.isArray(envelope.events) ? envelope.events : [];
      const shopOpen = events.some(event => event?.type === "shop.open");
      store.dispatch({
        type: "result",
        ok: envelope.ok,
        message: envelope.message,
        payload: envelope.payload,
        events: shopOpen ? events.filter(event => event?.type !== "shop.open") : events,
        toast: envelope.toast,
        log: envelope.log,
      });
      if (shopOpen) void openShop();
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

async function confirmSticker(selection) {
  await api.confirmSticker(selection);
  await refreshBootstrapAndConnect();
  toast("Sticker confirmed.", "success");
}

function closeEditor() {
  store.dispatch({ type: "editor-close" });
  store.dispatch({ type: "close-view" });
}

async function confirmCloseEditor() {
  const accepted = await dialogs.confirm(
    "Discard unsaved changes?",
    "Your room layout changes have not been saved.",
    "Discard",
  );
  if (accepted) closeEditor();
  return accepted;
}

async function openShop() {
  const state = store.getState();
  if (state.views.main === "edit-room" && state.editor?.dirty && !(await confirmCloseEditor())) return;
  store.dispatch({ type: "shop-open" });
}

async function openRoomEditor() {
  const roomId = store.getState().room?.id;
  if (!roomId) return;
  try {
    const layout = await api.getRoomLayout(roomId);
    if (layout) store.dispatch({ type: "editor-open", view: layout });
    else toast("The room layout could not be loaded.", "error");
  } catch (error) {
    showError(error);
  }
}

function editorPatch(editor) {
  return {
    props: editor.props.map(instance => ({
      id: instance.id,
      prop_id: instance.propId,
      position: instance.position,
      rotation: instance.rotation,
      scale: instance.scale,
    })),
    environment: editor.environment,
  };
}

async function saveRoomEditor() {
  const editor = store.getState().editor;
  if (!editor) return;
  store.dispatch({ type: "editor-status", message: "Saving…", error: "" });
  try {
    const result = await api.saveRoomLayout(editor.roomId, {
      base_revision: editor.baseRevision,
      patch: editorPatch(editor),
    });
    if (result.conflict) {
      store.dispatch({ type: "editor-conflict", layout: result.layout });
      toast(result.message, "error");
      return;
    }
    store.dispatch({ type: "editor-saved", view: result.layout });
    toast("Layout saved.", "success");
  } catch (error) {
    store.dispatch({ type: "editor-status", message: "", error: error instanceof Error ? error.message : String(error) });
    showError(error);
  }
}

function applyEditorPalette(index, value) {
  const state = store.getState();
  const editor = state.editor;
  if (!editor) return;
  const current = editor.environment.palette || state.room?.board?.palette || [];
  const colors = [...current];
  while (colors.length < 3) colors.push("#d4be94");
  if (String(colors[index] || "").toLowerCase() === String(value).toLowerCase()) return;
  colors[index] = value;
  store.dispatch({ type: "editor-env", key: "palette", value: colors });
}

async function applyEditorAction(action) {
  const state = store.getState();
  if (!state.editor) return;
  switch (action.action) {
    case "undo":
      store.dispatch({ type: "editor-undo" });
      break;
    case "redo":
      store.dispatch({ type: "editor-redo" });
      break;
    case "remove":
      if (state.editor.selectedId) store.dispatch({ type: "editor-remove", id: state.editor.selectedId });
      break;
    case "rotate":
      store.dispatch({ type: "editor-rotate", delta: action.delta || 15 });
      break;
    case "scale":
      store.dispatch({ type: "editor-scale", factor: action.factor || 1.15 });
      break;
    case "save":
      await saveRoomEditor();
      break;
    case "reload":
      if (state.editor.conflict) store.dispatch({ type: "editor-saved", view: state.editor.conflict });
      break;
    case "reapply":
      if (state.editor.conflict) {
        store.dispatch({ type: "editor-rebase", revision: state.editor.conflict.revision });
        await saveRoomEditor();
      }
      break;
  }
}

function handleEditorKey(event) {
  const state = store.getState();
  const editor = state.editor;
  if (!editor) return false;
  const step = editor.snapPosition ? 5 : 1;
  const moves = {
    ArrowLeft: [-step, 0],
    ArrowRight: [step, 0],
    ArrowUp: [0, -step],
    ArrowDown: [0, step],
  };
  if (moves[event.key]) {
    const [dx, dy] = moves[event.key];
    store.dispatch({ type: "editor-nudge", dx, dy });
    return true;
  }
  if (event.key === "[" || event.key === "]") {
    store.dispatch({ type: "editor-rotate", delta: event.key === "]" ? 15 : -15 });
    return true;
  }
  if (event.key === "+" || event.key === "=" || event.key === "-" || event.key === "_") {
    const factor = event.key === "-" || event.key === "_" ? 1 / 1.15 : 1.15;
    store.dispatch({ type: "editor-scale", factor });
    return true;
  }
  return false;
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
  const dialog = state.room?.dialog;
  const selectedPeep = dialog ? state.room?.npcs?.find(peep => peep.id === dialog.peepId) : null;
  const description = dialog
    ? { tag: "Conversation", title: dialog.peepLabel || selectedPeep?.label || "Conversation", description: dialog.text, imageUrl: selectedPeep?.stickerUrl || "" }
    : describeSelection(state);
  const peepPreview = (state.selection.kind === "peep" || dialog) && description.imageUrl
    ? `<img class="look-preview" src="${escapeHtml(description.imageUrl)}" alt="">` : "";
  const selectedProp = state.selection.kind === "prop"
    ? state.room?.props.find(prop => prop.id === state.selection.id)
    : null;
  const propPreview = selectedProp?.modelUrl
    ? `<canvas class="look-preview look-preview-3d" data-prop-model="${escapeHtml(selectedProp.modelUrl)}" data-prop-scale="${escapeHtml(selectedProp.scale)}" aria-hidden="true"></canvas>`
    : "";
  const look = $("#look-bar");
  if (updateMarkup(look, `${peepPreview}${propPreview}<div class="look-copy">
    <strong class="look-name" title="${escapeHtml(description.title)}">${escapeHtml(description.title)}</strong>
    <button type="button" class="look-description" data-focus-key="description" title="${escapeHtml(description.description)}" aria-label="Read full description">${escapeHtml(description.description)}</button>
    </div>`)) {
    look.querySelector("button").onclick = () => dialogs.description(description.title, description.description);
  }
}

async function handleAction(action) {
  if (!action) return;
  if (action.local) action = action.local;
  if (action.type !== "sell") playTone("tap");
  if (action.command) {
    try {
      cardMotion.animatePickupCommand(action.command);
      await sendCommand(action.command);
    } catch (error) { showError(error); }
    return;
  }
  if (action.type === "open-view" || action.type === "core-toggle") {
    const view = action.view || action.id;
    const closing = store.getState().views.main === view;
    store.dispatch({
      type: closing ? "close-view" : "open-view",
      view,
      propId: action.propId,
      stackId: action.stackId,
    });
    playTone("flip");
    if (!closing && view === "edit-room") await openRoomEditor();
    if (view === "journal") {
      await refreshTasks();
      if (store.getState().ui.journalTab === "Memories") await refreshJournalMonth();
    }
  } else if (["close-view", "close-details"].includes(action.type)) {
    const state = store.getState();
    if (action.type === "close-view" && state.views.main === "edit-room" && state.editor) {
      if (state.editor.dirty) { await confirmCloseEditor(); return; }
      closeEditor();
      return;
    }
    store.dispatch({ type: action.type });
  } else if (action.type === "open-shop") {
    await openShop();
  } else if (action.type === "shop-close") {
    store.dispatch({ type: "shop-close" });
  } else if (action.type === "buy-pack") {
    await buyPack(action.packId);
  } else if (action.type === "edit-add") {
    store.dispatch({ type: "editor-add", propId: action.propId });
  } else if (action.type === "edit-snap") {
    store.dispatch({ type: "editor-snap", which: action.which, value: action.value });
  } else if (action.type === "edit-palette") {
    applyEditorPalette(action.index, action.value);
  } else if (action.type === "edit-style") {
    store.dispatch({ type: "editor-env", key: "board_image_style", value: action.value });
  } else if (action.type === "edit-action") {
    await applyEditorAction(action);
  } else if (action.type === "open-details") {
    store.dispatch({ type: "open-details", stackId: action.stackId });
  } else if (action.type === "start-targeting") {
    store.dispatch({ type: "start-targeting", stackId: action.stackId, label: action.label });
    playTone("flip");
  } else if (action.type === "cancel-targeting") {
    store.dispatch({ type: "cancel-targeting" });
  } else if (action.type === "emote-category") {
    store.dispatch({ type: "emote-category", category: action.category });
  } else if (action.type === "play-emote") {
    store.dispatch({ type: "close-view" });
    try { await sendCommand(buildEmoteCommand(action.stackId)); } catch (error) { showError(error); }
  } else if (action.type === "journal-tab") {
    store.dispatch({ type: "journal-tab", tab: action.tab, tag: action.tag });
    await refreshTasks();
    if (action.tab === "Memories") await refreshJournalMonth();
  } else if (action.type === "journal-month") {
    store.dispatch({ type: "journal-month", delta: action.delta });
    await refreshJournalMonth();
  } else if (action.type === "journal-task-memories") {
    store.dispatch({ type: "journal-tab", tab: "Memories", tag: action.taskId });
    await refreshJournalMonth();
  } else if (action.type === "new-memory") {
    const text = chatInput.value.trim();
    if (!text) {
      toast("Type a memory in the chat bar first.", "info");
      return;
    }
    try {
      await sendCommand(`.memory_new ${text}`);
      if (chatInput.value.trim() === text) chatInput.value = "";
    } catch (error) { showError(error); }
  } else if (action.type === "memory-action") {
    await handleMemoryAction(action);
  } else if (action.type === "claim-bops") {
    try { await sendCommand(".claim_bops"); } catch (error) { showError(error); }
  } else if (action.type === "level-up") {
    try { await sendCommand(".level_up"); } catch (error) { showError(error); }
  } else if (action.type === "friend-action") {
    try { await sendCommand(buildFriendCommand(action.action, action.accountId)); } catch (error) { showError(error); }
  } else if (action.type === "skill-slot") {
    const state = store.getState();
    if (action.stackId) {
      try { await sendCommand(buildUnskillCommand(action.index)); } catch (error) { showError(error); }
    } else {
      const pending = state.views.skillStackId || (state.selection.kind === "inventory-card" ? state.selection.id : null);
      if (pending) {
        try { await sendCommand(buildSkillCommand(pending, action.index)); } catch (error) { showError(error); }
      } else {
        toast("Open a skill card in your Inventory and choose Slot… first.", "info");
      }
    }
  } else if (action.type === "merge") {
    await mergeStack(action.stackId);
  } else if (action.type === "sell") {
    let quantity = action.quantity || 1;
    if (action.max) {
      const chosen = await dialogs.quantity("sell", action.max, 1);
      if (chosen === null) return;
      quantity = chosen;
    }
    const total = (action.unit || 0) * quantity;
    const accepted = await dialogs.confirm(
      `Sell ${quantity}× ${action.label}?`,
      `You will receive ${total} Bops.`,
      "Sell",
    );
    if (!accepted) return;
    const sourceTile = document.querySelector(`#panel-layer [data-stack-id="${CSS.escape(action.stackId)}"]`);
    const from = sourceTile ? sourceTile.getBoundingClientRect() : null;
    try {
      const envelope = await sendCommand(buildSellCommand(action.stackId, quantity));
      const gained = Number(envelope?.payload?.sale?.bops_gained || 0);
      if (gained > 0) {
        const target = document.querySelector("#peeps-panel .peep-chip.self .peep-marker")
          || document.querySelector("#peeps-panel .peep-chip.self");
        playTone("coin");
        flyCoinReward({
          from: from || { x: window.innerWidth / 2, y: window.innerHeight / 2 },
          to: target,
          bops: gained,
          reducedMotion: store.getState().ui.reducedMotion,
        });
      }
    } catch (error) { showError(error); }
  } else if (action.type === "swap-sticker") {
    await openStickerSwap();
  } else if (action.type === "quantity") {
    const quantity = await dialogs.quantity(action.intent, action.max, action.minimum || 1);
    if (quantity === null) return;
    if (action.intent === "pickup") cardMotion.animatePickup(action.stackId);
    const command = action.intent === "split"
      ? buildSplitCommand(action.stackId, quantity)
      : buildQuantityCommand(action.intent, action.stackId, quantity);
    try { await sendCommand(command); } catch (error) { showError(error); }
  }
}

async function refreshTasks() {
  try {
    await sendCommand(".tasks");
  } catch (error) { showError(error); }
}

async function refreshJournalMonth() {
  const offset = Number(store.getState().ui.journalMonthOffset || 0);
  const now = new Date();
  const monthDate = new Date(now.getFullYear(), now.getMonth() + offset, 1);
  try {
    await sendCommand(`.memories ${monthDate.getFullYear()} ${monthDate.getMonth() + 1}`);
  } catch (error) { showError(error); }
}

async function handleMemoryAction(action) {
  const state = store.getState();
  const memory = (state.user?.journal?.memories || []).find(entry => entry.memoryId === action.memoryId);
  if (!memory) return;
  if (action.action === "delete") {
    const accepted = await dialogs.confirm("Delete this memory?", "This removes only your own manual memory.", "Delete");
    if (!accepted) return;
    try { await sendCommand(`.memory_delete @memory:${memory.memoryId}`); } catch (error) { showError(error); }
    return;
  }
  if (action.action === "edit") {
    const text = await dialogs.prompt("Edit memory", memory.text);
    if (text === null) return;
    const cleaned = String(text).trim();
    if (!cleaned || cleaned === memory.text) return;
    try { await sendCommand(`.memory_edit @memory:${memory.memoryId} ${cleaned}`); } catch (error) { showError(error); }
  }
}

async function mergeStack(stackId) {
  const state = store.getState();
  const stack = state.user?.inventory?.find(entry => entry.stackId === stackId);
  if (!stack) return;
  const candidates = (state.user?.inventory || []).filter(entry =>
    entry.stackId !== stackId
    && entry.definition?.id === stack.definition?.id
    && entry.quantity < (stack.definition?.stackLimit || 1)
  );
  if (!candidates.length) {
    toast("No other stack of that card has room to merge into.", "info");
    return;
  }
  let destination = candidates[0];
  if (candidates.length > 1) {
    const choice = await dialogs.choose("Merge into which stack?", candidates.map(entry => ({
      value: entry.stackId,
      label: `${entry.definition.label} ×${entry.quantity}`,
    })));
    if (!choice) return;
    destination = candidates.find(entry => entry.stackId === choice) || candidates[0];
  }
  try { await sendCommand(buildMergeCommand(stackId, destination.stackId)); } catch (error) { showError(error); }
}

async function openStickerSwap() {
  const state = store.getState();
  const stickers = state.stickers || [];
  const current = state.user?.sticker || "";
  const cost = state.user?.stickerSwapCost ?? 0;
  await dialogs.open(
    `<section class="global-dialog sticker-swap" role="dialog" aria-modal="true" aria-labelledby="sticker-swap-title">
      <h2 id="sticker-swap-title">Swap Sticker</h2>
      <p>Choose a new sticker. Confirming a different sticker costs ${cost} Bops; keeping the current one is free.</p>
      <div class="sticker-grid">${stickers.map(entry => {
        const name = String(entry?.name || "");
        const imageUrl = entry?.image_url || `/assets/stickers/${name}`;
        return `<button type="button" class="sticker-choice ${name === current ? "current" : ""}" data-sticker="${escapeHtml(name)}"><img src="${escapeHtml(imageUrl)}" alt=""></button>`;
      }).join("")}</div>
      <div class="dialog-actions">
        <button type="button" class="quiet design-custom-sticker">Design a Custom Sticker…</button>
        <button type="button" class="quiet cancel-swap">Cancel</button>
      </div>
    </section>`,
    (shade, close, cancel) => {
      shade.querySelector(".cancel-swap").onclick = cancel;
      shade.querySelector(".design-custom-sticker").onclick = async () => {
        close();
        try { await sendCommand(".play sticker-designer replace"); } catch (error) { showError(error); }
      };
      shade.querySelectorAll("[data-sticker]").forEach(button => {
        button.onclick = async () => {
          const chosen = button.dataset.sticker;
          close();
          try { await sendCommand(buildSwapStickerCommand(chosen)); } catch (error) { showError(error); }
        };
      });
    },
  );
}

function findPack(state, packId) {
  return (state.user?.packs || []).find(pack => pack.id === packId) || null;
}

function operationId() {
  return `pack-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;
}

async function buyPack(packId) {
  const state = store.getState();
  const pack = findPack(state, packId);
  if (!pack) return;
  const bops = Number(state.user?.bops ?? 0);
  if (bops < pack.price) {
    toast(`You need ${pack.price - bops} more Bops for that pack.`, "error");
    return;
  }
  const accepted = await dialogs.confirm(
    `Buy ${pack.label}?`,
    `Spend ${pack.price} Bops to open ${pack.size} cards?`,
    "Buy",
  );
  if (!accepted) return;
  try {
    const envelope = await sendCommand(`.buy_pack ${pack.id} ${operationId()}`);
    const purchase = envelope?.payload?.purchase;
    if (purchase) revealPack(purchase.cards || []);
  } catch (error) { showError(error); }
}

function revealPack(cards) {
  playTone("success");
  dialogs.open(
    `<section class="global-dialog pack-reveal" role="dialog" aria-modal="true" aria-labelledby="pack-reveal-title">
      <h2 id="pack-reveal-title">Your ${escapeHtml(cards.length)} cards</h2>
      <div class="pack-reveal-cards">${cards.map(card => `
        <figure class="pack-reveal-card"><img src="${escapeHtml(card.image_url)}" alt="${escapeHtml(card.label)}"><figcaption>${escapeHtml(card.label)}</figcaption></figure>
      `).join("")}</div>
      <div class="dialog-actions"><button type="button" class="primary pack-reveal-close">Continue</button></div>
    </section>`,
    (shade, close) => {
      const button = shade.querySelector(".pack-reveal-close");
      button.onclick = close;
      button.focus({ preventScroll: true });
    },
  );
}

function renderActions(state) {
  const bar = $("#actions-bar");
  if (state.ui.targeting) {
    const markup = `<span class="targeting-hint">Choose a target for ${escapeHtml(state.ui.targeting.label)}</span>
      <button type="button" class="cancel" data-action-index="-1">Cancel</button>`;
    if (!updateMarkup(bar, markup)) return;
    bar.querySelector("button").onclick = () => handleAction({ local: { type: "cancel-targeting" } });
    return;
  }
  const actions = state.room?.dialog ? dialogActions(state) : selectionActions(state);
  const markup = actions.length ? actions.map((action, index) => {
    const tone = action.label === "Inspect" || action.label.startsWith("Open") ? "neutral" : action.label === "Close" ? "cancel" : action.tone || "neutral";
    const label = escapeHtml(action.label);
    const className = action.icon ? `${tone} icon-action` : tone;
    const accessible = action.icon ? ` aria-label="${label}" title="${label}"` : "";
    const content = action.icon ? `<img src="${escapeHtml(action.icon)}" alt="">` : label;
    return `<button type="button" class="${className}" data-action-index="${index}" data-focus-key="${escapeHtml(action.command || action.label)}"${accessible} ${action.disabled ? "disabled" : ""}>${content}</button>`;
  }).join("") : `<span class="actions-empty">${state.room ? "Select a card or peep to see its actions." : "Welcome to Tinyrooms."}</span>`;
  if (!updateMarkup(bar, markup)) return;
  bar.querySelectorAll("button").forEach(button => {
    button.onclick = () => {
      const current = store.getState();
      const currentActions = current.room?.dialog ? dialogActions(current) : selectionActions(current);
      void handleAction(currentActions[Number(button.dataset.actionIndex)]);
    };
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
  const powers = new Set(state.user?.powers || []);
  const visible = catalog.filter(command => !command.power || powers.has(command.power));
  const filtered = visible.filter(command => `${command.name} ${command.summary} ${command.usage || ""} ${command.help || ""}`.toLowerCase().includes(commandSearch.toLowerCase()));
  const list = paletteShade.querySelector(".command-list");
  if (!updateMarkup(list, filtered.map(command => {
    const usage = command.usage && command.usage !== command.name ? `<code>${escapeHtml(command.usage)}</code>` : "";
    const power = command.power ? `<em class="command-power">${escapeHtml(command.power)}</em>` : "";
    return `<button type="button" class="command-row" data-command="${escapeHtml(command.name)}" data-focus-key="${escapeHtml(command.name)}"><strong>${escapeHtml(command.name)}${power}</strong><span>${escapeHtml(command.summary)}</span>${usage}</button>`;
  }).join("") || `<p class="empty-state">No matching commands.</p>`)) return;
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
    <div class="auth-tabs" role="group" aria-label="Choose login or account creation">
      <button type="button" class="auth-tab" aria-pressed="${state.auth.mode === "login"}" data-auth-mode="login">Login</button>
      <button type="button" class="auth-tab" aria-pressed="${state.auth.mode === "create"}" data-auth-mode="create">Create New Account</button>
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
    if (!item.silent) playTone(item.tone === "error" ? "error" : item.tone === "success" ? "success" : "tap");
    setTimeout(() => {
      timedToasts.delete(item.id);
      store.dispatch({ type: "dismiss-toast", id: item.id });
    }, item.tone === "error" ? 7000 : 4200);
  }
}

function renderFeedback(state) {
  const numbers = state.ui.floatingNumbers || [];
  const effects = state.ui.effects || [];
  const markup = [
    ...numbers.map(number => `<span class="floating-number ${number.amount >= 0 ? "gain" : "loss"}" data-float-id="${escapeHtml(number.id)}">${number.amount >= 0 ? "+" : ""}${Math.round(number.amount)} ${escapeHtml(number.kind)}</span>`),
    ...effects.map(effect => `<span class="room-effect" data-effect-id="${escapeHtml(effect.id)}"></span>`),
  ].join("");
  updateMarkup(feedbackLayer, markup);
  const bounds = $("#peeps-panel").getBoundingClientRect();
  for (const number of numbers) {
    const node = feedbackLayer.querySelector(`[data-float-id="${CSS.escape(number.id)}"]`);
    if (!node) continue;
    const marker = [...$("#peeps-panel").querySelectorAll("[data-peep-id]")].find(element => element.dataset.peepId === number.targetId);
    const rect = marker ? marker.getBoundingClientRect() : { top: bounds.top + 40, right: bounds.right };
    node.style.top = `${Math.max(8, rect.top)}px`;
    node.style.left = `${Math.min(window.innerWidth - 90, (rect.right || bounds.right) + 6)}px`;
  }
  for (const number of numbers) {
    if (consumedFeedback.has(`n:${number.id}`)) continue;
    consumedFeedback.add(`n:${number.id}`);
    setTimeout(() => {
      consumedFeedback.delete(`n:${number.id}`);
      store.dispatch({ type: "consume-floating", id: number.id });
    }, state.ui.reducedMotion ? 200 : 1500);
  }
  for (const effect of effects) {
    if (consumedFeedback.has(`e:${effect.id}`)) continue;
    consumedFeedback.add(`e:${effect.id}`);
    playTone("success");
    setTimeout(() => {
      consumedFeedback.delete(`e:${effect.id}`);
      store.dispatch({ type: "consume-effect", id: effect.id });
    }, state.ui.reducedMotion ? 200 : 1800);
  }
}

const peeps = createPeepsView({
  panel: $("#peeps-panel"), bubbleLayer: $("#bubble-layer"),
  onSelect: selection => {
    const state = store.getState();
    if (state.ui.targeting && selection.kind === "peep") {
      const stackId = state.ui.targeting.stackId;
      store.dispatch({ type: "cancel-targeting" });
      void sendCommand(`.use @card:${stackId} @peep:${selection.id}`).catch(showError);
      return;
    }
    store.dispatch({ type: "select", selection });
  },
  onDismiss: id => store.dispatch({ type: "dismiss-bubble", id }),
  onMove: command => { if (command) void sendCommand(command).catch(showError); },
  onSound: () => playTone("flip"),
});
const board = createBoard({
  canvas: $("#board-canvas"), overlay: $("#board-overlay"),
  onSelect(selection) {
    const state = store.getState();
    if (state.views.main || state.views.details || state.ui.targeting || dialogs.active || !state.user?.initialStickerComplete) return;
    store.dispatch({ type: "select", selection });
    playTone("flip");
  },
  onEditSelect(id) { store.dispatch({ type: "editor-select", id }); },
  onEditBegin() { store.dispatch({ type: "editor-begin" }); },
  onEditTransform({ id, position }) { store.dispatch({ type: "editor-transform", id, position }); },
  onEditRotate(delta) { store.dispatch({ type: "editor-rotate", delta }); },
  onEditScale(factor) { store.dispatch({ type: "editor-scale", factor }); },
});
const cards = createCardsView({
  handRoot: $("#card-hand"), panelRoot: panelLayer, detailRoot: detailLayer, editorRoot: $("#editor-dock"), shopRoot,
  onSelect(selection) {
    const detailsOpen = Boolean(store.getState().views.details);
    store.dispatch({ type: "select", selection });
    // While the card view is open, clicking another card retargets it instead of
    // leaving the old card on screen.
    if (detailsOpen && (selection.kind === "room-card" || selection.kind === "inventory-card")) {
      store.dispatch({ type: "open-details", stackId: selection.id });
    }
    playTone("flip");
  },
  onAction: action => { void handleAction(action); },
});
const propViewers = createPropViewerManager();
const cardViewers = createCardViewerManager();
const thumbnails = createThumbnailManager();
const cardMotion = createCardMotion({
  board,
  handRoot: $("#card-hand"),
  getState: () => store.getState(),
  sendCommand,
  onError: showError,
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
  root.classList.toggle("editing", Boolean(state.editor));
  root.classList.toggle("shopping", Boolean(state.shop));
  root.classList.toggle("targeting", Boolean(state.ui.targeting));
  $("#board-canvas").inert = !state.loggedIn || Boolean((state.views.main && state.views.main !== "edit-room") || state.views.details);
  panelLayer.inert = Boolean(state.views.details);
  activityLayer.inert = false;
  $(".bottom-stack").inert = !state.loggedIn || !state.user?.initialStickerComplete;
  settings.inert = !state.loggedIn || !state.user?.initialStickerComplete;
  peeps.render(state);
  renderLook(state);
  renderActions(state);
  renderActionLog(state);
  renderTopBar(state);
  renderAuth(state);
  renderToasts(state);
  renderFeedback(state);
  cards.render(state);
  if (state.views.main === "journal" && previousView !== "journal") playJournalOpen();
  propViewers.sync($("#look-bar"), state.ui.reducedMotion);
  propViewers.sync(panelLayer, state.ui.reducedMotion);
  propViewers.sync(detailLayer, state.ui.reducedMotion);
  cardViewers.sync(detailLayer, state.ui.reducedMotion);
  thumbnails.sync(editorRoot);
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
  let boardState = state;
  if (state.editor && state.views.main === "edit-room" && state.room) {
    const editableIds = editablePropIds(state.editor);
    boardState = {
      ...state,
      editing: true,
      editSelection: state.editor.selectedId,
      room: {
        ...state.room,
        props: [
          ...state.room.props.filter(prop => !editableIds.has(prop.propId)).map(prop => ({ ...prop, ghost: true })),
          ...editorBoardProps(state.editor),
        ],
        board: {
          ...state.room.board,
          palette: state.editor.environment.palette || state.room.board.palette,
          imageStyle: state.editor.environment.board_image_style || state.room.board.imageStyle,
        },
      },
    };
  }
  await board.render(boardState);
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
  const state = store.getState();
  const tag = event.target?.tagName;
  const typing = tag === "INPUT" || tag === "SELECT" || tag === "TEXTAREA";
  if (!typing && state.editor && state.views.main === "edit-room" && !dialogs.active) {
    if (event.key === "Escape") {
      event.preventDefault();
      if (board.cancelEditGesture()) { store.dispatch({ type: "editor-undo" }); return; }
      if (state.editor.dirty) { void confirmCloseEditor(); return; }
      closeEditor();
      return;
    }
    if (handleEditorKey(event)) { event.preventDefault(); return; }
  }
  if (event.key !== "Escape") return;
  if (state.ui.targeting) { event.preventDefault(); store.dispatch({ type: "cancel-targeting" }); return; }
  if (dialogs.active) { event.preventDefault(); dialogs.cancel(); return; }
  if (settings.open) { settings.open = false; settings.querySelector("summary").focus(); return; }
  if (state.shop) store.dispatch({ type: "shop-close" });
  else if (state.views.details) store.dispatch({ type: "close-details" });
  else if (state.views.main) store.dispatch({ type: "close-view" });
});
store.subscribe(state => { void render(state).catch(showError); });
void loadApp().catch(showError);
