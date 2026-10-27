import {
  discardDraft,
  loadDraft,
  loadSession,
  publishDraft,
  resetRoom,
  saveDraft,
  validateDraft,
} from "./api.js";
import { createBoardView } from "./board-view.js";
import { createStore } from "./store.js";
import { escapeHtml, parseCsv, parseJson, numberOr, textToActions, uniqueId } from "./util.js";
import { roomQualityReport } from "./quality.js";
import {
  applyDialogGraphChanges,
  applyRoomGraphChanges,
  dialogGraph,
  removeRoom,
  roomGraph,
} from "./graph-model.js";
import { createGraphView } from "./graph-view.js";
import { bindPanelSplitters } from "./panel-splitter.js";
import { renderRoomList } from "./panels/rooms.js";
import { renderProperties } from "./panels/properties.js";
import { renderValidation } from "./panels/validation.js";
import {
  renderActivities,
  renderEnvironment,
  renderRecipes,
  renderTasks,
} from "./panels/systems.js";
import { createThumbnailManager } from "../../app/js/editing/prop-thumbnails.js";
import { bindEditorControls, createEditorDock } from "../../app/js/editing/editor-dock.js";
import { editorSettingsView } from "../../app/js/views/edit-room-view.js";
import { createWorldRoomEditor, worldRoomEditor } from "./room-editor.js";
import { editorKeyAction } from "../../app/js/editing/editor-keyboard.js";
import { createCardSelector } from "./card-selector.js";
import { reconcileRoomCards } from "./room-cards.js";
import { createDialogs } from "../../app/js/dialogs.js";
import { openTextPropDialog } from "../../app/js/editing/text-prop-dialog.js";

const store = createStore();
const cardSelector = createCardSelector({
  getCards: () => {
    const catalog = store.state.catalog;
    const database = new Map((catalog?.card_database?.cards || []).map(card => [card.id, card]));
    return (catalog?.cards || []).map(card => ({ ...card, ...database.get(card.id) }));
  },
  onChange: handleChange,
  onError: error => store.status("", error),
});
const thumbnails = createThumbnailManager();
let roomFilter = "";
let previewing = false;
let pendingConfirm = null;
let lowerTab = "props";

const elements = {
  toolbar: document.getElementById("we-toolbar"),
  rooms: document.getElementById("we-rooms"),
  tabs: document.getElementById("we-tabs"),
  boardPane: document.getElementById("we-board-pane"),
  lower: document.getElementById("we-lower"),
  mapGraph: document.getElementById("we-map-graph"),
  systemsPane: document.getElementById("we-systems-pane"),
  systemsContent: document.getElementById("we-systems-content"),
  dialogPanel: document.getElementById("we-dialog-panel"),
  dialogHead: document.getElementById("we-dialog-head"),
  dialogGraph: document.getElementById("we-dialog-graph"),
  properties: document.getElementById("we-properties"),
  validation: document.getElementById("we-validation"),
  modal: document.getElementById("we-modal"),
  toast: document.getElementById("we-toast"),
  editorDock: document.getElementById("we-editor-dock"),
};

const mapView = createGraphView({
  container: elements.mapGraph,
  onSelectNode: id => store.select({ kind: "room", id }),
  onSelectLink: (id, sub) => store.select({ kind: "exit", id, sub }),
  onChange: changes => commitGraph(draft => applyRoomGraphChanges(draft, changes)),
  onMoveNode: (roomId, point) => {
    const x = Math.round(point.x * 100) / 100;
    const y = Math.round(point.y * 100) / 100;
    const room = store.state.draft?.rooms?.[roomId];
    if (!room || (room.editor?.map?.x === x && room.editor?.map?.y === y)) return;
    store.update(draft => {
      const target = draft.rooms?.[roomId];
      if (!target) return;
      if (!target.editor || typeof target.editor !== "object") target.editor = {};
      target.editor.map = { x, y };
    });
  },
});

const selectDialogNode = sub => store.select({ kind: "peep", id: store.state.selection.id, sub });
const dialogView = createGraphView({
  container: elements.dialogGraph,
  onSelectNode: selectDialogNode,
  onSelectLink: selectDialogNode,
  onChange: changes => {
    const peepId = store.state.selection.id;
    commitGraph(draft => applyDialogGraphChanges(draft.peeps?.[peepId]?.dialog, changes));
  },
});

const roomEditor = createWorldRoomEditor(store, currentRoomId);
const dialogs = createDialogs(elements.modal);
const textStore = {
  getState: () => ({ editor: worldRoomEditor(store.state, currentRoomId()) }),
  dispatch: action => roomEditor.dispatch(action),
};
function handleEditorAction(action) {
  if (previewing || dialogs.active || pendingConfirm) return;
  if (action.action === "reset") { store.editorSettings({ resetArmed: true }); return; }
  if (action.action === "reset-cancel") { store.editorSettings({ resetArmed: false }); return; }
  if (action.action === "reset-confirm") { void runResetRoom(); return; }
  const picker = store.state.editorSettings?.picker;
  if (picker && action.type === "edit-add") return replaceSelectedProp(action.propId, picker);
  if (action.action === "add-text") {
    return openTextPropDialog({ dialogs, store: textStore, propId: "builtin:text" });
  }
  if (action.type === "edit-add" && isTextPropId(action.propId)) {
    return openTextPropDialog({ dialogs, store: textStore, propId: action.propId });
  }
  if (action.action === "edit-text") {
    return openTextPropDialog({ dialogs, store: textStore, id: worldRoomEditor(store.state, currentRoomId())?.selectedId });
  }
  roomEditor.onAction(action);
}

