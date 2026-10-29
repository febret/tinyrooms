import { toggleClass } from "../inert.js";

/** Reflect the Peeps sidebar visibility onto the root. */
export function syncPeepsChrome(state, root) {
  const visible = state.ui.peepsVisible !== false && !state.room?.board?.spritesEnabled;
  toggleClass(root, "peeps-hidden", !visible);
}
