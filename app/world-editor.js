"use strict";

// ---------------------------------------------------------------------------
// Auth token helpers
// ---------------------------------------------------------------------------

const TOKEN_KEY = "tr_rest_auth_token";

// Image loading helpers (mirrors utils.js)
function _loadImage(url) {
  return new Promise((resolve, reject) => {
    const img = new Image();
    img.onload = () => resolve(img);
    img.onerror = () => reject(new Error(`Failed to load: ${url}`));
    img.src = url;
  });
}

function _drawSpriteThumb(canvas, srcImg, sx, sy, sw, sh) {
  const tc = canvas.getContext("2d");
  const dw = canvas.width, dh = canvas.height;
  tc.clearRect(0, 0, dw, dh);
  if (!srcImg || sw <= 0 || sh <= 0) return;
  const tmp = document.createElement("canvas");
  tmp.width = sw; tmp.height = sh;
  tmp.getContext("2d").drawImage(srcImg, sx, sy, sw, sh, 0, 0, sw, sh);
  const scale = Math.min(dw / sw, dh / sh);
  const scaledW = Math.round(sw * scale), scaledH = Math.round(sh * scale);
  const dx = Math.floor((dw - scaledW) / 2), dy = Math.floor((dh - scaledH) / 2);
  tc.imageSmoothingEnabled = false;
  tc.drawImage(tmp, 0, 0, sw, sh, dx, dy, scaledW, scaledH);
}

function _cachedLoadImage(url) {
  if (!WE.imgCache.has(url)) {
    WE.imgCache.set(url, _loadImage(url));
  }
  return WE.imgCache.get(url);
}

const authHeaders = (token) =>
  token ? { "X-TR-Auth": token, "Content-Type": "application/json" }
        : { "Content-Type": "application/json" };

// ---------------------------------------------------------------------------
// State
// ---------------------------------------------------------------------------

const WE = {
  token: "",
  world_id: "",
  world_label: "",
  rooms: new Map(),   // room_id -> room
  ways: new Map(),    // way_id -> way
  images: [],
  propLibrary: [],    // flat [{prop_id, label, display:{prop_meta:{...}}}]
  propLibrarySets: [], // [{setLabel, scope, filename, props:[...]}]

  currentRoomId: null,
  selectedPropId: null,  // prop_instance_id
  selectedWayId: null,

  activeTool: "select",  // "select" | "place" | "exit"
  libraryPropId: null,   // prop_id selected in library for placement
  libActiveSet: null,    // filename of active library set tab
  libSearch: "",

  showGrid: false,
  pan: { x: 0, y: 0 },
  zoom: 1.0,

  drag: null,  // {propInstanceId, startMouseX, startMouseY, origX, origY}

  // per-room draft: room_id -> cloned room snapshot
  drafts: new Map(),
  dirty: new Set(),

  // undo/redo: room_id -> {past:[], future:[]}
  history: new Map(),

  exitPickerPropId: null,

  // world map layout: room_id -> {x, y}
  mapLayout: new Map(),
  mapConnectMode: false,
  mapConnectFrom: null,
  libTagFilter: "",
  libAllTags: [],
  imgCache: new Map(),   // url -> Promise<HTMLImageElement>
};

// ---------------------------------------------------------------------------
// DOM refs
// ---------------------------------------------------------------------------

const $ = id => document.getElementById(id);

const authTokenEl    = null;  // removed; login handled via Login button
const btnReload      = $("btnReloadState");
const loginStatusEl  = $("loginStatus");
const tabRoom        = $("tabRoom");
const tabMap         = $("tabMap");
const toolSelect     = $("toolSelect");
const toolPlace      = $("toolPlace");
const toolExit       = $("toolExit");
const btnUndo        = $("btnUndo");
const btnRedo        = $("btnRedo");
const btnSaveRoom    = $("btnSaveRoom");
const btnSaveAll     = $("btnSaveAll");
const btnResetRoom   = $("btnResetRoom");
const btnToggleGrid  = $("btnToggleGrid");
const btnFitView     = $("btnFitView");
const roomListEl     = $("roomList");
const roomSearch     = $("roomSearch");
const btnNewRoom     = $("btnNewRoom");
const btnNewWay      = $("btnNewWay");
const roomPane       = $("roomPane");
const mapPane        = $("mapPane");
const roomTitle      = $("roomTitle");
const zoomLabel      = $("zoomLabel");
const dirtyLabel     = $("dirtyLabel");
const canvasViewport = $("canvasViewport");
const canvasStage    = $("canvasStage");
const exitPicker     = $("exitPicker");
const mapViewport    = $("mapViewport");
const mapSvg         = $("mapSvg");
const propertiesPanel = $("propertiesPanel");
const btnToggleLib   = $("btnToggleLibrary");
const libraryPanel   = $("libraryPanel");
const librarySearch  = $("librarySearch");
const libraryTabs    = $("libraryTabs");
const libraryGrid    = $("libraryGrid");
const statusText     = $("statusText");
const modalBackdrop  = $("modalBackdrop");
const modalTitle     = $("modalTitle");
const modalForm      = $("modalForm");
const btnCloseModal  = $("btnCloseModal");
const btnMapNewRoom  = $("btnMapNewRoom");
const btnMapConnect  = $("btnMapConnect");
const btnZoomIn       = $("btnZoomIn");
const btnZoomOut      = $("btnZoomOut");
const libraryTagFilter = $("libraryTagFilter");
const btnToggleSidebar = $("btnToggleSidebar");

// ---------------------------------------------------------------------------
// Status
// ---------------------------------------------------------------------------

function setStatus(msg, isError = false) {
  statusText.textContent = msg;
  statusText.style.color = isError ? "#f66" : "#b9c7e3";
}

// ---------------------------------------------------------------------------
// API helpers
// ---------------------------------------------------------------------------

async function apiFetch(method, path, body) {
  const opts = { method, headers: authHeaders(WE.token) };
  if (body !== undefined) opts.body = JSON.stringify(body);
  const res = await fetch(path, opts);
  if (res.status === 401) {
    WE.token = "";
    WE.initialLoad = false;
    localStorage.removeItem(TOKEN_KEY);
    loginStatusEl.textContent = "Session expired — please log in from the main client";
    loginStatusEl.style.color = "#f66";
    setStatus("Session expired. Please log in from the main client and return to this page.", true);
    throw new Error("Not authenticated");
  }
  const json = await res.json().catch(() => ({ ok: false, error: `HTTP ${res.status}` }));
  if (!res.ok) throw new Error(json.error || `HTTP ${res.status}`);
  return json;
}

const apiGet    = path       => apiFetch("GET",    path);
const apiPost   = (path, b)  => apiFetch("POST",   path, b);
const apiPut    = (path, b)  => apiFetch("PUT",    path, b);
const apiDelete = path       => apiFetch("DELETE", path);

// ---------------------------------------------------------------------------
// Load world state
// ---------------------------------------------------------------------------

async function loadState() {
  setStatus("Loading…");
  try {
    const data = await apiGet("/api/world-editor/state");
    applyState(data);
    setStatus(`Loaded — ${WE.rooms.size} rooms, ${WE.ways.size} ways`);
  } catch (err) {
    if (err.message === "Not authenticated") return; // 401 already handled
    setStatus(`Server error: ${err.message}`, true);
  }
}

function applyState(data) {
  WE.world_id = data.world_id || "";
  WE.world_label = data.world_label || "";
  WE.rooms = new Map((data.rooms || []).map(r => [r.room_id, r]));
  WE.ways  = new Map((data.ways  || []).map(w => [w.way_id,  w]));
  WE.images = data.images || [];
  WE.propLibrary = data.prop_library || [];
  WE.drafts = new Map();
  WE.dirty  = new Set();
  WE.history = new Map();
  WE.selectedPropId = null;
  WE.selectedWayId  = null;
  buildPropLibrarySets();
  renderRoomList();
  renderPropLibraryTabs();
  renderPropLibraryTagFilter();
  renderPropLibraryGrid();
  renderPropertiesPanel();
  const _urlRoom = new URLSearchParams(window.location.search).get("room");
  if (_urlRoom && WE.rooms.has(_urlRoom)) {
    openRoom(_urlRoom);
  } else if (WE.currentRoomId && WE.rooms.has(WE.currentRoomId)) {
    openRoom(WE.currentRoomId);
  } else if (WE.rooms.size > 0) {
    openRoom(WE.rooms.keys().next().value);
  }
  renderMapSvg();
}

