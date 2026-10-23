import { createCutsceneManager } from "../../app/js/cutscenes/manager.js";
import { playSound } from "../../app/js/audio.js";
import { escapeHtml } from "../../app/js/presentation.js";
import { withBase } from "../../app/js/base-path.js";
import { loadSession, loadCatalog, previewCutscene } from "./api.js";
import {
  changedParams,
  cueTokens,
  filterCutscenes,
  isPlayable,
  kindLabel,
  placeholderRows,
} from "./model.js";
import { createPicker } from "./pickers.js";

const root = document.querySelector("#app");
const worldLabel = document.querySelector("#cc-world");
const roomSelect = document.querySelector("#cc-room");
const refreshButton = document.querySelector("#cc-refresh");
const backLink = document.querySelector("#cc-back");
const motionNotice = document.querySelector("#cc-motion");
const searchInput = document.querySelector("#cc-search");
const tabsRoot = document.querySelector("#cc-tabs");
const scenesList = document.querySelector("#cc-scenes");
const detail = document.querySelector("#cc-detail");
const toastNode = document.querySelector("#cc-toast");
const layer = document.querySelector("#cutscene-layer");
const pickerDialog = document.querySelector("#cc-picker");
const pickerTitle = document.querySelector("#cc-picker-title");
const pickerSearch = document.querySelector("#cc-picker-search");
const pickerList = document.querySelector("#cc-picker-list");

const TABS = [
  ["playable", "Playable here"],
  ["all", "All"],
  ["hidden", "Hidden"],
  ["gated", "Gated"],
];

const state = {
  data: null,
  roomId: "",
  selectedId: "",
  tab: "playable",
  overrides: {},
  customKey: "",
  customValue: "",
  playing: false,
  motionQuery: window.matchMedia("(prefers-reduced-motion: reduce)"),
};

const picker = createPicker({
  dialog: pickerDialog,
  title: pickerTitle,
  search: pickerSearch,
  list: pickerList,
});

const player = createCutsceneManager({
  layer,
  getState: () => ({
    ui: { reducedMotion: state.motionQuery.matches },
    room: state.roomId ? { id: state.roomId } : null,
    transport: { connected: true },
  }),
  onToast: toast,
  onBlockingChange: () => {},
  onSound: sound => playSound(sound, true),
});

let toastTimer = 0;
function toast(message) {
  toastNode.textContent = String(message || "");
  window.clearTimeout(toastTimer);
  if (message) toastTimer = window.setTimeout(() => { toastNode.textContent = ""; }, 4200);
}

function reducedMotion() {
  return state.motionQuery.matches;
}

function syncMotionNotice() {
  if (reducedMotion()) {
    motionNotice.hidden = false;
    motionNotice.textContent = "Cutscene playback is disabled while your system requests reduced motion.";
  } else {
    motionNotice.hidden = true;
    motionNotice.textContent = "";
  }
}

function selectedEntry() {
  return (state.data?.cutscenes || []).find(entry => entry.id === state.selectedId) || null;
}

function gateBadges(entry) {
  const badges = [`audience: ${entry.audience}`, `frame: ${entry.frame}`];
  if (entry.hidden) badges.push("hidden");
  if (entry.power) badges.push(`power: ${entry.power}`);
  if (entry.feature) badges.push(`feature: ${entry.feature}`);
  if (entry.rooms?.length) badges.push(`rooms: ${entry.rooms.join(", ")}`);
  else if (!entry.gates.room) badges.push("room-blocked");
  if (!entry.gates.power) badges.push("power-blocked");
  if (!entry.gates.feature) badges.push("feature-blocked");
  return badges;
}

function renderTabs() {
  tabsRoot.innerHTML = TABS.map(([id, label]) => `
    <button type="button" role="tab" data-tab="${id}" aria-selected="${state.tab === id}">${escapeHtml(label)}</button>
  `).join("");
  tabsRoot.querySelectorAll("[data-tab]").forEach(button => {
    button.onclick = () => {
      state.tab = button.dataset.tab;
      renderTabs();
      renderList();
    };
  });
}

