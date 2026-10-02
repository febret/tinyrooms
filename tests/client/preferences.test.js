import test from "node:test";
import assert from "node:assert/strict";

import { createStore } from "../../app/js/state.js";

test("active prop outlines default off and persist when toggled", () => {
  const previous = globalThis.localStorage;
  const values = new Map();
  globalThis.localStorage = {
    getItem: key => values.get(key) ?? null,
    setItem: (key, value) => values.set(key, value),
  };
  try {
    const store = createStore();
    assert.equal(store.getState().ui.outlineActiveProps, false);
    store.dispatch({ type: "toggle-outline-active-props" });
    assert.equal(store.getState().ui.outlineActiveProps, true);
    assert.equal(createStore().getState().ui.outlineActiveProps, true);
    store.dispatch({ type: "toggle-outline-active-props" });
    assert.equal(createStore().getState().ui.outlineActiveProps, false);
  } finally {
    if (previous === undefined) delete globalThis.localStorage;
    else globalThis.localStorage = previous;
  }
});
