import {
  loadFile,
  loadFiles,
  loadJobs,
  loadSession,
  outputUrl,
  postprocess,
  reseedFile,
  saveFile,
  startBake,
} from "./api.js";
import { createModelPreview, renderModelThumb } from "./model-preview.js";
import { escapeHtml } from "../../app/js/presentation.js";
import {
  normalizeTaskForSave,
  previewKind,
  taskMatches,
  tasksSnapshot,
  validateTaskDraft,
} from "./validate.js";

function clone(value) {
  return typeof structuredClone === "function"
    ? structuredClone(value)
    : JSON.parse(JSON.stringify(value));
}

function numberOr(value, fallback) {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : fallback;
}

const QUEUE_LIMIT = 12;
const AUTOSAVE_DELAY = 1000;

const state = {
  files: [],
  fileId: "",
  tasks: [],
  simplify: {},
  snapshot: "",
  selectedLabel: "",
  checked: new Set(),
  filter: "",
  activeTab: "task",
  status: "",
  error: "",
  jobs: [],
  jobTimer: 0,
  pinnedJobs: new Set(),
  autosaveTimer: 0,
  thumbs: new Map(),
  previewKey: "",
};

const elements = {
  toolbar: document.getElementById("ab-toolbar"),
  files: document.getElementById("ab-files"),
  tasks: document.getElementById("ab-tasks"),
  previewMedia: document.getElementById("ab-preview-media"),
  previewInfo: document.getElementById("ab-preview-info"),
  jobs: document.getElementById("ab-jobs"),
  tabs: document.getElementById("ab-tabs"),
  editor: document.getElementById("ab-editor"),
  postprocess: document.getElementById("ab-postprocess"),
  bake: document.getElementById("ab-bake"),
  toast: document.getElementById("ab-toast"),
};

let modelPreview = null;
let modelPreviewError = "";

function ensureModelPreview() {
  if (modelPreview) return modelPreview;
  const canvas = document.getElementById("ab-model-canvas");
  if (!canvas) return null;
  modelPreview = createModelPreview({
    canvas,
    onError: () => {
      modelPreviewError = "Could not load this GLB preview.";
      renderPreviewInfo();
    },
  });
  return modelPreview;
}

function selectedTask() {
  return state.tasks.find(task => task.label === state.selectedLabel) || null;
}

function visibleTasks() {
  return state.tasks.filter(task => taskMatches(task, state.filter));
}

function isDirty() {
  if (!state.fileId) return false;
  return tasksSnapshot(state.tasks, state.simplify) !== state.snapshot;
}

function takeSnapshot() {
  state.snapshot = tasksSnapshot(state.tasks, state.simplify);
}

function renderToolbar() {
  const dirty = isDirty();
  elements.toolbar.innerHTML = `
    <div class="ab-toolbar-group">
      <strong class="ab-brand">Asset Bakery</strong>
      <span class="ab-file-id">${escapeHtml(state.fileId || "no file selected")}</span>
      ${dirty ? `<span class="ab-dirty" title="Unsaved changes">●</span>` : ""}
    </div>
    <div class="ab-toolbar-group">
      <button type="button" class="ab-quiet" data-ab-refresh>Refresh files</button>
      <button type="button" class="ab-quiet" data-ab-discard ${state.fileId && dirty ? "" : "disabled"}>Discard changes</button>
      <button type="button" class="ab-quiet" data-ab-save ${state.fileId && dirty ? "" : "disabled"}>Save bake.json</button>
      <button type="button" class="ab-quiet" data-ab-reseed ${state.fileId ? "" : "disabled"}>Reseed</button>
      <button type="button" class="ab-positive" data-ab-bake-selected ${state.checked.size ? "" : "disabled"}>Bake selected (${state.checked.size})</button>
      <button type="button" class="ab-positive" data-ab-bake-file ${state.fileId ? "" : "disabled"}>Bake file</button>
      <label class="ab-check"><input type="checkbox" data-ab-force> force</label>
      <label class="ab-check"><input type="checkbox" data-ab-dryrun> dry-run</label>
    </div>
  `;
}

