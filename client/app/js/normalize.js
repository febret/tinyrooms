/** Room, card, actor, and game-state normalization helpers. */

import { withBase } from "./base-path.js";

export function clone(value) {
  return typeof structuredClone === "function" ? structuredClone(value) : JSON.parse(JSON.stringify(value));
}

export function assetOrEmpty(value) {
  return typeof value === "string" && value ? withBase(value) : "";
}

export function normalizeQuickActions(actions) {
  return Array.isArray(actions)
    ? actions
        .filter(action => action && typeof action.command === "string" && typeof action.label === "string")
        .map(action => ({
          label: action.label,
          command: action.command,
          ...(action.default ? { default: true } : {}),
          ...(typeof action.sound === "string" && action.sound ? { sound: assetOrEmpty(action.sound) } : {}),
        }))
    : [];
}

export function normalizeSounds(sounds) {
  return sounds && typeof sounds === "object"
    ? Object.fromEntries(
        Object.entries(sounds)
          .filter(([, value]) => typeof value === "string" && value)
          .map(([key, value]) => [key, assetOrEmpty(value)]),
      )
    : {};
}

export function normalizeCardDefinition(definition) {
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
    backgroundUrl: assetOrEmpty(definition.background_url),
    backUrl: assetOrEmpty(definition.back_url),
    energyCost: typeof definition.energy_cost === "number" ? definition.energy_cost : null,
    rarity: String(definition.rarity || ""),
    target: String(definition.target || ""),
    effect: String(definition.effect || ""),
    amount: Number(definition.amount || 0),
    duration: Number(definition.duration || 0),
    category: String(definition.category || ""),
    cutscene: String(definition.cutscene || ""),
    rank: String(definition.rank || ""),
    bonuses: definition.bonuses || {},
    tags: Array.isArray(definition.tags) ? definition.tags.map(String) : [],
    quest: Boolean(definition.quest),
    sellPrice: typeof definition.sell_price === "number" ? definition.sell_price : null,
    order: typeof definition.order === "number" ? definition.order : null,
    sounds: normalizeSounds(definition.sounds),
  };
}

export function normalizeStackBase(stack) {
  return {
    stackId: String(stack?.stack_id || ""),
    quantity: Number(stack?.quantity || 0),
    pinned: Boolean(stack?.pinned),
    definition: normalizeCardDefinition(stack?.definition),
    quickActions: normalizeQuickActions(stack?.quick_actions),
  };
}

export function normalizeInventoryStack(stack) {
  return {
    ...normalizeStackBase(stack),
    scope: String(stack?.scope || ""),
    worldId: stack?.world_id ? String(stack.world_id) : "",
    equipped: Boolean(stack?.equipped),
  };
}

export function normalizeRoomCard(stack) {
  return {
    ...normalizeStackBase(stack),
    position: Array.isArray(stack?.position) ? stack.position : [50, 50, 0],
  };
}

export function normalizeExit(exit) {
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

export function normalizeSurface(surface) {
  return {
    kind: String(surface?.kind || ""),
    revision: Number(surface?.revision || 0),
    updatedBy: surface?.updated_by ? String(surface.updated_by) : "",
    content: surface?.content && typeof surface.content === "object" ? { ...surface.content } : {},
  };
}

export function normalizeProp(prop) {
  return {
    id: String(prop?.id || ""),
    hidden: Boolean(prop?.hidden),
    propId: String(prop?.prop_id || ""),
    label: String(prop?.label || "Prop"),
    description: String(prop?.description || ""),
    position: Array.isArray(prop?.position) ? prop.position : [50, 50, 0],
    rotation: Array.isArray(prop?.rotation) ? prop.rotation : [0, 0, 0],
    scale: Number(prop?.scale || 1),
    behavior: String(prop?.behavior || ""),
    modelUrl: assetOrEmpty(prop?.model_url),
    renderKind: String(prop?.render_kind || "model"),
    ...(prop?.text ? { text: { ...prop.text } } : {}),
    ...(typeof prop?.sign_style === "string" ? { signStyle: prop.sign_style } : {}),
    ...(prop?.surface && typeof prop.surface === "object" ? { surface: normalizeSurface(prop.surface) } : {}),
    animation: typeof prop?.animation === "string" ? prop.animation : "",
    state: typeof prop?.active_state === "string"
      ? prop.active_state
      : (typeof prop?.state === "string" ? prop.state : ""),
    states: prop?.states && typeof prop.states === "object"
      ? Object.fromEntries(Object.entries(prop.states).map(([name, url]) => [name, assetOrEmpty(url)]))
      : {},
    effectSets: prop?.effect_sets && typeof prop.effect_sets === "object" ? prop.effect_sets : {},
    activeEffect: typeof prop?.active_effect === "string" ? prop.active_effect : "",
    light: prop?.light && typeof prop.light === "object"
      ? {
        kind: String(prop.light.kind || ""),
        on: prop.light.on !== false,
        color: typeof prop.light.color === "string" ? prop.light.color : "",
      }
      : null,
    quickActions: normalizeQuickActions(prop?.quick_actions),
    sounds: normalizeSounds(prop?.sounds),
  };
}

/** Apply a layout broadcast: server labels/descriptions win, local behavior kept. */
export function mergeLayoutProps(previousProps, layoutProps) {
  if (!Array.isArray(layoutProps)) return previousProps;
  const previous = new Map((Array.isArray(previousProps) ? previousProps : []).map(prop => [prop.id, prop]));
  return layoutProps.map(entry => {
    const next = normalizeProp(entry);
    const existing = previous.get(next.id);
    if (!existing) return next;
    return {
      ...existing,
      ...next,
      behavior: existing.behavior,
      quickActions: existing.quickActions,
      sounds: existing.sounds,
      light: existing.light ?? next.light,
    };
  });
}

export function normalizePack(pack) {
  return {
    id: String(pack?.id || ""),
    label: String(pack?.label || ""),
    description: String(pack?.description || ""),
    price: Number(pack?.price || 0),
    size: Number(pack?.size || 0),
    backImageUrl: assetOrEmpty(pack?.back_image_url),
  };
}

export function normalizeCounters(counters) {
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
    decals: Array.isArray(counters.decals) ? counters.decals.map(entry => ({ ...entry })) : [],
  };
}

