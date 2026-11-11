import { withBase } from "../base-path.js";
import { escapeHtml } from "../presentation.js";

export const MULTIVERSE_OPEN_MS = 980;
export const MULTIVERSE_CLOSE_MS = 720;
export const MULTIVERSE_TRAVEL_MS = 1050;

function absoluteUrl(value) {
  const text = String(value || "").trim();
  if (!text || /\s/.test(text)) return "";
  let candidate = text;
  if (candidate.startsWith("/") && !candidate.startsWith("//")) candidate = withBase(candidate);
  try {
    const base = typeof window !== "undefined" && window.location?.href
      ? window.location.href
      : "https://tinyrooms.local/";
    const parsed = new URL(candidate, base);
    if (parsed.protocol === "http:" || parsed.protocol === "https:") return parsed.href;
  } catch {
    return "";
  }
  return "";
}

/** Resolve a world or friend image without letting malformed input break the layout. */
export function multiverseImageUrl(raw) {
  return absoluteUrl(raw);
}

/** Deterministic accent hue so every world keeps its own orbital signature. */
export function worldHue(worldId) {
  const text = String(worldId || "");
  let hash = 0;
  for (let index = 0; index < text.length; index += 1) {
    hash = (hash * 31 + text.charCodeAt(index)) % 360;
  }
  return hash;
}

export function multiverseCountLabel(online) {
  const count = Math.max(0, Number(online || 0));
  if (count <= 0) return "Quiet right now";
  if (count === 1) return "1 peep here";
  return `${count} peeps here`;
}

/** Put the current world at the top of the ring, then preserve server order. */
export function multiverseDisplayOrder(worlds) {
  const list = Array.isArray(worlds) ? [...worlds] : [];
  const current = list.find(world => world?.current);
  if (!current) return list;
  return [current, ...list.filter(world => world !== current)];
}

/** Clockwise planet angle in degrees, starting at the top of the ring. */
export function planetAngle(index, count) {
  if (!Number.isFinite(index) || !Number.isFinite(count) || count <= 0) return -90;
  return -90 + (index * 360) / count;
}

const MV_TAG_HEIGHT = 50;
const MV_TAG_EXTRA_WIDTH = 34;
const MV_MIN_PLANET = 52;

/** Points spaced by equal arc length, so flat ellipses do not bunch worlds up at their ends. */
function ringPoints(count, radiusX, radiusY, phase) {
  const samples = 720;
  const start = (planetAngle(0, count) * Math.PI) / 180;
  const at = step => {
    const angle = start + (step / samples) * Math.PI * 2;
    return { x: Math.cos(angle) * radiusX, y: Math.sin(angle) * radiusY };
  };
  const lengths = [0];
  let previous = at(0);
  for (let step = 1; step <= samples; step += 1) {
    const point = at(step);
    lengths.push(lengths[step - 1] + Math.hypot(point.x - previous.x, point.y - previous.y));
    previous = point;
  }
  const perimeter = lengths[samples];
  const points = [];
  let cursor = 0;
  for (let index = 0; index < count; index += 1) {
    const target = (((index + phase) / count) % 1) * perimeter;
    if (target < lengths[cursor]) cursor = 0;
    while (cursor < samples && lengths[cursor + 1] < target) cursor += 1;
    points.push(at(cursor));
  }
  return points;
}

function ringOverlaps(points, blockWidth, blockHeight) {
  for (let a = 0; a < points.length; a += 1) {
    for (let b = a + 1; b < points.length; b += 1) {
      if (Math.abs(points[a].x - points[b].x) < blockWidth && Math.abs(points[a].y - points[b].y) < blockHeight) return true;
    }
  }
  return false;
}

/**
 * Fit planets (orb plus name tag) on an ellipse inside the ring box without
 * overlapping. Shrinks the orbs until they fit; short, wide boxes may shift
 * the ring by half a step so no two worlds stack above each other.
 */
