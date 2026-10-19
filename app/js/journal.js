import { escapeHtml } from "./presentation.js";
import { withBase } from "./base-path.js";
import { memoryImageUrl } from "./api.js";

function stepMarkup(step) {
  const pct = step.amount > 0 ? Math.min(100, Math.round((step.progress / step.amount) * 100)) : 0;
  return `<li class="task-step ${step.complete ? "complete" : ""}">
    <span class="task-step-label">${escapeHtml(step.title || step.trigger)}</span>
    <span class="task-step-track"><span class="task-step-fill" style="width:${pct}%"></span></span>
    <span class="task-step-count">${step.progress}/${step.amount}</span>
  </li>`;
}

function taskMarkup(task, selected) {
  const reward = [
    task.reward.kudos ? `${task.reward.kudos} Kudos` : "",
    ...task.reward.cards,
  ].filter(Boolean).join(", ");
  const meta = [
    task.worldLabel || "",
    task.scope === "shared" ? "Shared" : "Personal",
    task.repeatable ? "Repeatable" : "",
    reward ? `Reward: ${reward}` : "",
  ].filter(Boolean).join(" · ");
  return `<article class="task-card ${selected ? "selected" : ""}">
    <button type="button" class="task-select" data-task-id="${escapeHtml(task.id)}" aria-pressed="${selected}">
      <strong>${escapeHtml(task.title)}</strong>
      <span class="task-meta">${escapeHtml(meta)}</span>
    </button>
    ${task.description ? `<p class="task-description">${escapeHtml(task.description)}</p>` : ""}
    <ol class="task-steps">${task.steps.map(stepMarkup).join("")}</ol>
  </article>`;
}

function taskGroup(label, list, emptyText, selectedId) {
  return `<section class="task-list">
    <h3>${escapeHtml(label)}</h3>
    ${list.length
      ? list.map(task => taskMarkup(task, task.id === selectedId)).join("")
      : `<div class="empty-state">${escapeHtml(emptyText)}</div>`}
  </section>`;
}

export function tasksMarkup(state) {
  const tasks = state.user?.tasks || { active: [], completed: [] };
  const selectedId = state.selection.kind === "task" ? state.selection.id : "";
  return taskGroup("Active", tasks.active, "No active tasks yet. Explore the house to begin.", selectedId)
    + taskGroup("Completed", tasks.completed, "No completed tasks yet.", selectedId);
}

function journalMonth(state) {
  const journal = state.user?.journal || { summary: {}, memories: [] };
  const summary = journal.summary || {};
  const offset = Number(state.ui.journalMonthOffset || 0);
  const now = new Date();
  const monthDate = summary.year && summary.month
    ? new Date(summary.year, summary.month - 1, 1)
    : new Date(now.getFullYear(), now.getMonth() + offset, 1);
  return { journal, summary, monthDate };
}

export function calendarMarkup(state) {
  const { summary, monthDate } = journalMonth(state);
  const year = monthDate.getFullYear();
  const month = monthDate.getMonth();
  const label = monthDate.toLocaleString("en-US", { month: "long", year: "numeric" });
  const startDay = new Date(year, month, 1).getDay();
  const dayCount = new Date(year, month + 1, 0).getDate();
  const dayCounts = summary.dayCounts || {};
  const cells = [];
  for (let index = 0; index < startDay; index += 1) cells.push('<span class="cal-cell empty" aria-hidden="true"></span>');
  for (let day = 1; day <= dayCount; day += 1) {
    const key = `${year}-${String(month + 1).padStart(2, "0")}-${String(day).padStart(2, "0")}`;
    const count = Number(dayCounts[key] || 0);
    cells.push(`<span class="cal-cell ${count ? "has-memories" : ""}" aria-label="Day ${day}, ${count} memories"><span class="cal-day">${day}</span>${count ? `<span class="cal-count">${count}</span>` : ""}</span>`);
  }
  const summaryText = `${summary.tasksCompleted || 0} tasks completed · ${summary.kudos || 0} Kudos · ${summary.newFriends || 0} new friends this month`;
  return `
    <div class="journal-calendar">
      <header class="cal-header">
        <button type="button" class="quiet" data-journal-month="-1" aria-label="Previous month">&lsaquo;</button>
        <strong>${escapeHtml(label)}</strong>
        <button type="button" class="quiet" data-journal-month="1" aria-label="Next month">&rsaquo;</button>
      </header>
      <div class="cal-grid cal-weekdays">${["S", "M", "T", "W", "T", "F", "S"].map(day => `<span>${day}</span>`).join("")}</div>
      <div class="cal-grid cal-days">${cells.join("")}</div>
      <p class="cal-progress">${escapeHtml(summaryText)}</p>
    </div>
  `;
}