function renderFiles() {
  const query = state.filterFiles || "";
  const files = state.files.filter(entry => !query || entry.id.toLowerCase().includes(query.toLowerCase()));
  elements.files.innerHTML = `
    <div class="ab-search-row"><input type="search" data-ab-file-search placeholder="Filter ${state.files.length} files" value="${escapeHtml(query)}" aria-label="Filter bake files"></div>
    <div class="ab-file-list">
    ${files.map(entry => `
      <button type="button" class="ab-file${entry.id === state.fileId ? " is-selected" : ""}" data-ab-file="${escapeHtml(entry.id)}">
        <code>${escapeHtml(entry.id)}</code>
        <small>${entry.tasks} task(s) · ${escapeHtml(Object.entries(entry.tools || {}).map(([tool, count]) => `${tool}:${count}`).join(" ") || "empty")}</small>
      </button>
    `).join("") || "<p>No bake.json files found.</p>"}
    </div>
  `;
}

function renderTabs() {
  const tabs = [["task", "Task"], ["post", "Postprocess"], ["bake", "File"]];
  elements.tabs.innerHTML = tabs.map(([id, label]) => `
    <button type="button" class="ab-tab${state.activeTab === id ? " is-active" : ""}" data-ab-tab="${id}">${label}</button>
  `).join("");
  elements.editor.hidden = state.activeTab !== "task";
  elements.postprocess.hidden = state.activeTab !== "post";
  elements.bake.hidden = state.activeTab !== "bake";
}

function thumbFor(task) {
  const preview = task._preview || {};
  if (!preview.exists) return `<span class="ab-thumb ab-thumb-missing" aria-hidden="true">—</span>`;
  const kind = previewKind(task.output);
  if (kind === "image") {
    return `<img class="ab-thumb" loading="lazy" src="${escapeHtml(outputUrl(state.fileId, task.label))}" alt="">`;
  }
  if (kind === "model") {
    const cached = state.thumbs.get(task.label);
    if (cached) return `<img class="ab-thumb" src="${cached}" alt="">`;
    return `<span class="ab-thumb ab-thumb-model" data-ab-thumb="${escapeHtml(task.label)}" aria-hidden="true">3D</span>`;
  }
  return `<span class="ab-thumb ab-thumb-model" aria-hidden="true">♪</span>`;
}

function renderTasks() {
  const tasks = visibleTasks();
  elements.tasks.innerHTML = `
    <div class="ab-task-search"><input type="search" data-ab-task-search placeholder="Filter ${state.tasks.length} tasks" value="${escapeHtml(state.filter)}" aria-label="Filter tasks"></div>
    <div class="ab-task-list">
    ${tasks.map(task => {
      const preview = task._preview || {};
      const missing = preview.exists === false ? " is-missing" : "";
      return `
      <div class="ab-task-row${task.label === state.selectedLabel ? " is-selected" : ""}">
        <input type="checkbox" data-ab-check="${escapeHtml(task.label)}" ${state.checked.has(task.label) ? "checked" : ""} aria-label="Select ${escapeHtml(task.label)}">
        ${thumbFor(task)}
        <button type="button" class="ab-task-pick" data-ab-task="${escapeHtml(task.label)}">
          <strong>${escapeHtml(task.label)}</strong>
          <small>${escapeHtml(task.tool || "")} · ${escapeHtml(String(task.prompt || "").slice(0, 100))}</small>
        </button>
        <span class="ab-badge${missing}">${preview.exists ? `${preview.width || "?"}×${preview.height || "?"}` : "missing"}</span>
      </div>`;
    }).join("") || "<p>Select a bake.json file to edit its tasks.</p>"}
    </div>
  `;
  queueThumbs(tasks);
}

