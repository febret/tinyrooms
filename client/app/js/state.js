import { editorReducer } from "./editing/edit-reducer.js";
import { annotateRoom } from "./eligibility.js";
import { dismissInvalidSelection, inspectCardState, inventoryTabState, openInventoryState } from "./inventory-state.js";
import { withBase } from "./base-path.js";
import {
  assetOrEmpty,
  clone,
  mergeLayoutProps,
  normalizeActivity,
  normalizeCardDefinition,
  normalizeChatEntry,
  normalizeCounters,
  normalizeDialog,
  normalizeGameState,
  normalizeInventoryStack,
  normalizeJournal,
  normalizeNpc,
  normalizeOccupant,
  normalizePack,
  normalizeRoom,
  normalizeRoomCard,
  normalizeSurface,
  normalizeTasks,
  normalizeUser,
} from "./normalize.js";
import {
  saveBubbleTimeout,
  savedBubbleTimeout,
  savedInventoryCompact,
  saveInventoryCompact,
  savedOutlineActiveProps,
  saveOutlineActiveProps,
  savedPhoneMusicEnabled,
  savedPhoneTrack,
  savedSidebarSize,
  savedToolbarSize,
  saveSidebarSize,
  saveToolbarSize,
} from "./preferences.js";

const REDUCED_MOTION = typeof window !== "undefined" && typeof window.matchMedia === "function"
  ? window.matchMedia("(prefers-reduced-motion: reduce)").matches
  : false;
const BUBBLE_LIMIT = 120;

function toastRecord(message, tone = "info", silent = false, sound = "") {
  return {
    id: crypto.randomUUID(),
    message: String(message || ""),
    tone,
    silent: Boolean(silent),
    sound: String(sound || ""),
  };
}

function applyBubble(peeps, key, label, text, style, imageUrl = "") {
  const url = withBase(String(imageUrl || ""));
  const wanted = String(label || "").toLowerCase();
  let next = peeps;
  for (let index = 0; index < peeps.length; index += 1) {
    const peep = peeps[index];
    if (peep.id !== key && peep.username.toLowerCase() !== wanted) continue;
    const updated = bubbleFor(peep, text, style, url);
    if (updated === null) continue;
    // Copy on first write so a no-op update leaves the caller's array intact.
    // The board and the peep panel both diff against this reference.
    if (next === peeps) next = peeps.slice();
    next[index] = updated;
  }
  return next;
}

/** Return the peep with its bubble replaced, or null when nothing would change. */
function bubbleFor(peep, text, style, url) {
  if (url) {
    const current = peep.bubble;
    if (
      current
      && !peep.bubbleDismissed
      && current.text === String(text || "")
      && current.style === style
      && current.imageUrl === url
    ) {
      return null;
    }
    return {
      ...peep,
      bubble: { text: String(text || ""), style, imageUrl: url },
      bubbleDismissed: false,
    };
  }
  const combined = peep.bubble && !peep.bubbleDismissed && !peep.bubble.imageUrl
    ? `${peep.bubble.text}\n${text}`
    : text;
  const trimmed = combined.length > BUBBLE_LIMIT ? combined.slice(combined.length - BUBBLE_LIMIT) : combined;
  const current = peep.bubble;
  if (!peep.bubbleDismissed && current && current.text === trimmed && current.style === style && !current.imageUrl) {
    return null;
  }
  return {
    ...peep,
    bubble: { text: trimmed, style },
    bubbleDismissed: false,
  };
}

function asSystemHistory(text) {
  return { id: crypto.randomUUID(), kind: "system", speaker: "", speakerId: "", style: "normal", text };
}

function updatePeepCounters(peeps, targetId, event) {
  return peeps.map(peep => {
    if (peep.id !== targetId) return peep;
    const counters = {
      ...(peep.counters || {}),
      health: Number(event.health ?? peep.counters?.health ?? 0),
      energy: Number(event.energy ?? peep.counters?.energy ?? 0),
      cleanliness: Number(event.cleanliness ?? peep.counters?.cleanliness ?? 0),
      maxHealth: Number(event.max_health ?? peep.counters?.maxHealth ?? 0),
      maxEnergy: Number(event.max_energy ?? peep.counters?.maxEnergy ?? 0),
      maxCleanliness: Number(event.max_cleanliness ?? peep.counters?.maxCleanliness ?? 0),
      statuses: Array.isArray(event.statuses) ? [...event.statuses] : (peep.counters?.statuses || []),
      decals: Array.isArray(event.decals) ? event.decals.map(entry => ({ ...entry })) : (peep.counters?.decals || []),
    };
    return {
      ...peep,
      counters,
      statuses: Array.isArray(event.statuses) ? [...event.statuses] : peep.statuses,
      decals: Array.isArray(event.decals) ? event.decals.map(entry => ({ ...entry })) : peep.decals,
    };
  });
}

function applyDialogPayload(state, rawDialog) {
  const dialog = normalizeDialog(rawDialog);
  const room = state.room ? { ...state.room, dialog } : state.room;
  const next = { ...state, room };
  if (!dialog || !state.room) return next;
  const present = [...state.room.occupants, ...state.room.npcs].some(peep => peep.id === dialog.peepId);
  return present ? { ...next, selection: { kind: "peep", id: dialog.peepId } } : next;
}

