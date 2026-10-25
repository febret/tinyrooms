import { decalDataUrl } from "../decals.js";
import { escapeHtml } from "../presentation.js";
import { findInventoryCard } from "../state.js";
import { titlesMarkup } from "./self-view.js";
import { counterBar, modalShell } from "./view-helpers.js";

function skillGridMarkup(state, pending) {
  const slots = state.user?.skills || [];
  const ranks = [...new Set(slots.map(slot => slot.rank))];
  if (!ranks.length) return '<p class="id-empty">No skill slots available yet.</p>';
  return `<div class="id-skills-grid">${ranks.map(rank => {
    const ranked = slots.filter(slot => slot.rank === rank);
    return `<section class="id-skill-row" aria-label="${escapeHtml(rank)} skills">
      <h4>${escapeHtml(rank)}</h4>
      <div class="id-skill-slots">${ranked.map(slot => {
        const stack = slot.stackId ? findInventoryCard(state, slot.stackId) : null;
        const selected = Boolean(stack && state.selection?.kind === "inventory-card" && state.selection.id === stack.stackId);
        const description = !slot.unlocked ? `Locked ${rank} slot ${slot.index + 1}. Unlocks at level ${slot.index + 1}.`
          : slot.stackId ? `${stack?.definition.label || "Slotted skill"}, ${rank} slot ${slot.index + 1}. Activate to remove it.`
            : `Empty ${rank} slot ${slot.index + 1}.${pending ? " Place the selected skill here." : " Click to choose a skill card."}`;
        return `<button type="button" class="id-skill-slot ${slot.unlocked ? "" : "locked"} ${slot.stackId ? "filled" : ""} ${selected ? "selected" : ""}"
          data-skill-slot="${escapeHtml(slot.index)}" data-stack-id="${escapeHtml(slot.stackId || "")}"
          aria-label="${escapeHtml(description)}" title="${escapeHtml(description)}" ${slot.unlocked ? "" : "disabled"}>
          ${stack ? `<img src="${escapeHtml(stack.definition.imageUrl)}" alt="">` : `<span aria-hidden="true">${!slot.unlocked ? "🔒" : slot.stackId ? "◆" : "+"}</span>`}
        </button>`;
      }).join("")}</div>
    </section>`;
  }).join("")}</div>`;
}

