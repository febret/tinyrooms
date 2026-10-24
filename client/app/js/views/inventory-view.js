import { escapeHtml } from "../presentation.js";
import { INVENTORY_TABS, previewStack, TAB_PREDICATES } from "../inventory-state.js";
import { cardPreviewMarkup } from "./card-preview.js";
import { inventorySection, modalShell } from "./view-helpers.js";

const ACTION_ICONS = {
  merge: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="m7 4 5 5 5-5M7 20l5-5 5 5"></path><path d="M12 9v6"></path></svg>`,
  sell: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M20 13 11 4H4v7l9 9 7-7Z"></path><circle cx="8" cy="8" r="1"></circle></svg>`,
  compact: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="3" y="3" width="7" height="7" rx="1"></rect><rect x="14" y="3" width="7" height="7" rx="1"></rect><rect x="3" y="14" width="7" height="7" rx="1"></rect><rect x="14" y="14" width="7" height="7" rx="1"></rect></svg>`,
};

function inventoryAction({ action, label, tone, icon, value = "1", pressed = null }) {
  const pressedAttr = pressed === null ? "" : ` aria-pressed="${pressed}"`;
  return `<button type="button" class="inventory-action ${tone}" data-${action}="${escapeHtml(value)}" aria-label="${escapeHtml(label)}" title="${escapeHtml(label)}"${pressedAttr}>${icon}<span class="inventory-action-label">${escapeHtml(label)}</span></button>`;
}

export function inventoryView(state) {
  const selling = Boolean(state.ui?.sellMode);
  const compact = Boolean(state.ui?.inventoryCompact);
  const stacks = state.room?.inventory || [];
  const hasPacks = stacks.some(stack => stack.definition?.type === "pack");
  const packs = hasPacks
    ? `<div class="inventory-packs">${inventorySection(state, "Packs", stack => stack.definition?.type === "pack", { compact })}</div>`
    : "";
  const tab = INVENTORY_TABS.includes(state.ui?.inventoryTab) ? state.ui.inventoryTab : "Items";
  const controls = `<div class="inventory-controls">
    <div class="inventory-tabs" role="group" aria-label="Inventory sections">
      ${INVENTORY_TABS.map(label => `<button type="button" class="${tab === label ? "selected" : ""}" data-inventory-tab="${label}" aria-pressed="${tab === label}">${escapeHtml(label)}</button>`).join("")}
    </div>
    <div class="inventory-actions" role="group" aria-label="Inventory actions">
      ${inventoryAction({ action: "compact-mode", label: compact ? "Full Cards" : "Compact View", tone: "neutral", icon: ACTION_ICONS.compact, value: "1", pressed: compact })}
      ${inventoryAction({ action: "auto-merge", label: "Auto Merge", tone: "neutral", icon: ACTION_ICONS.merge })}
      ${inventoryAction({ action: "sell-mode", label: selling ? "Done Selling" : "Sell Mode", tone: selling ? "negative" : "neutral", icon: ACTION_ICONS.sell, pressed: selling })}
    </div>
  </div>`;
  return modalShell({
    extraClass: `wide inventory-view${compact ? " is-compact" : ""}`,
    ariaLabel: "Inventory",
    title: "Your Inventory",
    subtitleHtml: controls,
    body: `
      <div class="inventory-layout">
        <aside class="inventory-preview" aria-label="Card preview">
          ${cardPreviewMarkup(previewStack(state, tab))}
        </aside>
        <div class="inventory-content">
          ${packs}
          <div class="modal-scroll">
            ${inventorySection(state, tab, TAB_PREDICATES[tab], { compact })}
          </div>
        </div>
      </div>
    `,
  });
}