function applyServerEvent(state, event) {
  if (!event || !state.room) return state;
  if (event.room_id && event.room_id !== state.room.id) return state;
  if (event.type === "counter.updated") {
    const targetId = String(event.target_id || "");
    return {
      ...state,
      room: {
        ...state.room,
        occupants: updatePeepCounters(state.room.occupants, targetId, event),
        npcs: updatePeepCounters(state.room.npcs, targetId, event),
      },
    };
  }
  if (event.type === "peep.sprite") {
    const targetId = String(event.peep_id || event.account_id || "");
    const position = Array.isArray(event.position) ? event.position.map(Number) : null;
    if (!targetId || !position) return state;
    const update = peep => peep.id === targetId ? { ...peep, spritePosition: position } : peep;
    return {
      ...state,
      room: {
        ...state.room,
        occupants: state.room.occupants.map(update),
        npcs: state.room.npcs.map(update),
      },
    };
  }
  if (event.type === "emote.bubble") {
    const bubble = event.bubble || {};
    const sourceId = String(event.source_id || "");
    const text = String(bubble.text || "");
    const updatedOccupants = applyBubble(state.room.occupants, sourceId, event.source, text, String(bubble.kind || "expression"), String(bubble.image_url || ""));
    const updatedNpcs = applyBubble(state.room.npcs, sourceId, event.source, text, String(bubble.kind || "expression"), String(bubble.image_url || ""));
    // User emotes are already logged via their command result; NPC speech and
    // emote labels have no such line, so add a label-derived log entry for them.
    const isUser = state.room.occupants.some(occupant => occupant.id === sourceId);
    const chatHistory = !isUser && text
      ? [...state.room.chatHistory, normalizeChatEntry({ speaker_id: sourceId, speaker: event.source, text, style: String(bubble.kind || "expression") })].slice(-50)
      : state.room.chatHistory;
    return {
      ...state,
      room: { ...state.room, occupants: updatedOccupants, npcs: updatedNpcs, chatHistory },
    };
  }
  if (event.type === "toast") {
    return {
      ...state,
      ui: {
        ...state.ui,
        toasts: [
          ...state.ui.toasts.slice(-2),
          toastRecord(event.text, event.tone || "info", event.silent, event.sound),
        ],
      },
    };
  }
  if (event.type === "action.log") {
    return state;
  }
  if (event.type === "chat.message") {
    const speaker = String(event.speaker_label || event.speaker || "");
    const updatedOccupants = applyBubble(state.room.occupants, String(event.speaker_id || ""), speaker, String(event.text || ""), String(event.style || "normal"));
    const updatedNpcs = applyBubble(state.room.npcs, String(event.speaker_id || ""), speaker, String(event.text || ""), String(event.style || "normal"));
    return {
      ...state,
      room: {
        ...state.room,
        occupants: updatedOccupants,
        npcs: updatedNpcs,
        chatHistory: [...state.room.chatHistory, normalizeChatEntry(event)].slice(-50),
      },
    };
  }
  if (event.type === "presence.enter") {
    const accountId = String(event.account_id || "");
    let occupants = state.room.occupants;
    if (accountId && !occupants.some(occupant => occupant.id === accountId)) {
      // Prefer the server's occupant payload; fall back to a minimal entry
      // built from the event so the list stays correct even when the payload
      // is absent (e.g. older behavior-generated events).
      const incoming = event.occupant && typeof event.occupant === "object"
        ? normalizeOccupant({ ...event.occupant, id: event.occupant.id || accountId })
        : normalizeOccupant({
          id: accountId,
          username: String(event.username || ""),
          label: String(event.label || event.username || "Peep"),
        });
      occupants = [...occupants, incoming];
    }
    return {
      ...state,
      room: {
        ...state.room,
        occupants,
        chatHistory: [...state.room.chatHistory, asSystemHistory(`${event.label || event.username} entered.`)].slice(-50),
      },
    };
  }
  if (event.type === "presence.leave") {
    const accountId = String(event.account_id || "");
    return {
      ...state,
      room: {
        ...state.room,
        occupants: accountId
          ? state.room.occupants.filter(occupant => occupant.id !== accountId)
          : state.room.occupants,
        chatHistory: [...state.room.chatHistory, asSystemHistory(`${event.label || event.username} left.`)].slice(-50),
      },
    };
  }
  if (event.type === "peep.enter") {
    const peepId = String(event.peep_id || "");
    let npcs = state.room.npcs;
    if (peepId && !npcs.some(npc => npc.id === peepId)) {
      const incoming = event.npc && typeof event.npc === "object"
        ? normalizeNpc({ ...event.npc, id: event.npc.id || peepId })
        : normalizeNpc({ id: peepId, label: String(event.label || peepId) });
      npcs = [...npcs, incoming];
    }
    return { ...state, room: { ...state.room, npcs } };
  }
  if (event.type === "peep.leave") {
    const peepId = String(event.peep_id || "");
    return {
      ...state,
      room: { ...state.room, npcs: peepId ? state.room.npcs.filter(npc => npc.id !== peepId) : state.room.npcs },
    };
  }
  if (event.type === "presence.title") {
    const targetId = String(event.account_id || "");
    const label = String(event.label || event.username || "");
    if (!targetId || !label) return state;
    return {
      ...state,
      room: {
        ...state.room,
        occupants: state.room.occupants.map(occupant => (
          occupant.id === targetId ? { ...occupant, label } : occupant
        )),
      },
    };
  }
  if (event.type === "presence.audio") {
    const targetId = String(event.account_id || "");
    return {
      ...state,
      room: {
        ...state.room,
        occupants: state.room.occupants.map(occupant => (
          occupant.id === targetId ? { ...occupant, audioEnabled: Boolean(event.enabled) } : occupant
        )),
      },
    };
  }
  if (event.type === "room.environment") {
    const revision = Number(event.revision || 0);
    if (revision <= Number(state.room.environmentRevision || 0)) return state;
    const environment = event.environment && typeof event.environment === "object" ? { ...event.environment } : {};
    return {
      ...state,
      room: {
        ...state.room,
        environment,
        environmentRevision: revision,
      },
    };
  }
  if (event.type === "room.layout.updated") {
    const revision = Number(event.revision || 0);
    if (revision <= Number(state.room.layoutRevision || 0)) return state;
    const environment = event.environment && typeof event.environment === "object" ? event.environment : {};
    return {
      ...state,
      room: {
        ...state.room,
        layoutRevision: revision,
        props: Array.isArray(event.props) ? mergeLayoutProps(state.room.props, event.props) : state.room.props,
        board: {
          ...state.room.board,
          palette: Array.isArray(environment.palette) ? [...environment.palette] : state.room.board.palette,
          imageStyle: environment.board_image_style ? String(environment.board_image_style) : state.room.board.imageStyle,
          imageUrl: typeof environment.board_image === "string" && environment.board_image && state.user?.worldId
            ? assetOrEmpty(`/assets/world/${state.user.worldId}/rooms/${environment.board_image}`)
            : state.room.board.imageUrl,
        },
      },
    };
  }
  if (event.type === "room.board.state" && state.room) {
    const nextState = normalizeGameState(event.state);
    const dynamicDescription = nextState?.room_description;
    return {
      ...state,
      room: {
        ...state.room,
        description: typeof dynamicDescription === "string" && dynamicDescription.trim()
          ? dynamicDescription
          : state.room.baseDescription,
        board: { ...state.room.board, state: nextState },
      },
    };
  }
  if (event.type === "room.prop.updated" && event.prop && state.room) {
    const targetId = String(event.prop.id || "");
    return {
      ...state,
      room: {
        ...state.room,
        props: state.room.props.map(prop => {
          if (prop.id !== targetId) return prop;
          if (event.prop.light && typeof event.prop.light === "object") {
            return {
              ...prop,
              light: {
                kind: String(event.prop.light.kind || prop.light?.kind || ""),
                on: event.prop.light.on !== false,
                color: typeof event.prop.light.color === "string"
                  ? event.prop.light.color
                  : (prop.light?.color || ""),
              },
            };
          }
          const nextState = typeof event.prop.active_state === "string"
            ? event.prop.active_state
            : event.prop.state;
          if (typeof nextState === "string") {
            return {
              ...prop,
              state: nextState,
              modelUrl: assetOrEmpty(event.prop.model_url || (prop.states || {})[nextState]),
            };
          }
          return { ...prop, activeEffect: String(event.prop.active_effect || "") };
        }),
      },
    };
  }
  if (event.type === "room.prop.surface" && event.prop_id && state.room) {
    const targetId = String(event.prop_id);
    const incoming = normalizeSurface(event.surface);
    return {
      ...state,
      room: {
        ...state.room,
        props: state.room.props.map(prop => {
          if (prop.id !== targetId) return prop;
          if (Number(prop.surface?.revision || 0) > incoming.revision) return prop;
          return { ...prop, surface: incoming };
        }),
      },
    };
  }
  if (event.type === "room.card.added" && event.stack) {
    return {
      ...state,
      room: {
        ...state.room,
        roomCards: [...state.room.roomCards, normalizeRoomCard(event.stack)],
        chatHistory: [...state.room.chatHistory, asSystemHistory(`${event.dropped_by || "Someone"} dropped a card.`)].slice(-50),
      },
    };
  }
  if (event.type === "room.card.updated") {
    return {
      ...state,
      room: {
        ...state.room,
        roomCards: state.room.roomCards.map(card => card.stackId === event.stack_id ? { ...card, quantity: Number(event.quantity || 0) } : card),
        chatHistory: [...state.room.chatHistory, asSystemHistory(`${event.picked_up_by || "Someone"} picked up a card.`)].slice(-50),
      },
    };
  }
  if (event.type === "room.card.removed") {
    return {
      ...state,
      room: {
        ...state.room,
        roomCards: state.room.roomCards.filter(card => card.stackId !== event.stack_id),
        chatHistory: [...state.room.chatHistory, asSystemHistory(`${event.picked_up_by || "Someone"} picked up the last card.`)].slice(-50),
      },
    };
  }
  if (event.type === "room.cards.reset" && Array.isArray(event.stacks)) {
    return {
      ...state,
      room: {
        ...state.room,
        roomCards: event.stacks.map(normalizeRoomCard),
        chatHistory: [...state.room.chatHistory, asSystemHistory(`${event.reset_by || "Someone"} reset the room.`)].slice(-50),
      },
    };
  }
  if (event.type === "visible.rejection") {
    return {
      ...state,
      ui: { ...state.ui, toasts: [...state.ui.toasts.slice(-2), toastRecord(event.message, "error")] },
      room: { ...state.room, chatHistory: [...state.room.chatHistory, asSystemHistory(event.message)].slice(-50) },
    };
  }
  if (event.type === "dialog.updated") {
    return applyDialogPayload(state, event.dialog);
  }
  if (event.type === "activity.started") {
    const activity = normalizeActivity(event.activity);
    return {
      ...state,
      user: state.user ? { ...state.user, activity } : state.user,
      activities: activity ? [activity] : [],
    };
  }
  if (event.type === "activity.closed") {
    return {
      ...state,
      user: state.user ? { ...state.user, activity: null } : state.user,
      activities: [],
      room: {
        ...state.room,
        chatHistory: [...state.room.chatHistory, asSystemHistory(`${event.activity?.title || "Activity"} closed.`)].slice(-50),
      },
    };
  }
  if (event.type === "task.updated" && event.tasks) {
    return { ...state, user: state.user ? { ...state.user, tasks: normalizeTasks(event.tasks) } : state.user };
  }
  return state;
}

