import { peepDamageTier } from "./peep-damage.js";
import { withBase } from "../base-path.js";
import { layoutPeeps } from "./peep-groups.js";
import { createBubbleElement, createPeepBubbles } from "./peep-bubbles.js";
import { escapeHtml, placeAt, updateMarkup } from "../presentation.js";
import { decalDataUrl, stinkDataUrl } from "../decals.js";
import { powerGlowStyle } from "../power-glow.js";

const MOVE_BUBBLE_LIFETIME = 5000;
const MOVE_RECORD_TTL = 10000;

function lowerFirst(text) {
  const value = String(text || "");
  return value ? value.charAt(0).toLowerCase() + value.slice(1) : value;
}

function peepSticker(peep) {
  return escapeHtml(peep.stickerUrl || withBase("/assets/stickers/s1.png"));
}

function groupMarkup(grouped) {
  if (!grouped.length) return "";
  const minis = grouped.slice(0, 4).map(peep => `<img src="${peepSticker(peep)}" alt="" draggable="false">`).join("");
  const label = grouped.length === 1 ? "1 more peep" : `${grouped.length} more peeps`;
  return `
      <article class="peep-chip peep-group-chip">
        <button type="button" class="peep-main peep-group" data-peep-group aria-label="Show ${label}" aria-expanded="false" title="Show ${label}">
          <span class="peep-group-grid" aria-hidden="true">${minis}<span class="peep-group-count">+${grouped.length}</span></span>
        </button>
      </article>`;
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
  let prevOrder = null;
  let prevRoomId = null;
  const pendingMoves = [];
  const moveBubbles = new Set();
  const ghosts = new Set();
  const peepBubbles = createPeepBubbles({ panel, bubbleLayer, onDismiss });

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
    placeAt(ghost, `${first.left}px`, `${first.top}px`);
    ghost.style.width = `${first.width}px`;
    ghost.style.height = `${first.height}px`;
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
    const bubble = createBubbleElement(bubbleLayer, {
      tag: "button",
      className: "bubble move",
      text: record.text,
    });
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
    const peepId = String(event?.peep_id || event?.account_id || "");
    if (!peepId || peepId === latest.user.id) return;
    const kind = String(event.type || "").endsWith("leave") ? "leave" : "enter";
    const label = String(event.label || event.username || "Peep");
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
      peepId,
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
      expanded = false;
      clearMoves();
      prevIds = null;
      prevOrder = null;
    }
    prevRoomId = roomId;
    const peeps = state.room ? [...state.room.occupants, ...state.room.npcs] : [];
    const pinned = new Set(state.user?.pinnedPeeps || []);
    const layout = layoutPeeps(peeps, {
      selfId: state.user?.id || "",
      pinned,
      expanded,
      dialogId: state.room?.dialog?.peepId || "",
    });
    const shown = layout.visible;
    const markup = `<div class="peep-list">${shown.map(peep => {
      const statuses = peep.statuses || [];
      const tired = statuses.includes("tired");
      const stinky = statuses.includes("stinky");
      const damage = peepDamage(peep, state);
      const decals = Array.isArray(peep.decals) ? peep.decals : (peep.counters?.decals || []);
      const decalUrl = decalDataUrl(peep.id, decals);
      const stinkUrl = stinky ? stinkDataUrl(peep.id) : "";
      const glowStyle = powerGlowStyle(peep.powers || []);
      return `
      <article class="peep-chip ${peep.id === state.user?.id ? "self" : ""} ${pinned.has(peep.id) ? "pinned" : ""} ${tired ? "tired" : ""} ${state.selection.kind === "peep" && state.selection.id === peep.id ? "selected" : ""}">
        <button type="button" class="peep-main" data-peep-id="${escapeHtml(peep.id)}" data-focus-key="${escapeHtml(peep.id)}" aria-label="Select ${escapeHtml(peep.label)}" title="${escapeHtml(peep.label)}" aria-pressed="${state.selection.kind === "peep" && state.selection.id === peep.id}">
          ${pinned.has(peep.id) ? '<span class="peep-pin" aria-hidden="true">◆</span>' : ""}
          <span class="peep-marker" data-damage="${damage}"${stinky ? ' data-stinky="1"' : ""}><span class="peep-aura" style="${glowStyle}" aria-hidden="true"></span><img src="${peepSticker(peep)}" alt="">${decalUrl ? `<img class="peep-decals" src="${decalUrl}" alt="" aria-hidden="true">` : ""}${stinkUrl ? `<img class="peep-stink" src="${stinkUrl}" alt="" aria-hidden="true">` : ""}<span class="peep-damage wear" aria-hidden="true"></span><span class="peep-damage gashes" aria-hidden="true"></span></span>
          ${peep.audioEnabled ? `<span class="peep-audio" role="img" aria-label="Audio chat on" title="Audio chat on">&#128266;</span>` : ""}
        </button>
      </article>`;
    }).join("")}${groupMarkup(layout.grouped)}</div>
      ${expanded && layout.canCollapse ? `<button type="button" class="quiet peeps-toggle" aria-expanded="true">Show fewer</button>` : ""}`;
    // The FLIP animation only means anything when the list actually reordered or
    // someone is arriving or leaving. Measuring every chip's rect before and
    // after the write forced two synchronous layouts per chip on every socket
    // message, including the many messages that change nothing about the list.
    const currentOrder = shown.map(peep => peep.id);
    const orderChanged = !prevOrder || currentOrder.length !== prevOrder.length
      || currentOrder.some((id, index) => prevOrder[index] !== id);
    const animating = orderChanged || pendingMoves.length > 0;
    const firstRects = prevOrder && animating
      ? captureRects(!state.ui.reducedMotion && pendingMoves.some(record => record.kind === "leave"))
      : null;
    if (updateMarkup(panel, markup)) {
      panel.querySelectorAll("[data-peep-id]").forEach(button => {
        button.onclick = () => { onSelect({ kind: "peep", id: button.dataset.peepId }); onSound(); };
      });
      const group = panel.querySelector("[data-peep-group]");
      if (group) group.onclick = () => { expanded = true; onSound(); render(latest); };
      const toggle = panel.querySelector(".peeps-toggle");
      if (toggle) toggle.onclick = () => { expanded = false; onSound(); render(latest); };
    }
    const currentIds = new Set(currentOrder);
    if (firstRects && panel.querySelector(".peep-list")) {
      if (!state.ui.reducedMotion) runFlip(firstRects);
      processMoves(currentIds, firstRects, state.ui.reducedMotion);
    }
    prevOrder = currentOrder;
    prevIds = currentIds;
    peepBubbles.render(state, shown);
  }

  function setSpriteAnchors(anchors) {
    peepBubbles.setSpriteAnchors(anchors);
  }

  function destroy() {
    peepBubbles.destroy();
    for (const bubble of moveBubbles) { clearTimeout(bubble._moveTimer); bubble.remove(); }
    moveBubbles.clear();
    for (const ghost of ghosts) ghost.remove();
    ghosts.clear();
  }

  return {
    render,
    noteMove,
    setSpriteAnchors,
    destroy,
    hasBubbles: () => peepBubbles.hasBubbles(),
  };
}