function renderList() {
  const entries = filterCutscenes(state.data?.cutscenes, { query: searchInput.value, tab: state.tab });
  scenesList.innerHTML = entries.length
    ? entries.map(entry => `
      <li>
        <button type="button" class="cc-scene${entry.id === state.selectedId ? " selected" : ""}" data-scene="${escapeHtml(entry.id)}">
          <span class="cc-scene-title">${escapeHtml(entry.title)}</span>
          <span class="cc-scene-id">${escapeHtml(entry.id)}${entry.hidden ? " · hidden" : ""}${isPlayable(entry) ? "" : " · gated"}</span>
        </button>
      </li>`).join("")
    : `<li><p class="cc-empty">No cutscenes match.</p></li>`;
  scenesList.querySelectorAll("[data-scene]").forEach(button => {
    button.onclick = () => selectScene(button.dataset.scene);
  });
}

function placeholderRowMarkup(entry, row, index) {
  const key = String(row.key);
  const value = String(state.overrides[key] ?? row.value ?? "");
  const tokenButtons = row.tokens.map(token => `
    <button type="button" class="quiet cc-token" data-row="${index}" data-token="${escapeHtml(token.token)}" data-kind="${escapeHtml(token.kind)}"
      title="Replace ${escapeHtml(token.token)}">↩ ${escapeHtml(kindLabel(token.kind))}</button>
  `).join("");
  return `
    <div class="cc-param" data-param="${escapeHtml(key)}">
      <div class="cc-param-head">
        <code>${escapeHtml(key)}</code>
        <span class="cc-kinds">${row.tokens.map(token => escapeHtml(token.kind)).join(" · ")}</span>
      </div>
      <div class="cc-param-controls">
        <input type="text" data-override="${escapeHtml(key)}" value="${escapeHtml(value)}" spellcheck="false"
          aria-label="Override value for ${escapeHtml(key)}">
        ${tokenButtons}
        <button type="button" class="quiet" data-reset="${escapeHtml(key)}">Reset</button>
      </div>
    </div>`;
}

