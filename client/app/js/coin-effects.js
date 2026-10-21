/** Reusable Bops coin animation: coins fly from a source anchor to a target anchor. */

const DENOMINATIONS = [100, 10, 1];
const FLIGHT_MS = 1400;
const STAGGER_MS = 200;
const MAX_COINS = 80;

let layer = null;

function motionLayer() {
  if (!layer) {
    layer = document.createElement("div");
    layer.className = "coin-motion-layer";
    document.body.appendChild(layer);
  }
  return layer;
}

/** Break a Bops amount into 100/10/1 coin denominations, largest first. */
export function coinBreakdown(bops) {
  let remaining = Math.max(0, Math.floor(Number(bops) || 0));
  const coins = [];
  for (const denomination of DENOMINATIONS) {
    const count = Math.floor(remaining / denomination);
    for (let index = 0; index < count; index += 1) coins.push(denomination);
    remaining -= count * denomination;
  }
  return coins;
}

/** Resolve an Element, DOMRect, or point into a viewport center point. */
function anchorPoint(anchor) {
  if (!anchor) return null;
  if (anchor instanceof Element) {
    const rect = anchor.getBoundingClientRect();
    return { x: rect.left + rect.width / 2, y: rect.top + rect.height / 2 };
  }
  if (typeof anchor.x === "number" && typeof anchor.y === "number") {
    return { x: anchor.x, y: anchor.y };
  }
  if (typeof anchor.left === "number" && typeof anchor.top === "number") {
    return { x: anchor.left + (anchor.width || 0) / 2, y: anchor.top + (anchor.height || 0) / 2 };
  }
  return null;
}

function spawnCoin(value, from, to, delay) {
  const coin = document.createElement("span");
  coin.className = `coin coin-${value}`;
  coin.textContent = String(value);
  coin.setAttribute("aria-hidden", "true");
  motionLayer().appendChild(coin);
  const size = coin.offsetWidth || 16;
  const jitter = () => (Math.random() - 0.5) * 18;
  const startX = from.x - size / 2 + jitter();
  const startY = from.y - size / 2 + jitter();
  const endX = to.x - size / 2 + jitter();
  const endY = to.y - size / 2 + jitter();
  const deltaX = endX - startX;
  const deltaY = endY - startY;
  const remove = () => coin.remove();
  try {
    const animation = coin.animate(
      [
        { transform: `translate(${startX}px, ${startY}px) scale(.35)`, opacity: 0 },
        { transform: `translate(${startX + deltaX * 0.12}px, ${startY + deltaY * 0.12 - 30}px) scale(1.08)`, opacity: 1, offset: 0.3 },
        { transform: `translate(${startX + deltaX * 0.62}px, ${startY + deltaY * 0.62 - 34}px) scale(1)`, opacity: 1, offset: 0.62 },
        { transform: `translate(${endX}px, ${endY}px) scale(.6)`, opacity: 1 },
      ],
      { duration: FLIGHT_MS, delay, easing: "cubic-bezier(.32, .06, .35, 1)", fill: "forwards" },
    );
    animation.addEventListener("finish", remove);
    animation.addEventListener("cancel", remove);
  } catch {
    remove();
  }
}

/**
 * Fly Bops coins from a source anchor to a target anchor.
 *
 * Anchors may be DOM Elements, DOMRects, or {x, y} viewport points, so any
 * feature can reuse this for its own reward source and destination.
 * Returns the number of coins spawned.
 */
export function flyCoinReward({ from, to, bops, reducedMotion = false }) {
  const source = anchorPoint(from);
  const target = anchorPoint(to);
  const coins = coinBreakdown(bops).slice(0, MAX_COINS);
  motionLayer().dataset.lastCoins = String(coins.length);
  if (reducedMotion || !source || !target || !coins.length) return coins.length;
  coins.forEach((value, index) => spawnCoin(value, source, target, index * STAGGER_MS));
  return coins.length;
}