function isTextPropId(propId) {
  return (store.state.catalog?.props || []).find(prop => prop.id === propId)?.render_kind === "text"
    || propId === "builtin:text";
}

function replaceSelectedProp(propId, picker) {
  if (isTextPropId(propId)) {
    store.status("Text props cannot replace a prop type.");
    return;
  }
  store.update(draft => {
    const instance = draft.rooms?.[picker.roomId]?.props?.[picker.sub];
    const current = (store.state.catalog?.props || []).find(prop => prop.id === instance?.prop);
    if (instance && (current?.render_kind !== "text" || isTextPropId(propId))) instance.prop = propId;
  });
  store.editorSettings({ picker: null });
  store.select({ kind: "prop", id: picker.roomId, sub: picker.sub });
}

async function runResetRoom() {
  const roomId = currentRoomId();
  if (!roomId) return;
  store.status("Resetting…");
  try {
    await resetRoom(roomId);
    store.editorSettings({ resetArmed: false });
    store.status(`Room '${roomId}' reset to its definition.`);
  } catch (error) {
    store.status("", error.message);
  }
}

const editorDock = createEditorDock({
  root: elements.editorDock,
  authoring: true,
  onAction: handleEditorAction,
});

const boardView = createBoardView({
  canvas: document.getElementById("we-canvas"),
  overlay: document.getElementById("we-overlay"),
  onSelect: selection => store.select(selection),
  onBegin: () => roomEditor.dispatch({ type: "editor-begin" }),
  onTransform: payload => roomEditor.dispatch({ type: "editor-transform", ...payload }),
  onRotate: (delta, gesture) => roomEditor.dispatch({ type: "editor-rotate", delta, gesture }),
  onScale: (factor, gesture) => roomEditor.dispatch({ type: "editor-scale", factor, gesture }),
  onElevate: (delta, gesture) => roomEditor.dispatch({ type: "editor-elevate", delta, gesture }),
});

function currentRoomId() {
  const selection = store.state.selection;
  if (["prop", "card", "room", "exit"].includes(selection.kind)) return selection.id;
  return Object.keys(store.state.draft?.rooms || {})[0] || null;
}

function commitGraph(mutator) {
  const probe = structuredClone(store.state.draft);
  if (mutator(probe)) store.update(mutator);
  else render();
}

function updateInstance(mutator, undoable = true) {
  const { selection } = store.state;
  store.update(draft => {
    const instance = draft.rooms?.[selection.id]?.props?.[selection.sub];
    if (instance) mutator(instance);
  }, { undoable });
}

function render() {
  const state = store.state;
  if (!state.draft) return;
  renderToolbar(state);
  renderTabs(state);
  const quality = roomQualityReport(state.draft, state.catalog);
  elements.rooms.innerHTML = `
    <div class="search-row">
      <input type="search" id="room-search" placeholder="Search rooms" aria-label="Search rooms" value="${escapeHtml(roomFilter)}">
    </div>
    <div id="room-list-host">${renderRoomList(state.draft, state.selection, roomFilter, quality)}</div>
    <button type="button" class="quiet" data-room-add>Add room</button>
  `;
  const roomId = currentRoomId();
  const editor = worldRoomEditor(state, roomId);
  elements.lower.hidden = previewing;
  elements.boardPane.classList.toggle("is-previewing", previewing);
  elements.editorDock.hidden = lowerTab !== "props";
  elements.mapGraph.hidden = lowerTab !== "map";
  for (const button of elements.lower.querySelectorAll("[data-lower-tab]")) {
    button.classList.toggle("is-active", button.dataset.lowerTab === lowerTab);
  }
  elements.lower.querySelector("[data-graph-fit]").hidden = lowerTab !== "map";
  editorDock.render({ editor, room: { canEditRoom: true } });
  boardView.render({
    draft: state.draft,
    catalog: state.catalog,
    worldId: state.catalog?.world_id || state.worldKey,
    roomId,
    selection: state.selection,
    editing: !previewing,
    editor,
  });
  if (state.activeTab === "board" && !previewing && lowerTab === "map") {
    mapView.render({ graph: roomGraph(state.draft), activeId: roomId });
  }
  elements.systemsContent.innerHTML = renderSystems(state);
  renderDialogPanel(state);
  const propertiesScroll = elements.properties.scrollTop;
  elements.properties.innerHTML = (state.activeTab === "board" ? editorSettingsView({ editor }) : "") + renderProperties(state);
  bindEditorControls(elements.properties, handleEditorAction);
  elements.properties.scrollTop = propertiesScroll;
  cardSelector.bind(elements.properties);
  cardSelector.bind(elements.systemsPane);
  elements.validation.innerHTML = renderValidation(state.validation);
  elements.toast.textContent = state.error || state.status || "";
  elements.toast.dataset.kind = state.error ? "error" : "info";
  thumbnails.sync(document);
}

