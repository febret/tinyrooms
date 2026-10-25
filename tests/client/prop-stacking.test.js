import test from "node:test";
import assert from "node:assert/strict";

import { cardDropElevation, footprintsOverlap, supportElevation } from "../../client/app/js/editing/prop-stacking.js";

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
});

test("supportElevation rests on the highest top among overlapping props", () => {
  const support = { id: "support", x: 0.5, z: 0.5, halfX: 1, halfZ: 1, topZ: 6 };
  assert.equal(supportElevation(dragged, [support]), 6);
  const low = { id: "low", x: 0, z: 0, halfX: 1, halfZ: 1, topZ: 3 };
  const high = { id: "high", x: 1, z: 0, halfX: 1, halfZ: 1, topZ: 8 };
  assert.equal(supportElevation(dragged, [low, high]), 8);
  assert.equal(supportElevation(dragged, [high, low]), 8);
});

function propRecord(id, x, z, topZ) {
  const size = 2;
  return {
    id,
    group: { position: { x, z }, rotation: { y: 0 }, scale: { x: 1 } },
    prop: { position: [50, 50, topZ - size / 0.1] },
    bounds: { min: { x: -1, y: 0, z: -1 }, max: { x: 1, y: size, z: 1 } },
  };
}

test("cardDropElevation is zero on the empty floor and rests on props", () => {
  assert.equal(cardDropElevation([], 0, 0, 0.425, 0.275), 0);
  const records = [propRecord("table", 0, 0, 12)];
  assert.equal(cardDropElevation(records, 0, 0, 0.425, 0.275), 12);
  assert.equal(cardDropElevation(records, 10, 10, 0.425, 0.275), 0);
});
