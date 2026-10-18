import { GRADE_COUNT, floorsOf, gradeName, isAcquirable } from "./classroom-floors.js";

const Tiny = window.TinyActivity;

const floorsEl = document.querySelector("#floors");
const bopsLabel = document.querySelector("#bops");
const myDoorButton = document.querySelector("#my-door");
const getDoorButton = document.querySelector("#get-door");
const designer = document.querySelector("#designer");
const designerClose = document.querySelector("#designer-close");
const designerSave = document.querySelector("#designer-save");
const preview = document.querySelector("#preview");
const controls = document.querySelector("#controls");
const lockInput = document.querySelector("#lock");
const connection = document.querySelector("#connection");

const BASE_PATH = window.__TR_BASE__ || "";

function withBase(path) {
  if (!BASE_PATH || typeof path !== "string" || !path.startsWith("/") || path.startsWith("//") || path.startsWith(`${BASE_PATH}/`)) return path;
  return `${BASE_PATH}${path}`;
}

const ASSET_ROOT = `${BASE_PATH}/activities/classrooms/assets/`;

const state = {
  user: null,
  room: null,
  catalog: null,
  doors: [],
  cost: 10,
  maxGrade: GRADE_COUNT,
  ownDoor: null,
  draft: null,
  started: false,
};

const assetCache = new Map();
let renderToken = 0;
let buyButtonPlaced = false;

function quote(value) {
  if (value === "") return '""';
  if (/^[A-Za-z0-9_.-]+$/.test(value)) return value;
  return `"${value.replace(/(["\\])/g, "\\$1")}"`;
}

function dimension(dimensionId) {
  return state.catalog?.dimensions?.find(entry => entry.id === dimensionId) || null;
}

function optionFor(dimensionId, optionId) {
  const entry = dimension(dimensionId);
  return entry?.options?.find(option => option.id === optionId) || null;
}

function colorValue(dimensionId, optionId) {
  return optionFor(dimensionId, optionId)?.value || "";
}

function assetUrl(dimensionId, optionId) {
  return optionFor(dimensionId, optionId)?.asset || "";
}

function loadAsset(url) {
  if (!url) return Promise.resolve("");
  if (!assetCache.has(url)) {
    assetCache.set(
      url,
      fetch(url)
        .then(response => (response.ok ? response.text() : ""))
        .catch(() => ""),
    );
  }
  return assetCache.get(url);
}

async function inlineAsset(url) {
  const layer = document.createElement("span");
  layer.className = "door-layer";
  layer.innerHTML = await loadAsset(url);
  return layer;
}

async function buildDoorVisual(style) {
  const visual = document.createElement("div");
  visual.className = "door-visual";
  visual.style.color = colorValue("color", style?.color);
  visual.append(await inlineAsset(`${ASSET_ROOT}door-panel.svg`));
  const material = assetUrl("material", style?.material);
  if (material) visual.append(await inlineAsset(material));
  const handle = assetUrl("handle", style?.handle);
  if (handle) visual.append(await inlineAsset(handle));
  const tag = await inlineAsset(`${ASSET_ROOT}tag.svg`);
  tag.style.color = colorValue("tag_color", style?.tag_color) || "#f4c430";
  visual.append(tag);
  const text = document.createElement("span");
  text.className = "door-tag-text";
  text.textContent = String(style?.tag_text || "");
  visual.append(text);
  visual.append(await inlineAsset(`${ASSET_ROOT}door-frame.svg`));
  return visual;
}

async function enterDoor(door) {
  if (door.locked && !door.is_owner) {
    Tiny.toast("That classroom door is locked.", true);
    return;
  }
  try {
    await Tiny.command(`.classroom enter ${door.room_id}`);
  } catch (error) {
    Tiny.toast(error instanceof Error ? error.message : String(error), true);
  }
}

async function buyDoor() {
  try {
    const response = await Tiny.command(".classroom buy");
    Tiny.celebrate();
    Tiny.toast(response.message || "Classroom purchased.");
    await refresh();
  } catch (error) {
    Tiny.toast(error instanceof Error ? error.message : String(error), true);
  }
}