function queueThumbs(tasks) {
  for (const task of tasks || []) {
    if (previewKind(task.output) !== "model") continue;
    if (!(task._preview || {}).exists) continue;
    if (state.thumbs.get(task.label)) continue;
    const url = outputUrl(state.fileId, task.label);
    renderModelThumb(url)
      .then(dataUrl => {
        if (!dataUrl) return;
        state.thumbs.set(task.label, dataUrl);
        const node = elements.tasks.querySelector(`[data-ab-thumb="${CSS.escape(task.label)}"]`);
        if (node && node.tagName !== "IMG") {
          const image = document.createElement("img");
          image.className = "ab-thumb";
          image.src = dataUrl;
          image.alt = "";
          node.replaceWith(image);
        }
      })
      .catch(() => {});
  }
}

function renderPreview() {
  const task = selectedTask();
  if (!task) {
    state.previewKey = "";
    elements.previewMedia.innerHTML = "<p>Select a task to preview its baked output.</p>";
    elements.previewInfo.innerHTML = "";
    return;
  }
  const kind = previewKind(task.output);
  const src = outputUrl(state.fileId, task.label);
  const key = `${state.fileId}|${task.label}|${kind}`;
  if (key !== state.previewKey) {
    state.previewKey = key;
    modelPreviewError = "";
    if (kind === "image") {
      elements.previewMedia.innerHTML = (task._preview || {}).exists
        ? `<img src="${escapeHtml(src)}" alt="Baked preview of ${escapeHtml(task.label)}">`
        : "<p>No baked output yet. Run a bake to generate it.</p>";
    } else if (kind === "model") {
      elements.previewMedia.innerHTML = (task._preview || {}).exists
        ? `<canvas id="ab-model-canvas" aria-label="3D preview of ${escapeHtml(task.label)}. Drag to rotate."></canvas>`
        : "<p>No baked output yet. Run a bake to generate it.</p>";
      modelPreview?.dispose();
      modelPreview = null;
    } else {
      elements.previewMedia.innerHTML = (task._preview || {}).exists
        ? `<audio controls src="${escapeHtml(src)}"></audio>`
        : "<p>No baked audio yet.</p>";
    }
  }
  if (kind === "model" && (task._preview || {}).exists) {
    const viewer = ensureModelPreview();
    if (viewer) {
      viewer.setModel(src);
      viewer.resize();
    } else if (modelPreviewError) {
      elements.previewMedia.innerHTML = `<p>${escapeHtml(modelPreviewError)}</p>`;
    }
  }
  renderPreviewInfo();
}

function renderPreviewInfo() {
  const task = selectedTask();
  if (!task) {
    elements.previewInfo.innerHTML = "";
    return;
  }
  const preview = task._preview || {};
  elements.previewInfo.innerHTML = `
    <h3>${escapeHtml(task.label)}</h3>
    ${modelPreviewError && previewKind(task.output) === "model" ? `<p class="ab-badge is-missing">${escapeHtml(modelPreviewError)}</p>` : ""}
    <p><span class="ab-badge">${escapeHtml(task.tool || "")}</span>
    <span class="ab-badge${preview.exists ? "" : " is-missing"}">${preview.exists ? "output exists" : "no output"}</span></p>
    <p><code>${escapeHtml(String(task.output || ""))}</code></p>
    ${preview.exists ? `<p>${preview.width ? `${preview.width}×${preview.height} · ` : ""}${preview.size ?? "?"} bytes · ${escapeHtml(preview.mtime || "")}</p>` : ""}
    <p>${escapeHtml(String(task.prompt || ""))}</p>
  `;
}

function argsEditor(args) {
  const text = (key, kind = "text") => {
    const value = args?.[key] ?? "";
    return `<label class="ab-field"><span>${key}</span><input type="${kind}" data-ab-arg="${key}" value="${escapeHtml(value)}"></label>`;
  };
  return `
    <div class="ab-row">${text("seed", "number")}${text("steps", "number")}</div>
    <div class="ab-row">${text("width", "number")}${text("height", "number")}</div>
    <div class="ab-row">${text("faces", "number")}${text("duration", "number")}</div>
    <label class="ab-field"><span>template</span><input type="text" data-ab-arg="template" value="${escapeHtml(args?.template ?? "")}"></label>
    <label class="ab-field"><span>negative</span><textarea data-ab-arg="negative" rows="2">${escapeHtml(args?.negative ?? "")}</textarea></label>
  `;
}