function buildPropLibrarySets() {
  const setMap = new Map();
  for (const p of WE.propLibrary) {
    const key = p.display?.prop_meta?.filename || "unknown";
    const scope = p.display?.prop_meta?.scope || "";
    if (!setMap.has(key)) setMap.set(key, { filename: key, scope, props: [] });
    setMap.get(key).props.push(p);
  }
  WE.propLibrarySets = [...setMap.values()];
  // collect all unique tags across all props
  const allTagSet = new Set();
  for (const p of WE.propLibrary) {
    for (const tag of (p.tags || [])) allTagSet.add(tag);
  }
  WE.libAllTags = [...allTagSet].sort();
  WE.imgCache = new Map();  // invalidate on reload
  if (WE.propLibrarySets.length > 0 && !WE.libActiveSet) {
    WE.libActiveSet = WE.propLibrarySets[0].filename;
  }
}

// ---------------------------------------------------------------------------
// Draft helpers
// ---------------------------------------------------------------------------

function currentDraft() {
  if (!WE.currentRoomId) return null;
  if (!WE.drafts.has(WE.currentRoomId)) {
    const room = WE.rooms.get(WE.currentRoomId);
    if (!room) return null;
    WE.drafts.set(WE.currentRoomId, deepClone(room));
  }
  return WE.drafts.get(WE.currentRoomId);
}

function deepClone(obj) {
  return JSON.parse(JSON.stringify(obj));
}

function markDirty(roomId) {
  WE.dirty.add(roomId);
  updateDirtyIndicator();
  updateRoomListItem(roomId);
}

function clearDirty(roomId) {
  WE.dirty.delete(roomId);
  updateDirtyIndicator();
  updateRoomListItem(roomId);
}

function updateDirtyIndicator() {
  if (!WE.currentRoomId) { dirtyLabel.textContent = ""; return; }
  dirtyLabel.textContent = WE.dirty.has(WE.currentRoomId) ? "● unsaved" : "";
  dirtyLabel.style.color = "#ffd166";
}

// ---------------------------------------------------------------------------
// Undo/redo
// ---------------------------------------------------------------------------

function snapshotHistory(roomId) {
  if (!WE.history.has(roomId)) WE.history.set(roomId, { past: [], future: [] });
  const h = WE.history.get(roomId);
  h.past.push(deepClone(WE.drafts.get(roomId) || WE.rooms.get(roomId)));
  h.future = [];
  if (h.past.length > 50) h.past.shift();
}

function undo() {
  const id = WE.currentRoomId; if (!id) return;
  if (!WE.history.has(id)) return;
  const h = WE.history.get(id);
  if (h.past.length === 0) { setStatus("Nothing to undo"); return; }
  h.future.push(deepClone(currentDraft()));
  WE.drafts.set(id, h.past.pop());
  markDirty(id);
  renderCanvas();
  renderPropertiesPanel();
}

function redo() {
  const id = WE.currentRoomId; if (!id) return;
  if (!WE.history.has(id)) return;
  const h = WE.history.get(id);
  if (h.future.length === 0) { setStatus("Nothing to redo"); return; }
  h.past.push(deepClone(currentDraft()));
  WE.drafts.set(id, h.future.pop());
  markDirty(id);
  renderCanvas();
  renderPropertiesPanel();
}

// ---------------------------------------------------------------------------
// Room List
// ---------------------------------------------------------------------------

function renderRoomList() {
  const filter = roomSearch.value.trim().toLowerCase();
  roomListEl.innerHTML = "";

  for (const [roomId, room] of WE.rooms) {
    const label = room.label || roomId;
    const wayIds = room.ways || [];

    // Filter: show room if it, any of its ways, or any way label matches
    const roomMatch = !filter || roomId.includes(filter) || label.toLowerCase().includes(filter);
    const matchingWays = wayIds.filter(wayId => {
      if (!filter) return true;
      const way = WE.ways.get(wayId);
      const wayLabel = way ? (way.label || wayId) : wayId;
      return wayId.includes(filter) || wayLabel.toLowerCase().includes(filter);
    });
    if (!roomMatch && matchingWays.length === 0) continue;

    const isActive = roomId === WE.currentRoomId;
    const isDirty  = WE.dirty.has(roomId);
    // Collapse ways by default; expand if this room is active or a child way is selected
    const hasActiveWay = wayIds.includes(WE.selectedWayId);
    const collapsed = !isActive && !hasActiveWay && !filter;
    const storageKey = `we-tree-${roomId}`;
    const isOpen = filter
      ? true
      : (isActive || hasActiveWay || sessionStorage.getItem(storageKey) === "1");

    // Tree node row
    const row = document.createElement("div");
    row.className = "we-tree-row we-tree-room" +
      (isActive ? " is-active" : "") +
      (isDirty  ? " is-dirty"  : "");
    row.dataset.roomId = roomId;

    // Toggle arrow (only shown when there are ways)
    const arrow = document.createElement("span");
    arrow.className = "we-tree-arrow" + (wayIds.length === 0 ? " we-tree-arrow-empty" : isOpen ? " is-open" : "");
    arrow.textContent = wayIds.length > 0 ? (isOpen ? "▾" : "▸") : " ";
    arrow.addEventListener("click", e => {
      e.stopPropagation();
      const open = sessionStorage.getItem(storageKey) === "1";
      sessionStorage.setItem(storageKey, open ? "0" : "1");
      renderRoomList();
    });

    const nameEl = document.createElement("span");
    nameEl.className = "we-tree-label";
    nameEl.textContent = label;

    const draft = WE.drafts.get(roomId) || WE.rooms.get(roomId);
    const propCount = (draft?.props || []).length;
    const wayCount  = wayIds.length;
    const idEl = document.createElement("span");
    idEl.className = "we-tree-id";
    idEl.title = `${propCount} props, ${wayCount} ways`;
    idEl.textContent = `${propCount}p ${wayCount}w`;

    row.appendChild(arrow);
    row.appendChild(nameEl);
    row.appendChild(idEl);
    row.addEventListener("click", () => {
      sessionStorage.setItem(storageKey, "1");
      openRoom(roomId);
    });
    row.addEventListener("contextmenu", e => { e.preventDefault(); showRoomContextMenu(e, roomId); });
    roomListEl.appendChild(row);

    // Way children
    if (isOpen && wayIds.length > 0) {
      const showWays = filter ? matchingWays : wayIds;
      for (const wayId of showWays) {
        const way = WE.ways.get(wayId);
        const wayLabel = way ? (way.label || wayId) : wayId;
        const targetLabel = way ? (way.to_room_label || way.to_room_id || "?") : "?";

        const wrow = document.createElement("div");
        wrow.className = "we-tree-row we-tree-way" + (wayId === WE.selectedWayId ? " is-active" : "");
        wrow.dataset.wayId = wayId;

        const wicon = document.createElement("span");
        wicon.className = "we-tree-way-icon";
        wicon.textContent = "→";

        const wnameEl = document.createElement("span");
        wnameEl.className = "we-tree-label";
        wnameEl.textContent = wayLabel;

        const wtargetEl = document.createElement("span");
        wtargetEl.className = "we-tree-id";
        wtargetEl.textContent = targetLabel;

        wrow.appendChild(wicon);
        wrow.appendChild(wnameEl);
        wrow.appendChild(wtargetEl);
        wrow.addEventListener("click", () => selectWay(wayId));
        roomListEl.appendChild(wrow);
      }
    }
  }
}

function updateRoomListItem(roomId) {
  const row = roomListEl.querySelector(`[data-room-id="${CSS.escape(roomId)}"]`);
  if (!row) return;
  row.className = "we-tree-row we-tree-room" +
    (WE.dirty.has(roomId)          ? " is-dirty"  : "") +
    (roomId === WE.currentRoomId   ? " is-active" : "");
}

function openRoom(roomId) {
  WE.currentRoomId = roomId;
  WE.selectedPropId = null;
  WE.selectedWayId  = null;
  hideExitPicker();
  const room = WE.rooms.get(roomId);
  roomTitle.textContent = room ? (room.label || roomId) : roomId;
  renderRoomList();
  updateDirtyIndicator();
  fitView();
  renderCanvas();
  renderPropertiesPanel();
}

function selectWay(wayId) {
  WE.selectedWayId  = wayId;
  WE.selectedPropId = null;
  renderRoomList();
  renderPropertiesPanel();
}

function showRoomContextMenu(e, roomId) {
  // simple inline context — just a delete button for now
  const menu = document.createElement("div");
  menu.style.cssText = "position:fixed;z-index:100;background:#1b2332;border:1px solid #33415c;border-radius:6px;padding:0.4rem 0;";
  menu.style.left = e.clientX + "px";
  menu.style.top  = e.clientY + "px";
  const items = [
    ["Delete", () => deleteRoom(roomId)],
  ];
  for (const [label, fn] of items) {
    const li = document.createElement("button");
    li.style.cssText = "display:block;width:100%;text-align:left;border:none;border-radius:0;background:none;padding:0.35rem 0.9rem;";
    li.textContent = label;
    li.addEventListener("click", () => { fn(); document.body.removeChild(menu); });
    menu.appendChild(li);
  }
  const removeMenu = () => { if (menu.parentNode) document.body.removeChild(menu); document.removeEventListener("click", removeMenu); };
  document.addEventListener("click", removeMenu, { once: true });
  document.body.appendChild(menu);
}

