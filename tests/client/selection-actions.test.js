import test from "node:test";
import assert from "node:assert/strict";

import { describeSelection, selectionActions } from "../../client/app/js/cards.js";
import { createStore, isTargetableStack } from "../../client/app/js/state.js";

function selectedState(stack) {
  return {
    room: { id: "room", inventory: [stack], occupants: [], npcs: [] },
    user: { id: "self" },
    views: { main: null },
    selection: { kind: "inventory-card", id: stack.stackId },
    ui: {},
  };
}

test("self peep hides friend-add and pin actions, and every peep hides look", () => {
  const state = selectedState({});
  state.selection = { kind: "peep", id: "self" };
  state.room.occupants = [{ id: "self", quickActions: [
    { label: "Look", command: ".look @sunbeam" },
    { label: "Add Friend", command: ".friend add @peep:self" },
    { label: "Unpin", command: ".pin @peep:self" },
  ] }];
  assert.deepEqual(selectionActions(state).map(action => action.label), ["Swap Sticker…"]);
  state.user.id = "other";
  state.selection = { kind: "peep", id: "self" };
  state.room.occupants = [{ id: "self", quickActions: [
    { label: "Look", command: ".look @sunbeam" },
    { label: "Chat", command: ".talk caretaker" },
  ] }];
  const labels = selectionActions(state).map(action => action.label);
  assert.ok(!labels.includes("Look"));
  assert.ok(labels.includes("Chat"));
});



test("Use is available without equipping and still requires an active effect", () => {
  for (const type of ["item", "action"]) {
    const stack = { stackId: "card", equipped: false, quantity: 1, definition: { type } };
    const labels = () => selectionActions(selectedState(stack)).map(action => action.label);
    assert.ok(!labels().includes("Use"));
    assert.ok(!labels().includes("Inspect"));
    assert.ok(labels().includes("Equip"));
    stack.definition.effect = "energy";
    assert.ok(labels().includes("Use"));
    assert.ok(labels().includes("Equip"));
    stack.equipped = true;
    assert.ok(labels().includes("Use"));
    assert.ok(labels().includes("Unequip"));
    stack.definition.passive = true;
    assert.ok(!labels().includes("Use"));
    stack.definition.passive = false;
    stack.definition.decorative = true;
    assert.ok(!labels().includes("Use"));
  }
});

test("targetable cards can be used from inventory without equipping", () => {
  const stack = { stackId: "card", equipped: false, quantity: 1, definition: { type: "item", target: "prop" } };
  const use = selectionActions(selectedState(stack)).find(action => action.label === "Use");
  assert.deepEqual(use?.local, { type: "start-targeting", stackId: "card" });
});

test("cancelling targeting keeps the card selected without rearming it or reopening its view", () => {
  const store = createStore();
  store.dispatch({ type: "bootstrap", user: { id: "self", inventory: [
    { stack_id: "card", equipped: true, quantity: 1, definition: { type: "item", target: "prop", label: "Broom" } },
  ] } });
  store.dispatch({ type: "open-view", view: "inventory" });
  store.dispatch({ type: "select", selection: { kind: "inventory-card", id: "card" } });
  assert.equal(store.getState().ui.targeting, null);
  assert.equal(store.getState().views.main, "inventory");
  const use = selectionActions({ ...store.getState(), room: { id: "room", inventory: store.getState().room?.inventory || [] } })
    .find(action => action.label === "Use");
  assert.deepEqual(use?.local, { type: "start-targeting", stackId: "card" });
  store.dispatch({ type: "start-targeting", stackId: "card" });
  assert.equal(store.getState().ui.targeting.stackId, "card");
  store.dispatch({ type: "cancel-targeting" });
  const state = store.getState();
  assert.deepEqual(state.selection, { kind: "inventory-card", id: "card" });
  assert.equal(state.ui.targeting, null);
  assert.equal(state.views.main, null);
  const roomState = { ...state, room: { id: "room", inventory: [] } };
  assert.ok(!selectionActions(roomState).some(action => action.label === "Inspect"));
  assert.ok(selectionActions(roomState).some(action => action.label === "Unequip"));
});

test("target confirmation does not restore the cancelled card selection", () => {
  const store = createStore();
  store.dispatch({ type: "bootstrap", user: { id: "self", inventory: [
    { stack_id: "card", equipped: true, definition: { type: "item", target: "prop" } },
  ] } });
  store.dispatch({ type: "select", selection: { kind: "inventory-card", id: "card" } });
  store.dispatch({ type: "start-targeting", stackId: "card" });
  store.dispatch({ type: "cancel-targeting", restoreSelection: false });
  assert.equal(store.getState().ui.targeting, null);
  assert.equal(store.getState().selection.kind, "none");
});

test("targeting allows world-handled prop actions but requires an effect for peeps", () => {
  const stack = { equipped: false, definition: { type: "item", target: "prop" } };
  assert.equal(isTargetableStack(stack), true);
  stack.definition.target = "peep";
  assert.equal(isTargetableStack(stack), false);
  stack.definition.effect = "health";
  assert.equal(isTargetableStack(stack), true);
});

test("peep descriptions include reciprocal vibes", () => {
  const state = {
    room: {
      id: "room",
      inventory: [],
      occupants: [],
      npcs: [{
        id: "npc",
        kind: "npc",
        label: "Caretaker",
        description: "Keeps the place tidy.",
        vibes: {
          toward: { value: 12, label: "Friend 🙂" },
          from: { value: -4, label: "Annoyance 🙄" },
        },
      }],
    },
    user: { id: "self" },
    views: { main: null },
    selection: { kind: "peep", id: "npc" },
    ui: {},
  };
  const description = describeSelection(state);
  assert.match(description.description, /You: Friend/);
  assert.match(description.description, /Them: Annoyance/);
});