function memoryDateLabel(value) {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value);
  if (!match) return value || "Unknown date";
  const date = new Date(Number(match[1]), Number(match[2]) - 1, Number(match[3]));
  return date.toLocaleDateString("en-US", { weekday: "short", month: "short", day: "numeric" });
}

export function groupMemoriesByDayAndWorld(memories) {
  const groups = [];
  const groupsByKey = new Map();
  for (const memory of memories) {
    const date = memory.localDate || memory.createdAt.slice(0, 10) || "";
    const world = memory.worldLabel || memory.worldId || "Unknown world";
    const key = `${date}\u0000${world}`;
    let group = groupsByKey.get(key);
    if (!group) {
      group = { date, world, memories: [], images: [] };
      groupsByKey.set(key, group);
      groups.push(group);
    }
    group.memories.push(memory);
    if (memory.hasImage) group.images.push(memory);
  }
  return groups;
}

function memoryEntryMarkup(memory) {
  return `<article class="memory-entry ${memory.editable ? "manual" : "game"}">
    <p class="memory-text">${escapeHtml(memory.text)}</p>
    ${memory.editable ? `<div class="memory-actions">
      <button type="button" data-memory-action="edit" data-memory-id="${escapeHtml(memory.memoryId)}">Edit</button>
      <button type="button" class="quiet" data-memory-action="delete" data-memory-id="${escapeHtml(memory.memoryId)}">Delete</button>
    </div>` : ""}
  </article>`;
}

function memorySectionMarkup(group) {
  const date = escapeHtml(group.date);
  const world = escapeHtml(group.world);
  const label = escapeHtml(memoryDateLabel(group.date));
  const count = group.images.length;
  const collageLabel = `${count} memory screenshot${count === 1 ? "" : "s"}`;
  const collage = count
    ? `<div class="memory-collage" role="group" aria-label="${collageLabel}">
      ${group.images.map(memory => `<img class="memory-collage-image" src="${escapeHtml(memoryImageUrl(memory.memoryId))}" alt="Memory screenshot from ${label} in ${world}" loading="lazy">`).join("")}
    </div>`
    : "";
  return `<section class="memory-section">
    <header class="memory-section-head">
      <h4 class="memory-section-date"><time datetime="${date}">${label}</time></h4>
      <span class="memory-section-world">${world}</span>
    </header>
    <div class="memory-section-entries">${group.memories.map(memoryEntryMarkup).join("")}</div>
    ${collage}
  </section>`;
}

export function memoriesMarkup(state) {
  const { journal } = journalMonth(state);
  const filter = state.ui.journalTagFilter || "";
  const memories = filter
    ? journal.memories.filter(memory => memory.tags.includes(`task:${filter}`))
    : journal.memories;
  const groups = groupMemoriesByDayAndWorld(memories);
  const filterBanner = filter
    ? `<p class="memory-filter">Showing memories for task <strong>${escapeHtml(filter)}</strong></p>`
    : "";
  return `
    <section class="memory-list">
      <h3>Memories <span class="memory-count">${memories.length}</span></h3>
      <img class="journal-flourish" src="${withBase("/app/assets/journal-flourish.svg")}" alt="" aria-hidden="true">
      ${filterBanner}
      ${groups.length
        ? groups.map(memorySectionMarkup).join("")
        : `<div class="empty-state">No memories this month. Type in the chat bar and choose New Memory.</div>`}
    </section>
  `;
}
