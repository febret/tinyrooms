import { escapeHtml, selectOptions } from "../util.js";

const CHOICE_FIELDS = [
  ["action", "Action id"],
  ["script", "Script callback"],
  ["give_card", "Give card"],
  ["start_task", "Start task"],
];

function input(spec, value, label, type = "text") {
  return `<input type="${type}" data-dialog-choice-field="${spec}" value="${escapeHtml(value ?? "")}" placeholder="${label}" aria-label="${label}">`;
}

export function renderDialogNodeEditor(dialog, nodeId) {
  const node = dialog?.[nodeId];
  if (!node || typeof node !== "object") {
    return '<p class="empty-state">Select a node in the dialog graph to edit its text and choices.</p>';
  }
  const id = escapeHtml(nodeId);
  const targets = [{ value: "", label: "(end)" }, ...Object.keys(dialog).map(key => ({ value: key, label: key }))];
  const choices = (Array.isArray(node.choices) ? node.choices : []).map((choice, index) => {
    const value = choice && typeof choice === "object" ? choice : {};
    const spec = field => `${id}:${index}:${field}`;
    return `
      <div class="dialog-choice">
        ${input(spec("label"), value.label, "Label")}
        <select data-dialog-choice-field="${spec("next")}" aria-label="Next node">${selectOptions(targets, value.end ? "" : value.next || "")}</select>
        ${CHOICE_FIELDS.map(([field, label]) => input(spec(field), value[field], label)).join("")}
        ${input(spec("grant"), value.grant ?? 0, "Grant", "number")}
        ${input(spec("when"), value.when && typeof value.when === "object" ? JSON.stringify(value.when) : "", "When (JSON)")}
        <button type="button" class="icon-button" data-dialog-choice-delete="${spec("")}" aria-label="Delete choice">✕</button>
      </div>
    `;
  });
  return `
    <fieldset class="subgroup">
      <legend>Dialog node · ${id}</legend>
      <textarea data-dialog-node-text="${id}" rows="3" placeholder="Node text" aria-label="Node text">${escapeHtml(node.text || "")}</textarea>
      ${choices.join("") || '<p class="empty-state">No choices: the conversation ends here.</p>'}
      <button type="button" class="quiet" data-dialog-choice-add="${id}">Add choice</button>
      ${nodeId === "start" ? "" : `<button type="button" class="negative" data-dialog-node-delete="${id}">Delete node</button>`}
    </fieldset>
  `;
}
