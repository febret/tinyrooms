import { escapeHtml } from "../presentation.js";
import { counterBar, modalShell, statusIconsMarkup } from "./view-helpers.js";

export function selfView(state) {
  const counters = state.user?.counters || {};
  const statuses = state.user?.statuses || [];
  const definitions = state.user?.statusDefinitions || {};
  const kudosToNext = state.user?.kudosToNext;
  const canLevel = typeof kudosToNext === "number" && (state.user?.kudos || 0) >= kudosToNext;
  return modalShell({
    extraClass: "self-view",
    ariaLabel: "Self",
    title: escapeHtml(state.user?.username || "You"),
    subtitle: `<p>Level ${state.user?.level || 0} · ${escapeHtml(state.user?.levelLabel || "Guest")}</p>`,
    body: `
      <div class="modal-scroll">
        <div class="profile-identity">
          ${state.user?.stickerUrl ? `<img class="profile-sticker" src="${escapeHtml(state.user.stickerUrl)}" alt="${escapeHtml(state.user.username)}'s sticker">` : ""}
          <div class="profile-actions">
            <button type="button" class="primary" data-level-up="1" ${canLevel ? "" : "disabled"}>Level Up${typeof kudosToNext === "number" ? ` (${kudosToNext} Kudos)` : ""}</button>
            <button type="button" class="positive" data-swap-sticker="1">Swap Sticker…</button>
          </div>
        </div>
        <div class="profile-statuses">${statuses.length ? statusIconsMarkup(statuses, definitions) : "<span class='muted'>Feeling fine.</span>"}</div>
        <div class="profile-counters">
          ${counterBar("Health", counters.health || 0, counters.maxHealth || 0)}
          ${counterBar("Energy", counters.energy || 0, counters.maxEnergy || 0)}
          ${counterBar("Cleanliness", counters.cleanliness || 0, counters.maxCleanliness || 0)}
        </div>
        <dl class="profile-stats">
          ${Object.entries(state.user?.stats || {}).map(([key, value]) => `<div><dt>${escapeHtml(key.replaceAll("_", " "))}</dt><dd>${escapeHtml(value)}</dd></div>`).join("")}
          <div><dt>Kudos</dt><dd>${state.user?.kudos || 0}</dd></div>
          <div><dt>Bops</dt><dd>${state.user?.bops || 0}</dd></div>
        </dl>
      </div>
    `,
  });
}