// ---------------------------------------------------------------------------
// Canvas rendering
// ---------------------------------------------------------------------------

function fitView() {
  const vw = canvasViewport.clientWidth;
  const vh = canvasViewport.clientHeight;
  const draft = currentDraft();
  const stage = (draft || WE.rooms.get(WE.currentRoomId) || {}).stage || {};
  const stW = stage.width  || 400;
  const stH = stage.type === "standard" ? ((stage.bg_height || 200) + (stage.floor_height || 100)) : (stage.height || 300);
  const scaleX = (vw - 48) / stW;
  const scaleY = (vh - 48) / stH;
  WE.zoom = Math.min(scaleX, scaleY, 1.5);
  WE.pan  = { x: Math.round((vw - stW * WE.zoom) / 2), y: Math.round((vh - stH * WE.zoom) / 2) };
  applyTransform();
  updateZoomLabel();
}

function applyTransform() {
  canvasStage.style.transform = `translate(${WE.pan.x}px, ${WE.pan.y}px) scale(${WE.zoom})`;
  canvasStage.style.transformOrigin = "0 0";
  canvasStage.style.left = "0";
  canvasStage.style.top  = "0";
}

function updateZoomLabel() {
  zoomLabel.textContent = Math.round(WE.zoom * 100) + "%";
}

function renderCanvas() {
  canvasStage.innerHTML = "";
  hideExitPicker();

  const draft = currentDraft();
  const room  = draft || WE.rooms.get(WE.currentRoomId);
  if (!room) { canvasStage.style.width = "400px"; canvasStage.style.height = "300px"; return; }

  const stage = room.stage || {};
  const stW   = stage.width  || 400;
  const stH   = stage.type === "standard"
    ? ((stage.bg_height || 200) + (stage.floor_height || 100))
    : (stage.height || 300);

  canvasStage.style.width   = stW + "px";
  canvasStage.style.height  = stH + "px";
  canvasStage.classList.toggle("show-grid", WE.showGrid);

  // background
  if (room.background_url) {
    canvasStage.style.backgroundImage = `url("${room.background_url}")`;
    canvasStage.style.backgroundRepeat = stage.background_mode === "stretch" ? "no-repeat" : "repeat";
    canvasStage.style.backgroundSize  = stage.background_mode === "stretch" ? "100% 100%" : "auto";
  } else {
    canvasStage.style.backgroundImage = "";
  }

  // standard stage divider
  if (stage.type === "standard") {
    const divider = document.createElement("div");
    divider.className = "we-standard-divider";
    divider.style.top = (stage.bg_height || 200) + "px";
    canvasStage.appendChild(divider);
    const floor = document.createElement("div");
    floor.className = "we-floor-overlay";
    floor.style.top    = (stage.bg_height || 200) + "px";
    floor.style.bottom = "0";
    canvasStage.appendChild(floor);
  }

  // props
  const props = room.props || [];
  const sorted = [...props].sort((a, b) => {
    const la = a.position?.layer || 0, lb = b.position?.layer || 0;
    if (la !== lb) return la - lb;
    return (a.position?.z_order || 0) - (b.position?.z_order || 0);
  });

  for (const prop of sorted) {
    renderPropEl(prop, room);
  }
}

function renderPropEl(prop, room) {
  const meta = resolveLibProp(prop.prop_id);
  const pm   = meta?.display?.prop_meta;
  const x = prop.position?.x || 0;
  const y = prop.position?.y || 0;
  const w = pm?.frame?.width  || 32;
  const h = pm?.frame?.height || 32;
  const orientation = prop.position?.orientation || "front";
  const rawScale = prop.position?.scale ?? 1;
  const scale = (Number.isFinite(rawScale) && rawScale > 0) ? rawScale : 1;

  const el = document.createElement("div");
  el.className  = "we-room-prop" + (prop.prop_instance_id === WE.selectedPropId ? " is-selected" : "");
  el.style.left = x + "px";
  el.style.top  = y + "px";
  if (Math.abs(scale - 1) > 0.001) {
    el.style.transformOrigin = "0 0";
    el.style.transform = `scale(${scale})`;
  }
  el.dataset.propInstanceId = prop.prop_instance_id;

  const sprite = document.createElement("div");
  sprite.className = "sprite";
  sprite.style.width  = w + "px";
  sprite.style.height = h + "px";
  if (pm) {
    sprite.style.backgroundImage    = `url("${pm.image_url}")`;
    sprite.style.backgroundPosition = `-${pm.frame.x}px -${pm.frame.y}px`;
    sprite.style.backgroundRepeat   = "no-repeat";
    sprite.style.backgroundSize     = "auto";
    sprite.style.transform          = orientationTransform(orientation);
  }
  el.appendChild(sprite);

  // exit badge
  if (prop.exit_way_id) {
    const way  = WE.ways.get(prop.exit_way_id);
    const badge = document.createElement("div");
    badge.className   = "we-exit-badge";
    badge.textContent = way ? (way.label || prop.exit_way_id) : prop.exit_way_id;
    el.appendChild(badge);
  }

  el.addEventListener("mousedown", e => onPropMouseDown(e, prop.prop_instance_id));
  el.addEventListener("contextmenu", e => { e.preventDefault(); showPropContextMenu(e, prop.prop_instance_id); });

  canvasStage.appendChild(el);
}

function resolveLibProp(propId) {
  return WE.propLibrary.find(p => p.prop_id === propId) || null;
}

function orientationTransform(o) {
  if (o === "left")  return "scaleX(-1)";
  if (o === "right") return "scaleX(1)";
  if (o === "back")  return "rotate(180deg)";
  return "";
}

// ---------------------------------------------------------------------------
// Canvas interaction
// ---------------------------------------------------------------------------

canvasViewport.addEventListener("wheel", e => {
  e.preventDefault();
  const factor = e.deltaY < 0 ? 1.1 : 0.91;
  const rect = canvasViewport.getBoundingClientRect();
  const mx = e.clientX - rect.left, my = e.clientY - rect.top;
  WE.zoom = Math.min(4, Math.max(0.1, WE.zoom * factor));
  WE.pan.x = mx - (mx - WE.pan.x) * factor;
  WE.pan.y = my - (my - WE.pan.y) * factor;
  applyTransform();
  updateZoomLabel();
}, { passive: false });

let _panDragging = false, _panStart = null;

canvasViewport.addEventListener("mousedown", e => {
  if (e.button === 1 || (e.button === 0 && e.target === canvasViewport)) {
    _panDragging = true;
    _panStart = { x: e.clientX - WE.pan.x, y: e.clientY - WE.pan.y };
    e.preventDefault();
  }
  if (e.button === 0 && e.target === canvasStage) {
    onCanvasClick(e);
  }
});

window.addEventListener("mousemove", e => {
  if (_panDragging) {
    WE.pan = { x: e.clientX - _panStart.x, y: e.clientY - _panStart.y };
    applyTransform();
  }
  if (WE.drag) onDragMove(e);
});

window.addEventListener("mouseup", e => {
  if (_panDragging) { _panDragging = false; _panStart = null; }
  if (WE.drag) onDragEnd(e);
});

// Touch pan support for tablets
let _touchPan = null;
canvasViewport.addEventListener("touchstart", e => {
  if (e.touches.length === 1) {
    _touchPan = { x: e.touches[0].clientX - WE.pan.x, y: e.touches[0].clientY - WE.pan.y };
    e.preventDefault();
  }
}, { passive: false });
canvasViewport.addEventListener("touchmove", e => {
  if (_touchPan && e.touches.length === 1) {
    WE.pan = { x: e.touches[0].clientX - _touchPan.x, y: e.touches[0].clientY - _touchPan.y };
    applyTransform();
    e.preventDefault();
  }
}, { passive: false });
canvasViewport.addEventListener("touchend", () => { _touchPan = null; });

function stageCoords(clientX, clientY) {
  const rect = canvasViewport.getBoundingClientRect();
  return {
    x: (clientX - rect.left - WE.pan.x) / WE.zoom,
    y: (clientY - rect.top  - WE.pan.y) / WE.zoom,
  };
}

function snapToGrid(v) {
  return WE.showGrid ? Math.round(v / 8) * 8 : Math.round(v);
}

