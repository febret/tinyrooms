import test from "node:test";
import assert from "node:assert/strict";

import { footprintsOverlap, supportElevation } from "../../app/js/editing/prop-stacking.js";

const dragged = { id: "dragged", x: 0, z: 0, halfX: 1, halfZ: 1, topZ: 0 };

test("footprintsOverlap is true for intersecting and edge-touching footprints", () => {
  assert.equal(footprintsOverlap(dragged, { x: 0, z: 0, halfX: 1, halfZ: 1 }), true);
  assert.equal(footprintsOverlap(dragged, { x: 2, z: 0, halfX: 1, halfZ: 1 }), true);
  assert.equal(footprintsOverlap(dragged, { x: 2.01, z: 0, halfX: 1, halfZ: 1 }), false);
  assert.equal(footprintsOverlap(dragged, { x: 0, z: 2.01, halfX: 1, halfZ: 1 }), false);
});

test("supportElevation is zero when nothing intersects", () => {
  assert.equal(supportElevation(dragged, []), 0);
  assert.equal(supportElevation(dragged, [{ id: "far", x: 10, z: 10, halfX: 1, halfZ: 1, topZ: 4 }]), 0);
  assert.equal(supportElevation(dragged, undefined), 0);
});

test("supportElevation rests on the top of a single intersecting prop", () => {
  const support = { id: "support", x: 0.5, z: 0.5, halfX: 1, halfZ: 1, topZ: 6 };
  assert.equal(supportElevation(dragged, [support]), 6);
});

test("supportElevation uses the highest top among overlapping props", () => {
  const low = { id: "low", x: 0, z: 0, halfX: 1, halfZ: 1, topZ: 3 };
  const high = { id: "high", x: 1, z: 0, halfX: 1, halfZ: 1, topZ: 8 };
  assert.equal(supportElevation(dragged, [low, high]), 8);
  assert.equal(supportElevation(dragged, [high, low]), 8);
});

test("supportElevation ignores the dragged prop itself", () => {
  const self = { id: "dragged", x: 0, z: 0, halfX: 1, halfZ: 1, topZ: 20 };
  assert.equal(supportElevation(dragged, [self]), 0);
});