function renderEditor() {
  const task = selectedTask();
  if (!task) {
    elements.editor.innerHTML = "<h2>Task</h2><p>Select a task to edit its bake parameters.</p>";
    return;
  }
  const errors = validateTaskDraft(task);
  const args = task.args || {};
  elements.editor.innerHTML = `
    <h2>${escapeHtml(task.label)}</h2>
    ${errors.length ? `<p class="ab-badge is-missing">${escapeHtml(errors.join(" "))}</p>` : ""}
    <label class="ab-field"><span>tool</span>
      <select data-ab-field="tool">${["image", "asset", "sound", "TEMPLATE"].map(tool => `<option value="${tool}"${task.tool === tool ? " selected" : ""}>${tool}</option>`).join("")}</select>
    </label>
    <label class="ab-field"><span>prompt / description</span><textarea data-ab-field="prompt" rows="4">${escapeHtml(task.prompt || "")}</textarea></label>
    <label class="ab-field"><span>output</span><input type="text" data-ab-field="output" value="${escapeHtml(task.output || "")}"></label>
    <h3>Args</h3>
    ${argsEditor(args)}
    <div class="ab-actions">
      <button type="button" class="ab-quiet" data-ab-add-random-seed>Randomize seed</button>
      <button type="button" class="ab-quiet" data-ab-bake-one>Bake this task</button>
    </div>
    <h3>Simplify override</h3>
    <label class="ab-field"><span>simplify JSON (optional)</span><textarea data-ab-simplify rows="3">${escapeHtml(JSON.stringify(task.simplify || {}, null, 2))}</textarea></label>
  `;
}

function renderPostprocess() {
  const task = selectedTask();
  const isImage = task && previewKind(task.output) === "image";
  elements.postprocess.innerHTML = `
    <h2>Postprocess</h2>
    ${!task ? "<p>Select a task first.</p>" : isImage ? `
      <label class="ab-field"><span>tolerance (0–128)</span><input type="number" data-ab-pp="tolerance" value="32" min="0" max="128"></label>
      <div class="ab-actions"><button type="button" class="ab-quiet" data-ab-pp-bg>Remove background</button></div>
      <div class="ab-row">
        <label class="ab-field"><span>width</span><input type="number" data-ab-pp="width" min="16" max="4096"></label>
        <label class="ab-field"><span>height</span><input type="number" data-ab-pp="height" min="16" max="4096"></label>
      </div>
      <div class="ab-actions"><button type="button" class="ab-quiet" data-ab-pp-resize>Resize</button></div>
      <label class="ab-field"><span>trim padding (0–256)</span><input type="number" data-ab-pp="padding" value="0" min="0" max="256"></label>
      <div class="ab-actions"><button type="button" class="ab-quiet" data-ab-pp-trim>Trim borders</button></div>
    ` : "<p>Background removal, resize, and trim are available for image outputs.</p>"}
  `;
}

function renderBakePane() {
  const simplifyText = escapeHtml(JSON.stringify(state.simplify || {}, null, 2));
  elements.bake.innerHTML = `
    <h2>File</h2>
    <p><code>${escapeHtml(state.fileId || "—")}</code></p>
    <label class="ab-field"><span>simplify</span><textarea data-ab-file-simplify rows="6">${simplifyText}</textarea></label>
  `;
}

function shortFileId(fileId) {
  const parts = String(fileId || "").split("/");
  return parts.length > 2 ? `…/${parts.slice(-2).join("/")}` : String(fileId || "—");
}

function timeAgo(iso) {
  const then = Date.parse(iso || "");
  if (!Number.isFinite(then)) return "";
  const seconds = Math.max(0, Math.round((Date.now() - then) / 1000));
  if (seconds < 60) return `${seconds}s ago`;
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  return `${Math.round(minutes / 60)}h ago`;
}

