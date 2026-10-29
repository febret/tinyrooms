import { createApiClient } from "./api.js";
import { withBase } from "./base-path.js";
import { createActivityManager } from "./activities.js";
import { activityResultPayload } from "./activity-result-payload.js";
import { createChatAutocomplete } from "./autocomplete.js";
import { createChatHistory } from "./chat-history.js";
import { playSound, preloadSounds } from "./audio.js";
import { actionSound, installButtonSoundHandler, playActionSound, playRoomSound, playSelectionSound, playToastSound } from "./ui-sounds.js";
import { createBoard } from "./board/board.js";
import { createPropActionButton } from "./props/prop-action-button.js";
import { syncEmoteChrome } from "./emote-chrome.js";
import { enterFullscreen, exitFullscreen, fullscreenSupported, isFullscreen, onFullscreenChange } from "./fullscreen.js";
import { syncPeepsChrome } from "./peeps/peeps-chrome.js";
import { createPhoneMusic } from "./phone-music.js";
import { handlePhoneMessagesAction, refreshPhoneMessages } from "./phone-actions.js";
import { createRoomPicker } from "./room-picker.js";
import { createContainerPanel } from "./container-panel.js";
import { createCardsView, defaultSelectionAction, describeSelection, dialogActions, selectionActions } from "./cards/cards.js";
import { lookPreview } from "./look-preview.js";
import { createCutsceneManager } from "./cutscenes/manager.js";
import {
  COMMANDS,
  buildEmoteCommand,
  buildFriendCommand,
  buildPhoneMessagesCommand,
  buildQuantityCommand,
  buildSkillCommand,
  buildSplitCommand,
  buildUnskillCommand,
  chatToCommand,
} from "./commands.js";
import { buildGotoCommand, phoneGotoTarget } from "./phone-goto.js";
import { createDialogs } from "./dialogs.js";
import { createCardMotion } from "./cards/card-motion.js";
import { createDropController } from "./drop-targeting.js";
import { editorBoardProps, editablePropIds } from "./editing/edit-reducer.js";
import { openTextPropDialog } from "./editing/text-prop-dialog.js";
import { openSignDialog } from "./sign-dialog.js";
import { createThumbnailManager } from "./editing/prop-thumbnails.js";
import { createEditorActions } from "./editor-actions.js";
import { createInertSweep, toggleClass } from "./inert.js";
import { createPeepsView } from "./peeps/peeps.js";
import { BUBBLE_TIMEOUT_CHOICES, saveFullscreenIntent, savedFullscreenIntent } from "./preferences.js";
import { escapeHtml, updateMarkup } from "./presentation.js";
import { createPropViewerManager } from "./props/prop-viewer.js";
import { createCardViewerManager } from "./cards/card-viewer.js";
import { createSocketClient, snapshotRefreshForEvent } from "./socket.js";
import { createStore } from "./state.js";
import { createStatusButton } from "./status-button.js";
import { topBarMarkup } from "./top-bar.js";
import { actionLogMarkup, actionsBarMarkup, syncPhoneFriendSelection as syncPhoneFriend } from "./ui-panels.js";
import { mergeStack as mergeStackAction, openPack as openPackAction, openStickerSwap as openStickerSwapAction, showPackReveal as showPackRevealView } from "./ui-inventory.js";
import { createTargetingController } from "./targeting.js";
import { createMultiverseView } from "./views/multiverse-view.js";
import { sellInventoryCard } from "./sell.js";
import { createVoiceChat } from "./voice.js";

const store = createStore();
const api = createApiClient();
const $ = selector => document.querySelector(selector);
const root = $("#app");
const panelLayer = $("#panel-layer");
const editorRoot = $("#editor-dock");
const activityLayer = $("#activity-layer");
const activityPills = $("#activity-pills");
const cutsceneLayer = $("#cutscene-layer");
const authLayer = $("#auth-layer");
const chatInput = $("#chat-input");
const emoteToggle = $("#emote-toggle");
const emoteToggleIcon = $("#emote-toggle-icon");
const emoteMenu = $("#emote-menu");
const settings = $("#settings");
const pushToTalk = $("#push-to-talk");
const talkRingProgress = $("#push-to-talk .talk-ring-progress");
const dialogs = createDialogs($("#global-modal-layer"));
const {
  saveAndCloseEditor,
  openRoomEditor,
  applyEditorPalette,
  applyEditorAction,
  handleEditorKey,
} = createEditorActions({ store, api, dialogs, toast, showError, sendCommand });
const timedToasts = new Set();
const leavingToasts = new Set();
let socket = null;
let paletteClose = null;
let paletteShade = null;
let commandSearch = "";
let authKey = "";
let previousUser = null;
let previousRoom = null;
let previousView = null;
let previousDialogKey = "";
let renderRevision = 0;
let refreshPromise = null;
let pendingGameStateRoom = "";
let targeting = null;
let dropTargeting = null;
let multiverseView = null;
let multiverseNavigating = false;
const canFullscreen = fullscreenSupported();
let fullscreenRestoreArmed = false;
let leavingPage = false;
store.dispatch({ type: "fullscreen-state", active: isFullscreen() });

const phoneKeyboardQuery = window.matchMedia("(any-pointer: coarse), (max-width: 780px), (max-height: 550px), (orientation: portrait)");
let pendingAppHeightFrame = 0;

function syncAppHeight() {
  const viewport = window.visualViewport;
  const scale = viewport?.scale || 1;
  const height = viewport && scale <= 1.01
    ? Math.min(window.innerHeight, Math.round(viewport.height))
    : window.innerHeight;
  document.documentElement.style.setProperty("--app-height", `${Math.max(240, Math.round(height))}px`);
  syncPhoneTyping();
}

function scheduleAppHeight() {
  if (pendingAppHeightFrame) return;
  pendingAppHeightFrame = window.requestAnimationFrame(() => {
    pendingAppHeightFrame = 0;
    syncAppHeight();
  });
}

function syncPhoneTyping(state = store.getState()) {
  const active = document.activeElement;
  const inPhone = Boolean(active?.closest?.(".phone-view"));
  const typingInput = Boolean(active?.matches?.("input, textarea")) && inPhone;
  const typingClose = Boolean(active?.matches?.(".phone-typing-close"));
  const typing = state.views.main === "phone"
    && (typingInput || typingClose)
    && phoneKeyboardQuery.matches;
  toggleClass(root, "phone-typing", Boolean(typing));
}