function renderDialogPanel(state) {
  const { selection } = state;
  const peep = selection.kind === "peep" ? state.draft.peeps?.[selection.id] : null;
  elements.dialogPanel.hidden = state.activeTab !== "peeps" || !peep;
  if (elements.dialogPanel.hidden) return;
  const pendingId = document.getElementById("dialog-new-node")?.value || "";
  elements.dialogHead.innerHTML = `
    <strong>Dialog · ${escapeHtml(peep.label || selection.id)}</strong>
    ${peep.dialog ? `
      <input type="text" id="dialog-new-node" placeholder="New node id" aria-label="New node id" value="${escapeHtml(pendingId)}">
      <button type="button" class="quiet" data-dialog-node-add>Add node</button>
      <button type="button" class="quiet" data-graph-fit="dialog">Fit</button>
    ` : '<button type="button" class="quiet" data-dialog-create>Add dialog</button>'}
  `;
  dialogView.render({ graph: dialogGraph(peep.dialog), scope: selection.id, activeId: selection.sub });
}

function draftStatusLabel(state) {
  if (!state.hasDraft) {
    return state.publishedRevision ? `Published r${state.publishedRevision}` : "No published revision";
  }
  if (state.draftMatchesPublished) {
    return `Draft saved · matches published${state.publishedRevision ? ` r${state.publishedRevision}` : ""}`;
  }
  const revision = state.draftInfo?.draft_revision;
  const base = state.draftInfo?.base_published_revision;
  return `Unpublished draft${revision ? ` r${revision}` : ""}${base ? ` · based on r${base}` : ""}`;
}

function renderToolbar(state) {
  const roomId = state.selection.id;
  const draftLabel = draftStatusLabel(state);
  const unpublished = state.hasDraft && !state.draftMatchesPublished;
  const updatedAt = state.draftInfo?.updated_at ? `Last saved ${state.draftInfo.updated_at}` : "";
  elements.toolbar.innerHTML = `
    <div class="toolbar-group">
      <strong class="brand">World Editor</strong>
      <span class="draft-badge${unpublished ? " is-unpublished" : ""}" title="${escapeHtml(updatedAt)}">${escapeHtml(draftLabel)}</span>
      <span class="dirty-marker${state.dirty ? " is-dirty" : ""}">${state.dirty ? "Unsaved changes" : "All changes saved"}</span>
    </div>
    <div class="toolbar-group">
      <button type="button" class="quiet" data-action="undo"${state.undo.length ? "" : " disabled"}>Undo</button>
      <button type="button" class="quiet" data-action="redo"${state.redo.length ? "" : " disabled"}>Redo</button>
      <button type="button" class="quiet" data-action="preview">${previewing ? "Stop preview" : "Preview"}</button>
      <button type="button" class="quiet" data-action="validate">Validate</button>
      <button type="button" class="primary" data-action="save">Save Draft</button>
      <button type="button" class="cancel" data-action="discard">Discard</button>
      <button type="button" class="positive" data-action="publish"${roomId ? "" : " disabled"}>Publish</button>
    </div>
  `;
}

const TABS = ["board", "peeps", "tasks", "recipes", "activities", "environment"];

function renderTabs(state) {
  elements.tabs.innerHTML = TABS.map(tab => `
    <button type="button" class="tab${state.activeTab === tab ? " is-active" : ""}" data-tab="${tab}">${tab[0].toUpperCase()}${tab.slice(1)}</button>
  `).join("");
  elements.boardPane.hidden = state.activeTab !== "board";
  elements.systemsPane.hidden = state.activeTab === "board";
}

function renderSystems(state) {
  switch (state.activeTab) {
    case "peeps":
      return renderPeepsList(state);
    case "tasks":
      return renderTasks(state.draft);
    case "recipes":
      return renderRecipes(state.draft);
    case "activities":
      return renderActivities(state.draft);
    case "environment":
      return renderEnvironment(state.draft);
    default:
      return "";
  }
}

function renderPeepsList(state) {
  const peeps = Object.entries(state.draft.peeps || {});
  return `
    <div class="systems-head">
      <h2>Peeps</h2>
      <button type="button" class="quiet" data-peep-add>Add peep</button>
    </div>
    <div class="room-list">
      ${peeps.map(([peepId, peep]) => `
        <button type="button" class="room-item${state.selection.kind === "peep" && state.selection.id === peepId ? " is-active" : ""}" data-peep-select="${escapeHtml(peepId)}">
          <span class="room-item-label">${escapeHtml(peep.label || peepId)}</span>
          <code class="room-item-id">${escapeHtml(peep.room || "")}</code>
        </button>
      `).join("") || '<p class="empty-state">No peeps.</p>'}
    </div>
  `;
}

