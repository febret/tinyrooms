import { escapeHtml } from "../presentation.js";

/** Shared centered entity preview used by peep, room, and prop descriptions. */
export function entityPreviewMarkup({ imageUrl = "", modelUrl = "", scale = "", label = "" } = {}) {
  if (modelUrl) {
    return `<canvas class="entity-preview-canvas" data-prop-model="${escapeHtml(modelUrl)}" data-prop-scale="${escapeHtml(scale)}" data-prop-interactive="true" aria-label="${escapeHtml(label)} model. Drag to rotate."></canvas>`;
  }
  if (imageUrl) {
    return `<img class="entity-preview-image" src="${escapeHtml(imageUrl)}" alt="">`;
  }
  return `<div class="entity-preview-empty" aria-hidden="true"></div>`;
}

/** Descriptive text block: large, centered, no metadata. */
export function entityDescriptionMarkup(description = "") {
  if (!description) return "";
  return `<p class="entity-details-description">${escapeHtml(description)}</p>`;
}

/** Full centered body: large preview with description above it. */
export function entityDetailsBody({ title = "", description = "", imageUrl = "", modelUrl = "", scale = "" } = {}) {
  return `
    <div class="entity-details-body">
      ${entityDescriptionMarkup(description)}
      ${entityPreviewMarkup({ imageUrl, modelUrl, scale, label: title })}
    </div>
  `;
}
