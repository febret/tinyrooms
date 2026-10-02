const OUTLINE_ACTIVE_PROPS_KEY = "tinyrooms:outline-active-props";

export function savedOutlineActiveProps() {
  try { return localStorage.getItem(OUTLINE_ACTIVE_PROPS_KEY) === "true"; }
  catch { return false; }
}

export function saveOutlineActiveProps(enabled) {
  try { localStorage.setItem(OUTLINE_ACTIVE_PROPS_KEY, String(enabled)); }
  catch { /* Storage may be unavailable. */ }
}
