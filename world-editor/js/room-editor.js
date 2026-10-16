import { editorReducer, normalizeEditorView } from "../../app/js/editing/edit-reducer.js";
import { editorPalette } from "../../app/js/views/edit-room-view.js";
import { withBase } from "../../app/js/base-path.js";

/** Adapt authored instances to the same editing core used by room owners. */
export function worldRoomEditor(state, roomId) {
  const room = state.draft?.rooms?.[roomId];
  if (!room) return null;
  const settings = state.editorSettings || {};
  const library = (state.catalog?.props || []).map(prop => ({
    prop_id: prop.id,
    label: prop.label,
    description: prop.description,
    model_url: withBase(prop.model_url || ""),
    base_scale: prop.scale,
    // Authors can arrange functional props and retain the existing authoring bounds.
    scale_min: 0.05,
    scale_max: Number.MAX_VALUE,
    source: prop.source,
    tags: prop.tags,
    locked: false,
  }));
  const visible = new Set(library.map(prop => prop.prop_id));
  const editor = normalizeEditorView({
    room_id: roomId,
    can_edit: true,
    library,
    props: Object.entries(room.props || {}).filter(([, prop]) => visible.has(prop.prop)).map(([id, prop]) => ({
      id, prop_id: prop.prop, position: prop.pos, rotation: prop.rot, scale: prop.scale,
      locked: Boolean(settings.locks?.[roomId]?.[id]),
    })),
    environment_whitelist: ["palette", "board_image_style"],
    environment: { palette: room.palette || [], board_image_style: room.board_image_style || "stretch" },
  });
  return {
    ...editor,
    selectedId: state.selection.kind === "prop" && state.selection.id === roomId ? state.selection.sub : null,
    snapPosition: settings.snapPosition ?? true,
    snapRotation: settings.snapRotation ?? false,
    undo: state.undo,
    redo: state.redo,
    dirty: state.dirty,
    status: state.status,
    error: state.error,
  };
}

/** Merge only edited fields; authoring-only data and non-visible props survive. */
export function applyRoomEditorChanges(room, before, after) {
  const previous = new Map(before.props.map(prop => [prop.id, prop]));
  const remaining = new Set(after.props.map(prop => prop.id));
  if (!room.props) room.props = {};
  for (const prop of before.props) {
    if (!remaining.has(prop.id)) delete room.props[prop.id];
  }
  for (const prop of after.props) {
    const old = previous.get(prop.id);
    if (!old) {
      room.props[prop.id] = { prop: prop.propId, pos: prop.position, rot: prop.rotation, scale: prop.scale };
      continue;
    }
    const target = room.props[prop.id];
    if (JSON.stringify(old.position) !== JSON.stringify(prop.position)) target.pos = [...prop.position];
    if (JSON.stringify(old.rotation) !== JSON.stringify(prop.rotation)) {
      const rotation = target.rot || [0, 0, 0];
      target.rot = [rotation[0], prop.rotation[1], rotation[2]];
    }
    if (old.scale !== prop.scale) target.scale = prop.scale;
  }
  for (const key of ["palette", "board_image_style"]) {
    if (JSON.stringify(before.environment[key]) !== JSON.stringify(after.environment[key])) {
      room[key] = after.environment[key];
    }
  }
}

export function createWorldRoomEditor(store, getRoomId) {
  function dispatch(action) {
    const roomId = getRoomId();
    const before = worldRoomEditor(store.state, roomId);
    if (!before) return;
    if (action.type === "editor-undo") return store.undo();
    if (action.type === "editor-redo") return store.redo();
    if (action.type === "editor-begin") return store.beginGesture();
    const after = editorReducer({ editor: before }, action).editor;
    if (after === before) return;
    if (action.type === "editor-snap") {
      return store.editorSettings({ snapPosition: after.snapPosition, snapRotation: after.snapRotation });
    }
    if (action.type === "editor-lock") {
      const locks = { ...store.state.editorSettings.locks };
      locks[roomId] = Object.fromEntries(after.props.filter(prop => prop.locked).map(prop => [prop.id, true]));
      return store.editorSettings({ locks });
    }
    if (JSON.stringify(before.props) !== JSON.stringify(after.props)
      || JSON.stringify(before.environment) !== JSON.stringify(after.environment)) {
      const streamed = action.type === "editor-transform" || Boolean(action.gesture);
      store.update(draft => applyRoomEditorChanges(draft.rooms[roomId], before, after), { undoable: !streamed });
    }
    if (after.selectedId !== before.selectedId) {
      store.select({ kind: after.selectedId ? "prop" : "room", id: roomId, sub: after.selectedId });
    }
  }

  function onAction(action) {
    if (action.type === "edit-action") {
      const name = action.action;
      const editor = worldRoomEditor(store.state, getRoomId());
      return dispatch({ ...action, type: `editor-${name}`, id: editor?.selectedId });
    }
    if (action.type === "edit-add") return dispatch({ type: "editor-add", propId: action.propId });
    if (action.type === "edit-snap") return dispatch({ type: "editor-snap", which: action.which, value: action.value });
    if (action.type === "edit-style") return dispatch({ type: "editor-env", key: "board_image_style", value: action.value });
    if (action.type === "edit-palette") {
      const editor = worldRoomEditor(store.state, getRoomId());
      const colors = [...(editor.environment.palette || [])];
      const defaults = editorPalette({ editor });
      while (colors.length < 3) colors.push(defaults[colors.length]);
      colors[action.index] = action.value;
      return dispatch({ type: "editor-env", key: "palette", value: colors });
    }
  }
  return { dispatch, onAction };
}