export function multiverseRingLayout(count, width, height) {
  const total = Math.max(1, Math.floor(Number(count) || 1));
  const compact = width < 760 || height < 520;
  const preferred = Math.round((total <= 1 ? 196 : total <= 3 ? 172 : total <= 5 ? 150 : total <= 7 ? 128 : 110) * (compact ? 0.88 : 1.3));
  let fallback = null;
  for (let size = preferred; size >= MV_MIN_PLANET; size -= 4) {
    const blockWidth = size + MV_TAG_EXTRA_WIDTH;
    const blockHeight = size + MV_TAG_HEIGHT;
    const maxX = width / 2 - blockWidth / 2;
    const maxY = height / 2 - blockHeight / 2;
    if (maxX < 24 || maxY < 24) continue;
    // Large screens prefer a tidy, tighter ring and only widen it when crowded.
    const rings = compact ? [[maxX, maxY]] : [[Math.min(maxX, 340), Math.min(maxY, 226)], [maxX, maxY]];
    for (const [radiusX, radiusY] of rings) {
      for (const phase of [0, 0.5]) {
        const points = ringPoints(total, radiusX, radiusY, phase);
        const layout = { size, radiusX, radiusY, phase, points };
        if (total === 1 || !ringOverlaps(points, blockWidth, blockHeight)) return layout;
        fallback = layout;
      }
    }
  }
  if (fallback) return fallback;
  const radiusX = Math.max(24, width / 2 - (MV_MIN_PLANET + MV_TAG_EXTRA_WIDTH) / 2);
  const radiusY = Math.max(24, height / 2 - (MV_MIN_PLANET + MV_TAG_HEIGHT) / 2);
  return { size: MV_MIN_PLANET, radiusX, radiusY, phase: 0, points: ringPoints(total, radiusX, radiusY, 0) };
}

export function multiversePlanetMarkup(world, { selected = false, traveling = false, index = 0, count = 1 } = {}) {
  const id = String(world.id || "");
  const label = String(world.label || id || "A world");
  const online = multiverseCountLabel(world.usersOnline);
  const friends = Array.isArray(world.friends) ? world.friends : [];
  const friendCount = friends.length;
  const selectedClass = selected ? " is-selected" : "";
  const travelingClass = traveling ? " is-traveling" : "";
  const currentClass = world.current ? " is-current" : "";
  const description = [
    label,
    online,
    world.current ? "You are here." : "Travel to this world.",
    friendCount ? `${friendCount} ${friendCount === 1 ? "friend" : "friends"} online.` : "",
  ].filter(Boolean).join(" ");
  return `
    <div class="mv-slot" data-multiverse-slot="${escapeHtml(id)}"
      style="--mv-index:${index}; --mv-count:${count}; --world-hue:${worldHue(id)}">
      <div class="mv-motion">
        <button type="button" role="option" class="mv-planet${selectedClass}${travelingClass}${currentClass}"
          data-world-id="${escapeHtml(id)}" data-sound="multiverseSelect"
          aria-selected="${selected ? "true" : "false"}" aria-label="${escapeHtml(description)}"
          title="${escapeHtml(label)}">
          <span class="mv-orb">
            <span class="mv-orb-art" aria-hidden="true">
              ${multiverseImageUrl(world.imageUrl)
                ? `<img class="mv-planet-image" src="${escapeHtml(multiverseImageUrl(world.imageUrl))}" alt="" loading="lazy" draggable="false">`
                : `<span class="mv-planet-fallback">✦</span>`}
              <span class="mv-planet-shade"></span>
            </span>
            ${world.current ? '<span class="mv-home" aria-hidden="true">HOME</span>' : ""}
          </span>
          <span class="mv-tag">
            <strong>${escapeHtml(label)}</strong>
            <em>${escapeHtml(online)}${friendCount ? ` · ${friendCount} ♥` : ""}</em>
          </span>
        </button>
      </div>
    </div>
  `;
}

function statusCopy(multiverse) {
  if (multiverse.status === "loading") return "Reading the map…";
  if (multiverse.status === "error") return multiverse.error || "The map is out of reach.";
  if (!multiverse.worlds.length) return "No other worlds are humming right now.";
  const total = multiverse.worlds.length;
  return `${total} ${total === 1 ? "world is" : "worlds are"} within reach.`;
}

