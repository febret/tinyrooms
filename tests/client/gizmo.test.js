import test from "node:test";
import assert from "node:assert/strict";

import { circleLocalRadius, footprintRadius, rotationDeltaForDrag, ROTATE_DRAG_DEG_PER_PX } from "../../app/js/editing/gizmo.js";

function closeTo(actual, expected, epsilon = 1e-9) {
  assert.ok(Math.abs(actual - expected) < epsilon, `${actual} is not within ${epsilon} of ${expected}`);
}

test("a 100px rightward rotate drag turns the prop 20 degrees clockwise", () => {
  assert.equal(ROTATE_DRAG_DEG_PER_PX, 0.2);
  closeTo(rotationDeltaForDrag(100), -20);
  closeTo(rotationDeltaForDrag(-50), 10);
  closeTo(rotationDeltaForDrag(0), 0);
  closeTo(rotationDeltaForDrag(undefined), 0);
});

test("the drag circle wraps the prop footprint at the gizmo's clamped scale", () => {
  // Unknown footprint still leaves a grabbable circle.
  closeTo(circleLocalRadius(0, 1), 0.56);
  closeTo(circleLocalRadius(-3, 1), 0.56);
  // A world footprint is divided back into local space so the world radius matches.
  closeTo(circleLocalRadius(2, 2), 1.14);
  // The scale factor is clamped to the same range as the gizmo group.
  closeTo(circleLocalRadius(4, 4), 2.14);
  closeTo(circleLocalRadius(4, 0.1), 8.14);
});

test("the footprint radius uses the widest local axis and the applied scale", () => {
  const bounds = { min: { x: 0, y: 0, z: 0 }, max: { x: 2, y: 1, z: 4 } };
  closeTo(footprintRadius(bounds, 2), 4);
  closeTo(footprintRadius(bounds, 1), 2);
  assert.equal(footprintRadius(null, 3), 0);
});
