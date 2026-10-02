import test from "node:test";
import assert from "node:assert/strict";

import { activePropAction, defaultPropAction, hasActivePropActions } from "../../app/js/prop-actions.js";

test("active props require a usable action other than look or inspect", () => {
  assert.equal(hasActivePropActions({ quickActions: [{ command: ".look @prop:door" }, { command: ".inspect @prop:door" }] }), false);
  assert.equal(hasActivePropActions({ quickActions: [{ command: ".go exit0" }] }), true);
  assert.equal(activePropAction({ command: ".go exit0", disabled: true }), false);
  assert.equal(hasActivePropActions({ quickActions: [] }), false);
});

test("the nearby action uses only an available authored default", () => {
  const prop = { quickActions: [
    { label: "Enter", command: ".go exit1", default: true, disabled: true },
    { label: "Enter", command: ".go exit0", default: true },
  ] };
  assert.equal(defaultPropAction(prop)?.label, "Enter");
  assert.equal(defaultPropAction(prop)?.command, ".go exit0");
  assert.equal(defaultPropAction({ quickActions: [{ label: "Inspect", command: ".inspect @prop:door", default: true }] })?.label, "Inspect");
  assert.equal(defaultPropAction({ quickActions: [{ label: "Enter", command: ".go exit0" }] }), null);
});
