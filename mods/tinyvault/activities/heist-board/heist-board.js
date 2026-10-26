import { crewSummary, jobSummary, normalizeBoard } from "./board.js";

const panel = document.querySelector("#panel");
const heatBadge = document.querySelector("#heat-badge");
const hint = document.querySelector("#hint");
const connection = document.querySelector("#connection");
const tabs = [...document.querySelectorAll(".board-tabs button")];

let tab = "jobs";
let board = normalizeBoard(null);

function escape(value) {
  return window.TinyActivity ? window.TinyActivity.escape(value) : String(value ?? "");
}

function button(label, command, primary = false) {
  const element = document.createElement("button");
  element.type = "button";
  element.textContent = label;
  if (primary) element.className = "primary";
  element.onclick = () => void send(command);
  return element;
}

async function send(commandText) {
  if (!window.TinyActivity) return;
  try {
    const response = await window.TinyActivity.command(commandText);
    if (response?.payload?.board) board = normalizeBoard(response.payload);
    if (response?.payload?.status) board.active = response.payload.status;
    render();
  } catch (error) {
    window.TinyActivity.toast(error instanceof Error ? error.message : String(error), true);
  }
}

function renderJobs() {
  panel.textContent = "";
  for (const job of board.jobs) {
    const card = document.createElement("article");
    card.className = "board-job";
    const title = document.createElement("h2");
    title.textContent = job.label;
    const meta = document.createElement("p");
    meta.className = "board-meta";
    meta.textContent = `${jobSummary(job)} · crew ${job.min_crew}-${job.max_crew} · deposit ${job.deposit}`;
    const description = document.createElement("p");
    description.textContent = job.description || "";
    const actions = document.createElement("div");
    actions.className = "board-actions";
    if (job.locked) {
      const locked = document.createElement("p");
      locked.className = "board-locked";
      locked.textContent = `Needs heat ${job.heat_tier}.`;
      actions.append(locked);
    } else {
      actions.append(button(`Start (${job.deposit} Bops)`, `.heist start ${job.id}`, true));
    }
    actions.append(button("Join", ".heist join"));
    actions.append(button("Enter", ".heist enter"));
    card.append(title, meta, description, actions);
    panel.append(card);
  }
  if (!board.jobs.length) {
    const empty = document.createElement("p");
    empty.className = "empty";
    empty.textContent = "No jobs posted. Bribe the fence with patience.";
    panel.append(empty);
  }
}

function renderCrew() {
  panel.textContent = "";
  const summary = document.createElement("p");
  summary.textContent = crewSummary(board.active);
  const actions = document.createElement("div");
  actions.className = "board-actions";
  actions.append(button("Refresh", ".heist status"));
  actions.append(button("Enter bank", ".heist enter", true));
  actions.append(button("Leave crew", ".heist leave"));
  actions.append(button("Abort", ".heist abort"));
  panel.append(summary, actions);
}

function renderLoadout() {
  panel.textContent = "";
  for (const tool of board.tools) {
    const row = document.createElement("article");
    row.className = "board-row";
    const title = document.createElement("h2");
    title.textContent = `${tool.label}${tool.owned ? " (owned)" : ""}`;
    const meta = document.createElement("p");
    meta.className = "board-meta";
    meta.textContent = `${tool.kind} · ${tool.price} Bops${tool.ready_in_seconds ? ` · ready in ${tool.ready_in_seconds}s` : ""}`;
    const actions = document.createElement("div");
    actions.className = "board-actions";
    if (!tool.owned) actions.append(button(`Buy (${tool.price})`, `.heist buy ${tool.id}`, true));
    row.append(title, meta, actions);
    panel.append(row);
  }
}

function renderBots() {
  panel.textContent = "";
  for (const bot of board.bots) {
    const row = document.createElement("article");
    row.className = "board-row";
    const title = document.createElement("h2");
    title.textContent = `${bot.label}${bot.hired ? " (hired)" : ""}`;
    const description = document.createElement("p");
    description.textContent = bot.description || "";
    const actions = document.createElement("div");
    actions.className = "board-actions";
    if (!bot.hired) actions.append(button(`Hire (${bot.price})`, `.heist bot ${bot.id}`, true));
    row.append(title, description, actions);
    panel.append(row);
  }
}

function render() {
  heatBadge.textContent = `Heat ${board.heat}`;
  for (const element of tabs) element.setAttribute("aria-selected", String(element.dataset.tab === tab));
  if (tab === "crew") renderCrew();
  else if (tab === "loadout") renderLoadout();
  else if (tab === "bots") renderBots();
  else renderJobs();
}

for (const element of tabs) {
  element.onclick = () => {
    tab = element.dataset.tab;
    render();
  };
}

async function refresh() {
  if (!window.TinyActivity) {
    connection.textContent = "Open this activity from Tinyrooms.";
    return;
  }
  try {
    const response = await window.TinyActivity.command(".heist jobs");
    if (response?.payload?.board) board = normalizeBoard(response.payload);
    connection.textContent = "";
    hint.textContent = response?.message || hint.textContent;
  } catch (error) {
    connection.textContent = error instanceof Error ? error.message : String(error);
  }
  render();
}

if (window.TinyActivity) {
  window.TinyActivity.subscribe(() => {
    if (connection.textContent) connection.textContent = "";
  });
}

void refresh();
