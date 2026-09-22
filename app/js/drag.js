import { findInventoryCard, findRoomCard } from "./state.js";

const DRAG_THRESHOLD = 6;
const FLIGHT_MS = 320;
const CLICK_SUPPRESSION_MS = 300;

function commandStackId(command) {
  const match = /@card:(\S+)/.exec(command || "");
  return match ? match[1] : "";
}

/** Drag cards from the equipped hand onto the board and animate hand/room card flights. */
export function createCardMotion({ board, handRoot, getState, sendCommand, onError }) {
  if (!board || typeof board.screenToBoardPosition !== "function" || !handRoot) {
    return { animatePickup() {}, animatePickupCommand() {}, destroy() {} };
  }
  let layer = null;
  let drag = null;
  let suppressClick = false;

  function motionLayer() {
    if (!layer) {
      layer = document.createElement("div");
      layer.className = "card-motion-layer";
      document.body.appendChild(layer);
    }
    return layer;
  }

  function reducedMotion() {
    return Boolean(getState().ui?.reducedMotion);
  }

  function animateFlight({ imageUrl, fromRect, toCenter, scaleFrom = 1, scaleTo = 1, opacityFrom = 1, opacityTo = 1 }) {
    if (reducedMotion() || !imageUrl) return;
    const image = document.createElement("img");
    image.className = "card-flight";
    image.src = imageUrl;
    image.alt = "";
    image.style.width = `${fromRect.width}px`;
    image.style.height = `${fromRect.height}px`;
    image.style.left = `${fromRect.left}px`;
    image.style.top = `${fromRect.top}px`;
    motionLayer().appendChild(image);
    const deltaX = toCenter.x - (fromRect.left + fromRect.width / 2);
    const deltaY = toCenter.y - (fromRect.top + fromRect.height / 2);
    const remove = () => image.remove();
    try {
      const animation = image.animate(
        [
          { transform: `translate(0px, 0px) scale(${scaleFrom})`, opacity: opacityFrom },
          { transform: `translate(${deltaX}px, ${deltaY}px) scale(${scaleTo})`, opacity: opacityTo },
        ],
        { duration: FLIGHT_MS, easing: "cubic-bezier(0.22, 0.61, 0.36, 1)", fill: "forwards" },
      );
      animation.addEventListener("finish", remove);
      animation.addEventListener("cancel", remove);
    } catch {
      remove();
    }
  }

  function equippedStackFrom(target) {
    const tile = target instanceof Element ? target.closest(".equipped-hand [data-stack-id]") : null;
    if (!tile || !handRoot.contains(tile)) return null;
    const stack = findInventoryCard(getState(), tile.dataset.stackId);
    return stack?.equipped ? { tile, stack } : null;
  }

  function createGhost(rect, imageUrl) {
    const image = document.createElement("img");
    image.className = "card-drag-ghost";
    image.src = imageUrl;
    image.alt = "";
    image.draggable = false;
    image.style.width = `${rect.width}px`;
    motionLayer().appendChild(image);
    return image;
  }

  function onPointerDown(event) {
    if (event.button !== 0) return;
    const state = getState();
    if (!state.room || state.views.main || state.views.details || !state.user?.initialStickerComplete) return;
    const match = equippedStackFrom(event.target);
    if (!match) return;
    drag = {
      pointerId: event.pointerId,
      stackId: match.stack.stackId,
      imageUrl: match.stack.definition?.imageUrl || "",
      rect: match.tile.getBoundingClientRect(),
      startX: event.clientX,
      startY: event.clientY,
      moved: false,
      ghost: null,
      drop: null,
    };
    window.addEventListener("pointermove", onPointerMove);
    window.addEventListener("pointerup", onPointerUp);
    window.addEventListener("pointercancel", onPointerCancel);
  }

  function onPointerMove(event) {
    if (!drag || event.pointerId !== drag.pointerId) return;
    if (!drag.moved) {
      if (Math.hypot(event.clientX - drag.startX, event.clientY - drag.startY) < DRAG_THRESHOLD) return;
      drag.moved = true;
      document.body.classList.add("card-dragging");
      drag.ghost = createGhost(drag.rect, drag.imageUrl);
    }
    if (drag.ghost) {
      drag.ghost.style.left = `${event.clientX}px`;
      drag.ghost.style.top = `${event.clientY}px`;
    }
    drag.drop = board.screenToBoardPosition(event.clientX, event.clientY);
    board.setDropHint(drag.drop?.position || null);
  }

  function stopTracking() {
    window.removeEventListener("pointermove", onPointerMove);
    window.removeEventListener("pointerup", onPointerUp);
    window.removeEventListener("pointercancel", onPointerCancel);
    document.body.classList.remove("card-dragging");
    board.setDropHint(null);
  }

  function onPointerUp(event) {
    if (!drag || event.pointerId !== drag.pointerId) return;
    const finished = drag;
    drag = null;
    stopTracking();
    finished.ghost?.remove();
    if (!finished.moved) return;
    suppressClick = true;
    window.setTimeout(() => { suppressClick = false; }, CLICK_SUPPRESSION_MS);
    const point = finished.drop || board.screenToBoardPosition(event.clientX, event.clientY);
    if (!point) return;
    const [x, y, z] = point.position;
    animateFlight({
      imageUrl: finished.imageUrl,
      fromRect: finished.rect,
      toCenter: point.screen,
      scaleFrom: 1,
      scaleTo: 0.24,
      opacityFrom: 1,
      opacityTo: 0.2,
    });
    const command = `.drop @card:${finished.stackId} 1 ${Number(x).toFixed(2)} ${Number(y).toFixed(2)} ${Number(z).toFixed(2)}`;
    Promise.resolve()
      .then(() => sendCommand(command))
      .catch(error => onError?.(error));
  }

  function onPointerCancel(event) {
    if (!drag || event.pointerId !== drag.pointerId) return;
    drag.ghost?.remove();
    drag = null;
    stopTracking();
  }

  function swallowClick(event) {
    if (!suppressClick) return;
    suppressClick = false;
    event.stopPropagation();
    event.preventDefault();
  }

  function blockNativeDrag(event) {
    event.preventDefault();
  }

  function handTargetRect() {
    const container = handRoot.querySelector(".equipped-hand") || handRoot;
    const rect = container.getBoundingClientRect();
    return rect.width && rect.height ? rect : null;
  }

  function animatePickup(stackId) {
    if (!stackId) return;
    const card = findRoomCard(getState(), stackId);
    if (!card) return;
    const source = board.projectPositionToScreen(card.position);
    const target = handTargetRect();
    if (!source || !target) return;
    const width = Math.min(64, target.width);
    const height = width * 1.4;
    animateFlight({
      imageUrl: card.definition?.imageUrl || "",
      fromRect: { left: source.x - width / 2, top: source.y - height / 2, width, height },
      toCenter: { x: target.left + target.width / 2, y: target.top + target.height / 2 },
      scaleFrom: 1,
      scaleTo: 1,
      opacityFrom: 0.15,
      opacityTo: 1,
    });
  }

  handRoot.addEventListener("pointerdown", onPointerDown);
  handRoot.addEventListener("dragstart", blockNativeDrag);
  document.addEventListener("click", swallowClick, true);

  return {
    animatePickup,
    /** Animate a pickup flight when a command string targets a visible room card. */
    animatePickupCommand(command) {
      if (!/^\.pickup\s/.test(command || "")) return;
      animatePickup(commandStackId(command));
    },
    destroy() {
      handRoot.removeEventListener("pointerdown", onPointerDown);
      handRoot.removeEventListener("dragstart", blockNativeDrag);
      document.removeEventListener("click", swallowClick, true);
      drag?.ghost?.remove();
      drag = null;
      stopTracking();
      layer?.remove();
      layer = null;
    },
  };
}