export function normalizeVibes(vibes) {
  if (!vibes || typeof vibes !== "object") return null;
  const pair = side => side && typeof side === "object"
    ? { value: Number(side.value || 0), label: String(side.label || "") }
    : null;
  return { toward: pair(vibes.toward), from: pair(vibes.from) };
}

export function normalizeActor(entity, { kind, labelSource }) {
  return {
    id: String(entity?.id || ""),
    username: labelSource,
    kind,
    label: labelSource,
    description: String(entity?.description || ""),
    stickerUrl: assetOrEmpty(entity?.sticker_url || entity?.image_url),
    quickActions: normalizeQuickActions(entity?.quick_actions),
    powers: Array.isArray(entity?.powers) ? entity.powers.map(power => String(power)) : [],
    statuses: Array.isArray(entity?.statuses) ? [...entity.statuses] : [],
    decals: Array.isArray(entity?.decals)
      ? entity.decals.map(entry => ({ ...entry }))
      : (Array.isArray(entity?.counters?.decals) ? entity.counters.decals.map(entry => ({ ...entry })) : []),
    counters: normalizeCounters(entity?.counters),
    vibes: normalizeVibes(entity?.vibes),
    pinned: Boolean(entity?.pinned),
    audioEnabled: Boolean(entity?.audio_enabled),
    spritePosition: Array.isArray(entity?.sprite?.position) ? entity.sprite.position.map(Number) : null,
    bubble: null,
    bubbleDismissed: false,
  };
}

export function normalizeOccupant(occupant) {
  const normalized = normalizeActor(occupant, {
    kind: String(occupant?.kind || "user"),
    labelSource: String(occupant?.label || occupant?.username || "Peep"),
  });
  normalized.username = String(occupant?.username || normalized.username || "Peep");
  return normalized;
}

export function normalizeNpc(npc) {
  return normalizeActor(npc, {
    kind: String(npc?.kind || "npc"),
    labelSource: String(npc?.label || npc?.id || "NPC"),
  });
}

export function normalizeChatEntry(entry) {
  return {
    id: "",
    speakerId: entry?.speaker_id ? String(entry.speaker_id) : "",
    speaker: String(entry?.speaker_label || entry?.speaker || entry?.username || "System"),
    style: String(entry?.style || "normal"),
    text: String(entry?.text || ""),
    kind: entry?.speaker ? "chat" : "system",
  };
}

/** Stable content key for a chat line, used to carry identity across snapshots. */
export function chatEntryKey(entry) {
  return `${entry.speakerId}\0${entry.speaker}\0${entry.style}\0${entry.text}`;
}

/**
 * Normalise a chat log, reusing the previous entry objects for unchanged lines.
 *
 * The server resends the whole log on every snapshot, and presence events ask
 * for a snapshot on every join and leave. Minting a fresh `crypto.randomUUID()`
 * per line therefore ran 50 UUID generations per resync, and replacing every
 * entry object defeated identity checks downstream. Matching on content keeps
 * the array reference stable when nothing changed.
 */
