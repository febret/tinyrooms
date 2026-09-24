import {
  discardDraft,
  loadDraft,
  loadSession,
  publishDraft,
  saveDraft,
  validateDraft,
} from "./api.js";
import { createBoardView } from "./board-view.js";
import { createStore } from "./store.js";
import { escapeHtml, parseCsv, parseJson, numberOr, textToActions } from "./util.js";
import { renderWorldMap } from "./world-map.js";
import { renderRoomList } from "./panels/rooms.js";
import { renderProperties } from "./panels/properties.js";
import { renderValidation } from "./panels/validation.js";
import {
  renderActivities,
  renderEnvironment,
  renderRecipes,
  renderTasks,
} from "./panels/systems.js";
import { createThumbnailManager } from "/app/js/editing/prop-thumbnails.js";

const store = createStore();
const thumbnails = createThumbnailManager();
let roomFilter = "";
let previewing = false;
let pendingConfirm = null;

const elements = {
  toolbar: document.getElementById("we-toolbar"),
  rooms: document.getElementById("we-rooms"),
  tabs: document.getElementById("we-tabs"),
  boardPane: document.getElementById("we-board-pane"),
  mapPane: document.getElementById("we-map-pane"),
  systemsPane: document.getElementById("we-systems-pane"),
  properties: document.getElementById("we-properties"),
  validation: document.getElementById("we-validation"),
  modal: document.getElementById("we-modal"),
  toast: document.getElementById("we-toast"),
};

const boardView = createBoardView({
  canvas: document.getElementById("we-canvas"),
  overlay: document.getElementById("we-overlay"),
  onSelect: selection => {
    if (selection.kind === "prop" && selection.id) store.select({ kind: "prop", id: selection.id });
    else store.select({ kind: "room", id: currentRoomId() });
  },
  onBegin: () => store.beginGesture(),
  onTransform: payload => updateInstance(instance => {
    instance.pos = [payload.position[0], payload.position[1], instance.pos?.[2] ?? 0];
  }, false),
  onRotate: delta => updateInstance(instance => {
    const rotation = Array.isArray(instance.rot) ? instance.rot : [0, 0, 0];
    instance.rot = [rotation[0] || 0, ((rotation[1] || 0) + delta) % 360, rotation[2] || 0];
  }),
  onScale: factor => updateInstance(instance => {
    instance.scale = Math.max(0.05, numberOr(instance.scale, 1) * factor);
  }),
});

function currentRoomId() {
  const selection = store.state.selection;
  if (selection.kind === "prop" || selection.kind === "card") return selection.id;
  if (selection.kind === "room") return selection.id;
  return Object.keys(store.state.draft?.rooms || {})[0] || null;
}

function currentInstance() {
  const { selection, draft } = store.state;
  return draft?.rooms?.[selection.id]?.props?.[selection.sub] || null;
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
  elements.rooms.innerHTML = `
    <div class="search-row">
      <input type="search" id="room-search" placeholder="Search rooms" aria-label="Search rooms" value="${escapeHtml(roomFilter)}">
    </div>
    <div id="room-list-host">${renderRoomList(state.draft, state.selection, roomFilter)}</div>
    <button type="button" class="quiet" data-room-add>Add room</button>
  `;
  const roomId = currentRoomId();
  boardView.render({
    draft: state.draft,
    catalog: state.catalog,
    worldId: state.catalog?.world_id || state.worldKey,
    roomId,
    selection: state.selection,
    editing: !previewing,
  });
  elements.mapPane.innerHTML = state.activeTab === "map" ? renderWorldMap(state.draft, state.selection) : "";
  elements.systemsPane.innerHTML = renderSystems(state);
  elements.properties.innerHTML = renderProperties(state);
  elements.validation.innerHTML = renderValidation(state.validation);
  elements.toast.textContent = state.error || state.status || "";
  elements.toast.dataset.kind = state.error ? "error" : "info";
  thumbnails.sync(document);
}

