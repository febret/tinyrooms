import { escapeHtml, selectOptions, actionsToText } from "../util.js";
import { renderDialogEditor } from "./dialog.js";

function field(label, input) {
  return `<label class="field"><span>${escapeHtml(label)}</span>${input}</label>`;
}

function textInput(value, attrs, placeholder = "") {
  return `<input type="text" ${attrs} value="${escapeHtml(value ?? "")}" placeholder="${escapeHtml(placeholder)}">`;
}

function numberInput(value, attrs, step = "0.05") {
  return `<input type="number" ${attrs} step="${step}" value="${escapeHtml(value ?? 0)}">`;
}

function textarea(value, attrs, rows = 3) {
  return `<textarea ${attrs} rows="${rows}">${escapeHtml(value ?? "")}</textarea>`;
}

function checkbox(checked, attrs) {
  return `<input type="checkbox" ${attrs}${checked ? " checked" : ""}>`;
}

function panelHeader(title, subtitle) {
  return `<header class="properties-head"><h2>${escapeHtml(title)}</h2><p>${escapeHtml(subtitle || "")}</p></header>`;
}

function roomPanel(state) {
  const { draft, catalog, selection } = state;
  const roomId = selection.id;
  const room = draft.rooms?.[roomId];
  if (!room) return '<p class="empty-state">Select a room.</p>';
  const environment = room.editor && Array.isArray(room.editor.environment) ? room.editor.environment : [];
  const initialCards = Array.isArray(room.cards) ? room.cards : [];
  const exits = Object.entries(room.exits || {});
  const cards = (catalog?.cards || []).map(card => ({ value: card.id, label: `${card.label} (${card.id})` }));
  const roomOptions = Object.keys(draft.rooms || {}).map(id => ({ value: id, label: id }));
  return `
    ${panelHeader(room.label || roomId, `Room · ${roomId}`)}
    <div class="properties-body">
      ${field("Room id", textInput(roomId, `data-room-id`, "room-id"))}
      ${field("Label", textInput(room.label, `data-room-field="label"`))}
      ${field("Description", textarea(room.description, `data-room-field="description"`, 3))}
      ${field("Board type", textInput(room.board_type || "basic", `data-room-field="board_type"`))}
      ${field("Board image", `<select data-room-field="board_image">${selectOptions(catalog?.board_images || [], room.board_image)}</select>`)}
      ${field("Board image style", `<select data-room-field="board_image_style">${selectOptions(catalog?.board_image_styles || [], room.board_image_style || "stretch")}</select>`)}
      ${field("Palette (comma-separated hex)", textInput((room.palette || []).join(", "), `data-room-field="palette"`))}
      <div class="field-row">
        <label class="mini-check">${checkbox(Boolean(room.dark), `data-room-field="dark"`)} dark</label>
        <label class="mini-check">${checkbox(Boolean(room.template), `data-room-field="template"`)} template</label>
      </div>
      <fieldset class="subgroup">
        <legend>Editor environment whitelist</legend>
        <label class="mini-check">${checkbox(environment.includes("palette"), `data-room-editor-env="palette"`)} palette</label>
        <label class="mini-check">${checkbox(environment.includes("board_image_style"), `data-room-editor-env="board_image_style"`)} board_image_style</label>
      </fieldset>
      ${field("Aura (JSON list)", textarea(JSON.stringify(room.aura || []), `data-room-field="aura"`, 3))}
      <fieldset class="subgroup">
        <legend>Initial room cards</legend>
        ${initialCards.map((card, index) => `
          <div class="list-row">
            <select data-card-field="${index}:card">${selectOptions(cards, card.card)}</select>
            <input type="number" data-card-field="${index}:quantity" min="1" value="${escapeHtml(card.quantity ?? 1)}" aria-label="Quantity">
            <button type="button" class="icon-button" data-card-delete="${index}" aria-label="Delete card">✕</button>
          </div>
        `).join("") || '<p class="empty-state">No initial cards.</p>'}
        <button type="button" class="quiet" data-card-add>Add card</button>
      </fieldset>
      <fieldset class="subgroup">
        <legend>Exits</legend>
        ${exits.map(([exitId, exit]) => `
          <div class="list-row">
            <code>${escapeHtml(exitId)}</code>
            <input type="text" data-exit-field="${escapeHtml(exitId)}:label" value="${escapeHtml(exit.label || "")}" placeholder="Label" aria-label="Exit label">
            <select data-exit-field="${escapeHtml(exitId)}:target">${selectOptions(roomOptions, exit.target)}</select>
            <label class="mini-check">${checkbox(Boolean(exit.locked), `data-exit-field="${escapeHtml(exitId)}:locked"`)} locked</label>
            <button type="button" class="icon-button" data-exit-delete="${escapeHtml(exitId)}" aria-label="Delete exit">✕</button>
          </div>
        `).join("") || '<p class="empty-state">No exits.</p>'}
        <button type="button" class="quiet" data-exit-add>Add exit</button>
      </fieldset>
      <fieldset class="subgroup">
        <legend>Prop library</legend>
        <div class="prop-library" role="list">
          ${(catalog?.props || []).map(prop => `
            <button type="button" class="prop-tile" role="listitem" data-prop-add="${escapeHtml(prop.id)}" title="${escapeHtml(prop.label)}">
              <img data-thumb-model="${escapeHtml(prop.model_url)}" data-thumb-scale="${escapeHtml(prop.scale)}" alt="" aria-hidden="true">
              <span>${escapeHtml(prop.label)}</span>
            </button>
          `).join("")}
        </div>
      </fieldset>
      <button type="button" class="negative" data-room-delete="${escapeHtml(roomId)}">Delete room</button>
    </div>
  `;
}

