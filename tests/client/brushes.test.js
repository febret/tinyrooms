import test from "node:test";
import assert from "node:assert/strict";

import {
  BRUSHES,
  dabSpacing,
  interpolatePoints,
  pressureForEvent,
} from "../../client/activities/whiteboard/brushes.js";

test("whiteboard offers a broad brush set with distinct painting behaviors", () => {
  assert.ok(BRUSHES.length >= 11);
  const kinds = new Set(BRUSHES.map(brush => brush.kind));
  assert.ok(kinds.has("round"));
  assert.ok(kinds.has("wash"));
  assert.ok(kinds.has("spray"));
  assert.ok(kinds.has("highlight"));
});

test("brush pressure prefers stylus input and falls back to pointer speed", () => {
  assert.equal(pressureForEvent({ pointerType: "pen", pressure: 0.2 }, 0), 0.2);
  assert.ok(pressureForEvent({ pointerType: "mouse" }, 100) > pressureForEvent({ pointerType: "mouse" }, 2400));
});

test("stroke interpolation and dab spacing stay smooth", () => {
  assert.ok(dabSpacing(10, 0.2) >= 1);
  const dabs = interpolatePoints([0, 0], [10, 0], 4);
  assert.ok(dabs.length >= 2);
  assert.deepEqual(dabs.at(-1).slice(0, 2), [10, 0]);
});
