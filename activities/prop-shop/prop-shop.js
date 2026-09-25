import { createPropViewerManager } from "/app/js/prop-viewer.js";
import { createThumbnailManager } from "/app/js/editing/prop-thumbnails.js";
import { filterLibrary, sourcesOf, tagsOf } from "/app/js/editing/library-filter.js";

const Tiny = window.TinyActivity;

const propsetsRoot = document.getElementById("propsets");
const tagsRoot = document.getElementById("tags");
const gridRoot = document.getElementById("grid");
const gridEmpty = document.getElementById("grid-empty");
const previewRoot = document.getElementById("preview");
const previewCanvas = document.getElementById("preview-canvas");
const previewLabel = document.getElementById("preview-label");
const previewDescription = document.getElementById("preview-description");
const previewPrice = document.getElementById("preview-price");
const buyButton = document.getElementById("buy");
const searchInput = document.getElementById("search");
const walletAmount = document.getElementById("wallet-amount");
const connection = document.getElementById("connection");

const propViewer = createPropViewerManager();
const thumbnails = createThumbnailManager();

let catalog = [];
let criteria = { query: "", source: "", tags: new Set() };
let selectedId = null;
let owned = new Set();
let loading = false;
let loaded = false;
let busy = false;
let lastUserKey = "";

function escape(value) {
  return Tiny.escape(value);
}

function ownedIds() {
  owned = new Set(Tiny.state?.user?.unlockedProps || []);
  return owned;
}

function isOwned(prop) {
  return !prop.locked || owned.has(prop.prop_id);
}

function selectedProp() {
  return catalog.find(prop => prop.prop_id === selectedId) || null;
}

function sampleEntries(entries, count) {
  if (!entries.length) return [];
  const total = Math.min(count, entries.length);
  const step = entries.length / total;
  const picked = [];
  for (let index = 0; index < total; index += 1) {
    picked.push(entries[Math.min(entries.length - 1, Math.floor(index * step))]);
  }
  return picked;
}

function watermark(entry, className) {
  return `<img class="${className}" data-thumb-model="${escape(entry.model_url)}"
    data-thumb-scale="${escape(entry.base_scale)}" alt="" aria-hidden="true">`;
}

function propSetLabel(source) {
  if (!source) return "Show all";
  const name = source.replace(/-base$/, "");
  return name.charAt(0).toUpperCase() + name.slice(1);
}

function renderWallet() {
  walletAmount.textContent = String(Tiny.state?.user?.bops ?? 0);
}

function renderPropsets() {
  const sources = sourcesOf(catalog);
  const button = (source, entries) => {
    const value = source || "";
    const label = propSetLabel(source);
    const art = sampleEntries(entries, 4).map(entry => watermark(entry, "shop-propset-thumb")).join("");
    return `<button type="button" class="shop-propset${criteria.source === value ? " is-active" : ""}"
      data-propset="${escape(value)}" aria-pressed="${criteria.source === value}" title="${escape(label)}">
      <span class="shop-propset-art">${art}</span>
      <span class="shop-propset-label">${escape(label)}</span>
    </button>`;
  };
  propsetsRoot.innerHTML = [
    button("", catalog),
    ...sources.map(source => button(source, catalog.filter(entry => entry.source === source))),
  ].join("");
  thumbnails.sync(propsetsRoot);
}

function renderTags() {
  const available = tagsOf(catalog, criteria.source);
  for (const tag of [...criteria.tags]) {
    if (!available.includes(tag)) criteria.tags.delete(tag);
  }
  tagsRoot.innerHTML = available.map(tag => `<button type="button"
    class="shop-tag${criteria.tags.has(tag) ? " is-active" : ""}" data-tag="${escape(tag)}"
    aria-pressed="${criteria.tags.has(tag)}">${escape(tag)}</button>`).join("");
}

function renderGrid() {
  const visible = filterLibrary(catalog, criteria);
  gridRoot.innerHTML = visible.map(prop => {
    const isOwned = prop.locked !== true || owned.has(prop.prop_id);
    return `<button type="button" class="shop-card" role="listitem" data-prop="${escape(prop.prop_id)}"
      aria-selected="${prop.prop_id === selectedId}" title="${escape(prop.label)}">
      ${prop.locked && !isOwned ? '<span class="shop-card-lock" aria-hidden="true">🔒</span>' : ""}
      ${watermark(prop, "shop-thumb")}
      <span class="shop-card-label">${escape(prop.label)}</span>
      ${isOwned
        ? '<span class="shop-card-owned">Owned</span>'
        : `<span class="shop-card-price">${prop.price} Bops</span>`}
    </button>`;
  }).join("");
  gridEmpty.hidden = visible.length > 0;
  thumbnails.sync(gridRoot);
}

