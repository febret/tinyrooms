import { calendarMarkup, memoriesMarkup, tasksMarkup } from "../journal.js";
import { escapeHtml } from "../presentation.js";
import { modalShell } from "./view-helpers.js";

export function journalView(state) {
  const tab = state.ui.journalTab || "Tasks";
  const tabs = `<div class="journal-tabs">
    <button type="button" class="${tab === "Tasks" ? "selected" : ""}" data-journal-tab="Tasks">Tasks</button>
    <button type="button" class="${tab === "Memories" ? "selected" : ""}" data-journal-tab="Memories">Memories</button>
  </div>`;
  const pageLabel = tab === "Memories" ? "Memories" : "Tasks";
  const body = tab === "Memories" ? memoriesMarkup(state) : tasksMarkup(state);
  return modalShell({
    extraClass: "journal-view",
    ariaLabel: "Journal",
    title: "Your Journal",
    subtitleHtml: tabs,
    body: `
      <div class="journal-book">
        <div class="journal-pages">
          <section class="journal-page journal-page-left" aria-label="Calendar">
            <div class="journal-page-inner">${calendarMarkup(state)}</div>
          </section>
          <div class="journal-spine" aria-hidden="true"></div>
          <section class="journal-page journal-page-right" aria-label="${escapeHtml(pageLabel)}">
            <div class="journal-page-inner">${body}</div>
          </section>
        </div>
      </div>
    `,
  });
}