export function normalizeChatHistory(rawEntries, previous = []) {
  if (!Array.isArray(rawEntries)) return [];
  if (rawEntries.length === 0 && previous.length === 0) return previous;
  const available = new Map();
  for (const entry of previous) {
    if (!available.has(chatEntryKey(entry))) available.set(chatEntryKey(entry), entry);
  }
  const reused = new Set();
  let unchanged = rawEntries.length === previous.length;
  const result = rawEntries.map((raw, index) => {
    const normalized = normalizeChatEntry(raw);
    const key = chatEntryKey(normalized);
    const existing = available.get(key);
    if (existing && !reused.has(existing)) {
      reused.add(existing);
      if (existing !== previous[index]) unchanged = false;
      return existing;
    }
    unchanged = false;
    return { ...normalized, id: `chat:${index}:${key}` };
  });
  // An identical log must keep the previous array so views can skip re-rendering.
  return unchanged ? previous : result;
}

export function normalizeActivity(activity) {
  if (!activity) return null;
  return {
    id: String(activity.id || ""),
    kind: String(activity.kind || ""),
    title: String(activity.title || "Activity"),
    iframeUrl: assetOrEmpty(activity.iframe_url),
    bridgeUrl: assetOrEmpty(activity.bridge_url),
    roomId: activity.room_id ? String(activity.room_id) : "",
    attention: Boolean(activity.attention),
    token: String(activity.token || ""),
    config: activity.config && typeof activity.config === "object" ? activity.config : {},
  };
}

export function normalizeDialog(dialog) {
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

export function normalizeTaskStep(step) {
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

export function normalizeTask(task) {
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
    worldId: String(task.world_id || ""),
    worldLabel: String(task.world_label || ""),
    steps: Array.isArray(task.steps) ? task.steps.map(normalizeTaskStep) : [],
  };
}

export function normalizeTasks(tasks) {
  const active = Array.isArray(tasks?.active) ? tasks.active.map(normalizeTask).filter(Boolean) : [];
  const completed = Array.isArray(tasks?.completed) ? tasks.completed.map(normalizeTask).filter(Boolean) : [];
  return { active, completed };
}

export function normalizeTitlePart(part) {
  if (!part || typeof part !== "object") return null;
  const unlock = part.unlock && typeof part.unlock === "object" ? { ...part.unlock } : { kind: "" };
  return {
    id: String(part.id || ""),
    label: String(part.label || ""),
    slot: String(part.slot || ""),
    unlock,
  };
}

export function normalizeTitles(titles) {
  const catalog = Array.isArray(titles?.catalog) ? titles.catalog.map(normalizeTitlePart).filter(Boolean) : [];
  const unlocked = Array.isArray(titles?.unlocked) ? titles.unlocked.map(entry => String(entry)) : [];
  const selection = titles?.selection && typeof titles.selection === "object" ? titles.selection : {};
  return {
    catalog,
    unlocked,
    selection: {
      salutation: selection.salutation ? String(selection.salutation) : null,
      nickname: selection.nickname ? String(selection.nickname) : null,
      suffix: selection.suffix ? String(selection.suffix) : null,
      crewName: String(selection.crew_name || ""),
      displayLabel: String(selection.display_label || ""),
    },
    cookedCount: Number(titles?.cooked_count || 0),
    taughtCount: Number(titles?.taught_count || 0),
  };
}

export function normalizeMemory(memory) {
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
    worldId: String(memory?.world_id || ""),
    worldLabel: String(memory?.world_label || ""),
  };
}