function mergeResultPayload(state, payload) {
  if (!payload) return state;
  let next = state;
  if (payload.user) {
    const user = normalizeUser(payload.user);
    next = { ...next, user, ui: { ...next.ui, actionLogVisible: Boolean(user?.showActivityLog) || next.ui.actionLogVisible } };
  }
  if (payload.counters) {
    const counters = normalizeCounters(payload.counters);
    if (counters && next.user) {
      next = {
        ...next,
        user: {
          ...next.user,
          counters,
          stats: counters.stats,
          statuses: counters.statuses,
          sharedEnergy: counters.energy,
        },
      };
    }
  }
  if (Array.isArray(payload.pinned_peeps)) {
    next = { ...next, user: next.user ? { ...next.user, pinnedPeeps: [...payload.pinned_peeps] } : next.user };
  }
  if (Array.isArray(payload.packs)) {
    next = {
      ...next,
          user: next.user
        ? { ...next.user, packs: payload.packs.map(normalizePack) }
        : next.user,
    };
  }
  if (payload.tasks) {
    next = { ...next, user: next.user ? { ...next.user, tasks: normalizeTasks(payload.tasks) } : next.user };
  }
  if (payload.journal) {
    next = { ...next, user: next.user ? { ...next.user, journal: normalizeJournal(payload.journal) } : next.user };
  }
  if (Array.isArray(payload.commands)) {
    next = {
      ...next,
      commandCatalog: payload.commands.map(item => {
        const name = String(item.name || "");
        return {
          name: name.startsWith(".") || name.startsWith("\\") ? name : `.${name}`,
          summary: String(item.summary || ""),
          usage: String(item.usage || ""),
          power: item.power ? String(item.power) : null,
          help: String(item.help || item.summary || ""),
        };
      }),
    };
  }
  if (Array.isArray(payload.inventory)) {
    const inventory = payload.inventory.map(normalizeInventoryStack);
    next = {
      ...next,
      user: next.user ? { ...next.user, inventory } : next.user,
      room: next.room ? { ...next.room, inventory } : next.room,
    };
  }
  if (typeof payload.show_activity_log === "boolean") {
    next = {
      ...next,
      user: next.user
        ? { ...next.user, showActivityLog: payload.show_activity_log }
        : next.user,
      ui: { ...next.ui, actionLogVisible: payload.show_activity_log },
    };
  }
  if ("activity" in payload) {
    const activity = normalizeActivity(payload.activity);
    next = {
      ...next,
      user: next.user ? { ...next.user, activity } : next.user,
      activities: activity ? [activity] : [],
    };
  }
  if ("dialog" in payload) {
    next = applyDialogPayload(next, payload.dialog);
  }
  if (payload.entity) {
    next = { ...next, describedEntity: clone(payload.entity) };
  }
  return next;
}

