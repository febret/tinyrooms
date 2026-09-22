import { escapeHtml } from "../presentation.js";
import { modalShell } from "./view-helpers.js";

function calendarMarkup(monthDate) {
  const year = monthDate.getFullYear();
  const month = monthDate.getMonth();
  const label = monthDate.toLocaleString("en-US", { month: "long", year: "numeric" });
  const startDay = new Date(year, month, 1).getDay();
  const dayCount = new Date(year, month + 1, 0).getDate();
  const cells = [];
  for (let index = 0; index < startDay; index += 1) cells.push('<span class="cal-cell empty" aria-hidden="true"></span>');
  for (let day = 1; day <= dayCount; day += 1) {
    cells.push(`<span class="cal-cell" aria-label="Day ${day}, 0 memories"><span class="cal-day">${day}</span><span class="cal-count">0</span></span>`);
  }
  return `
    <div class="journal-calendar">
      <header class="cal-header">
        <button type="button" class="quiet" data-journal-month="-1" aria-label="Previous month">&lsaquo;</button>
        <strong>${escapeHtml(label)}</strong>
        <button type="button" class="quiet" data-journal-month="1" aria-label="Next month">&rsaquo;</button>
      </header>
      <div class="cal-grid cal-weekdays">${["S", "M", "T", "W", "T", "F", "S"].map(day => `<span>${day}</span>`).join("")}</div>
      <div class="cal-grid cal-days">${cells.join("")}</div>
      <p class="cal-progress">0 tasks completed · 0 Kudos · 0 new friends this month</p>
    </div>
  `;
}

export function journalView(state) {
  const tab = state.ui.journalTab || "Tasks";
  if (tab === "Memories") {
    const offset = Number(state.ui.journalMonthOffset || 0);
    const now = new Date();
    const monthDate = new Date(now.getFullYear(), now.getMonth() + offset, 1);
    return modalShell({
      extraClass: "journal-view",
      ariaLabel: "Journal",
      title: "Your Journal",
      subtitleHtml: `<div class="journal-tabs"><button type="button" class="${tab === "Tasks" ? "selected" : ""}" data-journal-tab="Tasks">Tasks</button><button type="button" class="selected" data-journal-tab="Memories">Memories</button></div>`,
      body: `
        <div class="modal-scroll">
          ${calendarMarkup(monthDate)}
          <section class="memory-list"><h3>Memories</h3><div class="empty-state">No memories yet. Memories arrive with the next milestone.</div></section>
        </div>
      `,
    });
  }
  return modalShell({
    extraClass: "journal-view",
    ariaLabel: "Journal",
    title: "Your Journal",
    subtitleHtml: `<div class="journal-tabs"><button type="button" class="selected" data-journal-tab="Tasks">Tasks</button><button type="button" class="${tab === "Memories" ? "selected" : ""}" data-journal-tab="Memories">Memories</button></div>`,
    body: `
      <div class="modal-scroll">
        <section class="task-list">
          <div class="empty-state">No tasks yet. Tasks arrive with the next milestone.</div>
        </section>
      </div>
    `,
  });
}
