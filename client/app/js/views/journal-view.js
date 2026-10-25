import { calendarMarkup, memoriesMarkup, tasksMarkup } from "../journal.js";
import { escapeHtml } from "../presentation.js";
import { journalSpreadMarkup, modalShell } from "./view-helpers.js";

export const JOURNAL_TABS = ["Tasks", "Memories"];

export function journalView(state) {
  const tab = JOURNAL_TABS.includes(state.ui?.journalTab) ? state.ui.journalTab : "Tasks";
  const tabs = `<div class="journal-tabs-row"><div class="journal-tabs" role="group" aria-label="Journal sections">
    ${JOURNAL_TABS.map(label => `<button type="button" class="${tab === label ? "selected" : ""}" data-journal-tab="${label}" aria-pressed="${tab === label}">${escapeHtml(label)}</button>`).join("")}
  </div><button type="button" class="quiet journal-close" data-close-view="1">Close</button></div>`;
  const pages = {
    leftLabel: "Calendar",
    rightLabel: tab,
    left: calendarMarkup(state),
    right: tab === "Memories" ? memoriesMarkup(state) : tasksMarkup(state),
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
