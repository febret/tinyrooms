import { escapeHtml } from "../presentation.js";
import { inventorySection, modalShell } from "./view-helpers.js";

const INVENTORY_TABS = ["Items", "Emotes", "Skills"];

const TAB_PREDICATES = {
  Items: stack => stack.definition?.type !== "emote" && stack.definition?.type !== "skill" && stack.definition?.type !== "pack",
  Emotes: stack => stack.definition?.type === "emote",
  Skills: stack => stack.definition?.type === "skill",
};

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
  return modalShell({
    extraClass: "wide inventory-view",
    ariaLabel: "Inventory",
    title: "Your Inventory",
    subtitleHtml: `<p class="inventory-balance">${escapeHtml(state.user?.bops ?? 0)} Bops <button type="button" class="positive" data-claim-bops="1">Claim Daily Bops</button> <button type="button" class="primary" data-open-shop="cards">Shop</button> <button type="button" class="neutral" data-auto-merge="1">Auto Merge</button> <button type="button" class="${selling ? "negative" : "neutral"}" data-sell-mode="1" aria-pressed="${selling}">${selling ? "Done Selling" : "Sell Mode"}</button></p>`,
    body: `
      ${packs}
      ${tabs}
      <div class="modal-scroll">
        ${inventorySection(state, tab, TAB_PREDICATES[tab])}
      </div>
    `,
  });
}