function setPath(object, path, value) {
  const parts = path.split(".");
  let cursor = object;
  for (let index = 0; index < parts.length - 1; index += 1) {
    const key = /^\d+$/.test(parts[index]) ? Number(parts[index]) : parts[index];
    cursor = cursor[key];
  }
  const last = parts[parts.length - 1];
  cursor[/^\d+$/.test(last) ? Number(last) : last] = value;
}

function toggleArrayValue(array, value, enabled) {
  const next = new Set(array || []);
  if (enabled) next.add(value);
  else next.delete(value);
  return [...next];
}

function handleChange(target) {
  const dataset = target.dataset;
  if (dataset.roomId !== undefined) return renameRoom(target.value.trim());
  if (dataset.roomField !== undefined) return changeRoomField(dataset.roomField, target);
  if (dataset.roomEditorEnv !== undefined) return changeRoomEnvironment(dataset.roomEditorEnv, target.checked);
  if (dataset.envKey !== undefined) return changeRoomEnvironment(dataset.envKey, target.checked, dataset.envRoom);
  if (dataset.cardField !== undefined) return changeCardField(dataset.cardField, target);
  if (dataset.exitField !== undefined) return changeExitField(dataset.exitField, target);
  if (dataset.instanceField !== undefined) return changeInstanceField(dataset.instanceField, target);
  if (dataset.peepField !== undefined) return changePeepField(dataset.peepField, target);
  if (dataset.dialogNodeText !== undefined) return changeDialogNodeText(dataset.dialogNodeText, target.value);
  if (dataset.dialogChoiceField !== undefined) return changeDialogChoice(dataset.dialogChoiceField, target);
  if (dataset.taskField !== undefined) return changeSystemField("tasks", dataset.taskField, target);
  if (dataset.recipeField !== undefined) return changeSystemField("recipes", dataset.recipeField, target);
  if (dataset.activityField !== undefined) return changeSystemField("activities", dataset.activityField, target);
  return undefined;
}

function renameRoom(newId) {
  if (!newId) return;
  const state = store.state;
  const oldId = state.selection.id;
  if (oldId === newId || state.draft.rooms?.[newId]) return;
  store.update(draft => {
    const room = draft.rooms[oldId];
    if (!room) return;
    draft.rooms[newId] = room;
    delete draft.rooms[oldId];
    if (draft.world.entry_room === oldId) draft.world.entry_room = newId;
    for (const candidate of Object.values(draft.rooms)) {
      for (const exit of Object.values(candidate.exits || {})) {
        if (exit.target === oldId) exit.target = newId;
      }
    }
  });
  store.select({ kind: "room", id: newId });
}

function changeRoomField(fieldName, target) {
  const roomId = store.state.selection.id;
  store.update(draft => {
    const room = draft.rooms?.[roomId];
    if (!room) return;
    if (fieldName === "cards") room.cards = reconcileRoomCards(room.cards, parseCsv(target.value));
    else if (fieldName === "palette") room.palette = parseCsv(target.value);
    else if (fieldName === "dark" || fieldName === "template") room[fieldName] = target.checked;
    else room[fieldName] = target.value;
  });
}

function changeRoomEnvironment(key, enabled, roomId = store.state.selection.id) {
  store.update(draft => {
    const room = draft.rooms?.[roomId];
    if (!room) return;
    if (!room.editor || typeof room.editor !== "object") room.editor = {};
    room.editor.environment = toggleArrayValue(room.editor.environment, key, enabled);
  });
}

function changeCardField(spec, target) {
  const [indexText, fieldName] = spec.split(":");
  const index = Number(indexText);
  const roomId = store.state.selection.id;
  store.update(draft => {
    const cards = draft.rooms?.[roomId]?.cards;
    if (!Array.isArray(cards) || !cards[index]) return;
    const card = cards[index];
    if (fieldName === "card") card.card = target.value;
    else if (fieldName === "quantity") card.quantity = Math.max(1, Number(target.value) || 1);
    else if (fieldName.startsWith("pos.")) {
      if (!Array.isArray(card.pos)) card.pos = [50, 50, 0];
      setPath(card, fieldName, numberOr(target.value, 0));
    }
  });
}

function changeExitField(spec, target) {
  const [exitId, fieldName] = spec.split(":");
  const roomId = store.state.selection.id;
  store.update(draft => {
    const exit = draft.rooms?.[roomId]?.exits?.[exitId];
    if (!exit) return;
    if (fieldName === "locked") exit.locked = target.checked;
    else if (fieldName === "requires") {
      if (target.value) exit.requires = target.value;
      else delete exit.requires;
    } else exit[fieldName] = target.value;
  });
}

