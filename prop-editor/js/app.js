import {
  loadCatalog,
  loadEffect,
  loadEffects,
  loadProp,
  loadSession,
  reloadWorld,
  saveEffect,
  saveProp,
} from "./api.js";
import { renderEffectsPanel } from "./effects-panel.js";
import { createPreviewViewer } from "./preview.js";
import { renderPropsPanel } from "./props-panel.js";
import { escapeHtml, clone, numberOr, parseCsv, setPath } from "./util.js";
import { libraryGridMarkup, libraryPropsetMarkup, libraryTagMarkup } from "/app/js/editing/prop-library.js";
import { bindEditorLibrary } from "/app/js/editing/library-filter.js";
import { createThumbnailManager } from "/app/js/editing/prop-thumbnails.js";

const thumbnails = createThumbnailManager();

const state = {
  worldId: "",
  catalog: null,
  entries: [],
  effects: [],
  enums: {},
  selected: null,
  propDraft: null,
  propSnapshot: null,
  propScale: null,
  file: null,
  selectedEffectId: null,
  effectDraft: null,
  effectSnapshot: null,
  activeTab: "props",
  status: "",
  error: "",
};

const elements = {
  toolbar: document.getElementById("pe-toolbar"),
  library: document.getElementById("pe-library"),
  tabs: document.getElementById("pe-tabs"),
  propPane: document.getElementById("pe-prop-pane"),
  effectPane: document.getElementById("pe-effect-pane"),
  previewCanvas: document.getElementById("pe-preview-canvas"),
  previewInfo: document.getElementById("pe-preview-info"),
  previewEmpty: document.getElementById("pe-preview-empty"),
  toast: document.getElementById("pe-toast"),
};

const preview = createPreviewViewer({ canvas: elements.previewCanvas });

function equal(a, b) {
  return JSON.stringify(a) === JSON.stringify(b);
}

function propDirty() {
  return state.propDraft != null && !equal(state.propDraft, state.propSnapshot);
}

function effectDirty() {
  return state.effectDraft != null && !equal(state.effectDraft, state.effectSnapshot);
}

function modelUrlFor(kind, source, model) {
  if (kind === "mod") return `/assets/mods/${source}/props/${model}`;
  if (kind === "propset") return `/assets/propsets/${source}/${model}`;
  return `/assets/world/${state.worldId}/props/${model}`;
}

function readValue(target, kind) {
  if (kind === "bool") return target.checked;
  if (kind === "number") return numberOr(target.value, 0);
  if (kind === "int") return Math.trunc(numberOr(target.value, 0));
  if (kind === "csv") return parseCsv(target.value);
  return target.value;
}

function uniqueName(existing, base) {
  let index = 1;
  let candidate = base;
  while (existing.includes(candidate)) {
    index += 1;
    candidate = `${base}-${index}`;
  }
  return candidate;
}

function selectedSummary() {
  return (state.catalog?.props || []).find(prop => prop.id === state.selected?.id) || null;
}

function renderToolbar() {
  elements.toolbar.innerHTML = `
    <div class="pe-toolbar-group">
      <strong class="pe-brand">Prop Editor</strong>
      <span class="pe-world">${escapeHtml(state.worldId || "")}</span>
    </div>
    <div class="pe-toolbar-group">
      <button type="button" class="pe-quiet" data-pe-refresh>Refresh catalog</button>
      <button type="button" class="pe-positive" data-pe-reload>Reload world</button>
    </div>
  `;
}

function renderTabs() {
  const tabs = [["props", "Props"], ["effects", "Effects"]];
  elements.tabs.innerHTML = tabs.map(([id, label]) => `
    <button type="button" class="pe-tab${state.activeTab === id ? " is-active" : ""}" data-pe-tab="${id}">${label}</button>
  `).join("");
  elements.propPane.hidden = state.activeTab !== "props";
  elements.effectPane.hidden = state.activeTab !== "effects";
}

function renderLibrary() {
  const entries = state.entries;
  elements.library.innerHTML = `
    <div class="pe-search-row">
      <input type="search" data-edit-search placeholder="Search props" aria-label="Search props">
      <span class="editor-library-count" role="status"></span>
    </div>
    <div class="editor-propsets" role="list" aria-label="Prop sources">
      ${libraryPropsetMarkup(entries)}
    </div>
    <div class="pe-tag-row" role="group" aria-label="Filter by tag">
      ${libraryTagMarkup(entries)}
    </div>
    <div class="editor-library-grid" role="list" aria-label="Props">
      ${libraryGridMarkup(entries)}
    </div>
    <p class="editor-library-empty pe-empty" hidden>No props match your filters.</p>
  `;
  bindEditorLibrary(elements.library, entries);
  for (const entry of entries) {
    const tile = elements.library.querySelector(`.editor-library-item[data-edit-add="${CSS.escape(entry.propId)}"]`);
    if (!tile) continue;
    if (entry.hidden) tile.classList.add("is-hidden");
    if (state.selected && state.selected.id === entry.propId) tile.classList.add("is-selected");
  }
  thumbnails.sync(elements.library);
}

