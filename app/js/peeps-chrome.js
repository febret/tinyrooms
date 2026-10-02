import { toggleClass } from "./inert.js";

/** Reflect the Peeps sidebar visibility onto the root and the toolbar toggle. */
export function syncPeepsChrome(state, root, toggle) {
  const visible = state.ui.peepsVisible !== false;
  toggleClass(root, "peeps-hidden", !visible);
  const expanded = visible ? "true" : "false";
  if (toggle.getAttribute("aria-expanded") !== expanded) toggle.setAttribute("aria-expanded", expanded);
  const label = visible ? "Hide peeps" : "Show peeps";
  if (toggle.getAttribute("aria-label") !== label) toggle.setAttribute("aria-label", label);
  const title = visible ? "Hide peep list" : "Show peep list";
  if (toggle.title !== title) toggle.title = title;
}
