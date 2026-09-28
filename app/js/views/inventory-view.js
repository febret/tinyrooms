import { escapeHtml } from "../presentation.js";
import { inventorySection, modalShell } from "./view-helpers.js";

export function inventoryView(state) {
  const selling = Boolean(state.ui?.sellMode);
  const stacks = state.room?.inventory || [];
  const hasPacks = stacks.some(stack => stack.definition?.type === "pack");
  const packs = hasPacks
    ? inventorySection(state, "Packs", stack => stack.definition?.type === "pack")
    : "";
  return modalShell({
    extraClass: "wide inventory-view",
    ariaLabel: "Inventory",
    title: "Your Inventory",
    subtitleHtml: `<p class="inventory-balance">${escapeHtml(state.user?.bops ?? 0)} Bops <button type="button" class="positive" data-claim-bops="1">Claim Daily Bops</button> <button type="button" class="primary" data-open-shop="cards">Shop</button> <button type="button" class="neutral" data-auto-merge="1">Auto Merge</button> <button type="button" class="${selling ? "negative" : "neutral"}" data-sell-mode="1" aria-pressed="${selling}">${selling ? "Done Selling" : "Sell Mode"}</button></p>`,
    body: `
      <div class="modal-scroll">
        ${packs}
        ${inventorySection(state, "Items", stack => stack.definition?.type !== "emote" && stack.definition?.type !== "skill" && stack.definition?.type !== "pack")}
        ${inventorySection(state, "Emotes", stack => stack.definition?.type === "emote")}
        ${inventorySection(state, "Skills", stack => stack.definition?.type === "skill")}
      </div>
    `,
  });
}
