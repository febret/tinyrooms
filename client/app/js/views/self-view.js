import { decalDataUrl } from "../decals.js";
import { escapeHtml } from "../presentation.js";
import { counterBar, journalSpreadMarkup, modalShell } from "./view-helpers.js";

export function selfPagesMarkup(state) {
  const user = state.user || {};
  const counters = user.counters || {};
  const decalUrl = decalDataUrl(user.id, counters.decals);
  const kudos = Number.isFinite(user.kudos) ? user.kudos : 0;
  const cost = user.kudosToNext;
  const hasNextLevel = Number.isFinite(cost) && cost >= 0;
  const canLevel = hasNextLevel && kudos >= cost;
  const statuses = (user.statuses || []).map(id => {
    const definition = user.statusDefinitions?.[id];
    return `<li class="journal-status" title="${escapeHtml(definition?.description || "")}">
      <span aria-hidden="true">${escapeHtml(definition?.icon || "•")}</span>
      <span>${escapeHtml(definition?.label || id)}</span>
    </li>`;
  }).join("");
  return {
    leftLabel: "Self identity and level",
    rightLabel: "Self wellbeing and stats",
    left: `
      <p class="journal-eyebrow">A little about you</p>
      <div class="profile-identity">
        ${user.stickerUrl
          ? `<span class="profile-sticker-frame">
              <img class="profile-sticker" src="${escapeHtml(user.stickerUrl)}" alt="${escapeHtml(user.username || "Your")} sticker">
              ${decalUrl ? `<img class="profile-sticker-decals" src="${escapeHtml(decalUrl)}" alt="" aria-hidden="true">` : ""}
            </span>`
          : '<div class="journal-sticker-placeholder" aria-hidden="true">✦</div>'}
        <h3 class="journal-name">${escapeHtml(user.username || "You")}</h3>
        <p class="journal-level">Level ${escapeHtml(user.level ?? 0)} · ${escapeHtml(user.levelLabel || "Guest")}</p>
      </div>
      <section class="journal-kudos" aria-label="Level progress">
        <h3>Kudos <span class="journal-balance">${escapeHtml(kudos)}</span></h3>
        ${hasNextLevel ? counterBar("Next level", kudos, cost, { tone: "counter-kudos", valueText: `${kudos} / ${cost} Kudos` }) : '<p class="journal-note">Maximum level reached. Keep collecting Kudos!</p>'}
        <p class="journal-note">${hasNextLevel ? (canLevel ? "Ready for your next chapter!" : `${escapeHtml(Math.max(0, cost - kudos))} more Kudos to your next level.`) : "You're at the top of your game."}</p>
      </section>
      <div class="profile-actions">
        <button type="button" class="primary" data-level-up="1" ${canLevel ? "" : "disabled"}>${hasNextLevel ? `Level Up (${escapeHtml(cost)} Kudos)` : "Maximum Level"}</button>
        <button type="button" class="positive" data-swap-sticker="1">Swap Sticker…</button>
      </div>`,
    right: `
      <p class="journal-eyebrow">Check in with yourself</p>
      <h3 class="journal-page-title">Feeling good?</h3>
      <div class="profile-counters">
        ${counterBar("Health", counters.health ?? 0, counters.maxHealth ?? 0, { tone: "counter-health" })}
        ${counterBar("Energy", counters.energy ?? 0, counters.maxEnergy ?? 0, { tone: "counter-energy" })}
        ${counterBar("Cleanliness", counters.cleanliness ?? 0, counters.maxCleanliness ?? 0, { tone: "counter-cleanliness" })}
      </div>
      <section class="journal-statuses" aria-label="Current statuses"><h3>Right now</h3>
        ${statuses ? `<ul>${statuses}</ul>` : '<p class="journal-note">Feeling fine. No active statuses.</p>'}
      </section>
      <section class="journal-stats" aria-label="Effective stats"><h3>Your stats</h3>
        <dl class="profile-stats">${Object.entries(user.stats || {}).map(([key, value]) => `<div><dt>${escapeHtml(key.replaceAll("_", " "))}</dt><dd>${escapeHtml(value)}</dd></div>`).join("")}</dl>
      </section>
      <dl class="journal-wallet"><div><dt>Bops</dt><dd>${escapeHtml(user.bops ?? 0)}</dd></div></dl>`,
  };
}

export function selfView(state) {
  return modalShell({ extraClass: "journal-view self-view", ariaLabel: "Self", title: "Your Self", body: journalSpreadMarkup(selfPagesMarkup(state)) });
}
