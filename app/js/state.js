import { editorReducer } from "./editing/edit-reducer.js";

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
    sellPrice: typeof definition.sell_price === "number" ? definition.sell_price : null,
    order: typeof definition.order === "number" ? definition.order : null,
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

function normalizePack(pack) {
  return {
    id: String(pack?.id || ""),
    label: String(pack?.label || ""),
    description: String(pack?.description || ""),
    price: Number(pack?.price || 0),
    size: Number(pack?.size || 0),
    backImageUrl: assetOrEmpty(pack?.back_image_url),
  };
}

function normalizeCounters(counters) {
  if (!counters || typeof counters !== "object") return null;
  return {
    health: Number(counters.health || 0),
    energy: Number(counters.energy || 0),
    cleanliness: Number(counters.cleanliness || 0),
    maxHealth: Number(counters.max_health || 0),
    maxEnergy: Number(counters.max_energy || 0),
    maxCleanliness: Number(counters.max_cleanliness || 0),
    stats: counters.stats && typeof counters.stats === "object" ? { ...counters.stats } : {},
    statuses: Array.isArray(counters.statuses) ? [...counters.statuses] : [],
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
    statuses: Array.isArray(entity?.statuses) ? [...entity.statuses] : [],
    counters: normalizeCounters(entity?.counters),
    pinned: Boolean(entity?.pinned),
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
    config: activity.config && typeof activity.config === "object" ? activity.config : {},
  };
}

function normalizeDialog(dialog) {
  if (!dialog) return null;
  return {
    peepId: String(dialog.peep_id || ""),
    peepLabel: String(dialog.peep_label || ""),
    nodeId: String(dialog.node_id || ""),
    revision: Number(dialog.revision || 0),
    text: String(dialog.text || ""),
    choices: Array.isArray(dialog.choices)
      ? dialog.choices.map(choice => ({
          label: String(choice.label || ""),
          index: Number(choice.index || 0),
          actionId: String(choice.action_id || ""),
          disabled: Boolean(choice.disabled),
        }))
      : [],
  };
}

function normalizeTaskStep(step) {
  return {
    stepId: String(step?.step_id || ""),
    title: String(step?.title || ""),
    trigger: String(step?.trigger || ""),
    amount: Number(step?.amount || 1),
    progress: Number(step?.progress || 0),
    complete: Boolean(step?.complete),
    memoryTag: step?.memory_tag ? String(step.memory_tag) : "",
  };
}

function normalizeTask(task) {
  if (!task) return null;
  return {
    id: String(task.id || ""),
    scope: String(task.scope || "personal"),
    title: String(task.title || "Task"),
    description: String(task.description || ""),
    status: String(task.status || "active"),
    revision: Number(task.revision || 1),
    reward: {
      kudos: Number(task.reward?.kudos || 0),
      cards: Array.isArray(task.reward?.cards) ? task.reward.cards.map(String) : [],
    },
    memoryTags: Array.isArray(task.memory_tags) ? task.memory_tags.map(String) : [],
    repeatable: Boolean(task.repeatable),
    resetPolicy: task.reset_policy ? String(task.reset_policy) : "",
    startedAt: String(task.started_at || ""),
    completedAt: task.completed_at ? String(task.completed_at) : "",
    steps: Array.isArray(task.steps) ? task.steps.map(normalizeTaskStep) : [],
  };
}

function normalizeTasks(tasks) {
  const active = Array.isArray(tasks?.active) ? tasks.active.map(normalizeTask).filter(Boolean) : [];
  const completed = Array.isArray(tasks?.completed) ? tasks.completed.map(normalizeTask).filter(Boolean) : [];
  return { active, completed };
}

function normalizeMemory(memory) {
  return {
    memoryId: String(memory?.memory_id || ""),
    author: String(memory?.author || ""),
    sourceType: String(memory?.source_type || "game"),
    text: String(memory?.text || ""),
    tags: Array.isArray(memory?.tags) ? memory.tags.map(String) : [],
    taskId: memory?.task_id ? String(memory.task_id) : "",
    createdAt: String(memory?.created_at || ""),
    editable: Boolean(memory?.editable),
    localDate: String(memory?.local_date || ""),
  };
}

function normalizeJournal(journal) {
  const summary = journal?.summary && typeof journal.summary === "object" ? journal.summary : {};
  return {
    summary: {
      year: Number(summary.year || 0),
      month: Number(summary.month || 0),
      dayCounts: summary.day_counts && typeof summary.day_counts === "object" ? { ...summary.day_counts } : {},
      memoryCount: Number(summary.memory_count || 0),
      tasksCompleted: Number(summary.tasks_completed || 0),
      kudos: Number(summary.kudos || 0),
      newFriends: Number(summary.new_friends || 0),
    },
    memories: Array.isArray(journal?.memories) ? journal.memories.map(normalizeMemory) : [],
  };
}

