const OUTLINE_ACTIVE_PROPS_KEY = "tinyrooms:outline-active-props";
const BUBBLE_TIMEOUT_KEY = "tinyrooms:bubble-timeout";
const FULLSCREEN_KEY = "tinyrooms:fullscreen";

export const BUBBLE_TIMEOUT_CHOICES = [15000, 30000, 0];

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