function onCanvasClick(e) {
  if (WE.activeTool === "place" && WE.libraryPropId) {
    const pos = stageCoords(e.clientX, e.clientY);
    const draft = currentDraft();
    if (!draft) return;
    snapshotHistory(WE.currentRoomId);
    const instanceId = `${WE.currentRoomId}-${WE.libraryPropId}-${Date.now().toString(36)}`;
    const maxZ = Math.max(10, ...(draft.props || []).map(p => p.position?.z_order || 0)) + 1;
    draft.props = draft.props || [];
    draft.props.push({
      prop_instance_id: instanceId,
      prop_id: WE.libraryPropId,
      exit_way_id: null,
      position: { x: snapToGrid(pos.x), y: snapToGrid(pos.y), orientation: "front", layer: 0, z_order: maxZ, scale: 1 },
    });
    WE.selectedPropId = instanceId;
    setTool("select");
    markDirty(WE.currentRoomId);
    renderCanvas();
    renderPropertiesPanel();
    return;
  }
  // click on empty canvas: deselect
  if (WE.activeTool === "select") {
    WE.selectedPropId = null;
    WE.selectedWayId  = null;
    hideExitPicker();
    renderCanvas();
    renderPropertiesPanel();
  }
}

function onPropMouseDown(e, propInstanceId) {
  e.stopPropagation();
  if (WE.activeTool === "exit") {
    showExitPickerFor(e, propInstanceId);
    return;
  }
  WE.selectedPropId = propInstanceId;
  WE.selectedWayId  = null;
  hideExitPicker();
  renderCanvas();
  renderPropertiesPanel();

  if (WE.activeTool === "select") {
    const draft = currentDraft();
    if (!draft) return;
    const prop = draft.props?.find(p => p.prop_instance_id === propInstanceId);
    if (!prop) return;
    WE.drag = {
      propInstanceId,
      startMouseX: e.clientX,
      startMouseY: e.clientY,
      origX: prop.position?.x || 0,
      origY: prop.position?.y || 0,
    };
  }
}

function onDragMove(e) {
  if (!WE.drag) return;
  const draft = currentDraft();
  if (!draft) return;
  const prop = draft.props?.find(p => p.prop_instance_id === WE.drag.propInstanceId);
  if (!prop) return;
  const dx = (e.clientX - WE.drag.startMouseX) / WE.zoom;
  const dy = (e.clientY - WE.drag.startMouseY) / WE.zoom;
  const altSnap = e.altKey;
  prop.position.x = altSnap ? Math.round(WE.drag.origX + dx) : snapToGrid(WE.drag.origX + dx);
  prop.position.y = altSnap ? Math.round(WE.drag.origY + dy) : snapToGrid(WE.drag.origY + dy);
  // update DOM directly for performance
  const el = canvasStage.querySelector(`[data-prop-instance-id="${CSS.escape(WE.drag.propInstanceId)}"]`);
  if (el) { el.style.left = prop.position.x + "px"; el.style.top = prop.position.y + "px"; }
}

function onDragEnd(e) {
  if (!WE.drag) return;
  const draft = currentDraft();
  if (draft) {
    const prop = draft.props?.find(p => p.prop_instance_id === WE.drag.propInstanceId);
    if (prop) {
      const origX = WE.drag.origX, origY = WE.drag.origY;
      if (prop.position.x !== origX || prop.position.y !== origY) {
        snapshotHistory(WE.currentRoomId);
        markDirty(WE.currentRoomId);
      }
    }
  }
  WE.drag = null;
  renderCanvas();
  renderPropertiesPanel();
}

// ---------------------------------------------------------------------------
// Exit picker
// ---------------------------------------------------------------------------

function showExitPickerFor(e, propInstanceId) {
  WE.exitPickerPropId = propInstanceId;
  WE.selectedPropId   = propInstanceId;

  const draft = currentDraft();
  const room  = draft || WE.rooms.get(WE.currentRoomId);
  const wayIds = room?.ways || [];

  const pos = stageCoords(e.clientX, e.clientY);
  exitPicker.style.left = (pos.x * WE.zoom + WE.pan.x) + "px";
  exitPicker.style.top  = (pos.y * WE.zoom + WE.pan.y) + "px";
  exitPicker.innerHTML  = "";
  exitPicker.classList.remove("hidden");

  const noneOpt = document.createElement("button");
  noneOpt.style.display = "block"; noneOpt.style.width = "100%";
  noneOpt.textContent = "— none —";
  noneOpt.addEventListener("click", () => assignExit(propInstanceId, null));
  exitPicker.appendChild(noneOpt);

  for (const wayId of wayIds) {
    const way = WE.ways.get(wayId);
    const btn = document.createElement("button");
    btn.style.display = "block"; btn.style.width = "100%";
    btn.textContent = way ? (way.label || wayId) : wayId;
    btn.addEventListener("click", () => assignExit(propInstanceId, wayId));
    exitPicker.appendChild(btn);
  }
}

function assignExit(propInstanceId, wayId) {
  const draft = currentDraft();
  if (!draft) { hideExitPicker(); return; }
  snapshotHistory(WE.currentRoomId);
  const prop = draft.props?.find(p => p.prop_instance_id === propInstanceId);
  if (prop) prop.exit_way_id = wayId;
  markDirty(WE.currentRoomId);
  hideExitPicker();
  renderCanvas();
  renderPropertiesPanel();
}

function hideExitPicker() {
  exitPicker.classList.add("hidden");
  exitPicker.innerHTML = "";
  WE.exitPickerPropId  = null;
}

canvasViewport.addEventListener("click", e => {
  if (e.target === canvasViewport && !exitPicker.classList.contains("hidden")) {
    hideExitPicker();
  }
});

// ---------------------------------------------------------------------------
// Prop context menu
// ---------------------------------------------------------------------------

function showPropContextMenu(e, propInstanceId) {
  const draft = currentDraft();
  if (!draft) return;
  const prop = draft.props?.find(p => p.prop_instance_id === propInstanceId);
  if (!prop) return;
  WE.selectedPropId = propInstanceId;
  renderCanvas();
  renderPropertiesPanel();

  const menu = document.createElement("div");
  menu.style.cssText = "position:fixed;z-index:100;background:#1b2332;border:1px solid #33415c;border-radius:6px;padding:0.4rem 0;";
  menu.style.left = e.clientX + "px";
  menu.style.top  = e.clientY + "px";

  const actions = [
    ["Duplicate Prop",  () => duplicateProp(propInstanceId)],
    ["Bring Forward",   () => changePropZ(propInstanceId,  1)],
    ["Send Backward",   () => changePropZ(propInstanceId, -1)],
    ["Remove Prop",     () => removeProp(propInstanceId)],
  ];
  for (const [lbl, fn] of actions) {
    const btn = document.createElement("button");
    btn.style.cssText = "display:block;width:100%;text-align:left;border:none;border-radius:0;background:none;padding:0.35rem 0.9rem;";
    btn.textContent = lbl;
    btn.addEventListener("click", () => { fn(); document.body.removeChild(menu); });
    menu.appendChild(btn);
  }
  const removeMenu = () => { if (menu.parentNode) document.body.removeChild(menu); document.removeEventListener("click", removeMenu); };
  document.addEventListener("click", removeMenu, { once: true });
  document.body.appendChild(menu);
}

function changePropZ(propInstanceId, delta) {
  const draft = currentDraft();
  if (!draft) return;
  snapshotHistory(WE.currentRoomId);
  const prop = draft.props?.find(p => p.prop_instance_id === propInstanceId);
  if (prop) prop.position.z_order = (prop.position.z_order || 0) + delta;
  markDirty(WE.currentRoomId);
  renderCanvas();
  renderPropertiesPanel();
}

function removeProp(propInstanceId) {
  const draft = currentDraft();
  if (!draft) return;
  snapshotHistory(WE.currentRoomId);
  draft.props = (draft.props || []).filter(p => p.prop_instance_id !== propInstanceId);
  if (WE.selectedPropId === propInstanceId) WE.selectedPropId = null;
  markDirty(WE.currentRoomId);
  renderCanvas();
  renderPropertiesPanel();
}

function duplicateProp(propInstanceId) {
  const draft = currentDraft();
  if (!draft) return;
  const orig = draft.props?.find(p => p.prop_instance_id === propInstanceId);
  if (!orig) return;
  snapshotHistory(WE.currentRoomId);
  const newId = `${WE.currentRoomId}-dup-${Date.now().toString(36)}`;
  const newProp = deepClone(orig);
  newProp.prop_instance_id = newId;
  newProp.position = { ...deepClone(orig.position), x: (orig.position?.x || 0) + 16, y: (orig.position?.y || 0) + 16 };
  draft.props.push(newProp);
  WE.selectedPropId = newId;
  markDirty(WE.currentRoomId);
  renderCanvas();
  renderPropertiesPanel();
}