function renderDetail() {
  const entry = selectedEntry();
  if (!entry) {
    detail.innerHTML = `<p class="cc-empty">Select a cutscene.</p>`;
    return;
  }
  const rows = placeholderRows(entry);
  const cueOnly = cueTokens(entry);
  detail.innerHTML = `
    <header class="cc-detail-head">
      <div>
        <h2>${escapeHtml(entry.title)}</h2>
        <p class="cc-meta">${escapeHtml(entry.id)}${entry.aliases?.length ? ` · aliases: ${entry.aliases.map(escapeHtml).join(", ")}` : ""} · origin: ${escapeHtml(entry.origin)}</p>
        <p class="cc-badges">${gateBadges(entry).map(badge => `<span class="cc-badge">${escapeHtml(badge)}</span>`).join("")}</p>
      </div>
      <div class="cc-detail-actions">
        <button type="button" id="cc-play" class="primary" ${reducedMotion() ? "disabled" : ""}>Preview locally</button>
      </div>
    </header>
    <dl class="cc-facts">
      <div><dt>Script</dt><dd><code>${escapeHtml(entry.script_url)}</code></dd></div>
      <div><dt>Duration cap</dt><dd>${entry.duration ? `${entry.duration} ms` : "none"}</dd></div>
      <div><dt>Energy cost</dt><dd>${entry.energy_cost}</dd></div>
      <div><dt>Room bound</dt><dd>${entry.room_bound ? "yes" : "no"}</dd></div>
      <div><dt>Skip</dt><dd>${entry.skip ? "allowed" : "disabled"}</dd></div>
    </dl>
    <section aria-label="Placeholders">
      <h3>Placeholders</h3>
      ${rows.length
        ? `<p class="cc-hint">Pick a replacement per param. Preview merges these over the authored params.</p>
           ${rows.map((row, index) => placeholderRowMarkup(entry, row, index)).join("")}`
        : `<p class="cc-hint">This scene declares no placeholder params. Cue-only tokens are listed below.</p>`}
      <div class="cc-param cc-custom">
        <div class="cc-param-head"><code>custom override</code><span class="cc-kinds">advanced</span></div>
        <div class="cc-param-controls">
          <input type="text" id="cc-custom-key" placeholder="key" value="${escapeHtml(state.customKey)}" aria-label="Custom override key">
          <input type="text" id="cc-custom-value" placeholder="value" value="${escapeHtml(state.customValue)}" aria-label="Custom override value">
          <button type="button" class="quiet" id="cc-custom-add">Add</button>
        </div>
      </div>
    </section>
    ${cueOnly.length ? `
    <section aria-label="Cue tokens">
      <h3>Cue tokens (read-only)</h3>
      <p class="cc-hint">These tokens are resolved from the live trigger context and cannot be overridden per param.</p>
      <p class="cc-cue-tokens">${cueOnly.map(token => `<code title="${escapeHtml(token.kind)}">${escapeHtml(token.token)}</code>`).join(" ")}</p>
    </section>` : ""}
    <section aria-label="Dialogue cues">
      <h3>Dialogue cues (${entry.text?.length || 0})</h3>
      ${(entry.text || []).map(cue => `
        <p class="cc-cue"><span class="cc-cue-at">${cue.at}ms</span>
        ${cue.speaker ? `<strong>${escapeHtml(cue.speaker)}</strong> ` : ""}${escapeHtml(cue.say)}</p>
      `).join("") || `<p class="cc-hint">No cues.</p>`}
    </section>
    <p id="cc-status" class="cc-status" aria-live="polite"></p>`;
  detail.querySelectorAll("[data-override]").forEach(input => {
    input.oninput = () => {
      state.overrides[input.dataset.override] = input.value;
    };
  });
  detail.querySelectorAll("[data-reset]").forEach(button => {
    button.onclick = () => {
      const key = button.dataset.reset;
      const authored = entry.params?.[key];
      state.overrides[key] = authored === undefined ? "" : String(authored);
      renderDetail();
    };
  });
  detail.querySelectorAll("[data-row]").forEach(button => {
    button.onclick = () => openRowPicker(entry, Number(button.dataset.row), button.dataset.token);
  });
  const addButton = detail.querySelector("#cc-custom-add");
  if (addButton) {
    addButton.onclick = () => {
      state.customKey = detail.querySelector("#cc-custom-key").value.trim();
      state.customValue = detail.querySelector("#cc-custom-value").value;
      if (!state.customKey) return;
      state.overrides[state.customKey] = state.customValue;
      toast(`Override ${state.customKey} staged for preview.`);
    };
  }
  detail.querySelector("#cc-play").onclick = () => void previewSelected();
}

function tokenChoices(kind) {
  const choices = state.data?.choices || {};
  if (kind === "card") {
    return (choices.cards || []).map(card => ({
      value: `$card:${card.id}`,
      label: card.label,
      sub: [card.rarity, card.type, card.source].filter(Boolean).join(" · "),
      imageUrl: card.image_url,
    }));
  }
  if (kind === "prop") {
    return (choices.props || []).map(prop => ({
      value: `$prop:${prop.id}`,
      label: prop.label,
      sub: prop.id,
      modelUrl: prop.model_url,
      scale: prop.scale,
    }));
  }
  if (kind === "sticker") {
    return (choices.stickers || []).map(sticker => ({
      value: `$sticker:${sticker.name}`,
      label: sticker.name,
      sub: "sticker",
      imageUrl: sticker.image_url,
    }));
  }
  if (kind === "user") {
    return (choices.users || []).map(user => ({
      value: `$user:${user.id}`,
      label: user.self ? `${user.name} (you)` : user.name,
      sub: "room user",
      imageUrl: user.image_url,
    }));
  }
  if (kind === "peep") {
    return (choices.peeps || []).map(peep => ({
      value: `$peep:${peep.id}`,
      label: peep.label,
      sub: peep.room_id,
      imageUrl: peep.image_url,
    }));
  }
  if (kind === "me") {
    const self = [{ value: "$me", label: "Your sticker", sub: "self" }];
    const stickers = (choices.stickers || []).map(sticker => ({
      value: `$sticker:${sticker.name}`,
      label: sticker.name,
      sub: "sticker",
      imageUrl: sticker.image_url,
    }));
    return [...self, ...stickers];
  }
  return [];
}