function changeInstanceField(fieldName, target) {
  const editor = worldRoomEditor(store.state, currentRoomId());
  if ((fieldName.startsWith("pos.") || fieldName.startsWith("rot.") || fieldName === "scale")
    && editor?.props.find(prop => prop.id === editor.selectedId)?.locked) return;
  if (fieldName === "scale") {
    const selected = editor?.props.find(prop => prop.id === editor.selectedId);
    const entry = selected ? editor.library.find(prop => prop.propId === selected.propId) : null;
    if (!entry?.resizable) return;
  }
  updateInstance(instance => {
    if (fieldName === "prop") {
      if (instance.prop !== "builtin:text" && target.value !== "builtin:text") instance.prop = target.value;
    }
    else if (fieldName === "label") {
      if (target.value.trim()) instance.label = target.value;
      else delete instance.label;
    }
    else if (fieldName === "description") {
      if (target.value.trim()) instance.description = target.value;
      else delete instance.description;
    }
    else if (fieldName === "actions") instance.actions = textToActions(target.value);
    else if (fieldName === "exit_to") {
      if (target.value) instance.exit_to = target.value;
      else delete instance.exit_to;
    }
    else if (fieldName === "draw_weight") instance.draw_weight = parseJson(target.value, {});
    else if (fieldName === "only_missing") {
      if (target.checked) instance.only_missing = true;
      else delete instance.only_missing;
    }
    else if (fieldName === "animation") {
      if (target.value) instance[fieldName] = target.value;
      else delete instance[fieldName];
    } else if (fieldName.startsWith("pos.") || fieldName.startsWith("rot.")) {
      const arrayName = fieldName.startsWith("pos.") ? "pos" : "rot";
      if (!Array.isArray(instance[arrayName])) instance[arrayName] = arrayName === "pos" ? [50, 50, 0] : [0, 0, 0];
      setPath(instance, fieldName, numberOr(target.value, 0));
    } else if (fieldName === "scale") instance.scale = Math.max(0.05, numberOr(target.value, 1));
  });
}

function changePeepField(fieldName, target) {
  const peepId = store.state.selection.id;
  store.update(draft => {
    const peep = draft.peeps?.[peepId];
    if (!peep) return;
    if (fieldName === "actions") peep.actions = textToActions(target.value);
    else if (fieldName === "activity") {
      if (target.value) peep.activity = target.value;
      else delete peep.activity;
    } else peep[fieldName] = target.value;
  });
}

function dialogNodes(draft, peepId) {
  const peep = draft.peeps?.[peepId];
  if (!peep) return null;
  if (!peep.dialog || typeof peep.dialog !== "object") peep.dialog = {};
  return peep.dialog;
}

function changeDialogNodeText(nodeId, value) {
  const peepId = store.state.selection.id;
  store.update(draft => {
    const dialog = dialogNodes(draft, peepId);
    if (!dialog) return;
    if (!dialog[nodeId] || typeof dialog[nodeId] !== "object") dialog[nodeId] = { text: "", choices: [] };
    dialog[nodeId].text = value;
  });
}

function changeDialogChoice(spec, target) {
  const [nodeId, indexText, fieldName] = spec.split(":");
  const index = Number(indexText);
  const peepId = store.state.selection.id;
  store.update(draft => {
    const dialog = dialogNodes(draft, peepId);
    const choice = dialog?.[nodeId]?.choices?.[index];
    if (!choice) return;
    if (fieldName === "next") {
      if (target.value) {
        delete choice.end;
        choice.next = target.value;
      } else {
        delete choice.next;
        choice.end = true;
      }
    } else if (fieldName === "grant") {
      const grant = Number(target.value) || 0;
      if (grant) choice.grant = grant;
      else delete choice.grant;
    } else if (fieldName === "when") {
      const parsed = parseJson(target.value, null);
      if (parsed && typeof parsed === "object") choice.when = parsed;
      else delete choice.when;
    } else if (target.value) {
      choice[fieldName] = target.value;
    } else {
      delete choice[fieldName];
    }
  });
}

function changeSystemField(section, spec, target) {
  const [itemId, fieldName] = spec.split(":");
  store.update(draft => {
    const item = draft[section]?.[itemId];
    if (!item) return;
    if (fieldName === "steps") item.steps = parseJson(target.value, []);
    else if (fieldName === "ingredients" || fieldName === "output") item[fieldName] = parseJson(target.value, {});
    else if (fieldName === "memory_tags" || fieldName === "rooms" || fieldName === "aliases") item[fieldName] = parseCsv(target.value);
    else if (fieldName === "reward.cards") {
      if (!item.reward || typeof item.reward !== "object") item.reward = {};
      item.reward.cards = parseCsv(target.value);
    } else if (fieldName === "reward.kudos") {
      if (!item.reward || typeof item.reward !== "object") item.reward = {};
      item.reward.kudos = Number(target.value) || 0;
    }     else if (fieldName === "revision" || fieldName === "energy_cost") item[fieldName] = Number(target.value) || 0;
    else item[fieldName] = target.value;
  });
}

