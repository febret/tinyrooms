import { escapeHtml } from "../util.js";

function conditionText(when) {
  if (!when || typeof when !== "object") return "";
  return JSON.stringify(when);
}

export function renderDialogEditor(dialog) {
  const nodes = dialog && typeof dialog === "object" ? dialog : {};
  const nodeIds = Object.keys(nodes);
  const blocks = nodeIds.map(nodeId => {
    const node = nodes[nodeId] && typeof nodes[nodeId] === "object" ? nodes[nodeId] : {};
    const choices = Array.isArray(node.choices) ? node.choices : [];
    const choiceRows = choices.map((choice, index) => {
      const value = choice && typeof choice === "object" ? choice : {};
      const end = value.end ? " checked" : "";
      return `
        <div class="dialog-choice">
          <input type="text" data-dialog-choice-field="${escapeHtml(nodeId)}:${index}:label" value="${escapeHtml(value.label || "")}" placeholder="Label" aria-label="Choice label">
          <input type="text" data-dialog-choice-field="${escapeHtml(nodeId)}:${index}:next" value="${escapeHtml(value.next || "")}" placeholder="Next node" aria-label="Next node">
          <label class="mini-check"><input type="checkbox" data-dialog-choice-field="${escapeHtml(nodeId)}:${index}:end"${end}> end</label>
          <input type="text" data-dialog-choice-field="${escapeHtml(nodeId)}:${index}:action" value="${escapeHtml(value.action || "")}" placeholder="Action id" aria-label="Action id">
          <input type="text" data-dialog-choice-field="${escapeHtml(nodeId)}:${index}:script" value="${escapeHtml(value.script || "")}" placeholder="Script callback" aria-label="Script callback">
          <input type="text" data-dialog-choice-field="${escapeHtml(nodeId)}:${index}:give_card" value="${escapeHtml(value.give_card || "")}" placeholder="Give card" aria-label="Give card">
          <input type="text" data-dialog-choice-field="${escapeHtml(nodeId)}:${index}:start_task" value="${escapeHtml(value.start_task || "")}" placeholder="Start task" aria-label="Start task">
          <input type="number" data-dialog-choice-field="${escapeHtml(nodeId)}:${index}:grant" value="${escapeHtml(value.grant ?? 0)}" placeholder="Grant" aria-label="Grant">
          <input type="text" data-dialog-choice-field="${escapeHtml(nodeId)}:${index}:when" value="${escapeHtml(conditionText(value.when))}" placeholder='When {"counter":"..."}' aria-label="Condition">
          <button type="button" class="icon-button" data-dialog-choice-delete="${escapeHtml(nodeId)}:${index}" aria-label="Delete choice">✕</button>
        </div>
      `;
    });
    const isStart = nodeId === "start";
    return `
      <div class="dialog-node">
        <div class="dialog-node-head">
          <code>${escapeHtml(nodeId)}</code>
          ${isStart ? '<span class="badge">start</span>' : `<button type="button" class="icon-button" data-dialog-node-delete="${escapeHtml(nodeId)}" aria-label="Delete node">✕</button>`}
        </div>
        <textarea data-dialog-node-text="${escapeHtml(nodeId)}" rows="2" placeholder="Node text" aria-label="Node text">${escapeHtml(node.text || "")}</textarea>
        <div class="dialog-choices">${choiceRows.join("")}</div>
        <button type="button" class="quiet" data-dialog-choice-add="${escapeHtml(nodeId)}">Add choice</button>
      </div>
    `;
  });
  return `
    <div class="dialog-editor">
      ${blocks.length ? blocks.join("") : '<p class="empty-state">No dialog nodes.</p>'}
      <div class="dialog-add-row">
        <input type="text" id="dialog-new-node" placeholder="New node id" aria-label="New node id">
        <button type="button" class="quiet" data-dialog-node-add>Add node</button>
      </div>
    </div>
  `;
}