function renderJobs() {
  const active = state.jobs.filter(job => job.status === "running" || job.status === "queued").length;
  const visible = state.jobs.slice(0, QUEUE_LIMIT);
  const hidden = state.jobs.length - visible.length;
  elements.jobs.innerHTML = `
    <h2>Baking queue <span class="ab-job-count">${state.jobs.length}</span>${active ? ` · ${active} active` : ""}</h2>
    ${visible.map(job => {
      const open = job.status === "running" || job.status === "queued" || state.pinnedJobs.has(job.id);
      const filters = (job.filters || []).join(", ");
      const when = timeAgo(job.created_at);
      return `
      <details class="ab-queue-row" data-ab-job="${escapeHtml(job.id)}"${open ? " open" : ""}>
        <summary>
          <span class="ab-dot is-${escapeHtml(job.status)}" aria-hidden="true"></span>
          <code>${escapeHtml(String(job.id).slice(0, 8))}</code>
          <span class="ab-queue-file">${escapeHtml(shortFileId(job.file_id))}${filters ? ` · ${escapeHtml(filters.length > 60 ? `${filters.slice(0, 57)}…` : filters)}` : ""}</span>
          <span class="ab-queue-meta">${escapeHtml(job.status)}${job.exit_code !== null && job.exit_code !== undefined ? ` (${job.exit_code})` : ""}${when ? ` · ${escapeHtml(when)}` : ""}</span>
        </summary>
        <pre>${escapeHtml((job.log || "").slice(-2000) || "No output yet.")}</pre>
      </details>`;
    }).join("") || "<p>No bake jobs yet. Queue one with Bake file or Bake selected.</p>"}
    ${hidden > 0 ? `<p>${hidden} older job(s) hidden.</p>` : ""}
  `;
}

function render() {
  renderToolbar();
  renderFiles();
  renderTabs();
  renderTasks();
  renderPreview();
  renderEditor();
  renderPostprocess();
  renderBakePane();
  renderJobs();
  elements.toast.textContent = state.error || state.status || "";
}

function fail(error) {
  state.error = error?.message || String(error);
  state.status = "";
  render();
}

function note(message) {
  state.status = message;
  state.error = "";
  render();
}

async function refreshFiles() {
  const body = await loadFiles();
  state.files = body.files || [];
  if (state.fileId && !state.files.some(entry => entry.id === state.fileId)) {
    state.fileId = "";
    state.tasks = [];
  }
}

async function openFile(fileId) {
  const body = await loadFile(fileId);
  state.fileId = body.id;
  state.tasks = body.tasks || [];
  state.simplify = body.simplify || {};
  state.selectedLabel = state.tasks[0]?.label || "";
  state.checked = new Set();
  state.thumbs = new Map();
  state.previewKey = "";
  takeSnapshot();
  note(`Editing ${body.id} (${body.count} tasks).`);
}

async function selectFile(fileId) {
  if (fileId === state.fileId) return;
  if (isDirty()) {
    try {
      await persistFile({ quiet: true });
    } catch (error) {
      fail(new Error(`Auto-save failed: ${error.message}. Fix or discard changes first.`));
      return;
    }
  }
  try {
    await openFile(fileId);
  } catch (error) {
    fail(error);
  }
}

async function persistFile({ quiet = false } = {}) {
  const tasks = state.tasks.map(normalizeTaskForSave);
  let simplify = state.simplify || {};
  const node = document.querySelector("[data-ab-file-simplify]");
  if (node) {
    try {
      simplify = node.value.trim() ? JSON.parse(node.value) : {};
    } catch (error) {
      throw new Error(`File simplify is not valid JSON: ${error.message}`);
    }
  }
  const body = await saveFile({ file_id: state.fileId, tasks, simplify });
  state.tasks = body.tasks || [];
  state.simplify = body.simplify || {};
  takeSnapshot();
  await refreshFiles();
  if (quiet) {
    state.status = `Auto-saved ${state.fileId}.`;
    state.error = "";
    renderToolbar();
    renderTasks();
    renderPreview();
    elements.toast.textContent = state.status;
    return body;
  }
  note(`Saved ${state.fileId}.`);
  return body;
}

