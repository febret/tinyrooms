import { toggleClass } from "./inert.js";

/** Reflect the Peeps sidebar visibility onto the root. */
export function syncPeepsChrome(state, root) {
  const spriteMode = Boolean(state.room?.board?.spritesEnabled);
  const visible = state.ui.peepsVisible !== false && !spriteMode;
  toggleClass(root, "sprite-mode", spriteMode);
  toggleClass(root, "peeps-hidden", !visible);
}
