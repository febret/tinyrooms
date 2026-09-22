import { escapeHtml } from "../presentation.js";

export function rarityLabel(definition) {
  return definition?.rarity || (definition?.type === "core" ? "Core" : definition?.type ? definition.type : "Card");
}

export function longDescription(definition) {
  const lines = [definition?.description || "No description available."];
  if (definition?.category) lines.push(`${definition.category} emote.`);
  if (definition?.rank) lines.push(`Rank: ${definition.rank}.`);
  if (definition?.oneUse) lines.push("One use.");
  if (definition?.passive) lines.push("Passive while equipped or slotted.");
  if (definition?.target) lines.push(`Target: ${definition.target}.`);
  if (definition?.effect) lines.push(`Effect: ${definition.effect}.`);
  if (definition?.amount) lines.push(`Amount: ${definition.amount}.`);
  if (definition?.duration) lines.push(`Duration: ${definition.duration} seconds.`);
  if (definition?.bonuses && Object.keys(definition.bonuses).length) {
    lines.push(`Bonuses: ${Object.entries(definition.bonuses).map(([key, value]) => `${key.replaceAll("_", " ")} ${value > 0 ? "+" : ""}${value}`).join(", ")}.`);
  }
  return lines.join(" ");
}

export function tileMarkup(definition, stack, selected, scope) {
  const label = `${definition.label}${stack.quantity > 1 ? `, ${stack.quantity} copies` : ""}${stack.pinned ? ", pinned" : ""}${stack.equipped ? ", equipped" : ""}`;
  return `
    <button type="button" class="game-card ${selected ? "selected" : ""} ${stack.equipped ? "is-equipped" : ""}"
      data-stack-id="${escapeHtml(stack.stackId)}" data-scope="${scope}" aria-label="${escapeHtml(label)}"
      aria-pressed="${selected}" title="${escapeHtml(`${definition.label} · ${rarityLabel(definition)}`)}">
      <img src="${escapeHtml(definition.imageUrl)}" alt="" loading="lazy">
      ${stack.quantity > 1 ? `<span class="card-badge quantity-badge" aria-hidden="true">×${escapeHtml(stack.quantity)}</span>` : ""}
      ${stack.pinned ? '<span class="card-badge pin-badge" aria-hidden="true">◆</span>' : ""}
      ${stack.equipped ? '<span class="card-badge equipped-badge" aria-hidden="true">✓</span>' : ""}
    </button>
  `;
}

export function cardsGrid(stacks, scope, selection, emptyText) {
  const kind = scope === "room" ? "room-card" : "inventory-card";
  return `
    <div class="cards-grid">
      ${stacks.length
        ? stacks.map(stack => tileMarkup(stack.definition, stack, selection.kind === kind && selection.id === stack.stackId, scope)).join("")
        : `<div class="empty-state">${emptyText}</div>`}
    </div>
  `;
}

export function inventorySection(state, title, predicate) {
  const stacks = state.room?.inventory?.filter(predicate) || [];
  return `
    <section class="inventory-group">
      <header><h3>${escapeHtml(title)}</h3><span>${stacks.length}</span></header>
      ${cardsGrid(stacks, "inventory", state.selection, "Nothing here yet.")}
    </section>
  `;
}

export function modalShell({ extraClass = "", ariaLabel, title = "", titleHtml = null, subtitle = "", subtitleHtml = null, body }) {
  const heading = titleHtml === null ? escapeHtml(title) : titleHtml;
  const subheading = subtitleHtml === null ? (subtitle ? `<p>${escapeHtml(subtitle)}</p>` : "") : subtitleHtml;
  return `
    <section class="board-modal ${extraClass}" role="dialog" aria-modal="false" aria-label="${escapeHtml(ariaLabel)}">
      <header class="modal-header">
        <div><h2>${heading}</h2>${subheading}</div>
        <button type="button" class="quiet" data-close-view="1">Close</button>
      </header>
      ${body}
    </section>
  `;
}

export function statusIconMarkup(statuses, definitions) {
  return statuses.map(id => {
    const definition = definitions?.[id];
    return `<span class="status-icon" title="${escapeHtml(definition?.label || id)}">${escapeHtml(definition?.icon || "•")}</span>`;
  }).join("");
}

export function statusIconsMarkup(statuses, definitions) {
  if (!statuses?.length) return "";
  return `<span class="status-icons">${statusIconMarkup(statuses, definitions)}</span>`;
}

export function counterBar(label, value, maximum) {
  const percent = maximum > 0 ? Math.max(0, Math.min(100, (value / maximum) * 100)) : 0;
  return `
    <div class="counter-row">
      <span class="counter-label">${escapeHtml(label)}</span>
      <span class="counter-track"><span class="counter-fill" style="width:${percent}%"></span></span>
      <span class="counter-value">${Math.floor(value)}/${maximum}</span>
    </div>
  `;
}