// ---------------------------------------------------------------------------
// Properties Panel
// ---------------------------------------------------------------------------

function renderPropertiesPanel() {
  propertiesPanel.innerHTML = "";

  if (WE.selectedWayId) {
    renderWayProperties();
    return;
  }
  if (WE.selectedPropId && WE.currentRoomId) {
    renderPropProperties();
    return;
  }
  if (WE.currentRoomId) {
    renderRoomProperties();
    return;
  }
  propertiesPanel.innerHTML = "<p class='we-help'>Select a room from the list.</p>";
}

function renderRoomProperties() {
  const draft = currentDraft();
  const room  = draft || WE.rooms.get(WE.currentRoomId);
  if (!room) return;
  const stage = room.stage || {};
  const isStandard = stage.type === "standard";

  propertiesPanel.innerHTML = `
    <div class="we-form-grid">
      <label><span>Room ID</span><input type="text" value="${esc(room.room_id)}" disabled></label>
      <label><span>Label</span><input id="rp-label" type="text" value="${esc(room.label || '')}"></label>
      <label><span>Description</span><textarea id="rp-desc" rows="3">${esc(room.description || '')}</textarea></label>
      <label><span>Owner</span><input id="rp-owner" type="text" value="${esc(room.owner_id || '')}"></label>
      <label><span>Background Image</span>
        <select id="rp-bg">${imageOptions(room.background)}</select>
      </label>
    </div>
    <details open style="margin-top:1rem">
      <summary style="cursor:pointer;font-weight:700;margin-bottom:0.5rem">Stage Settings</summary>
      <div class="we-form-grid" style="margin-top:0.5rem">
        <label><span>Stage Type</span>
          <select id="rp-stagetype">
            <option value="basic"${!isStandard?" selected":""}>Basic</option>
            <option value="standard"${isStandard?" selected":""}>Standard</option>
          </select>
        </label>
        <label><span>Width (px)</span><input id="rp-width" type="number" value="${stage.width||400}"></label>
        ${!isStandard
          ? `<label><span>Height (px)</span><input id="rp-height" type="number" value="${stage.height||300}"></label>`
          : `<label><span>Background Height (px)</span><input id="rp-bgh" type="number" value="${stage.bg_height||200}"></label>
             <label><span>Floor Height (px)</span><input id="rp-fh" type="number" value="${stage.floor_height||100}"></label>
             <label><span>Floor Image</span><select id="rp-floorimg">${imageOptions(stage.floor_image)}</select></label>`
        }
        <label><span>Background Mode</span>
          <select id="rp-bgmode">
            <option value="tile"${stage.background_mode!=="stretch"?" selected":""}>Tile</option>
            <option value="stretch"${stage.background_mode==="stretch"?" selected":""}>Stretch</option>
          </select>
        </label>
        <label><span>Theme</span><input id="rp-theme" type="text" value="${esc(stage.theme||'')}"></label>
      </div>
    </details>`;

  // Snapshot history once before the first change in this panel session.
  let _snapped = false;
  function maybeSnap() {
    if (!_snapped) { snapshotHistory(WE.currentRoomId); _snapped = true; }
  }

  // Read all current field values into the draft and re-render canvas.
  function liveApply() {
    const d = currentDraft();
    if (!d) return;
    d.label       = $("rp-label").value.trim();
    d.description = $("rp-desc").value.trim();
    d.owner_id    = $("rp-owner").value.trim();
    const bgPath  = $("rp-bg").value;
    d.background     = bgPath;
    d.background_url = resolveAssetUrl(bgPath);
    const stType = $("rp-stagetype").value;
    const st = d.stage = d.stage || {};
    st.type  = stType;
    st.width = parseInt($("rp-width").value) || 400;
    if (stType === "basic") {
      st.height = parseInt($("rp-height")?.value) || 300;
      delete st.bg_height; delete st.floor_height; delete st.floor_image;
    } else {
      st.bg_height    = parseInt($("rp-bgh")?.value) || 200;
      st.floor_height = parseInt($("rp-fh")?.value)  || 100;
      st.floor_image  = $("rp-floorimg")?.value || "";
      delete st.height;
    }
    st.background_mode = $("rp-bgmode").value;
    st.theme           = $("rp-theme").value.trim();
    markDirty(WE.currentRoomId);
    renderCanvas();
    renderRoomList();
  }

  // Text / textarea: live preview on every keystroke.
  for (const id of ["rp-label", "rp-owner", "rp-theme"]) {
    $(id)?.addEventListener("input", () => { maybeSnap(); liveApply(); });
  }
  $("rp-desc")?.addEventListener("input", () => { maybeSnap(); liveApply(); });

  // Number inputs: live preview while spinning/typing.
  for (const id of ["rp-width", "rp-height", "rp-bgh", "rp-fh"]) {
    $(id)?.addEventListener("input", () => { maybeSnap(); liveApply(); });
  }

  // Selects: update on pick.
  for (const id of ["rp-bg", "rp-bgmode", "rp-floorimg"]) {
    $(id)?.addEventListener("change", () => { maybeSnap(); liveApply(); });
  }

  // Stage type: re-render the whole panel (fields change) then apply.
  $("rp-stagetype")?.addEventListener("change", () => {
    maybeSnap();
    liveApply();
    renderPropertiesPanel();  // rebuilds with correct height fields
  });
}

function imageOptions(current) {
  const cur = current || "";
  // Also match by basename in case YAML stores a bare filename like "bg.png"
  // while img.path is "images/bg.png".
  const curBasename = cur.includes("/") ? cur.split("/").pop() : cur;
  let html = `<option value=""${!cur?" selected":""}>— none —</option>`;
  for (const img of WE.images) {
    const imgBasename = img.path.includes("/") ? img.path.split("/").pop() : img.path;
    const sel = img.path === cur || img.url === cur ||
                (cur && imgBasename === curBasename) ? " selected" : "";
    html += `<option value="${esc(img.path)}"${sel}>${esc(img.label || img.path)}</option>`;
  }
  return html;
}

function resolveAssetUrl(path) {
  if (!path) return "";
  if (path.startsWith("/") || path.startsWith("http")) return path;
  return `/world/${path}`;
}

function renderPropProperties() {
  const draft = currentDraft();
  const room  = draft || WE.rooms.get(WE.currentRoomId);
  if (!room) return;
  const prop = (room.props || []).find(p => p.prop_instance_id === WE.selectedPropId);
  if (!prop) { renderRoomProperties(); return; }
  const meta = resolveLibProp(prop.prop_id);
  const pos  = prop.position || {};
  const wayIds = room.ways || [];

  let exitHtml = `<option value=""${!prop.exit_way_id?" selected":""}>— none —</option>`;
  for (const wid of wayIds) {
    const w   = WE.ways.get(wid);
    const lbl = w ? (w.label || wid) : wid;
    exitHtml += `<option value="${esc(wid)}"${prop.exit_way_id===wid?" selected":""}>${esc(lbl)}</option>`;
  }

  const thumbHtml = meta?.display?.prop_meta
    ? `<canvas id="pp-thumb" class="we-selected-prop-thumb" width="80" height="80"></canvas>`
    : "";

  propertiesPanel.innerHTML = `
    ${thumbHtml}
    <div class="we-form-grid">
      <label><span>Prop ID</span><input type="text" value="${esc(prop.prop_id)}" disabled></label>
      <label><span>X (px)</span><input id="pp-x" type="number" value="${pos.x||0}"></label>
      <label><span>Y (px)</span><input id="pp-y" type="number" value="${pos.y||0}"></label>
      <label><span>Scale</span><input id="pp-scale" type="number" min="0.1" max="10" step="0.05" value="${(pos.scale ?? 1).toFixed(2)}"></label>
      <label><span>Orientation</span>
        <select id="pp-orient">
          ${["front","back","left","right"].map(o=>`<option${pos.orientation===o?" selected":""}>${o}</option>`).join("")}
        </select>
      </label>
      <label><span>Layer</span><input id="pp-layer" type="number" value="${pos.layer||0}"></label>
      <label><span>Z-order</span><input id="pp-z" type="number" value="${pos.z_order||0}"></label>
      <label><span>Exit</span>
        <select id="pp-exit">${exitHtml}</select>
      </label>
    </div>
    <div style="margin-top:1rem;display:flex;gap:0.5rem;flex-wrap:wrap">
      <button id="pp-dup">Duplicate</button>
      <button id="pp-remove" style="border-color:#f66">Remove Prop</button>
    </div>`;

  // Draw prop thumbnail.
  const pm = meta?.display?.prop_meta;
  if (pm) {
    const thumbCanvas = $("pp-thumb");
    if (thumbCanvas) {
      _cachedLoadImage(pm.image_url).then(img => {
        _drawSpriteThumb(thumbCanvas, img, pm.frame.x, pm.frame.y, pm.frame.width, pm.frame.height);
      }).catch(() => {});
    }
  }

  // Snapshot history once before the first change in this panel session.
  let _snapped = false;
  function maybeSnap() {
    if (!_snapped) { snapshotHistory(WE.currentRoomId); _snapped = true; }
  }

  // Read all fields into prop.position and re-render the canvas immediately.
  // Does NOT call renderPropertiesPanel() to avoid resetting inputs mid-edit.
  function liveApply() {
    prop.position.x           = parseInt($("pp-x").value) || 0;
    prop.position.y           = parseInt($("pp-y").value) || 0;
    const rawScale            = parseFloat($("pp-scale").value);
    prop.position.scale       = Number.isFinite(rawScale) && rawScale > 0
      ? Math.max(0.1, Math.min(10.0, rawScale)) : 1.0;
    prop.position.orientation = $("pp-orient").value;
    prop.position.layer       = parseInt($("pp-layer").value) || 0;
    prop.position.z_order     = parseInt($("pp-z").value) || 0;
    prop.exit_way_id          = $("pp-exit").value || null;
    markDirty(WE.currentRoomId);
    renderCanvas();
  }

  // Number inputs: live preview on every keystroke/spin.
  for (const id of ["pp-x", "pp-y", "pp-scale", "pp-layer", "pp-z"]) {
    $(id)?.addEventListener("input", () => { maybeSnap(); liveApply(); });
  }

  // Selects: update immediately on pick.
  for (const id of ["pp-orient", "pp-exit"]) {
    $(id)?.addEventListener("change", () => { maybeSnap(); liveApply(); });
  }

  $("pp-remove").addEventListener("click", () => removeProp(WE.selectedPropId));
  $("pp-dup")?.addEventListener("click", () => duplicateProp(WE.selectedPropId));
}