function scheduleAutosave() {
  renderToolbar();
  if (!state.fileId || !isDirty()) return;
  window.clearTimeout(state.autosaveTimer);
  state.autosaveTimer = window.setTimeout(() => {
    persistFile({ quiet: true }).catch(error => fail(error));
  }, AUTOSAVE_DELAY);
}

async function refreshJobs() {
  try {
    const body = await loadJobs();
    state.jobs = body.jobs || [];
    renderJobs();
  } catch {
    // Job polling is best-effort while editing.
  }
}

function startJobPolling() {
  window.clearInterval(state.jobTimer);
  state.jobTimer = window.setInterval(refreshJobs, 2500);
}

async function bakeCurrent({ filters, force, dryRun, reseed }) {
  const body = await startBake({ file_id: state.fileId, filters, force, dry_run: dryRun, reseed });
  note(`Bake job ${body.job.id} queued.`);
  await refreshJobs();
}

function readEditorField(target) {
  const task = selectedTask();
  if (!task) return;
  const field = target.dataset.abField;
  if (field) {
    task[field] = target.value;
    return;
  }
  const arg = target.dataset.abArg;
  if (arg) {
    task.args = task.args || {};
    if (target.type === "number") {
      task.args[arg] = target.value === "" ? undefined : numberOr(target.value, 0);
    } else {
      task.args[arg] = target.value;
    }
  }
}

async function handleClick(target) {
  const dataset = target.dataset || {};
  if (dataset.abTab !== undefined) {
    state.activeTab = dataset.abTab;
    render();
    return;
  }
  if (dataset.abRefresh !== undefined) {
    try {
      await refreshFiles();
      await refreshJobs();
      note("Catalog refreshed.");
    } catch (error) { fail(error); }
    return;
  }
  if (dataset.abFile !== undefined) {
    void selectFile(dataset.abFile);
    return;
  }
  if (dataset.abTask !== undefined) {
    state.selectedLabel = dataset.abTask;
    render();
    return;
  }
  if (dataset.abDiscard !== undefined) {
    try {
      await openFile(state.fileId);
      note("Discarded unsaved changes.");
    } catch (error) { fail(error); }
    return;
  }
  if (dataset.abSave !== undefined) {
    try { await persistFile(); } catch (error) { fail(error); }
    return;
  }
  if (dataset.abReseed !== undefined) {
    try {
      const body = await reseedFile(state.fileId, false);
      await openFile(state.fileId);
      note(`Reseeded ${body.reseeded} seed(s).`);
    } catch (error) { fail(error); }
    return;
  }
  if (dataset.abBakeFile !== undefined) {
    try {
      await bakeCurrent({
        filters: [],
        force: document.querySelector("[data-ab-force]")?.checked || false,
        dryRun: document.querySelector("[data-ab-dryrun]")?.checked || false,
        reseed: false,
      });
    } catch (error) { fail(error); }
    return;
  }
  if (dataset.abBakeSelected !== undefined) {
    try {
      await bakeCurrent({
        filters: [...state.checked],
        force: document.querySelector("[data-ab-force]")?.checked || false,
        dryRun: document.querySelector("[data-ab-dryrun]")?.checked || false,
        reseed: false,
      });
    } catch (error) { fail(error); }
    return;
  }
  if (dataset.abBakeOne !== undefined) {
    try {
      await bakeCurrent({
        filters: [state.selectedLabel],
        force: true,
        dryRun: false,
        reseed: false,
      });
    } catch (error) { fail(error); }
    return;
  }
  if (dataset.abAddRandomSeed !== undefined) {
    const task = selectedTask();
    if (task) {
      task.args = task.args || {};
      task.args.seed = 1 + Math.floor(Math.random() * 2147483646);
      scheduleAutosave();
      state.status = "Assigned a random seed. Auto-saving…";
      state.error = "";
      render();
    }
    return;
  }
  if (dataset.abPpBg !== undefined || dataset.abPpResize !== undefined || dataset.abPpTrim !== undefined) {
    const params = {};
    for (const node of document.querySelectorAll("[data-ab-pp]")) {
      if (node.value !== "") params[node.dataset.abPp] = numberOr(node.value, 0);
    }
    const operation = dataset.abPpBg !== undefined ? "bg_remove" : dataset.abPpResize !== undefined ? "resize" : "trim";
    try {
      const body = await postprocess({ file_id: state.fileId, label: state.selectedLabel, operation, params });
      await openFile(state.fileId);
      note(`Postprocess ${operation}: ${JSON.stringify(body).slice(0, 160)}`);
    } catch (error) { fail(error); }
  }
}

