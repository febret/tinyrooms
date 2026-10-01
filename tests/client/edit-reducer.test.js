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

test("rotate streams gesture deltas under one undo step and discrete deltas separately", () => {
  const start = editorState();
  assert.equal(start.editor.snapRotation, false, "rotation is smooth by default");
  const begun = editorReducer(start, { type: "editor-begin" });
  const first = editorReducer(begun, { type: "editor-rotate", delta: 10, gesture: true });
  const second = editorReducer(first, { type: "editor-rotate", delta: 10, gesture: true });
  assert.equal(second.editor.undo.length, start.editor.undo.length + 1);
  assert.equal(second.editor.props[0].rotation[1], 20);
  const discrete = editorReducer(second, { type: "editor-rotate", delta: 15 });
  assert.equal(discrete.editor.undo.length, start.editor.undo.length + 2);
  assert.equal(discrete.editor.props[0].rotation[1], 35);
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

test("elevate gestures stream under one undo, clamp to 0-50 and keep x/y", () => {
  const start = editorState();
  const begun = editorReducer(start, { type: "editor-begin" });
  const raised = editorReducer(begun, { type: "editor-elevate", delta: 12, gesture: true });
  assert.equal(raised.editor.undo.length, start.editor.undo.length + 1);
  assert.deepEqual(raised.editor.props[0].position, [50, 50, 12]);
  const floored = editorReducer(raised, { type: "editor-elevate", delta: -99, gesture: true });
  assert.deepEqual(floored.editor.props[0].position, [50, 50, 0]);
  const capped = editorReducer(floored, { type: "editor-elevate", delta: 99, gesture: true });
  assert.deepEqual(capped.editor.props[0].position, [50, 50, 50]);
});

test("editor-lock toggles, is undoable, and defaults off", () => {
  const start = editorState();
  assert.equal(start.editor.props[0].locked, false);
  const locked = editorReducer(start, { type: "editor-lock", id: "p1" });
  assert.equal(locked.editor.props[0].locked, true);
  assert.equal(locked.editor.undo.length, start.editor.undo.length + 1);
  const unlocked = editorReducer(locked, { type: "editor-lock", id: "p1" });
  assert.equal(unlocked.editor.props[0].locked, false);
  const undone = editorReducer(unlocked, { type: "editor-undo" });
  assert.equal(undone.editor.props[0].locked, true);
});

test("locked instances reject move, nudge, rotate, scale and elevate", () => {
  const locked = editorReducer(editorState(), { type: "editor-lock", id: "p1", locked: true });
  const moved = editorReducer(locked, { type: "editor-transform", id: "p1", position: [10, 10, 0] });
  assert.deepEqual(moved.editor.props[0].position, [50, 50, 0]);
  const nudged = editorReducer(locked, { type: "editor-nudge", dx: 5, dy: 5 });
  assert.deepEqual(nudged.editor.props[0].position, [50, 50, 0]);
  const rotated = editorReducer(locked, { type: "editor-rotate", delta: 15 });
  assert.equal(rotated.editor.props[0].rotation[1], 0);
  const scaled = editorReducer(locked, { type: "editor-scale", factor: 2 });
  assert.equal(scaled.editor.props[0].scale, 1);
  const raised = editorReducer(locked, { type: "editor-elevate", delta: 10 });
  assert.equal(raised.editor.props[0].position[2], 0);
  // The lock itself stays reversible.
  const unlocked = editorReducer(locked, { type: "editor-lock", id: "p1", locked: false });
  const after = editorReducer(unlocked, { type: "editor-nudge", dx: 5, dy: 0 });
  assert.deepEqual(after.editor.props[0].position, [55, 50, 0]);
});
