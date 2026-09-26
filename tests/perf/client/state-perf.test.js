import test from "node:test";
import assert from "node:assert/strict";

import { createStore } from "../../../app/js/state.js";
import { makeRoomPayload, makeUserPayload } from "./fixtures.js";
import { assertScales, medianMs, record } from "./perfkit.js";

/** Seed a store with a synthetic room and return it. */
function seeded(overrides = {}) {
  const store = createStore();
  store.dispatch({ type: "session", user: makeUserPayload() });
  store.dispatch({ type: "snapshot", room: makeRoomPayload(overrides) });
  return store;
}

const chatAction = index => ({
  type: "room-event",
  event: {
    type: "chat.message",
    room_id: "hub",
    speaker_id: "user-3",
    speaker: "player3",
    style: "normal",
    text: `hello world ${index ?? ""}`,
  },
});

test("snapshot normalisation is linear in room size", () => {
  const small = medianMs(() => {
    const store = createStore();
    store.dispatch({ type: "session", user: makeUserPayload() });
    store.dispatch({ type: "snapshot", room: makeRoomPayload({ props: 15, npcs: 2, occupants: 2, roomCards: 2, chat: 5, inventory: 2 }) });
  }, { iterations: 12, warmup: 3 });

  const large = medianMs(() => {
    const store = createStore();
    store.dispatch({ type: "session", user: makeUserPayload() });
    store.dispatch({ type: "snapshot", room: makeRoomPayload({ props: 120, npcs: 12, occupants: 20, roomCards: 20, chat: 50, inventory: 12 }) });
  }, { iterations: 12, warmup: 3 });

  record("client/state/snapshot-ms/small", small, { note: "Normalising a small room snapshot." });
  record("client/state/snapshot-ms/large", large, { note: "Normalising a busy room snapshot." });
  assertScales(assert, "state/snapshot", small, large, { factor: 8, maxFactor: 2.4, smallN: 15, largeN: 120 });
});

test("a chat event leaves unrelated entity lists untouched", () => {
  const store = seeded();
  const before = store.getState();

  const elapsed = medianMs(() => {
    store.dispatch(chatAction());
  }, { iterations: 40, warmup: 5 });

  const after = store.getState();
  record("client/state/chat-event-ms", elapsed, {
    note: "Reducing one chat message in a 120-prop, 20-occupant room.",
  });

  // The occupants array must be copied, because the speaking peep gains a
  // bubble. Nothing else in the room has any reason to be rebuilt.
  assert.equal(after.room.props, before.room.props, "a chat message reallocated the prop list");
  assert.equal(after.room.npcs, before.room.npcs, "a chat message reallocated the npc list");
  assert.equal(after.room.roomCards, before.room.roomCards, "a chat message reallocated room cards");
  assert.equal(after.room.inventory, before.room.inventory, "a chat message reallocated inventory");
});

test("a chat message only allocates the one peep that spoke", () => {
  const store = seeded();
  const before = store.getState();
  store.dispatch(chatAction());
  const after = store.getState();

  const changed = after.room.occupants.filter((peep, index) => peep !== before.room.occupants[index]);
  assert.ok(changed.length <= 1, `${changed.length} occupant objects were replaced for one message`);
  const matched = changed.find(peep => peep.id === "user-3");
  assert.ok(matched, "the speaking occupant was not updated");
  assert.match(matched.bubble.text, /hello world/, "the speech bubble was not applied");
});

test("a speech bubble for a silent room costs nothing", () => {
  const store = seeded();
  const before = store.getState();
  // Nobody matches this speaker, so nothing should be allocated at all.
  store.dispatch({
    type: "room-event",
    event: {
      type: "chat.message",
      room_id: "hub",
      speaker_id: "nobody",
      speaker: "ghost",
      style: "normal",
      text: "is anyone here",
    },
  });
  const after = store.getState();
  assert.equal(after.room.occupants, before.room.occupants, "a speech for nobody reallocated occupants");
  assert.equal(after.room.npcs, before.room.npcs, "a speech for nobody reallocated the npc list");
});

test("normalising a snapshot does not mint new chat identities", () => {
  const store = seeded();
  const before = store.getState();

  let minted = 0;
  const original = globalThis.crypto.randomUUID;
  globalThis.crypto.randomUUID = () => {
    minted += 1;
    return original.call(globalThis.crypto);
  };
  try {
    store.dispatch({ type: "snapshot", room: makeRoomPayload() });
  } finally {
    globalThis.crypto.randomUUID = original;
  }

  record("client/state/uuids-per-snapshot", minted, {
    unit: "uuids",
    note: (
      "crypto.randomUUID calls while re-normalising an unchanged 50-line chat history. Each one " +
      "is a fresh identity for a line that did not change, which defeats downstream memoisation."
    ),
  });
  assert.equal(minted, 0, `normalising an unchanged chat log minted ${minted} new identities`);

  // Identity must survive so views can diff against the previous array.
  const after = store.getState();
  assert.equal(after.room.chatHistory, before.room.chatHistory, "an unchanged chat log was replaced");
});

test("chat history stays bounded and keeps its scrollback", () => {
  const store = seeded();
  for (let index = 0; index < 120; index += 1) store.dispatch(chatAction(index));
  const history = store.getState().room.chatHistory;
  assert.ok(history.length <= 50, `chat history grew to ${history.length} entries`);
  assert.match(history.at(-1).text, /hello world 119$/, "the newest message was dropped");
});

test("occupant and npc bubble updates stay linear", () => {
  const store = seeded();
  const elapsed = medianMs(() => {
    store.dispatch(chatAction());
  }, { iterations: 40, warmup: 5 });

  record("client/state/bubble-ms", elapsed, {
    ceiling: 25,
    note: "Applying one speech bubble across a room's occupants and npcs.",
  });
});

test("store dispatch stays cheap as the room fills", () => {
  const timings = {};
  for (const occupants of [4, 32]) {
    const store = seeded({ occupants, props: 40, npcs: 6, roomCards: 8, chat: 20, inventory: 6 });
    timings[occupants] = medianMs(() => {
      store.dispatch({ type: "toggle-log" });
      store.dispatch({ type: "toggle-log" });
    }, { iterations: 40, warmup: 5 });
  }
  record("client/state/toggle-ms/4-occupants", timings[4], { note: "Two UI toggles in a 4-occupant room." });
  record("client/state/toggle-ms/32-occupants", timings[32], { note: "Two UI toggles in a 32-occupant room." });
  assertScales(assert, "state/toggle", timings[4], timings[32], {
    factor: 8,
    maxFactor: 1.6,
    smallN: 4,
    largeN: 32,
  });
});