function effectSetsForPreview() {
  const raw = state.propDraft?.effects;
  if (!raw || typeof raw !== "object") return {};
  const byId = new Map((state.effects || []).map(effect => [effect.id, effect]));
  const sets = {};
  for (const [name, ids] of Object.entries(raw)) {
    const list = (Array.isArray(ids) ? ids : []).map(id => byId.get(id)).filter(Boolean);
    if (list.length) sets[name] = list;
  }
  return sets;
}

function renderPreview() {
  const draft = state.propDraft;
  if (!draft || !state.selected) {
    preview.setProp({ modelUrl: "", scale: 1, effectSets: {}, activeEffect: null });
    elements.previewInfo.innerHTML = "";
    elements.previewEmpty.hidden = false;
    return;
  }
  const meta = selectedSummary();
  const effectSets = effectSetsForPreview();
  const activeEffect = draft.active_effect && effectSets[draft.active_effect]
    ? draft.active_effect
    : Object.keys(effectSets)[0] || null;
  const modelUrl = draft.model ? modelUrlFor(state.selected.kind, state.selected.source, draft.model) : "";
  const scale = numberOr(draft.scale, 1) * numberOr(state.file?.scale_adjust, 1);
  preview.setProp({ modelUrl, scale, effectSets, activeEffect });
  elements.previewEmpty.hidden = true;
  elements.previewInfo.innerHTML = `
    <h2>${escapeHtml(draft.label || state.selected.id)}</h2>
    <p>${escapeHtml(draft.description || "")}</p>
    <dl class="pe-preview-meta">
      <div><dt>Id</dt><dd><code>${escapeHtml(state.selected.id)}</code></dd></div>
      <div><dt>Source</dt><dd>${escapeHtml(meta?.source_kind || state.selected.kind)}/${escapeHtml(state.selected.source)}</dd></div>
      <div><dt>Model</dt><dd><code>${escapeHtml(draft.model || "")}</code></dd></div>
      <div><dt>Scale</dt><dd>${escapeHtml(scale.toFixed(3))}</dd></div>
      ${activeEffect ? `<div><dt>Effect</dt><dd><code>${escapeHtml(activeEffect)}</code></dd></div>` : ""}
    </dl>
  `;
}

function render() {
  renderToolbar();
  renderTabs();
  renderLibrary();
  elements.propPane.innerHTML = renderPropsPanel({ ...state, propDirty: propDirty() });
  elements.effectPane.innerHTML = renderEffectsPanel({ ...state, effectDirty: effectDirty() });
  renderPreview();
  elements.toast.textContent = state.error || state.status || "";
  elements.toast.dataset.kind = state.error ? "error" : "info";
}

function fail(error) {
  state.error = error.message || String(error);
  state.status = "";
  render();
}

async function refreshCatalog() {
  const body = await loadCatalog();
  const catalog = body.catalog;
  state.worldId = catalog.world_id;
  state.catalog = catalog;
  state.effects = catalog.effects || [];
  state.enums = catalog.enums || {};
  state.entries = catalog.props.map(prop => ({
    propId: prop.id,
    label: prop.label,
    description: prop.description,
    tags: prop.tags || [],
    source: prop.source,
    sourceKind: prop.source_kind,
    modelUrl: prop.model_url,
    baseScale: prop.scale,
    hidden: Boolean(prop.hidden),
  }));
}

async function selectProp(propId) {
  const summary = (state.catalog?.props || []).find(prop => prop.id === propId);
  if (!summary) return;
  const body = await loadProp(summary.source_kind, summary.source, propId);
  state.selected = { id: propId, kind: summary.source_kind, source: summary.source };
  state.propDraft = clone(body.prop.raw);
  state.propSnapshot = clone(body.prop.raw);
  state.propScale = body.prop.scale;
  state.file = body.file;
  state.activeTab = "props";
  state.error = "";
  state.status = `Editing ${propId}.`;
  render();
  elements.library
    .querySelector(`.editor-library-item[data-edit-add="${CSS.escape(propId)}"]`)
    ?.scrollIntoView({ block: "nearest" });
}

async function selectEffect(effectId) {
  const body = await loadEffect(effectId);
  state.selectedEffectId = effectId;
  state.effectDraft = clone(body.effect.raw);
  state.effectSnapshot = clone(body.effect.raw);
  state.enums = body.enums || state.enums;
  state.activeTab = "effects";
  state.error = "";
  render();
}

