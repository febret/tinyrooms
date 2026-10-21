import test from "node:test";
import assert from "node:assert/strict";

import {
  defaultInventorySelection,
  previewStack,
  stacksForTab,
  tabForDefinition,
} from "../../client/app/js/inventory-state.js";

function stack(stackId, type) {
  return { stackId, quantity: 1, definition: { id: stackId, label: stackId, type }, quickActions: [] };
}

function stateWith(inventory, selection = { kind: "core", id: "inventory" }) {
  return {
    room: { id: "room", inventory, roomCards: [stack("room-card", "item")], occupants: [], npcs: [] },
    user: { inventory: [] },
    selection,
    ui: { inventoryTab: "Items" },
  };
}

test("tab helpers classify cards", () => {
  assert.equal(tabForDefinition({ type: "emote" }), "Emotes");
  assert.equal(tabForDefinition({ type: "skill" }), "Skills");
  assert.equal(tabForDefinition({ type: "pack" }), "Items");
  assert.equal(stacksForTab(stateWith([stack("item", "item"), stack("emote", "emote")]), "Emotes").length, 1);
});

test("opening inventory selects a card from a populated tab", () => {
  const populated = defaultInventorySelection(stateWith([stack("emote", "emote")]), "Items");
  assert.equal(populated.tab, "Emotes");
  assert.deepEqual(populated.selection, { kind: "inventory-card", id: "emote" });

  const fallback = defaultInventorySelection(stateWith([stack("item", "item")]), "Skills");
  assert.equal(fallback.tab, "Items");
  assert.deepEqual(fallback.selection, { kind: "inventory-card", id: "item" });
  assert.equal(previewStack(stateWith([stack("item", "item")]), "Skills"), null);
});

test("preview resolves room cards selected from the board", () => {
  const state = stateWith([stack("item", "item")], { kind: "room-card", id: "room-card" });
  assert.equal(previewStack(state, "Items").kind, "room-card");
  assert.equal(previewStack(state, "Items").stack.stackId, "room-card");
});
