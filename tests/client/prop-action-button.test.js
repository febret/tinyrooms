import test from "node:test";
import assert from "node:assert/strict";

import { createPropActionButton } from "../../app/js/prop-action-button.js";

test("default prop action appears beside a click, stays in bounds, and executes once", () => {
  const button = {
    hidden: true, style: {}, offsetWidth: 90, offsetHeight: 30,
    parentElement: { getBoundingClientRect: () => ({ left: 100, top: 50, width: 200, height: 100 }) },
  };
  const prop = { id: "portal", quickActions: [{ label: "Enter", command: ".go exit0", default: true }] };
  const state = {
    room: { id: "hub", board: { dark: false }, props: [prop] },
    selection: { kind: "prop", id: "portal" },
    views: {}, ui: {},
  };
  const executed = [];
  const controller = createPropActionButton({ button, getState: () => state, onAction: action => executed.push(action.command) });
  controller.select(state.selection, { x: 290, y: 145 }, state.room);
  controller.sync(state);
  assert.equal(button.hidden, false);
  assert.equal(button.textContent, "Enter");
  assert.equal(button.style.left, "110px");
  assert.equal(button.style.top, "70px");
  button.onclick();
  assert.deepEqual(executed, [".go exit0"]);
  assert.equal(button.hidden, true);
  button.onclick();
  assert.deepEqual(executed, [".go exit0"]);
  controller.select(state.selection, { x: 110, y: 60 }, state.room);
  state.ui.targeting = { stackId: "card" };
  controller.sync(state);
  assert.equal(button.hidden, true);
});