function initialPhoneMusic() {
  const track = savedPhoneTrack();
  return {
    track,
    enabled: Boolean(track) && savedPhoneMusicEnabled(),
    mode: "suggestions",
    path: "",
    query: "",
    items: [],
    top: [],
    community: [],
    queue: [],
    queueIndex: 0,
    loading: false,
    error: "",
    loaded: false,
  };
}

function createInitialState() {
  return {
    sessionChecked: false,
    loggedIn: false,
    csrfToken: "",
    auth: { mode: "login", busy: false, error: "" },
    transport: { connected: false, status: "idle", message: "" },
    user: null,
    room: null,
    stickers: [],
    activities: [],
    rtc: { iceServers: [] },
    selection: { kind: "none", id: "" },
    views: { auth: true, main: null, commandPalette: false, propId: null, skillStackId: null, skillPickerSlot: null },
    ui: { actionLogVisible: false, soundEnabled: true, outlineActiveProps: savedOutlineActiveProps(), bubbleTimeout: savedBubbleTimeout(), sidebarSize: savedSidebarSize(), toolbarSize: savedToolbarSize(), inventoryCompact: savedInventoryCompact(), fullscreen: false, audioEnabled: false, audioMuted: false, reducedMotion: REDUCED_MOTION, toasts: [], emoteMenuOpen: false, roomPickerOpen: false, peepsVisible: true, journalTab: "Tasks", inventoryTab: "Items", idCardSide: "self", journalMonthOffset: 0, journalTagFilter: "", phoneApp: "apps", phoneFriendIndex: 0, phoneMusic: initialPhoneMusic(), targeting: null, dropTargeting: null, sellMode: false, titlesOpen: false },
    commandCatalog: [],
    describedEntity: null,
    editor: null,
  };
}

