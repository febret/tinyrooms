import { cardFaceSvg } from "./card-face.js";
import { escapeHtml } from "./presentation.js";
import { findInventoryCard, findRoomCard } from "./state.js";

/** Describe the selected entity's preview above the look bar and the inspect action it opens. */
export function lookPreview(state, description) {
  const selection = state.selection || {};
  const dialog = state.room?.dialog;
  if ((selection.kind === "peep" || dialog) && description.imageUrl) {
    return { markup: `<img class="look-preview" src="${escapeHtml(description.imageUrl)}" alt="">`, action: null };
  }
  if (dialog) return { markup: "", action: null };
  if (selection.kind === "prop") {
    const prop = state.room?.props?.find(candidate => candidate.id === selection.id);
    if (prop?.renderKind === "sign" || prop?.renderKind === "whiteboard") {
      const label = prop.renderKind === "sign" ? "sign" : "whiteboard";
      return {
        markup: `<button type="button" class="look-preview look-preview-button look-preview-surface" data-look-inspect="prop" data-focus-key="look-inspect" aria-label="Inspect ${escapeHtml(prop.label)}" title="Inspect ${escapeHtml(prop.label)}"><span aria-hidden="true">${prop.renderKind === "sign" ? "✎" : "▤"}</span> ${escapeHtml(label)}</button>`,
        action: { type: "open-view", view: "prop-details", propId: prop.id },
      };
    }
    if (!prop?.modelUrl) return { markup: "", action: null };
    return {
      markup: `<button type="button" class="look-preview look-preview-button look-preview-3d" data-look-inspect="prop" data-focus-key="look-inspect" aria-label="Inspect ${escapeHtml(prop.label)}" title="Inspect ${escapeHtml(prop.label)}"><canvas data-prop-model="${escapeHtml(prop.modelUrl)}" data-prop-scale="${escapeHtml(prop.scale)}" aria-hidden="true"></canvas></button>`,
      action: { type: "open-view", view: "prop-details", propId: prop.id },
    };
  }
  if (selection.kind === "room-card" || selection.kind === "inventory-card") {
    const stack = selection.kind === "room-card" ? findRoomCard(state, selection.id) : findInventoryCard(state, selection.id);
    if (!stack?.definition) return { markup: "", action: null };
    const label = stack.definition.label || "card";
    return {
      markup: `<button type="button" class="look-preview look-preview-button look-preview-card" data-look-inspect="card" data-focus-key="look-inspect" aria-label="Inspect ${escapeHtml(label)}" title="Inspect ${escapeHtml(label)}">${cardFaceSvg(stack.definition)}</button>`,
      action: { type: "inspect-card", stackId: stack.stackId },
    };
  }
  return { markup: "", action: null };
}
