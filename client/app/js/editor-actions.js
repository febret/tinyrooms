import { editorPatch } from "./editing/edit-reducer.js";
import { editorKeyAction } from "./editing/editor-keyboard.js";
import { resetLibraryFilter } from "./editing/library-filter.js";
import { openTextPropDialog } from "./editing/text-prop-dialog.js";

/**
 * Room-editor open/save/reset actions, bound to the app's shared services.
 *
 * The editor spans the WebSocket store and the layout HTTP API, so these live
 * beside the app shell rather than inside the pure reducer.
 */
export function createEditorActions({ store, api, dialogs, toast, showError, sendCommand }) {
  function closeEditor() {
    resetLibraryFilter();
    store.dispatch({ type: "editor-close" });
    store.dispatch({ type: "close-view" });
  }

  /** Save any pending layout changes, then close. Stays open when the save conflicts or fails. */
  async function saveAndCloseEditor() {
    const editor = store.getState().editor;
    if (editor?.dirty && !(await saveRoomEditor())) return false;
    closeEditor();
    return true;
  }

  async function openRoomEditor() {
    const roomId = store.getState().room?.id;
    if (!roomId) return;
    try {
      const layout = await api.getRoomLayout(roomId);
      if (layout) {
        resetLibraryFilter();
        store.dispatch({ type: "editor-open", view: layout });
      } else toast("The room layout could not be loaded.", "error");
    } catch (error) {
      showError(error);
    }
  }

  /** Reset the live room to its YAML definition, discarding unsaved edits. */
  async function resetRoomEditor() {
    const editor = store.getState().editor;
    if (!editor) return;
    store.dispatch({ type: "editor-status", message: "Resetting…", error: "" });
    try {
      const result = await api.resetRoomLayout(editor.roomId);
      store.dispatch({ type: "editor-reset-arm", armed: false });
      if (result?.layout) store.dispatch({ type: "editor-open", view: result.layout });
      toast("Room reset to its defined state.", "success");
    } catch (error) {
      store.dispatch({ type: "editor-status", message: "", error: error instanceof Error ? error.message : String(error) });
      showError(error);
    }
  }

  async function saveRoomEditor() {
    const editor = store.getState().editor;
    if (!editor) return false;
    store.dispatch({ type: "editor-status", message: "Saving…", error: "" });
    try {
      const result = await api.saveRoomLayout(editor.roomId, {
        base_revision: editor.baseRevision,
        patch: editorPatch(editor),
      });
      if (result.conflict) {
        store.dispatch({ type: "editor-conflict", layout: result.layout });
        toast(result.message, "error");
        return false;
      }
      store.dispatch({ type: "editor-saved", view: result.layout });
      toast("Layout saved.", "success");
      return true;
    } catch (error) {
      store.dispatch({ type: "editor-status", message: "", error: error instanceof Error ? error.message : String(error) });
      showError(error);
      return false;
    }
  }

  function applyEditorPalette(index, value) {
    const state = store.getState();
    const editor = state.editor;
    if (!editor) return;
    const current = editor.environment.palette || state.room?.board?.palette || [];
    const colors = [...current];
    while (colors.length < 3) colors.push("#d4be94");
    if (String(colors[index] || "").toLowerCase() === String(value).toLowerCase()) return;
    colors[index] = value;
    store.dispatch({ type: "editor-env", key: "palette", value: colors });
  }

  async function applyEditorAction(action) {
    const state = store.getState();
    if (!state.editor) return;
    switch (action.action) {
      case "add-text":
        openTextPropDialog({ dialogs, store });
        break;
      case "edit-text":
        openTextPropDialog({ dialogs, store, id: state.editor.selectedId });
        break;
      case "undo":
        store.dispatch({ type: "editor-undo" });
        break;
      case "redo":
        store.dispatch({ type: "editor-redo" });
        break;
      case "remove":
        if (state.editor.selectedId) store.dispatch({ type: "editor-remove", id: state.editor.selectedId });
        break;
      case "lock":
        if (state.editor.selectedId) {
          const selected = state.editor.props.find(entry => entry.id === state.editor.selectedId);
          store.dispatch({ type: "editor-lock", id: state.editor.selectedId, locked: !selected?.locked });
        }
        break;
      case "rotate":
        store.dispatch({ type: "editor-rotate", delta: action.delta || 15 });
        break;
      case "scale":
        store.dispatch({ type: "editor-scale", factor: action.factor || 1.15 });
        break;
      case "shop":
        try { await sendCommand(".shop props"); } catch (error) { showError(error); }
        break;
      case "reset":
        store.dispatch({ type: "editor-reset-arm", armed: true });
        break;
      case "reset-cancel":
        store.dispatch({ type: "editor-reset-arm", armed: false });
        break;
      case "reset-confirm":
        await resetRoomEditor();
        break;
      case "reload":
        if (state.editor.conflict) store.dispatch({ type: "editor-saved", view: state.editor.conflict });
        break;
      case "reapply":
        if (state.editor.conflict) {
          store.dispatch({ type: "editor-rebase", revision: state.editor.conflict.revision });
          await saveRoomEditor();
        }
        break;
    }
  }

  function handleEditorKey(event) {
    const action = editorKeyAction(event, store.getState().editor);
    if (!action) return false;
    store.dispatch(action);
    return true;
  }

  return {
    closeEditor,
    saveAndCloseEditor,
    openRoomEditor,
    resetRoomEditor,
    saveRoomEditor,
    applyEditorPalette,
    applyEditorAction,
    handleEditorKey,
  };
}