export function multiverseShellMarkup(multiverse) {
  const ordered = multiverseDisplayOrder(multiverse?.worlds || []);
  const selected = ordered.find(world => world.id === multiverse?.selectedId) || ordered[0] || null;
  const status = statusCopy(multiverse || {});
  const totalOnline = ordered.reduce((sum, world) => sum + Math.max(0, Number(world.usersOnline || 0)), 0);
  return `
    <section class="multiverse" role="dialog" aria-modal="true" aria-labelledby="multiverse-title" data-multiverse-root>
      <div class="mv-backdrop" aria-hidden="true">
        <div class="mv-nebula"></div>
        <div class="mv-tunnel"><i></i><i></i><i></i><i></i><i></i></div>
        <div class="mv-starfield"></div>
        <div class="mv-core"><span class="mv-core-flare"></span></div>
        <div class="mv-flash"></div>
      </div>
      <header class="mv-head">
        <div class="mv-head-copy">
          <p class="mv-eyebrow">Radial star atlas</p>
          <h2 id="multiverse-title">The Multiverse</h2>
          <p class="mv-status" data-multiverse-status>${escapeHtml(status)}</p>
        </div>
        <div class="mv-head-actions">
          <button type="button" class="quiet mv-refresh" data-multiverse-refresh aria-label="Refresh worlds" title="Refresh worlds">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M20 11a8 8 0 0 0-14.9-4M4 13a8 8 0 0 0 14.9 4"></path><path d="M20 4v7h-7M4 20v-7h7"></path></svg>
          </button>
          <button type="button" class="quiet mv-close" data-multiverse-close aria-label="Close the Multiverse">×</button>
        </div>
      </header>
      <div class="mv-stage">
        <div class="mv-orbit" role="listbox" aria-label="Reachable worlds" data-multiverse-ring>
          ${ordered.length
            ? ordered.map((world, index) => multiversePlanetMarkup(world, {
              selected: Boolean(selected && selected.id === world.id),
              traveling: Boolean(multiverse?.travelingId && multiverse.travelingId === world.id),
              index,
              count: ordered.length,
            })).join("")
            : `<p class="mv-empty">${escapeHtml(multiverse?.status === "loading" ? "The vortex is still forming…" : status)}</p>`}
        </div>
        ${multiverse?.status === "error" && !ordered.length
          ? `<button type="button" class="primary mv-retry" data-multiverse-refresh>Try again</button>`
          : ""}
      </div>
      <footer class="mv-foot">
        <span data-multiverse-count>${escapeHtml(totalOnline ? `${totalOnline} peeps across the Multiverse` : "")}</span>
        <span class="mv-hint">Click a world to travel · Click anywhere else to close</span>
      </footer>
    </section>
  `;
}

