const CORE_ORDER = ["room", "emotes", "inventory", "skills", "journal", "self", "friends"];
const REDUCED_MOTION = typeof window !== "undefined" && typeof window.matchMedia === "function"
  ? window.matchMedia("(prefers-reduced-motion: reduce)").matches
  : false;
const BUBBLE_LIMIT = 120;

function clone(value) {
  return typeof structuredClone === "function" ? structuredClone(value) : JSON.parse(JSON.stringify(value));
}

function assetOrEmpty(value) {
  return typeof value === "string" && value ? value : "";
}

function normalizeQuickActions(actions) {
  return Array.isArray(actions)
    ? actions
        .filter(action => action && typeof action.command === "string" && typeof action.label === "string")
        .map(action => ({ label: action.label, command: action.command }))
    : [];
}

function normalizeCardDefinition(definition) {
  if (!definition) return null;
  return {
    id: String(definition.id || ""),
    label: String(definition.label || definition.id || "Card"),
    description: String(definition.description || ""),
    type: String(definition.type || ""),
    collectible: Boolean(definition.collectible),
    decorative: Boolean(definition.decorative),
    stackLimit: Number(definition.stack_limit || 1),
    oneUse: Boolean(definition.one_use),
    passive: Boolean(definition.passive),
    imageUrl: assetOrEmpty(definition.image_url),
    rarity: String(definition.rarity || ""),
    target: String(definition.target || ""),
    effect: String(definition.effect || ""),
    amount: Number(definition.amount || 0),
    duration: Number(definition.duration || 0),
    category: String(definition.category || ""),
    rank: String(definition.rank || ""),
    bonuses: definition.bonuses || {},
    quest: Boolean(definition.quest),
  };
}

function normalizeStackBase(stack) {
  return {
    stackId: String(stack?.stack_id || ""),
    quantity: Number(stack?.quantity || 0),
    pinned: Boolean(stack?.pinned),
    definition: normalizeCardDefinition(stack?.definition),
    quickActions: normalizeQuickActions(stack?.quick_actions),
  };
}

function normalizeInventoryStack(stack) {
  return {
    ...normalizeStackBase(stack),
    scope: String(stack?.scope || ""),
    worldId: stack?.world_id ? String(stack.world_id) : "",
    equipped: Boolean(stack?.equipped),
  };
}

function normalizeRoomCard(stack) {
  return {
    ...normalizeStackBase(stack),
    position: Array.isArray(stack?.position) ? stack.position : [50, 50, 0],
  };
}

function normalizeExit(exit) {
  return {
    id: String(exit?.id || ""),
    label: String(exit?.label || ""),
    targetRoomId: String(exit?.target_room_id || ""),
    locked: Boolean(exit?.locked),
    requiresCardId: exit?.requires_card_id ? String(exit.requires_card_id) : "",
    quickAction: exit?.quick_action && typeof exit.quick_action.command === "string"
      ? { label: exit.quick_action.label, command: exit.quick_action.command }
      : null,
  };
}

function normalizeProp(prop) {
  return {
    id: String(prop?.id || ""),
    propId: String(prop?.prop_id || ""),
    label: String(prop?.label || "Prop"),
    description: String(prop?.description || ""),
    position: Array.isArray(prop?.position) ? prop.position : [50, 50, 0],
    rotation: Array.isArray(prop?.rotation) ? prop.rotation : [0, 0, 0],
    scale: Number(prop?.scale || 1),
    behavior: String(prop?.behavior || ""),
    modelUrl: assetOrEmpty(prop?.model_url),
    animation: typeof prop?.animation === "string" ? prop.animation : "",
    quickActions: normalizeQuickActions(prop?.quick_actions),
  };
}

function normalizeActor(entity, { kind, labelSource }) {
  return {
    id: String(entity?.id || ""),
    username: labelSource,
    kind,
    label: labelSource,
    description: String(entity?.description || ""),
    stickerUrl: assetOrEmpty(entity?.sticker_url || entity?.image_url),
    quickActions: normalizeQuickActions(entity?.quick_actions),
    bubble: null,
    bubbleDismissed: false,
  };
}

