import { savePhoneMusicEnabled, savePhoneTrack } from "./preferences.js";

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
  const song = String(track.song ?? track.id ?? "").trim();
  if (!song) return null;
  return { song, label: String(track.label ?? track.title ?? "").trim() };
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

export function parentPath(path) {
  const trimmed = String(path ?? "").replace(/^\/+|\/+$/g, "");
  const index = trimmed.lastIndexOf("/");
  return index < 0 ? "" : trimmed.slice(0, index);
}

export function starredSongs(user) {
  return new Set((user?.starredTracks || []).map(track => track.song));
}

/**
 * Own the hidden personal chiptune.app player used by the phone's music app.
 *
 * The cross-origin frame cannot be scripted, so each track change reloads
 * `https://chiptune.app/?play=<song>`. The phone owns playback state; rooms no
 * longer carry music.
 */
export function createPhoneMusic({ api, store, onToast, onError }) {
  const document = documentForFrame();
  const frame = document.createElement("iframe");
  frame.className = "phone-music-engine-frame";
  frame.setAttribute("allow", "autoplay");
  frame.setAttribute("referrerpolicy", "no-referrer");
  frame.setAttribute("aria-hidden", "true");
  frame.setAttribute("tabindex", "-1");
  frame.title = "Chiptune.app music player";
  frame.src = "about:blank";
  document.body.appendChild(frame);

  let loadedSong = "";
  let requestToken = 0;

  function loadSong(song) {
    const next = String(song ?? "").trim();
    if (next === loadedSong) return;
    loadedSong = next;
    frame.src = next ? chiptunePlayUrl(next) : "about:blank";
  }

  function syncFrame(state) {
    const music = state.ui.phoneMusic;
    loadSong(music.enabled && music.track ? music.track.song : "");
  }

  function play(track) {
    const normalized = normalizeTrack(track);
    if (!normalized) return;
    store.dispatch({ type: "phone-music-play", track: normalized });
    savePhoneTrack(normalized);
    savePhoneMusicEnabled(true);
  }

  function stop() {
    store.dispatch({ type: "phone-music-stop" });
    savePhoneMusicEnabled(false);
  }

  function toggle() {
    const music = store.getState().ui.phoneMusic;
    if (!music.track) return;
    const enabled = !music.enabled;
    store.dispatch({ type: "phone-music-toggle" });
    savePhoneMusicEnabled(enabled);
  }

  async function load(mode = "suggestions", { path = "", query = "", force = false } = {}) {
    const current = store.getState().ui.phoneMusic;
    if (!force && !current.error && current.loaded && current.mode === mode && current.path === path && current.query === query) return;
    store.dispatch({ type: "phone-music-mode", mode, path, query, load: true });
    const token = ++requestToken;
    try {
      if (mode === "starred") {
        store.dispatch({ type: "phone-music-loaded", items: [] });
        return;
      }
      if (mode === "search") {
        const items = await api.chiptuneSearch(query, RESULT_LIMIT);
        if (token === requestToken) store.dispatch({ type: "phone-music-loaded", items });
        return;
      }
      if (mode === "browse") {
        const items = await api.chiptuneBrowse(path);
        if (token === requestToken) store.dispatch({ type: "phone-music-loaded", items });
        return;
      }
      const suggestions = await api.chiptuneSuggestions(RESULT_LIMIT);
      if (token === requestToken) store.dispatch({ type: "phone-music-loaded", top: suggestions.top, community: suggestions.community });
    } catch (error) {
      if (token === requestToken) {
        store.dispatch({ type: "phone-music-error", error: error instanceof Error ? error.message : String(error) });
        onError?.(error);
      }
    }
  }

  async function toggleStar(track) {
    const normalized = normalizeTrack(track);
    if (!normalized) return;
    const wasStarred = starredSongs(store.getState().user).has(normalized.song);
    try {
      const tracks = await api.chiptuneSetStarred(normalized.song, normalized.label, !wasStarred);
      store.dispatch({ type: "starred-tracks", tracks });
      onToast?.(wasStarred ? "Removed from your starred tracks." : "Added to your starred tracks.", "success");
      const music = store.getState().ui.phoneMusic;
      if (music.mode === "suggestions") await load("suggestions", { force: true });
    } catch (error) {
      onError?.(error);
    }
  }

  return {
    render(state) {
      syncFrame(state);
    },
    load,
    play,
    stop,
    toggle,
    toggleStar,
    destroy() {
      frame.remove();
    },
  };
}

function documentForFrame() {
  if (typeof document !== "undefined") return document;
  return globalThis.document;
}
