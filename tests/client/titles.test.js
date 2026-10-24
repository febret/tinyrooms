import test from "node:test";
import assert from "node:assert/strict";

import { normalizeChatEntry, normalizeOccupant, normalizeTitles, normalizeUser } from "../../client/app/js/normalize.js";
import { createStore } from "../../client/app/js/state.js";
import { selfPagesMarkup } from "../../client/app/js/views/self-view.js";

test("occupants prefer the composed title label but keep the bare username", () => {
  const occupant = normalizeOccupant({ id: "a1", username: "Ada", label: 'Captain Ada "Tourfriend", Adept', kind: "user" });
  assert.equal(occupant.label, 'Captain Ada "Tourfriend", Adept');
  assert.equal(occupant.username, "Ada");
});

test("occupants fall back to the username without a title label", () => {
  const occupant = normalizeOccupant({ id: "a1", username: "Ada", kind: "user" });
  assert.equal(occupant.label, "Ada");
  assert.equal(occupant.username, "Ada");
});

test("chat entries prefer the speaker title label", () => {
  const entry = normalizeChatEntry({ speaker_id: "a1", speaker: "Ada", speaker_label: "Chef Ada", text: "hi" });
  assert.equal(entry.speaker, "Chef Ada");
});

test("user normalization carries titles with camelCase selection", () => {
  const user = normalizeUser({
    id: "self",
    username: "Ada",
    titles: {
      catalog: [{ id: "chef", label: "Chef", slot: "salutation", unlock: { kind: "cook", count: 10 } }],
      unlocked: ["chef"],
      selection: { salutation: "chef", nickname: null, suffix: null, crew_name: "Starling", display_label: "Chef Ada Starling" },
      cooked_count: 10,
      taught_count: 3,
    },
  });
  assert.deepEqual(user.titles.selection, {
    salutation: "chef",
    nickname: null,
    suffix: null,
    crewName: "Starling",
    displayLabel: "Chef Ada Starling",
  });
  assert.equal(user.titles.cookedCount, 10);
  assert.equal(user.titles.taughtCount, 3);
});

test("presence.title updates the occupant label live", () => {
  const store = createStore();
  store.dispatch({
    type: "bootstrap",
    user: { id: "self", username: "Me", inventory: [] },
  });
  store.dispatch({
    type: "snapshot",
    room: { id: "hub", occupants: [{ id: "a1", username: "Ada", kind: "user" }], npcs: [] },
  });
  store.dispatch({
    type: "room-event",
    event: { type: "presence.title", account_id: "a1", username: "Ada", label: "Chef Ada" },
  });
  const occupant = store.getState().room.occupants.find(entry => entry.id === "a1");
  assert.equal(occupant.label, "Chef Ada");
  assert.equal(occupant.username, "Ada");
});

test("self view shows a title nameplate below the level line", () => {
  const pages = selfPagesMarkup({
    ui: { titlesOpen: false },
    user: {
      username: "Ada",
      level: 3,
      levelLabel: "Apprentice",
      kudos: 0,
      titles: normalizeTitles({
        catalog: [
          { id: "captain", label: "Captain", slot: "salutation", unlock: { kind: "level", level: 3 } },
          { id: "chef", label: "Chef", slot: "salutation", unlock: { kind: "cook", count: 10 } },
        ],
        unlocked: ["captain"],
        selection: { salutation: "captain", nickname: null, suffix: null, crew_name: "", display_label: "Captain Ada" },
        cooked_count: 4,
        taught_count: 0,
      }),
    },
  });
  assert.match(pages.left, /journal-name">Ada</);
  assert.match(pages.left, /data-titles-toggle/);
  assert.match(pages.left, /Captain Ada/);
  assert.match(pages.left, /aria-expanded="false"/);
  assert.match(pages.left, /id="title-editor" hidden/);
});

test("self view opens the title editor with slots and locked hints", () => {
  const pages = selfPagesMarkup({
    ui: { titlesOpen: true },
    user: {
      username: "Ada",
      level: 3,
      levelLabel: "Apprentice",
      kudos: 0,
      titles: normalizeTitles({
        catalog: [
          { id: "captain", label: "Captain", slot: "salutation", unlock: { kind: "level", level: 3 } },
          { id: "chef", label: "Chef", slot: "salutation", unlock: { kind: "cook", count: 10 } },
        ],
        unlocked: ["captain"],
        selection: { salutation: "captain", nickname: null, suffix: null, crew_name: "", display_label: "Captain Ada" },
        cooked_count: 4,
        taught_count: 0,
      }),
    },
  });
  assert.match(pages.left, /aria-expanded="true"/);
  assert.match(pages.left, /data-title-slot="salutation"/);
  assert.match(pages.left, /data-title-slot="nickname"/);
  assert.match(pages.left, /data-title-slot="suffix"/);
  assert.match(pages.left, /data-title-crew-input/);
  assert.match(pages.left, /<option value="captain" selected>Captain<\/option>/);
  assert.doesNotMatch(pages.left, /Chef/);
});

test("title editor toggle flips the ui flag", () => {
  const store = createStore();
  assert.equal(store.getState().ui.titlesOpen, false);
  store.dispatch({ type: "toggle-titles" });
  assert.equal(store.getState().ui.titlesOpen, true);
  store.dispatch({ type: "toggle-titles" });
  assert.equal(store.getState().ui.titlesOpen, false);
});
