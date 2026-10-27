import { withBase } from "../base-path.js";
import { escapeHtml } from "../presentation.js";

export const MULTIVERSE_OPEN_MS = 980;
export const MULTIVERSE_CLOSE_MS = 720;
export const MULTIVERSE_TRAVEL_MS = 1050;
const MAX_PLANET_FRIEND_STICKERS = 4;
const MAX_DETAIL_FRIEND_STICKERS = 8;

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

function initials(username) {
  const text = String(username || "").trim();
  if (!text) return "•";
  const parts = text.split(/\s+/).filter(Boolean).slice(0, 2);
  return parts.map(part => part.slice(0, 1).toUpperCase()).join("") || "•";
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

function friendStickerMarkup(friend) {
  const username = String(friend.username || "Friend");
  const source = absoluteUrl(friend.stickerUrl);
  if (!source) {
    return `<span class="mv-friend fallback" title="${escapeHtml(`${username} is online here`)}" aria-label="${escapeHtml(`${username} is online here`)}">${escapeHtml(initials(username))}</span>`;
  }
  return `<span class="mv-friend" title="${escapeHtml(`${username} is online here`)}" aria-label="${escapeHtml(`${username} is online here`)}"><img src="${escapeHtml(source)}" alt="" loading="lazy" draggable="false"></span>`;
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
    world.current ? "You are here." : "Select to inspect this world.",
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
            ${multiverseImageUrl(world.imageUrl)
              ? `<img class="mv-planet-image" src="${escapeHtml(multiverseImageUrl(world.imageUrl))}" alt="" loading="lazy" draggable="false">`
              : `<span class="mv-planet-fallback" aria-hidden="true">✦</span>`}
            <span class="mv-planet-shade" aria-hidden="true"></span>
            <span class="mv-planet-ring" aria-hidden="true"></span>
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

export function multiverseDetailMarkup(selected, multiverse = {}) {
  if (!selected) {
    return `
      <div class="mv-detail-empty">
        <p>No world selected.</p>
        <span>Choose a planet on the rim.</span>
      </div>
    `;
  }
  const image = multiverseImageUrl(selected.imageUrl);
  const friends = Array.isArray(selected.friends) ? selected.friends : [];
  const shownFriends = friends.slice(0, MAX_DETAIL_FRIEND_STICKERS);
  const traveling = Boolean(multiverse.travelingId && multiverse.travelingId === selected.id);
  const travelDisabled = Boolean(selected.current || traveling || multiverse.status !== "ready");
  const travelLabel = traveling
    ? `Stepping toward ${selected.label}…`
    : selected.current
      ? "You are here"
      : `Travel to ${selected.label}`;
  return `
    <div class="mv-detail-media">
      ${image
        ? `<img class="mv-detail-image" src="${escapeHtml(image)}" alt="" loading="lazy" draggable="false">`
        : `<span class="mv-detail-fallback" aria-hidden="true">✦</span>`}
      <span class="mv-detail-veil" aria-hidden="true"></span>
      ${selected.current ? '<span class="mv-detail-home">You are here</span>' : ""}
    </div>
    <h3 class="mv-detail-name">${escapeHtml(selected.label)}</h3>
    <p class="mv-detail-description">${escapeHtml(selected.description || "A shimmering world waits on the other side.")}</p>
    <dl class="mv-detail-meta">
      <div><dt>Peeps</dt><dd>${escapeHtml(multiverseCountLabel(selected.usersOnline))}</dd></div>
      <div><dt>World</dt><dd>${escapeHtml(String(selected.id || ""))}</dd></div>
    </dl>
    ${friends.length
      ? `<div class="mv-detail-friends" aria-label="${escapeHtml(`${friends.length} ${friends.length === 1 ? "friend" : "friends"} online here`)}">${shownFriends.map(friendStickerMarkup).join("")}${friends.length > MAX_DETAIL_FRIEND_STICKERS ? `<span class="mv-friend fallback" aria-hidden="true">+${friends.length - MAX_DETAIL_FRIEND_STICKERS}</span>` : ""}</div>`
      : `<p class="mv-detail-friends-empty">No friends here right now.</p>`}
    <button type="button" class="mv-travel primary" data-multiverse-travel="${escapeHtml(String(selected.id || ""))}" data-sound="multiverseTravel" ${travelDisabled ? "disabled" : ""}>${escapeHtml(travelLabel)}</button>
    ${traveling ? '<p class="mv-detail-note" role="status">Holding the portal open…</p>' : ""}
  `;
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
        <aside class="mv-panel" aria-label="Selected world" aria-live="polite" data-multiverse-detail>
          ${multiverseDetailMarkup(selected, multiverse || {})}
        </aside>
      </div>
      <footer class="mv-foot">
        <span data-multiverse-count>${escapeHtml(totalOnline ? `${totalOnline} peeps across the Multiverse` : "")}</span>
        <span class="mv-hint">Arrows move · Enter selects · Travel confirms</span>
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
  let previewId = "";
  let hoverAt = 0;
  let hoverId = "";
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

  function detail() {
    return layer.querySelector("[data-multiverse-detail]");
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
    previewId = "";
  }

  function setBackground() {
    layer.style.setProperty("--mv-nebula", `url("${withBase("/app/assets/textures/multiverse-nebula.png")}")`);
    layer.style.setProperty("--mv-core", `url("${withBase("/app/assets/textures/multiverse-vortex.png")}")`);
    layer.style.setProperty("--mv-placeholder", `url("${withBase("/app/assets/textures/multiverse-world-placeholder.png")}")`);
  }

  function slotGeometry(slot, index, count, rect) {
    const compact = rect.width < 760 || rect.height < 620;
    const base = Math.min(rect.width, rect.height);
    const panelOffset = rect.width >= 1080 ? Math.min(rect.width * 0.11, 150) : 0;
    const radiusX = Math.max(104, Math.min(rect.width * (compact ? 0.34 : 0.30) - panelOffset * 0.35, compact ? 190 : 320));
    const radiusY = Math.max(84, Math.min(rect.height * (compact ? 0.21 : 0.28), compact ? 132 : 216));
    const angle = (planetAngle(index, count) * Math.PI) / 180;
    const x = Math.cos(angle) * radiusX - panelOffset;
    const y = Math.sin(angle) * radiusY * (base < 520 ? 0.92 : 1);
    slot.style.setProperty("--mv-x", `${Math.round(x)}px`);
    slot.style.setProperty("--mv-y", `${Math.round(y)}px`);
    slot.style.setProperty("--mv-sx", `${Math.round(-x)}px`);
    slot.style.setProperty("--mv-sy", `${Math.round(-y)}px`);
    const size = count <= 1 ? 196 : count <= 3 ? 172 : count <= 5 ? 150 : count <= 7 ? 128 : 110;
    slot.style.setProperty("--mv-size", `${compact ? Math.round(size * 0.68) : size}px`);
  }

  function layoutPlanets() {
    const ringNode = ring();
    if (!ringNode) return;
    const rect = layer.getBoundingClientRect();
    if (!rect.width || !rect.height) return;
    const slots = [...ringNode.querySelectorAll("[data-multiverse-slot]")];
    slots.forEach((slot, index) => slotGeometry(slot, index, slots.length || 1, rect));
  }

  function refreshImages(scope) {
    scope.querySelectorAll("img").forEach(image => {
      if (image.dataset.mvBound) return;
      image.dataset.mvBound = "1";
      image.addEventListener("error", () => {
        const slot = image.closest("[data-multiverse-slot]");
        if (slot) slot.classList.add("is-imageless");
        const fallback = document.createElement("span");
        fallback.className = image.classList.contains("mv-detail-image") ? "mv-detail-fallback" : "mv-planet-fallback";
        fallback.textContent = "✦";
        fallback.setAttribute("aria-hidden", "true");
        image.replaceWith(fallback);
      }, { once: true });
    });
  }

  function showDetail(world, multiverse, { announce = false } = {}) {
    const detailNode = detail();
    if (!detailNode) return;
    const markup = multiverseDetailMarkup(world, multiverse);
    if (detailNode.dataset.world === String(world?.id || "") && detailNode.dataset.travel === String(multiverse.travelingId || "")) return;
    detailNode.dataset.world = String(world?.id || "");
    detailNode.dataset.travel = String(multiverse.travelingId || "");
    detailNode.innerHTML = markup;
    if (announce) detailNode.setAttribute("aria-live", "assertive");
    else detailNode.setAttribute("aria-live", "polite");
    refreshImages(detailNode);
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
    if (!previewId) showDetail(selected, multiverse);
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
    previewId = "";
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
    previewId = "";
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
    previewId = "";
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
    previewId = "";
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
      previewId = "";
      onRefresh?.();
      return;
    }
    const close = event.target.closest("[data-multiverse-close]");
    if (close) {
      onClose?.();
      return;
    }
    const travel = event.target.closest("[data-multiverse-travel]");
    if (travel && !travel.disabled) {
      onTravel?.(String(travel.dataset.multiverseTravel || ""));
      return;
    }
    const planet = event.target.closest("[data-world-id]");
    if (planet) selectWorld(planet.dataset.worldId);
  });

  layer.addEventListener("pointerover", event => {
    if (layer.hidden || layer.dataset.state !== "open") return;
    if (event.pointerType === "touch") return;
    const planet = event.target.closest?.("[data-world-id]");
    if (!planet) return;
    const id = String(planet.dataset.worldId || "");
    const now = Date.now();
    if (id && (id !== hoverId || now - hoverAt > 220)) {
      hoverId = id;
      hoverAt = now;
      play("multiverseHover");
    }
    const world = worldById(id);
    if (world && previewId !== id) {
      previewId = id;
      showDetail(world, stateMultiverse());
      ring()?.querySelectorAll("[data-world-id]").forEach(button => {
        button.classList.toggle("is-preview", button.dataset.worldId === id);
      });
    }
  });

  layer.addEventListener("pointerleave", () => {
    if (!previewId) return;
    previewId = "";
    ring()?.querySelectorAll("[data-world-id]").forEach(button => button.classList.remove("is-preview"));
    showDetail(selectedWorld(stateMultiverse()), stateMultiverse());
  }, true);

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
