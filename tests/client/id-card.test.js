import test from "node:test";
import assert from "node:assert/strict";

import { createStore } from "../../client/app/js/state.js";
import { idCardView } from "../../client/app/js/views/id-card-view.js";
import { inventoryView } from "../../client/app/js/views/inventory-view.js";
import { journalView } from "../../client/app/js/views/journal-view.js";
import { phoneView } from "../../client/app/js/views/phone-view.js";

function baseState(overrides = {}) {
  return {
    user: {
      id: "self",
      username: "Ada",
      level: 3,
      levelLabel: "Explorer",
      kudos: 5,
      kudosToNext: 10,
      bops: 42,
      counters: { health: 8, maxHealth: 10, energy: 5, maxEnergy: 10, cleanliness: 2, maxCleanliness: 10 },
      statuses: [],
      statusDefinitions: {},
      stats: { constitution: 1 },
      skills: [],
      titles: { catalog: [], unlocked: [], selection: {} },
    },
    room: { inventory: [] },
    views: { main: null, skillStackId: null, skillPickerSlot: null },
    selection: { kind: "core", id: "journal" },
    ui: {
      journalTab: "Tasks",
      inventoryTab: "Items",
      idCardSide: "self",
      inventoryCompact: false,
      sellMode: false,
      titlesOpen: false,
    },
    ...overrides,
  };
}

test("open-view self and skills land on the identity card with the matching side", () => {
  const store = createStore();
  store.dispatch({ type: "bootstrap", user: { id: "self", username: "Ada", inventory: [] } });
  store.dispatch({
    type: "snapshot",
    room: { id: "hub", occupants: [], npcs: [], inventory: [], roomCards: [], props: [] },
  });
  store.dispatch({ type: "open-view", view: "self" });
  assert.equal(store.getState().views.main, "id");
  assert.equal(store.getState().ui.idCardSide, "self");
  store.dispatch({ type: "open-view", view: "skills", stackId: "s1" });
  assert.equal(store.getState().views.main, "id");
  assert.equal(store.getState().ui.idCardSide, "skills");
  assert.equal(store.getState().views.skillStackId, "s1");
});

test("id-flip toggles between the identity and skills sides", () => {
  const store = createStore();
  store.dispatch({ type: "bootstrap", user: { id: "self", username: "Ada", inventory: [] } });
  store.dispatch({ type: "id-flip" });
  assert.equal(store.getState().ui.idCardSide, "skills");
  store.dispatch({ type: "id-flip" });
  assert.equal(store.getState().ui.idCardSide, "self");
});

test("journal keeps two tabs and puts close next to them", () => {
  const markup = journalView(baseState());
  assert.equal((markup.match(/data-journal-tab/g) || []).length, 2);
  assert.ok(!markup.includes('data-journal-tab="Self"'));
  assert.ok(!markup.includes('data-journal-tab="Skills"'));
  assert.ok(markup.includes("journal-tabs-row"));
  assert.ok(markup.includes("journal-close"));
});

test("inventory renders its close button inline with the action row", () => {
  const markup = inventoryView(baseState());
  assert.ok(markup.includes("inventory-close"));
  assert.equal((markup.match(/data-close-view/g) || []).length, 1);
});

test("identity photo prefers live self-peep art over the profile sticker", () => {
  const withOccupant = baseState({
    room: {
      inventory: [],
      occupants: [{ id: "self", stickerUrl: "/assets/stickers/live.png" }],
    },
  });
  const markup = idCardView(withOccupant);
  assert.ok(markup.includes('src="/assets/stickers/live.png"'));
  assert.ok(markup.includes('data-id-photo="1"'));
  assert.ok(!markup.includes("id-photo-placeholder"));
});

test("identity photo falls back to the placeholder without any art", () => {
  const markup = idCardView(baseState());
  assert.ok(markup.includes("id-photo-placeholder"));
  assert.ok(!markup.includes("data-id-photo"));
});

test("skills face groups ranks without an internal scroll container", () => {
  const ui = { ...baseState().ui, idCardSide: "skills" };
  const back = idCardView(baseState({
    ui,
    user: {
      ...baseState().user,
      skills: [
        { index: 0, rank: "Script Kiddo", unlocked: true, stackId: "" },
        { index: 5, rank: "Hacker", unlocked: false, stackId: "" },
      ],
    },
  }));
  assert.ok(back.includes("id-skills-grid"));
});

test("phone media controls live on the base and close lives on the keypad", () => {
  const markup = phoneView(baseState());
  assert.ok(markup.includes('class="phone-hardkey phone-media phone-media-toggle"'));
  assert.ok(markup.includes('data-phone-key="close"'));
  assert.ok(!markup.includes("phone-view-close"));
});

test("identity card renders both faces and the flip control", () => {
  const front = idCardView(baseState());
  assert.ok(front.includes('data-id-flip="1"'));
  assert.ok(front.includes("Flip to Skills"));
  assert.ok(front.includes("id-front"));
  assert.ok(front.includes("id-back"));
  assert.ok(front.includes("TINYROOMS • RESIDENT ID"));
  const back = idCardView(baseState({ ui: { ...baseState().ui, idCardSide: "skills" } }));
  assert.ok(back.includes("flipped"));
  assert.ok(back.includes("Flip to ID"));
});
