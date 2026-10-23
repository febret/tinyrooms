import { withBase } from "./base-path.js";

/** Stable UI icon keys served from `/assets/ui/<key>.svg`.
 *
 * The server resolves each key as world `ui/<key>.svg`, then enabled-mod
 * `ui/<key>.svg` files, then the core defaults under `data/ui/icons/`.
 */
export const UI_ICON_KEYS = Object.freeze([
  "settings",
  "room-picker",
  "multiverse",
  "edit",
  "clapper",
  "tinymag",
  "keyring",
  "peeps",
  "log",
  "sound",
  "fullscreen",
  "outlines",
  "bubble",
  "audio",
  "mute",
  "commands",
  "logout",
  "reconnect",
]);

const UI_ICON_KEY_PATTERN = /^[a-z0-9][a-z0-9-]*$/;

/** Return the served URL for a UI icon key, honoring any deployment base path. */
export function uiIconUrl(key) {
  const name = String(key || "");
  if (!UI_ICON_KEY_PATTERN.test(name) || !UI_ICON_KEYS.includes(name)) {
    throw new Error(`Unknown UI icon '${name}'.`);
  }
  return withBase(`/assets/ui/${name}.svg`);
}

/** Render an image-backed toolbar icon; the host button keeps the accessible label. */
export function uiIconMarkup(key, { className = "toolbar-icon" } = {}) {
  const safeClass = String(className || "").replace(/[^a-zA-Z0-9 _-]/g, "");
  return `<img class="${safeClass}" src="${uiIconUrl(key)}" alt="" aria-hidden="true" draggable="false">`;
}
