import { escapeHtml, placeAt } from "./presentation.js";
import { tileMarkup } from "./views/view-helpers.js";

function cardMarkup(stack, selection) {
  const selected = selection?.kind === "container-card" && selection.id === stack.stackId;
  const tile = tileMarkup(stack.definition, stack, selected, "container", { face: "illustration" });
  return `<div class="room-picker-entry" role="listitem">${tile}
    <span class="room-picker-label" aria-hidden="true">${escapeHtml(stack.definition.label)}${stack.quantity > 1 ? ` ×${escapeHtml(stack.quantity)}` : ""}</span>
  </div>`;
}

/** Pure markup builder; callers only need to render it while the panel is open. */
export function containerPanelMarkup(state) {
  const container = state.container;
  const cards = container?.cards || [];
  return `<header class="room-picker-header">
      <h2 id="container-panel-title">${escapeHtml(container?.label || "Container")}</h2>
      <button type="button" class="room-picker-close quiet" data-container-close aria-label="Close container">×</button>
    </header>
    <div class="room-picker-track">
      <div class="room-picker-grid" role="list" aria-label="Container contents">${cards.length
        ? cards.map(stack => cardMarkup(stack, state.selection)).join("")
        : '<p class="room-picker-empty">Empty.</p>'}</div>
    </div>`;
}

/** Non-modal container panel: the same docked-panel pattern as the room picker. */
export function createContainerPanel({ root, store, onSelect, thumbnails, projectPosition }) {
  const document = root.ownerDocument;
  let markup = "";
  let wasOpen = false;
  const isOpen = () => Boolean(store.getState().room && store.getState().ui.containerOpen);
  const itemButtons = () => [...root.querySelectorAll("[data-stack-id]")];
  const identity = button => button?.hasAttribute("data-stack-id") ? `card:${button.dataset.stackId}` : "close";

  function anchorFor(state) {
    const prop = (state.room?.props || []).find(entry => entry.id === state.container?.instanceId);
    if (!prop || !Array.isArray(prop.position) || typeof projectPosition !== "function") return null;
    return projectPosition(prop.position);
  }

  function placeNear(anchor) {
    const parent = root.offsetParent;
    if (!anchor || !parent || !Number.isFinite(anchor.x) || !Number.isFinite(anchor.y)) return false;
    const bounds = parent.getBoundingClientRect();
    const width = root.offsetWidth || 420;
    const height = root.offsetHeight || 240;
    const x = Math.max(8, Math.min(bounds.width - width - 8, anchor.x - bounds.left + 16));
    const y = Math.max(8, Math.min(bounds.height - height - 8, anchor.y - bounds.top + 16));
    placeAt(root, `${x}px`, `${y}px`);
    return true;
  }

  function clearPosition() {
    root.style.left = "";
    root.style.top = "";
  }

  root.classList.add("room-picker");
  root.setAttribute("role", "dialog");
  root.setAttribute("aria-modal", "false");
  root.setAttribute("aria-labelledby", "container-panel-title");
  root.tabIndex = -1;

  function focusLookBar() {
    document.querySelector("#look-bar [data-look-inspect]")?.focus({ preventScroll: true });
  }

  function close({ restoreFocus = false } = {}) {
    store.dispatch({ type: "close-container" });
    if (restoreFocus) focusLookBar();
  }

  function sync(state) {
    const open = Boolean(state.room && state.ui.containerOpen);
    if (root.hidden !== !open) root.hidden = !open;
    if (root.hasAttribute("inert") !== !open) root.toggleAttribute("inert", !open);
    if (root.getAttribute("aria-hidden") !== String(!open)) root.setAttribute("aria-hidden", String(!open));
    if (!open) {
      if (markup) root.replaceChildren();
      markup = "";
      wasOpen = false;
      return;
    }
    const next = containerPanelMarkup(state);
    const freshlyOpened = !wasOpen;
    wasOpen = true;
    if (markup === next && !freshlyOpened) return;
    const active = root.contains(document.activeElement) ? document.activeElement : null;
    const key = active ? identity(active) : null;
    const oldButtons = itemButtons();
    const index = oldButtons.indexOf(active);
    const track = root.querySelector(".room-picker-track");
    const scroll = { top: track?.scrollTop || 0, left: track?.scrollLeft || 0 };
    root.innerHTML = next;
    markup = next;
    if (freshlyOpened || active) {
      const buttons = itemButtons();
      const restored = key
        ? [...buttons, root.querySelector("[data-container-close]")].find(button => identity(button) === key)
        : null;
      (restored || buttons[Math.min(Math.max(index, 0), buttons.length - 1)] || root.querySelector("[data-container-close]") || root)
        .focus({ preventScroll: true });
    }
    const newTrack = root.querySelector(".room-picker-track");
    if (newTrack) {
      newTrack.scrollTop = scroll.top;
      newTrack.scrollLeft = scroll.left;
    }
    if (!placeNear(anchorFor(state))) clearPosition();
    thumbnails?.sync(root);
  }

  root.addEventListener("load", event => {
    const image = event.target;
    if (image.tagName === "IMG") {
      const ready = image.naturalWidth > 0;
      image.classList.toggle("room-picker-image-ready", ready);
      image.parentElement.classList.toggle("room-picker-has-image", ready);
    }
  }, true);
  root.addEventListener("error", event => {
    if (event.target.tagName === "IMG") {
      event.target.classList.remove("room-picker-image-ready");
      event.target.parentElement.classList.remove("room-picker-has-image");
    }
  }, true);

  root.addEventListener("click", event => {
    if (!isOpen()) return;
    if (event.target.closest("[data-container-close]")) {
      close({ restoreFocus: true });
      return;
    }
    const button = event.target.closest("[data-stack-id]");
    if (!button || !root.contains(button)) return;
    onSelect({ kind: "container-card", id: button.dataset.stackId });
  });

  document.addEventListener("pointerdown", event => {
    if (isOpen() && !root.contains(event.target)) close();
  });

  sync(store.getState());

  return {
    sync,
    close,
    handleEscape(event) {
      if (event.key !== "Escape" || !isOpen()) return false;
      event.preventDefault();
      close({ restoreFocus: true });
      return true;
    },
  };
}
