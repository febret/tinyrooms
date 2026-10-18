import { escapeHtml } from "./presentation.js";
import { hasActivePropActions } from "./prop-actions.js";
import { tileMarkup } from "./views/view-helpers.js";

function propMarkup(prop, selection) {
  const selected = selection?.kind === "prop" && selection.id === prop.id;
  return `<div class="room-picker-entry" role="listitem">
    <button type="button" class="room-picker-prop" data-room-picker-prop="${escapeHtml(prop.id)}"
      aria-label="${escapeHtml(prop.label)}" aria-pressed="${selected}" title="${escapeHtml(prop.label)}">
      <span class="room-picker-art">
        <span class="room-picker-fallback" aria-hidden="true">◇</span>
        ${prop.modelUrl ? `<img data-thumb-model="${escapeHtml(prop.modelUrl)}"
          data-thumb-scale="${escapeHtml(Number.isFinite(prop.scale) ? prop.scale : 1)}" alt="">` : ""}
      </span>
    </button>
    <span class="room-picker-label" aria-hidden="true">${escapeHtml(prop.label)}</span>
  </div>`;
}

function cardMarkup(stack, selection) {
  const selected = selection?.kind === "room-card" && selection.id === stack.stackId;
  const tile = tileMarkup(stack.definition, stack, selected, "room")
    .replace("<img ", '<span class="room-picker-fallback" aria-hidden="true">▧</span><img ');
  return `<div class="room-picker-entry" role="listitem">${tile}
    <span class="room-picker-label" aria-hidden="true">${escapeHtml(stack.definition.label)}</span>
  </div>`;
}

/** Pure markup builder; callers only need to render it while the picker is open. */
export function roomPickerMarkup(state) {
  const props = (state.room?.props || []).filter(hasActivePropActions);
  const cards = state.room?.roomCards || [];
  return `<header class="room-picker-header">
      <h2 id="room-picker-title">${escapeHtml(state.room?.label || "Look around")}</h2>
      <button type="button" class="room-picker-close quiet" data-room-picker-close aria-label="Close room picker">×</button>
    </header>
    <div class="room-picker-track">
      <div class="room-picker-grid" role="list" aria-label="Props and cards">${props.length || cards.length
        ? [...props.map(prop => propMarkup(prop, state.selection)), ...cards.map(stack => cardMarkup(stack, state.selection))].join("")
        : '<p class="room-picker-empty">Nothing to interact with here.</p>'}</div>
    </div>`;
}

/** The parent owns state subscription, Escape priority, and the toolbar markup. */
export function createRoomPicker({ root, store, onSelect, thumbnails }) {
  const document = root.ownerDocument;
  let markup = "";
  const trigger = () => document.querySelector("#core-tools #room-picker-toggle");
  const isOpen = () => Boolean(store.getState().room && store.getState().ui.roomPickerOpen);
  const itemButtons = () => [...root.querySelectorAll("[data-room-picker-prop], [data-stack-id]")];
  const identity = button => button?.hasAttribute("data-room-picker-prop")
    ? `prop:${button.dataset.roomPickerProp}`
    : button?.hasAttribute("data-stack-id") ? `card:${button.dataset.stackId}` : "close";

  root.classList.add("room-picker");
  root.setAttribute("role", "dialog");
  root.setAttribute("aria-modal", "false");
  root.setAttribute("aria-labelledby", "room-picker-title");
  root.tabIndex = -1;

  function focusTrigger() {
    trigger()?.focus({ preventScroll: true });
  }

  function close({ restoreFocus = false } = {}) {
    store.dispatch({ type: "close-room-picker" });
    if (restoreFocus) focusTrigger();
  }

  function sync(state) {
    const open = Boolean(state.room && state.ui.roomPickerOpen);
    if (root.hidden !== !open) root.hidden = !open;
    if (root.hasAttribute("inert") !== !open) root.toggleAttribute("inert", !open);
    if (root.getAttribute("aria-hidden") !== String(!open)) root.setAttribute("aria-hidden", String(!open));
    const toggle = trigger();
    if (toggle) {
      if (toggle.getAttribute("aria-expanded") !== String(open)) toggle.setAttribute("aria-expanded", String(open));
      if (toggle.disabled !== !state.room) toggle.disabled = !state.room;
    }
    if (!open) {
      if (markup) root.replaceChildren();
      markup = "";
      return;
    }
    const next = roomPickerMarkup(state);
    if (markup === next) return;
    const active = root.contains(document.activeElement) ? document.activeElement : null;
    const key = active ? identity(active) : null;
    const oldButtons = itemButtons();
    const index = oldButtons.indexOf(active);
    const track = root.querySelector(".room-picker-track");
    const scroll = { top: track?.scrollTop || 0, left: track?.scrollLeft || 0 };
    root.innerHTML = next;
    markup = next;
    if (active) {
      const buttons = itemButtons();
      const restored = [...buttons, root.querySelector("[data-room-picker-close]")]
        .find(button => identity(button) === key);
      (restored || buttons[Math.min(Math.max(index, 0), buttons.length - 1)] || root)
        .focus({ preventScroll: true });
    }
    const newTrack = root.querySelector(".room-picker-track");
    newTrack.scrollTop = scroll.top;
    newTrack.scrollLeft = scroll.left;
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
    if (event.target.closest("[data-room-picker-close]")) {
      close({ restoreFocus: true });
      return;
    }
    const button = event.target.closest("[data-room-picker-prop], [data-stack-id]");
    if (!button || !root.contains(button)) return;
    const selection = button.hasAttribute("data-room-picker-prop")
      ? { kind: "prop", id: button.dataset.roomPickerProp }
      : { kind: "room-card", id: button.dataset.stackId };
    close();
    onSelect(selection);
    if (!store.getState().views?.details
        && (document.activeElement === document.body || document.activeElement === button
          || document.activeElement === trigger())) focusTrigger();
  });

  document.addEventListener("click", event => {
    const toggle = event.target.closest?.("#core-tools #room-picker-toggle");
    if (!toggle || toggle.disabled) return;
    store.dispatch({ type: "toggle-room-picker" });
    if (isOpen()) queueMicrotask(() => {
      if (isOpen()) (itemButtons()[0] || root.querySelector("[data-room-picker-close]") || root).focus();
    });
  });
  document.addEventListener("pointerdown", event => {
    if (isOpen() && !root.contains(event.target) && !trigger()?.contains(event.target)) close();
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
