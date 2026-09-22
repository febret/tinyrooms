import { escapeHtml, updateMarkup } from "./presentation.js";

/** Render room-granularity peep standees and anchored, dismissible chat bubbles. */
export function createPeepsView({ panel, bubbleLayer, onSelect, onDismiss, onSound }) {
  let expanded = false;
  let latest = null;
  const bubbles = new Map();
  const dismissing = new Set();

  function positionBubbles() {
    const bounds = panel.getBoundingClientRect();
    for (const [id, bubble] of bubbles) {
      const marker = [...panel.querySelectorAll("[data-peep-id]")].find(node => node.dataset.peepId === id);
      if (!marker) { bubble.hidden = true; continue; }
      const rect = marker.getBoundingClientRect();
      const visible = rect.bottom > bounds.top && rect.top < bounds.bottom;
      bubble.hidden = !visible;
      if (!visible) continue;
      bubble.style.left = `${Math.min(bounds.right + 2, window.innerWidth - bubble.offsetWidth - 8)}px`;
      bubble.style.top = `${Math.max(8, Math.min(rect.top + 4, bounds.bottom - bubble.offsetHeight))}px`;
    }
  }

  function render(state) {
    latest = state;
    const peeps = state.room ? [...state.room.occupants, ...state.room.npcs] : [];
    const pinned = new Set(state.user?.pinnedPeeps || []);
    const self = peeps.filter(peep => peep.id === state.user?.id);
    const others = peeps.filter(peep => peep.id !== state.user?.id);
    const pinnedOthers = others.filter(peep => pinned.has(peep.id));
    const unpinnedOthers = others.filter(peep => !pinned.has(peep.id));
    const shownUnpinned = expanded ? unpinnedOthers : unpinnedOthers.slice(0, 4);
    const shown = [...self, ...pinnedOthers, ...shownUnpinned];
    const definitions = state.user?.statusDefinitions || {};
    const markup = `<div class="peep-list">${shown.map(peep => {
      const statuses = peep.statuses || [];
      const tired = statuses.includes("tired");
      return `
      <article class="peep-chip ${peep.id === state.user?.id ? "self" : ""} ${pinned.has(peep.id) ? "pinned" : ""} ${tired ? "tired" : ""} ${state.selection.kind === "peep" && state.selection.id === peep.id ? "selected" : ""}">
        <button type="button" class="peep-main" data-peep-id="${escapeHtml(peep.id)}" data-focus-key="${escapeHtml(peep.id)}" aria-label="Select ${escapeHtml(peep.label)}" aria-pressed="${state.selection.kind === "peep" && state.selection.id === peep.id}">
          <span class="peep-marker"><img src="${escapeHtml(peep.stickerUrl || "/assets/stickers/s1.png")}" alt=""></span>
          <span class="peep-name">${escapeHtml(peep.label)}${peep.id === state.user?.id ? " (You)" : ""}</span>
          ${statuses.length ? `<span class="peep-statuses">${statuses.map(id => {
            const definition = definitions[id];
            return `<span class="status-icon" title="${escapeHtml(definition?.label || id)}">${escapeHtml(definition?.icon || "•")}</span>`;
          }).join("")}</span>` : ""}
        </button>
      </article>`;
    }).join("")}</div>
      ${unpinnedOthers.length > 4 ? `<button type="button" class="quiet peeps-toggle" aria-expanded="${expanded}">${expanded ? "Show fewer" : `+${unpinnedOthers.length - 4} peeps`}</button>` : ""}`;
    if (updateMarkup(panel, markup)) {
      panel.querySelectorAll("[data-peep-id]").forEach(button => {
        button.onclick = () => { onSelect({ kind: "peep", id: button.dataset.peepId }); onSound(); };
      });
      const toggle = panel.querySelector(".peeps-toggle");
      if (toggle) toggle.onclick = () => { expanded = !expanded; render(latest); };
    }
    const visibleIds = new Set();
    for (const peep of shown) {
      if (!peep.bubble || peep.bubbleDismissed) continue;
      visibleIds.add(peep.id);
      let bubble = bubbles.get(peep.id);
      if (!bubble) {
        bubble = document.createElement("button");
        bubble.type = "button";
        const text = document.createElement("span");
        text.className = "bubble-text";
        bubble.append(text);
        bubble.dataset.bubbleId = peep.id;
        bubbleLayer.append(bubble);
        bubbles.set(peep.id, bubble);
        bubble.onclick = () => {
          if (dismissing.has(peep.id)) return;
          dismissing.add(peep.id);
          const dismissedText = bubble.textContent;
          bubble.classList.add("dismissing");
          setTimeout(() => {
            dismissing.delete(peep.id);
            const current = [...(latest.room?.occupants || []), ...(latest.room?.npcs || [])].find(item => item.id === peep.id);
            if (current?.bubble?.text === dismissedText) onDismiss(peep.id);
            else render(latest);
          }, state.ui.reducedMotion ? 0 : 180);
        };
      }
      const style = peep.bubble.style === "thinking" ? "thought" : peep.bubble.style === "spiky" ? "spiky" : "speech";
      bubble.className = `bubble ${style} ${peep.bubble.text.length > 75 ? "long" : ""} ${dismissing.has(peep.id) ? "dismissing" : ""}`;
      bubble.querySelector(".bubble-text").textContent = peep.bubble.text;
      bubble.setAttribute("aria-label", `${peep.label}: ${peep.bubble.text}. Dismiss message`);
    }
    for (const [id, bubble] of bubbles) {
      if (!visibleIds.has(id)) { bubble.remove(); bubbles.delete(id); dismissing.delete(id); }
    }
    positionBubbles();
  }
  panel.addEventListener("scroll", positionBubbles, { passive: true });
  new ResizeObserver(positionBubbles).observe(panel);
  window.addEventListener("resize", positionBubbles);
  return { render };
}