function normalizeOccupant(occupant) {
  return normalizeActor(occupant, {
    kind: String(occupant?.kind || "user"),
    labelSource: String(occupant?.username || occupant?.label || "Peep"),
  });
}

function normalizeNpc(npc) {
  return normalizeActor(npc, {
    kind: String(npc?.kind || "npc"),
    labelSource: String(npc?.label || npc?.id || "NPC"),
  });
}

function normalizeChatEntry(entry) {
  return {
    id: crypto.randomUUID(),
    speakerId: entry?.speaker_id ? String(entry.speaker_id) : "",
    speaker: String(entry?.speaker || entry?.username || "System"),
    style: String(entry?.style || "normal"),
    text: String(entry?.text || ""),
    kind: entry?.speaker ? "chat" : "system",
  };
}

function normalizeActivity(activity) {
  if (!activity) return null;
  return {
    id: String(activity.id || ""),
    kind: String(activity.kind || ""),
    title: String(activity.title || "Activity"),
    iframeUrl: assetOrEmpty(activity.iframe_url),
    bridgeUrl: assetOrEmpty(activity.bridge_url),
    roomBound: Boolean(activity.room_bound),
    roomId: activity.room_id ? String(activity.room_id) : "",
    attention: Boolean(activity.attention),
  };
}

function normalizeUser(user) {
  if (!user) return null;
  return {
    id: String(user.id || ""),
    username: String(user.username || "Guest"),
    sticker: String(user.sticker || ""),
    stickerUrl: user.sticker ? `/assets/stickers/${user.sticker}` : "",
    initialStickerComplete: Boolean(user.initial_sticker_complete),
    favorites: Array.isArray(user.favorites) ? [...user.favorites] : [],
    inventory: Array.isArray(user.inventory) ? user.inventory.map(normalizeInventoryStack) : [],
    activity: normalizeActivity(user.activity),
    showActivityLog: Boolean(user.show_activity_log),
    level: Number(user.level || 0),
    kudos: Number(user.kudos || 0),
    bops: Number(user.bops || 0),
    sharedEnergy: Number(user.shared_energy || 0),
    worldId: String(user.world_id || ""),
    rememberedRoom: String(user.remembered_room || ""),
    canEnterWorld: user.can_enter_world !== false,
  };
}

function normalizeRoom(room) {
  if (!room) return null;
  return {
    id: String(room.id || ""),
    label: String(room.label || "Room"),
    description: String(room.description || ""),
    board: {
      type: String(room.board?.type || ""),
      imageUrl: assetOrEmpty(room.board?.image_url),
      imageStyle: String(room.board?.image_style || ""),
      palette: Array.isArray(room.board?.palette) ? [...room.board.palette] : [],
      dark: Boolean(room.board?.dark),
    },
    note: String(room.metadata?.note || ""),
    exits: Array.isArray(room.exits) ? room.exits.map(normalizeExit) : [],
    props: Array.isArray(room.props) ? room.props.map(normalizeProp) : [],
    occupants: Array.isArray(room.occupants) ? room.occupants.map(normalizeOccupant) : [],
    npcs: Array.isArray(room.npcs) ? room.npcs.map(normalizeNpc) : [],
    roomCards: Array.isArray(room.room_cards) ? room.room_cards.map(normalizeRoomCard) : [],
    chatHistory: Array.isArray(room.chat_history) ? room.chat_history.map(normalizeChatEntry) : [],
    inventory: Array.isArray(room.inventory) ? room.inventory.map(normalizeInventoryStack) : [],
    favorites: Array.isArray(room.favorites) ? [...room.favorites] : [],
    quickActions: normalizeQuickActions(room.quick_actions),
    seq: Number(room.seq || 0),
  };
}

function coreCard(id, label, description, imageName) {
  return { id, label, description, type: "core", imageUrl: `/assets/base/${imageName}` };
}

