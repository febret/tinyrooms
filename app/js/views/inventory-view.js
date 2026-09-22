import { escapeHtml } from "../presentation.js";
import { inventorySection, modalShell } from "./view-helpers.js";

export function inventoryView(state) {
  return modalShell({
    extraClass: "wide inventory-view",
    ariaLabel: "Inventory",
    title: "Your Inventory",
    subtitle: `<p class="inventory-balance">${escapeHtml(state.user?.bops ?? 0)} Bops <button type="button" class="positive" data-claim-bops="1">Claim Daily Bops</button></p>`,
    body: `
      <div class="modal-scroll">
        ${inventorySection(state, "Items", stack => stack.definition?.type !== "emote" && stack.definition?.type !== "skill")}
        ${inventorySection(state, "Emotes", stack => stack.definition?.type === "emote")}
        ${inventorySection(state, "Skills", stack => stack.definition?.type === "skill")}
      </div>
    `,
  });
}