function changeProp(target) {
  const path = target.dataset.peProp;
  const value = readValue(target, target.dataset.peKind);
  if (path === "active_effect" && value === "") delete state.propDraft.active_effect;
  else setPath(state.propDraft, path, value);
  state.status = "Unsaved prop changes.";
  state.error = "";
  render();
}

function changeEffect(target) {
  const path = target.dataset.peEffect;
  setPath(state.effectDraft, path, readValue(target, target.dataset.peKind));
  state.status = "Unsaved effect changes.";
  state.error = "";
  render();
}

function renameSet(index, value) {
  const entries = Object.entries(state.propDraft.effects || {});
  const current = entries[index];
  if (!current) return;
  const name = String(value || "").trim();
  const nextName = name || current[0];
  if (nextName !== current[0] && entries.some(([key]) => key === nextName)) return;
  const effects = {};
  entries.forEach(([key, ids], entryIndex) => {
    effects[entryIndex === index ? nextName : key] = ids;
  });
  state.propDraft.effects = effects;
  if (state.propDraft.active_effect === current[0]) state.propDraft.active_effect = nextName;
  render();
}

function toggleSetEffect(target) {
  const [indexText, effectId] = target.dataset.peSetToggle.split(":");
  const index = Number(indexText);
  const name = Object.keys(state.propDraft.effects || {})[index];
  if (name == null) return;
  const ids = new Set(state.propDraft.effects[name] || []);
  if (target.checked) ids.add(effectId);
  else ids.delete(effectId);
  state.propDraft.effects[name] = [...ids];
  state.status = "Unsaved prop changes.";
  render();
}

function addSet() {
  const effects = state.propDraft.effects || (state.propDraft.effects = {});
  const name = uniqueName(Object.keys(effects), "set");
  effects[name] = state.effects.length ? [state.effects[0].id] : [];
  state.status = "Added effect set.";
  render();
}

function removeSet(index) {
  const entries = Object.entries(state.propDraft.effects || {});
  const current = entries[index];
  if (!current) return;
  const effects = {};
  entries.forEach(([key, ids], entryIndex) => {
    if (entryIndex !== index) effects[key] = ids;
  });
  state.propDraft.effects = effects;
  if (state.propDraft.active_effect === current[0]) delete state.propDraft.active_effect;
  render();
}

function applyJson(scope) {
  const node = document.querySelector(`[data-pe-json="${scope}"]`);
  if (!node) return;
  let parsed;
  try {
    parsed = JSON.parse(node.value);
  } catch (error) {
    fail(new Error(`Invalid JSON: ${error.message}`));
    return;
  }
  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
    fail(new Error("JSON must be an object."));
    return;
  }
  if (scope === "prop") state.propDraft = parsed;
  else state.effectDraft = parsed;
  state.status = "Applied JSON.";
  state.error = "";
  render();
}

function resetJson(scope) {
  if (scope === "prop") state.propDraft = clone(state.propSnapshot);
  else state.effectDraft = clone(state.effectSnapshot);
  state.error = "";
  render();
}

function addLayer(type) {
  const layer = { type };
  if (type === "transform") layer.motion = "bob";
  else if (type === "material") layer.emissive = "#ffffff";
  else {
    layer.preset = "smoke";
    layer.texture = (state.enums.textures || [])[0] || "smoke-puff.png";
  }
  state.effectDraft.layers = [...(state.effectDraft.layers || []), layer];
  state.status = `Added ${type} layer.`;
  render();
}

function removeLayer(index) {
  const layers = [...(state.effectDraft.layers || [])];
  layers.splice(index, 1);
  state.effectDraft.layers = layers;
  render();
}

function moveLayer(spec) {
  const [indexText, deltaText] = spec.split(":");
  const index = Number(indexText);
  const target = index + Number(deltaText);
  const layers = [...(state.effectDraft.layers || [])];
  if (target < 0 || target >= layers.length) return;
  const [layer] = layers.splice(index, 1);
  layers.splice(target, 0, layer);
  state.effectDraft.layers = layers;
  render();
}

async function saveCurrentProp() {
  if (!state.selected) return;
  state.status = "Saving prop…";
  state.error = "";
  render();
  try {
    const body = await saveProp({
      kind: state.selected.kind,
      source: state.selected.source,
      prop_id: state.selected.id,
      prop: state.propDraft,
      scale_adjust: state.file?.scale_adjust ?? null,
    });
    state.propDraft = clone(body.prop.raw);
    state.propSnapshot = clone(body.prop.raw);
    state.propScale = body.prop.scale;
    state.file = body.file;
    state.status = "Prop saved to YAML. Use Reload world to apply.";
    await refreshCatalog();
    render();
  } catch (error) {
    fail(error);
  }
}