function reduce(state, action) {
  if (typeof action.type === "string" && action.type.startsWith("editor-")) {
    return editorReducer(state, action);
  }
  if (action.type === "session") {
    const user = normalizeUser(action.user);
    return {
      ...state,
      sessionChecked: true,
      loggedIn: Boolean(action.loggedIn),
      csrfToken: String(action.csrfToken || ""),
      user,
      room: action.loggedIn ? state.room : null,
      activities: user?.activity ? [user.activity] : [],
      ui: { ...state.ui, actionLogVisible: Boolean(user?.showActivityLog), soundEnabled: state.ui.soundEnabled, audioEnabled: false, audioMuted: false, phoneApp: action.loggedIn ? state.ui.phoneApp : "apps", phoneMusic: action.loggedIn ? state.ui.phoneMusic : { ...initialPhoneMusic(), enabled: false }, dropTargeting: action.loggedIn ? state.ui.dropTargeting : null },
      views: { auth: !action.loggedIn, main: null, commandPalette: false, skillStackId: null, skillPickerSlot: null },
      auth: { ...state.auth, busy: false, error: "" },
      selection: action.loggedIn ? state.selection : { kind: "none", id: "" },
      commandCatalog: action.loggedIn ? state.commandCatalog : [],
      describedEntity: null,
      editor: action.loggedIn ? state.editor : null,
    };
  }
  if (action.type === "bootstrap") {
    const user = normalizeUser(action.user);
    return {
      ...state,
      loggedIn: Boolean(user),
      user,
      activities: user?.activity ? [user.activity] : [],
      rtc: action.rtc ? { iceServers: Array.isArray(action.rtc.ice_servers) ? action.rtc.ice_servers : [] } : state.rtc,
      ui: { ...state.ui, actionLogVisible: Boolean(user?.showActivityLog) || state.ui.actionLogVisible },
      views: { ...state.views, auth: !user },
      auth: { ...state.auth, busy: false, error: "" },
    };
  }
  if (action.type === "auth-busy") return { ...state, auth: { ...state.auth, busy: action.busy, error: action.error || "" } };
  if (action.type === "auth-mode") return { ...state, auth: { ...state.auth, mode: action.mode, error: "" } };
  if (action.type === "transport") return { ...state, transport: { ...state.transport, ...action.transport } };
  if (action.type === "stickers") return { ...state, stickers: Array.isArray(action.stickers) ? [...action.stickers] : [] };
  if (action.type === "select") {
    if (!selectionIsEligible(state, action.selection)) return state;
    return { ...state, selection: action.selection, ui: { ...state.ui, targeting: null, dropTargeting: null } };
  }
  if (action.type === "start-drop") {
    if (state.room?.board?.type === "diorama") return state;
    const stack = findInventoryCard(state, action.stackId);
    if (!stack || stack.quantity < 1) return state;
    const requested = Number(action.quantity);
    const quantity = Number.isFinite(requested)
      ? Math.min(stack.quantity, Math.max(1, Math.trunc(requested)))
      : 1;
    return {
      ...state,
      selection: { kind: "inventory-card", id: stack.stackId },
      views: { ...state.views, main: null },
      ui: {
        ...state.ui,
        dropTargeting: { stackId: stack.stackId, quantity, label: stack.definition?.label || "card" },
        targeting: null,
        emoteMenuOpen: false,
        roomPickerOpen: false,
        sellMode: false,
      },
    };
  }
  if (action.type === "cancel-drop") {
    const drop = state.ui.dropTargeting;
    const stack = findInventoryCard(state, drop?.stackId);
    const selection = stack && action.restoreSelection !== false
      ? { kind: "inventory-card", id: stack.stackId }
      : state.room ? { kind: "room", id: state.room.id } : state.selection;
    return { ...state, selection, ui: { ...state.ui, dropTargeting: null } };
  }
  if (action.type === "start-targeting") {
    const stack = findInventoryCard(state, action.stackId);
    if (!isTargetableStack(stack)) return state;
    return {
      ...state,
      selection: { kind: "inventory-card", id: stack.stackId },
      views: { ...state.views, main: null },
      ui: { ...state.ui, targeting: { stackId: stack.stackId, label: stack.definition.label }, dropTargeting: null, emoteMenuOpen: false },
    };
  }
  if (action.type === "open-view") {
    if (action.view === "prop-details" && !selectionIsEligible(state, { kind: "prop", id: action.propId })) return state;
    const idSide = { self: "self", skills: "skills" }[action.view];
    const view = idSide ? "id" : action.view;
    let selection = view === "prop-details" ? { kind: "prop", id: action.propId } : { kind: "core", id: view };
    let inventoryTab = state.ui.inventoryTab;
    if (view === "inventory") {
      const next = openInventoryState(state);
      selection = next.selection;
      inventoryTab = next.tab;
    }
    return {
      ...state,
      selection,
      views: {
        ...state.views,
        main: view,
        propId: action.view === "prop-details" ? action.propId || null : null,
        skillStackId: action.view === "skills" ? action.stackId || null : null,
        skillPickerSlot: null,
      },
      ui: { ...state.ui, idCardSide: idSide || state.ui.idCardSide, inventoryTab, phoneApp: view === "phone" ? "apps" : state.ui.phoneApp, targeting: null, dropTargeting: null, sellMode: false, emoteMenuOpen: false, roomPickerOpen: false },
    };
  }
  if (action.type === "id-flip") {
    const side = state.ui.idCardSide === "skills" ? "self" : "skills";
    return { ...state, ui: { ...state.ui, idCardSide: side } };
  }
  if (action.type === "close-view") return { ...state, selection: state.room ? { kind: "room", id: state.room.id } : state.selection, views: { ...state.views, main: null, skillStackId: null, skillPickerSlot: null }, ui: { ...state.ui, phoneApp: "apps", targeting: null, dropTargeting: null, sellMode: false, emoteMenuOpen: false, roomPickerOpen: false } };
  if (action.type === "toggle-room-picker") return { ...state, views: { ...state.views, skillPickerSlot: null }, ui: { ...state.ui, roomPickerOpen: !state.ui.roomPickerOpen, emoteMenuOpen: false } };
  if (action.type === "close-room-picker") return { ...state, views: { ...state.views, skillPickerSlot: null }, ui: { ...state.ui, roomPickerOpen: false } };
  if (action.type === "phone-app") return { ...state, selection: { kind: "core", id: "phone" }, views: { ...state.views, main: "phone" }, ui: { ...state.ui, phoneApp: action.app || "apps", phoneFriendIndex: 0, emoteMenuOpen: false, roomPickerOpen: false, dropTargeting: null } };
  if (action.type === "phone-home") return { ...state, ui: { ...state.ui, phoneApp: "apps" } };
  if (action.type === "phone-friend-step") {
    const count = (state.user?.friends?.friends || []).length;
    if (!count) return state;
    const current = Number(state.ui.phoneFriendIndex || 0);
    const next = (current + Number(action.delta || 0) + count * 1000) % count;
    return { ...state, ui: { ...state.ui, phoneFriendIndex: next } };
  }
  if (action.type === "phone-music-play") {
    const queue = Array.isArray(action.queue) ? action.queue.filter(track => track && typeof track.song === "string" && track.song) : state.ui.phoneMusic.queue;
    const queueIndex = Number.isFinite(action.queueIndex) ? Math.max(0, Number(action.queueIndex)) : state.ui.phoneMusic.queueIndex;
    return { ...state, ui: { ...state.ui, phoneMusic: { ...state.ui.phoneMusic, track: action.track || state.ui.phoneMusic.track, queue, queueIndex, enabled: true } } };
  }
  if (action.type === "phone-music-stop") return { ...state, ui: { ...state.ui, phoneMusic: { ...state.ui.phoneMusic, enabled: false } } };
  if (action.type === "phone-music-toggle") return { ...state, ui: { ...state.ui, phoneMusic: { ...state.ui.phoneMusic, enabled: !state.ui.phoneMusic.enabled } } };
  if (action.type === "phone-music-mode") return { ...state, ui: { ...state.ui, phoneMusic: { ...state.ui.phoneMusic, mode: action.mode || "suggestions", path: action.path || "", query: action.query || "", items: [], loading: Boolean(action.load), error: "", loaded: false } } };
  if (action.type === "phone-music-loading") return { ...state, ui: { ...state.ui, phoneMusic: { ...state.ui.phoneMusic, loading: Boolean(action.loading), error: "" } } };
  if (action.type === "phone-music-loaded") return { ...state, ui: { ...state.ui, phoneMusic: { ...state.ui.phoneMusic, top: Array.isArray(action.top) ? action.top : state.ui.phoneMusic.top, community: Array.isArray(action.community) ? action.community : state.ui.phoneMusic.community, items: Array.isArray(action.items) ? action.items : state.ui.phoneMusic.items, loading: false, error: "", loaded: true } } };
  if (action.type === "phone-music-error") return { ...state, ui: { ...state.ui, phoneMusic: { ...state.ui.phoneMusic, loading: false, error: String(action.error || "The chiptune catalog is unavailable."), loaded: true } } };
  if (action.type === "starred-tracks") return { ...state, user: state.user ? { ...state.user, starredTracks: Array.isArray(action.tracks) ? action.tracks.map(track => ({ song: String(track.song || ""), label: String(track.label || ""), starredAt: String(track.starred_at || "") })).filter(track => track.song) : state.user.starredTracks } : state.user };
  if (action.type === "open-skill-picker") return { ...state, views: { ...state.views, skillPickerSlot: Number(action.slot) }, ui: { ...state.ui, roomPickerOpen: true, emoteMenuOpen: false } };
  if (action.type === "inventory-tab") {
    const next = inventoryTabState(state, action.tab);
    return { ...state, selection: next.selection, ui: { ...state.ui, inventoryTab: next.tab } };
  }
  if (action.type === "toggle-emote-menu") return { ...state, ui: { ...state.ui, emoteMenuOpen: !state.ui.emoteMenuOpen, roomPickerOpen: false, dropTargeting: null } };
  if (action.type === "toggle-peeps") return { ...state, ui: { ...state.ui, peepsVisible: !state.ui.peepsVisible } };
  if (action.type === "close-emote-menu") return { ...state, ui: { ...state.ui, emoteMenuOpen: false } };
  if (action.type === "journal-tab") return { ...state, selection: { kind: "core", id: "journal" }, views: { ...state.views, skillStackId: null, skillPickerSlot: null }, ui: { ...state.ui, journalTab: action.tab, journalTagFilter: action.tag ? String(action.tag) : "", roomPickerOpen: false } };
  if (action.type === "journal-month") return { ...state, ui: { ...state.ui, journalMonthOffset: (state.ui.journalMonthOffset || 0) + Number(action.delta || 0) } };
  if (action.type === "toggle-sell-mode") return { ...state, ui: { ...state.ui, sellMode: !state.ui.sellMode } };
  if (action.type === "toggle-titles") return { ...state, ui: { ...state.ui, titlesOpen: !state.ui.titlesOpen } };
  if (action.type === "toggle-inventory-compact") {
    const enabled = !state.ui.inventoryCompact;
    saveInventoryCompact(enabled);
    return { ...state, ui: { ...state.ui, inventoryCompact: enabled } };
  }
  if (action.type === "cancel-targeting") {
    const stack = findInventoryCard(state, state.ui.targeting?.stackId);
    const selection = stack && action.restoreSelection !== false
      ? { kind: "inventory-card", id: stack.stackId }
      : state.room ? { kind: "room", id: state.room.id } : { kind: "none", id: "" };
    return { ...state, selection, ui: { ...state.ui, targeting: null } };
  }
  if (action.type === "inspect-card") {
    const next = inspectCardState(state, action.stackId);
    if (!next) return state;
    return {
      ...state,
      selection: next.selection,
      views: { ...state.views, main: "inventory", propId: null, skillStackId: null, skillPickerSlot: null },
      ui: { ...state.ui, inventoryTab: next.tab, targeting: null, dropTargeting: null, sellMode: false, emoteMenuOpen: false, roomPickerOpen: false },
    };
  }
  if (action.type === "command-palette") return { ...state, views: { ...state.views, commandPalette: action.open } };
  if (action.type === "dismiss-toast") return { ...state, ui: { ...state.ui, toasts: state.ui.toasts.filter(toast => toast.id !== action.id) } };
  if (action.type === "toast") return { ...state, ui: { ...state.ui, toasts: [...state.ui.toasts.slice(-2), toastRecord(action.message, action.tone)] } };
  if (action.type === "toggle-log") return { ...state, ui: { ...state.ui, actionLogVisible: !state.ui.actionLogVisible } };
  if (action.type === "toggle-sound") return { ...state, ui: { ...state.ui, soundEnabled: !state.ui.soundEnabled } };
  if (action.type === "fullscreen-state") {
    const active = Boolean(action.active);
    if (state.ui.fullscreen === active) return state;
    return { ...state, ui: { ...state.ui, fullscreen: active } };
  }
  if (action.type === "toggle-outline-active-props") {
    const enabled = !state.ui.outlineActiveProps;
    saveOutlineActiveProps(enabled);
    return { ...state, ui: { ...state.ui, outlineActiveProps: enabled } };
  }
  if (action.type === "set-bubble-timeout") {
    const timeout = Number(action.timeout) || 0;
    saveBubbleTimeout(timeout);
    return { ...state, ui: { ...state.ui, bubbleTimeout: timeout } };
  }
  if (action.type === "set-sidebar-size" && ["compact", "normal", "large"].includes(action.size)) {
    saveSidebarSize(action.size);
    return { ...state, ui: { ...state.ui, sidebarSize: action.size } };
  }
  if (action.type === "set-toolbar-size" && ["compact", "normal", "large"].includes(action.size)) {
    saveToolbarSize(action.size);
    return { ...state, ui: { ...state.ui, toolbarSize: action.size } };
  }
  if (action.type === "audio-state") return { ...state, ui: { ...state.ui, audioEnabled: Boolean(action.enabled), audioMuted: Boolean(action.muted) } };
  if (action.type === "log-line" && state.room && action.text) {
    return {
      ...state,
      room: {
        ...state.room,
        chatHistory: [...state.room.chatHistory, asSystemHistory(String(action.text))].slice(-50),
      },
    };
  }
  if (action.type === "dismiss-bubble" && state.room) {
    const mutate = peep => peep.id === action.id ? { ...peep, bubbleDismissed: true } : peep;
    return { ...state, room: { ...state.room, occupants: state.room.occupants.map(mutate), npcs: state.room.npcs.map(mutate) } };
  }
  if (action.type === "snapshot") {
    const previousRoom = state.room;
    const room = normalizeRoom(action.room, previousRoom);
    const sameRoom = room && room.id === previousRoom?.id;
    if (sameRoom) {
      const previousPeeps = new Map([...previousRoom.occupants, ...previousRoom.npcs].map(peep => [peep.id, peep]));
      const preserveBubble = peep => {
        const previous = previousPeeps.get(peep.id);
        return previous ? { ...peep, bubble: previous.bubble, bubbleDismissed: previous.bubbleDismissed } : peep;
      };
      room.occupants = room.occupants.map(preserveBubble);
      room.npcs = room.npcs.map(preserveBubble);
    }
    const next = {
      ...state,
      room,
      selection: sameRoom ? state.selection : room ? { kind: "room", id: room.id } : state.selection,
      views: sameRoom ? state.views : { ...state.views, main: null, skillStackId: null, skillPickerSlot: null },
      ui: sameRoom ? state.ui : { ...state.ui, targeting: null, dropTargeting: null, sellMode: false, emoteMenuOpen: false, roomPickerOpen: false },
      editor: sameRoom ? state.editor : null,
      user: state.user ? { ...state.user, rememberedRoom: room?.id || state.user.rememberedRoom, inventory: room?.inventory || state.user.inventory } : state.user,
    };
    return next;
  }
  if (action.type === "result") {
    let next = mergeResultPayload(state, action.payload);
    const priorToastIds = new Set(next.ui.toasts.map(item => item.id));
    for (const event of action.events || []) next = applyServerEvent(next, event);
    const announcedByEvent = next.ui.toasts.some(item => !priorToastIds.has(item.id));
    if (action.log !== false && action.message && next.room && next.room.chatHistory.at(-1)?.text !== action.message) {
      next = { ...next, room: { ...next.room, chatHistory: [...next.room.chatHistory, asSystemHistory(action.message)].slice(-50) } };
    }
    if (action.ok && action.toast !== false && action.message && !announcedByEvent) next = { ...next, ui: { ...next.ui, toasts: [...next.ui.toasts.slice(-2), toastRecord(action.message, "success")] } };
    if (!action.ok && action.message && !next.ui.toasts.some(item => item.tone === "error" && item.message === action.message)) {
      next = { ...next, ui: { ...next.ui, toasts: [...next.ui.toasts.slice(-2), toastRecord(action.message, "error")] } };
    }
    return next;
  }
  if (action.type === "room-event") return applyServerEvent(state, action.event);
  if (action.type === "session-replaced") {
    const state = createInitialState();
    return {
      ...state,
      sessionChecked: true,
      transport: { connected: false, status: "replaced", message: action.message || "This session was replaced elsewhere." },
      ui: { ...state.ui, phoneMusic: { ...state.ui.phoneMusic, enabled: false }, toasts: [toastRecord(action.message || "This session was replaced elsewhere.", "error")] },
    };
  }
  return state;
}

