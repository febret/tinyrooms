import test from "node:test";
import assert from "node:assert/strict";

import { statusButtonMarkup, statusSnapshot } from "../../client/app/js/status-button.js";

function stateWith({ counters, statuses, journal = false } = {}) {
  return {
    loggedIn: true,
    user: {
      id: "self",
      counters: counters || { energy: 5, maxEnergy: 10, health: 8, maxHealth: 10, cleanliness: 2, maxCleanliness: 10 },
      statuses: statuses || [],
      statusDefinitions: {
        stinky: { label: "Stinky", icon: "🐷" },
        tired: { label: "Tired", icon: "😪" },
      },
    },
    room: { occupants: [] },
    views: { main: journal ? "id" : null },
    ui: { idCardSide: journal ? "self" : "skills", reducedMotion: false },
  };
}

test("visitors see nothing when logged out", () => {
  assert.equal(statusButtonMarkup({ loggedIn: false }), "");
});

test("the status button meters energy, health, and cleanliness", () => {
  const markup = statusButtonMarkup(stateWith());
  assert.ok(markup.includes('data-status-toggle="1"'));
  assert.ok(markup.includes("status-pill energy"));
  assert.ok(markup.includes("status-pill health"));
  assert.ok(markup.includes("status-pill cleanliness"));
  assert.ok(markup.includes("--fill:50.0%"));
  assert.ok(markup.includes("Wellbeing: Energy 5/10 · Health 8/10 · Cleanliness 2/10"));
});

test("active statuses are exposed for the cycling badge", () => {
  const state = stateWith({ statuses: ["stinky", "tired"] });
  const snapshot = statusSnapshot(state);
  assert.deepEqual(snapshot.statuses, ["stinky", "tired"]);
  const markup = statusButtonMarkup(state);
  assert.ok(markup.includes('data-status="stinky"'));
  assert.ok(markup.includes("🐷"));
  assert.ok(markup.includes("Active statuses: Stinky, Tired"));
});

test("the button is pressed on the identity card view", () => {
  assert.ok(statusButtonMarkup(stateWith({ journal: true })).includes('aria-pressed="true"'));
});