panelLayer.addEventListener("focusin", () => syncPhoneTyping());
panelLayer.addEventListener("focusout", () => window.setTimeout(() => syncPhoneTyping(), 0));
phoneKeyboardQuery.addEventListener?.("change", () => syncPhoneTyping());
window.addEventListener("resize", scheduleAppHeight);
window.visualViewport?.addEventListener("resize", scheduleAppHeight);
window.visualViewport?.addEventListener("scroll", scheduleAppHeight);
syncAppHeight();

function armFullscreenRestoreFallback() {
  if (fullscreenRestoreArmed) return;
  fullscreenRestoreArmed = true;
  const cleanup = () => {
    document.removeEventListener("pointerdown", retry, true);
    document.removeEventListener("keydown", retry, true);
  };
  const retry = event => {
    if (event?.target && settings?.contains(event.target)) return;
    cleanup();
    if (savedFullscreenIntent() && !isFullscreen() && canFullscreen) {
      enterFullscreen().catch(() => {});
    }
  };
  document.addEventListener("pointerdown", retry, true);
  document.addEventListener("keydown", retry, true);
}

function restoreFullscreenIntent() {
  if (!canFullscreen || !savedFullscreenIntent() || isFullscreen()) return;
  enterFullscreen().catch(armFullscreenRestoreFallback);
}

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

const TALK_RING_LENGTH = 100.53;

function renderTalkProgress({ talking: active, remainingMs, durationMs }) {
  const fraction = active && durationMs > 0 ? Math.max(0, Math.min(1, remainingMs / durationMs)) : 0;
  talkRingProgress.style.strokeDashoffset = String(TALK_RING_LENGTH * (1 - fraction));
  pushToTalk.setAttribute("aria-pressed", active ? "true" : "false");
}

const voice = createVoiceChat({
  sendSignal: (to, signal) => {
    try { socket?.sendRtcSignal(to, signal); } catch { /* the socket is closed */ }
  },
  sendPresence: enabled => {
    try { socket?.sendRtcPresence(enabled); } catch { /* the socket is closed */ }
  },
  onError: showError,
  onTalk: renderTalkProgress,
  onStateChange: ({ enabled, muted }) => {
    const ui = store.getState().ui;
    if (ui.audioEnabled === enabled && ui.audioMuted === muted) return;
    store.dispatch({ type: "audio-state", enabled, muted });
  },
});
function syncVoice(state) {
  if (!state.loggedIn || !state.room) {
    if (voice.isEnabled()) voice.reset();
    return;
  }
  voice.configure({ iceServers: state.rtc?.iceServers, selfId: state.user?.id });
  if (!voice.isEnabled()) return;
  voice.reconcile(state.room.occupants.filter(occupant => occupant.audioEnabled).map(occupant => occupant.id));
}

function playJournalOpen() {
  const book = panelLayer.querySelector(".journal-book");
  if (!book) return;
  book.classList.add("journal-opening");
  book.addEventListener("animationend", () => book.classList.remove("journal-opening"), { once: true });
}

function playPhoneOpen() {
  if (store.getState().ui.reducedMotion) return;
  const lid = panelLayer.querySelector(".phone-view .phone-lid");
  if (!lid) return;
  lid.classList.remove("phone-closing");
  lid.classList.add("phone-opening");
  lid.addEventListener("animationend", () => lid.classList.remove("phone-opening"), { once: true });
}

let phoneClosePromise = null;

function closePhoneAnimated() {
  if (phoneClosePromise) return phoneClosePromise;
  const lid = panelLayer.querySelector(".phone-view .phone-lid");
  if (!lid || store.getState().ui.reducedMotion) return Promise.resolve();
  phoneClosePromise = new Promise(resolve => {
    let finished = false;
    const finish = () => {
      if (finished) return;
      finished = true;
      resolve();
    };
    lid.classList.remove("phone-opening");
    lid.classList.add("phone-closing");
    lid.addEventListener("animationend", finish, { once: true });
    setTimeout(finish, 620);
  }).finally(() => { phoneClosePromise = null; });
  return phoneClosePromise;
}

const MULTIVERSE_SOUNDS = ["multiverseOpen", "multiverseClose", "multiverseHover", "multiverseSelect", "multiverseTravel"];

async function refreshMultiverse() {
  const state = store.getState();
  if (!state.room || !state.transport.connected) {
    store.dispatch({ type: "multiverse-error", message: "Connect to the room before reading the map." });
    return;
  }
  store.dispatch({ type: "multiverse-loading" });
  try {
    await sendCommand(".multiverse_worlds");
  } catch (error) {
    // Command failures also surface through the result toast pipeline.
    if (store.getState().views.main === "multiverse") {
      store.dispatch({ type: "multiverse-error", message: error instanceof Error ? error.message : String(error) });
    } else {
      showError(error);
    }
  }
}

async function closeMultiverseView({ sound = "" } = {}) {
  if (store.getState().views.main !== "multiverse") return;
  if (sound) playTone(sound);
  try {
    await multiverseView?.closeAnimated();
  } catch {
    // Closing must never trap the user in the vortex.
  }
  if (store.getState().views.main !== "multiverse") return;
  store.dispatch({ type: "close-view" });
}

async function travelMultiverse(worldId) {
  const id = String(worldId || "");
  if (!id) return;
  const state = store.getState();
  const world = state.multiverse.worlds.find(entry => entry.id === id);
  if (!world || world.current || state.multiverse.travelingId === id) return;
  store.dispatch({ type: "multiverse-traveling", id });
  try {
    await sendCommand(`.multiverse_travel ${id}`);
  } catch (error) {
    store.dispatch({ type: "multiverse-travel-failed", message: error instanceof Error ? error.message : String(error) });
    showError(error);
  }
}

function beginMultiverseNavigation(url) {
  const target = String(url || "");
  if (!target || multiverseNavigating) return;
  multiverseNavigating = true;
  if (store.getState().views.main !== "multiverse" || !multiverseView) {
    toast("Stepping through the portal...");
    window.location.assign(target);
    return;
  }
  playTone("multiverseTravel");
  const delay = multiverseView.depart();
  window.setTimeout(() => window.location.assign(target), delay);
}

function applyMultiverseInert(state) {
  const active = state.views.main === "multiverse";
  for (const selector of [".topbar", ".sidebar", ".board-frame", ".bottom-stack", ".bubble-layer", "#action-log"]) {
    const node = root.querySelector(selector);
    if (node) node.inert = active;
  }
  if (activityLayer) activityLayer.inert = active;
  if (active) {
    const picker = $("#room-picker");
    if (picker) picker.inert = true;
    const container = $("#container-panel");
    if (container) container.inert = true;
  }
}

