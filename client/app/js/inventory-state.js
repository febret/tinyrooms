/**
 * Pure inventory selection helpers. They live outside state.js so reducers,
 * views, and Node tests can share one definition of the current tab/card.
 */

export const INVENTORY_TABS = ["Items", "Emotes", "Skills"];

export const TAB_PREDICATES = {
  Items: stack => stack.definition?.type !== "emote" && stack.definition?.type !== "skill" && stack.definition?.type !== "pack",
  Emotes: stack => stack.definition?.type === "emote",
  Skills: stack => stack.definition?.type === "skill",
};

export function tabForDefinition(definition) {
  if (definition?.type === "emote") return "Emotes";
  if (definition?.type === "skill") return "Skills";
  return "Items";
}

export function roomInventory(state) {
  return Array.isArray(state?.room?.inventory) ? state.room.inventory : [];
}

export function findInventoryStack(state, stackId) {
  return roomInventory(state).find(stack => stack.stackId === stackId)
    || state?.user?.inventory?.find(stack => stack.stackId === stackId)
    || null;
}

export function findRoomStack(state, stackId) {
  return state?.room?.roomCards?.find(stack => stack.stackId === stackId) || null;
}

export function stacksForTab(state, tab) {
  const predicate = TAB_PREDICATES[tab] || TAB_PREDICATES.Items;
  return roomInventory(state).filter(predicate);
}

export function firstPopulatedTab(state) {
  return INVENTORY_TABS.find(tab => stacksForTab(state, tab).length > 0) || INVENTORY_TABS[0];
}

export function selectionForInventoryStack(stack) {
  return stack ? { kind: "inventory-card", id: stack.stackId } : { kind: "core", id: "inventory" };
}

/** Opening the inventory lands on a tab and card that actually exist. */
export function defaultInventorySelection(state, tab = "Items") {
  const stacks = stacksForTab(state, tab);
  if (stacks.length) {
    return { tab, selection: selectionForInventoryStack(stacks[0]) };
  }
  const fallbackTab = firstPopulatedTab(state);
  const fallbackStacks = stacksForTab(state, fallbackTab);
  return {
    tab: fallbackStacks.length ? fallbackTab : tab,
    selection: selectionForInventoryStack(fallbackStacks[0]),
  };
}

/** Keep a valid inventory card selected when opening the view. */
export function openInventoryState(state) {
  const current = state.selection.kind === "inventory-card" ? findInventoryStack(state, state.selection.id) : null;
  if (current) {
    return {
      tab: tabForDefinition(current.definition),
      selection: { kind: "inventory-card", id: current.stackId },
    };
  }
  return defaultInventorySelection(state, state.ui.inventoryTab);
}

/** Keep the current card when it belongs to the new tab, else choose the first. */
export function inventoryTabState(state, tab) {
  const stacks = stacksForTab(state, tab);
  const current = state.selection.kind === "inventory-card" ? findInventoryStack(state, state.selection.id) : null;
  const keep = current && stacks.some(stack => stack.stackId === current.stackId);
  return {
    tab,
    selection: keep ? state.selection
      : stacks[0] ? { kind: "inventory-card", id: stacks[0].stackId }
        : { kind: "core", id: "inventory" },
  };
}

/** Inspect a card from anywhere by opening the inventory with it selected. */
export function inspectCardState(state, stackId) {
  const roomStack = findRoomStack(state, stackId);
  const inventoryStack = roomStack ? null : findInventoryStack(state, stackId);
  const stack = roomStack || inventoryStack;
  if (!stack) return null;
  const kind = roomStack ? "room-card" : "inventory-card";
  return {
    tab: kind === "inventory-card" ? tabForDefinition(stack.definition) : state.ui.inventoryTab,
    selection: { kind, id: stack.stackId },
  };
}

/** Reconcile stale selections after room snapshots and command results. */
export function dismissInvalidSelection(state, isEligible) {
  if (!state.room) return state;
  if (!isEligible(state, state.selection)) {
    if (state.views.main === "inventory" && ["room-card", "inventory-card"].includes(state.selection.kind)) {
      const next = defaultInventorySelection(state, state.ui.inventoryTab);
      state = { ...state, selection: next.selection, ui: { ...state.ui, inventoryTab: next.tab } };
    } else {
      state = {
        ...state,
        selection: { kind: "room", id: state.room.id },
        views: { ...state.views, main: state.views.main === "prop-details" ? null : state.views.main, propId: null },
      };
    }
  }
  if (state.views.main === "prop-details" && !isEligible(state, { kind: "prop", id: state.views.propId })) {
    state = { ...state, views: { ...state.views, main: null, propId: null } };
  }
  if (state.ui.targeting && !findInventoryStack(state, state.ui.targeting.stackId)) {
    state = { ...state, ui: { ...state.ui, targeting: null } };
  }
  if (state.ui.dropTargeting && !findInventoryStack(state, state.ui.dropTargeting.stackId)) {
    state = { ...state, ui: { ...state.ui, dropTargeting: null } };
  }
  if (state.selection.kind === "inventory-card" && !findInventoryStack(state, state.selection.id)) {
    if (state.views.main === "inventory") {
      const next = defaultInventorySelection(state, state.ui.inventoryTab);
      return { ...state, selection: next.selection, ui: { ...state.ui, inventoryTab: next.tab } };
    }
    return { ...state, selection: { kind: "room", id: state.room.id } };
  }
  if (state.selection.kind === "peep" && ![...state.room.occupants, ...state.room.npcs].some(peep => peep.id === state.selection.id)) {
    return { ...state, selection: { kind: "room", id: state.room.id } };
  }
  return state;
}

/** Resolve the card the inventory preview should show right now. */
export function previewStack(state, tab) {
  const selection = state?.selection || {};
  if (selection.kind === "room-card") {
    const stack = findRoomStack(state, selection.id);
    if (stack) return { kind: "room-card", stack };
  }
  if (selection.kind === "inventory-card") {
    const stack = findInventoryStack(state, selection.id);
    if (stack) return { kind: "inventory-card", stack };
  }
  const stacks = stacksForTab(state, tab);
  return stacks.length ? { kind: "inventory-card", stack: stacks[0] } : null;
}
