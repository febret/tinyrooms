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

export function handIconMarkup(definition, stack) {
  const label = `${definition.label}${stack.quantity > 1 ? `, ${stack.quantity} copies` : ""}${stack.pinned ? ", pinned" : ""}, equipped`;
  return `
    <button type="button" class="hand-icon" data-stack-id="${escapeHtml(stack.stackId)}" data-scope="inventory"
      aria-label="${escapeHtml(label)}" aria-pressed="false" title="${escapeHtml(definition.label)}">
      <img class="card-icon-art" src="${escapeHtml(definition.imageUrl)}" alt="" loading="lazy">
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

export function journalSpreadMarkup({ left, right, leftLabel, rightLabel }) {
  return `<div class="journal-book"><div class="journal-pages">
    <section class="journal-page journal-page-left" aria-label="${escapeHtml(leftLabel)}">
      <div class="journal-page-inner" tabindex="0">${left}</div>
    </section>
    <div class="journal-spine" aria-hidden="true"></div>
    <section class="journal-page journal-page-right" aria-label="${escapeHtml(rightLabel)}">
      <div class="journal-page-inner" tabindex="0">${right}</div>
    </section>
  </div></div>`;
}

export function counterBar(label, value, maximum, { tone = "", valueText = null } = {}) {
  const current = Number.isFinite(value) ? value : 0;
  const limit = Number.isFinite(maximum) ? Math.max(0, maximum) : 0;
  const clamped = Math.max(0, Math.min(limit, current));
  const text = valueText ?? `${Math.floor(current)}/${limit}`;
  return `
    <div class="counter-row ${escapeHtml(tone)}">
      <span class="counter-label">${escapeHtml(label)}</span>
      <progress class="counter-track" value="${clamped}" max="${limit || 1}" aria-label="${escapeHtml(label)}" aria-valuetext="${escapeHtml(limit > 0 ? text : `${text}; no capacity`)}">${escapeHtml(text)}</progress>
      <span class="counter-value">${escapeHtml(text)}</span>
    </div>
  `;
}

