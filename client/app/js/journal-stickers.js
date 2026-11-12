import { escapeHtml } from "./presentation.js";

function metDateLabel(value) {
  const date = value ? new Date(value) : null;
  if (!date || Number.isNaN(date.getTime())) return "";
  return date.toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });
}

function stickerPicture(peep, extraClass = "") {
  return peep.imageUrl
    ? `<img class="peep-sticker-picture ${extraClass}" src="${escapeHtml(peep.imageUrl)}" alt="" loading="lazy">`
    : `<span class="peep-sticker-picture peep-sticker-placeholder ${extraClass}" aria-hidden="true">✦</span>`;
}

function vibeText(label, value) {
  return label ? `${label} (${value})` : String(value);
}

export function stickerTagsMarkup(tags) {
  if (!Array.isArray(tags) || !tags.length) return "";
  const chips = tags.map(tag => {
    const index = tag.indexOf(":");
    if (index > 0 && index < tag.length - 1) {
      const key = tag.slice(0, index);
      const value = tag.slice(index + 1);
      return `<li class="peep-sticker-tag" title="${escapeHtml(tag)}"><span class="peep-sticker-tag-key">${escapeHtml(key)}:</span> ${escapeHtml(value)}</li>`;
    }
    return `<li class="peep-sticker-tag">${escapeHtml(tag)}</li>`;
  }).join("");
  return `<ul class="peep-sticker-tags" aria-label="Tags">${chips}</ul>`;
}

export function selectedSticker(state) {
  const collection = state.user?.peepCollection;
  const peeps = collection?.peeps || [];
  const key = state.ui?.journalStickerKey || "";
  return peeps.find(peep => peep.key === key) || peeps[peeps.length - 1] || null;
}

export function stickerCollectionMarkup(state) {
  const collection = state.user?.peepCollection || { peeps: [], count: 0, milestoneSize: 10, nextMilestoneAt: 10, milestoneReward: { bops: 0, kudos: 0 } };
  const selected = selectedSticker(state);
  const size = collection.milestoneSize || 10;
  const intoMilestone = collection.count % size;
  const pct = Math.round((intoMilestone / size) * 100);
  const reward = collection.milestoneReward || { bops: 0, kudos: 0 };
  const progress = `<div class="peep-sticker-progress" aria-label="Sticker milestone progress">
    <span class="peep-sticker-count"><strong>${collection.count}</strong> peeps met</span>
    <span class="task-step-track"><span class="task-step-fill" style="width:${pct}%"></span></span>
    <span class="peep-sticker-next">Next: ${collection.nextMilestoneAt} → +${reward.bops} Bops, +${reward.kudos} Kudos</span>
  </div>`;
  if (!collection.peeps.length) {
    return `${progress}<div class="empty-state">No stickers yet. Look at or talk to peeps you meet to collect them.</div>`;
  }
  const cards = collection.peeps.map(peep => {
    const isSelected = selected?.key === peep.key;
    return `<button type="button" class="peep-sticker ${isSelected ? "selected" : ""}" data-peep-sticker="${escapeHtml(peep.key)}" aria-pressed="${isSelected}" title="${escapeHtml(peep.label)}">
      ${stickerPicture(peep)}
      <span class="peep-sticker-label">${escapeHtml(peep.label)}</span>
    </button>`;
  }).join("");
  return `${progress}<div class="peep-sticker-grid" role="group" aria-label="Sticker collection">${cards}</div>`;
}

export function stickerDetailMarkup(state) {
  const peep = selectedSticker(state);
  if (!peep) return `<div class="empty-state">Meet a peep to start your sticker collection.</div>`;
  const traits = peep.traits || {};
  const facts = [
    ["World", traits.world_label || peep.worldId],
    ["First met", [traits.room_label, metDateLabel(peep.firstMetAt)].filter(Boolean).join(" · ")],
    ["They feel", vibeText(peep.vibeLabel, peep.vibe || 0)],
    ["You feel", vibeText(peep.vibeTowardLabel, peep.vibeToward || 0)],
    ["Activity", traits.activity || ""],
    ["Actions", Array.isArray(traits.actions) ? traits.actions.join(", ") : ""],
  ].filter(([, value]) => value);
  return `<article class="peep-sticker-detail">
    ${stickerPicture(peep, "large")}
    <h3>${escapeHtml(peep.label)}</h3>
    ${peep.description ? `<p class="peep-sticker-description">${escapeHtml(peep.description)}</p>` : ""}
    ${stickerTagsMarkup(peep.tags)}
    <dl class="peep-sticker-facts">${facts.map(([name, value]) => `<div><dt>${escapeHtml(name)}</dt><dd>${escapeHtml(value)}</dd></div>`).join("")}</dl>
  </article>`;
}
