import { calendarMarkup, memoriesMarkup, tasksMarkup } from "../journal.js";
import { escapeHtml } from "../presentation.js";
import { friendsPagesMarkup } from "./friends-view.js";
import { selfPagesMarkup } from "./self-view.js";
import { skillsPagesMarkup } from "./skills-view.js";
import { journalSpreadMarkup, modalShell } from "./view-helpers.js";

const JOURNAL_TABS = ["Tasks", "Memories", "Self", "Skills", "Friends"];

export function journalView(state) {
  const tab = JOURNAL_TABS.includes(state.ui?.journalTab) ? state.ui.journalTab : "Tasks";
  const tabs = `<div class="journal-tabs" role="group" aria-label="Journal sections">
    ${JOURNAL_TABS.map(label => `<button type="button" class="${tab === label ? "selected" : ""}" data-journal-tab="${label}" aria-pressed="${tab === label}">${escapeHtml(label)}</button>`).join("")}
  </div>`;
  const pageRenderers = { Self: selfPagesMarkup, Skills: skillsPagesMarkup, Friends: friendsPagesMarkup };
  const pages = pageRenderers[tab] ? pageRenderers[tab](state) : {
    leftLabel: "Calendar",
    rightLabel: tab,
    left: calendarMarkup(state),
    right: tab === "Memories" ? memoriesMarkup(state) : tasksMarkup(state),
  };
  return modalShell({
    extraClass: "journal-view",
    ariaLabel: "Journal",
    title: "Your Journal",
    subtitleHtml: tabs,
    body: journalSpreadMarkup(pages),
  });
}