document.addEventListener("click", event => {
  const target = event.target.closest("[data-ab-tab],[data-ab-refresh],[data-ab-file],[data-ab-task],[data-ab-discard],[data-ab-save],[data-ab-reseed],[data-ab-bake-file],[data-ab-bake-selected],[data-ab-bake-one],[data-ab-add-random-seed],[data-ab-pp-bg],[data-ab-pp-resize],[data-ab-pp-trim]");
  if (target) void handleClick(target);
});

document.addEventListener("toggle", event => {
  const row = event.target.closest?.("[data-ab-job]");
  if (!row) return;
  if (row.open) state.pinnedJobs.add(row.dataset.abJob);
  else state.pinnedJobs.delete(row.dataset.abJob);
}, true);

document.addEventListener("change", event => {
  const target = event.target;
  if (!target?.dataset) return;
  if (target.dataset.abFileSearch !== undefined) {
    state.filterFiles = target.value;
    renderFiles();
    return;
  }
  if (target.dataset.abTaskSearch !== undefined) {
    state.filter = target.value;
    renderTasks();
    return;
  }
  if (target.dataset.abCheck !== undefined) {
    if (target.checked) state.checked.add(target.dataset.abCheck);
    else state.checked.delete(target.dataset.abCheck);
    renderToolbar();
    return;
  }
  if (target.dataset.abSimplify !== undefined) {
    const task = selectedTask();
    if (!task) return;
    try {
      task.simplify = target.value.trim() ? JSON.parse(target.value) : {};
      state.error = "";
    } catch (error) {
      state.error = `Task simplify is not valid JSON: ${error.message}`;
    }
    scheduleAutosave();
    elements.toast.textContent = state.error || state.status || "";
    return;
  }
  if (target.dataset.abFileSimplify !== undefined) {
    try {
      state.simplify = target.value.trim() ? JSON.parse(target.value) : {};
      state.error = "";
    } catch (error) {
      state.error = `File simplify is not valid JSON: ${error.message}`;
    }
    scheduleAutosave();
    elements.toast.textContent = state.error || state.status || "";
    return;
  }
  if (target.dataset.abField !== undefined || target.dataset.abArg !== undefined) {
    readEditorField(target);
    scheduleAutosave();
  }
});

document.addEventListener("input", event => {
  const target = event.target;
  if (!target?.dataset) return;
  if (target.dataset.abFileSearch !== undefined) {
    state.filterFiles = target.value;
    renderFiles();
  } else if (target.dataset.abTaskSearch !== undefined) {
    state.filter = target.value;
    renderTasks();
  } else if (target.dataset.abFileSimplify !== undefined) {
    try {
      state.simplify = target.value.trim() ? JSON.parse(target.value) : {};
      state.error = "";
    } catch {
      // Invalid JSON surfaces on change; keep typing.
    }
    renderToolbar();
  } else if (target.dataset.abField !== undefined || target.dataset.abArg !== undefined) {
    readEditorField(target);
    scheduleAutosave();
  }
});

async function boot() {
  try {
    await loadSession();
    await refreshFiles();
    await refreshJobs();
    const requested = new URLSearchParams(window.location.search).get("file");
    if (requested && state.files.some(entry => entry.id === requested)) {
      await openFile(requested);
    } else {
      state.status = state.files.length
        ? `Found ${state.files.length} bake.json file(s). Select one to edit.`
        : "No bake.json files found under data/, worlds/, client/, or mods/.";
    }
    startJobPolling();
    render();
  } catch (error) {
    fail(error);
  }
}

boot();
