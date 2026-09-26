const UNDO_LIMIT = 50;
const POSITION_SNAP = 5;
const ROTATION_SNAP = 15;
const SCALE_STEP = 1.15;

function clone(value) {
  return typeof structuredClone === "function" ? structuredClone(value) : JSON.parse(JSON.stringify(value));
}

function clamp(value, minimum, maximum) {
  return Math.min(maximum, Math.max(minimum, value));
}

function roundTo(value, step) {
  return Math.round(value / step) * step;
}

function normalizeInstance(entry) {
  return {
    id: String(entry?.id || ""),
    propId: String(entry?.prop_id || entry?.propId || ""),
    position: Array.isArray(entry?.position) ? entry.position.map(Number) : [50, 50, 0],
    rotation: Array.isArray(entry?.rotation) ? entry.rotation.map(Number) : [0, 0, 0],
    scale: Number(entry?.scale ?? 1),
    effectSets: entry?.effect_sets && typeof entry.effect_sets === "object" ? entry.effect_sets : {},
    activeEffect: typeof entry?.active_effect === "string" ? entry.active_effect : "",
  };
}

function normalizeLibrary(entries) {
  return (Array.isArray(entries) ? entries : [])
    .map(entry => ({
      propId: String(entry?.prop_id || ""),
      label: String(entry?.label || entry?.prop_id || "Prop"),
      description: String(entry?.description || ""),
      modelUrl: String(entry?.model_url || ""),
      baseScale: Number(entry?.base_scale || 1),
      scaleMin: Number(entry?.scale_min ?? 0.25),
      scaleMax: Number(entry?.scale_max ?? 4),
      source: String(entry?.source || ""),
      tags: (Array.isArray(entry?.tags) ? entry.tags : []).map(tag => String(tag).trim().toLowerCase()).filter(Boolean),
      price: Number(entry?.price ?? 5),
      locked: Boolean(entry?.locked),
      effectSets: entry?.effect_sets && typeof entry.effect_sets === "object" ? entry.effect_sets : {},
      activeEffect: typeof entry?.active_effect === "string" ? entry.active_effect : "",
    }))
    .filter(entry => entry.propId);
}

/** Library entries the account may actually place (locked props need an unlock). */
export function availableLibrary(editor, unlockedPropIds) {
  const unlocked = unlockedPropIds instanceof Set ? unlockedPropIds : new Set(unlockedPropIds || []);
  return (editor?.library || []).filter(entry => !entry.locked || unlocked.has(entry.propId));
}

export function normalizeEditorView(view) {
  const props = Array.isArray(view?.props) ? view.props.map(normalizeInstance) : [];
  const environment = view?.environment && typeof view.environment === "object" ? { ...view.environment } : {};
  const revision = Number(view?.revision || 0);
  return {
    roomId: String(view?.room_id || ""),
    baseRevision: revision,
    revision,
    canEdit: Boolean(view?.can_edit),
    library: normalizeLibrary(view?.library),
    environmentWhitelist: Array.isArray(view?.environment_whitelist) ? [...view.environment_whitelist] : [],
    environment,
    savedEnvironment: { ...environment },
    props,
    savedProps: clone(props),
    selectedId: null,
    snapPosition: true,
    snapRotation: true,
    undo: [],
    redo: [],
    dirty: false,
    conflict: null,
    status: "",
    error: "",
  };
}

export function editablePropIds(editor) {
  return new Set((editor?.library || []).map(entry => entry.propId));
}

export function libraryEntry(editor, propId) {
  return (editor?.library || []).find(entry => entry.propId === propId) || null;
}

export function selectedInstance(editor) {
  if (!editor?.selectedId) return null;
  return editor.props.find(instance => instance.id === editor.selectedId) || null;
}

