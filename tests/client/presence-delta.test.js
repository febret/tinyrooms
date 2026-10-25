import test from "node:test";
import assert from "node:assert/strict";

import { createStore } from "../../client/app/js/state.js";

function seededRoom(overrides = {}) {
  return {
    id: "hub",
    label: "Hub",
    description: "A room",
    board: { type: "standard", image_url: "", image_style: "", palette: [], dark: false, game: null, state: null },
    metadata: {},
    environment: {},
    environment_revision: 3,
    exits: [{ id: "exit0", label: "Out", target_room_id: "hall" }],
    props: [{ id: "prop-1", prop_id: "chair", label: "Chair" }],
    occupants: [{ id: "a1", username: "Ada", kind: "user" }],
    npcs: [{ id: "peep-1", label: "Molly", kind: "npc" }],
    room_cards: [],
    chat_history: [],
    inventory: [],
    editable: false,
    can_edit_room: false,
    layout_revision: 5,
    dialog: null,
    quick_actions: [],
    ...overrides,
  };
}

function seededStore() {
  const store = createStore();
  store.dispatch({ type: "session", user: { id: "self", username: "Me", inventory: [] } });
  store.dispatch({ type: "snapshot", room: seededRoom() });
  return store;
}

test("presence.enter inserts the occupant from the event payload", () => {
  const store = seededStore();
  store.dispatch({
    type: "room-event",
    event: {
      type: "presence.enter",
      room_id: "hub",
      account_id: "a2",
      username: "Bo",
      label: "Bo",
      occupant: { id: "a2", username: "Bo", label: "Bo", kind: "user" },
    },
  });
  const occupants = store.getState().room.occupants;
  assert.ok(occupants.some(entry => entry.id === "a2"), "joiner was not added");
  assert.equal(occupants.length, 2);
});

test("presence.enter without a payload still adds a minimal occupant", () => {
  const store = seededStore();
  store.dispatch({
    type: "room-event",
    event: { type: "presence.enter", room_id: "hub", account_id: "a3", username: "Cy" },
  });
  const added = store.getState().room.occupants.find(entry => entry.id === "a3");
  assert.ok(added, "joiner was not added");
  assert.equal(added.username, "Cy");
});

test("presence.enter is idempotent for duplicate events", () => {
  const store = seededStore();
  const event = {
    type: "presence.enter",
    room_id: "hub",
    account_id: "a2",
    username: "Bo",
    occupant: { id: "a2", username: "Bo", kind: "user" },
  };
  store.dispatch({ type: "room-event", event });
  store.dispatch({ type: "room-event", event });
  assert.equal(store.getState().room.occupants.filter(entry => entry.id === "a2").length, 1);
});

test("presence.leave removes the occupant without a snapshot", () => {
  const store = seededStore();
  store.dispatch({
    type: "room-event",
    event: { type: "presence.leave", room_id: "hub", account_id: "a1", username: "Ada" },
  });
  assert.equal(store.getState().room.occupants.length, 0);
});

test("peep.enter and peep.leave patch the npc list", () => {
  const store = seededStore();
  store.dispatch({
    type: "room-event",
    event: {
      type: "peep.enter",
      room_id: "hub",
      peep_id: "peep-2",
      label: "Pip",
      source_room_id: "hall",
      npc: { id: "peep-2", label: "Pip", kind: "npc" },
    },
  });
  assert.ok(store.getState().room.npcs.some(entry => entry.id === "peep-2"));
  store.dispatch({
    type: "room-event",
    event: { type: "peep.leave", room_id: "hub", peep_id: "peep-1", label: "Molly", destination_room_id: "hall" },
  });
  assert.ok(!store.getState().room.npcs.some(entry => entry.id === "peep-1"));
});

test("a revision-gated snapshot keeps cached props and exits", () => {
  const store = seededStore();
  const before = store.getState().room;
  store.dispatch({
    type: "snapshot",
    room: {
      id: "hub",
      occupants: [{ id: "a1", username: "Ada", kind: "user" }, { id: "a2", username: "Bo", kind: "user" }],
      npcs: [],
      room_cards: [],
      chat_history: [],
      inventory: [],
      board: before.board,
      environment: {},
      environment_revision: 3,
      layout_revision: 5,
      props_unchanged: true,
      exits_unchanged: true,
    },
  });
  const after = store.getState().room;
  assert.equal(after.props, before.props, "cached props were replaced");
  assert.equal(after.exits, before.exits, "cached exits were replaced");
  assert.equal(after.occupants.length, 2, "fresh occupants were not applied");
});