function handleClick(target) {
  const dataset = target.dataset;
  if (dataset.action) return handleAction(dataset.action);
  if (dataset.propPick !== undefined) {
    const { kind, id, sub } = store.state.selection;
    if (kind === "prop" && sub) store.editorSettings({ picker: { roomId: id, sub } });
    return;
  }
  if (dataset.propPickCancel !== undefined) return store.editorSettings({ picker: null });
  if (dataset.tab) return store.activeTab(dataset.tab);
  if (dataset.room !== undefined) return store.select({ kind: "room", id: dataset.room });
  if (dataset.roomAdd !== undefined) return addRoom();
  if (dataset.roomDelete !== undefined) return deleteRoom(dataset.roomDelete);
  if (dataset.cardAdd !== undefined) return addCard();
  if (dataset.cardDelete !== undefined) return deleteCard(Number(dataset.cardDelete));
  if (dataset.exitAdd !== undefined) return addExit();
  if (dataset.exitDelete !== undefined) return deleteExit(dataset.exitDelete);
  if (dataset.propAdd !== undefined) return addProp(dataset.propAdd);
  if (dataset.instanceDelete !== undefined) return deleteInstance();
  if (dataset.peepAdd !== undefined) return addPeep();
  if (dataset.peepDelete !== undefined) return deletePeep();
  if (dataset.peepSelect !== undefined) return store.select({ kind: "peep", id: dataset.peepSelect });
  if (dataset.dialogNodeAdd !== undefined) return addDialogNode();
  if (dataset.dialogCreate !== undefined) return createDialog();
  if (dataset.dialogNodeDelete !== undefined) return deleteDialogNode(dataset.dialogNodeDelete);
  if (dataset.dialogChoiceAdd !== undefined) return addDialogChoice(dataset.dialogChoiceAdd);
  if (dataset.dialogChoiceDelete !== undefined) return deleteDialogChoice(dataset.dialogChoiceDelete);
  if (dataset.taskAdd !== undefined) return addSystemItem("tasks", { title: "New task", scope: "personal", steps: [] });
  if (dataset.taskDelete !== undefined) return deleteSystemItem("tasks", dataset.taskDelete);
  if (dataset.recipeAdd !== undefined) return addSystemItem("recipes", { label: "New recipe", ingredients: {}, output: {} });
  if (dataset.recipeDelete !== undefined) return deleteSystemItem("recipes", dataset.recipeDelete);
  if (dataset.activityAdd !== undefined) return addSystemItem("activities", { title: "New activity" });
  if (dataset.activityDelete !== undefined) return deleteSystemItem("activities", dataset.activityDelete);
  if (dataset.lowerTab !== undefined) {
    lowerTab = dataset.lowerTab;
    return render();
  }
  if (dataset.graphFit !== undefined) return (dataset.graphFit === "map" ? mapView : dialogView).fit();
  if (dataset.confirmPublish !== undefined) return confirmPublish();
  if (dataset.cancelPublish !== undefined) {
    pendingConfirm = null;
    elements.modal.innerHTML = "";
    return undefined;
  }
  return undefined;
}

function firstRoomId() {
  return Object.keys(store.state.draft?.rooms || {})[0] || null;
}

function addRoom() {
  const id = uniqueId(Object.keys(store.state.draft.rooms || {}), "room");
  store.update(draft => {
    draft.rooms[id] = {
      label: "New Room",
      description: "",
      board_type: "basic",
      board_image: store.state.catalog?.board_images?.[0] || "",
      board_image_style: "stretch",
      palette: [],
      editor: { environment: ["palette", "board_image_style"] },
      props: {},
      exits: {},
    };
  });
  store.select({ kind: "room", id });
}

function deleteRoom(roomId) {
  store.update(draft => removeRoom(draft, roomId));
  store.select({ kind: "room", id: firstRoomId() });
}

function addCard() {
  const roomId = store.state.selection.id;
  store.update(draft => {
    const room = draft.rooms?.[roomId];
    if (!room) return;
    if (!Array.isArray(room.cards)) room.cards = [];
    room.cards.push({ card: store.state.catalog?.cards?.[0]?.id || "", quantity: 1, pos: [50, 50, 0] });
  });
}

function deleteCard(index) {
  const roomId = store.state.selection.id;
  store.update(draft => {
    const room = draft.rooms?.[roomId];
    if (room && Array.isArray(room.cards)) room.cards.splice(index, 1);
  });
  store.select({ kind: "room", id: roomId });
}

function addExit() {
  const roomId = store.state.selection.id;
  const rooms = Object.keys(store.state.draft.rooms || {});
  store.update(draft => {
    const room = draft.rooms?.[roomId];
    if (!room) return;
    if (!room.exits) room.exits = {};
    const id = uniqueId(Object.keys(room.exits), "exit");
    room.exits[id] = { label: "New exit", target: rooms[0] || roomId };
  });
}