export const CORE_CARDS = {
  room: coreCard("room", "Room", "List the cards placed in the current room.", "room.webp"),
  inventory: coreCard("inventory", "Inventory", "Browse the cards you own in this world.", "inventory.webp"),
  emotes: coreCard("emotes", "Emotes", "See expression and animation cards you own.", "emotes.webp"),
  skills: coreCard("skills", "Skills", "Your skill collection. Skill slots are not available yet.", "skills.webp"),
  journal: coreCard("journal", "Journal", "A place for your tasks and memories. Coming in a later milestone.", "journal.webp"),
  self: coreCard("self", "Self", "Check your current counters, Bops, and Kudos.", "self.webp"),
  friends: coreCard("friends", "Friends", "A place to keep in touch. Friend lists are not available yet.", "friends.webp"),
};

function toastRecord(message, tone = "info") {
  return { id: crypto.randomUUID(), message: String(message || ""), tone };
}

function applyBubble(peeps, key, label, text, style) {
  return peeps.map(peep => {
    const match = peep.id === key || peep.username.toLowerCase() === String(label || "").toLowerCase();
    if (!match) return peep;
    const combined = peep.bubble && !peep.bubbleDismissed
      ? `${peep.bubble.text}\n${text}`
      : text;
    const trimmed = combined.length > BUBBLE_LIMIT ? combined.slice(combined.length - BUBBLE_LIMIT) : combined;
    return {
      ...peep,
      bubble: { text: trimmed, style },
      bubbleDismissed: false,
    };
  });
}

function asSystemHistory(text) {
  return { id: crypto.randomUUID(), kind: "system", speaker: "", speakerId: "", style: "normal", text };
}