/** Convert draft instances into the normalized prop shape the board renders. */
export function editorBoardProps(editor) {
  if (!editor) return [];
  return editor.props.map(instance => {
    const entry = libraryEntry(editor, instance.propId);
    return {
      id: instance.id,
      propId: instance.propId,
      position: [...instance.position],
      rotation: [...instance.rotation],
      scale: instance.scale * (entry?.baseScale ?? 1),
      behavior: "",
      modelUrl: entry?.modelUrl || "",
      label: entry?.label || "Prop",
      description: entry?.description || "",
      animation: "",
      effectSets: Object.keys(instance.effectSets || {}).length ? instance.effectSets : (entry?.effectSets || {}),
      activeEffect: instance.activeEffect || entry?.activeEffect || "",
      quickActions: [],
      ghost: false,
    };
  });
}

function snapshot(editor) {
  return { props: clone(editor.props), environment: clone(editor.environment) };
}

function isDirty(editor) {
  return JSON.stringify(editor.props) !== JSON.stringify(editor.savedProps)
    || JSON.stringify(editor.environment) !== JSON.stringify(editor.savedEnvironment);
}

function pushUndo(editor) {
  return {
    ...editor,
    undo: [...editor.undo, snapshot(editor)].slice(-UNDO_LIMIT),
    redo: [],
  };
}

function withProps(editor, props) {
  const next = { ...editor, props };
  return { ...next, dirty: isDirty(next) };
}

function updateInstance(editor, id, updater) {
  const props = editor.props.map(instance => instance.id === id ? updater(instance) : instance);
  return withProps(editor, props);
}

function snapPosition(editor, position) {
  const x = editor.snapPosition ? roundTo(Number(position[0]), POSITION_SNAP) : Number(position[0]);
  const y = editor.snapPosition ? roundTo(Number(position[1]), POSITION_SNAP) : Number(position[1]);
  return [clamp(x, 0, 100), clamp(y, 0, 100), clamp(Number(position[2] || 0), 0, 50)];
}

function snapRotation(editor, rotation) {
  const y = Number(rotation[1] || 0);
  const snapped = editor.snapRotation ? roundTo(y, ROTATION_SNAP) : y;
  return [0, ((snapped % 360) + 360) % 360, 0];
}

function applySaved(editor, view) {
  const saved = normalizeEditorView(view);
  const stillSelected = saved.props.some(instance => instance.id === editor.selectedId);
  return {
    ...saved,
    selectedId: stillSelected ? editor.selectedId : null,
    snapPosition: editor.snapPosition,
    snapRotation: editor.snapRotation,
  };
}