function deleteExit(exitId) {
  const roomId = store.state.selection.id;
  store.update(draft => {
    const room = draft.rooms?.[roomId];
    if (room?.exits) delete room.exits[exitId];
    for (const instance of Object.values(room?.props || {})) {
      if (instance?.exit_to === exitId) delete instance.exit_to;
    }
  });
  store.select({ kind: "room", id: roomId });
}

function addProp(propId) {
  handleEditorAction({ type: "edit-add", propId });
}

function deleteInstance() {
  const { selection } = store.state;
  store.update(draft => {
    const room = draft.rooms?.[selection.id];
    if (room?.props) delete room.props[selection.sub];
  });
  store.select({ kind: "room", id: selection.id });
}

function addPeep() {
  const id = uniqueId(Object.keys(store.state.draft.peeps || {}), "peep");
  const rooms = Object.keys(store.state.draft.rooms || {});
  store.update(draft => {
    if (!draft.peeps) draft.peeps = {};
    draft.peeps[id] = {
      label: "New Peep",
      description: "",
      room: rooms[0] || "",
      image: store.state.catalog?.peep_images?.[0] || "",
      actions: [],
    };
  });
  store.select({ kind: "peep", id });
}

function deletePeep() {
  const { selection } = store.state;
  store.update(draft => {
    if (draft.peeps) delete draft.peeps[selection.id];
  });
  store.select({ kind: "room", id: firstRoomId() });
}

function addDialogNode() {
  const input = document.getElementById("dialog-new-node");
  const nodeId = (input?.value || "").trim();
  const peepId = store.state.selection.id;
  if (!nodeId || store.state.draft.peeps?.[peepId]?.dialog?.[nodeId]) return;
  input.value = "";
  store.update(draft => {
    const dialog = dialogNodes(draft, peepId);
    if (dialog) dialog[nodeId] = { text: "", choices: [] };
  });
  store.select({ kind: "peep", id: peepId, sub: nodeId });
}

function createDialog() {
  const peepId = store.state.selection.id;
  store.update(draft => {
    const dialog = dialogNodes(draft, peepId);
    if (dialog && !dialog.start) dialog.start = { text: "Hello!", choices: [] };
  });
  store.select({ kind: "peep", id: peepId, sub: "start" });
}

function deleteDialogNode(nodeId) {
  const peepId = store.state.selection.id;
  store.update(draft => applyDialogGraphChanges(draft.peeps?.[peepId]?.dialog, [{ type: "remove", node: nodeId }]));
  store.select({ kind: "peep", id: peepId });
}

function addDialogChoice(nodeId) {
  const peepId = store.state.selection.id;
  store.update(draft => {
    const node = dialogNodes(draft, peepId)?.[nodeId];
    if (!node) return;
    if (!Array.isArray(node.choices)) node.choices = [];
    node.choices.push({ label: "Choice", end: true });
  });
}

function deleteDialogChoice(spec) {
  const [nodeId, indexText] = spec.split(":");
  const peepId = store.state.selection.id;
  store.update(draft => {
    const node = dialogNodes(draft, peepId)?.[nodeId];
    if (node && Array.isArray(node.choices)) node.choices.splice(Number(indexText), 1);
  });
}

function addSystemItem(section, value) {
  store.update(draft => {
    if (!draft[section] || typeof draft[section] !== "object") draft[section] = {};
    const id = uniqueId(Object.keys(draft[section]), section.slice(0, -1) || "item");
    draft[section][id] = value;
  });
}

function deleteSystemItem(section, itemId) {
  store.update(draft => {
    if (draft[section]) delete draft[section][itemId];
  });
}

async function handleAction(action) {
  if (action === "undo") return store.undo();
  if (action === "redo") return store.redo();
  if (action === "preview") {
    previewing = !previewing;
    return render();
  }
  if (action === "validate") return runValidate();
  if (action === "save") return runSave();
  if (action === "discard") return runDiscard();
  if (action === "publish") return runPublish();
  return undefined;
}

async function runValidate() {
  store.status("Validating…");
  try {
    const body = await validateDraft(store.state.draft);
    store.validation(body.report);
    store.status(body.report.valid ? "Draft is valid." : `${body.report.errors.length} validation error(s).`);
    store.activeTab("board");
  } catch (error) {
    store.status("", error.message);
  }
}

async function runSave() {
  store.status("Saving…");
  try {
    const body = await saveDraft(store.state.draft);
    store.saved(body.draft, {
      draftInfo: body.info,
      draftMatchesPublished: Boolean(body.draft_matches_published),
    });
    store.status(`Draft revision ${body.info.draft_revision} saved.`);
  } catch (error) {
    store.status("", error.message);
  }
}

async function runDiscard() {
  if (!window.confirm("Discard the saved draft and rebuild it from the published files?")) return;
  try {
    const body = await discardDraft();
    store.discarded(body.draft);
    store.status("Draft discarded.");
  } catch (error) {
    store.status("", error.message);
  }
}

