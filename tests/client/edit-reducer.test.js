import test from "node:test";
import assert from "node:assert/strict";

import { editorReducer, normalizeEditorView, snapPositionValue } from "../../app/js/editing/edit-reducer.js";

function editorState() {
  const editor = normalizeEditorView({
    room_id: "hub",
    revision: 1,
    can_edit: true,
    props: [{ id: "p1", prop_id: "plant", position: [50, 50, 0], rotation: [0, 0, 0], scale: 1 }],
    environment: {},
    library: [{ prop_id: "plant", label: "Plant", model_url: "/plant.glb", base_scale: 1, scale_min: 0.25, scale_max: 4 }],
  });
  return { editor: { ...editor, selectedId: "p1" } };
}

test("snapPositionValue snaps x/y to the grid and clamps elevation", () => {
  assert.deepEqual(snapPositionValue([52, 47, 3], true), [50, 45, 3]);
  assert.deepEqual(snapPositionValue([52.4, 47.6, 3], false), [52.4, 47.6, 3]);
  assert.deepEqual(snapPositionValue([150, -10, 99], true), [100, 0, 50]);
});

test("rotate gestures stream deltas under a single undo snapshot", () => {
  const start = editorState();
  const free = editorReducer(start, { type: "editor-snap", which: "rotation", value: false });
  const begun = editorReducer(free, { type: "editor-begin" });
  const first = editorReducer(begun, { type: "editor-rotate", delta: 10, gesture: true });
  const second = editorReducer(first, { type: "editor-rotate", delta: 10, gesture: true });
  assert.equal(second.editor.undo.length, start.editor.undo.length + 1);
  assert.equal(second.editor.props[0].rotation[1], 20);
});

test("rotation is smooth by default instead of snapping to fixed angles", () => {
  const start = editorState();
  assert.equal(start.editor.snapRotation, false);
  const rotated = editorReducer(start, { type: "editor-rotate", delta: 7 });
  assert.equal(rotated.editor.props[0].rotation[1], 7);
});

test("a non-gesture rotate still records its own undo step", () => {
  const start = editorState();
  const next = editorReducer(start, { type: "editor-rotate", delta: 15 });
  assert.equal(next.editor.undo.length, start.editor.undo.length + 1);
  assert.equal(next.editor.props[0].rotation[1], 15);
});

test("scale gestures clamp to the library bounds without piling up undo", () => {
  const start = editorState();
  const begun = editorReducer(start, { type: "editor-begin" });
  let state = begun;
  for (let index = 0; index < 10; index += 1) {
    state = editorReducer(state, { type: "editor-scale", factor: 2, gesture: true });
  }
  assert.equal(state.editor.undo.length, start.editor.undo.length + 1);
  assert.equal(state.editor.props[0].scale, 4);
});
