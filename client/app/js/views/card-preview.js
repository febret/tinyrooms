import { cardFaceFields } from "../cards/card-face.js";
import { cardRarityKey, cardTheme, tagAccent } from "../cards/card-style.js";
import { escapeHtml } from "../presentation.js";
import { longDescription, rarityLabel } from "./view-helpers.js";

function tagChips(tags) {
  if (!tags.length) return "";
  return `<ul class="card-tag-list" aria-label="Card tags">${tags.map(tag => {
    const accent = tagAccent([tag]);
    return `<li class="card-tag" style="--tag-color:${accent.accent}">${escapeHtml(tag)}</li>`;
  }).join("")}</ul>`;
}

function metric(label, value) {
  return `<div><dt>${escapeHtml(label)}</dt><dd>${escapeHtml(value)}</dd></div>`;
}

/**
 * The shared inventory card preview. The canvas keeps the same data contract as
 * the former details overlay so the WebGL viewer can mount it directly.
 */
export function cardPreviewMarkup(preview) {
  const stack = preview?.stack;
  if (!stack?.definition) {
    return `<div class="inventory-preview-empty">
      <p>Nothing to preview</p>
      <span>This tab has no cards yet.</span>
    </div>`;
  }
  const definition = stack.definition;
  const theme = cardTheme(definition);
  const rarity = cardRarityKey(definition.rarity);
  const faceKey = JSON.stringify(cardFaceFields(definition));
  const backUrl = definition.backUrl || "";
  const equipped = preview.kind === "inventory-card" ? `<div><dt>Equipped</dt><dd>${stack.equipped ? "Yes" : "No"}</dd></div>` : "";
  const scope = stack.scope ? metric("Scope", stack.scope) : "";
  return `
    <div class="inventory-preview-card rarity-${rarity}" data-rarity="${rarity}" style="--card-glow:${theme.glow}">
      <canvas class="card-preview-canvas" data-card-face="${escapeHtml(faceKey)}" data-card-back="${escapeHtml(backUrl)}"
        data-card-interactive="true" aria-label="${escapeHtml(`${definition.label} card preview. Drag to rotate.`)}"></canvas>
    </div>
    <div class="inventory-preview-info">
      <h3 class="inventory-preview-name">${escapeHtml(definition.label)}</h3>
      <p class="inventory-preview-description">${escapeHtml(longDescription(definition))}</p>
      <dl class="details-metrics inventory-preview-metrics">
        ${metric("Rarity", rarityLabel(definition))}
        ${metric("Quantity", String(stack.quantity || 0))}
        ${metric("Stack limit", String(definition.stackLimit || 1))}
        ${scope}
        <div><dt>Pinned</dt><dd>${stack.pinned ? "Yes" : "No"}</dd></div>
        ${equipped}
      </dl>
      ${tagChips(theme.tags)}
    </div>
  `;
}
