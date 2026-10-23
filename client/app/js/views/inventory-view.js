import { escapeHtml } from "../presentation.js";
import { INVENTORY_TABS, previewStack, TAB_PREDICATES } from "../inventory-state.js";
import { cardPreviewMarkup } from "./card-preview.js";
import { inventorySection, modalShell } from "./view-helpers.js";

const ACTION_ICONS = {
  claim: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="4" y="9" width="16" height="11" rx="2"></rect><path d="M12 9v11M4 13h16M8 9a2.5 2.5 0 1 1 4-2 2.5 2.5 0 1 1 4 2"></path></svg>`,
  shop: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M5 8h14l-1 12H6L5 8Z"></path><path d="M9 8a3 3 0 0 1 6 0"></path></svg>`,
  merge: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="m7 4 5 5 5-5M7 20l5-5 5 5"></path><path d="M12 9v6"></path></svg>`,
  sell: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M20 13 11 4H4v7l9 9 7-7Z"></path><circle cx="8" cy="8" r="1"></circle></svg>`,
};

function inventoryAction({ action, label, tone, icon, value = "1", pressed = null }) {
  const pressedAttr = pressed === null ? "" : ` aria-pressed="${pressed}"`;
  return `<button type="button" class="inventory-action ${tone}" data-${action}="${escapeHtml(value)}" aria-label="${escapeHtml(label)}" title="${escapeHtml(label)}"${pressedAttr}>${icon}<span class="inventory-action-label">${escapeHtml(label)}</span></button>`;
}

export function inventoryView(state) {
  const selling = Boolean(state.ui?.sellMode);
  const stacks = state.room?.inventory || [];
  const hasPacks = stacks.some(stack => stack.definition?.type === "pack");
  const packs = hasPacks
    ? `<div class="inventory-packs">${inventorySection(state, "Packs", stack => stack.definition?.type === "pack")}</div>`
    : "";
  const tab = INVENTORY_TABS.includes(state.ui?.inventoryTab) ? state.ui.inventoryTab : "Items";
  const tabs = `<div class="inventory-tabs" role="group" aria-label="Inventory sections">
    ${INVENTORY_TABS.map(label => `<button type="button" class="${tab === label ? "selected" : ""}" data-inventory-tab="${label}" aria-pressed="${tab === label}">${escapeHtml(label)}</button>`).join("")}
  </div>`;
  const actions = `<div class="inventory-actions" role="group" aria-label="Inventory actions">
    ${inventoryAction({ action: "claim-bops", label: "Claim Daily Bops", tone: "positive", icon: ACTION_ICONS.claim })}
    ${inventoryAction({ action: "open-shop", label: "Shop", tone: "primary", icon: ACTION_ICONS.shop, value: "cards" })}
    ${inventoryAction({ action: "auto-merge", label: "Auto Merge", tone: "neutral", icon: ACTION_ICONS.merge })}
    ${inventoryAction({ action: "sell-mode", label: selling ? "Done Selling" : "Sell Mode", tone: selling ? "negative" : "neutral", icon: ACTION_ICONS.sell, pressed: selling })}
  </div>`;
  return modalShell({
    extraClass: "wide inventory-view",
    ariaLabel: "Inventory",
    title: "Your Inventory",
    subtitleHtml: `<div class="inventory-toolbar"><span class="inventory-bops">${escapeHtml(state.user?.bops ?? 0)} Bops</span>${actions}</div>`,
    body: `
      <div class="inventory-layout">
        <aside class="inventory-preview" aria-label="Card preview">
          ${cardPreviewMarkup(previewStack(state, tab))}
        </aside>
        <div class="inventory-content">
          ${packs}
          ${tabs}
          <div class="modal-scroll">
            ${inventorySection(state, tab, TAB_PREDICATES[tab])}
          </div>
        </div>
      </div>
    `,
  });
}
