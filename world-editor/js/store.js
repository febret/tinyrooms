const UNDO_LIMIT = 60;

function clone(value) {
  return typeof structuredClone === "function"
    ? structuredClone(value)
    : JSON.parse(JSON.stringify(value));
}

function equal(a, b) {
  return JSON.stringify(a) === JSON.stringify(b);
}

export function createStore() {
  let state = {
    draft: null,
    catalog: null,
    worldKey: "",
    publishedRevision: null,
    selection: { kind: null, id: null, sub: null },
    activeTab: "board",
    dirty: false,
    undo: [],
    redo: [],
    validation: null,
    status: "",
    error: "",
    savedSnapshot: null,
  };
  const listeners = new Set();

  function emit() {
    for (const listener of listeners) listener(state);
  }

  function set(partial) {
    state = { ...state, ...partial };
    emit();
  }

  function withDraft(draft, extra) {
    return { ...extra, draft, dirty: !equal(draft, state.savedSnapshot) };
  }

  return {
    get state() {
      return state;
    },
    subscribe(listener) {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
    init({ draft, catalog, worldKey, publishedRevision }) {
      state = {
        ...state,
        draft,
        catalog,
        worldKey,
        publishedRevision,
        selection: { kind: null, id: null, sub: null },
        dirty: false,
        undo: [],
        redo: [],
        validation: null,
        status: "",
        error: "",
        savedSnapshot: clone(draft),
      };
      emit();
    },
    select(selection) {
      set({ selection: { kind: selection.kind || null, id: selection.id || null, sub: selection.sub || null } });
    },
    beginGesture() {
      set({ undo: [...state.undo, clone(state.draft)].slice(-UNDO_LIMIT), redo: [] });
    },
    update(mutator, { undoable = true } = {}) {
      const draft = clone(state.draft);
      mutator(draft);
      const undo = undoable
        ? [...state.undo, clone(state.draft)].slice(-UNDO_LIMIT)
        : state.undo;
      set(withDraft(draft, { undo, redo: undoable ? [] : state.redo }));
    },
    undo() {
      if (!state.undo.length) return;
      const draft = clone(state.undo[state.undo.length - 1]);
      set(withDraft(draft, {
        undo: state.undo.slice(0, -1),
        redo: [...state.redo, clone(state.draft)].slice(-UNDO_LIMIT),
      }));
    },
    redo() {
      if (!state.redo.length) return;
      const draft = clone(state.redo[state.redo.length - 1]);
      set(withDraft(draft, {
        redo: state.redo.slice(0, -1),
        undo: [...state.undo, clone(state.draft)].slice(-UNDO_LIMIT),
      }));
    },
    saved(draft) {
      set({ draft, savedSnapshot: clone(draft), dirty: false, undo: [], redo: [] });
    },
    discarded(draft) {
      set({ draft, savedSnapshot: clone(draft), dirty: false, undo: [], redo: [], validation: null });
    },
    validation(report) {
      set({ validation: report });
    },
    status(status, error = "") {
      set({ status, error });
    },
    activeTab(tab) {
      set({ activeTab: tab });
    },
  };
}