function renderWayProperties() {
  const way = WE.ways.get(WE.selectedWayId);
  if (!way) { propertiesPanel.innerHTML = ""; return; }

  let roomOpts = `<option value="">— none —</option>`;
  for (const [rid, r] of WE.rooms) {
    roomOpts += `<option value="${esc(rid)}"${way.to_room_id===rid?" selected":""}>${esc(r.label||rid)}</option>`;
  }

  propertiesPanel.innerHTML = `
    <div class="we-form-grid">
      <label><span>Way ID</span><input type="text" value="${esc(way.way_id)}" disabled></label>
      <label><span>Label</span><input id="wp-label" type="text" value="${esc(way.label||'')}"></label>
      <label><span>Target Room</span><select id="wp-to">${roomOpts}</select></label>
      <label><span>Referenced By</span>
        <input type="text" value="${esc((way.from_room_ids||[]).join(', '))}" disabled>
      </label>
    </div>
    <div style="margin-top:1rem;display:flex;gap:0.5rem;flex-wrap:wrap">
      <button id="wp-apply">Apply</button>
      <button id="wp-nav">→ Go to target room</button>
      <button id="wp-delete" style="border-color:#f66">Delete Way</button>
    </div>`;

  $("wp-apply").addEventListener("click",  () => saveWayProperties());
  $("wp-nav").addEventListener("click",    () => { if (way.to_room_id) openRoom(way.to_room_id); });
  $("wp-delete").addEventListener("click", () => deleteWay(WE.selectedWayId));
}

async function saveWayProperties() {
  const wayId = WE.selectedWayId;
  if (!wayId) return;
  const label     = $("wp-label").value.trim();
  const toRoomId  = $("wp-to").value;
  const fromRoom  = WE.ways.get(wayId)?.from_room_ids?.[0] || "";
  setStatus("Saving way…");
  try {
    const data = await apiPut(`/api/world-editor/ways/${wayId}`, { label, to_room_id: toRoomId, from_room_id: fromRoom });
    WE.ways.set(wayId, data.way);
    setStatus("Way saved");
    renderRoomList();
    renderPropertiesPanel();
  } catch (err) {
    setStatus(`Error: ${err.message}`, true);
  }
}

// ---------------------------------------------------------------------------
// Save / Reset
// ---------------------------------------------------------------------------

async function saveRoom(roomId) {
  const draft = WE.drafts.get(roomId) || WE.rooms.get(roomId);
  if (!draft) return;
  setStatus("Saving room…");
  try {
    const data = await apiPut(`/api/world-editor/rooms/${roomId}`, draft);
    WE.rooms.set(roomId, data.room);
    WE.drafts.delete(roomId);
    clearDirty(roomId);
    if (roomId === WE.currentRoomId) renderCanvas();
    renderRoomList();
    setStatus(`Room '${roomId}' saved`);
  } catch (err) {
    setStatus(`Error: ${err.message}`, true);
  }
}

async function saveAll() {
  for (const roomId of WE.dirty) {
    await saveRoom(roomId);
  }
}

function resetRoom(roomId) {
  WE.drafts.delete(roomId);
  WE.history.delete(roomId);
  clearDirty(roomId);
  if (WE.selectedPropId) { WE.selectedPropId = null; }
  renderCanvas();
  renderPropertiesPanel();
  setStatus(`Room '${roomId}' reset`);
}

// ---------------------------------------------------------------------------
// Delete room/way
// ---------------------------------------------------------------------------

async function deleteRoom(roomId) {
  if (!confirm(`Delete room '${roomId}'? This cannot be undone.`)) return;
  setStatus("Deleting room…");
  try {
    await apiDelete(`/api/world-editor/rooms/${roomId}`);
    WE.rooms.delete(roomId);
    WE.drafts.delete(roomId);
    WE.dirty.delete(roomId);
    if (WE.currentRoomId === roomId) {
      WE.currentRoomId = WE.rooms.size > 0 ? WE.rooms.keys().next().value : null;
    }
    renderRoomList();
    renderCanvas();
    renderPropertiesPanel();
    renderMapSvg();
    setStatus(`Room '${roomId}' deleted`);
  } catch (err) {
    setStatus(`Error: ${err.message}`, true);
  }
}

async function deleteWay(wayId) {
  if (!confirm(`Delete way '${wayId}'? This cannot be undone.`)) return;
  setStatus("Deleting way…");
  try {
    await apiDelete(`/api/world-editor/ways/${wayId}`);
    WE.ways.delete(wayId);
    WE.selectedWayId = null;
    // remove from room drafts and originals
    for (const room of WE.rooms.values()) {
      room.ways = (room.ways || []).filter(w => w !== wayId);
    }
    for (const draft of WE.drafts.values()) {
      draft.ways = (draft.ways || []).filter(w => w !== wayId);
    }
    renderRoomList();
    renderPropertiesPanel();
    renderMapSvg();
    setStatus(`Way '${wayId}' deleted`);
  } catch (err) {
    setStatus(`Error: ${err.message}`, true);
  }
}

// ---------------------------------------------------------------------------
// Prop Library Panel
// ---------------------------------------------------------------------------

function renderPropLibraryTabs() {
  libraryTabs.innerHTML = "";
  for (const set of WE.propLibrarySets) {
    const lbl = set.filename + (set.scope === "server" ? " [S]" : " [W]");
    const btn = document.createElement("button");
    btn.textContent = lbl;
    btn.className = set.filename === WE.libActiveSet ? "is-active" : "";
    btn.addEventListener("click", () => { WE.libActiveSet = set.filename; renderPropLibraryTabs(); renderPropLibraryGrid(); });
    libraryTabs.appendChild(btn);
  }
}

function renderPropLibraryTagFilter() {
  if (!libraryTagFilter) return;
  libraryTagFilter.innerHTML = '<option value="">All tags</option>';
  for (const tag of WE.libAllTags) {
    const opt = document.createElement("option");
    opt.value = tag;
    opt.textContent = tag;
    if (tag === WE.libTagFilter) opt.selected = true;
    libraryTagFilter.appendChild(opt);
  }
  libraryTagFilter.style.display = WE.libAllTags.length > 0 ? "" : "none";
}