function normalizeUser(user) {
  if (!user) return null;
  const normalizedCore = (Array.isArray(user.core_cards) ? user.core_cards : [])
    .map(normalizeCardDefinition)
    .filter(definition => definition && definition.id);
  return {
    id: String(user.id || ""),
    username: String(user.username || "Guest"),
    sticker: String(user.sticker || ""),
    stickerUrl: user.sticker ? `/assets/stickers/${user.sticker}` : "",
    initialStickerComplete: Boolean(user.initial_sticker_complete),
    inventory: Array.isArray(user.inventory) ? user.inventory.map(normalizeInventoryStack) : [],
    coreCards: Object.fromEntries(normalizedCore.map(definition => [definition.id, definition])),
    coreOrder: normalizedCore
      .filter(definition => definition.order !== null)
      .sort((left, right) => left.order - right.order)
      .map(definition => definition.id),
    activity: normalizeActivity(user.activity),
    showActivityLog: Boolean(user.show_activity_log),
    level: Number(user.level || 0),
    levelLabel: String(user.level_label || ""),
    kudos: Number(user.kudos || 0),
    kudosToNext: typeof user.kudos_to_next === "number" ? user.kudos_to_next : null,
    bops: Number(user.bops || 0),
    stickerSwapCost: Number(user.sticker_swap_cost || 0),
    sharedEnergy: Number(user.shared_energy || 0),
    counters: normalizeCounters(user.counters) || { health: 0, energy: 0, cleanliness: 0, maxHealth: 0, maxEnergy: 0, maxCleanliness: 0, stats: {}, statuses: [] },
    stats: user.stats && typeof user.stats === "object" ? { ...user.stats } : {},
    statuses: Array.isArray(user.statuses) ? [...user.statuses] : [],
    statusDefinitions: user.status_definitions && typeof user.status_definitions === "object" ? { ...user.status_definitions } : {},
    powers: Array.isArray(user.powers) ? user.powers.map(power => String(power)) : [],
    skills: Array.isArray(user.skills) ? user.skills.map(slot => ({
      index: Number(slot.index || 0),
      rank: String(slot.rank || ""),
      unlocked: Boolean(slot.unlocked),
      stackId: slot.stack_id ? String(slot.stack_id) : null,
    })) : [],
    pinnedPeeps: Array.isArray(user.pinned_peeps) ? [...user.pinned_peeps] : [],
    friends: user.friends && typeof user.friends === "object"
      ? {
          friends: Array.isArray(user.friends.friends) ? [...user.friends.friends] : [],
          incoming: Array.isArray(user.friends.incoming) ? [...user.friends.incoming] : [],
          outgoing: Array.isArray(user.friends.outgoing) ? [...user.friends.outgoing] : [],
        }
      : { friends: [], incoming: [], outgoing: [] },
    packs: Array.isArray(user.packs) ? user.packs.map(normalizePack) : [],
    tasks: normalizeTasks(user.tasks),
    journal: normalizeJournal(user.journal),
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
    environment: room.environment && typeof room.environment === "object" ? { ...room.environment } : {},
    environmentRevision: Number(room.environment_revision || 0),
    exits: Array.isArray(room.exits) ? room.exits.map(normalizeExit) : [],
    props: Array.isArray(room.props) ? room.props.map(normalizeProp) : [],
    occupants: Array.isArray(room.occupants) ? room.occupants.map(normalizeOccupant) : [],
    npcs: Array.isArray(room.npcs) ? room.npcs.map(normalizeNpc) : [],
    roomCards: Array.isArray(room.room_cards) ? room.room_cards.map(normalizeRoomCard) : [],
    chatHistory: Array.isArray(room.chat_history) ? room.chat_history.map(normalizeChatEntry) : [],
    inventory: Array.isArray(room.inventory) ? room.inventory.map(normalizeInventoryStack) : [],
    editable: Boolean(room.editable),
    canEditRoom: Boolean(room.can_edit_room),
    layoutRevision: Number(room.layout_revision || 0),
    dialog: normalizeDialog(room.dialog),
    quickActions: normalizeQuickActions(room.quick_actions),
  };
}

function toastRecord(message, tone = "info", silent = false) {
  return { id: crypto.randomUUID(), message: String(message || ""), tone, silent: Boolean(silent) };
}

