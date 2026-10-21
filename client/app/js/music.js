import { escapeHtml, updateMarkup } from "./presentation.js";

const CHIPTUNE_BASE = "https://chiptune.app";
const RESULT_LIMIT = 20;

/** Build the chiptune.app play URL for a song id or catalog path. */
export function chiptunePlayUrl(song) {
  const value = String(song ?? "").trim();
  if (!value) return "about:blank";
  return `${CHIPTUNE_BASE}/?play=${encodeURIComponent(value)}`;
}

/** Normalize a track payload from the server into `{ song, label }` or null. */
export function normalizeTrack(track) {
  if (!track || typeof track !== "object") return null;
  const song = String(track.song ?? "").trim();
  if (!song) return null;
  return { song, label: String(track.label ?? "").trim() };
}

/** Human-readable label for a track, falling back to its song id/path. */
export function trackLabel(track) {
  const normalized = normalizeTrack(track);
  if (!normalized) return "No music";
  return normalized.label || normalized.song;
}

/** The song id or path the chiptune.app player should load for a catalog row. */
export function songForItem(item) {
  if (!item || typeof item !== "object") return "";
  return String(item.id || item.path || "").trim();
}

function quoteArg(value) {
  const text = String(value ?? "");
  if (!/[\s"\\]/.test(text)) return text;
  return `"${text.replace(/(["\\])/g, "\\$1")}"`;
}

/** Build the `.music set` command for a catalog row. */
export function buildMusicCommand(song, label = "") {
  const args = [".music", "set", quoteArg(song)];
  const text = String(label ?? "").trim();
  if (text) args.push(quoteArg(text));
  return args.join(" ");
}

function parentPath(path) {
  const trimmed = String(path ?? "").replace(/^\/+|\/+$/g, "");
  const index = trimmed.lastIndexOf("/");
  return index < 0 ? "" : trimmed.slice(0, index);
}

function itemMarkup(item, { canControl }) {
  const song = songForItem(item);
  if (!song) return "";
  const title = escapeHtml(item.title || song);
  const subtitle = escapeHtml(item.subtitle || "");
  const isDirectory = item.kind === "directory";
  const actions = isDirectory
    ? `<button type="button" class="music-row-open quiet" data-music-action="browse" data-music-path="${escapeHtml(item.path || "")}">Open</button>`
    : `<button type="button" class="music-row-listen quiet" data-music-action="listen" data-music-song="${escapeHtml(song)}" data-music-label="${escapeHtml(item.title || "")}">Listen</button>`
      + (canControl
        ? `<button type="button" class="music-row-set quiet" data-music-action="set-room" data-music-song="${escapeHtml(song)}" data-music-label="${escapeHtml(item.title || "")}">Set room</button>`
        : "");
  return `<li class="music-row${isDirectory ? " directory" : ""}">
    <span class="music-row-text"><strong>${title}</strong>${subtitle ? `<small>${subtitle}</small>` : ""}</span>
    <span class="music-row-actions">${actions}</span>
  </li>`;
}

function resultsMarkup(view, canControl) {
  if (view.loading) return `<p class="music-empty">Loading…</p>`;
  if (view.error) return `<p class="music-empty music-error">${escapeHtml(view.error)}</p>`;
  if (!view.items.length) return `<p class="music-empty">${view.mode === "search" ? "No matching tracks." : "Nothing here yet."}</p>`;
  return `<ul class="music-results">${view.items.map(item => itemMarkup(item, { canControl })).join("")}</ul>`;
}

function panelMarkup(state, view, canControl) {
  const roomTrack = normalizeTrack(state.room?.music);
  const override = normalizeTrack(state.ui.musicOverride);
  const effective = override || roomTrack;
  const enabled = Boolean(state.ui.musicEnabled);
  const updatedBy = state.room?.music?.updated_by ? String(state.room.music.updated_by) : "";
  const mode = view.mode;
  return `<header class="music-header">
      <h2 id="music-title">Music</h2>
      <button type="button" class="music-close quiet" data-music-action="close" aria-label="Close music player">×</button>
    </header>
    <div class="music-now">
      <p class="music-now-label">${escapeHtml(trackLabel(effective))}</p>
      <p class="music-now-meta">${override
        ? "Listening to your pick"
        : roomTrack
          ? `Room music${updatedBy ? ` · set by ${escapeHtml(updatedBy)}` : ""}`
          : "No room music"}</p>
      <div class="music-now-actions">
        <button type="button" class="quiet" data-music-action="toggle-enabled" aria-pressed="${enabled}">${enabled ? "Music On" : "Turn on music"}</button>
        ${override ? `<button type="button" class="quiet" data-music-action="follow-room">Follow room</button>` : ""}
      </div>
    </div>
    <form class="music-search" data-music-action="search">
      <input type="search" name="query" placeholder="Search chiptune.app" aria-label="Search chiptune.app" value="${escapeHtml(view.query)}" maxlength="120">
      <button type="submit" class="quiet">Search</button>
    </form>
    <nav class="music-tabs" aria-label="Music sources">
      <button type="button" class="quiet" data-music-action="mode" data-music-mode="top" aria-pressed="${mode === "top"}">Top</button>
      <button type="button" class="quiet" data-music-action="mode" data-music-mode="browse" aria-pressed="${mode === "browse"}">Browse</button>
    </nav>
    ${mode === "browse" ? `<div class="music-crumbs">
      <button type="button" class="quiet" data-music-action="browse" data-music-path="${escapeHtml(parentPath(view.path))}"${view.path ? "" : " disabled"}>Up</button>
      <span>${escapeHtml(view.path || "Catalog")}</span>
    </div>` : ""}
    ${resultsMarkup(view, canControl)}
    <footer class="music-footer">
      ${canControl ? "" : "<span>Only the room owner or staff can change room music.</span>"}
      <a href="https://chiptune.app/" target="_blank" rel="noopener noreferrer">Powered by chiptune.app</a>
    </footer>`;
}

/**
 * Own a hidden chiptune.app iframe plus the Tinyrooms mini player.
 *
 * The cross-origin frame cannot be scripted, so each track change reloads
 * `https://chiptune.app/?play=<song>`. Music starts only after a user gesture
 * (autoplay policy); the server owns the room's authoritative track.
 */
export function createMusicPlayer({ root, store, api, sendCommand, onToast, onError }) {
  const document = root.ownerDocument;
  const frame = document.createElement("iframe");
  frame.className = "music-engine-frame";
  frame.setAttribute("allow", "autoplay");
  frame.setAttribute("referrerpolicy", "no-referrer");
  frame.setAttribute("aria-hidden", "true");
  frame.setAttribute("tabindex", "-1");
  frame.title = "Chiptune.app music player";
  frame.src = "about:blank";
  document.body.appendChild(frame);

  let loadedSong = "";
  const view = { mode: "top", path: "", query: "", items: [], loading: false, error: "", loaded: false };

  root.classList.add("music-player");
  root.setAttribute("role", "dialog");
  root.setAttribute("aria-modal", "false");
  root.setAttribute("aria-labelledby", "music-title");
  root.tabIndex = -1;

  function canControl(state) {
    if (!state.room) return false;
    if (state.room.canEditRoom) return true;
    const powers = new Set(state.user?.powers || []);
    return powers.has("game-master") || powers.has("admin");
  }

  function effectiveTrack(state) {
    return normalizeTrack(state.ui.musicOverride) || normalizeTrack(state.room?.music);
  }

  function loadSong(song) {
    const next = String(song ?? "").trim();
    if (next === loadedSong) return;
    loadedSong = next;
    frame.src = next ? chiptunePlayUrl(next) : "about:blank";
  }

  function syncFrame(state) {
    if (!state.ui.musicEnabled) {
      loadSong("");
      return;
    }
    const track = effectiveTrack(state);
    loadSong(track ? track.song : "");
  }

  async function loadView() {
    view.loading = true;
    view.loaded = true;
    view.error = "";
    render(store.getState());
    try {
      if (view.mode === "search") view.items = await api.chiptuneSearch(view.query, RESULT_LIMIT);
      else if (view.mode === "browse") view.items = await api.chiptuneBrowse(view.path);
      else view.items = await api.chiptuneTop(RESULT_LIMIT);
    } catch (error) {
      view.error = error instanceof Error ? error.message : String(error);
      view.items = [];
    } finally {
      view.loading = false;
      render(store.getState());
    }
  }

  function enable() {
    if (store.getState().ui.musicEnabled) return;
    store.dispatch({ type: "music-enabled", enabled: true });
    const track = effectiveTrack(store.getState());
    loadedSong = "";
    loadSong(track ? track.song : "");
  }

  function disable() {
    store.dispatch({ type: "music-enabled", enabled: false });
    loadSong("");
  }

  root.addEventListener("click", event => {
    const button = event.target.closest("[data-music-action]");
    if (!button) return;
    const action = button.dataset.musicAction;
    if (action === "close") store.dispatch({ type: "close-music" });
    else if (action === "toggle-enabled") (store.getState().ui.musicEnabled ? disable() : enable());
    else if (action === "follow-room") store.dispatch({ type: "music-follow-room" });
    else if (action === "mode") {
      view.mode = button.dataset.musicMode === "browse" ? "browse" : "top";
      view.path = "";
      view.loaded = false;
      void loadView();
    } else if (action === "browse") {
      view.mode = "browse";
      view.path = button.dataset.musicPath || "";
      view.loaded = false;
      void loadView();
    } else if (action === "listen") {
      store.dispatch({ type: "music-override", track: { song: button.dataset.musicSong, label: button.dataset.musicLabel } });
      if (!store.getState().ui.musicEnabled) enable();
    } else if (action === "set-room") {
      const song = button.dataset.musicSong || "";
      const label = button.dataset.musicLabel || "";
      sendCommand(buildMusicCommand(song, label)).catch(onError);
    }
  });

  root.addEventListener("submit", event => {
    const form = event.target.closest("[data-music-action='search']");
    if (!form) return;
    event.preventDefault();
    const query = String(new FormData(form).get("query") || "").trim();
    if (!query) return;
    view.mode = "search";
    view.query = query;
    view.loaded = false;
    void loadView();
  });

  function render(state) {
    const open = Boolean(state.room && state.ui.musicOpen);
    syncFrame(state);
    if (root.hidden !== !open) root.hidden = !open;
    if (root.hasAttribute("inert") !== !open) root.toggleAttribute("inert", !open);
    if (root.getAttribute("aria-hidden") !== String(!open)) root.setAttribute("aria-hidden", String(!open));
    if (!open) {
      updateMarkup(root, "");
      return;
    }
    updateMarkup(root, panelMarkup(state, view, canControl(state)));
    if (!view.loaded && !view.loading) void loadView();
  }

  return {
    render,
    enable,
    /** Clear local state when the room changes so the next room follows its own track. */
    resetRoom() {
      view.mode = "top";
      view.path = "";
      view.query = "";
      view.items = [];
      view.error = "";
      view.loaded = false;
    },
    destroy() {
      frame.remove();
    },
  };
}
