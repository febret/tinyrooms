import { renderSticker, exportSticker } from "./composer.js";
import {
  CATEGORIES,
  STARTER_PRESETS,
  applyPalettePair,
  cloneDesign,
  darken,
  defaultDesign,
  randomDesign,
} from "./parts.js";

const Tiny = window.TinyActivity;

const grid = document.querySelector("#grid");
const modeTabs = document.querySelector("#mode-tabs");
const presetsPane = document.querySelector("#presets-pane");
const customPane = document.querySelector("#custom-pane");
const preview = document.querySelector("#preview");
const randomizeButton = document.querySelector("#randomize");
const resetButton = document.querySelector("#reset-design");
const starters = document.querySelector("#starters");
const catTabs = document.querySelector("#cat-tabs");
const partGrid = document.querySelector("#part-grid");
const palettes = document.querySelector("#palettes");
const summary = document.querySelector("#summary");
const confirmButton = document.querySelector("#confirm");
const connection = document.querySelector("#connection");

let state = null;
let mode = "presets";
let design = null;
let activeCategory = CATEGORIES[0].id;
let selectedPreset = "";
let confirming = false;
let gridMarkup = "";
let previewPromise = Promise.resolve();
let renderToken = 0;
let partButtons = [];
let controlsKey = "";
let pendingRenders = 0;

function track(promise) {
  pendingRenders += 1;
  document.body.dataset.stickerReady = "false";
  const done = () => {
    pendingRenders -= 1;
    if (pendingRenders === 0) document.body.dataset.stickerReady = "true";
  };
  promise.then(done, done);
  return promise;
}

function buildCategoryTabs() {
  catTabs.innerHTML = CATEGORIES.map(entry => `
    <button type="button" class="cat-tab" role="tab" data-category="${Tiny.escape(entry.id)}" aria-selected="false">${Tiny.escape(entry.label)}</button>
  `).join("");
  catTabs.querySelectorAll("[data-category]").forEach(button => {
    button.onclick = () => {
      if (activeCategory === button.dataset.category) return;
      activeCategory = button.dataset.category;
      Tiny.sound("flip");
      renderControls();
    };
  });
}
buildCategoryTabs();

function currentStickerName() {
  return String(state?.user?.sticker || "");
}

function normalizeSticker(choice) {
  return {
    name: String(choice?.name || ""),
    imageUrl: Tiny.image(choice?.image_url || ""),
  };
}

function presetStickers() {
  return Array.isArray(state?.stickers) ? state.stickers.map(normalizeSticker) : [];
}

function activeCategoryEntry() {
  return CATEGORIES.find(category => category.id === activeCategory) || CATEGORIES[0];
}

function setMode(next) {
  mode = next === "custom" ? "custom" : "presets";
  modeTabs.querySelectorAll("[data-mode]").forEach(tab => {
    tab.setAttribute("aria-selected", String(tab.dataset.mode === mode));
    tab.setAttribute("tabindex", tab.dataset.mode === mode ? "0" : "-1");
  });
  presetsPane.hidden = mode !== "presets";
  customPane.hidden = mode !== "custom";
  if (mode === "custom") {
    if (!design) design = cloneDesign(state?.user?.stickerDesign || defaultDesign());
    renderControls();
  }
  updateSummary();
}

function renderPresets() {
  const stickers = presetStickers();
  const focused = grid.contains(document.activeElement) ? document.activeElement.dataset.sticker : null;
  const current = currentStickerName();
  if (mode === "presets" && !selectedPreset) selectedPreset = current || stickers[0]?.name || "";
  const markup = stickers.map(sticker => `
    <button type="button" class="sticker" data-sticker="${Tiny.escape(sticker.name)}" aria-pressed="${sticker.name === selectedPreset}">
      <img src="${Tiny.escape(sticker.imageUrl)}" alt="${Tiny.escape(sticker.name)}">
      <strong>${Tiny.escape(sticker.name.replace(/\.png$/i, ""))}</strong>
      <span class="current">${sticker.name === current ? "Current sticker" : sticker.name === selectedPreset ? "Selected" : ""}</span>
    </button>
  `).join("");
  if (markup !== gridMarkup) {
    gridMarkup = markup;
    grid.innerHTML = markup;
    grid.querySelectorAll("[data-sticker]").forEach(button => {
      button.onclick = () => {
        selectedPreset = button.dataset.sticker;
        Tiny.sound("flip");
        renderPresets();
        updateSummary();
      };
    });
    if (focused) {
      [...grid.querySelectorAll("[data-sticker]")].find(button => button.dataset.sticker === focused)?.focus({ preventScroll: true });
    }
  }
}

function controlsSignature() {
  return `${activeCategory}|${JSON.stringify(design)}`;
}