function applyBubble(peeps, key, label, text, style, imageUrl = "") {
  const url = String(imageUrl || "");
  return peeps.map(peep => {
    const match = peep.id === key || peep.username.toLowerCase() === String(label || "").toLowerCase();
    if (!match) return peep;
    if (url) {
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

function updatePeepCounters(peeps, targetId, event) {
  return peeps.map(peep => {
    if (peep.id !== targetId) return peep;
    const counters = {
      ...(peep.counters || {}),
      health: Number(event.health ?? peep.counters?.health ?? 0),
      energy: Number(event.energy ?? peep.counters?.energy ?? 0),
      maxHealth: Number(event.max_health ?? peep.counters?.maxHealth ?? 0),
      maxEnergy: Number(event.max_energy ?? peep.counters?.maxEnergy ?? 0),
      statuses: Array.isArray(event.statuses) ? [...event.statuses] : (peep.counters?.statuses || []),
    };
    return {
      ...peep,
      counters,
      statuses: Array.isArray(event.statuses) ? [...event.statuses] : peep.statuses,
    };
  });
}

function pushFloating(state, entry) {
  return { ...state.ui, floatingNumbers: [...state.ui.floatingNumbers, entry].slice(-8) };
}

function applyServerEvent(state, event) {
  if (!event || !state.room) return state;
  if (event.type === "counter.updated") {
    const targetId = String(event.target_id || "");
    const amount = Number(event.health_delta || 0) || Number(event.energy_delta || 0);
    const kind = Number(event.health_delta || 0) ? "health" : "energy";
    const entry = {
      id: crypto.randomUUID(),
      targetId,
      label: String(event.target_label || ""),
      amount,
      kind,
    };
    const withCounters = {
      ...state,
      room: {
        ...state.room,
        occupants: updatePeepCounters(state.room.occupants, targetId, event),
        npcs: updatePeepCounters(state.room.npcs, targetId, event),
      },
      ui: pushFloating(state, entry),
    };
    return withCounters;
  }
  if (event.type === "emote.bubble") {
    const bubble = event.bubble || {};
    const updatedOccupants = applyBubble(state.room.occupants, String(event.source_id || ""), event.source, String(bubble.text || ""), String(bubble.kind || "expression"), String(bubble.image_url || ""));
    const updatedNpcs = applyBubble(state.room.npcs, String(event.source_id || ""), event.source, String(bubble.text || ""), String(bubble.kind || "expression"), String(bubble.image_url || ""));
    return {
      ...state,
      room: { ...state.room, occupants: updatedOccupants, npcs: updatedNpcs },
    };
  }
  if (event.type === "effect.queued") {
    return {
      ...state,
      ui: {
        ...state.ui,
        effects: [...state.ui.effects, {
          id: crypto.randomUUID(),
          effect: String(event.effect || ""),
          source: String(event.source || ""),
        }].slice(-6),
      },
    };
  }
  if (event.type === "toast") {
    return { ...state, ui: { ...state.ui, toasts: [...state.ui.toasts.slice(-2), toastRecord(event.text, event.tone || "info", event.silent)] } };
  }
  if (event.type === "action.log") {
    return state;
  }
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
  if (event.type === "room.environment") {
    const revision = Number(event.revision || 0);
    if (revision <= Number(state.room.environmentRevision || 0)) return state;
    const environment = event.environment && typeof event.environment === "object" ? { ...event.environment } : {};
    const lighting = environment.lighting;
    const dark = lighting === "dark" ? true : lighting === "normal" ? false : state.room.board.dark;
    return {
      ...state,
      room: {
        ...state.room,
        environment,
        environmentRevision: revision,
        board: { ...state.room.board, dark },
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
        props: Array.isArray(event.props) ? event.props.map(normalizeProp) : state.room.props,
        board: {
          ...state.room.board,
          palette: Array.isArray(environment.palette) ? [...environment.palette] : state.room.board.palette,
          imageStyle: environment.board_image_style ? String(environment.board_image_style) : state.room.board.imageStyle,
        },
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
    return { ...state, room: { ...state.room, dialog: normalizeDialog(event.dialog) } };
  }
  if (event.type === "shop.open") {
    return {
      ...state,
      editor: null,
      shop: true,
      views: { ...state.views, main: null, details: null },
      ui: { ...state.ui, targeting: null },
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
    next = {
      ...next,
      room: next.room ? { ...next.room, dialog: normalizeDialog(payload.dialog) } : next.room,
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
    views: { auth: true, main: null, details: null, commandPalette: false, propId: null, skillStackId: null },
    ui: { actionLogVisible: false, soundEnabled: true, reducedMotion: REDUCED_MOTION, toasts: [], effects: [], floatingNumbers: [], emoteCategory: "Expression", journalTab: "Tasks", journalMonthOffset: 0, journalTagFilter: "", targeting: null },
    commandCatalog: [],
    describedEntity: null,
    editor: null,
    shop: false,
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
      ui: { ...state.ui, actionLogVisible: Boolean(user?.showActivityLog), soundEnabled: state.ui.soundEnabled },
      views: { auth: !action.loggedIn, main: null, details: null, commandPalette: false },
      auth: { ...state.auth, busy: false, error: "" },
      selection: action.loggedIn ? state.selection : { kind: "none", id: "" },
      commandCatalog: action.loggedIn ? state.commandCatalog : [],
      describedEntity: null,
      editor: action.loggedIn ? state.editor : null,
      shop: false,
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
  if (action.type === "open-view") {
    return {
      ...state,
      shop: false,
      selection: { kind: "core", id: action.view },
      views: {
        ...state.views,
        main: action.view,
        details: null,
        propId: action.view === "prop-details" ? action.propId || null : null,
        skillStackId: action.view === "skills" ? action.stackId || null : null,
      },
      ui: { ...state.ui, targeting: null },
    };
  }
  if (action.type === "close-view") return { ...state, selection: state.room ? { kind: "room", id: state.room.id } : state.selection, views: { ...state.views, main: null, details: null }, ui: { ...state.ui, targeting: null } };
  if (action.type === "shop-open") return { ...state, editor: null, shop: true, views: { ...state.views, main: null, details: null }, ui: { ...state.ui, targeting: null } };
  if (action.type === "shop-close") return { ...state, shop: false };
  if (action.type === "emote-category") return { ...state, ui: { ...state.ui, emoteCategory: action.category } };
  if (action.type === "journal-tab") return { ...state, ui: { ...state.ui, journalTab: action.tab, journalTagFilter: action.tag ? String(action.tag) : "" } };
  if (action.type === "journal-month") return { ...state, ui: { ...state.ui, journalMonthOffset: (state.ui.journalMonthOffset || 0) + Number(action.delta || 0) } };
  if (action.type === "start-targeting") return { ...state, views: { ...state.views, main: null, details: null }, ui: { ...state.ui, targeting: { stackId: action.stackId, label: action.label } } };
  if (action.type === "cancel-targeting") return { ...state, ui: { ...state.ui, targeting: null } };
  if (action.type === "open-details") return { ...state, views: { ...state.views, details: action.stackId } };
  if (action.type === "close-details") return { ...state, views: { ...state.views, details: null } };
  if (action.type === "command-palette") return { ...state, views: { ...state.views, commandPalette: action.open } };
  if (action.type === "dismiss-toast") return { ...state, ui: { ...state.ui, toasts: state.ui.toasts.filter(toast => toast.id !== action.id) } };
  if (action.type === "consume-effect") return { ...state, ui: { ...state.ui, effects: state.ui.effects.filter(effect => effect.id !== action.id) } };
  if (action.type === "consume-floating") return { ...state, ui: { ...state.ui, floatingNumbers: state.ui.floatingNumbers.filter(number => number.id !== action.id) } };
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
      ui: sameRoom ? state.ui : { ...state.ui, targeting: null },
      editor: sameRoom ? state.editor : null,
      user: state.user ? { ...state.user, rememberedRoom: room?.id || state.user.rememberedRoom, inventory: room?.inventory || state.user.inventory } : state.user,
    };
    return dismissInvalidSelection(next);
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
  if (state.selection.kind === "core") return state.user?.coreCards?.[state.selection.id] || null;
  if (state.selection.kind === "task") return findTask(state, state.selection.id);
  if (state.selection.kind === "room-card") return findRoomCard(state, state.selection.id);
  if (state.selection.kind === "inventory-card") return findInventoryCard(state, state.selection.id);
  if (state.selection.kind === "prop") return state.room.props.find(prop => prop.id === state.selection.id) || null;
  if (state.selection.kind === "peep") return [...state.room.occupants, ...state.room.npcs].find(peep => peep.id === state.selection.id) || null;
  return null;
}

export function findTask(state, taskId) {
  const tasks = state.user?.tasks;
  if (!tasks) return null;
  return (tasks.active || []).find(task => task.id === taskId)
    || (tasks.completed || []).find(task => task.id === taskId)
    || null;
}
