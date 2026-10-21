import { updateMarkup } from "../presentation.js";
import {
  editRoomView, editorConflictMarkup, editorSelectedName, signStyleMarkup,
} from "../views/edit-room-view.js";
import { availableLibrary, selectedInstance } from "./edit-reducer.js";
import { bindEditorLibrary, createLibraryFilter } from "./library-filter.js";

export function bindEditorControls(root, onAction) {
  root.querySelectorAll("[data-close-view]").forEach(button => {
    button.onclick = () => onAction({ type: "close-view" });
  });
  root.querySelectorAll("[data-edit-add]").forEach(button => {
    button.onclick = () => onAction({ type: "edit-add", propId: button.dataset.editAdd });
  });
  root.querySelectorAll("[data-edit-action]").forEach(button => {
    button.onclick = () => onAction({
      type: "edit-action",
      action: button.dataset.editAction,
      delta: Number(button.dataset.editDelta || 0),
      factor: Number(button.dataset.editFactor || 1),
    });
  });
  root.querySelectorAll("[data-edit-snap]").forEach(input => {
    input.onchange = () => onAction({ type: "edit-snap", which: input.dataset.editSnap, value: input.checked });
  });
  root.querySelectorAll("[data-edit-style]").forEach(select => {
    select.onchange = () => onAction({ type: "edit-style", value: select.value });
  });
  root.querySelectorAll("[data-edit-sign-style]").forEach(button => {
    button.onclick = () => onAction({ type: "edit-sign-style", signStyle: button.dataset.editSignStyle });
  });
}

const SCROLL_REGIONS = ".editor-workspace, .editor-propsets, .editor-library-grid";

/** Shared gameplay/authoring dock. Actions use the gameplay editor payloads. */
export function createEditorDock({
  root, onAction, authoring = false,
  libraryFilter = authoring ? createLibraryFilter() : { bind: bindEditorLibrary },
}) {
  let rendered;

  function mount(markup, library) {
    if (rendered === markup) return;
    const active = root.contains(document.activeElement) ? document.activeElement : null;
    const searchFocused = active?.dataset.editSearch !== undefined;
    const caret = searchFocused ? [active.selectionStart, active.selectionEnd] : null;
    const scrolls = [...root.querySelectorAll(SCROLL_REGIONS)]
      .map(element => ({ top: element.scrollTop, left: element.scrollLeft }));
    root.innerHTML = markup;
    rendered = markup;
    bindEditorControls(root, onAction);
    libraryFilter.bind(root, library);
    root.querySelectorAll(SCROLL_REGIONS).forEach((element, index) => {
      element.scrollTop = scrolls[index]?.top || 0;
      element.scrollLeft = scrolls[index]?.left || 0;
    });
    if (searchFocused) {
      const search = root.querySelector("[data-edit-search]");
      search?.focus({ preventScroll: true });
      if (search && caret[0] !== null) search.setSelectionRange(...caret);
    }
  }

  return {
    /** With shell:false, only patch an already-mounted dock's dynamic regions. */
    render(state, { shell = true, authoring: authoringMode = authoring } = {}) {
      if (!root) return;
      const editor = state.editor;
      if (!editor) {
        if (shell) mount("", []);
        return;
      }
      if (shell) {
        // Selection and save state are patched without remounting library tiles.
        const shellState = { ...state, editor: { ...editor, conflict: null } };
        mount(editRoomView(shellState, { authoring: authoringMode }), availableLibrary(editor, state.user?.unlockedProps));
      }
      const selected = selectedInstance(editor);
      const name = root.querySelector("[data-edit-selected-name]");
      if (name) name.textContent = editorSelectedName(editor, selected);
      const styleRegion = root.querySelector("[data-editor-sign-styles]");
      if (styleRegion && updateMarkup(styleRegion, signStyleMarkup(editor, selected))) {
        bindEditorControls(styleRegion, onAction);
      }
      const deleteButton = root.querySelector("[data-editor-delete]");
      if (deleteButton) deleteButton.disabled = !selected;
      const textButton = root.querySelector("[data-editor-text]");
      if (textButton) textButton.disabled = !selected?.text || selected.locked;
      const undo = root.querySelector("[data-editor-undo]");
      if (undo) undo.disabled = !editor.undo.length;
      const redo = root.querySelector("[data-editor-redo]");
      if (redo) redo.disabled = !editor.redo.length;
      const status = root.querySelector("[data-editor-status]");
      if (status) status.textContent = editor.error || editor.status || (editor.dirty ? "Unsaved changes" : authoringMode ? "Draft saved" : "All changes saved");
      const conflict = root.querySelector("[data-editor-conflict]");
      if (conflict && updateMarkup(conflict, editorConflictMarkup(editor))) bindEditorControls(conflict, onAction);
    },
  };
}
