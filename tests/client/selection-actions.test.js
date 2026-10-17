import test from "node:test";
import assert from "node:assert/strict";

import { selectionActions } from "../../app/js/cards.js";
import { createStore, isTargetableStack } from "../../app/js/state.js";

function selectedState(stack) {
  return {
    room: { id: "room", inventory: [stack], occupants: [], npcs: [] },
    user: { id: "self" },
    views: { main: null },
    selection: { kind: "inventory-card", id: stack.stackId },
    ui: {},
  };
}

test("self peep hides look, friend-add and pin actions but keeps self shortcuts", () => {
  const state = selectedState({});
  state.selection = { kind: "peep", id: "self" };
  state.room.occupants = [{ id: "self", quickActions: [
    { label: "Look", command: ".look @sunbeam" },
    { label: "Add Friend", command: ".friend add @peep:self" },
    { label: "Unpin", command: ".pin @peep:self" },
  ] }];
  assert.deepEqual(selectionActions(state).map(action => action.label), ["Open Self", "Friends", "Skills", "Swap Sticker…"]);
  state.user.id = "other";
  assert.ok(selectionActions(state).some(action => action.label === "Look"));
});

test("Use requires an active effect on an equipped item or action", () => {
  for (const type of ["item", "action"]) {
    const stack = { stackId: "card", equipped: true, quantity: 1, definition: { type } };
    const labels = () => selectionActions(selectedState(stack)).map(action => action.label);
    assert.ok(!labels().includes("Use"));
    assert.ok(labels().includes("Inspect"));
    assert.ok(labels().includes("Unequip"));
    stack.definition.effect = "energy";
    assert.ok(labels().includes("Use"));
    stack.definition.passive = true;
    assert.ok(!labels().includes("Use"));
    stack.definition.passive = false;
    stack.definition.decorative = true;
    assert.ok(!labels().includes("Use"));
  }
});

test("cancelling targeting keeps the card selected without rearming it or reopening its view", () => {
  const store = createStore();
  store.dispatch({ type: "bootstrap", user: { id: "self", inventory: [
    { stack_id: "card", equipped: true, quantity: 1, definition: { type: "item", target: "prop", label: "Broom" } },
  ] } });
  store.dispatch({ type: "open-view", view: "inventory" });
  store.dispatch({ type: "select", selection: { kind: "inventory-card", id: "card" } });
  assert.equal(store.getState().ui.targeting.stackId, "card");
  store.dispatch({ type: "cancel-targeting" });
  const state = store.getState();
  assert.deepEqual(state.selection, { kind: "inventory-card", id: "card" });
  assert.equal(state.ui.targeting, null);
  assert.equal(state.views.main, null);
  const roomState = { ...state, room: { id: "room", inventory: [] } };
  assert.ok(selectionActions(roomState).some(action => action.label === "Inspect"));
  assert.ok(selectionActions(roomState).some(action => action.label === "Unequip"));
});

test("target confirmation does not restore the cancelled card selection", () => {
  const store = createStore();
  store.dispatch({ type: "bootstrap", user: { id: "self", inventory: [
    { stack_id: "card", equipped: true, definition: { type: "item", target: "prop" } },
  ] } });
  store.dispatch({ type: "select", selection: { kind: "inventory-card", id: "card" } });
  store.dispatch({ type: "cancel-targeting", restoreSelection: false });
  assert.equal(store.getState().ui.targeting, null);
  assert.equal(store.getState().selection.kind, "none");
});

test("targeting allows world-handled prop actions but requires an effect for peeps", () => {
  const stack = { equipped: true, definition: { type: "item", target: "prop" } };
  assert.equal(isTargetableStack(stack), true);
  stack.definition.target = "peep";
  assert.equal(isTargetableStack(stack), false);
  stack.definition.effect = "health";
  assert.equal(isTargetableStack(stack), true);
});