function openRowPicker(entry, rowIndex, token) {
  const row = placeholderRows(entry)[rowIndex];
  if (!row) return;
  const kind = row.tokens.find(entry => entry.token === token)?.kind || row.tokens[0]?.kind || "";
  const choices = tokenChoices(kind);
  if (!choices.length) {
    toast(`No ${kind || "value"} choices are available in ${state.roomId}.`);
    return;
  }
  picker.open({
    title: `${row.key} · replace ${token}`,
    choices,
    onPick: choice => {
      const current = String(state.overrides[row.key] ?? row.value ?? "");
      state.overrides[row.key] = current.includes(token)
        ? current.replace(token, choice.value)
        : choice.value;
      renderDetail();
    },
  });
}

function setStatus(message) {
  const node = detail.querySelector("#cc-status");
  if (node) node.textContent = String(message || "");
}

function selectScene(id) {
  const entry = (state.data?.cutscenes || []).find(candidate => candidate.id === id);
  if (!entry) return;
  state.selectedId = entry.id;
  state.overrides = {};
  for (const row of placeholderRows(entry)) state.overrides[String(row.key)] = String(row.value ?? "");
  state.customKey = "";
  state.customValue = "";
  renderList();
  renderDetail();
}

async function previewSelected() {
  const entry = selectedEntry();
  if (!entry || state.playing) return;
  if (reducedMotion()) {
    syncMotionNotice();
    return;
  }
  state.playing = true;
  setStatus("Building preview…");
  try {
    const body = await previewCutscene({
      id: entry.id,
      room_id: state.roomId,
      params: changedParams(entry, state.overrides),
    });
    player.clearQueue();
    player.enqueue(body.event);
    setStatus(`Playing “${entry.title}”.`);
  } catch (error) {
    toast(error?.message || "Preview failed.");
    setStatus("");
  } finally {
    state.playing = false;
  }
}

function syncWorldStylesheet() {
  const href = String(state.data?.world?.world_css_url || "");
  if (state.data?.world?.id) root.dataset.world = state.data.world.id;
  else delete root.dataset.world;
  let link = document.head.querySelector("link[data-world-stylesheet]");
  if (!href) {
    link?.remove();
    return;
  }
  if (!link) {
    link = document.createElement("link");
    link.rel = "stylesheet";
    link.dataset.worldStylesheet = "";
    document.head.append(link);
  }
  if (link.getAttribute("href") !== href) link.href = href;
}

async function refresh() {
  try {
    state.data = await loadCatalog(state.roomId);
  } catch (error) {
    state.data = null;
    detail.innerHTML = `<p class="cc-empty">Could not load the catalog: ${escapeHtml(error?.message || error)}</p>`;
    return;
  }
  const rooms = state.data.rooms || [];
  roomSelect.innerHTML = rooms.map(room => `
    <option value="${escapeHtml(room.id)}">${escapeHtml(room.label)}</option>`).join("");
  state.roomId = state.data.room_id;
  roomSelect.value = state.roomId;
  worldLabel.textContent = `${state.data.world.label} · ${(state.data.cutscenes || []).length} cutscenes`;
  if (!selectedEntry()) {
    const playable = filterCutscenes(state.data.cutscenes, { tab: "playable" });
    state.selectedId = (playable[0] || state.data.cutscenes[0])?.id || "";
  }
  const entry = selectedEntry();
  state.overrides = {};
  if (entry) for (const row of placeholderRows(entry)) state.overrides[String(row.key)] = String(row.value ?? "");
  syncWorldStylesheet();
  player.sync();
  renderList();
  renderDetail();
}

function boot() {
  backLink.href = withBase("/");
  syncMotionNotice();
  state.motionQuery.addEventListener?.("change", () => {
    syncMotionNotice();
    player.sync();
    renderDetail();
  });
  renderTabs();
  searchInput.oninput = renderList;
  refreshButton.onclick = () => void refresh();
  roomSelect.onchange = () => {
    state.roomId = roomSelect.value;
    state.selectedId = "";
    void refresh();
  };
  loadSession()
    .then(() => refresh())
    .catch(error => {
      detail.innerHTML = `<p class="cc-empty">Could not load the catalog: ${escapeHtml(error?.message || error)}</p>`;
    });
}

boot();
