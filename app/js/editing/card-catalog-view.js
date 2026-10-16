import { escapeHtml } from "../presentation.js";
import { withBase } from "../base-path.js";

export function filterCards(cards, query = "", source = "") {
  const search = query.trim().toLowerCase();
  return cards.filter(card => (!source || card.source === source)
    && `${card.id} ${card.label} ${card.description || ""} ${card.type} ${card.rarity || ""} ${card.source || ""}`.toLowerCase().includes(search));
}

export function cardGridMarkup(cards, { selectable = false, selected = new Set(), multiple = true } = {}) {
  if (!cards.length) return '<p class="cdb-status">No matching cards.</p>';
  return `<div class="card-grid">${cards.map(card => {
    const details = [];
    if (card.bonuses && Object.keys(card.bonuses).length) details.push(`Bonuses: ${Object.entries(card.bonuses).map(([key, value]) => `${key} +${value}`).join(", ")}`);
    if (card.effect) details.push(`Effect: ${card.effect}${card.amount != null ? ` (${card.amount})` : ""}`);
    if (card.target) details.push(`Target: ${card.target}`);
    if (card.energy_cost != null) details.push(`Energy: ${card.energy_cost}`);
    if (card.packs?.length) details.push(`Packs: ${card.packs.join(", ")}`);
    if (card.recipes?.length) details.push(`Recipes: ${card.recipes.join(", ")}`);
    const content = `
      <img src="${escapeHtml(withBase(card.image_url || ""))}" alt="${escapeHtml(card.label)}" loading="lazy">
      <h3>${escapeHtml(card.label)}</h3>
      <div class="badges"><span class="badge scope-${card.scope === "world" ? "world" : "base"}">${escapeHtml(card.scope || card.source || "")}</span>
        <span class="badge">${escapeHtml(card.type)}</span>
        ${card.rarity ? `<span class="badge rarity">${escapeHtml(card.rarity)}</span>` : ""}
        ${card.collectible ? '<span class="badge">collectible</span>' : ""}</div>
      <p>${escapeHtml(card.description || "")}</p>
      ${details.map(line => `<p class="detail-line">${escapeHtml(line)}</p>`).join("")}`;
    return selectable
      ? `<label class="card-tile${selected.has(card.id) ? " is-selected" : ""}"><span><input type="${multiple ? "checkbox" : "radio"}" name="selected-card" aria-label="Select ${escapeHtml(card.label)}" value="${escapeHtml(card.id)}" ${selected.has(card.id) ? "checked" : ""}> Select ${escapeHtml(card.label)}</span>${content}</label>`
      : `<article class="card-tile">${content}</article>`;
  }).join("")}</div>`;
}