async function buildDoorCard(door) {
  const card = document.createElement("button");
  card.type = "button";
  card.className = `door-card${door.is_owner ? " own" : ""}`;
  card.dataset.roomId = door.room_id;
  card.setAttribute(
    "aria-label",
    `${door.label}${door.locked ? ", locked" : ""}. Click to enter.`,
  );
  card.append(await buildDoorVisual(door.style));
  const name = document.createElement("span");
  name.className = "door-name";
  name.textContent = door.owner_username;
  card.append(name);
  if (door.locked) {
    const lock = document.createElement("span");
    lock.className = "door-lock";
    lock.setAttribute("aria-hidden", "true");
    lock.textContent = "\u{1F512}";
    card.append(lock);
  }
  if (door.is_owner) {
    const design = document.createElement("span");
    design.className = "door-design";
    design.setAttribute("role", "button");
    design.tabIndex = 0;
    design.textContent = "Design";
    design.addEventListener("click", event => {
      event.stopPropagation();
      openDesigner(door);
    });
    design.addEventListener("keydown", event => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        event.stopPropagation();
        openDesigner(door);
      }
    });
    card.append(design);
  }
  card.addEventListener("click", () => enterDoor(door));
  return card;
}

function buildEmptySlot() {
  const slot = document.createElement("div");
  slot.className = "door-slot";
  if (!state.ownDoor && !buyButtonPlaced) {
    buyButtonPlaced = true;
    const button = document.createElement("button");
    button.type = "button";
    button.className = "door-buy";
    button.textContent = "+";
    button.title = `Get a classroom (${state.cost} Bops)`;
    button.setAttribute("aria-label", `Get a classroom for ${state.cost} Bops`);
    button.addEventListener("click", buyDoor);
    slot.append(button);
  }
  return slot;
}

function wireCorridorDrag(corridor) {
  let dragging = false;
  let dragStartX = 0;
  let dragStartScroll = 0;
  corridor.addEventListener("pointerdown", event => {
    if (event.target.closest("button")) return;
    dragging = true;
    dragStartX = event.clientX;
    dragStartScroll = corridor.scrollLeft;
    corridor.setPointerCapture(event.pointerId);
  });
  corridor.addEventListener("pointermove", event => {
    if (!dragging) return;
    corridor.scrollLeft = dragStartScroll - (event.clientX - dragStartX);
  });
  const endDrag = () => {
    dragging = false;
  };
  corridor.addEventListener("pointerup", endDrag);
  corridor.addEventListener("pointercancel", endDrag);
}

async function buildFloor(grade, doors) {
  const floor = document.createElement("section");
  floor.className = "floor";
  floor.dataset.grade = String(grade);
  floor.setAttribute("aria-label", gradeName(grade));

  const head = document.createElement("div");
  head.className = "floor-head";
  const label = document.createElement("h2");
  label.className = "floor-label";
  label.textContent = gradeName(grade);
  head.append(label);
  const count = document.createElement("span");
  count.className = "floor-count";
  count.textContent = `${doors.length} classroom${doors.length === 1 ? "" : "s"}`;
  head.append(count);
  floor.append(head);

  const corridor = document.createElement("div");
  corridor.className = "corridor";
  corridor.tabIndex = 0;
  const track = document.createElement("div");
  track.className = "corridor-track";
  corridor.append(track);

  for (const door of doors) {
    track.append(await buildDoorCard(door));
  }
  if (isAcquirable(grade) && !state.ownDoor) {
    track.append(buildEmptySlot());
  }
  if (!doors.length && !(isAcquirable(grade) && !state.ownDoor)) {
    const empty = document.createElement("p");
    empty.className = "floor-empty";
    empty.textContent = isAcquirable(grade) ? "No classrooms yet." : "This floor is locked for now.";
    track.append(empty);
  }
  floor.append(corridor);
  wireCorridorDrag(corridor);
  return floor;
}

async function renderFloors() {
  const token = ++renderToken;
  buyButtonPlaced = false;
  const gradeCount = Math.min(Math.max(state.maxGrade || GRADE_COUNT, 1), GRADE_COUNT);
  const grouped = floorsOf(state.doors, gradeCount);
  floorsEl.innerHTML = "";
  for (let index = 0; index < gradeCount; index += 1) {
    if (token !== renderToken) return;
    floorsEl.append(await buildFloor(index + 1, grouped[index]));
  }
}

function updateTopBar() {
  const bops = state.user?.bops;
  bopsLabel.textContent = Number.isFinite(bops) ? `${bops} Bops` : "";
  if (state.ownDoor) {
    myDoorButton.hidden = false;
    getDoorButton.hidden = true;
    myDoorButton.textContent = `My classroom \u00b7 ${gradeName(state.ownDoor.grade)}`;
  } else {
    myDoorButton.hidden = true;
    getDoorButton.hidden = !state.catalog;
    getDoorButton.textContent = `Get a classroom \u00b7 ${state.cost} Bops`;
  }
}

