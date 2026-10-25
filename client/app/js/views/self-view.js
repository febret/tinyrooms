import { decalDataUrl } from "../decals.js";
import { escapeHtml } from "../presentation.js";
import { counterBar, journalSpreadMarkup, modalShell } from "./view-helpers.js";

function titleSlotRow(slot, slotLabel, titles) {
  const unlocked = new Set(titles.unlocked || []);
  const selected = titles.selection?.[slot] || "none";
  const choices = (titles.catalog || []).filter(part => part.slot === slot && unlocked.has(part.id));
  const options = [`<option value="none"${selected === "none" ? " selected" : ""}>None</option>`];
  for (const part of choices) {
    options.push(
      `<option value="${escapeHtml(part.id)}"${selected === part.id ? " selected" : ""}>${escapeHtml(part.label)}</option>`,
    );
  }
  return `<div class="title-slot">
    <span class="title-slot-name" id="title-slot-${escapeHtml(slot)}">${escapeHtml(slotLabel)}</span>
    <select data-title-slot="${escapeHtml(slot)}" aria-labelledby="title-slot-${escapeHtml(slot)}">${options.join("")}</select>
  </div>`;
}

export function titlesMarkup(user, open) {
  const titles = user.titles || { catalog: [], unlocked: [], selection: {}, cookedCount: 0, taughtCount: 0 };
  const selection = titles.selection || {};
  const displayLabel = selection.displayLabel || user.username || "You";
  return `
      <button type="button" class="title-nameplate" data-titles-toggle="1" aria-expanded="${open ? "true" : "false"}" aria-controls="title-editor" title="${open ? "Close the title editor" : "Edit your titles"}">
        <span class="title-nameplate-label">${escapeHtml(displayLabel)}</span>
        <span class="title-nameplate-action" aria-hidden="true">${open ? "✓ Done" : "✎ Titles"}</span>
      </button>
      <div class="title-editor" id="title-editor"${open ? "" : " hidden"}>
        ${titleSlotRow("salutation", "Salutation", titles)}
        ${titleSlotRow("nickname", "Nickname", titles)}
        ${titleSlotRow("suffix", "Suffix", titles)}
        <div class="title-slot">
          <span class="title-slot-name" id="title-slot-crew">Crew name</span>
          <div class="title-crew-row" data-title-crew="1">
            <input type="text" data-title-crew-input="1" maxlength="24" value="${escapeHtml(selection.crewName || "")}" placeholder="Optional crew name" aria-labelledby="title-slot-crew">
            <button type="button" class="title-save" data-title-crew-save="1">Save</button>
          </div>
        </div>
      </div>`;
}

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
  const titlesOpen = Boolean(state.ui?.titlesOpen);
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
        ${titlesMarkup(user, titlesOpen)}
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
