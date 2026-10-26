import test from "node:test";
import assert from "node:assert/strict";

import { clampNumber, validColor, wrapLines } from "../../client/app/js/surface-canvas.js";
import {
  defaultSurfaceFor,
  editorBoardProps,
  editorPatch,
  editorReducer,
  normalizeEditorView,
} from "../../client/app/js/editing/edit-reducer.js";

function editorWithSign() {
  return normalizeEditorView({
    room_id: "room:test",
    revision: 1,
    can_edit: true,
    props: [],
    library: [{
      prop_id: "builtin:sign",
      label: "Sign",
      render_kind: "sign",
      default_sign_style: "chalk",
      scale_min: 0.5,
      scale_max: 2,
    }],
    sign_options: { styles: [{ id: "wood" }, { id: "chalk" }] },
  });
}

test("wrapLines wraps, preserves newlines, and caps lines", () => {
  const context = { measureText: text => ({ width: String(text).length * 10 }) };
  assert.deepEqual(wrapLines(context, "one two three", 60, 4), ["one", "two", "three"]);
  assert.deepEqual(wrapLines(context, "one\ntwo", 100, 4), ["one", "two"]);
  assert.deepEqual(wrapLines(context, "a b c d e", 10, 2), ["a", "b"]);
});

test("surface canvas helpers reject malformed values", () => {
  assert.equal(validColor("#AABBCC", "#000000"), "#AABBCC");
  assert.equal(validColor("red", "#000000"), "#000000");
  assert.equal(clampNumber("12", 0, 10, 5), 10);
  assert.equal(clampNumber("nope", 0, 10, 5), 5);
});

test("adding a sign seeds its default finish and blank surface", () => {
  const state = { editor: editorWithSign() };
  const added = editorReducer(state, { type: "editor-add", propId: "builtin:sign" });
  const instance = added.editor.props[0];
  assert.equal(instance.signStyle, "chalk");
  assert.deepEqual(defaultSurfaceFor(added.editor.library[0]), {
    kind: "sign",
    revision: 0,
    content: { text: "New sign" },
  });
  assert.equal(editorPatch(added.editor).props[0].sign_style, "chalk");
  const boardProp = editorBoardProps(added.editor)[0];
  assert.equal(boardProp.renderKind, "sign");
  assert.equal(boardProp.surface.kind, "sign");
});

test("adding a whiteboard seeds a blank image-backed surface", () => {
  const editor = normalizeEditorView({
    room_id: "room:test",
    revision: 1,
    can_edit: true,
    props: [],
    library: [{
      prop_id: "builtin:whiteboard",
      label: "Whiteboard",
      render_kind: "whiteboard",
      scale_min: 0.5,
      scale_max: 2,
    }],
  });
  const surface = defaultSurfaceFor(editor.library[0]);
  assert.equal(surface.kind, "whiteboard");
  assert.equal(surface.content.image_url, "");
  assert.equal(surface.content.frame.outer, "bevel");
});

test("sign finish changes are undoable editor state", () => {
  let state = { editor: editorWithSign() };
  state = editorReducer(state, { type: "editor-add", propId: "builtin:sign" });
  const id = state.editor.props[0].id;
  const restyled = editorReducer(state, { type: "editor-sign-style", id, signStyle: "wood" });
  assert.equal(restyled.editor.props[0].signStyle, "wood");
  assert.equal(restyled.editor.dirty, true);
  const undone = editorReducer(restyled, { type: "editor-undo" });
  assert.equal(undone.editor.props[0].signStyle, "chalk");
});