function renderToolbar(state) {
  const roomId = state.selection.id;
  elements.toolbar.innerHTML = `
    <div class="toolbar-group">
      <strong class="brand">World Editor</strong>
      <span class="dirty-marker${state.dirty ? " is-dirty" : ""}">${state.dirty ? "Unsaved changes" : "Saved"}</span>
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

const TABS = ["board", "map", "peeps", "tasks", "recipes", "activities", "environment"];

function renderTabs(state) {
  elements.tabs.innerHTML = TABS.map(tab => `
    <button type="button" class="tab${state.activeTab === tab ? " is-active" : ""}" data-tab="${tab}">${tab[0].toUpperCase()}${tab.slice(1)}</button>
  `).join("");
  elements.boardPane.hidden = state.activeTab !== "board";
  elements.mapPane.hidden = state.activeTab !== "map";
  elements.systemsPane.hidden = !["peeps", "tasks", "recipes", "activities", "environment"].includes(state.activeTab);
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

function uniqueId(existing, base) {
  let index = 1;
  let candidate = `${base}-${index}`;
  while (existing.includes(candidate)) {
    index += 1;
    candidate = `${base}-${index}`;
  }
  return candidate;
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

function getPath(object, path) {
  return path.split(".").reduce((cursor, key) => {
    if (cursor == null) return undefined;
    return cursor[/^\d+$/.test(key) ? Number(key) : key];
  }, object);
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
  if (dataset.cardField !== undefined) return changeCardField(dataset.cardField, target);
  if (dataset.exitField !== undefined) return changeExitField(dataset.exitField, target);
  if (dataset.instanceField !== undefined) return changeInstanceField(dataset.instanceField, target);
  if (dataset.peepField !== undefined) return changePeepField(dataset.peepField, target);
  if (dataset.dialogNodeText !== undefined) return changeDialogNodeText(dataset.dialogNodeText, target.value);
  if (dataset.dialogChoiceField !== undefined) return changeDialogChoice(dataset.dialogChoiceField, target);
  if (dataset.taskField !== undefined) return changeSystemField("tasks", dataset.taskField, target);
  if (dataset.recipeField !== undefined) return changeSystemField("recipes", dataset.recipeField, target);
  if (dataset.activityField !== undefined) return changeSystemField("activities", dataset.activityField, target);
  if (dataset.envAura !== undefined) return changeRoomAura(dataset.envAura, target.value);
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
    if (fieldName === "palette") room.palette = parseCsv(target.value);
    else if (fieldName === "aura") room.aura = parseJson(target.value, []);
    else if (fieldName === "dark" || fieldName === "template") room[fieldName] = target.checked;
    else room[fieldName] = target.value;
  });
}

function changeRoomEnvironment(key, enabled) {
  const roomId = store.state.selection.id;
  store.update(draft => {
    const room = draft.rooms?.[roomId];
    if (!room) return;
    if (!room.editor || typeof room.editor !== "object") room.editor = {};
    room.editor.environment = toggleArrayValue(room.editor.environment, key, enabled);
  });
}

function changeRoomAura(roomId, value) {
  store.update(draft => {
    const room = draft.rooms?.[roomId];
    if (room) room.aura = parseJson(value, []);
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
  updateInstance(instance => {
    if (fieldName === "prop") instance.prop = target.value;
    else if (fieldName === "content") instance.content = parseCsv(target.value);
    else if (fieldName === "recipes") instance.recipes = parseCsv(target.value);
    else if (fieldName === "actions") instance.actions = textToActions(target.value);
    else if (fieldName === "draw_weight") instance.draw_weight = parseJson(target.value, {});
    else if (fieldName === "behavior" || fieldName === "animation" || fieldName === "activity") {
      if (target.value) instance[fieldName] = target.value;
      else delete instance[fieldName];
    } else if (fieldName.startsWith("pos.") || fieldName.startsWith("rot.")) {
      const arrayName = fieldName.startsWith("pos.") ? "pos" : "rot";
      if (!Array.isArray(instance[arrayName])) instance[arrayName] = arrayName === "pos" ? [50, 50, 0] : [0, 0, 0];
      setPath(instance, fieldName, numberOr(target.value, 0));
    } else if (fieldName === "cooldown") {
      if (target.value === "") delete instance.cooldown;
      else instance.cooldown = Math.max(0, Number(target.value) || 0);
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
    if (fieldName === "end") {
      if (target.checked) {
        choice.end = true;
        delete choice.next;
      } else {
        delete choice.end;
      }
    } else if (fieldName === "grant") {
      choice.grant = Number(target.value) || 0;
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
    } else if (fieldName === "revision" || fieldName === "energy_cost") item[fieldName] = Number(target.value) || 0;
    else if (fieldName === "room_bound") item.room_bound = target.checked;
    else item[fieldName] = target.value;
  });
}

function handleClick(target) {
  const dataset = target.dataset;
  if (dataset.action) return handleAction(dataset.action);
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
  if (dataset.dialogNodeDelete !== undefined) return deleteDialogNode(dataset.dialogNodeDelete);
  if (dataset.dialogChoiceAdd !== undefined) return addDialogChoice(dataset.dialogChoiceAdd);
  if (dataset.dialogChoiceDelete !== undefined) return deleteDialogChoice(dataset.dialogChoiceDelete);
  if (dataset.taskAdd !== undefined) return addSystemItem("tasks", { title: "New task", scope: "personal", steps: [] });
  if (dataset.taskDelete !== undefined) return deleteSystemItem("tasks", dataset.taskDelete);
  if (dataset.recipeAdd !== undefined) return addSystemItem("recipes", { label: "New recipe", ingredients: {}, output: {} });
  if (dataset.recipeDelete !== undefined) return deleteSystemItem("recipes", dataset.recipeDelete);
  if (dataset.activityAdd !== undefined) return addSystemItem("activities", { title: "New activity", room_bound: true });
  if (dataset.activityDelete !== undefined) return deleteSystemItem("activities", dataset.activityDelete);
  if (dataset.mapRoom !== undefined) return store.select({ kind: "room", id: dataset.mapRoom });
  if (dataset.mapExit !== undefined) {
    const [roomId, exitId] = dataset.mapExit.split(":");
    return store.select({ kind: "exit", id: roomId, sub: exitId });
  }
  if (dataset.envRoom !== undefined) return undefined;
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
  store.update(draft => {
    delete draft.rooms[roomId];
    for (const room of Object.values(draft.rooms)) {
      for (const [exitId, exit] of Object.entries(room.exits || {})) {
        if (exit.target === roomId) delete room.exits[exitId];
      }
    }
    if (draft.world.entry_room === roomId) draft.world.entry_room = firstRoomId() || "";
  });
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
  });
  store.select({ kind: "room", id: roomId });
}

function addProp(propId) {
  const roomId = store.state.selection.id;
  const definition = (store.state.catalog?.props || []).find(prop => prop.id === propId);
  const existing = Object.keys(store.state.draft.rooms?.[roomId]?.props || {});
  const instanceId = uniqueId(existing, propId);
  store.update(draft => {
    const room = draft.rooms?.[roomId];
    if (!room) return;
    if (!room.props) room.props = {};
    room.props[instanceId] = { prop: propId, pos: [50, 50, 0], rot: [0, 0, 0], scale: definition?.scale ?? 1 };
  });
  store.select({ kind: "prop", id: roomId, sub: instanceId });
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
  if (!nodeId) return;
  const peepId = store.state.selection.id;
  store.update(draft => {
    const dialog = dialogNodes(draft, peepId);
    if (dialog && !dialog[nodeId]) dialog[nodeId] = { text: "", choices: [] };
  });
}

function deleteDialogNode(nodeId) {
  const peepId = store.state.selection.id;
  store.update(draft => {
    const dialog = dialogNodes(draft, peepId);
    if (dialog) delete dialog[nodeId];
  });
}

function addDialogChoice(nodeId) {
  const peepId = store.state.selection.id;
  store.update(draft => {
    const node = dialogNodes(draft, peepId)?.[nodeId];
    if (!node) return;
    if (!Array.isArray(node.choices)) node.choices = [];
    node.choices.push({ label: "Choice", next: "start" });
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
    store.saved(body.draft);
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
  const body = await loadDraft();
  store.init({
    draft: body.draft,
    catalog: body.catalog,
    worldKey: body.world_key,
    publishedRevision: body.published_revision,
  });
  const roomId = firstRoomId();
  if (roomId) store.select({ kind: "room", id: roomId });
}

document.addEventListener("change", event => {
  const target = event.target;
  if (target && target.dataset && Object.keys(target.dataset).length) handleChange(target);
});

document.addEventListener("click", event => {
  const target = event.target.closest("[data-action],[data-tab],[data-room],[data-room-add],[data-room-delete],[data-card-add],[data-card-delete],[data-exit-add],[data-exit-delete],[data-prop-add],[data-instance-delete],[data-peep-add],[data-peep-delete],[data-peep-select],[data-dialog-node-add],[data-dialog-node-delete],[data-dialog-choice-add],[data-dialog-choice-delete],[data-task-add],[data-task-delete],[data-recipe-add],[data-recipe-delete],[data-activity-add],[data-activity-delete],[data-map-room],[data-map-exit],[data-confirm-publish],[data-cancel-publish]");
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
    if (host) host.innerHTML = renderRoomList(store.state.draft, store.state.selection, roomFilter);
  }
});

document.addEventListener("keydown", event => {
  const modifier = event.ctrlKey || event.metaKey;
  if (!modifier) return;
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