export function createStore({ now = Date.now, setTimer = setTimeout, clearTimer = clearTimeout } = {}) {
  let state = createInitialState();
  const listeners = new Set();
  let timer = null;
  let deadline = null;
  let disposed = false;
  function dispatch(action) {
    if (disposed) return state;
    const previous = state.room;
    let next = reduce(state, action);
    const room = next.room;
    if (room && (action.type === "eligibility-expired" || !previous || room.board !== previous.board
        || room.environment !== previous.environment || room.props !== previous.props || room.roomCards !== previous.roomCards)) {
      const annotated = annotateRoom(room, now());
      if (annotated !== room) next = { ...next, room: annotated };
    }
    state = next.room !== previous || action.type === "result" ? dismissInvalidSelection(next, selectionIsEligible) : next;
    const expires = state.room?.eligibilityExpiresAt ?? null;
    if (expires !== deadline || action.type === "eligibility-expired") {
      if (timer !== null) clearTimer(timer);
      deadline = expires;
      timer = expires === null ? null : setTimer(() => dispatch({ type: "eligibility-expired" }),
        Math.min(2147483647, Math.max(0, expires - now())));
      timer?.unref?.();
    }
    listeners.forEach(listener => listener(state, action));
    return state;
  }
  return {
    getState() {
      return state;
    },
    subscribe(listener) {
      listeners.add(listener);
      listener(state);
      return () => listeners.delete(listener);
    },
    dispatch,
    dispose() {
      disposed = true;
      if (timer !== null) clearTimer(timer);
      timer = null;
      listeners.clear();
    },
  };
}