function applyServerEvent(state, event) {
  if (!event || !state.room) return state;
  if (event.type === "chat.message") {
    const updatedOccupants = applyBubble(state.room.occupants, String(event.speaker_id || ""), event.speaker, String(event.text || ""), String(event.style || "normal"));
    const updatedNpcs = applyBubble(state.room.npcs, String(event.speaker_id || ""), event.speaker, String(event.text || ""), String(event.style || "normal"));
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
    return {
      ...state,
      room: {
        ...state.room,
        chatHistory: [...state.room.chatHistory, asSystemHistory(`${event.username} entered.`)].slice(-50),
      },
    };
  }
  if (event.type === "presence.leave") {
    return {
      ...state,
      room: {
        ...state.room,
        chatHistory: [...state.room.chatHistory, asSystemHistory(`${event.username} left.`)].slice(-50),
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
  return state;
}

function mergeResultPayload(state, payload) {
  if (!payload) return state;
  let next = state;
  if (Array.isArray(payload.commands)) {
    next = {
      ...next,
      commandCatalog: payload.commands.map(item => {
        const name = String(item.name || "");
        return { name: name.startsWith(".") || name.startsWith("\\") ? name : `.${name}`, summary: String(item.summary || "") };
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
  if (Array.isArray(payload.favorites)) {
    const favorites = [...payload.favorites];
    next = {
      ...next,
      user: next.user ? { ...next.user, favorites } : next.user,
      room: next.room ? { ...next.room, favorites } : next.room,
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
  if (payload.entity) {
    next = { ...next, describedEntity: clone(payload.entity) };
  }
  return next;
}

function dismissInvalidSelection(state) {
  if (!state.room) return state;
  if (state.views.details && ![...state.room.roomCards, ...state.room.inventory].some(card => card.stackId === state.views.details)) {
    state = { ...state, views: { ...state.views, details: null } };
  }
  if (state.selection.kind === "room-card" && !state.room.roomCards.some(card => card.stackId === state.selection.id)) {
    return { ...state, selection: { kind: "room", id: state.room.id }, views: { ...state.views, details: null } };
  }
  if (state.selection.kind === "inventory-card" && !state.room.inventory.some(card => card.stackId === state.selection.id)) {
    return { ...state, selection: { kind: "room", id: state.room.id }, views: { ...state.views, details: null } };
  }
  if (state.selection.kind === "peep" && ![...state.room.occupants, ...state.room.npcs].some(peep => peep.id === state.selection.id)) {
    return { ...state, selection: { kind: "room", id: state.room.id } };
  }
  if (state.selection.kind === "prop" && !state.room.props.some(prop => prop.id === state.selection.id)) {
    return { ...state, selection: { kind: "room", id: state.room.id } };
  }
  return state;
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
    selection: { kind: "none", id: "" },
    views: { auth: true, main: null, details: null, commandPalette: false, coreExpanded: false },
    ui: { actionLogVisible: false, soundEnabled: true, reducedMotion: REDUCED_MOTION, toasts: [] },
    commandCatalog: [],
    describedEntity: null,
  };
}

function reduce(state, action) {
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
      ui: { ...state.ui, actionLogVisible: Boolean(user?.showActivityLog), soundEnabled: state.ui.soundEnabled },
      views: { auth: !action.loggedIn, main: null, details: null, commandPalette: false, coreExpanded: false },
      auth: { ...state.auth, busy: false, error: "" },
      selection: action.loggedIn ? state.selection : { kind: "none", id: "" },
      commandCatalog: action.loggedIn ? state.commandCatalog : [],
      describedEntity: null,
    };
  }
  if (action.type === "bootstrap") {
    const user = normalizeUser(action.user);
    return {
      ...state,
      loggedIn: Boolean(user),
      user,
      activities: user?.activity ? [user.activity] : [],
      ui: { ...state.ui, actionLogVisible: Boolean(user?.showActivityLog) || state.ui.actionLogVisible },
      views: { ...state.views, auth: !user },
      auth: { ...state.auth, busy: false, error: "" },
    };
  }
  if (action.type === "auth-busy") return { ...state, auth: { ...state.auth, busy: action.busy, error: action.error || "" } };
  if (action.type === "auth-mode") return { ...state, auth: { ...state.auth, mode: action.mode, error: "" } };
  if (action.type === "transport") return { ...state, transport: { ...state.transport, ...action.transport } };
  if (action.type === "stickers") return { ...state, stickers: Array.isArray(action.stickers) ? [...action.stickers] : [] };
  if (action.type === "select") return { ...state, selection: action.selection };
  if (action.type === "open-view") return { ...state, selection: { kind: "core", id: action.view }, views: { ...state.views, main: action.view, details: null } };
  if (action.type === "close-view") return { ...state, selection: state.room ? { kind: "room", id: state.room.id } : state.selection, views: { ...state.views, main: null, details: null } };
  if (action.type === "toggle-core") return { ...state, views: { ...state.views, coreExpanded: !state.views.coreExpanded } };
  if (action.type === "open-details") return { ...state, views: { ...state.views, details: action.stackId } };
  if (action.type === "close-details") return { ...state, views: { ...state.views, details: null } };
  if (action.type === "command-palette") return { ...state, views: { ...state.views, commandPalette: action.open } };
  if (action.type === "dismiss-toast") return { ...state, ui: { ...state.ui, toasts: state.ui.toasts.filter(toast => toast.id !== action.id) } };
  if (action.type === "toast") return { ...state, ui: { ...state.ui, toasts: [...state.ui.toasts.slice(-2), toastRecord(action.message, action.tone)] } };
  if (action.type === "toggle-log") return { ...state, ui: { ...state.ui, actionLogVisible: !state.ui.actionLogVisible } };
  if (action.type === "toggle-sound") return { ...state, ui: { ...state.ui, soundEnabled: !state.ui.soundEnabled } };
  if (action.type === "dismiss-bubble" && state.room) {
    const mutate = peep => peep.id === action.id ? { ...peep, bubbleDismissed: true } : peep;
    return { ...state, room: { ...state.room, occupants: state.room.occupants.map(mutate), npcs: state.room.npcs.map(mutate) } };
  }
  if (action.type === "snapshot") {
    const room = normalizeRoom(action.room);
    const sameRoom = room && room.id === state.room?.id;
    if (sameRoom) {
      const previousPeeps = new Map([...state.room.occupants, ...state.room.npcs].map(peep => [peep.id, peep]));
      const preserveBubble = peep => {
        const previous = previousPeeps.get(peep.id);
        return previous ? { ...peep, bubble: previous.bubble, bubbleDismissed: previous.bubbleDismissed } : peep;
      };
      room.occupants = room.occupants.map(preserveBubble);
      room.npcs = room.npcs.map(preserveBubble);
      const chatKey = entries => JSON.stringify(entries.filter(entry => entry.kind === "chat").map(entry => [entry.speakerId, entry.speaker, entry.style, entry.text]));
      if (chatKey(room.chatHistory) === chatKey(state.room.chatHistory)) room.chatHistory = state.room.chatHistory;
    }
    const next = {
      ...state,
      room,
      selection: sameRoom ? state.selection : room ? { kind: "room", id: room.id } : state.selection,
      views: sameRoom ? state.views : { ...state.views, main: null, details: null },
      user: state.user ? { ...state.user, rememberedRoom: room?.id || state.user.rememberedRoom, inventory: room?.inventory || state.user.inventory, favorites: room?.favorites || state.user.favorites } : state.user,
    };
    return dismissInvalidSelection(next);
  }
  if (action.type === "result") {
    let next = mergeResultPayload(state, action.payload);
    for (const event of action.events || []) next = applyServerEvent(next, event);
    if (action.message && next.room && next.room.chatHistory.at(-1)?.text !== action.message) {
      next = { ...next, room: { ...next.room, chatHistory: [...next.room.chatHistory, asSystemHistory(action.message)].slice(-50) } };
    }
    const quietAcknowledgement = /^\.(?:say|help|look|settings)(?:\s|$)/.test(action.command || "");
    if (action.ok && action.message && !quietAcknowledgement) next = { ...next, ui: { ...next.ui, toasts: [...next.ui.toasts.slice(-2), toastRecord(action.message, "success")] } };
    if (!action.ok && action.message && !next.ui.toasts.some(item => item.tone === "error" && item.message === action.message)) {
      next = { ...next, ui: { ...next.ui, toasts: [...next.ui.toasts.slice(-2), toastRecord(action.message, "error")] } };
    }
    return dismissInvalidSelection(next);
  }
  if (action.type === "room-event") return dismissInvalidSelection(applyServerEvent(state, action.event));
  if (action.type === "session-replaced") {
    const state = createInitialState();
    return {
      ...state,
      sessionChecked: true,
      transport: { connected: false, status: "replaced", message: action.message || "This session was replaced elsewhere." },
      ui: { ...state.ui, toasts: [toastRecord(action.message || "This session was replaced elsewhere.", "error")] },
    };
  }
  return state;
}

export function createStore() {
  let state = createInitialState();
  const listeners = new Set();
  return {
    getState() {
      return state;
    },
    subscribe(listener) {
      listeners.add(listener);
      listener(state);
      return () => listeners.delete(listener);
    },
    dispatch(action) {
      state = reduce(state, action);
      listeners.forEach(listener => listener(state, action));
      return state;
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

export function findSelectedEntity(state) {
  if (!state.room) return null;
  if (state.selection.kind === "room") return state.room;
  if (state.selection.kind === "core") return CORE_CARDS[state.selection.id] || null;
  if (state.selection.kind === "room-card") return findRoomCard(state, state.selection.id);
  if (state.selection.kind === "inventory-card") return findInventoryCard(state, state.selection.id);
  if (state.selection.kind === "prop") return state.room.props.find(prop => prop.id === state.selection.id) || null;
  if (state.selection.kind === "peep") return [...state.room.occupants, ...state.room.npcs].find(peep => peep.id === state.selection.id) || null;
  return null;
}

export { CORE_ORDER };
