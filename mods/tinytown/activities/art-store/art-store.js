import { renderWhiteboardCanvas } from "../../app/js/surface-canvas.js";

const Tiny = window.TinyActivity;

const wallet = document.getElementById("wallet");
const roomLabel = document.getElementById("room-label");
const connection = document.getElementById("connection");
const tabs = document.getElementById("tabs");
const floorsPanel = document.getElementById("floors-panel");
const artPanel = document.getElementById("art-panel");
const floorGrid = document.getElementById("floor-grid");
const artGrid = document.getElementById("art-grid");
const capacity = document.getElementById("capacity");
const back = document.getElementById("back");

const ui = {
  tab: "floors",
  data: null,
  busy: false,
  started: false,
  pending: "",
};

function escape(value) {
  return Tiny.escape(value ?? "");
}

function image(url) {
  return Tiny.image(url);
}

function money(value) {
  return Number(value || 0).toLocaleString();
}

function renderWallet() {
  wallet.textContent = money(Tiny.state?.user?.bops ?? ui.data?.wallet ?? 0);
}

function showError(error) {
  connection.textContent = error instanceof Error ? error.message : String(error);
  Tiny.toast(connection.textContent, true);
}

function setTab(tab) {
  ui.tab = tab === "art" ? "art" : "floors";
  for (const button of tabs.querySelectorAll("[data-tab]")) {
    button.setAttribute("aria-selected", String(button.dataset.tab === ui.tab));
  }
  floorsPanel.hidden = ui.tab !== "floors";
  artPanel.hidden = ui.tab !== "art";
}

function floorCard(floor) {
  const bops = Number(Tiny.state?.user?.bops ?? ui.data?.wallet ?? 0);
  const affordable = floor.unlocked || bops >= floor.price;
  const pending = ui.pending === `floor:${floor.id}`;
  const action = floor.current
    ? '<button type="button" class="applied" disabled>On this floor</button>'
    : pending
      ? `<button type="button" class="confirm" data-confirm-floor="${escape(floor.id)}">Confirm · ${money(floor.price)} Bops</button>
         <button type="button" class="quiet" data-cancel="1">Cancel</button>`
      : `<button type="button" class="${floor.unlocked ? "" : "primary"}" data-floor="${escape(floor.id)}"${affordable ? "" : " disabled"}>
           ${floor.unlocked ? "Apply" : `Buy · ${money(floor.price)} Bops`}
         </button>`;
  return `<article class="art-card" role="listitem">
    <div class="art-card-preview">
      <img src="${escape(image(floor.image_url))}" alt="${escape(floor.label)} floor texture" loading="lazy">
      ${floor.current ? '<span class="art-current">Currently fitted</span>' : ""}
      <span class="art-price">${floor.unlocked ? "Owned" : `${money(floor.price)} Bops`}</span>
    </div>
    <div class="art-card-body">
      <h3>${escape(floor.label)}</h3>
      <p>${escape(floor.description)}</p>
      <div class="art-tags">${floor.tags.map(tag => `<span>${escape(tag)}</span>`).join("")}</div>
      <div class="art-card-actions">${action}</div>
    </div>
  </article>`;
}

function artCard(piece) {
  const unlocked = (ui.data?.unlocked_art || []).includes(piece.id);
  const bops = Number(Tiny.state?.user?.bops ?? ui.data?.wallet ?? 0);
  const full = Number(ui.data?.whiteboards || 0) >= Number(ui.data?.max_whiteboards || 4);
  const affordable = unlocked || bops >= piece.price;
  const pending = ui.pending === `art:${piece.id}`;
  const action = full
    ? '<button type="button" disabled>Walls full · remove a piece</button>'
    : pending
      ? `<button type="button" class="confirm" data-confirm-art="${escape(piece.id)}">Confirm · ${money(piece.price)} Bops</button>
         <button type="button" class="quiet" data-cancel="1">Cancel</button>`
      : `<button type="button" class="${unlocked ? "" : "primary"}" data-art="${escape(piece.id)}"${affordable ? "" : " disabled"}>
           ${unlocked ? "Hang another" : `Buy & hang · ${money(piece.price)} Bops`}
         </button>`;
  return `<article class="art-card" role="listitem">
    <div class="art-card-preview">
      <canvas data-art-canvas="${escape(piece.id)}" width="512" height="320" aria-label="${escape(piece.label)} preview"></canvas>
      <span class="art-price">${unlocked ? "Owned" : `${money(piece.price)} Bops`}</span>
    </div>
    <div class="art-card-body">
      <h3>${escape(piece.label)}</h3>
      <p>${escape(piece.description)}</p>
      <div class="art-tags">${piece.tags.map(tag => `<span>${escape(tag)}</span>`).join("")}</div>
      <div class="art-card-actions">${action}</div>
    </div>
  </article>`;
}