function renderPropLibraryGrid() {
  libraryGrid.innerHTML = "";
  const search = WE.libSearch.toLowerCase();
  const tagFilter = WE.libTagFilter;

  // When searching/filtering use all sets; otherwise only the active set
  let props;
  if (search || tagFilter) {
    props = WE.propLibrary;
  } else {
    const activeSet = WE.propLibrarySets.find(s => s.filename === WE.libActiveSet);
    props = activeSet ? activeSet.props : [];
  }

  for (const p of props) {
    const labelText = (p.label || p.prop_id).toLowerCase();
    const propIdLower = p.prop_id.toLowerCase();
    if (search && !propIdLower.includes(search) && !labelText.includes(search)) continue;
    if (tagFilter && !(p.tags || []).includes(tagFilter)) continue;

    const pm = p.display?.prop_meta;
    const card = document.createElement("div");
    card.className = "we-prop-card" + (p.prop_id === WE.libraryPropId ? " is-selected" : "");
    card.title = p.prop_id;

    if (pm) {
      const thumbWrap = document.createElement("div");
      thumbWrap.className = "we-prop-thumb";
      thumbWrap.style.cssText = "width:72px;height:72px;margin:0 auto 0.35rem;position:relative;overflow:hidden;";
      const canvas = document.createElement("canvas");
      canvas.width = 72; canvas.height = 72;
      canvas.style.imageRendering = "pixelated";
      thumbWrap.appendChild(canvas);
      card.appendChild(thumbWrap);
      _cachedLoadImage(pm.image_url).then(img => {
        _drawSpriteThumb(canvas, img, pm.frame.x, pm.frame.y, pm.frame.width, pm.frame.height);
      }).catch(() => {});
    }

    const lbl = document.createElement("div");
    lbl.style.fontSize = "0.7rem";
    lbl.textContent = p.prop_id.split("/").pop();
    card.appendChild(lbl);

    card.addEventListener("click", () => {
      WE.libraryPropId = p.prop_id;
      setTool("place");
      renderPropLibraryGrid();
    });
    libraryGrid.appendChild(card);
  }
}

// ---------------------------------------------------------------------------
// World Map
// ---------------------------------------------------------------------------

function renderMapSvg() {
  mapSvg.innerHTML = `
    <defs>
      <marker id="arrowhead" markerWidth="8" markerHeight="6" refX="7" refY="3" orient="auto">
        <polygon points="0 0, 8 3, 0 6" fill="#7f92b8"/>
      </marker>
    </defs>`;

  // Auto-layout rooms in a grid if no stored layout
  const roomIds = [...WE.rooms.keys()];
  const cols = Math.max(1, Math.ceil(Math.sqrt(roomIds.length)));
  const cellW = 180, cellH = 100;

  for (let i = 0; i < roomIds.length; i++) {
    if (!WE.mapLayout.has(roomIds[i])) {
      WE.mapLayout.set(roomIds[i], {
        x: 60 + (i % cols) * cellW,
        y: 50 + Math.floor(i / cols) * cellH,
      });
    }
  }

  // draw way edges
  for (const [wayId, way] of WE.ways) {
    const fromRoomId = way.from_room_ids?.[0];
    const toRoomId   = way.to_room_id;
    if (!fromRoomId || !toRoomId) continue;
    const from = WE.mapLayout.get(fromRoomId);
    const to   = WE.mapLayout.get(toRoomId);
    if (!from || !to) continue;
    const midX = (from.x + 70 + to.x + 70) / 2;
    const midY = (from.y + 20 + to.y + 20) / 2;
    const line = document.createElementNS("http://www.w3.org/2000/svg", "line");
    line.setAttribute("class", "we-map-edge");
    line.setAttribute("x1", from.x + 70); line.setAttribute("y1", from.y + 20);
    line.setAttribute("x2", to.x + 70);   line.setAttribute("y2", to.y + 20);
    mapSvg.appendChild(line);
    const lblEl = document.createElementNS("http://www.w3.org/2000/svg", "text");
    lblEl.setAttribute("class", "we-map-label");
    lblEl.setAttribute("x", midX); lblEl.setAttribute("y", midY - 6);
    lblEl.setAttribute("font-size", "10"); lblEl.setAttribute("text-anchor", "middle");
    lblEl.textContent = way.label || wayId;
    mapSvg.appendChild(lblEl);
  }

  // draw room nodes
  for (const [roomId, room] of WE.rooms) {
    const pos   = WE.mapLayout.get(roomId) || { x: 60, y: 50 };
    const label = room.label || roomId;
    const isActive = roomId === WE.currentRoomId;

    const g = document.createElementNS("http://www.w3.org/2000/svg", "g");
    g.style.cursor = "pointer";
    g.addEventListener("click", () => { openRoom(roomId); setActiveTab("room"); });
    g.addEventListener("mousedown", e => startMapDrag(e, roomId));

    const rect = document.createElementNS("http://www.w3.org/2000/svg", "rect");
    rect.setAttribute("class", "we-map-node" + (isActive ? " active" : ""));
    rect.setAttribute("x", pos.x); rect.setAttribute("y", pos.y);
    rect.setAttribute("width", 140); rect.setAttribute("height", 40);
    rect.setAttribute("rx", 8);
    g.appendChild(rect);

    const txt = document.createElementNS("http://www.w3.org/2000/svg", "text");
    txt.setAttribute("class", "we-map-room-label");
    txt.setAttribute("x", pos.x + 70); txt.setAttribute("y", pos.y + 26);
    txt.setAttribute("text-anchor", "middle"); txt.setAttribute("font-size", "12");
    txt.textContent = label.length > 16 ? label.slice(0, 14) + "…" : label;
    g.appendChild(txt);

    mapSvg.appendChild(g);
  }
}

let _mapDrag = null;

function startMapDrag(e, roomId) {
  e.preventDefault();
  _mapDrag = { roomId, startX: e.clientX, startY: e.clientY, orig: { ...WE.mapLayout.get(roomId) } };
  const onMove = ev => {
    if (!_mapDrag) return;
    const pos = WE.mapLayout.get(_mapDrag.roomId);
    pos.x = _mapDrag.orig.x + ev.clientX - _mapDrag.startX;
    pos.y = _mapDrag.orig.y + ev.clientY - _mapDrag.startY;
    renderMapSvg();
  };
  const onUp = () => {
    _mapDrag = null;
    window.removeEventListener("mousemove", onMove);
    window.removeEventListener("mouseup",   onUp);
  };
  window.addEventListener("mousemove", onMove);
  window.addEventListener("mouseup",   onUp);
}

// ---------------------------------------------------------------------------
// Modal dialogs
// ---------------------------------------------------------------------------

function showModal(title, fieldsHtml, onSubmit, submitLabel = "Create") {
  modalTitle.textContent = title;
  modalForm.innerHTML    = fieldsHtml + `<div class="we-modal-footer"><button type="submit">${submitLabel}</button><button type="button" id="btnCancelModal">Cancel</button></div>`;
  modalBackdrop.classList.remove("hidden");
  modalForm.onsubmit = e => { e.preventDefault(); onSubmit(); };
  $("btnCancelModal").addEventListener("click", closeModal);
}

function closeModal() {
  modalBackdrop.classList.add("hidden");
}

btnCloseModal.addEventListener("click", closeModal);
modalBackdrop.addEventListener("click", e => { if (e.target === modalBackdrop) closeModal(); });

function openNewRoomDialog() {
  const roomOpts = [...WE.rooms.entries()].map(([id, r]) => `<option value="${esc(id)}">${esc(r.label||id)}</option>`).join("");
  showModal("New Room", `
    <div class="we-form-grid">
      <label><span>Room ID (snake_case)</span><input id="nr-id" type="text" required pattern="[a-z0-9_]+" placeholder="my_new_room"></label>
      <label><span>Label</span><input id="nr-label" type="text" placeholder="My New Room"></label>
      <label><span>Stage Type</span>
        <select id="nr-type">
          <option value="basic">Basic</option>
          <option value="standard">Standard</option>
        </select>
      </label>
      <label><span>Copy From (optional)</span>
        <select id="nr-copy"><option value="">— none —</option>${roomOpts}</select>
      </label>
    </div>`, createRoom);
}

async function createRoom() {
  const roomId   = $("nr-id")?.value.trim();
  const label    = $("nr-label")?.value.trim() || roomId;
  const stType   = $("nr-type")?.value || "basic";
  const copyFrom = $("nr-copy")?.value || undefined;
  if (!roomId) return;
  closeModal();
  setStatus("Creating room…");
  try {
    const body = { room_id: roomId, label, stage: { type: stType, width: 400 }, ...(copyFrom ? { copy_from: copyFrom } : {}) };
    if (stType === "basic") body.stage.height = 300;
    else { body.stage.bg_height = 200; body.stage.floor_height = 100; }
    const data = await apiPost("/api/world-editor/rooms", body);
    WE.rooms.set(roomId, data.room);
    renderRoomList();
    renderMapSvg();
    openRoom(roomId);
    setStatus(`Room '${roomId}' created`);
  } catch (err) {
    setStatus(`Error: ${err.message}`, true);
  }
}

