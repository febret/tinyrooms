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

/** Normalize one visible catalog row into a queue track, or null for folders. */
export function queueTrackFromItem(item) {
  if (!item || typeof item !== "object" || item.kind === "directory") return null;
  return normalizeTrack({ song: songForItem(item), label: item.title });
}

/** Build the playable queue for the music state the user is currently viewing. */
export function queueForMusic(music, user) {
  const source = music?.mode === "starred"
    ? (user?.starredTracks || [])
    : music?.mode === "suggestions"
      ? [...(music?.top || []), ...(music?.community || [])]
      : (music?.items || []);
  return source.map(entry => (
    music?.mode === "starred" ? normalizeTrack(entry) : queueTrackFromItem(entry)
  )).filter(Boolean);
}

/** Find a song's queue position, defaulting to the queue start. */
export function indexOfSong(queue, song) {
  const position = (Array.isArray(queue) ? queue : []).findIndex(track => track?.song === song);
  return position < 0 ? 0 : position;
}

/** Step through a queue with wraparound; an empty queue stays at index zero. */
export function stepQueue(queue, index, delta) {
  const tracks = Array.isArray(queue) ? queue : [];
  if (!tracks.length) return 0;
  const current = Number.isFinite(index) ? Number(index) : 0;
  return (current + Number(delta || 0) + tracks.length * 1000) % tracks.length;
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
    const state = store.getState();
    const queue = queueForMusic(state.ui.phoneMusic, state.user);
    const queueIndex = indexOfSong(queue, normalized.song);
    store.dispatch({ type: "phone-music-play", track: normalized, queue, queueIndex });
    savePhoneTrack(normalized);
    savePhoneMusicEnabled(true);
  }

  function step(delta) {
    const state = store.getState();
    const stored = Array.isArray(state.ui.phoneMusic.queue) && state.ui.phoneMusic.queue.length
      ? state.ui.phoneMusic.queue
      : queueForMusic(state.ui.phoneMusic, state.user);
    if (!stored.length) {
      onToast?.("No track queued.", "info");
      return;
    }
    const start = state.ui.phoneMusic.track?.song
      ? indexOfSong(stored, state.ui.phoneMusic.track.song)
      : Number(state.ui.phoneMusic.queueIndex || 0);
    const queueIndex = stepQueue(stored, start, delta);
    const next = stored[queueIndex];
    store.dispatch({ type: "phone-music-play", track: next, queue: stored, queueIndex });
    savePhoneTrack(next);
    savePhoneMusicEnabled(true);
  }

  function previous() {
    step(-1);
  }

  function next() {
    step(1);
  }

  function toggleOrPlay() {
    const music = store.getState().ui.phoneMusic;
    if (music.track) {
      toggle();
      return;
    }
    const first = queueForMusic(music, store.getState().user)[0];
    if (!first) {
      onToast?.("No track queued.", "info");
      return;
    }
    play(first);
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

  async function toggleStarCurrent() {
    const track = store.getState().ui.phoneMusic.track;
    if (!track) {
      onToast?.("Play a track first.", "info");
      return;
    }
    await toggleStar(track);
  }

  return {
    render(state) {
      syncFrame(state);
    },
    load,
    play,
    stop,
    toggle,
    toggleOrPlay,
    previous,
    next,
    toggleStar,
    toggleStarCurrent,
    destroy() {
      frame.remove();
    },
  };
}

function documentForFrame() {
  if (typeof document !== "undefined") return document;
  return globalThis.document;
}
