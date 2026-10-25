import { isExitProp } from "./exit-props.js";
import { escapeHtml } from "./presentation.js";
import { findInventoryCard, findRoomCard } from "./state.js";

/** Render the active dialog response above the selected peep display. */
export function lookDialogBubble(state, description) {
  const selection = state.selection || {};
  const dialog = state.room?.dialog;
  if (selection.kind !== "peep" || !description.imageUrl || dialog?.peepId !== selection.id) {
    return "";
  }
  const text = String(dialog.text || "");
  const label = `${dialog.peepLabel || description.title || "Peep"}: ${text}. Conversation`;
  return `<div class="bubble dialog-bubble look-dialog-bubble" role="status" aria-label="${escapeHtml(label)}"><span class="bubble-text">${escapeHtml(text)}</span></div>`;
}

/** Describe the selected entity's preview above the look bar and the inspect action it opens. */
export function lookPreview(state, description) {
  const selection = state.selection || {};
  if (selection.kind === "peep" && description.imageUrl) {
    const previewMarkup = `<img class="look-preview" src="${escapeHtml(description.imageUrl)}" alt="">`;
    return { markup: `${previewMarkup}${lookDialogBubble(state, description)}`, action: null };
  }
  if (selection.kind === "prop") {
    const prop = state.room?.props?.find(candidate => candidate.id === selection.id);
    if (prop?.renderKind === "sign" || prop?.renderKind === "whiteboard") {
      const label = prop.renderKind === "sign" ? "sign" : "whiteboard";
      return {
        markup: `<button type="button" class="look-preview look-preview-button look-preview-surface" data-look-inspect="prop" data-sound="open" data-focus-key="look-inspect" aria-label="Inspect ${escapeHtml(prop.label)}" title="Inspect ${escapeHtml(prop.label)}"><span aria-hidden="true">${prop.renderKind === "sign" ? "✎" : "▤"}</span> ${escapeHtml(label)}</button>`,
        action: { type: "open-view", view: "prop-details", propId: prop.id },
      };
    }
    if (isExitProp(prop)) {
      return {
        markup: `<button type="button" class="look-preview look-preview-button look-preview-surface" data-look-inspect="prop" data-sound="open" data-focus-key="look-inspect" aria-label="Inspect ${escapeHtml(prop.label)}" title="Inspect ${escapeHtml(prop.label)}"><span aria-hidden="true">➔</span> ${escapeHtml(prop.label)}</button>`,
        action: { type: "open-view", view: "prop-details", propId: prop.id },
      };
    }
    if (!prop?.modelUrl) return { markup: "", action: null };
    return {
      markup: `<button type="button" class="look-preview look-preview-button look-preview-3d" data-look-inspect="prop" data-sound="open" data-focus-key="look-inspect" aria-label="Inspect ${escapeHtml(prop.label)}" title="Inspect ${escapeHtml(prop.label)}"><canvas data-prop-model="${escapeHtml(prop.modelUrl)}" data-prop-scale="${escapeHtml(prop.scale)}" aria-hidden="true"></canvas></button>`,
      action: { type: "open-view", view: "prop-details", propId: prop.id },
    };
  }
  if (selection.kind === "room-card" || selection.kind === "inventory-card") {
    const stack = selection.kind === "room-card" ? findRoomCard(state, selection.id) : findInventoryCard(state, selection.id);
    if (!stack?.definition) return { markup: "", action: null };
    const label = stack.definition.label || "card";
    return {
      markup: `<button type="button" class="look-preview look-preview-button look-preview-card" data-look-inspect="card" data-sound="card" data-focus-key="look-inspect" aria-label="Inspect ${escapeHtml(label)}" title="Inspect ${escapeHtml(label)}"><img class="look-preview-card-icon" src="${escapeHtml(stack.definition.imageUrl)}" alt=""></button>`,
      action: { type: "inspect-card", stackId: stack.stackId },
    };
  }
  return { markup: "", action: null };
}
