import { memoriesMarkup, tasksMarkup } from "../journal.js";
import { modalShell } from "./view-helpers.js";

export function journalView(state) {
  const tab = state.ui.journalTab || "Tasks";
  const tabs = `<div class="journal-tabs">
    <button type="button" class="${tab === "Tasks" ? "selected" : ""}" data-journal-tab="Tasks">Tasks</button>
    <button type="button" class="${tab === "Memories" ? "selected" : ""}" data-journal-tab="Memories">Memories</button>
  </div>`;
  const body = tab === "Memories" ? memoriesMarkup(state) : tasksMarkup(state);
  return modalShell({
    extraClass: "journal-view",
    ariaLabel: "Journal",
    title: "Your Journal",
    subtitleHtml: tabs,
    body: `<div class="modal-scroll">${body}</div>`,
  });
}
