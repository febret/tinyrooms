import test from "node:test";
import assert from "node:assert/strict";

import {
  editorBoardProps,
  editorPatch,
  editorReducer,
  normalizeEditorView,
} from "../../client/app/js/editing/edit-reducer.js";
import { propModelKey } from "../../client/app/js/board-helpers.js";
import { exitFinishMarkup } from "../../client/app/js/views/edit-room-view.js";
import {
  applyRoomEditorChanges,
  worldRoomEditor,
} from "../../client/world-editor/js/room-editor.js";

const DOOR_ENTRY = {
  prop_id: "builtin:door",
  label: "Door",
  render_kind: "door",
  scale_min: 0.25,
  scale_max: 4,
};

const EXIT_STYLE_OPTIONS = {
  door: [{ id: "panel", label: "Paneled" }, { id: "arch", label: "Arched" }, { id: "slab", label: "Modern slab" }],
  arrow: [{ id: "floor", label: "Floor chevron" }],
  stairs: [],
  textures: [{ id: "plain", label: "Plain" }, { id: "wood", label: "Wood grain", file: "exit-wood.png" }],
  defaults: { door: { style: "panel", main: "#b07a4a", accent: "#6b4a2f", texture: "plain" } },
};

function editorWithDoor() {
  return normalizeEditorView({
    room_id: "room:test",
    revision: 1,
    can_edit: true,
    props: [],
    library: [DOOR_ENTRY],
    exit_style_options: EXIT_STYLE_OPTIONS,
  });
}

test("adding an exit prop seeds the kind default finish", () => {
  const state = { editor: editorWithDoor() };
  const added = editorReducer(state, { type: "editor-add", propId: "builtin:door" });
  assert.deepEqual(added.editor.props[0].exitStyle, {
    style: "panel", main: "#b07a4a", accent: "#6b4a2f", texture: "plain",
  });
  assert.deepEqual(editorPatch(added.editor).props[0].exit_style, {
    style: "panel", main: "#b07a4a", accent: "#6b4a2f", texture: "plain",
  });
});

test("exit finish patches merge over the current finish", () => {
  let state = { editor: editorWithDoor() };
  state = editorReducer(state, { type: "editor-add", propId: "builtin:door" });
  const id = state.editor.props[0].id;
  const styled = editorReducer(state, { type: "editor-exit-style", id, key: "style", value: "arch" });
  assert.equal(styled.editor.props[0].exitStyle.style, "arch");
  assert.equal(styled.editor.props[0].exitStyle.texture, "plain");
  const colored = editorReducer(
    { editor: styled.editor },
    { type: "editor-exit-style", id, key: "main", value: "#112233" },
  );
  assert.equal(colored.editor.props[0].exitStyle.main, "#112233");
  assert.equal(colored.editor.props[0].exitStyle.style, "arch");
  assert.equal(colored.editor.dirty, true);
});

test("exit finish patches reject unknown keys and non-exit props", () => {
  const state = { editor: editorWithDoor() };
  const added = editorReducer(state, { type: "editor-add", propId: "builtin:door" });
  const id = added.editor.props[0].id;
  const rejected = editorReducer(
    { editor: added.editor },
    { type: "editor-exit-style", id, key: "surface", value: "x" },
  );
  assert.equal(rejected.editor.props[0].exitStyle.style, "panel");
});

test("the dock renders finish controls for the selected exit prop", () => {
  let state = { editor: editorWithDoor() };
  state = editorReducer(state, { type: "editor-add", propId: "builtin:door" });
  const editor = state.editor;
  const selected = editor.props[0];
  const html = exitFinishMarkup({ ...editor, exitStyleOptions: EXIT_STYLE_OPTIONS }, selected);
  assert.match(html, /data-edit-exit-style="style"/);
  assert.match(html, /data-edit-exit-style="main"/);
  assert.match(html, /data-edit-exit-style="accent"/);
  assert.match(html, /data-edit-exit-style="texture"/);
  assert.match(html, /Arched/);
  assert.match(html, /Wood grain/);
});

test("the dock renders no finish controls without an exit selection", () => {
  const editor = editorWithDoor();
  assert.equal(exitFinishMarkup(editor, null), "");
  const plain = normalizeEditorView({
    room_id: "room:test",
    revision: 1,
    can_edit: true,
    props: [{ id: "rug-1", prop_id: "rug", position: [50, 50, 0], rotation: [0, 0, 0], scale: 1 }],
    library: [{ prop_id: "rug", label: "Rug", render_kind: "model" }],
    exit_style_options: EXIT_STYLE_OPTIONS,
  });
  const selected = plain.props.find(entry => entry.id === "rug-1");
  assert.equal(exitFinishMarkup({ ...plain, exitStyleOptions: EXIT_STYLE_OPTIONS }, selected), "");
});

function worldEditorState(room) {
  return {
    draft: { rooms: { hub: room } },
    selection: { kind: "room", id: "hub" },
    catalog: {
      props: [{ id: "builtin:door", label: "Door", render_kind: "door", scale: 1 }],
      exit_style_options: EXIT_STYLE_OPTIONS,
    },
    editorSettings: {},
    undo: [],
    redo: [],
    dirty: false,
    status: "",
    error: "",
  };
}

test("the world editor adapter carries exit finishes into and out of the dock", () => {  const room = {
    label: "Hub",
    props: {
      door: {
        prop: "builtin:door",
        pos: [50, 50, 0],
        rot: [0, 0, 0],
        scale: 1,
        exit_to: "out",
        exit_style: { style: "arch", main: "#b07a4a", accent: "#6b4a2f", texture: "wood" },
      },
    },
    exits: { out: { label: "Out", target: "elsewhere" } },
  };
  const editor = worldRoomEditor(worldEditorState(room), "hub");
  assert.deepEqual(editor.props[0].exitStyle, {
    style: "arch", main: "#b07a4a", accent: "#6b4a2f", texture: "wood",
  });
  const after = editorReducer(
    { editor },
    { type: "editor-exit-style", id: "door", key: "texture", value: "plain" },
  );
  applyRoomEditorChanges(room, editor, after.editor);
  assert.equal(room.props.door.exit_style.texture, "plain");
  assert.equal(room.props.door.exit_style.style, "arch");
  assert.equal(room.props.door.exit_to, "out");
});

test("editor board props carry the finish so dock edits rebuild the mesh", () => {
  let state = { editor: editorWithDoor() };
  state = editorReducer(state, { type: "editor-add", propId: "builtin:door" });
  const id = state.editor.props[0].id;
  const before = editorBoardProps(state.editor).find(prop => prop.id === id);
  assert.deepEqual(before.exitStyle, {
    style: "panel", main: "#b07a4a", accent: "#6b4a2f", texture: "plain",
  });
  const beforeKey = propModelKey(before);
  state = editorReducer(state, { type: "editor-exit-style", id, key: "style", value: "slab" });
  const after = editorBoardProps(state.editor).find(prop => prop.id === id);
  assert.equal(after.exitStyle.style, "slab");
  assert.notEqual(propModelKey(after), beforeKey);
});