function openNewWayDialog(preFromId) {
  const roomOpts = (cur) => [...WE.rooms.entries()].map(([id, r]) => `<option value="${esc(id)}"${id===cur?" selected":""}>${esc(r.label||id)}</option>`).join("");
  const from = preFromId || WE.currentRoomId || "";
  showModal("New Way", `
    <div class="we-form-grid">
      <label><span>Way ID (snake_case)</span><input id="nw-id" type="text" required pattern="[a-z0-9_]+" placeholder="to_some_room"></label>
      <label><span>Label</span><input id="nw-label" type="text" placeholder="through the gate 🌿"></label>
      <label><span>From Room</span><select id="nw-from">${roomOpts(from)}</select></label>
      <label><span>To Room</span><select id="nw-to">${roomOpts("")}</select></label>
      <label><span>Also create reverse way</span><input id="nw-rev" type="checkbox" checked style="width:auto"></label>
    </div>`, createWay);
}

async function createWay() {
  const wayId   = $("nw-id")?.value.trim();
  const label   = $("nw-label")?.value.trim();
  const fromId  = $("nw-from")?.value;
  const toId    = $("nw-to")?.value;
  const rev     = $("nw-rev")?.checked ?? true;
  if (!wayId || !fromId || !toId) return;
  closeModal();
  setStatus("Creating way…");
  try {
    const data = await apiPost("/api/world-editor/ways", { way_id: wayId, label, from_room_id: fromId, to_room_id: toId, create_reverse: rev });
    for (const w of (data.ways || [])) WE.ways.set(w.way_id, w);
    // refresh room data to pick up updated ways lists
    await loadState();
    setStatus(`Way '${wayId}' created`);
  } catch (err) {
    setStatus(`Error: ${err.message}`, true);
  }
}

// ---------------------------------------------------------------------------
// Tool selection
// ---------------------------------------------------------------------------

function setTool(tool) {
  WE.activeTool = tool;
  toolSelect.classList.toggle("is-active", tool === "select");
  toolPlace.classList.toggle("is-active",  tool === "place");
  toolExit.classList.toggle("is-active",   tool === "exit");
  canvasViewport.style.cursor = tool === "place" ? "crosshair" : tool === "exit" ? "cell" : "default";
}

toolSelect.addEventListener("click", () => setTool("select"));
toolPlace.addEventListener("click",  () => setTool("place"));
toolExit.addEventListener("click",   () => setTool("exit"));

// ---------------------------------------------------------------------------
// Tab switching
// ---------------------------------------------------------------------------

function setActiveTab(tab) {
  const isRoom = tab === "room";
  tabRoom.classList.toggle("is-active",  isRoom);
  tabMap.classList.toggle("is-active",  !isRoom);
  roomPane.classList.toggle("is-active", isRoom);
  mapPane.classList.toggle("is-active", !isRoom);
  if (!isRoom) renderMapSvg();
}

tabRoom.addEventListener("click", () => setActiveTab("room"));
tabMap.addEventListener("click",  () => setActiveTab("map"));

// ---------------------------------------------------------------------------
// Toolbar wiring
// ---------------------------------------------------------------------------

// Zoom controls
btnZoomIn.addEventListener("click", () => {
  WE.zoom = Math.min(4, WE.zoom * 1.2);
  applyTransform();
  updateZoomLabel();
});
btnZoomOut.addEventListener("click", () => {
  WE.zoom = Math.max(0.1, WE.zoom / 1.2);
  applyTransform();
  updateZoomLabel();
});

btnUndo.addEventListener("click",       undo);
btnRedo.addEventListener("click",       redo);
btnSaveRoom.addEventListener("click",   () => WE.currentRoomId && saveRoom(WE.currentRoomId));
btnSaveAll.addEventListener("click",    saveAll);
btnResetRoom.addEventListener("click",  () => WE.currentRoomId && resetRoom(WE.currentRoomId));
btnToggleGrid.addEventListener("click", () => {
  WE.showGrid = !WE.showGrid;
  btnToggleGrid.classList.toggle("is-active", WE.showGrid);
  renderCanvas();
});
btnFitView.addEventListener("click", fitView);
btnNewRoom.addEventListener("click",    openNewRoomDialog);
btnNewWay.addEventListener("click",     () => openNewWayDialog());
btnMapNewRoom.addEventListener("click", openNewRoomDialog);
btnMapConnect.addEventListener("click", () => {
  WE.mapConnectMode = !WE.mapConnectMode;
  btnMapConnect.classList.toggle("is-active", WE.mapConnectMode);
  setStatus(WE.mapConnectMode ? "Click a source room on the map, then a target room." : "");
});

btnToggleLib.addEventListener("click", () => {
  libraryPanel.classList.toggle("is-collapsed");
  btnToggleLib.textContent = libraryPanel.classList.contains("is-collapsed") ? "Props ▲" : "Props ▼";
});

if (btnToggleSidebar) {
  btnToggleSidebar.addEventListener("click", () => {
    document.querySelector(".we-sidebar").classList.toggle("is-open");
  });
}

librarySearch.addEventListener("input", () => {
  WE.libSearch = librarySearch.value;
  renderPropLibraryGrid();
});

if (libraryTagFilter) {
  libraryTagFilter.addEventListener("change", () => {
    WE.libTagFilter = libraryTagFilter.value;
    renderPropLibraryGrid();
  });
}

btnReload.addEventListener("click", () => {
  if (!WE.token) {
    setStatus("No session token found. Please log in from the main client first.", true);
    return;
  }
  loadState();
});

// ---------------------------------------------------------------------------
// Keyboard shortcuts
// ---------------------------------------------------------------------------

document.addEventListener("keydown", e => {
  const tag = document.activeElement.tagName;
  if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return;

  if (e.key === "s" || e.key === "S") { setTool("select"); return; }
  if (e.key === "p" || e.key === "P") { setTool("place");  return; }
  if (e.key === "e" || e.key === "E") { setTool("exit");   return; }
  if (e.key === "l" || e.key === "L") { btnToggleLib.click(); return; }
  if (e.key === "g" || e.key === "G") { btnToggleGrid.click(); return; }
  if (e.key === "f" || e.key === "F") { fitView(); return; }
  if (e.key === "Escape") {
    if (WE.activeTool !== "select") setTool("select");
    hideExitPicker();
    return;
  }
  if ((e.ctrlKey || e.metaKey) && e.key === "z") {
    e.shiftKey ? redo() : undo();
    e.preventDefault(); return;
  }
  if ((e.ctrlKey || e.metaKey) && e.key === "y") { redo(); e.preventDefault(); return; }
  if ((e.ctrlKey || e.metaKey) && e.key === "s") {
    e.preventDefault();
    WE.currentRoomId && saveRoom(WE.currentRoomId);
    return;
  }
  if ((e.ctrlKey || e.metaKey) && e.key === "d" && WE.selectedPropId) {
    e.preventDefault();
    duplicateProp(WE.selectedPropId);
    return;
  }
  if ((e.key === "Delete" || e.key === "Backspace") && WE.selectedPropId) {
    e.preventDefault();
    removeProp(WE.selectedPropId);
    return;
  }
  // arrow nudge
  if (WE.selectedPropId && ["ArrowLeft","ArrowRight","ArrowUp","ArrowDown"].includes(e.key)) {
    e.preventDefault();
    const step = e.shiftKey ? 8 : 1;
    const draft = currentDraft();
    if (!draft) return;
    const prop = draft.props?.find(p => p.prop_instance_id === WE.selectedPropId);
    if (!prop) return;
    if (e.key === "ArrowLeft")  prop.position.x -= step;
    if (e.key === "ArrowRight") prop.position.x += step;
    if (e.key === "ArrowUp")    prop.position.y -= step;
    if (e.key === "ArrowDown")  prop.position.y += step;
    markDirty(WE.currentRoomId);
    renderCanvas();
    renderPropertiesPanel();
  }
});

// ---------------------------------------------------------------------------
// Escape HTML
// ---------------------------------------------------------------------------

function esc(str) {
  return String(str || "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

window.addEventListener("beforeunload", e => {
  if (WE.dirty.size > 0) {
    e.preventDefault();
    e.returnValue = "You have unsaved room changes. Are you sure you want to leave?";
  }
});

// ---------------------------------------------------------------------------
// Init
// ---------------------------------------------------------------------------

function init() {
  setActiveTab("room");
  setTool("select");

  const token = localStorage.getItem(TOKEN_KEY) || "";
  if (token) {
    WE.token = token;
    loginStatusEl.textContent = "";
    loadState();
  } else {
    loginStatusEl.textContent = "Not logged in";
    loginStatusEl.style.color = "#f66";
    setStatus("Please log in from the main tinyrooms client first, then return to this page.", true);
  }
}

init();