function propPanel(state) {
  const { draft, catalog, selection } = state;
  const room = draft.rooms?.[selection.id];
  const instance = room?.props?.[selection.sub];
  if (!room || !instance) return '<p class="empty-state">Select a prop on the board.</p>';
  const propId = selection.sub;
  const position = Array.isArray(instance.pos) ? instance.pos : [50, 50, 0];
  const rotation = Array.isArray(instance.rot) ? instance.rot : [0, 0, 0];
  const propOptions = (catalog?.props || []).map(prop => ({ value: prop.id, label: prop.label }));
  return `
    ${panelHeader(propId, `Prop · ${selection.id}`)}
    <div class="properties-body">
      ${field("Prop type", `<select data-instance-field="prop">${selectOptions(propOptions, instance.prop)}</select>`)}
      <div class="field-row">
        ${field("X", numberInput(position[0], `data-instance-field="pos.0"`))}
        ${field("Y", numberInput(position[1], `data-instance-field="pos.1"`))}
        ${field("Z", numberInput(position[2], `data-instance-field="pos.2"`))}
      </div>
      <div class="field-row">
        ${field("Rot Y", numberInput(rotation[1], `data-instance-field="rot.1"`, "15"))}
        ${field("Scale", numberInput(instance.scale ?? 1, `data-instance-field="scale"`))}
      </div>
      ${field("Behavior", textInput(instance.behavior || "", `data-instance-field="behavior"`, "dispenser / script"))}
      ${field("Animation", textInput(instance.animation || "", `data-instance-field="animation"`))}
      ${field("Activity", `<select data-instance-field="activity">${selectOptions([{ value: "", label: "(none)" }, ...(catalog?.activities || []).map(id => ({ value: id, label: id }))], instance.activity || "")}</select>`)}
      ${field("Cooldown (seconds)", numberInput(instance.cooldown ?? 0, `data-instance-field="cooldown"`, "1"))}
      ${field("Content cards (comma)", textInput((instance.content || []).join(", "), `data-instance-field="content"`))}
      ${field("Recipes (comma)", textInput((instance.recipes || []).join(", "), `data-instance-field="recipes"`))}
      ${field("Actions (label | command per line)", textarea(actionsToText(instance.actions), `data-instance-field="actions"`, 3))}
      ${field("Draw weights (JSON)", textarea(JSON.stringify(instance.draw_weight || {}), `data-instance-field="draw_weight"`, 2))}
      <button type="button" class="negative" data-instance-delete>Delete prop</button>
    </div>
  `;
}