/** Reduce an editor action against the shared store state. */
export function editorReducer(state, action) {
  const editor = state.editor;
  switch (action.type) {
    case "editor-open":
      return { ...state, editor: normalizeEditorView(action.view) };
    case "editor-close":
      return { ...state, editor: null };
    case "editor-select":
      return editor ? { ...state, editor: { ...editor, selectedId: action.id || null } } : state;
    case "editor-add": {
      if (!editor) return state;
      const entry = libraryEntry(editor, action.propId);
      if (!entry) return state;
      const instance = {
        id: `custom:${crypto.randomUUID()}`,
        propId: entry.propId,
        position: snapPosition(editor, action.position || [50, 50, 0]),
        rotation: [0, 0, 0],
        scale: clamp(1, entry.scaleMin, entry.scaleMax),
      };
      const next = pushUndo(editor);
      const props = [...next.props, instance];
      const withNew = withProps(next, props);
      return { ...state, editor: { ...withNew, selectedId: instance.id } };
    }
    case "editor-remove": {
      if (!editor) return state;
      const next = pushUndo(editor);
      const props = next.props.filter(instance => instance.id !== action.id);
      return { ...state, editor: { ...withProps(next, props), selectedId: next.selectedId === action.id ? null : next.selectedId } };
    }
    case "editor-begin":
      return editor ? { ...state, editor: pushUndo(editor) } : state;
    case "editor-transform": {
      if (!editor) return state;
      const props = editor.props.map(instance => {
        if (instance.id !== action.id) return instance;
        if (action.position) return { ...instance, position: snapPosition(editor, action.position) };
        if (action.rotation) return { ...instance, rotation: snapRotation(editor, action.rotation) };
        if (typeof action.scale === "number") {
          const entry = libraryEntry(editor, instance.propId);
          return { ...instance, scale: clamp(action.scale, entry?.scaleMin ?? 0.25, entry?.scaleMax ?? 4) };
        }
        return instance;
      });
      return { ...state, editor: withProps(editor, props) };
    }
    case "editor-nudge": {
      if (!editor) return state;
      const instance = selectedInstance(editor);
      if (!instance) return state;
      const position = [
        instance.position[0] + Number(action.dx || 0),
        instance.position[1] + Number(action.dy || 0),
        instance.position[2],
      ];
      const next = pushUndo(editor);
      return { ...state, editor: updateInstance(next, instance.id, current => ({ ...current, position: snapPosition(next, position) })) };
    }
    case "editor-rotate": {
      if (!editor) return state;
      const instance = selectedInstance(editor);
      if (!instance) return state;
      const next = pushUndo(editor);
      return {
        ...state,
        editor: updateInstance(next, instance.id, current => ({
          ...current,
          rotation: snapRotation(next, [0, current.rotation[1] + Number(action.delta || 0), 0]),
        })),
      };
    }
    case "editor-scale": {
      if (!editor) return state;
      const instance = selectedInstance(editor);
      if (!instance) return state;
      const entry = libraryEntry(editor, instance.propId);
      const factor = Number(action.factor || SCALE_STEP);
      const next = pushUndo(editor);
      return {
        ...state,
        editor: updateInstance(next, instance.id, current => ({
          ...current,
          scale: clamp(current.scale * factor, entry?.scaleMin ?? 0.25, entry?.scaleMax ?? 4),
        })),
      };
    }
    case "editor-env": {
      if (!editor) return state;
      const next = pushUndo(editor);
      const environment = { ...next.environment, [action.key]: clone(action.value) };
      const withEnv = { ...next, environment };
      return { ...state, editor: { ...withEnv, dirty: isDirty(withEnv) } };
    }
    case "editor-undo": {
      if (!editor || !editor.undo.length) return state;
      const previous = editor.undo[editor.undo.length - 1];
      const next = {
        ...editor,
        props: clone(previous.props),
        environment: clone(previous.environment),
        undo: editor.undo.slice(0, -1),
        redo: [...editor.redo, snapshot(editor)].slice(-UNDO_LIMIT),
        conflict: null,
      };
      return { ...state, editor: { ...next, dirty: isDirty(next) } };
    }
    case "editor-redo": {
      if (!editor || !editor.redo.length) return state;
      const following = editor.redo[editor.redo.length - 1];
      const next = {
        ...editor,
        props: clone(following.props),
        environment: clone(following.environment),
        redo: editor.redo.slice(0, -1),
        undo: [...editor.undo, snapshot(editor)].slice(-UNDO_LIMIT),
        conflict: null,
      };
      return { ...state, editor: { ...next, dirty: isDirty(next) } };
    }
    case "editor-snap":
      return editor ? { ...state, editor: { ...editor, [action.which === "rotation" ? "snapRotation" : "snapPosition"]: Boolean(action.value) } } : state;
    case "editor-saved":
      return editor ? { ...state, editor: applySaved(editor, action.view) } : state;
    case "editor-conflict":
      return editor ? { ...state, editor: { ...editor, conflict: action.layout ? normalizeEditorView(action.layout) : null, status: "" } } : state;
    case "editor-rebase":
      return editor ? { ...state, editor: { ...editor, baseRevision: Number(action.revision || 0), conflict: null } } : state;
    case "editor-status":
      return editor ? { ...state, editor: { ...editor, status: String(action.message || ""), error: String(action.error || "") } } : state;
    default:
      return state;
  }
}