export function normalizeJournal(journal) {
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

export function normalizeUser(user) {
  if (!user) return null;
  const normalizedCore = (Array.isArray(user.core_cards) ? user.core_cards : [])
    .map(normalizeCardDefinition)
    .filter(definition => definition && definition.id);
  return {
    id: String(user.id || ""),
    username: String(user.username || "Guest"),
    sticker: String(user.sticker || ""),
    stickerUrl: user.sticker ? withBase(`/assets/stickers/${user.sticker}`) : "",
    stickerDesign: user.sticker_design && typeof user.sticker_design === "object"
      ? {
          ...user.sticker_design,
          colors: user.sticker_design.colors && typeof user.sticker_design.colors === "object"
            ? { ...user.sticker_design.colors }
            : {},
        }
      : null,
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
    starredTracks: Array.isArray(user.starred_tracks) ? user.starred_tracks.map(track => ({
      song: String(track.song || "").trim(),
      label: String(track.label || "").trim(),
      starredAt: String(track.starred_at || ""),
    })).filter(track => track.song) : [],
    friends: user.friends && typeof user.friends === "object"
      ? {
          friends: Array.isArray(user.friends.friends) ? [...user.friends.friends] : [],
          incoming: Array.isArray(user.friends.incoming) ? [...user.friends.incoming] : [],
          outgoing: Array.isArray(user.friends.outgoing) ? [...user.friends.outgoing] : [],
        }
      : { friends: [], incoming: [], outgoing: [] },
    beacons: Array.isArray(user.beacons) ? user.beacons.map(beacon => ({
      fromAccountId: String(beacon.from_account_id || ""),
      fromUsername: String(beacon.from_username || ""),
      worldId: String(beacon.world_id || ""),
      worldLabel: String(beacon.world_label || ""),
      roomId: String(beacon.room_id || ""),
      roomLabel: String(beacon.room_label || ""),
      createdAt: String(beacon.created_at || ""),
      crossWorld: Boolean(beacon.cross_world),
    })) : [],
    packs: Array.isArray(user.packs) ? user.packs.map(normalizePack) : [],
    unlockedProps: Array.isArray(user.unlocked_props) ? user.unlocked_props.map(propId => String(propId)) : [],
    tasks: normalizeTasks(user.tasks),
    journal: normalizeJournal(user.journal),
    titles: normalizeTitles(user.titles),
    worldId: String(user.world_id || ""),
    worldCssUrl: assetOrEmpty(user.world_css_url),
    rememberedRoom: String(user.remembered_room || ""),
    canEnterWorld: user.can_enter_world !== false,
  };
}

export function normalizeGameAssets(assets) {
  if (!assets || typeof assets !== "object") return {};
  return Object.fromEntries(Object.entries(assets).map(([name, url]) => [String(name), assetOrEmpty(url)]));
}

export function normalizeGameModels(models) {
  if (!models || typeof models !== "object") return {};
  return Object.fromEntries(Object.entries(models).map(([name, model]) => [String(name), {
    modelUrl: assetOrEmpty(model?.model_url),
    scale: Number(model?.scale || 1),
  }]));
}

export function normalizeRoomGame(game) {
  if (!game || typeof game !== "object") return null;
  return {
    kind: String(game.kind || ""),
    controller: String(game.controller || ""),
    renderer: String(game.renderer || ""),
    config: game.config && typeof game.config === "object" ? clone(game.config) : {},
    assets: normalizeGameAssets(game.assets),
    models: normalizeGameModels(game.models),
    effects: game.effects && typeof game.effects === "object" ? clone(game.effects) : {},
  };
}

export function normalizeGameState(boardState) {
  return boardState && typeof boardState === "object" ? clone(boardState) : null;
}

export function normalizeRoom(room, previousRoom = null) {
  if (!room) return null;
  return {
    id: String(room.id || ""),
    label: String(room.label || "Room"),
    description: String(room.description || ""),
    baseDescription: String(room.description || ""),
    board: {
      type: String(room.board?.type || ""),
      imageUrl: assetOrEmpty(room.board?.image_url),
      imageStyle: String(room.board?.image_style || ""),
      palette: Array.isArray(room.board?.palette) ? [...room.board.palette] : [],
      dark: Boolean(room.board?.dark),
      baseDark: Boolean(room.board?.base_dark ?? room.board?.dark),
      spritesEnabled: Boolean(room.board?.sprites_enabled),
      game: normalizeRoomGame(room.board?.game),
      state: normalizeGameState(room.board?.state),
    },
    note: String(room.metadata?.note || ""),
    environment: room.environment && typeof room.environment === "object" ? { ...room.environment } : {},
    environmentRevision: Number(room.environment_revision || 0),
    exits: Array.isArray(room.exits) ? room.exits.map(normalizeExit) : [],
    props: Array.isArray(room.props) ? room.props.map(normalizeProp) : [],
    occupants: Array.isArray(room.occupants) ? room.occupants.map(normalizeOccupant) : [],
    npcs: Array.isArray(room.npcs) ? room.npcs.map(normalizeNpc) : [],
    roomCards: Array.isArray(room.room_cards) ? room.room_cards.map(normalizeRoomCard) : [],
    chatHistory: normalizeChatHistory(room.chat_history, previousRoom?.chatHistory),
    inventory: Array.isArray(room.inventory) ? room.inventory.map(normalizeInventoryStack) : [],
    editable: Boolean(room.editable),
    canEditRoom: Boolean(room.can_edit_room),
    layoutRevision: Number(room.layout_revision || 0),
    dialog: normalizeDialog(room.dialog),
    quickActions: normalizeQuickActions(room.quick_actions),
  };
}
