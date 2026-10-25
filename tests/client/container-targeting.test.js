import test from "node:test";
import assert from "node:assert/strict";

import { selectionActions } from "../../client/app/js/cards.js";
import { buildContainerDropCommand, buildTakeCommand } from "../../client/app/js/commands.js";
import { createDropController } from "../../client/app/js/drop-targeting.js";

const CONTAINER = { id: "cabinet", behavior: "container" };
const ORDINARY = { id: "lamp", behavior: null };

function dropHarness({ drop = null, props = [] } = {}) {
  const state = { ui: { dropTargeting: drop }, room: { id: "room", props } };
  const sent = [];
  const toasts = [];
  const dispatched = [];
  const controller = createDropController({
    getState: () => state,
    store: { dispatch: action => { dispatched.push(action); } },
    sendCommand: command => { sent.push(command); return Promise.resolve(); },
    onToast: message => { toasts.push(message); },
    onError: () => {},
  });
  return { sent, toasts, dispatched, controller };
}

test("dropping on a container prop stores the card inside it", () => {
  const harness = dropHarness({
    drop: { stackId: "card", quantity: 2, label: "Poop" },
    props: [ORDINARY, CONTAINER],
  });
  assert.equal(harness.controller.handle({ kind: "prop", id: "cabinet" }), true);
  assert.deepEqual(harness.sent, [".drop @card:card 2 @prop:cabinet"]);
  assert.deepEqual(harness.dispatched, [{ type: "cancel-drop" }]);
  assert.deepEqual(harness.toasts, []);
});

test("dropping on an ordinary prop keeps floor-drop targeting armed", () => {
  const harness = dropHarness({
    drop: { stackId: "card", quantity: 1, label: "Poop" },
    props: [ORDINARY, CONTAINER],
  });
  assert.equal(harness.controller.handle({ kind: "prop", id: "lamp" }), true);
  assert.deepEqual(harness.sent, []);
  assert.deepEqual(harness.dispatched, []);
  assert.match(harness.toasts.join(" "), /Click a spot in the room/);
});

test("drop targeting ignores peep selections except for the toast", () => {
  const harness = dropHarness({
    drop: { stackId: "card", quantity: 1, label: "Poop" },
    props: [CONTAINER],
  });
  assert.equal(harness.controller.handle({ kind: "peep", id: "pip" }), true);
  assert.deepEqual(harness.sent, []);
});

test("drop targeting stays idle without an armed drop", () => {
  const harness = dropHarness({ props: [CONTAINER] });
  assert.equal(harness.controller.handle({ kind: "prop", id: "cabinet" }), false);
  assert.deepEqual(harness.sent, []);
  assert.deepEqual(harness.toasts, []);
});

test("inventory cards offer Drop, not a separate Put in action", () => {
  const stack = {
    stackId: "card",
    equipped: false,
    quantity: 1,
    quickActions: [{ label: "Drop", command: ".drop @card:card 1" }],
    definition: { type: "item" },
  };
  const state = {
    room: { id: "room", inventory: [stack], props: [CONTAINER], occupants: [], npcs: [] },
    user: { id: "self" },
    views: { main: null },
    selection: { kind: "inventory-card", id: "card" },
    ui: {},
  };
  const labels = selectionActions(state).map(action => action.label);
  assert.ok(!labels.includes("Put in…"));
  assert.ok(labels.includes("Drop"));
});

test("container commands target the container stack", () => {
  assert.equal(buildContainerDropCommand("card", 2, "cabinet"), ".drop @card:card 2 @prop:cabinet");
  assert.equal(buildTakeCommand("cabinet", "container:abc", 1), ".take @prop:cabinet @card:container:abc 1");
  assert.equal(buildTakeCommand("cabinet", "container:abc", 4), ".take @prop:cabinet @card:container:abc 4");
});
