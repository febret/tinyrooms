import { placeAt } from "./presentation.js";

function bubbleKey(peep) {
  const bubble = peep?.bubble;
  return bubble ? `${bubble.text || ""}\u0000${bubble.imageUrl || ""}` : "";
}

export function createBubbleElement(bubbleLayer, {
  tag = "div",
  className = "bubble",
  text = "",
  role = "",
} = {}) {
  const bubble = document.createElement(tag);
  if (tag === "button") bubble.type = "button";
  bubble.className = className;
  if (role) bubble.setAttribute("role", role);
  const label = document.createElement("span");
  label.className = "bubble-text";
  label.textContent = text;
  bubble.append(label);
  bubbleLayer.append(bubble);
  return bubble;
}

/** Own chat and dialog bubble state, placement, and lifecycle. */
export function createPeepBubbles({ panel, bubbleLayer, onDismiss }) {
  let latest = null;
  let latestShown = [];
  let spriteAnchors = new Map();
  const chatBubbles = new Map();
  const dismissing = new Set();
  const bubbleSizes = new Map();
  let dialogBubble = null;
  let dialogPeepId = "";

  function isSpritePeep(peep) {
    return Boolean(latest?.room?.board?.spritesEnabled && Array.isArray(peep?.spritePosition));
  }

  function roomPeep(peepId) {
    return [...(latest?.room?.occupants || []), ...(latest?.room?.npcs || [])]
      .find(peep => peep.id === peepId) || null;
  }

  function measureBubble(bubble) {
    let size = bubbleSizes.get(bubble);
    if (!size) {
      size = { width: bubble.offsetWidth, height: bubble.offsetHeight };
      bubbleSizes.set(bubble, size);
    }
    return size;
  }

  function hideBubble(bubble) {
    if (!bubble.hidden) bubble.hidden = true;
    bubbleSizes.delete(bubble);
  }

  function setBubbleText(bubble, text) {
    const node = bubble.querySelector(".bubble-text");
    if (!node || node.textContent === text) return;
    node.textContent = text;
    bubbleSizes.delete(bubble);
  }

  function setBubbleClass(bubble, className, { preserveSide = false } = {}) {
    const side = preserveSide && bubble.classList.contains("side");
    const next = side ? `${className} side` : className;
    if (bubble.className === next) return;
    bubble.className = next;
    bubbleSizes.delete(bubble);
  }

  function setBubbleLabel(bubble, label) {
    if (bubble.getAttribute("aria-label") !== label) bubble.setAttribute("aria-label", label);
  }

  function placeChatBubble(item, bounds) {
    const { rect, size } = item;
    const left = Math.min(bounds.right + 2, window.innerWidth - size.width - 8);
    const top = Math.max(8, Math.min(rect.top + 4, bounds.bottom - size.height));
    placeAt(item.bubble, `${left}px`, `${top}px`);
  }

  function placeDialogBubble(item) {
    const { bubble } = item;
    const { rect, size, bounds } = item;
    const minTop = Math.max(8, bounds.top - 8);
    const above = rect.top - size.height - 10;
    if (above < minTop) {
      bubble.classList.add("side");
      bubble.style.removeProperty("--bubble-arrow-left");
      const left = Math.min(bounds.right + 4, window.innerWidth - size.width - 8);
      const top = Math.max(minTop, Math.min(rect.top + 4, bounds.bottom - size.height));
      placeAt(bubble, `${left}px`, `${top}px`);
      return;
    }
    bubble.classList.remove("side");
    const markerCenter = rect.left + rect.width / 2;
    const minCenter = size.width / 2 + 8;
    const maxCenter = Math.max(minCenter, window.innerWidth - size.width / 2 - 8);
    const center = Math.min(Math.max(markerCenter, minCenter), maxCenter);
    const left = center - size.width / 2;
    const arrowLeft = Math.min(Math.max(markerCenter - left, 18), Math.max(18, size.width - 18));
    bubble.style.setProperty("--bubble-arrow-left", `${arrowLeft}px`);
    placeAt(bubble, `${left}px`, `${above}px`);
  }

  function measureTarget(target, context) {
    const { spriteMode, markers, boardSprites, bounds } = context;
    if (spriteMode) {
      const anchor = boardSprites?.get(target.peepId);
      if (!anchor) return { ...target, visible: false };
      return { ...target, visible: true, anchor, size: measureBubble(target.bubble), sprite: true };
    }
    const rect = markers.get(target.peepId)?.getBoundingClientRect();
    if (!rect || rect.bottom <= bounds.top || rect.top >= bounds.bottom) {
      return { ...target, visible: false };
    }
    return { ...target, visible: true, rect, size: measureBubble(target.bubble), bounds };
  }

  function position() {
    const spriteMode = Boolean(latest?.room?.board?.spritesEnabled);
    const markers = new Map();
    if (!spriteMode) {
      for (const node of panel.querySelectorAll("[data-peep-id]")) {
        markers.set(node.dataset.peepId, node);
      }
    }
    const boardSprites = spriteMode ? spriteAnchors : null;
    const targets = [];
    if (dialogBubble && dialogPeepId) {
      targets.push({ bubble: dialogBubble, peepId: dialogPeepId, placement: "dialog" });
    }
    for (const [peepId, bubble] of chatBubbles) {
      targets.push({ bubble, peepId, placement: "chat" });
    }
    if (!targets.length) return;
    if (!markers.size && !boardSprites?.size) {
      for (const target of targets) hideBubble(target.bubble);
      return;
    }
    const bounds = panel.getBoundingClientRect();
    const context = { spriteMode, markers, boardSprites, bounds };
    const measurements = targets.map(target => measureTarget(target, context));
    for (const item of measurements) {
      if (!item.visible) {
        hideBubble(item.bubble);
        continue;
      }
      if (item.bubble.hidden) item.bubble.hidden = false;
      if (item.sprite) {
        item.bubble.classList.remove("side");
        item.bubble.style.setProperty("--bubble-scale", item.anchor.scale.toFixed(3));
        item.bubble.style.removeProperty("--bubble-arrow-left");
        placeAt(item.bubble, `${item.anchor.x}px`, `${item.anchor.y}px`);
        continue;
      }
      item.bubble.style.removeProperty("--bubble-scale");
      if (item.placement === "dialog") placeDialogBubble(item);
      else placeChatBubble(item, bounds);
    }
  }

  function removeDialogBubble() {
    if (!dialogBubble) return;
    bubbleSizes.delete(dialogBubble);
    dialogBubble.remove();
    dialogBubble = null;
    dialogPeepId = "";
  }

  function syncDialogBubble(dialog, shownPeeps) {
    const peep = dialog ? shownPeeps.find(candidate => candidate.id === dialog.peepId) : null;
    if (!dialog || !peep) {
      removeDialogBubble();
      return;
    }
    if (!dialogBubble) {
      dialogBubble = createBubbleElement(bubbleLayer, {
        className: "bubble dialog-bubble",
        role: "status",
      });
    }
    dialogPeepId = peep.id;
    setBubbleText(dialogBubble, dialog.text || "");
    setBubbleClass(
      dialogBubble,
      `bubble dialog-bubble${isSpritePeep(peep) ? " sprite-bubble" : ""}`,
      { preserveSide: true },
    );
    setBubbleLabel(dialogBubble, `${peep.label}: ${dialog.text || ""}. Conversation`);
  }

  function dismissChatBubble(peepId, bubble) {
    if (dismissing.has(peepId)) return;
    dismissing.add(peepId);
    const dismissedKey = bubble.dataset.bubbleKey;
    bubble.classList.add("dismissing");
    setTimeout(() => {
      dismissing.delete(peepId);
      if (bubbleKey(roomPeep(peepId)) === dismissedKey) onDismiss(peepId);
      else render(latest, latestShown);
    }, latest?.ui?.reducedMotion ? 0 : 180);
  }

  function createChatBubble(peep) {
    const bubble = createBubbleElement(bubbleLayer, { tag: "button" });
    bubble.dataset.bubbleId = peep.id;
    bubble.onclick = () => dismissChatBubble(peep.id, bubble);
    chatBubbles.set(peep.id, bubble);
    return bubble;
  }

  function syncChatBubble(bubble, peep) {
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
    const className = `bubble ${style}${emoteClass} ${peep.bubble.text.length > 75 ? "long" : ""} ${isSpritePeep(peep) ? "sprite-bubble" : ""} ${dismissing.has(peep.id) ? "dismissing" : ""}`;
    setBubbleClass(bubble, className);
    setBubbleText(bubble, hasImage ? "" : peep.bubble.text);
    if (image && image.getAttribute("src") !== peep.bubble.imageUrl) image.src = peep.bubble.imageUrl;
    if (hasImage && bubbleChanged) {
      bubble.style.animation = "none";
      void bubble.offsetWidth;
      bubble.style.animation = "";
    }
    const label = `${peep.label}: ${hasImage ? `${peep.bubble.text} emote` : peep.bubble.text}. Dismiss message`;
    setBubbleLabel(bubble, label);
    const timeout = Number(latest?.ui?.bubbleTimeout || 0);
    if (timeout > 0) {
      if (bubbleChanged || !bubble._autoTimer) {
        clearTimeout(bubble._autoTimer);
        bubble._autoTimer = setTimeout(() => {
          bubble._autoTimer = 0;
          if (bubbleKey(roomPeep(peep.id)) !== nextKey) { render(latest, latestShown); return; }
          onDismiss(peep.id);
        }, timeout);
      }
    } else if (bubble._autoTimer) {
      clearTimeout(bubble._autoTimer);
      bubble._autoTimer = 0;
    }
  }

  function syncChatBubbles(shownPeeps) {
    const visibleIds = new Set();
    for (const peep of shownPeeps) {
      if (!peep.bubble || peep.bubbleDismissed) continue;
      visibleIds.add(peep.id);
      const bubble = chatBubbles.get(peep.id) || createChatBubble(peep);
      syncChatBubble(bubble, peep);
    }
    for (const [peepId, bubble] of chatBubbles) {
      if (visibleIds.has(peepId)) continue;
      clearTimeout(bubble._autoTimer);
      bubble.remove();
      chatBubbles.delete(peepId);
      dismissing.delete(peepId);
    }
  }

  function render(state, shownPeeps) {
    latest = state;
    latestShown = Array.isArray(shownPeeps) ? shownPeeps : [];
    syncChatBubbles(latestShown);
    syncDialogBubble(state.room?.dialog || null, latestShown);
    position();
  }

  function setSpriteAnchors(anchors) {
    spriteAnchors = anchors instanceof Map ? anchors : new Map();
    position();
  }

  const panelObserver = new ResizeObserver(position);
  panel.addEventListener("scroll", position, { passive: true });
  panelObserver.observe(panel);
  window.addEventListener("resize", position);

  function destroy() {
    panel.removeEventListener("scroll", position);
    panelObserver.disconnect();
    window.removeEventListener("resize", position);
    for (const bubble of chatBubbles.values()) {
      clearTimeout(bubble._autoTimer);
      bubble.remove();
    }
    chatBubbles.clear();
    bubbleSizes.clear();
    removeDialogBubble();
  }

  return {
    render,
    position,
    setSpriteAnchors,
    destroy,
    hasBubbles: () => chatBubbles.size > 0 || Boolean(dialogBubble),
  };
}