export function findRoomCard(state, stackId) {
  return state.room?.roomCards.find(card => card.stackId === stackId) || null;
}

export function findInventoryCard(state, stackId) {
  return state.room?.inventory?.find(card => card.stackId === stackId)
    || state.user?.inventory?.find(card => card.stackId === stackId)
    || null;
}

export function hasSlottedSkill(state, cardDefinitionId) {
  if (!cardDefinitionId) return false;
  return (state.user?.skills || []).some(slot => {
    if (!slot.stackId) return false;
    return findInventoryCard(state, slot.stackId)?.definition?.id === cardDefinitionId;
  });
}

export function isTargetableStack(stack) {
  const definition = stack?.definition;
  const type = definition?.type || "item";
  return Boolean(["prop", "peep"].includes(definition?.target) && (type === "item" || type === "action")
    && (definition.target === "prop" || definition.effect) && !definition.passive && !definition.decorative);
}

export function findSelectedEntity(state) {
  if (!state.room) return null;
  return findEntity(state, state.selection);
}

function selectionIsEligible(state, selection) {
  return !["prop", "room-card"].includes(selection?.kind) || Boolean(findEntity(state, selection));
}

export function findEntity(state, selection) {
  const entity = resolveEntity(state, selection);
  return entity?.selectable === false ? null : entity;
}

function resolveEntity(state, selection) {
  if (!state.room) return null;
  if (selection.kind === "room") return state.room;
  if (selection.kind === "core") {
    return state.user?.coreCards?.[selection.id]
      || (selection.id === "id" ? state.user?.coreCards?.journal || { label: "ID Card", description: "Your identity and skills.", imageUrl: "" } : null);
  }
  if (selection.kind === "task") return findTask(state, selection.id);
  if (selection.kind === "room-card") return findRoomCard(state, selection.id);
  if (selection.kind === "inventory-card") return findInventoryCard(state, selection.id);
  if (selection.kind === "prop") return state.room.props.find(prop => prop.id === selection.id) || null;
  if (selection.kind === "peep") return state.room.occupants.find(peep => peep.id === selection.id)
    || state.room.npcs.find(peep => peep.id === selection.id) || null;
  return null;
}

export function findTask(state, taskId) {
  const tasks = state.user?.tasks;
  if (!tasks) return null;
  return (tasks.active || []).find(task => task.id === taskId)
    || (tasks.completed || []).find(task => task.id === taskId)
    || null;
}