function paintPreviews() {
  for (const piece of ui.data?.art || []) {
    const canvas = artGrid.querySelector(`[data-art-canvas="${CSS.escape(piece.id)}"]`);
    if (!canvas) continue;
    const source = renderWhiteboardCanvas(piece.surface || {});
    const context = canvas.getContext("2d");
    if (!context) continue;
    context.clearRect(0, 0, canvas.width, canvas.height);
    context.drawImage(source, 0, 0, canvas.width, canvas.height);
  }
}

function render() {
  renderWallet();
  if (!ui.data) return;
  roomLabel.textContent = `${ui.data.room?.label || "Your room"} · ${ui.data.room?.house || "TinyTown"}`;
  document.getElementById("floors-panel").querySelector(".art-hint").textContent =
    "One finish per room. Buy once, reapply whenever the mood changes.";
  floorGrid.innerHTML = (ui.data.floors || []).map(floorCard).join("") ||
    '<p class="empty">No floor finishes are available.</p>';
  artGrid.innerHTML = (ui.data.art || []).map(artCard).join("") ||
    '<p class="empty">No art is available.</p>';
  const used = Number(ui.data.whiteboards || 0);
  const max = Number(ui.data.max_whiteboards || 4);
  capacity.textContent = `${used} of ${max} wall spaces used. Art hangs on editable whiteboards.`;
  setTab(ui.tab);
  paintPreviews();
}

async function refresh() {
  const response = await Tiny.command(".tinytown decor");
  ui.data = response.payload || null;
  connection.textContent = "";
  render();
}

async function applyFloor(floorId) {
  if (ui.busy) return;
  ui.busy = true;
  try {
    const response = await Tiny.command(`.tinytown floor ${floorId}`);
    ui.pending = "";
    ui.busy = false;
    Tiny.celebrate();
    Tiny.toast(response.message || "Floor fitted.");
    await refresh();
  } catch (error) {
    ui.busy = false;
    showError(error);
  }
}

async function hangArt(artId) {
  if (ui.busy) return;
  ui.busy = true;
  try {
    const response = await Tiny.command(`.tinytown hang ${artId}`);
    ui.pending = "";
    ui.busy = false;
    Tiny.celebrate();
    Tiny.toast(response.message || "Art hung.");
    await refresh();
  } catch (error) {
    ui.busy = false;
    showError(error);
  }
}

tabs.addEventListener("click", event => {
  const button = event.target.closest("[data-tab]");
  if (button) setTab(button.dataset.tab);
});

floorGrid.addEventListener("click", event => {
  const floor = event.target.closest("[data-floor]");
  if (floor) {
    const item = (ui.data?.floors || []).find(entry => entry.id === floor.dataset.floor);
    if (item?.unlocked) {
      void applyFloor(item.id);
    } else {
      ui.pending = `floor:${item?.id || ""}`;
      render();
    }
    return;
  }
  const confirm = event.target.closest("[data-confirm-floor]");
  if (confirm) {
    void applyFloor(confirm.dataset.confirmFloor);
    return;
  }
  if (event.target.closest("[data-cancel]")) {
    ui.pending = "";
    render();
  }
});

artGrid.addEventListener("click", event => {
  const art = event.target.closest("[data-art]");
  if (art) {
    const piece = (ui.data?.art || []).find(entry => entry.id === art.dataset.art);
    if ((ui.data?.unlocked_art || []).includes(piece?.id)) {
      void hangArt(piece.id);
    } else {
      ui.pending = `art:${piece?.id || ""}`;
      render();
    }
    return;
  }
  const confirm = event.target.closest("[data-confirm-art]");
  if (confirm) {
    void hangArt(confirm.dataset.confirmArt);
    return;
  }
  if (event.target.closest("[data-cancel]")) {
    ui.pending = "";
    render();
  }
});

back.addEventListener("click", async () => {
  try {
    await Tiny.command(".tinytown");
  } catch (error) {
    showError(error);
  }
});

Tiny.subscribe(() => {
  renderWallet();
  if (!ui.started) {
    ui.started = true;
    refresh().catch(showError);
  }
});

window.setTimeout(() => {
  if (!ui.started) connection.textContent = "Waiting for Tinyrooms…";
}, 600);
