import test from "node:test";
import assert from "node:assert/strict";

import { mergeLayoutProps } from "../../client/app/js/normalize.js";

test("a layout update keeps authored prop actions and sounds while moving it", () => {
  const quickActions = [{ label: "Open", command: ".go @way:garden" }];
  const sounds = { action: "/assets/sounds/door.ogg" };
  const previous = [{
    id: "door",
    propId: "wood-door",
    label: "Door",
    description: "A sturdy wooden door.",
    behavior: "portal",
    position: [10, 10, 0],
    rotation: [0, 0, 0],
    scale: 1,
    quickActions,
    sounds,
    modelUrl: "/assets/door.glb",
    renderKind: "model",
  }];
  const merged = mergeLayoutProps(previous, [{
    id: "door",
    prop_id: "wood-door",
    label: "Wood Door",
    description: "Updated description.",
    behavior: "portal",
    position: [60, 40, 0],
    rotation: [0, 45, 0],
    scale: 1.2,
    model_url: "/assets/door.glb",
    render_kind: "model",
    quick_actions: [],
  }]);

  assert.equal(merged.length, 1);
  assert.deepEqual(merged[0].position, [60, 40, 0]);
  assert.deepEqual(merged[0].rotation, [0, 45, 0]);
  assert.equal(merged[0].scale, 1.2);
  assert.deepEqual(merged[0].quickActions, quickActions);
  assert.deepEqual(merged[0].sounds, sounds);
  assert.equal(merged[0].label, "Wood Door");
  assert.equal(merged[0].description, "Updated description.");
  assert.equal(merged[0].behavior, "portal");
});

test("a layout update adds new props and removes missing props", () => {
  const previous = [{ id: "old", propId: "chair", position: [20, 20, 0] }];
  const merged = mergeLayoutProps(previous, [{
    id: "custom:new",
    prop_id: "chair",
    position: [80, 80, 0],
    rotation: [0, 0, 0],
    scale: 1,
    quick_actions: [],
  }]);

  assert.deepEqual(merged.map(prop => prop.id), ["custom:new"]);
  assert.deepEqual(merged[0].quickActions, []);
});
