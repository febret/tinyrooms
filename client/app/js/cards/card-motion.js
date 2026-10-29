import { findInventoryCard, findRoomCard } from "../state.js";

const FLIGHT_MS = 320;

function commandStackId(command) {
  const match = /@card:(\S+)/.exec(command || "");
  return match ? match[1] : "";
}

/** Animate hand/room card flights without owning any drag gesture. */
export function createCardMotion({ board, handRoot, getState }) {
  if (!board || typeof board.projectPositionToScreen !== "function" || !handRoot) {
    return { animatePickup() {}, animatePickupCommand() {}, animateDrop() {}, destroy() {} };
  }
  let layer = null;

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

  function animateDrop(stackId, toCenter) {
    if (!stackId || !toCenter) return;
    const stack = findInventoryCard(getState(), stackId);
    const tile = handRoot.querySelector(`.equipped-hand [data-stack-id="${CSS.escape(stackId)}"]`);
    if (!stack || !tile) return;
    const rect = tile.getBoundingClientRect();
    if (!rect.width || !rect.height) return;
    animateFlight({
      imageUrl: stack.definition?.imageUrl || "",
      fromRect: rect,
      toCenter,
      scaleFrom: 1,
      scaleTo: 0.24,
      opacityFrom: 1,
      opacityTo: 0.2,
    });
  }

  return {
    animatePickup,
    /** Animate a pickup flight when a command string targets a visible room card. */
    animatePickupCommand(command) {
      if (!/^\.pickup\s/.test(command || "")) return;
      animatePickup(commandStackId(command));
    },
    animateDrop,
    destroy() {
      layer?.remove();
      layer = null;
    },
  };
}
