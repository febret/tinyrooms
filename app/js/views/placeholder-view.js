import { modalShell, PLACEHOLDER_VIEWS } from "./view-helpers.js";

export function placeholderView(view) {
  const [label, emptyText] = PLACEHOLDER_VIEWS[view];
  return modalShell({
    ariaLabel: label,
    title: `Your ${label}`,
    body: `<div class="empty-state">${emptyText}</div>`,
  });
}
