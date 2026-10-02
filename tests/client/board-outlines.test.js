import test from "node:test";
import assert from "node:assert/strict";
import * as THREE from "three";

import { createBoardOutlines } from "../../app/js/board-outlines.js";

test("selected mask takes precedence over active mask and releases proxy meshes", () => {
  const model = new THREE.Mesh(new THREE.BoxGeometry(1, 1, 1), new THREE.MeshBasicMaterial());
  const record = { model, prop: { quickActions: [{ command: ".go exit0" }] } };
  const renderer = { getPixelRatio: () => 1 };
  const outlines = createBoardOutlines(renderer, new THREE.Scene(), new THREE.Camera());
  try {
    assert.equal(outlines.update(record, false, true), true);
    assert.equal(record.outlineKind, 2);
    assert.equal(record.outlines[0].proxy.visible, true);
    const activeScene = record.outlines[0].proxy.parent;
    const activeMaterial = record.outlines[0].proxy.material;
    assert.equal(outlines.update(record, true, true), true);
    assert.equal(record.outlineKind, 1);
    assert.notEqual(record.outlines[0].proxy.material, activeMaterial);
    assert.notEqual(record.outlines[0].proxy.parent, activeScene);
    assert.equal(outlines.update(record, true, true), false);
    assert.equal(outlines.update(record, false, false), true);
    assert.equal(record.outlines[0].proxy.visible, false);
    assert.equal(record.outlines[0].proxy.parent, activeScene);
    outlines.remove(record);
    assert.equal(record.outlines, null);
    assert.equal(model.children.length, 0);
  } finally {
    outlines.dispose();
    model.geometry.dispose();
    model.material.dispose();
  }
});

test("mask proxies keep the geometry and morph pose without changing pickable models", () => {
  const geometry = new THREE.BoxGeometry(1, 1, 1);
  geometry.morphAttributes.position = [geometry.attributes.position.clone()];
  const model = new THREE.Mesh(geometry, new THREE.MeshBasicMaterial());
  model.morphTargetInfluences[0] = 0.7;
  const record = { model, prop: { quickActions: [] } };
  const outlines = createBoardOutlines({ getPixelRatio: () => 2 }, new THREE.Scene(), new THREE.Camera());
  try {
    outlines.update(record, true, false);
    const { proxy } = record.outlines[0];
    assert.equal(proxy.geometry, geometry);
    assert.equal(proxy.morphTargetInfluences, model.morphTargetInfluences);
    assert.equal(model.children.length, 0);
    outlines.remove(record);
    assert.equal(record.outlineKind, 0);
  } finally {
    outlines.dispose();
    geometry.dispose();
    model.material.dispose();
  }
});