async function runPublish() {
  store.status("Publishing…");
  try {
    const body = await publishDraft(store.state.draft, false);
    await finishPublish(body);
  } catch (error) {
    if (error.status === 409 && error.body?.changes) {
      pendingConfirm = { draft: store.state.draft };
      showConfirm(error.body);
      store.status("Destructive changes need confirmation.");
      return;
    }
    store.status("", error.message);
  }
}

async function confirmPublish() {
  if (!pendingConfirm) return;
  const { draft } = pendingConfirm;
  elements.modal.innerHTML = "";
  try {
    const body = await publishDraft(draft, true);
    await finishPublish(body);
  } catch (error) {
    store.status("", error.message);
  } finally {
    pendingConfirm = null;
  }
}

async function finishPublish(body) {
  await refresh();
  store.status(`Published revision ${body.result.revision}.`);
}

function showConfirm(body) {
  const rooms = Array.isArray(body.rooms) ? body.rooms : [];
  elements.modal.innerHTML = `
    <div class="modal-card" role="dialog" aria-modal="true" aria-label="Confirm publish">
      <h2>Confirm destructive changes</h2>
      <p>Saving will apply destructive changes to ${rooms.length} room(s):</p>
      <p class="modal-rooms">${rooms.map(room => `<code>${escapeHtml(room)}</code>`).join(" ")}</p>
      <ul class="validation-list">
        ${(body.changes || []).map(change => `<li><code>${escapeHtml(change.kind)}</code><span>${escapeHtml(change.summary)}</span></li>`).join("")}
      </ul>
      <div class="dialog-actions">
        <button type="button" class="cancel" data-cancel-publish>Cancel</button>
        <button type="button" class="positive" data-confirm-publish>Save anyway</button>
      </div>
    </div>
  `;
}

async function refresh() {
  dialogs.closeAll();
  const body = await loadDraft();
  store.init({
    draft: body.draft,
    catalog: body.catalog,
    worldKey: body.world_key,
    publishedRevision: body.published_revision,
    hasDraft: Boolean(body.has_draft),
    draftInfo: body.draft_info || null,
    draftMatchesPublished: Boolean(body.draft_matches_published),
  });
  const roomId = firstRoomId();
  if (roomId) store.select({ kind: "room", id: roomId });
}

document.addEventListener("change", event => {
  const target = event.target;
  if (target && target.dataset && Object.keys(target.dataset).length) handleChange(target);
});

document.addEventListener("click", event => {
  const target = event.target.closest("[data-action],[data-prop-pick],[data-prop-pick-cancel],[data-tab],[data-room],[data-room-add],[data-room-delete],[data-card-add],[data-card-delete],[data-exit-add],[data-exit-delete],[data-prop-add],[data-instance-delete],[data-peep-add],[data-peep-delete],[data-peep-select],[data-dialog-node-add],[data-dialog-node-delete],[data-dialog-choice-add],[data-dialog-choice-delete],[data-task-add],[data-task-delete],[data-recipe-add],[data-recipe-delete],[data-activity-add],[data-activity-delete],[data-lower-tab],[data-graph-fit],[data-dialog-create],[data-confirm-publish],[data-cancel-publish]");
  if (!target) return;
  if (target.dataset.room !== undefined && target.dataset.roomAdd === undefined && target.dataset.roomDelete === undefined) {
    store.select({ kind: "room", id: target.dataset.room });
    return;
  }
  handleClick(target);
});

document.addEventListener("input", event => {
  if (event.target?.id === "room-search") {
    roomFilter = event.target.value;
    const host = document.getElementById("room-list-host");
    if (host) host.innerHTML = renderRoomList(store.state.draft, store.state.selection, roomFilter, roomQualityReport(store.state.draft, store.state.catalog));
  }
});

document.addEventListener("keydown", event => {
  if (dialogs.active) {
    if (event.key === "Escape") { event.preventDefault(); dialogs.cancel(); }
    return;
  }
  const modifier = event.ctrlKey || event.metaKey;
  if (event.defaultPrevented || event.target.closest("input,textarea,select,[contenteditable=true]")) return;
  if (!modifier) {
    if (previewing || store.state.activeTab !== "board" || event.target.closest(".we-graph")) return;
    const editor = worldRoomEditor(store.state, currentRoomId());
    const action = editorKeyAction(event, editor);
    if (action) { event.preventDefault(); roomEditor.dispatch(action); }
    return;
  }
  if (event.key.toLowerCase() === "z" && !event.shiftKey) {
    event.preventDefault();
    store.undo();
  } else if ((event.key.toLowerCase() === "z" && event.shiftKey) || event.key.toLowerCase() === "y") {
    event.preventDefault();
    store.redo();
  } else if (event.key.toLowerCase() === "s") {
    event.preventDefault();
    runSave();
  }
});

store.subscribe(render);
bindPanelSplitters(document.querySelector(".we-stage"));

async function boot() {
  try {
    await loadSession();
    await refresh();
  } catch (error) {
    elements.toast.textContent = `Could not load the editor: ${error.message}`;
    elements.toast.dataset.kind = "error";
  }
}

boot();
