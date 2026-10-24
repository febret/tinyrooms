const OUTLINE_ACTIVE_PROPS_KEY = "tinyrooms:outline-active-props";
const BUBBLE_TIMEOUT_KEY = "tinyrooms:bubble-timeout";
const SIDEBAR_SIZE_KEY = "tinyrooms:sidebar-size";
const TOOLBAR_SIZE_KEY = "tinyrooms:toolbar-size";
const FULLSCREEN_KEY = "tinyrooms:fullscreen";
const INVENTORY_COMPACT_KEY = "tinyrooms:inventory-compact";
const PHONE_TRACK_KEY = "tinyrooms:phone-track";
const PHONE_MUSIC_ENABLED_KEY = "tinyrooms:phone-music-enabled";

export const BUBBLE_TIMEOUT_CHOICES = [15000, 30000, 0];
export const PANEL_SIZE_CHOICES = ["compact", "normal", "large"];

function savedPanelSize(key) {
  try {
    const stored = localStorage.getItem(key);
    return PANEL_SIZE_CHOICES.includes(stored) ? stored : "normal";
  } catch { return "normal"; }
}

function savePanelSize(key, size) {
  try {
    if (PANEL_SIZE_CHOICES.includes(size)) localStorage.setItem(key, size);
  } catch { /* Storage may be unavailable. */ }
}

export function savedSidebarSize() {
  return savedPanelSize(SIDEBAR_SIZE_KEY);
}

export function saveSidebarSize(size) {
  savePanelSize(SIDEBAR_SIZE_KEY, size);
}

export function savedToolbarSize() {
  return savedPanelSize(TOOLBAR_SIZE_KEY);
}

export function saveToolbarSize(size) {
  savePanelSize(TOOLBAR_SIZE_KEY, size);
}

export function savedOutlineActiveProps() {
  try { return localStorage.getItem(OUTLINE_ACTIVE_PROPS_KEY) === "true"; }
  catch { return false; }
}

export function saveOutlineActiveProps(enabled) {
  try { localStorage.setItem(OUTLINE_ACTIVE_PROPS_KEY, String(enabled)); }
  catch { /* Storage may be unavailable. */ }
}

export function savedBubbleTimeout() {
  try {
    const stored = localStorage.getItem(BUBBLE_TIMEOUT_KEY);
    if (stored === null || stored === "") return BUBBLE_TIMEOUT_CHOICES[0];
    const raw = Number(stored);
    return BUBBLE_TIMEOUT_CHOICES.includes(raw) ? raw : BUBBLE_TIMEOUT_CHOICES[0];
  } catch { return BUBBLE_TIMEOUT_CHOICES[0]; }
}

export function saveBubbleTimeout(timeoutMs) {
  try { localStorage.setItem(BUBBLE_TIMEOUT_KEY, String(timeoutMs)); }
  catch { /* Storage may be unavailable. */ }
}

export function bubbleTimeoutLabel(timeoutMs) {
  return timeoutMs > 0 ? `${Math.round(timeoutMs / 1000)}s` : "Off";
}

export function savedFullscreenIntent() {
  try { return localStorage.getItem(FULLSCREEN_KEY) === "true"; }
  catch { return false; }
}

export function saveFullscreenIntent(enabled) {
  try { localStorage.setItem(FULLSCREEN_KEY, String(Boolean(enabled))); }
  catch { /* Storage may be unavailable. */ }
}

export function savedInventoryCompact() {
  try {
    const stored = localStorage.getItem(INVENTORY_COMPACT_KEY);
    return stored === null ? true : stored === "true";
  } catch { return true; }
}

export function saveInventoryCompact(enabled) {
  try { localStorage.setItem(INVENTORY_COMPACT_KEY, String(Boolean(enabled))); }
  catch { /* Storage may be unavailable. */ }
}

export function savedPhoneTrack() {
  try {
    const raw = localStorage.getItem(PHONE_TRACK_KEY);
    if (!raw) return null;
    const track = JSON.parse(raw);
    const song = String(track?.song || "").trim();
    return song ? { song, label: String(track.label || "").trim() } : null;
  } catch { return null; }
}

export function savePhoneTrack(track) {
  try {
    if (!track?.song) localStorage.removeItem(PHONE_TRACK_KEY);
    else localStorage.setItem(PHONE_TRACK_KEY, JSON.stringify({ song: track.song, label: track.label || "" }));
  } catch { /* Storage may be unavailable. */ }
}

export function savedPhoneMusicEnabled() {
  try { return localStorage.getItem(PHONE_MUSIC_ENABLED_KEY) === "true"; }
  catch { return false; }
}

export function savePhoneMusicEnabled(enabled) {
  try { localStorage.setItem(PHONE_MUSIC_ENABLED_KEY, String(Boolean(enabled))); }
  catch { /* Storage may be unavailable. */ }
}
