export function syncEmoteChrome(state, toggle, icon, menu) {
  const open = Boolean(state.ui.emoteMenuOpen && state.room);
  const expanded = open ? "true" : "false";
  if (toggle.getAttribute("aria-expanded") !== expanded) toggle.setAttribute("aria-expanded", expanded);
  if (toggle.classList.contains("active") !== open) toggle.classList.toggle("active", open);
  if (menu.inert === open) menu.inert = !open;
  const iconUrl = state.user?.coreCards?.emotes?.imageUrl || "";
  toggle.hidden = !iconUrl;
  if (iconUrl && icon.getAttribute("src") !== iconUrl) icon.src = iconUrl;
}