function logCutscene(cutscene) {
  const title = String(cutscene?.title || "").trim();
  if (!title || cutscene?.hidden) return;
  const text = cutscene?.audience === "room"
    ? `${title} played for the room.`
    : `${title} played.`;
  store.dispatch({ type: "log-line", text });
}

function connectSocket() {
  socket?.disconnect();
  socket = createSocketClient({
    onStatus(transport) { store.dispatch({ type: "transport", transport }); },
    onSnapshot(envelope) {
      const room = envelope.room;
      store.dispatch({ type: "snapshot", room });
      if (room?.metadata?.note) toast(room.metadata.note);
      if (room?.board?.game && !room.board.state) {
        if (pendingGameStateRoom !== room.id) {
          pendingGameStateRoom = room.id;
          setTimeout(() => {
            if (pendingGameStateRoom === room.id) {
              const current = store.getState().room;
              socket?.requestSnapshot(current
                ? { layoutRevision: current.layoutRevision, environmentRevision: current.environmentRevision }
                : undefined);
            }
          }, 250);
        }
      } else if (pendingGameStateRoom === room?.id) {
        pendingGameStateRoom = "";
      }
    },
    onRoomEvent(envelope) {
      if (envelope.event?.type === "cutscene.play") {
        cutscenes.enqueue(envelope.event);
        logCutscene(envelope.event.cutscene);
        return;
      }
      store.dispatch({ type: "room-event", event: envelope.event });
      if (envelope.event?.type === "phone.message") {
        // A text arriving on the open thread is shown as read: tell the
        // server so the badge does not linger until the next refresh.
        const state = store.getState();
        const key = String(envelope.event.thread_key || "");
        if (key && state.views.main === "phone" && state.ui.phoneApp === "messages"
          && state.ui.phoneMessages?.threadKey === key) {
          void sendCommand(buildPhoneMessagesCommand("read", key)).catch(() => {});
        }
      }
      const room = store.getState().room;
      const revisions = room
        ? { layoutRevision: room.layoutRevision, environmentRevision: room.environmentRevision }
        : undefined;
      if (envelope.event?.type === "presence.enter" || envelope.event?.type === "peep.enter"
        || envelope.event?.type === "presence.leave" || envelope.event?.type === "peep.leave") {
        peeps.noteMove(envelope.event);
      }
      // A world reload rebuilds prop definitions without bumping the room
      // layout revision, so it needs the full snapshot; a revision-gated
      // request would omit the props whose scale just changed.
      const refresh = snapshotRefreshForEvent(envelope.event);
      if (refresh === "full") socket?.requestSnapshot();
      else if (refresh === "gated") socket?.requestSnapshot(revisions);
      if (envelope.event?.type === "room.reset") {
        const editor = store.getState().editor;
        if (editor && editor.roomId === envelope.event.room_id
            && Number(editor.baseRevision || 0) < Number(envelope.event.revision || 0)) {
          void openRoomEditor();
        }
      } else if (envelope.event?.type === "world.reloaded") {
        const editor = store.getState().editor;
        if (editor) {
          if (editor.dirty) {
            toast("The world reloaded; reopen the room editor to see updated prop scales.");
          } else {
            void openRoomEditor();
          }
        }
      }
    },
    onSessionReplaced(envelope) { store.dispatch({ type: "session-replaced", message: envelope.message }); },
    onRtcSignal(envelope) { void voice.handleSignal(envelope); },
    onProfileResync() {
      api.getBootstrap()
        .then(bootstrap => {
          store.dispatch({ type: "bootstrap", user: bootstrap.user, rtc: bootstrap.rtc });
          toast("Profile data refreshed.");
        })
        .catch(() => {});
    },
    onErrorEnvelope(envelope) { toast(envelope.message || "The room rejected that message.", "error"); },
    onResult(envelope) {
      const travelUrl = envelope.payload?.travel?.url;
      if (travelUrl) {
        beginMultiverseNavigation(String(travelUrl));
        return;
      }
      const signEditor = envelope.payload?.sign_editor;
      if (signEditor) {
        openSignDialog({ dialogs, store, api, payload: signEditor, toast, showError });
        return;
      }
      const events = Array.isArray(envelope.events) ? envelope.events : [];
      // `cutscene.play` is handled out of band, so it is filtered out before the
      // store sees it and never becomes view state.
      const handled = events.filter(event => {
        if (event?.type === "cutscene.play") {
          cutscenes.enqueue(event);
          logCutscene(event.cutscene);
          return false;
        }
        return true;
      });
      store.dispatch({
        type: "result",
        ok: envelope.ok,
        message: envelope.message,
        payload: envelope.payload,
        events: handled,
        toast: envelope.toast,
        log: envelope.log,
      });
      const opened = envelope.payload?.opened;
      // The pack cutscene is presentation-only. Reduced motion suppresses it, and
      // an idempotent replay has already played, so reveal inline in both cases no
      // matter whether the open came from the UI action or a raw command.
      if (opened && (opened.replayed || store.getState().ui.reducedMotion)) {
        showPackReveal(opened.cards || []);
      }
      const container = envelope.payload?.container;
      if (envelope.payload?.container_open && container) {
        store.dispatch({ type: "open-container", container });
      }
    },
  });
  socket.connect();
}

async function refreshBootstrapAndConnect() {
  const bootstrap = await api.getBootstrap();
  store.dispatch({ type: "bootstrap", user: bootstrap.user, rtc: bootstrap.rtc });
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
  store.dispatch({ type: "result", ok: true, message: "", payload: activityResultPayload(response), events });
  return response;
}

async function confirmSticker(selection) {
  await api.confirmSticker(selection);
  await refreshBootstrapAndConnect();
  toast("Sticker confirmed.", "success");
}

async function openShop(section = "cards") {
  try {
    await sendCommand(section === "props" ? ".shop props" : ".shop cards");
  } catch (error) {
    showError(error);
  }
}

async function openCommands() {
  settings.open = false;
  store.dispatch({ type: "command-palette", open: true });
  if (!store.getState().commandCatalog.length && store.getState().transport.connected) {
    try { await sendCommand(".help"); } catch (error) { showError(error); }
  }
}