async function saveCurrentEffect() {
  if (!state.selectedEffectId) return;
  state.status = "Saving effect…";
  state.error = "";
  render();
  try {
    const body = await saveEffect({ effect_id: state.selectedEffectId, effect: state.effectDraft });
    state.effectDraft = clone(body.effect.raw);
    state.effectSnapshot = clone(body.effect.raw);
    state.enums = body.enums || state.enums;
    state.status = "Effect saved to YAML. Use Reload world to apply.";
    const effectsBody = await loadEffects();
    state.effects = effectsBody.effects || state.effects;
    state.enums = effectsBody.enums || state.enums;
    render();
  } catch (error) {
    fail(error);
  }
}

async function runReload() {
  state.status = "Reloading world…";
  state.error = "";
  render();
  try {
    const body = await reloadWorld();
    await refreshCatalog();
    if (state.selected && (state.catalog?.props || []).some(prop => prop.id === state.selected.id)) {
      await selectProp(state.selected.id);
    }
    state.status = `World reloaded (revision ${body.revision ?? "?"}).`;
    render();
  } catch (error) {
    fail(error);
  }
}

async function runRefresh() {
  try {
    await refreshCatalog();
    state.status = "Catalog refreshed.";
    state.error = "";
    render();
  } catch (error) {
    fail(error);
  }
}

function handleChange(target) {
  const dataset = target.dataset || {};
  if (dataset.peSetName !== undefined) return renameSet(Number(dataset.peSetName), target.value);
  if (dataset.peSetToggle !== undefined) return toggleSetEffect(target);
  if (dataset.peEffectSelect !== undefined) {
    if (!target.value) {
      state.selectedEffectId = null;
      state.effectDraft = null;
      state.effectSnapshot = null;
      return render();
    }
    return selectEffect(target.value);
  }
  if (dataset.peProp !== undefined) return changeProp(target);
  if (dataset.peFile !== undefined) {
    state.file.scale_adjust = readValue(target, dataset.peKind);
    return render();
  }
  if (dataset.peEffect !== undefined) return changeEffect(target);
  return undefined;
}

function handleClick(target) {
  const dataset = target.dataset || {};
  if (dataset.peTab !== undefined) {
    state.activeTab = dataset.peTab;
    return render();
  }
  if (dataset.editAdd !== undefined) return selectProp(dataset.editAdd);
  if (dataset.peRefresh !== undefined) return runRefresh();
  if (dataset.peReload !== undefined) return runReload();
  if (dataset.peSaveProp !== undefined) return saveCurrentProp();
  if (dataset.peResetProp !== undefined) {
    state.propDraft = clone(state.propSnapshot);
    return render();
  }
  if (dataset.peAddSet !== undefined) return addSet();
  if (dataset.peRemoveSet !== undefined) return removeSet(Number(dataset.peRemoveSet));
  if (dataset.peJsonApply !== undefined) return applyJson(dataset.peJsonApply);
  if (dataset.peJsonReset !== undefined) return resetJson(dataset.peJsonReset);
  if (dataset.peAddLayer !== undefined) return addLayer(dataset.peAddLayer);
  if (dataset.peRemoveLayer !== undefined) return removeLayer(Number(dataset.peRemoveLayer));
  if (dataset.peMoveLayer !== undefined) return moveLayer(dataset.peMoveLayer);
  if (dataset.peSaveEffect !== undefined) return saveCurrentEffect();
  if (dataset.peResetEffect !== undefined) {
    state.effectDraft = clone(state.effectSnapshot);
    return render();
  }
  return undefined;
}

document.addEventListener("change", event => {
  const target = event.target;
  if (target?.dataset && Object.keys(target.dataset).length) handleChange(target);
});

document.addEventListener("click", event => {
  const target = event.target.closest(
    "[data-pe-tab],[data-edit-add],[data-pe-refresh],[data-pe-reload],[data-pe-save-prop],[data-pe-reset-prop]," +
    "[data-pe-add-set],[data-pe-remove-set],[data-pe-json-apply],[data-pe-json-reset]," +
    "[data-pe-add-layer],[data-pe-remove-layer],[data-pe-move-layer],[data-pe-save-effect],[data-pe-reset-effect]"
  );
  if (target) handleClick(target);
});

async function boot() {
  try {
    await loadSession();
    await refreshCatalog();
    const requested = new URLSearchParams(window.location.search).get("prop");
    if (requested && (state.catalog?.props || []).some(prop => prop.id === requested)) {
      await selectProp(requested);
      return;
    }
    state.status = "Select a prop or effect to edit.";
    render();
  } catch (error) {
    fail(error);
  }
}

boot();