function selfFaceMarkup(state) {
  const user = state.user || {};
  const counters = user.counters || {};
  // Prefer the live self-peep presence art; the profile sticker lags until it
  // is confirmed, while room presence may already carry the artwork.
  const selfPeep = (state.room?.occupants || []).find(peep => peep.id === user.id) || null;
  const photoUrl = selfPeep?.stickerUrl || user.stickerUrl || "";
  const decalUrl = decalDataUrl(user.id, counters.decals);
  const kudos = Number.isFinite(user.kudos) ? user.kudos : 0;
  const cost = user.kudosToNext;
  const hasNextLevel = Number.isFinite(cost) && cost >= 0;
  const canLevel = hasNextLevel && kudos >= cost;
  const statuses = (user.statuses || []).map(id => {
    const definition = user.statusDefinitions?.[id];
    return `<li title="${escapeHtml(definition?.description || "")}"><span aria-hidden="true">${escapeHtml(definition?.icon || "•")}</span><span>${escapeHtml(definition?.label || id)}</span></li>`;
  }).join("");
  const titlesOpen = Boolean(state.ui?.titlesOpen);
  return `
    <div class="id-photo">
      ${photoUrl
        ? `<img src="${escapeHtml(photoUrl)}" alt="${escapeHtml(user.username || "Your")} sticker" data-id-photo="1">
           ${decalUrl ? `<img class="id-photo-decals" src="${escapeHtml(decalUrl)}" alt="" aria-hidden="true">` : ""}`
        : '<span class="id-photo-placeholder" aria-hidden="true">✦</span>'}
      <span class="id-photo-caption">ID PHOTO</span>
    </div>
    <div class="id-fields">
      <p class="id-brand">TINYROOMS • RESIDENT ID</p>
      <h3 class="id-name">${escapeHtml(user.username || "You")}</h3>
      <p class="id-level">LEVEL ${escapeHtml(user.level ?? 0)} · ${escapeHtml(user.levelLabel || "Guest")}</p>
      ${titlesMarkup(user, titlesOpen)}
      <div class="id-kudos">
        <span class="id-kudos-label">KUDOS ${escapeHtml(kudos)}${hasNextLevel ? ` / ${escapeHtml(cost)}` : " · MAX"}</span>
        ${hasNextLevel ? counterBar("Next level", kudos, cost, { tone: "counter-kudos", valueText: `${kudos}/${cost}` }) : '<p class="id-note">Maximum level reached.</p>'}
      </div>
      <div class="id-counters">
        ${counterBar("Health", counters.health ?? 0, counters.maxHealth ?? 0, { tone: "counter-health" })}
        ${counterBar("Energy", counters.energy ?? 0, counters.maxEnergy ?? 0, { tone: "counter-energy" })}
        ${counterBar("Clean", counters.cleanliness ?? 0, counters.maxCleanliness ?? 0, { tone: "counter-cleanliness" })}
      </div>
      ${statuses ? `<ul class="id-statuses">${statuses}</ul>` : '<p class="id-note">No active statuses.</p>'}
      <dl class="id-stats">${Object.entries(user.stats || {}).map(([key, value]) => `<div><dt>${escapeHtml(key.replaceAll("_", " "))}</dt><dd>${escapeHtml(value)}</dd></div>`).join("")}</dl>
      <p class="id-wallet">BOPS <strong>${escapeHtml(user.bops ?? 0)}</strong></p>
      <div class="id-actions">
        <button type="button" class="primary" data-level-up="1" ${canLevel ? "" : "disabled"}>${hasNextLevel ? `Level Up (${escapeHtml(cost)})` : "Maximum Level"}</button>
        <button type="button" data-swap-sticker="1">Swap Sticker…</button>
      </div>
    </div>`;
}

function skillsFaceMarkup(state) {
  const pending = state.views?.skillStackId || null;
  const pendingStack = pending ? findInventoryCard(state, pending) : null;
  return `
    <div class="id-fields id-fields-back">
      <p class="id-brand">TINYROOMS • SKILLS</p>
      <h3 class="id-name">Skill Clearance</h3>
      <p class="id-note" ${pending ? 'role="status"' : ""}>${pending ? `Ready to slot${pendingStack ? `: ${escapeHtml(pendingStack.definition.label)}` : ""}. Choose an empty, unlocked slot.` : "Click an empty, unlocked slot to choose a skill card."}</p>
      ${skillGridMarkup(state, pending)}
      <dl class="id-stats">${Object.entries(state.user?.stats || {}).map(([key, value]) => `<div><dt>${escapeHtml(key.replaceAll("_", " "))}</dt><dd>${escapeHtml(value)}</dd></div>`).join("")}</dl>
      <p class="id-note">Each level unlocks another slot. Higher ranks can hold lower-rank skills.</p>
    </div>`;
}

export function idCardView(state) {
  const side = state.ui?.idCardSide === "skills" ? "skills" : "self";
  const showingSkills = side === "skills";
  const flip = `<div class="id-card-actions"><button type="button" data-id-flip="1" aria-label="${showingSkills ? "Flip card to identity side" : "Flip card to skills side"}">⇄ Flip to ${showingSkills ? "ID" : "Skills"}</button></div>`;
  return modalShell({
    extraClass: "id-card-view",
    ariaLabel: "Identity card",
    title: "Your ID Card",
    subtitleHtml: flip,
    body: `
      <div class="id-card-scene">
        <div class="id-card ${showingSkills ? "flipped" : ""}">
          <section class="id-face id-front" aria-label="Identity side">${selfFaceMarkup(state)}</section>
          <section class="id-face id-back" aria-label="Skills side" aria-hidden="${showingSkills ? "false" : "true"}">${skillsFaceMarkup(state)}</section>
        </div>
      </div>`,
  });
}