function renderLook(state) {
  const description = describeSelection(state);
  const preview = lookPreview(state, description);
  const look = $("#look-bar");
  if (updateMarkup(look, `${preview.markup}<div class="look-copy">
    <strong class="look-name" title="${escapeHtml(description.title)}">${escapeHtml(description.title)}</strong>
    <button type="button" class="look-description" data-focus-key="description" title="${escapeHtml(description.description)}" aria-label="Read full description">${escapeHtml(description.description)}</button>
    </div>`)) {
    look.querySelector(".look-description").onclick = () => dialogs.description(description.title, description.description, description.imageUrl || "");
  }
  const inspect = look.querySelector("[data-look-inspect]");
  if (inspect) inspect.onclick = () => handleAction(preview.action, { silentSound: true });
}

async function handleAction(action, { silentSound = false } = {}) {
  if (!action) return;
  const customSound = action.sound;
  if (action.local) action = action.local;
  if (!silentSound) {
    playActionSound(store.getState(), customSound ? { ...action, sound: customSound } : action);
  }
  if (action.command) {
    try {
      cardMotion.animatePickupCommand(action.command);
      await sendCommand(action.command);
    } catch (error) { showError(error); }
    return;
  }
  if (action.type === "open-view" || action.type === "core-toggle") {
    const view = action.view || action.id;
    const state = store.getState();
    const resolved = view === "self" || view === "skills" ? "id" : view;
    const closing = state.views.main === resolved || state.views.main === view;
    // Leaving or closing the editor commits the layout first. The editor stays
    // open when the save conflicts or fails so changes are never dropped.
    if (state.editor && state.views.main === "edit-room") {
      if (!(await saveAndCloseEditor())) return;
      if (view === "edit-room") return;
    }
    if (closing && view === "phone") await closePhoneAnimated();
    if (closing && view === "multiverse") {
      await closeMultiverseView({ sound: "multiverseClose" });
      return;
    }
    store.dispatch({
      type: closing ? "close-view" : "open-view",
      view,
      propId: action.propId,
      stackId: action.stackId,
    });
    if (!closing && view === "multiverse") {
      preloadSounds(MULTIVERSE_SOUNDS);
      await refreshMultiverse();
    }
    if (!closing && view === "edit-room") await openRoomEditor();
    if (!closing && view === "journal") {
      const tab = store.getState().ui.journalTab;
      if (tab === "Tasks") await refreshTasks();
      if (tab === "Memories") await refreshJournalMonth();
    }
  } else if (action.type === "close-view") {
    const state = store.getState();
    if (action.type === "close-view" && state.views.main === "edit-room" && state.editor) {
      await saveAndCloseEditor();
      return;
    }
    if (state.views.main === "multiverse") {
      await closeMultiverseView({ sound: "multiverseClose" });
      return;
    }
    if (state.views.main === "phone") await closePhoneAnimated();
    if (store.getState().views.main !== state.views.main) return;
    store.dispatch({ type: action.type });
  } else if (action.type === "open-shop") {
    await openShop(action.section);
  } else if (action.type === "open-pack") {
    await openPack(action.stackId);
  } else if (action.type === "edit-add") {
    const library = store.getState().editor?.library || [];
    const entry = library.find(item => item.propId === action.propId);
    if (entry?.renderKind === "text" || action.propId === "builtin:text") {
      openTextPropDialog({ dialogs, store, propId: entry?.propId || "builtin:text" });
    } else store.dispatch({ type: "editor-add", propId: action.propId });
  } else if (action.type === "edit-snap") {
    store.dispatch({ type: "editor-snap", which: action.which, value: action.value });
  } else if (action.type === "edit-palette") {
    applyEditorPalette(action.index, action.value);
  } else if (action.type === "edit-style") {
    store.dispatch({ type: "editor-env", key: "board_image_style", value: action.value });
  } else if (action.type === "edit-sign-style") {
    const editor = store.getState().editor;
    if (editor?.selectedId) {
      store.dispatch({ type: "editor-sign-style", id: editor.selectedId, signStyle: action.signStyle });
    }
  } else if (action.type === "edit-exit-style") {
    const editor = store.getState().editor;
    if (editor?.selectedId) {
      store.dispatch({ type: "editor-exit-style", id: editor.selectedId, key: action.key, value: action.value });
    }
  } else if (action.type === "edit-action") {
    await applyEditorAction(action);
  } else if (action.type === "open-prop-editor") {
    if (action.propId) window.open(withBase(`/prop-editor/?prop=${encodeURIComponent(action.propId)}`), "_blank", "noopener");
  } else if (action.type === "open-cutscene-catalog") {
    window.open(withBase("/cutscene-catalog/"), "_blank", "noopener");
  } else if (action.type === "inspect-card") {
    store.dispatch({ type: "inspect-card", stackId: action.stackId });
  } else if (action.type === "start-targeting") {
    store.dispatch({ type: "start-targeting", stackId: action.stackId });
  } else if (action.type === "cancel-targeting") {
    store.dispatch({ type: "cancel-targeting" });
  } else if (action.type === "start-drop") {
    store.dispatch({ type: "start-drop", stackId: action.stackId, quantity: action.quantity });
  } else if (action.type === "cancel-drop") {
    store.dispatch({ type: "cancel-drop" });
  } else if (action.type === "play-emote") {
    store.dispatch({ type: "close-emote-menu" });
    try { await sendCommand(buildEmoteCommand(action.stackId)); } catch (error) { showError(error); }
  } else if (action.type === "id-flip") {
    store.dispatch({ type: "id-flip" });
  } else if (action.type === "journal-tab") {
    store.dispatch({ type: "journal-tab", tab: action.tab, tag: action.tag });
    if (action.tab === "Tasks") await refreshTasks();
    if (action.tab === "Memories") await refreshJournalMonth();
  } else if (action.type === "phone-app") {
    store.dispatch({ type: "phone-app", app: action.app });
    if (action.app === "friends") await refreshFriends();
    if (action.app === "messages") await refreshPhoneMessages({ store, sendCommand, showError });
    if (action.app === "chiptune") await phoneMusic.load(store.getState().ui.phoneMusic.mode || "suggestions", {
      path: store.getState().ui.phoneMusic.path,
      query: store.getState().ui.phoneMusic.query,
    });
  } else if (action.type === "phone-home") {
    store.dispatch({ type: "phone-home" });
  } else if (action.type === "phone-key") {
    if (action.key === "music-prev") phoneMusic.previous();
    else if (action.key === "music-toggle") phoneMusic.toggleOrPlay();
    else if (action.key === "music-next") phoneMusic.next();
    else if (action.key === "music-star") await phoneMusic.toggleStarCurrent();
    else if (action.key === "friend-prev") store.dispatch({ type: "phone-friend-step", delta: -1 });
    else if (action.key === "friend-next") store.dispatch({ type: "phone-friend-step", delta: 1 });
    else if (action.key === "messages") {
      store.dispatch({ type: "phone-app", app: "messages" });
      await refreshPhoneMessages({ store, sendCommand, showError });
    } else if (action.key === "close") {
      await handleAction({ type: "close-view" });
    } else if (action.key === "goto") {
      const target = phoneGotoTarget(store.getState());
      if (!target) {
        toast("Select a friend or peep first.", "info");
        return;
      }
      try { await sendCommand(buildGotoCommand(target)); } catch (error) { showError(error); }
    }
  } else if (action.type === "phone-music") {
    if (action.action === "play") phoneMusic.play({ song: action.song, label: action.label });
    else if (action.action === "stop") phoneMusic.stop();
    else if (action.action === "toggle") phoneMusic.toggle();
    else if (action.action === "star") await phoneMusic.toggleStar({ song: action.song, label: action.label });
    else if (action.action === "mode") {
      const mode = action.mode === "browse" ? "browse" : action.mode === "starred" ? "starred" : "suggestions";
      await phoneMusic.load(mode, { path: mode === "browse" ? "" : undefined });
    } else if (action.action === "browse") {
      await phoneMusic.load("browse", { path: action.path || "" });
    } else if (action.action === "search") {
      await phoneMusic.load("search", { query: action.query });
    }
  } else if (action.type === "inventory-tab") {
    store.dispatch({ type: "inventory-tab", tab: action.tab });
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
  } else if (action.type === "phone-messages" || action.type === "phone-messages-send") {
    await handlePhoneMessagesAction(action, { store, sendCommand, showError });
  } else if (action.type === "skill-slot") {
    const state = store.getState();
    if (action.stackId) {
      try { await sendCommand(buildUnskillCommand(action.index)); } catch (error) { showError(error); }
    } else {
      const pending = state.views.skillStackId || (state.selection.kind === "inventory-card" ? state.selection.id : null);
      if (pending) {
        try { await sendCommand(buildSkillCommand(pending, action.index)); } catch (error) { showError(error); }
      } else {
        store.dispatch({ type: "open-skill-picker", slot: action.index });
        queueMicrotask(() => {
          const picker = $("#room-picker");
          (picker.querySelector("[data-stack-id]") || picker.querySelector("[data-room-picker-close]") || picker)
            .focus({ preventScroll: true });
        });
      }
    }
  } else if (action.type === "merge") {
    await mergeStack(action.stackId);
  } else if (action.type === "toggle-sell-mode") {
    store.dispatch({ type: "toggle-sell-mode" });
  } else if (action.type === "toggle-titles") {
    store.dispatch({ type: "toggle-titles" });
  } else if (action.type === "toggle-inventory-compact") {
    store.dispatch({ type: "toggle-inventory-compact" });
  } else if (action.type === "sell-click") {
    await sellInventoryCard(action.stackId, { store, sendCommand, playCoin: () => playTone("coin"), onError: showError, onToast: toast });
  } else if (action.type === "swap-sticker") {
    await openStickerSwap();
  } else if (action.type === "quantity") {
    const quantity = await dialogs.quantity(action.intent, action.max, action.minimum || 1);
    if (quantity === null) return;
    if (action.intent === "drop") {
      store.dispatch({ type: "start-drop", stackId: action.stackId, quantity });
      return;
    }
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

async function refreshFriends() {
  try {
    await sendCommand(".friend list");
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

const inventoryDeps = () => ({ store, dialogs, sendCommand, toast, showError, playTone });
const mergeStack = stackId => mergeStackAction(inventoryDeps(), stackId);
const openStickerSwap = () => openStickerSwapAction(inventoryDeps());
const openPack = stackId => openPackAction(inventoryDeps(), stackId);
const showPackReveal = cards => showPackRevealView(inventoryDeps(), cards);

function renderActions(state) {
  const bar = $("#actions-bar");
  const markup = actionsBarMarkup(state, dialogActions, selectionActions, actionSound);
  if (state.ui.dropTargeting || state.ui.targeting) {
    if (!updateMarkup(bar, markup)) return;
    const cancelType = state.ui.dropTargeting ? "cancel-drop" : "cancel-targeting";
    bar.querySelector("button").onclick = () => handleAction({ local: { type: cancelType } }, { silentSound: true });
    return;
  }
  if (!updateMarkup(bar, markup)) return;
  bar.querySelectorAll("button").forEach(button => {
    button.onclick = () => {
      const current = store.getState();
      const currentActions = current.room?.dialog ? dialogActions(current) : selectionActions(current);
      void handleAction(currentActions[Number(button.dataset.actionIndex)], { silentSound: true });
    };
  });
}

async function toggleLog() {
  try { await sendCommand(`.settings action-log ${store.getState().ui.actionLogVisible ? "off" : "on"}`); }
  catch (error) { showError(error); }
}

function renderActionLog(state) {
  if (root.classList.contains("log-open") !== state.ui.actionLogVisible) {
    root.classList.toggle("log-open", state.ui.actionLogVisible);
  }
  const log = $("#action-log");
  const oldLines = log.querySelector(".log-lines");
  const atBottom = !oldLines || oldLines.scrollTop + oldLines.clientHeight >= oldLines.scrollHeight - 8;
  const oldTop = oldLines?.scrollTop || 0;
  if (!updateMarkup(log, actionLogMarkup(state))) return;
  log.querySelector("button").onclick = toggleLog;
  const lines = log.querySelector(".log-lines");
  lines.scrollTop = atBottom ? lines.scrollHeight : oldTop;
}

function renderTopBar(state) {
  const connection = $("#connection-status");
  connection.textContent = state.transport.message || "";
  connection.dataset.status = state.transport.status || "idle";
  const top = $("#top-actions");
  const markup = topBarMarkup(state, canFullscreen);
  if (!updateMarkup(top, markup)) return;
  top.querySelectorAll("[data-size-setting]").forEach(select => {
    select.onchange = () => {
      const kind = select.dataset.sizeSetting === "toolbar" ? "toolbar" : "sidebar";
      store.dispatch({ type: kind === "toolbar" ? "set-toolbar-size" : "set-sidebar-size", size: select.value });
    };
  });
  top.querySelectorAll("button").forEach(button => {
    button.onclick = async () => {
      const which = button.dataset.topAction;
      if (which === "peeps") store.dispatch({ type: "toggle-peeps" });
      if (which === "log") await toggleLog();
      if (which === "sound") store.dispatch({ type: "toggle-sound" });
      if (which === "fullscreen") {
        if (!canFullscreen) return;
        try {
          if (isFullscreen()) await exitFullscreen();
          else await enterFullscreen();
          settings.open = false;
        } catch (error) { showError(error); }
      }
      if (which === "outlines") store.dispatch({ type: "toggle-outline-active-props" });
      if (which === "bubble") {
        const current = store.getState().ui.bubbleTimeout;
        const index = BUBBLE_TIMEOUT_CHOICES.indexOf(current);
        store.dispatch({
          type: "set-bubble-timeout",
          timeout: BUBBLE_TIMEOUT_CHOICES[(index + 1) % BUBBLE_TIMEOUT_CHOICES.length],
        });
      }
      if (which === "audio") {
        if (store.getState().ui.audioEnabled) {
          voice.disable();
        } else {
          try {
            await voice.enable();
            toast("Audio chat is on.", "success");
          } catch (error) { showError(error); }
        }
      }
      if (which === "mute") {
        voice.toggleMute();
      }
      if (which === "commands") await openCommands();
      if (which === "reconnect" && !refreshPromise) {
        refreshPromise = api.getSession().then(syncLoggedInState).catch(showError).finally(() => { refreshPromise = null; });
      }
      if (which === "logout") {
        try {
          const result = await api.logout();
          socket?.disconnect();
          settings.open = false;
          if (result && typeof result.redirect_url === "string" && result.redirect_url) {
            window.location.assign(result.redirect_url);
            return;
          }
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
    `<article class="toast ${escapeHtml(item.tone)}${leavingToasts.has(item.id) ? " leaving" : ""}" data-toast-id="${escapeHtml(item.id)}">${escapeHtml(item.message)}</article>`).join(""));
  for (const item of state.ui.toasts) {
    if (timedToasts.has(item.id)) continue;
    timedToasts.add(item.id);
    playToastSound(state, item);
    const lifetime = item.tone === "error" ? 7000 : 4200;
    setTimeout(() => {
      leavingToasts.add(item.id);
      document.querySelector(`#toast-stack [data-toast-id="${CSS.escape(item.id)}"]`)?.classList.add("leaving");
    }, Math.max(0, lifetime - 340));
    setTimeout(() => {
      timedToasts.delete(item.id);
      leavingToasts.delete(item.id);
      store.dispatch({ type: "dismiss-toast", id: item.id });
    }, lifetime);
  }
}

/** Set a data attribute only when it actually changes. */
function toggleAttribute(node, name, value) {
  if (node.dataset[name] === value) return;
  node.dataset[name] = value;
}

const propActionButton = createPropActionButton({
  button: $("#prop-default-action"), getState: () => store.getState(), onAction: action => { void handleAction(action); },
});
// Clicking an already-selected entity fires its default quick action, if any.
function activateSelection(selection) {
  const state = store.getState();
  const same = selection.kind !== "none"
    && state.selection.kind === selection.kind
    && state.selection.id === selection.id;
  if (!same) return false;
  const action = defaultSelectionAction(state);
  if (!action) return false;
  void handleAction(action);
  return true;
}

const peeps = createPeepsView({
  panel: $("#peeps-panel"), bubbleLayer: $("#bubble-layer"),
  onSelect: selection => {
    if (dropTargeting?.handle(selection)) return;
    if (targeting?.handle(selection)) return;
    if (activateSelection(selection)) return;
    store.dispatch({ type: "select", selection });
  },
  onDismiss: id => store.dispatch({ type: "dismiss-bubble", id }),
  onMove: command => { if (command) void sendCommand(command).catch(showError); },
  onSound: () => {},
});
const statusButton = createStatusButton({
  root: $("#status-tools"),
  onAction: action => { void handleAction(action); },
});
const board = createBoard({
  canvas: $("#board-canvas"), overlay: $("#board-overlay"),
  needsPeepAnchors: () => peeps.hasBubbles(),
  onGameAction(action) {
    const state = store.getState();
    const controller = state.room?.board?.game?.controller;
    if (!controller || !action) return;
    void sendCommand(`.act ${action} @prop:${controller}`).catch(showError);
  },
  onSelect(selection, point) {
    const state = store.getState();
    if (state.views.main || dialogs.active || !state.user?.initialStickerComplete) return;
    if (dropTargeting?.handle(selection)) return;
    if (targeting?.handle(selection)) return;
    if (activateSelection(selection)) { propActionButton.clear(); return; }
    propActionButton.select(selection, point, state.room);
    store.dispatch({ type: "select", selection });
    playSelectionSound(state, selection);
  },
  onDropPoint(position, screen) {
    dropTargeting?.dropAt(position, screen);
  },
  onMoveSprite(position) {
    const state = store.getState();
    if (!state.room?.board?.spritesEnabled || state.views.main
      || dialogs.active || state.ui.targeting || state.ui.dropTargeting || !state.user?.initialStickerComplete) return;
    const self = state.room.occupants.find(occupant => occupant.id === state.user.id);
    if (!self?.spritePosition) return;
    const x = Number(position?.[0]);
    const y = Number(position?.[1]);
    if (!Number.isFinite(x) || !Number.isFinite(y)) return;
    const clamp = value => Math.min(94, Math.max(6, value));
    void sendCommand(`.sprite move ${clamp(x)} ${clamp(y)}`).catch(showError);
  },
  onPeepAnchors(anchors) { peeps.setSpriteAnchors(anchors); },
  onEditSelect(id) { store.dispatch({ type: "editor-select", id }); },
  onEditBegin() { store.dispatch({ type: "editor-begin" }); },
  onEditTransform({ id, position }) { store.dispatch({ type: "editor-transform", id, position }); },
  onEditRotate(delta, gesture) { store.dispatch({ type: "editor-rotate", delta, gesture: Boolean(gesture) }); },
  onEditScale(factor, gesture) { store.dispatch({ type: "editor-scale", factor, gesture: Boolean(gesture) }); },
  onEditElevate(delta, gesture) { store.dispatch({ type: "editor-elevate", delta, gesture: Boolean(gesture) }); },
  stackProps: true,
  dragHandles: true,
});
globalThis.__tinyroomsBoard = board;
targeting = createTargetingController({
  board, boardFrame: $(".board-frame"), getState: () => store.getState(), store, sendCommand,
  onToast: toast, onError: showError,
});
const cards = createCardsView({
  coreRoot: $("#core-tools"), handRoot: $("#card-hand"), menuRoot: emoteMenu, panelRoot: panelLayer, editorRoot: $("#editor-dock"),
  onSelect(selection) {
    if (dropTargeting?.handle(selection)) return;
    if (targeting?.handle(selection)) return;
    const sellState = store.getState();
    if (sellState.ui.sellMode && selection.kind === "inventory-card") {
      void sellInventoryCard(selection.id, { store, sendCommand, playCoin: () => playTone("coin"), onError: showError, onToast: toast });
      return;
    }
    if (activateSelection(selection)) return;
    store.dispatch({ type: "select", selection });
    playSelectionSound(store.getState(), selection);
  },
  onAction: action => { void handleAction(action, { silentSound: true }); },
});
const propViewers = createPropViewerManager();
const cardViewers = createCardViewerManager();
const thumbnails = createThumbnailManager();
const roomPicker = createRoomPicker({
  root: $("#room-picker"), store, thumbnails,
  onSelect(selection) {
    if (dropTargeting?.handle(selection) || targeting?.handle(selection) || activateSelection(selection)) return;
    store.dispatch({ type: "select", selection });
    playSelectionSound(store.getState(), selection);
  },
  onSkillPick({ stackId, slot }) {
    void sendCommand(buildSkillCommand(stackId, slot))
      .then(() => {
        store.dispatch({ type: "close-room-picker" });
        panelLayer.querySelector(`[data-skill-slot="${slot}"]`)?.focus({ preventScroll: true });
      })
      .catch(showError);
  },
});
const phoneMusic = createPhoneMusic({
  api,
  store,
  onToast: toast,
  onError: showError,
});
const containerPanel = createContainerPanel({
  root: $("#container-panel"), store, thumbnails,
  projectPosition: position => {
    const project = board.projectPositionToScreen;
    return typeof project === "function" ? project.call(board, position) : null;
  },
  onSelect(selection) {
    if (dropTargeting?.handle(selection)) return;
    if (targeting?.handle(selection)) return;
    if (activateSelection(selection)) return;
    store.dispatch({ type: "select", selection });
    playSelectionSound(store.getState(), selection);
  },
});
function syncPhoneFriendSelection(state) {
  syncPhoneFriend(state, panelLayer);
}
const cardMotion = createCardMotion({
  board,
  handRoot: $("#card-hand"),
  getState: () => store.getState(),
});
dropTargeting = createDropController({
  getState: () => store.getState(),
  store,
  sendCommand,
  onToast: toast,
  onError: showError,
  onDropFlight: (stackId, screen) => cardMotion.animateDrop(stackId, screen),
});
const activities = createActivityManager({
  layer: activityLayer, pillRoot: activityPills, getState: () => store.getState(),
  onActivityBridge: bridgeActivity, onCommand: sendCommand,
  onStickerConfirm: confirmSticker, onToast: toast,
});
multiverseView = createMultiverseView({
  layer: $("#multiverse-layer"),
  getState: () => store.getState(),
  onRefresh: () => { void refreshMultiverse(); },
  onSelect: id => store.dispatch({ type: "multiverse-select", id }),
  onTravel: id => { void travelMultiverse(id); },
  onClose: () => { void closeMultiverseView({ sound: "multiverseClose" }); },
  onSound: name => playTone(name),
});

const applyInert = createInertSweep({
  root, panelLayer, activityLayer, settings,
  bottomStack: $(".bottom-stack"),
});

const cutscenes = createCutsceneManager({
  layer: cutsceneLayer, getState: () => store.getState(),
  onToast: toast, onBlockingChange: () => applyInert(store.getState()),
  onSound: sound => playSound(sound, store.getState().ui.soundEnabled),
});

/** Assemble the board view state, merging the live editor draft when editing. */
function buildBoardState(state) {
  if (!state.editor || state.views.main !== "edit-room" || !state.room) return state;
  const editableIds = editablePropIds(state.editor);
  return {
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

function syncWorldStylesheet(state) {
  const href = state.loggedIn ? String(state.user?.worldCssUrl || "") : "";
  const worldId = state.loggedIn ? String(state.user?.worldId || "") : "";
  if (worldId) root.dataset.world = worldId;
  else delete root.dataset.world;
  let link = document.head.querySelector("link[data-world-stylesheet]");
  if (!href) {
    link?.remove();
    return;
  }
  if (!link) {
    link = document.createElement("link");
    link.rel = "stylesheet";
    link.dataset.worldStylesheet = "";
    document.head.append(link);
  }
  if (link.getAttribute("href") !== href) link.href = href;
}

async function render(state) {
  const revision = ++renderRevision;
  const roomChanged = Boolean(previousRoom && state.room?.id && previousRoom !== state.room.id);
  if (previousUser !== state.user?.id || previousRoom !== state.room?.id) {
    previousUser = state.user?.id;
    previousRoom = state.room?.id;
    previousDialogKey = "";
    dialogs.closeAll();
    if (revision !== renderRevision) return;
  }
  const dialog = state.room?.dialog;
  const dialogKey = dialog ? `${dialog.peepId}:${dialog.nodeId}:${dialog.revision}` : "";
  if (dialog?.sound && dialogKey && dialogKey !== previousDialogKey) {
    previousDialogKey = dialogKey;
    playSound(dialog.sound, state.ui.soundEnabled);
  } else if (!dialogKey) {
    previousDialogKey = "";
  }
  toggleAttribute(root, "auth", state.loggedIn ? "in" : "out");
  toggleAttribute(root, "sidebarSize", state.ui.sidebarSize || "normal");
  toggleAttribute(root, "toolbarSize", state.ui.toolbarSize || "normal");
  syncWorldStylesheet(state);
  toggleClass(root, "onboarding", Boolean(state.loggedIn && !state.user?.initialStickerComplete));
  toggleClass(root, "has-view", Boolean(state.views.main));
  toggleClass(root, "multiverse-open", state.views.main === "multiverse");
  toggleClass(root, "full-view", state.views.main === "inventory" || state.views.main === "journal" || state.views.main === "phone" || state.views.main === "id");
  toggleClass(root, "immersive-view", state.views.main === "journal" || state.views.main === "phone" || state.views.main === "id");
  toggleClass(root, "editing", Boolean(state.editor));
  toggleClass(root, "targeting", Boolean(state.ui.targeting));
  toggleClass(root, "drop-targeting", Boolean(state.ui.dropTargeting));
  toggleClass(root, "sell-mode", Boolean(state.ui.sellMode));
  const selfPeep = (state.room?.occupants || []).find(peep => peep.id === state.user?.id);
  toggleClass(root, "scared", Boolean(state.room) && (selfPeep?.statuses || state.user?.statuses || []).includes("scared"));
  toggleClass(root, "audio-mode", Boolean(state.ui.audioEnabled));
  const pushDisabled = !state.ui.audioEnabled || state.ui.audioMuted;
  if (pushToTalk.disabled !== pushDisabled) pushToTalk.disabled = pushDisabled;
  cutscenes.sync();
  applyInert(state);
  peeps.render(state);
  syncVoice(state);
  renderLook(state);
  renderActions(state);
  targeting?.sync(state);
  renderActionLog(state);
  renderTopBar(state);
  statusButton.render(state);
  propActionButton.sync(state);
  renderAuth(state);
  renderToasts(state);
  cards.render(state);
  syncPhoneFriendSelection(state);
  if (roomChanged) playRoomSound(state);
  syncEmoteChrome(state, emoteToggle, emoteToggleIcon, emoteMenu);
  syncPeepsChrome(state, root);
  roomPicker.sync(state);
  containerPanel.sync(state);
  phoneMusic.render(state);
  applyMultiverseInert(state);
  multiverseView?.sync(state);
  if (state.views.main === "journal" && previousView !== "journal") playJournalOpen();
  if (state.views.main === "phone" && previousView !== "phone") playPhoneOpen();
  propViewers.sync($("#look-bar"), state.ui.reducedMotion);
  propViewers.sync(panelLayer, state.ui.reducedMotion);
  cardViewers.sync(panelLayer, state.ui.reducedMotion);
  thumbnails.sync(editorRoot);
  if (!dialogs.active) {
    if (state.views.main && previousView !== state.views.main) {
      if (state.views.main !== "multiverse") {
        panelLayer.querySelector("[data-close-view]")?.focus({ preventScroll: true });
      }
    } else if (!state.views.main && previousView) {
      if (previousView === "multiverse") {
        $("#multiverse-toggle")?.focus({ preventScroll: true });
      } else {
        $("#core-tools").querySelector(`[data-core-id="${CSS.escape(previousView)}"]`)?.focus({ preventScroll: true });
      }
    }
  }
  previousView = state.views.main;
  syncPhoneTyping(state);
  renderCommandPalette(state);
  // Iframes must not wait for room textures/models to finish loading.
  await activities.sync(state.activities);
  if (revision !== renderRevision) return;
  await board.render(buildBoardState(state));
}

/** Prop transforms stream at pointer rate; only the board and tiny meta patches need updating. */
function isTransientEditorAction(action) {
  if (!action?.type) return false;
  if (action.type === "editor-transform") return true;
  return (action.type === "editor-rotate" || action.type === "editor-scale") && Boolean(action.gesture);
}

function renderEditorTransient(state) {
  // Shell is unchanged by an instance transform, so patch regions without rebuilding it.
  cards.renderEditor(state, { shell: false });
  if (state.views.main === "edit-room" && state.room) {
    void board.render(buildBoardState(state)).catch(showError);
  }
}

const chatHistory = createChatHistory();
const chatAutocomplete = createChatAutocomplete({ form: $("#chat-form"), input: chatInput, store, requestCatalog: () => sendCommand(".help"), history: chatHistory });
pushToTalk.onclick = () => { voice.toggleTalk(); };
emoteToggle.onclick = () => { store.dispatch({ type: "toggle-emote-menu" }); };
$("#chat-form").onsubmit = async event => {
  event.preventDefault();
  const text = chatInput.value;
  const command = chatToCommand(text);
  if (!command) return;
  chatHistory.record(text);
  try {
    const result = await sendCommand(command);
    if (result) {
      playTone("tap");
      if (chatInput.value === text) {
        chatInput.value = "";
        chatAutocomplete.close();
      }
    }
  } catch (error) { showError(error); }
};

document.addEventListener("pointerdown", event => {
  if (settings.open && !settings.contains(event.target)) settings.open = false;
  const state = store.getState();
  if (
    state.ui.emoteMenuOpen
    && !emoteMenu.contains(event.target)
    && !emoteToggle.contains(event.target)
  ) {
    store.dispatch({ type: "close-emote-menu" });
  }
  if (state.views.main === "phone" && !dialogs.active && !event.target?.closest?.(".phone-device, .phone-typing-close")) {
    void handleAction({ type: "close-view" });
  }
});
installButtonSoundHandler({ document, store });
document.addEventListener("keydown", event => {
  const state = store.getState();
  const tag = event.target?.tagName;
  const typing = tag === "INPUT" || tag === "SELECT" || tag === "TEXTAREA";
  if (!typing && state.editor && state.views.main === "edit-room" && !dialogs.active) {
    if (event.key === "Escape") {
      event.preventDefault();
      const cancelled = board.cancelEditGesture();
      if (cancelled) {
        if (cancelled.undo) store.dispatch({ type: "editor-undo" });
        return;
      }
      void saveAndCloseEditor();
      return;
    }
    if (handleEditorKey(event)) { event.preventDefault(); return; }
  }
  if (event.key !== "Escape") return;
  if (state.ui.dropTargeting) { event.preventDefault(); store.dispatch({ type: "cancel-drop" }); return; }
  if (state.ui.targeting) { event.preventDefault(); store.dispatch({ type: "cancel-targeting" }); return; }
  if (dialogs.active) { event.preventDefault(); dialogs.cancel(); return; }
  if (roomPicker.handleEscape(event)) return;
  if (containerPanel.handleEscape(event)) return;
  if (settings.open) { settings.open = false; settings.querySelector("summary").focus(); return; }
  if (state.ui.emoteMenuOpen) {
    event.preventDefault();
    store.dispatch({ type: "close-emote-menu" });
    emoteToggle.focus();
    return;
  }
  if (state.views.main) void handleAction({ type: "close-view" });
});
onFullscreenChange(() => {
  const active = isFullscreen();
  store.dispatch({ type: "fullscreen-state", active });
  // A reload can drop element fullscreen before unload; keep the last intent.
  if (!leavingPage) saveFullscreenIntent(active);
});
const markLeavingPage = () => {
  leavingPage = true;
  if (isFullscreen()) saveFullscreenIntent(true);
};
window.addEventListener("beforeunload", markLeavingPage);
window.addEventListener("pagehide", markLeavingPage);
window.addEventListener("pageshow", () => { leavingPage = false; });
store.subscribe((state, action) => {
  if (isTransientEditorAction(action)) { renderEditorTransient(state); return; }
  void render(state).catch(showError);
});
restoreFullscreenIntent();
void loadApp().catch(showError);