function renderPreview() {
  const prop = selectedProp();
  if (!prop) {
    previewLabel.textContent = "Pick a prop";
    previewDescription.textContent = "";
    previewPrice.textContent = "";
    previewPrice.classList.remove("owned");
    buyButton.disabled = true;
    buyButton.textContent = "Buy";
    return;
  }
  const isOwned = prop.locked !== true || owned.has(prop.prop_id);
  const bops = Number(Tiny.state?.user?.bops ?? 0);
  const affordable = bops >= prop.price;
  previewLabel.textContent = prop.label;
  previewDescription.textContent = prop.description || "";
  previewPrice.textContent = isOwned ? "You own this" : `${prop.price} Bops`;
  previewPrice.classList.toggle("owned", isOwned);
  buyButton.disabled = isOwned || busy || !affordable;
  buyButton.textContent = isOwned
    ? "Owned"
    : busy
      ? "Buying…"
      : affordable
        ? "Buy"
        : `Need ${prop.price} Bops`;
  if (previewCanvas.dataset.propModel !== prop.model_url || previewCanvas.dataset.propScale !== String(prop.base_scale)) {
    previewCanvas.dataset.propModel = prop.model_url;
    previewCanvas.dataset.propScale = String(prop.base_scale);
    previewCanvas.removeAttribute("data-model-ready");
    previewCanvas.removeAttribute("data-model-error");
  }
  propViewer.sync(previewRoot, Boolean(Tiny.state?.config?.reducedMotion));
}

function selectProp(propId) {
  selectedId = propId;
  renderGrid();
  renderPreview();
}

function renderAll() {
  renderWallet();
  renderPropsets();
  renderTags();
  renderGrid();
  renderPreview();
}

async function loadCatalog() {
  if (loading || loaded) return;
  loading = true;
  try {
    const response = await Tiny.command(".prop_catalog");
    catalog = response.payload?.catalog || [];
    if (!catalog.length) {
      connection.textContent = "The Prop Shop has no props for sale yet.";
      return;
    }
    ownedIds();
    loaded = true;
    document.body.dataset.shopReady = "true";
    selectedId = catalog[0].prop_id;
    renderAll();
  } catch (error) {
    connection.textContent = "The Prop Shop could not load. Reopen the activity to retry.";
    Tiny.toast(error.message || "The Prop Shop could not load.", true);
  } finally {
    loading = false;
  }
}

async function buy() {
  const prop = selectedProp();
  if (busy || !prop || isOwned(prop)) return;
  busy = true;
  renderPreview();
  try {
    const response = await Tiny.command(`.buy_prop ${prop.prop_id}`);
    if (Array.isArray(response.payload?.user?.unlocked_props)) {
      owned = new Set(response.payload.user.unlocked_props);
    } else {
      owned.add(prop.prop_id);
    }
    Tiny.celebrate();
    Tiny.toast(`${prop.label} unlocked!`);
    renderAll();
  } catch (error) {
    Tiny.toast(error.message || "That purchase was rejected.", true);
  } finally {
    busy = false;
    renderPreview();
  }
}

propsetsRoot.addEventListener("click", event => {
  const button = event.target.closest("[data-propset]");
  if (!button) return;
  criteria.source = button.dataset.propset || "";
  renderPropsets();
  renderTags();
  renderGrid();
});

tagsRoot.addEventListener("click", event => {
  const pill = event.target.closest("[data-tag]");
  if (!pill) return;
  const tag = pill.dataset.tag || "";
  if (criteria.tags.has(tag)) criteria.tags.delete(tag);
  else criteria.tags.add(tag);
  renderTags();
  renderGrid();
});

gridRoot.addEventListener("click", event => {
  const card = event.target.closest("[data-prop]");
  if (!card) return;
  selectProp(card.dataset.prop || "");
});

searchInput.addEventListener("input", () => {
  criteria.query = searchInput.value;
  renderGrid();
});

buyButton.onclick = () => { void buy(); };

function userKey() {
  const user = Tiny.state?.user;
  return `${user?.bops ?? 0}|${(user?.unlockedProps || []).join(",")}`;
}

Tiny.subscribe(state => {
  connection.textContent = "";
  renderWallet();
  if (!loaded) {
    void loadCatalog();
    return;
  }
  const key = userKey();
  if (key !== lastUserKey) {
    lastUserKey = key;
    ownedIds();
    renderGrid();
    renderPreview();
  }
});