export function createMultiverseView({
  layer,
  getState,
  onRefresh,
  onSelect,
  onTravel,
  onClose,
  onSound,
}) {
  let open = false;
  let worldsKey = "";
  let selectedKey = "";
  let closeTimer = 0;
  let travelTimer = 0;

  function stateMultiverse() {
    return getState()?.multiverse || { status: "idle", worlds: [], selectedId: "", travelingId: "", error: "" };
  }

  function orderedWorlds(multiverse) {
    return multiverseDisplayOrder(multiverse?.worlds || []);
  }

  function selectedWorld(multiverse) {
    const ordered = orderedWorlds(multiverse);
    return ordered.find(world => world.id === multiverse.selectedId) || ordered[0] || null;
  }

  function play(name) {
    try { onSound?.(name); } catch { /* sound is decorative */ }
  }

  function ring() {
    return layer.querySelector("[data-multiverse-ring]");
  }

  function statusNode() {
    return layer.querySelector("[data-multiverse-status]");
  }

  function countNode() {
    return layer.querySelector("[data-multiverse-count]");
  }

  function ensureShell(multiverse) {
    if (layer.querySelector("[data-multiverse-root]")) return;
    layer.innerHTML = multiverseShellMarkup(multiverse);
    worldsKey = "";
    selectedKey = "";
  }

  function setBackground() {
    layer.style.setProperty("--mv-nebula", `url("${withBase("/app/assets/textures/multiverse-nebula.png")}")`);
    layer.style.setProperty("--mv-core", `url("${withBase("/app/assets/textures/multiverse-vortex.png")}")`);
    layer.style.setProperty("--mv-placeholder", `url("${withBase("/app/assets/textures/multiverse-world-placeholder.png")}")`);
  }

  function layoutPlanets() {
    const ringNode = ring();
    if (!ringNode) return;
    const rect = ringNode.getBoundingClientRect();
    if (!rect.width || !rect.height) return;
    const slots = [...ringNode.querySelectorAll("[data-multiverse-slot]")];
    const layout = multiverseRingLayout(slots.length || 1, rect.width, rect.height);
    slots.forEach((slot, index) => {
      const { x, y } = layout.points[index];
      slot.style.setProperty("--mv-x", `${Math.round(x)}px`);
      slot.style.setProperty("--mv-y", `${Math.round(y)}px`);
      slot.style.setProperty("--mv-sx", `${Math.round(-x)}px`);
      slot.style.setProperty("--mv-sy", `${Math.round(-y)}px`);
      slot.style.setProperty("--mv-size", `${layout.size}px`);
    });
  }

  function refreshImages(scope) {
    scope.querySelectorAll("img").forEach(image => {
      if (image.dataset.mvBound) return;
      image.dataset.mvBound = "1";
      image.addEventListener("error", () => {
        const slot = image.closest("[data-multiverse-slot]");
        if (slot) slot.classList.add("is-imageless");
        const fallback = document.createElement("span");
        fallback.className = "mv-planet-fallback";
        fallback.textContent = "✦";
        fallback.setAttribute("aria-hidden", "true");
        image.replaceWith(fallback);
      }, { once: true });
    });
  }

  function syncWorlds(force = false) {
    const multiverse = stateMultiverse();
    const ordered = orderedWorlds(multiverse);
    const key = JSON.stringify([multiverse.status, multiverse.travelingId, ordered.map(world => [
      world.id, world.label, world.imageUrl, world.usersOnline, world.current,
      (world.friends || []).map(friend => `${friend.accountId}:${friend.username}:${friend.stickerUrl}`).join("|"),
    ])]);
    const selected = selectedWorld(multiverse);
    const selectionChanged = selectedKey !== String(selected?.id || "");
    if (force || worldsKey !== key) {
      worldsKey = key;
      selectedKey = String(selected?.id || "");
      ensureShell(multiverse);
      const ringNode = ring();
      if (ringNode) {
        ringNode.innerHTML = ordered.length
          ? ordered.map((world, index) => multiversePlanetMarkup(world, {
            selected: Boolean(selected && selected.id === world.id),
            traveling: Boolean(multiverse.travelingId && multiverse.travelingId === world.id),
            index,
            count: ordered.length,
          })).join("")
          : `<p class="mv-empty">${escapeHtml(multiverse.status === "loading" ? "The vortex is still forming…" : statusCopy(multiverse))}</p>`;
        refreshImages(ringNode);
      }
      if (statusNode()) statusNode().textContent = statusCopy(multiverse);
      if (countNode()) {
        const total = ordered.reduce((sum, world) => sum + Math.max(0, Number(world.usersOnline || 0)), 0);
        countNode().textContent = total ? `${total} peeps across the Multiverse` : "";
      }
    } else if (selectionChanged || force) {
      selectedKey = String(selected?.id || "");
      ring()?.querySelectorAll("[data-world-id]").forEach(button => {
        const active = button.dataset.worldId === selectedKey;
        button.classList.toggle("is-selected", active);
        button.setAttribute("aria-selected", active ? "true" : "false");
        button.setAttribute("aria-pressed", active ? "true" : "false");
      });
      const travelingId = String(multiverse.travelingId || "");
      ring()?.querySelectorAll("[data-world-id]").forEach(button => {
        button.classList.toggle("is-traveling", Boolean(travelingId && button.dataset.worldId === travelingId));
      });
      if (statusNode()) statusNode().textContent = statusCopy(multiverse);
    }
    if (statusNode() && (force || worldsKey === key) && !ordered.length && multiverse.status !== "loading") {
      statusNode().textContent = statusCopy(multiverse);
    }
    layoutPlanets();
  }

  function focusSelected() {
    const multiverse = stateMultiverse();
    const selected = selectedWorld(multiverse);
    const target = (selected && ring()?.querySelector(`[data-world-id="${CSS.escape(selected.id)}"]`))
      || layer.querySelector("[data-multiverse-refresh]");
    target?.focus({ preventScroll: true });
  }

  function enter() {
    const reduced = Boolean(getState()?.ui?.reducedMotion);
    const multiverse = stateMultiverse();
    open = true;
    setBackground();
    ensureShell(multiverse);
    layer.hidden = false;
    layer.dataset.state = reduced ? "open" : "entering";
    syncWorlds(true);
    window.clearTimeout(closeTimer);
    window.clearTimeout(travelTimer);
    layoutPlanets();
    if (reduced) {
      focusSelected();
      return;
    }
    window.setTimeout(() => {
      if (!open) return;
      if (layer.dataset.state === "entering") layer.dataset.state = "open";
      focusSelected();
    }, 140);
    window.setTimeout(() => {
      if (open && layer.dataset.state === "entering") layer.dataset.state = "open";
    }, MULTIVERSE_OPEN_MS);
  }

  function hide() {
    open = false;
    worldsKey = "";
    selectedKey = "";
    layer.dataset.state = "idle";
    layer.hidden = true;
    layer.innerHTML = "";
  }

  function closeAnimated() {
    if (!open) return Promise.resolve();
    const reduced = Boolean(getState()?.ui?.reducedMotion);
    layer.dataset.state = "closing";
    return new Promise(resolve => {
      if (reduced) {
        resolve();
        return;
      }
      window.clearTimeout(closeTimer);
      closeTimer = window.setTimeout(resolve, MULTIVERSE_CLOSE_MS);
    });
  }

  function depart() {
    if (!open) return 0;
    const reduced = Boolean(getState()?.ui?.reducedMotion);
    window.clearTimeout(travelTimer);
    const travelingId = String(stateMultiverse().travelingId || "");
    const departing = travelingId && ring()?.querySelector(`[data-world-id="${CSS.escape(travelingId)}"]`);
    departing?.closest("[data-multiverse-slot]")?.classList.add("is-departing");
    if (reduced) {
      layer.dataset.state = "open";
      return 0;
    }
    layer.dataset.state = "traveling";
    return MULTIVERSE_TRAVEL_MS;
  }

  function worldById(id) {
    return orderedWorlds(stateMultiverse()).find(world => world.id === String(id || "")) || null;
  }

  function selectWorld(id, { focus = false } = {}) {
    const world = worldById(id);
    if (!world) return;
    onSelect?.(world.id);
    if (focus) {
      ring()?.querySelector(`[data-world-id="${CSS.escape(world.id)}"]`)?.focus({ preventScroll: true });
    }
  }

  function stepSelection(delta) {
    const multiverse = stateMultiverse();
    const ordered = orderedWorlds(multiverse);
    if (!ordered.length) return;
    const selected = selectedWorld(multiverse);
    const current = Math.max(0, ordered.findIndex(world => world.id === selected?.id));
    const next = ordered[(current + delta + ordered.length) % ordered.length];
    play("multiverseSelect");
    selectWorld(next.id, { focus: true });
  }

  layer.addEventListener("click", event => {
    if (layer.hidden) return;
    const refresh = event.target.closest("[data-multiverse-refresh]");
    if (refresh) {
      onRefresh?.();
      return;
    }
    if (stateMultiverse().travelingId || layer.dataset.state === "closing" || layer.dataset.state === "traveling") return;
    const planet = event.target.closest("[data-world-id]");
    if (!planet) {
      onClose?.();
      return;
    }
    const world = worldById(planet.dataset.worldId);
    if (!world || world.current) return;
    selectWorld(world.id);
    onTravel?.(world.id);
  });

  layer.addEventListener("focusin", event => {
    const planet = event.target.closest?.("[data-world-id]");
    if (!planet || layer.dataset.state !== "open") return;
    selectWorld(planet.dataset.worldId);
  });

  layer.addEventListener("keydown", event => {
    if (layer.hidden) return;
    if (event.key === "ArrowRight" || event.key === "ArrowDown") {
      event.preventDefault();
      stepSelection(1);
    } else if (event.key === "ArrowLeft" || event.key === "ArrowUp") {
      event.preventDefault();
      stepSelection(-1);
    } else if (event.key === "Home") {
      event.preventDefault();
      const ordered = orderedWorlds(stateMultiverse());
      if (ordered[0]) {
        play("multiverseSelect");
        selectWorld(ordered[0].id, { focus: true });
      }
    } else if (event.key === "End") {
      event.preventDefault();
      const ordered = orderedWorlds(stateMultiverse());
      if (ordered.length) {
        play("multiverseSelect");
        selectWorld(ordered.at(-1).id, { focus: true });
      }
    }
  });

  let resizeFrame = 0;
  function scheduleLayout() {
    if (resizeFrame) return;
    resizeFrame = window.requestAnimationFrame(() => {
      resizeFrame = 0;
      if (open && !layer.hidden) layoutPlanets();
    });
  }
  if (typeof ResizeObserver !== "undefined") {
    new ResizeObserver(scheduleLayout).observe(layer);
  } else {
    window.addEventListener("resize", scheduleLayout);
  }

  function sync(state) {
    const active = state?.views?.main === "multiverse" && Boolean(state.room);
    if (active && !open) {
      enter();
      return;
    }
    if (!active && open) {
      // Normal closes animate first; unexpected room/session changes hide immediately.
      hide();
      return;
    }
    if (!active) return;
    syncWorlds(false);
  }

  return { sync, closeAnimated, depart, focusSelected, layoutPlanets };
}
