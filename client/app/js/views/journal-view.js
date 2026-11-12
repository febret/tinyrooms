import { calendarMarkup, memoriesMarkup, tasksMarkup } from "../journal.js";
import { stickerCollectionMarkup, stickerDetailMarkup } from "../journal-stickers.js";
import { escapeHtml } from "../presentation.js";
import { journalSpreadMarkup, modalShell } from "./view-helpers.js";

export const JOURNAL_TABS = ["Tasks", "Memories", "Stickers"];

function rightPage(state, tab) {
  if (tab === "Memories") return memoriesMarkup(state);
  if (tab === "Stickers") return stickerCollectionMarkup(state);
  return tasksMarkup(state);
}

export function journalView(state) {
  const tab = JOURNAL_TABS.includes(state.ui?.journalTab) ? state.ui.journalTab : "Tasks";
  const tabs = `<div class="journal-tabs-row"><div class="journal-tabs" role="group" aria-label="Journal sections">
    ${JOURNAL_TABS.map(label => `<button type="button" class="${tab === label ? "selected" : ""}" data-journal-tab="${label}" aria-pressed="${tab === label}">${escapeHtml(label)}</button>`).join("")}
  </div><button type="button" class="quiet journal-close" data-close-view="1">Close</button></div>`;
  const stickers = tab === "Stickers";
  const pages = {
    leftLabel: stickers ? "Sticker" : "Calendar",
    rightLabel: stickers ? "Sticker Collection" : tab,
    left: stickers ? stickerDetailMarkup(state) : calendarMarkup(state),
    right: rightPage(state, tab),
  };
  return modalShell({
    extraClass: "journal-view",
    ariaLabel: "Journal",
    title: "Your Journal",
    hideClose: true,
    subtitleHtml: tabs,
    body: journalSpreadMarkup(pages),
  });
}