function peepPanel(state) {
  const { draft, catalog, selection } = state;
  const peep = draft.peeps?.[selection.id];
  if (!peep) return '<p class="empty-state">Select a peep.</p>';
  const roomOptions = Object.keys(draft.rooms || {}).map(id => ({ value: id, label: id }));
  return `
    ${panelHeader(peep.label || selection.id, `Peep · ${selection.id}`)}
    <div class="properties-body">
      ${field("Label", textInput(peep.label, `data-peep-field="label"`))}
      ${field("Description", textarea(peep.description, `data-peep-field="description"`, 2))}
      ${field("Room", `<select data-peep-field="room">${selectOptions(roomOptions, peep.room)}</select>`)}
      ${field("Image", `<select data-peep-field="image">${selectOptions(catalog?.peep_images || [], peep.image)}</select>`)}
      ${field("Script", textInput(peep.script || "", `data-peep-field="script"`, "molly.py"))}
      ${field("Activity", `<select data-peep-field="activity">${selectOptions([{ value: "", label: "(none)" }, ...(catalog?.activities || []).map(id => ({ value: id, label: id }))], peep.activity || "")}</select>`)}
      ${field("Actions (label | command per line)", textarea(actionsToText(peep.actions), `data-peep-field="actions"`, 3))}
      <fieldset class="subgroup">
        <legend>Dialog</legend>
        ${renderDialogEditor(peep.dialog)}
      </fieldset>
      <button type="button" class="negative" data-peep-delete>Delete peep</button>
    </div>
  `;
}

function cardPanel(state) {
  const { draft, catalog, selection } = state;
  const room = draft.rooms?.[selection.id];
  const index = Number(selection.sub);
  const card = room?.cards?.[index];
  if (!room || !card) return '<p class="empty-state">Select an initial card.</p>';
  const cards = (catalog?.cards || []).map(entry => ({ value: entry.id, label: `${entry.label} (${entry.id})` }));
  return `
    ${panelHeader("Initial card", `Room · ${selection.id}`)}
    <div class="properties-body">
      ${field("Card", `<select data-card-field="${index}:card">${selectOptions(cards, card.card)}</select>`)}
      ${field("Quantity", numberInput(card.quantity ?? 1, `data-card-field="${index}:quantity"`, "1"))}
      <div class="field-row">
        ${field("X", numberInput((card.pos || [50, 50, 0])[0], `data-card-field="${index}:pos.0"`))}
        ${field("Y", numberInput((card.pos || [50, 50, 0])[1], `data-card-field="${index}:pos.1"`))}
      </div>
      <button type="button" class="negative" data-card-delete="${index}">Delete card</button>
    </div>
  `;
}

export function renderProperties(state) {
  if (!state.draft) return "";
  switch (state.selection.kind) {
    case "prop":
      return propPanel(state);
    case "peep":
      return peepPanel(state);
    case "card":
      return cardPanel(state);
    case "exit":
      return exitPanel(state);
    case "room":
    default:
      return roomPanel(state);
  }
}

function exitPanel(state) {
  const { draft, catalog, selection } = state;
  const room = draft.rooms?.[selection.id];
  const exit = room?.exits?.[selection.sub];
  if (!room || !exit) return '<p class="empty-state">Select an exit on the map.</p>';
  const roomOptions = Object.keys(draft.rooms || {}).map(id => ({ value: id, label: id }));
  const cardOptions = [{ value: "", label: "(none)" }, ...(catalog?.cards || []).map(card => ({ value: card.id, label: card.label }))];
  const exitId = selection.sub;
  return `
    ${panelHeader(`Exit · ${exitId}`, `Room · ${selection.id}`)}
    <div class="properties-body">
      ${field("Label", textInput(exit.label || "", `data-exit-field="${escapeHtml(exitId)}:label"`))}
      ${field("Target room", `<select data-exit-field="${escapeHtml(exitId)}:target">${selectOptions(roomOptions, exit.target)}</select>`)}
      ${field("Requires card", `<select data-exit-field="${escapeHtml(exitId)}:requires">${selectOptions(cardOptions, exit.requires || "")}</select>`)}
      <label class="mini-check">${checkbox(Boolean(exit.locked), `data-exit-field="${escapeHtml(exitId)}:locked"`)} locked</label>
      <button type="button" class="negative" data-exit-delete="${escapeHtml(exitId)}">Delete exit</button>
    </div>
  `;
}
