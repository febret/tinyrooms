import { escapeHtml } from "../presentation.js";
import { findInventoryCard } from "../state.js";
import { modalShell } from "./view-helpers.js";

export function skillsView(state) {
  const slots = state.user?.skills || [];
  const ranks = ["Script Kiddo", "Hacker", "Leet"];
  const rows = ranks.map(rank => {
    const rowSlots = slots.filter(slot => slot.rank === rank);
    return `
      <div class="skill-row" data-rank="${escapeHtml(rank)}">
        <h3>${escapeHtml(rank)}</h3>
        <div class="skill-slots">
          ${rowSlots.map(slot => {
            const stack = slot.stackId ? findInventoryCard(state, slot.stackId) : null;
            const selected = stack && state.selection.kind === "inventory-card" && state.selection.id === stack.stackId;
            return `
              <button type="button" class="skill-slot ${slot.unlocked ? "" : "locked"} ${slot.stackId ? "filled" : ""} ${selected ? "selected" : ""}"
                data-skill-slot="${slot.index}" data-stack-id="${escapeHtml(slot.stackId || "")}"
                aria-label="${escapeHtml(slot.unlocked ? (stack ? `Slot ${slot.index + 1}: ${stack.definition.label}` : `Empty ${rank} slot ${slot.index + 1}`) : `Locked slot ${slot.index + 1}`)}">
                ${stack ? `<img src="${escapeHtml(stack.definition.imageUrl)}" alt="">` : (slot.unlocked ? "+" : "🔒")}
              </button>
            `;
          }).join("")}
        </div>
      </div>
    `;
  }).join("");
  const stats = state.user?.stats || {};
  const bonuses = Object.entries(stats).map(([key, value]) => `${key.replaceAll("_", " ")} ${value}`).join(" · ");
  return modalShell({
    extraClass: "skills-view",
    ariaLabel: "Skills",
    title: "Your Skills",
    subtitle: `<p>${escapeHtml(bonuses)}</p>`,
    body: `
      <div class="modal-scroll">
        ${rows}
        <p class="skills-hint">Select a skill card in your Inventory, then choose an unlocked slot. Slots unlock with your level.</p>
      </div>
    `,
  });
}
