import { peepDamageTier } from "./peep-damage.js";
import { escapeHtml, updateMarkup } from "./presentation.js";
import { statusIconMarkup } from "./views/view-helpers.js";

const MOVE_BUBBLE_LIFETIME = 5000;
const MOVE_RECORD_TTL = 10000;

function bubbleKey(peep) {
  const bubble = peep?.bubble;
  return bubble ? `${bubble.text || ""}\u0000${bubble.imageUrl || ""}` : "";
}

function lowerFirst(text) {
  const value = String(text || "");
  return value ? value.charAt(0).toLowerCase() + value.slice(1) : value;
}

function peepDamage(peep, state) {
  const counters = peep.counters || (peep.id === state.user?.id ? state.user?.counters : null);
  return peepDamageTier(counters);
}

/** Render room-granularity peep standees and anchored, dismissible chat bubbles. */
export function createPeepsView({ panel, bubbleLayer, onSelect, onDismiss, onMove, onSound }) {
  let expanded = false;
  let latest = null;
  let prevIds = null;
  let prevRoomId = null;
  const bubbles = new Map();
  const dismissing = new Set();
  const pendingMoves = [];
  const moveBubbles = new Set();
  const ghosts = new Set();

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

  function captureRects(includeClone) {
    const map = new Map();
    for (const chip of panel.querySelectorAll(".peep-chip")) {
      const id = chip.querySelector("[data-peep-id]")?.dataset.peepId;
      if (!id) continue;
      const rect = chip.getBoundingClientRect();
      map.set(id, {
        top: rect.top,
        left: rect.left,
        width: rect.width,
        height: rect.height,
        clone: includeClone ? chip.cloneNode(true) : null,
      });
    }
    return map;
  }

  function chipFor(id) {
    return [...panel.querySelectorAll(".peep-chip")].find(chip => chip.querySelector("[data-peep-id]")?.dataset.peepId === id) || null;
  }

  function runFlip(firstRects) {
    for (const chip of panel.querySelectorAll(".peep-chip")) {
      const id = chip.querySelector("[data-peep-id]")?.dataset.peepId;
      const first = id ? firstRects.get(id) : null;
      if (!first) continue;
      const last = chip.getBoundingClientRect();
      const dx = first.left - last.left;
      const dy = first.top - last.top;
      if (Math.abs(dx) < 1 && Math.abs(dy) < 1) continue;
      chip.style.transition = "none";
      chip.style.transform = `translate(${dx}px, ${dy}px)`;
      requestAnimationFrame(() => {
        chip.style.transition = "transform .28s ease";
        chip.style.transform = "";
        chip.addEventListener("transitionend", () => { chip.style.transition = ""; chip.style.transform = ""; }, { once: true });
      });
    }
  }

  function animateDeparture(first) {
    if (!first?.clone) return;
    const ghost = first.clone;
    ghost.classList.add("peep-ghost");
    ghost.classList.remove("self", "selected", "pinned");
    ghost.style.position = "fixed";
    ghost.style.left = `${first.left}px`;
    ghost.style.top = `${first.top}px`;
    ghost.style.width = `${first.width}px`;
    ghost.style.height = `${first.height}px`;
    ghost.style.margin = "0";
    ghost.style.pointerEvents = "none";
    ghost.style.zIndex = "48";
    bubbleLayer.append(ghost);
    ghosts.add(ghost);
    requestAnimationFrame(() => {
      ghost.style.transition = "transform .5s ease-in, opacity .5s ease-in";
      ghost.style.transform = `translateX(${-(first.left + first.width + 60)}px)`;
      ghost.style.opacity = "0";
    });
    const remove = () => { ghosts.delete(ghost); ghost.remove(); };
    ghost.addEventListener("transitionend", remove, { once: true });
    setTimeout(remove, 800);
  }

  function animateArrival(chip) {
    const rect = chip.getBoundingClientRect();
    chip.style.transition = "none";
    chip.style.transform = `translateX(${-(rect.left + rect.width + 60)}px)`;
    chip.style.opacity = "0";
    requestAnimationFrame(() => {
      chip.style.transition = "transform .4s ease-out, opacity .4s ease-out";
      chip.style.transform = "";
      chip.style.opacity = "";
      chip.addEventListener("transitionend", () => { chip.style.transition = ""; chip.style.transform = ""; chip.style.opacity = ""; }, { once: true });
    });
  }

  function dismissMoveBubble(bubble) {
    clearTimeout(bubble._moveTimer);
    if (!moveBubbles.has(bubble)) return;
    moveBubbles.delete(bubble);
    bubble.classList.add("dismissing");
    const remove = () => bubble.remove();
    bubble.addEventListener("animationend", remove, { once: true });
    setTimeout(remove, 320);
  }

  function showMoveBubble(record, rect) {
    const bubble = document.createElement("button");
    bubble.type = "button";
    bubble.className = "bubble move";
    const text = document.createElement("span");
    text.className = "bubble-text";
    text.textContent = record.text;
    bubble.append(text);
    const top = Math.max(8, Math.min(rect.top + 4, panel.getBoundingClientRect().bottom - 40));
    bubble.style.top = `${top}px`;
    bubble.style.left = `${panel.getBoundingClientRect().right + 2}px`;
    if (record.command) {
      bubble.classList.add("actionable");
      bubble.onclick = () => { dismissMoveBubble(bubble); onSound(); onMove(record.command); };
      bubble.setAttribute("aria-label", `${record.text}. Move this way`);
    } else {
      bubble.setAttribute("aria-label", record.text);
      bubble.onclick = () => dismissMoveBubble(bubble);
    }
    bubbleLayer.append(bubble);
    moveBubbles.add(bubble);
    bubble.style.left = `${Math.min(panel.getBoundingClientRect().right + 2, window.innerWidth - bubble.offsetWidth - 8)}px`;
    bubble._moveTimer = setTimeout(() => dismissMoveBubble(bubble), latest?.ui?.reducedMotion ? MOVE_BUBBLE_LIFETIME + 2000 : MOVE_BUBBLE_LIFETIME);
  }

  function clearMoves() {
    for (const bubble of moveBubbles) { clearTimeout(bubble._moveTimer); bubble.remove(); }
    moveBubbles.clear();
    for (const ghost of ghosts) ghost.remove();
    ghosts.clear();
    pendingMoves.length = 0;
  }

  function noteMove(event) {
    if (!latest?.user || !latest.room) return;
    const accountId = String(event?.account_id || "");
    if (!accountId || accountId === latest.user.id) return;
    const kind = event.type === "presence.leave" ? "leave" : "enter";
    const label = String(event.username || "Peep");
    const otherRoomId = kind === "leave"
      ? String(event.destination_room_id || "")
      : String(event.source_room_id || "");
    const exit = otherRoomId ? (latest.room.exits || []).find(item => item.targetRoomId === otherRoomId) : null;
    const direction = kind === "leave"
      ? String(event.direction || exit?.label || "").trim()
      : String(event.source_room_label || "").trim();
    const text = kind === "leave"
      ? (direction ? `${label} went ${lowerFirst(direction)}` : `${label} left`)
      : (direction ? `${label} came from ${direction}` : `${label} arrived`);
    pendingMoves.push({
      peepId: accountId,
      kind,
      text,
      command: exit ? `.go ${exit.id}` : "",
      createdAt: Date.now(),
    });
    if (pendingMoves.length > 12) pendingMoves.shift();
  }

  function processMoves(currentIds, firstRects, reducedMotion) {
    const enteredIds = new Set([...currentIds].filter(id => !prevIds.has(id)));
    const leftIds = new Set([...prevIds].filter(id => !currentIds.has(id)));
    const now = Date.now();
    const remaining = [];
    for (const record of pendingMoves) {
      if (record.kind === "leave" && leftIds.has(record.peepId)) {
        const first = firstRects.get(record.peepId);
        if (first && !reducedMotion) animateDeparture(first);
        showMoveBubble(record, first || { top: panel.getBoundingClientRect().top + 40 });
      } else if (record.kind === "enter" && enteredIds.has(record.peepId)) {
        const chip = chipFor(record.peepId);
        const rect = chip ? chip.getBoundingClientRect() : { top: panel.getBoundingClientRect().top + 40 };
        if (chip && !reducedMotion) animateArrival(chip);
        showMoveBubble(record, rect);
      } else if (now - record.createdAt <= MOVE_RECORD_TTL) {
        remaining.push(record);
      }
    }
    pendingMoves.length = 0;
    pendingMoves.push(...remaining);
  }

  function render(state) {
    latest = state;
    const roomId = state.room?.id || "";
    if (prevRoomId !== null && roomId !== prevRoomId) {
      clearMoves();
      prevIds = null;
    }
    prevRoomId = roomId;
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
      const damage = peepDamage(peep, state);
      return `
      <article class="peep-chip ${peep.id === state.user?.id ? "self" : ""} ${pinned.has(peep.id) ? "pinned" : ""} ${tired ? "tired" : ""} ${state.selection.kind === "peep" && state.selection.id === peep.id ? "selected" : ""}">
        <button type="button" class="peep-main" data-peep-id="${escapeHtml(peep.id)}" data-focus-key="${escapeHtml(peep.id)}" aria-label="Select ${escapeHtml(peep.label)}" aria-pressed="${state.selection.kind === "peep" && state.selection.id === peep.id}">
          <span class="peep-marker" data-damage="${damage}"><img src="${escapeHtml(peep.stickerUrl || "/assets/stickers/s1.png")}" alt=""><span class="peep-damage wear" aria-hidden="true"></span><span class="peep-damage gashes" aria-hidden="true"></span></span>
          <span class="peep-name">${escapeHtml(peep.label)}${peep.id === state.user?.id ? " (You)" : ""}</span>
          ${peep.audioEnabled ? `<span class="peep-audio" role="img" aria-label="Audio chat on" title="Audio chat on">&#128266;</span>` : ""}
          ${statuses.length ? `<span class="peep-statuses">${statusIconMarkup(statuses, definitions)}</span>` : ""}
        </button>
      </article>`;
    }).join("")}</div>
      ${unpinnedOthers.length > 4 ? `<button type="button" class="quiet peeps-toggle" aria-expanded="${expanded}">${expanded ? "Show fewer" : `+${unpinnedOthers.length - 4} peeps`}</button>` : ""}`;
    const firstRects = prevIds
      ? captureRects(!state.ui.reducedMotion && pendingMoves.some(record => record.kind === "leave"))
      : null;
    if (updateMarkup(panel, markup)) {
      panel.querySelectorAll("[data-peep-id]").forEach(button => {
        button.onclick = () => { onSelect({ kind: "peep", id: button.dataset.peepId }); onSound(); };
      });
      const toggle = panel.querySelector(".peeps-toggle");
      if (toggle) toggle.onclick = () => { expanded = !expanded; render(latest); };
    }
    const currentIds = new Set(shown.map(peep => peep.id));
    if (prevIds && firstRects && panel.querySelector(".peep-list")) {
      if (!state.ui.reducedMotion) runFlip(firstRects);
      processMoves(currentIds, firstRects, state.ui.reducedMotion);
    }
    prevIds = currentIds;
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
          const dismissedKey = bubble.dataset.bubbleKey;
          bubble.classList.add("dismissing");
          setTimeout(() => {
            dismissing.delete(peep.id);
            const current = [...(latest.room?.occupants || []), ...(latest.room?.npcs || [])].find(item => item.id === peep.id);
            if (bubbleKey(current) === dismissedKey) onDismiss(peep.id);
            else render(latest);
          }, state.ui.reducedMotion ? 0 : 180);
        };
      }
      const style = peep.bubble.style === "thinking" ? "thought" : peep.bubble.style === "spiky" ? "spiky" : "speech";
      const hasImage = Boolean(peep.bubble.imageUrl);
      const nextKey = bubbleKey(peep);
      const bubbleChanged = bubble.dataset.bubbleKey !== nextKey;
      let image = bubble.querySelector(".bubble-image");
      if (hasImage && !image) {
        image = document.createElement("img");
        image.className = "bubble-image";
        image.alt = "";
        image.draggable = false;
        bubble.append(image);
      } else if (!hasImage && image) {
        image.remove();
        image = null;
      }
      bubble.dataset.bubbleKey = nextKey;
      const emoteClass = hasImage ? ` emote emote-${peep.bubble.style}` : "";
      bubble.className = `bubble ${style}${emoteClass} ${peep.bubble.text.length > 75 ? "long" : ""} ${dismissing.has(peep.id) ? "dismissing" : ""}`;
      bubble.querySelector(".bubble-text").textContent = hasImage ? "" : peep.bubble.text;
      if (image) image.src = peep.bubble.imageUrl;
      if (hasImage && bubbleChanged) {
        bubble.style.animation = "none";
        void bubble.offsetWidth;
        bubble.style.animation = "";
      }
      bubble.setAttribute("aria-label", `${peep.label}: ${hasImage ? `${peep.bubble.text} emote` : peep.bubble.text}. Dismiss message`);
    }
    for (const [id, bubble] of bubbles) {
      if (!visibleIds.has(id)) { bubble.remove(); bubbles.delete(id); dismissing.delete(id); }
    }
    positionBubbles();
  }
  panel.addEventListener("scroll", positionBubbles, { passive: true });
  new ResizeObserver(positionBubbles).observe(panel);
  window.addEventListener("resize", positionBubbles);
  return { render, noteMove };
}