async function refresh() {
  try {
    const response = await Tiny.command(".classroom list");
    const payload = response.payload || {};
    state.doors = Array.isArray(payload.doors) ? payload.doors : [];
    state.catalog = payload.catalog || state.catalog;
    state.cost = Number.isFinite(payload.cost) ? payload.cost : state.cost;
    state.maxGrade = Number.isFinite(payload.max_grade) ? payload.max_grade : state.maxGrade;
    state.ownDoor = payload.own_door || null;
    connection.textContent = "";
    updateTopBar();
    await renderFloors();
  } catch (error) {
    connection.textContent = error instanceof Error ? error.message : String(error);
  }
}

async function renderPreview() {
  const token = renderToken;
  const visual = await buildDoorVisual(state.draft);
  if (token !== renderToken && !designer.hidden) return;
  preview.innerHTML = "";
  preview.append(visual);
}

function renderDesigner() {
  controls.innerHTML = "";
  for (const entry of state.catalog?.dimensions || []) {
    const row = document.createElement("div");
    row.className = "control-row";
    const label = document.createElement("span");
    label.className = "control-label";
    label.textContent = entry.label;
    row.append(label);
    if (entry.kind === "text") {
      const input = document.createElement("input");
      input.type = "text";
      input.maxLength = entry.max_length || 16;
      input.value = state.draft[entry.id] || "";
      input.addEventListener("input", () => {
        state.draft[entry.id] = input.value;
        renderPreview();
      });
      row.append(input);
    } else {
      const options = document.createElement("div");
      options.className = "control-options";
      for (const option of entry.options) {
        const swatch = document.createElement("button");
        swatch.type = "button";
        swatch.className = "swatch";
        swatch.setAttribute("aria-pressed", String(state.draft[entry.id] === option.id));
        swatch.title = option.label;
        swatch.setAttribute("aria-label", option.label);
        if (option.value) swatch.style.background = option.value;
        if (option.asset) {
          swatch.classList.add("asset");
          const icon = document.createElement("img");
          icon.src = withBase(option.asset);
          icon.alt = "";
          swatch.append(icon);
        }
        swatch.addEventListener("click", () => {
          state.draft[entry.id] = option.id;
          [...options.children].forEach(child => child.setAttribute("aria-pressed", String(child === swatch)));
          Tiny.sound("flip");
          renderPreview();
        });
        options.append(swatch);
      }
      row.append(options);
    }
    controls.append(row);
  }
  lockInput.checked = Boolean(state.ownDoor?.locked);
}

function openDesigner(door) {
  state.draft = { ...door.style };
  designer.hidden = false;
  renderDesigner();
  renderPreview();
  controls.querySelector("button, input")?.focus({ preventScroll: true });
}

function closeDesigner() {
  designer.hidden = true;
  state.draft = null;
}

async function saveDesign() {
  const tokens = [];
  for (const entry of state.catalog?.dimensions || []) {
    tokens.push(entry.id, quote(String(state.draft?.[entry.id] ?? "")));
  }
  try {
    const response = await Tiny.command(`.classroom design ${tokens.join(" ")}`);
    Tiny.toast(response.message || "Door updated.");
    closeDesigner();
    await refresh();
  } catch (error) {
    Tiny.toast(error instanceof Error ? error.message : String(error), true);
  }
}

designerClose.addEventListener("click", closeDesigner);
designerSave.addEventListener("click", saveDesign);
designer.addEventListener("click", event => {
  if (event.target === designer) closeDesigner();
});

lockInput.addEventListener("change", async () => {
  try {
    await Tiny.command(`.classroom lock ${lockInput.checked ? "on" : "off"}`);
    Tiny.toast(lockInput.checked ? "Your door is locked." : "Your door is unlocked.");
    await refresh();
  } catch (error) {
    lockInput.checked = !lockInput.checked;
    Tiny.toast(error instanceof Error ? error.message : String(error), true);
  }
});

myDoorButton.addEventListener("click", () => {
  const floor = floorsEl.querySelector(`.floor[data-grade="${state.ownDoor?.grade || 1}"]`);
  floor?.scrollIntoView({ behavior: "smooth", block: "nearest" });
  floor?.querySelector(".door-card.own")?.scrollIntoView({ behavior: "smooth", inline: "center", block: "nearest" });
});

getDoorButton.addEventListener("click", buyDoor);

Tiny.subscribe(nextState => {
  state.user = nextState?.user || null;
  state.room = nextState?.room || null;
  updateTopBar();
  if (!state.started) {
    state.started = true;
    refresh();
  }
});