function renderControls() {
  const category = activeCategoryEntry();
  controlsKey = controlsSignature();
  catTabs.querySelectorAll("[data-category]").forEach(button => {
    button.setAttribute("aria-selected", String(button.dataset.category === category.id));
  });

  partButtons = [];
  partGrid.innerHTML = "";
  category.parts.forEach(part => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "part-card";
    button.dataset.part = part.id;
    button.setAttribute("aria-pressed", String(design[category.partSlot] === part.id));
    const canvas = document.createElement("canvas");
    canvas.width = 62;
    canvas.height = 68;
    button.appendChild(canvas);
    const label = document.createElement("span");
    label.textContent = part.label;
    button.appendChild(label);
    button.onclick = () => selectPart(category.partSlot, part.id);
    partGrid.appendChild(button);
    partButtons.push({ button, canvas, part });
  });

  palettes.innerHTML = "";
  category.palettes.forEach(entry => {
    const row = document.createElement("div");
    row.className = "palette-row";
    const label = document.createElement("span");
    label.className = "palette-label";
    label.textContent = entry.label;
    row.appendChild(label);
    const swatches = document.createElement("div");
    swatches.className = "swatches";
    entry.palette.forEach(pair => {
      const swatch = document.createElement("button");
      swatch.type = "button";
      swatch.className = "swatch";
      swatch.dataset.slot = entry.slot;
      swatch.dataset.color = pair[0];
      swatch.style.background = pair[0];
      swatch.setAttribute("aria-label", `${entry.label} ${pair[0]}`);
      swatch.setAttribute("aria-pressed", String(design.colors[entry.slot]?.toLowerCase() === pair[0].toLowerCase()));
      swatch.onclick = () => choosePair(entry.slot, pair[0], pair[1]);
      swatches.appendChild(swatch);
    });
    const picker = document.createElement("input");
    picker.type = "color";
    picker.value = design.colors[entry.slot] || "#ffffff";
    picker.setAttribute("aria-label", `Custom ${entry.label.toLowerCase()} color`);
    picker.addEventListener("change", () => choosePair(entry.slot, picker.value, darken(picker.value)));
    row.appendChild(swatches);
    row.appendChild(picker);
    palettes.appendChild(row);
  });

  renderStarters();
  renderPartThumbs();
  schedulePreview();
}

function renderStarters() {
  starters.innerHTML = STARTER_PRESETS.map((preset, index) => `
    <button type="button" class="starter" data-starter="${index}">${Tiny.escape(preset.label)}</button>
  `).join("");
  starters.querySelectorAll("[data-starter]").forEach(button => {
    button.onclick = () => {
      design = cloneDesign(STARTER_PRESETS[Number(button.dataset.starter)].design);
      Tiny.sound("flip");
      renderControls();
    };
  });
}

function selectPart(slot, partId) {
  if (design[slot] === partId) return;
  design[slot] = partId;
  Tiny.sound("tap");
  partButtons.forEach(entry => entry.button.setAttribute("aria-pressed", String(design[slot] === entry.part.id)));
  controlsKey = controlsSignature();
  schedulePreview();
}

function choosePair(slot, base, dark) {
  applyPalettePair(design, slot, base, dark);
  Tiny.sound("tap");
  palettes.querySelectorAll(`[data-slot="${slot}"]`).forEach(swatch => {
    swatch.setAttribute("aria-pressed", String(swatch.dataset.color.toLowerCase() === String(base).toLowerCase()));
  });
  controlsKey = controlsSignature();
  renderPartThumbs();
  schedulePreview();
}

function renderPartThumbs() {
  partButtons.forEach(entry => {
    const variant = cloneDesign(design);
    variant[activeCategoryEntry().partSlot] = entry.part.id;
    track(renderSticker(entry.canvas, variant)).catch(() => {});
  });
}

function schedulePreview() {
  const token = ++renderToken;
  previewPromise = track(renderSticker(preview, design)).then(() => {
    if (token !== renderToken) return;
  }).catch(error => {
    Tiny.toast(error instanceof Error ? error.message : String(error), true);
  });
  return previewPromise;
}

function updateSummary() {
  const user = state?.user;
  const cost = Number(user?.stickerSwapCost || 0);
  if (mode === "presets") {
    const current = currentStickerName();
    summary.textContent = current && selectedPreset === current
      ? "You are keeping your current sticker."
      : user?.initialStickerComplete ? "Confirm to update your room marker." : "Confirm your sticker to enter Tinyrooms.";
  } else if (!user?.initialStickerComplete) {
    summary.textContent = "Design your sticker, then confirm it to enter Tinyrooms.";
  } else {
    summary.textContent = cost > 0
      ? `Confirm to save this design. Changing your sticker costs ${cost} Bops.`
      : "Confirm to save this design.";
  }
  confirmButton.disabled = confirming || (mode === "presets" ? !selectedPreset : !design);
  confirmButton.textContent = mode === "custom" ? "Confirm custom sticker" : "Confirm sticker";
}

function render() {
  if (!state) return;
  connection.textContent = state.user
    ? state.user.initialStickerComplete ? "" : "Choose your first sticker to enter Tinyrooms."
    : "Waiting for Tinyrooms…";
  if (!design) design = cloneDesign(state.user?.stickerDesign || defaultDesign());
  if (!selectedPreset) {
    const current = currentStickerName();
    const presets = presetStickers();
    selectedPreset = presets.some(entry => entry.name === current) ? current : presets[0]?.name || "";
  }
  renderPresets();
  if (mode === "custom" && controlsSignature() !== controlsKey) renderControls();
  updateSummary();
}

modeTabs.querySelectorAll("[data-mode]").forEach(tab => {
  tab.onclick = () => setMode(tab.dataset.mode);
});

randomizeButton.onclick = () => {
  design = cloneDesign(randomDesign());
  Tiny.sound("flip");
  renderControls();
};

resetButton.onclick = () => {
  design = cloneDesign(defaultDesign());
  Tiny.sound("flip");
  renderControls();
};

confirmButton.onclick = async () => {
  if (confirming) return;
  if (mode === "presets" && !selectedPreset) return;
  confirming = true;
  confirmButton.disabled = true;
  try {
    let selection;
    if (mode === "presets") {
      selection = { sticker: selectedPreset };
    } else {
      await previewPromise;
      selection = { sticker: "", image: exportSticker(preview), design: cloneDesign(design) };
    }
    const result = await Tiny.confirmSticker(selection);
    Tiny.celebrate();
    Tiny.toast(result.message || "Sticker confirmed.");
  } catch (error) {
    Tiny.toast(error instanceof Error ? error.message : String(error), true);
  } finally {
    confirming = false;
    updateSummary();
  }
};

Tiny.subscribe(nextState => {
  state = nextState;
  render();
});
