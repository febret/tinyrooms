import { escapeHtml } from "../presentation.js";
import { findInventoryCard } from "../state.js";
import { journalSpreadMarkup, modalShell } from "./view-helpers.js";

function skillRankMarkup(state, rank, slots, pending) {
  return `<section class="skill-row" data-rank="${escapeHtml(rank)}" aria-label="${escapeHtml(rank)} skills">
    <h3>${escapeHtml(rank)}</h3>
    <div class="skill-slots">${slots.map(slot => {
      const stack = slot.stackId ? findInventoryCard(state, slot.stackId) : null;
      const selected = Boolean(stack && state.selection?.kind === "inventory-card" && state.selection.id === stack.stackId);
      const actionable = slot.unlocked && (slot.stackId || pending);
      const description = !slot.unlocked ? `Locked ${rank} slot ${slot.index + 1}. Unlocks at level ${slot.index + 1}.`
        : slot.stackId ? `${stack?.definition.label || "Slotted skill"}, ${rank} slot ${slot.index + 1}. Activate to remove it.`
          : `Empty ${rank} slot ${slot.index + 1}.${pending ? " Place the selected skill here." : " Choose a skill in Inventory first."}`;
      return `<button type="button" class="skill-slot ${slot.unlocked ? "" : "locked"} ${slot.stackId ? "filled" : ""} ${selected ? "selected" : ""} ${actionable ? "actionable" : ""}"
        data-skill-slot="${escapeHtml(slot.index)}" data-stack-id="${escapeHtml(slot.stackId || "")}"
        aria-label="${escapeHtml(description)}" title="${escapeHtml(description)}" ${slot.unlocked ? "" : "disabled"}>
        ${stack ? `<img src="${escapeHtml(stack.definition.imageUrl)}" alt="">` : `<span aria-hidden="true">${!slot.unlocked ? "🔒" : slot.stackId ? "◆" : "+"}</span>`}
      </button>`;
    }).join("")}</div>
  </section>`;
}

export function skillsPagesMarkup(state) {
  const slots = state.user?.skills || [];
  const ranks = [...new Set(slots.map(slot => slot.rank))];
  const pending = state.views?.skillStackId || null;
  const pendingStack = pending ? findInventoryCard(state, pending) : null;
  const rows = ranks.map(rank => skillRankMarkup(state, rank, slots.filter(slot => slot.rank === rank), pending));
  const split = Math.ceil(rows.length / 2);
  return {
    leftLabel: "Skill slots, first ranks",
    rightLabel: "More skill slots and effective stats",
    left: `<p class="journal-eyebrow">Make room for your talents</p><h3 class="journal-page-title">Your Skills</h3>
      <p class="skills-hint" ${pending ? 'role="status"' : ""}>${pending ? `Ready to slot${pendingStack ? `: ${escapeHtml(pendingStack.definition.label)}` : " your selected skill"}. Choose an empty, unlocked slot.` : "Select a skill card in Inventory and choose Slot…, then pick an empty slot here."}</p>
      ${rows.slice(0, split).join("") || '<p class="empty-state">No skill slots available yet.</p>'}`,
    right: `<p class="journal-eyebrow">A growing collection of talents</p>
      ${rows.slice(split).join("")}
      <section class="journal-stats" aria-label="Effective stats"><h3>Effective stats</h3>
        <dl class="profile-stats">${Object.entries(state.user?.stats || {}).map(([key, value]) => `<div><dt>${escapeHtml(key.replaceAll("_", " "))}</dt><dd>${escapeHtml(value)}</dd></div>`).join("")}</dl>
        <p class="journal-note">These totals include your active bonuses.</p>
      </section>
      <p class="skills-hint">Each level unlocks another slot. Higher ranks can hold lower-rank skills. Activate a filled slot to remove its skill.</p>`,
  };
}

export function skillsView(state) {
  return modalShell({ extraClass: "journal-view skills-view", ariaLabel: "Skills", title: "Your Skills", body: journalSpreadMarkup(skillsPagesMarkup(state)) });
}
