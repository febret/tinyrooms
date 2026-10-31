import { withBase } from "../../app/js/base-path.js";
import { escapeHtml } from "./util.js";
import {
  INT32_MAX,
  INT32_MIN,
  customExitLinks,
  floorLinks,
  floorRooms,
  gridBounds,
  gridRooms,
  liveRooms,
  missingGridRooms,
  roomAt,
  verticalNeighbors,
} from "./grid-map-model.js";

const CELL_WIDTH = 132;
const CELL_HEIGHT = 92;
const MIN_ZOOM = 0.25;
const MAX_ZOOM = 1.25;

function clampZoom(zoom) {
  return Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, zoom));
}

function tileCenter(bounds, position) {
  return {
    x: (position[0] - bounds.minX) * CELL_WIDTH + CELL_WIDTH / 2,
    y: (position[1] - bounds.minY) * CELL_HEIGHT + CELL_HEIGHT / 2,
  };
}

export function createGridMapView({ container, onSelect, onMove, onCreateGrid }) {
  let floor = 0;
  let lastActiveId = null;
  let lastActivePosition = null;
  let lastArgs = null;
  let lastSignature = "";
  let layout = null;
  let transform = { x: 0, y: 0, zoom: 1 };
  let drag = null;
  let pan = null;
  let justDragged = false;
  const fitted = new Set();

  const viewport = () => container.querySelector(".grid-map-viewport");
  const world = () => container.querySelector(".grid-map-world");

  function applyTransform() {
    const worldElement = world();
    if (!worldElement) return;
    worldElement.style.transform = `translate(${transform.x}px, ${transform.y}px) scale(${transform.zoom})`;
  }

  function toWorld(event) {
    const view = viewport();
    const rect = view?.getBoundingClientRect();
    if (!view || !rect || !layout) return null;
    return {
      x: (event.clientX - rect.left - transform.x) / transform.zoom,
      y: (event.clientY - rect.top - transform.y) / transform.zoom,
    };
  }

  function cellFromWorld(point) {
    return {
      x: Math.floor(point.x / CELL_WIDTH) + layout.bounds.minX,
      y: Math.floor(point.y / CELL_HEIGHT) + layout.bounds.minY,
    };
  }

  function activeEntry() {
    if (!lastArgs || !lastArgs.activeId) return null;
    return gridRooms(lastArgs.draft).find(entry => entry.id === lastArgs.activeId) || null;
  }

  function fit() {
    const view = viewport();
    if (!view || !layout?.bounds) return;
    const rect = view.getBoundingClientRect();
    if (!rect.width || !rect.height) return;
    const worldWidth = (layout.bounds.maxX - layout.bounds.minX + 1) * CELL_WIDTH;
    const worldHeight = (layout.bounds.maxY - layout.bounds.minY + 1) * CELL_HEIGHT;
    const zoom = clampZoom(Math.min((rect.width - 32) / worldWidth, (rect.height - 32) / worldHeight));
    transform = {
      zoom,
      x: (rect.width - worldWidth * zoom) / 2,
      y: (rect.height - worldHeight * zoom) / 2,
    };
    applyTransform();
  }

  function zoomAtPoint(factor, clientX, clientY) {
    const view = viewport();
    if (!view) return;
    const rect = view.getBoundingClientRect();
    const zoom = clampZoom(transform.zoom * factor);
    const scale = zoom / transform.zoom;
    transform = {
      zoom,
      x: clientX - rect.left - (clientX - rect.left - transform.x) * scale,
      y: clientY - rect.top - (clientY - rect.top - transform.y) * scale,
    };
    applyTransform();
  }

  function linkMarkup(links, byId) {
    return links.map(link => {
      const from = byId.get(link.from);
      const to = byId.get(link.to);
      if (!from || !to) return "";
      const start = tileCenter(layout.bounds, from.position);
      const end = tileCenter(layout.bounds, to.position);
      return `<line class="grid-map-link" x1="${start.x}" y1="${start.y}" x2="${end.x}" y2="${end.y}" />`;
    }).join("");
  }

  function portalMarkup(entries, active) {
    if (!active) return "";
    const byId = new Map(entries.map(entry => [entry.id, entry]));
    return customExitLinks(lastArgs.draft, active.id)
      .map(link => {
        const target = byId.get(link.to);
        if (!target || target.position[2] !== floor) return "";
        const start = tileCenter(layout.bounds, active.position);
        const end = tileCenter(layout.bounds, target.position);
        return `<line class="grid-map-portal" x1="${start.x}" y1="${start.y}" x2="${end.x}" y2="${end.y}"><title>${escapeHtml(link.label)} to ${escapeHtml(target.label)}</title></line>`;
      })
      .join("");
  }

  function tileMarkup(entry, { activeId, entryId, worldId }) {
    const room = entry.room;
    const image = typeof room.board_image === "string" && room.board_image
      ? withBase(`/assets/world/${worldId}/rooms/${room.board_image}`)
      : "";
    const accent = Array.isArray(room.palette) && room.palette[0] ? room.palette[0] : "";
    const vertical = verticalNeighbors(gridRooms(lastArgs.draft), entry.id);
    const badges = [
      entry.id === entryId ? '<span class="grid-map-badge" title="Entry room">★</span>' : "",
      vertical.above.length ? '<span class="grid-map-badge" title="Room above">▲</span>' : "",
      vertical.below.length ? '<span class="grid-map-badge" title="Room below">▼</span>' : "",
    ].join("");
    const left = (entry.position[0] - layout.bounds.minX) * CELL_WIDTH;
    const top = (entry.position[1] - layout.bounds.minY) * CELL_HEIGHT;
    return `
      <button type="button" class="grid-map-room${entry.id === activeId ? " is-active" : ""}" style="left:${left}px;top:${top}px;${accent ? `--grid-accent:${escapeHtml(accent)};` : ""}" data-grid-room="${escapeHtml(entry.id)}" aria-label="${escapeHtml(entry.label)}, grid ${entry.position[0]}, ${entry.position[1]}, ${entry.position[2]}">
        ${image ? `<img class="grid-map-image" src="${escapeHtml(image)}" alt="" draggable="false">` : ""}
        <span class="grid-map-tile-top"><span class="grid-map-badges">${badges}</span><code>${entry.position[0]}, ${entry.position[1]}, ${entry.position[2]}</code></span>
        <strong>${escapeHtml(entry.label)}</strong>
        <code class="grid-map-id">${escapeHtml(entry.id)}</code>
      </button>
    `;
  }

  function selectionMarkup(entries, active) {
    if (!active) return '<span class="grid-map-hint">Select a room to move it with the arrow keys.</span>';
    if (active.position[2] !== floor) {
      return `
        <span class="grid-map-hint">Selected room is on floor ${active.position[2]}.</span>
        <button type="button" class="quiet compact-button" data-grid-focus="goto" data-grid-goto="${active.position[2]}">Go to floor</button>
      `;
    }
    const upDisabled = active.position[2] >= INT32_MAX ? " disabled" : "";
    const downDisabled = active.position[2] <= INT32_MIN ? " disabled" : "";
    return `
      <span class="grid-map-hint">Selected · ${active.position[0]}, ${active.position[1]}, ${active.position[2]}</span>
      <button type="button" class="quiet compact-button" data-grid-focus="move-up" data-grid-move="up"${upDisabled}>Move up</button>
      <button type="button" class="quiet compact-button" data-grid-focus="move-down" data-grid-move="down"${downDisabled}>Move down</button>
    `;
  }

  function buildMarkup(entries, active, worldId, unpositioned) {
    const rooms = floorRooms(entries, floor);
    const links = floorLinks(entries, floor);
    const byId = new Map(entries.map(entry => [entry.id, entry]));
    const entryId = typeof lastArgs.draft?.world?.entry_room === "string" ? lastArgs.draft.world.entry_room : "";
    const width = (layout.bounds.maxX - layout.bounds.minX + 1) * CELL_WIDTH;
    const height = (layout.bounds.maxY - layout.bounds.minY + 1) * CELL_HEIGHT;
    return `
      <div class="grid-map-head">
        <div class="grid-map-title"><strong>Room grid</strong><span>${entries.length} room${entries.length === 1 ? "" : "s"} · Floor ${floor}</span></div>
        <div class="grid-map-controls">
          <div class="grid-map-floors" role="group" aria-label="Viewed floor">
            <button type="button" class="quiet compact-button" data-grid-focus="floor-down" data-grid-floor="down" aria-label="View lower floor">−</button>
            <span aria-live="polite">Floor ${floor}</span>
            <button type="button" class="quiet compact-button" data-grid-focus="floor-up" data-grid-floor="up" aria-label="View upper floor">+</button>
          </div>
          <button type="button" class="quiet compact-button" data-grid-focus="zoom-out" data-grid-zoom="out" aria-label="Zoom out">−</button>
          <button type="button" class="quiet compact-button" data-grid-focus="zoom-in" data-grid-zoom="in" aria-label="Zoom in">+</button>
        </div>
      </div>
      ${unpositioned.length ? `
        <div class="grid-map-notice">
          <span>${unpositioned.length} room${unpositioned.length === 1 ? " needs" : "s need"} a grid position.</span>
          <button type="button" class="quiet compact-button" data-grid-focus="create" data-grid-create>Place rooms</button>
        </div>
      ` : ""}
      <div class="grid-map-viewport" tabindex="0" role="group" aria-label="Room grid map. Drag rooms between cells, or use arrow keys to move the selected room.">
        <div class="grid-map-world">
          <svg class="grid-map-links" width="${width}" height="${height}" viewBox="0 0 ${width} ${height}" aria-hidden="true">
            ${linkMarkup(links, byId)}
            ${portalMarkup(entries, active)}
          </svg>
          ${rooms.length ? rooms.map(entry => tileMarkup(entry, { activeId: active?.id || null, entryId, worldId })).join("") : '<p class="grid-map-empty-floor">No rooms on this floor.</p>'}
          <div class="grid-map-target" hidden></div>
        </div>
      </div>
      <div class="grid-map-foot">
        <span class="grid-map-hint">Drag rooms to empty cells. Solid lines follow grid adjacency; dashed lines show the selected room’s custom exits.</span>
        <span class="grid-map-selection">${selectionMarkup(entries, active)}</span>
      </div>
    `;
  }

  function focusKey() {
    const element = document.activeElement;
    if (!element || !container.contains(element)) return null;
    const key = element.dataset?.gridFocus;
    if (key) return `focus:${key}`;
    const room = element.closest?.("[data-grid-room]");
    if (room) return `room:${room.dataset.gridRoom}`;
    return "viewport";
  }

  function restoreFocus(key) {
    if (!key) return;
    if (key === "viewport") {
      viewport()?.focus({ preventScroll: true });
      return;
    }
    if (key.startsWith("focus:")) {
      container.querySelector(`[data-grid-focus="${key.slice(6)}"]`)?.focus({ preventScroll: true });
      return;
    }
    if (key.startsWith("room:")) {
      const roomId = key.slice(5);
      const tiles = [...container.querySelectorAll("[data-grid-room]")];
      const tile = tiles.find(candidate => candidate.dataset.gridRoom === roomId)
        || tiles.find(candidate => candidate.classList.contains("is-active"));
      (tile || viewport())?.focus({ preventScroll: true });
    }
  }

  function render({ draft, activeId = null, worldId = "" }) {
    lastArgs = { draft, activeId, worldId };
    const entries = gridRooms(draft);
    const unpositioned = missingGridRooms(draft);
    const activeRoom = entries.find(entry => entry.id === activeId) || null;
    if (lastActiveId !== activeId) {
      lastActiveId = activeId;
      if (activeRoom) floor = activeRoom.position[2];
    } else if (activeRoom && lastActivePosition && activeRoom.position[2] !== lastActivePosition[2]) {
      floor = activeRoom.position[2];
    }
    lastActivePosition = activeRoom ? [...activeRoom.position] : null;
    if (!liveRooms(draft).length) {
      lastSignature = "no-rooms";
      layout = null;
      container.innerHTML = '<p class="grid-map-empty">No rooms to arrange yet.</p>';
      return;
    }
    if (!entries.length) {
      lastSignature = `setup:${unpositioned.length}`;
      layout = null;
      container.innerHTML = `
        <div class="grid-map-setup">
          <p><strong>No room grid yet.</strong> Create grid positions to arrange rooms and edit their connections.</p>
          <button type="button" class="quiet compact-button" data-grid-focus="create" data-grid-create>Create grid layout</button>
        </div>
      `;
      return;
    }
    const rooms = floorRooms(entries, floor);
    layout = { bounds: gridBounds(rooms.length ? rooms : entries), rooms };
    const active = activeRoom;
    const signature = JSON.stringify({
      rooms: entries.map(entry => [entry.id, entry.label, entry.room.board_image || "", entry.room.palette || [], entry.position]),
      floor,
      activeId,
      worldId,
      entry: draft?.world?.entry_room || "",
      unpositioned: unpositioned.length,
    });
    if (signature !== lastSignature) {
      const key = focusKey();
      container.innerHTML = buildMarkup(entries, active, worldId, unpositioned);
      lastSignature = signature;
      applyTransform();
      restoreFocus(key);
    }
    const fitKey = `${worldId}:${floor}`;
    if (!fitted.has(fitKey) && container.clientWidth > 0) {
      fitted.add(fitKey);
      fit();
    }
  }

  function renderDragPreview() {
    const worldElement = world();
    const targetElement = worldElement?.querySelector(".grid-map-target");
    if (!worldElement || !targetElement || !drag || !layout) return;
    const deltaX = drag.world.x - drag.startWorld.x;
    const deltaY = drag.world.y - drag.startWorld.y;
    drag.element.style.transform = `translate(${deltaX}px, ${deltaY}px)`;
    const left = (drag.target.x - layout.bounds.minX) * CELL_WIDTH;
    const top = (drag.target.y - layout.bounds.minY) * CELL_HEIGHT;
    targetElement.hidden = false;
    targetElement.style.left = `${left}px`;
    targetElement.style.top = `${top}px`;
    targetElement.classList.toggle("is-invalid", !drag.valid);
  }

  function clearDragPreview() {
    const worldElement = world();
    if (!worldElement || !drag) return;
    drag.element.style.transform = "";
    const targetElement = worldElement.querySelector(".grid-map-target");
    if (targetElement) {
      targetElement.hidden = true;
      targetElement.classList.remove("is-invalid");
    }
  }

  function handleClick(event) {
    const control = event.target.closest("[data-grid-room],[data-grid-floor],[data-grid-zoom],[data-grid-move],[data-grid-create],[data-grid-goto]");
    if (!control) return;
    if (control.hasAttribute("data-grid-room")) {
      if (justDragged) {
        justDragged = false;
        return;
      }
      onSelect?.(control.dataset.gridRoom);
      return;
    }
    if (control.hasAttribute("data-grid-floor")) {
      floor += control.dataset.gridFloor === "up" ? 1 : -1;
      render(lastArgs);
      return;
    }
    if (control.hasAttribute("data-grid-zoom")) {
      const view = viewport();
      const rect = view?.getBoundingClientRect();
      if (rect) zoomAtPoint(control.dataset.gridZoom === "in" ? 1.2 : 1 / 1.2, rect.left + rect.width / 2, rect.top + rect.height / 2);
      return;
    }
    if (control.hasAttribute("data-grid-goto")) {
      floor = Number(control.dataset.gridGoto) || 0;
      render(lastArgs);
      return;
    }
    if (control.hasAttribute("data-grid-move")) {
      const active = activeEntry();
      if (!active) return;
      const delta = control.dataset.gridMove === "up" ? 1 : -1;
      onMove?.(active.id, [active.position[0], active.position[1], active.position[2] + delta]);
      return;
    }
    if (control.hasAttribute("data-grid-create")) onCreateGrid?.();
  }

  function handlePointerDown(event) {
    if (event.isPrimary === false) return;
    const view = event.target.closest?.(".grid-map-viewport");
    if (!view || !layout || !lastArgs) return;
    justDragged = false;
    view.focus({ preventScroll: true });
    const roomElement = event.target.closest?.("[data-grid-room]");
    const point = toWorld(event);
    if (!point) return;
    if (roomElement) {
      const entry = gridRooms(lastArgs.draft).find(candidate => candidate.id === roomElement.dataset.gridRoom);
      if (!entry) return;
      drag = {
        pointerId: event.pointerId,
        roomId: entry.id,
        element: roomElement,
        startWorld: point,
        world: point,
        target: { x: entry.position[0], y: entry.position[1] },
        valid: true,
        moved: false,
        captured: false,
      };
    } else {
      pan = {
        pointerId: event.pointerId,
        startX: event.clientX,
        startY: event.clientY,
        origin: { ...transform },
        moved: false,
        captured: false,
      };
    }
  }

  function capturePointer(event) {
    const view = viewport();
    if (!view) return;
    try {
      view.setPointerCapture(event.pointerId);
    } catch {
      // Pointer capture is a progressive enhancement for drag tracking.
    }
  }

  function handlePointerMove(event) {
    if (drag && event.pointerId === drag.pointerId) {
      const point = toWorld(event);
      if (!point) return;
      drag.world = point;
      if (Math.hypot(point.x - drag.startWorld.x, point.y - drag.startWorld.y) > 4) {
        drag.moved = true;
        if (!drag.captured) {
          drag.captured = true;
          capturePointer(event);
        }
      }
      const cell = cellFromWorld(point);
      drag.target = { x: cell.x, y: cell.y };
      const occupant = roomAt(gridRooms(lastArgs.draft), [cell.x, cell.y, floor], drag.roomId);
      drag.valid = !occupant;
      renderDragPreview();
      return;
    }
    if (pan && event.pointerId === pan.pointerId) {
      if (Math.hypot(event.clientX - pan.startX, event.clientY - pan.startY) > 4) {
        pan.moved = true;
        if (!pan.captured) {
          pan.captured = true;
          capturePointer(event);
        }
      }
      if (!pan.moved) return;
      transform = {
        ...transform,
        x: pan.origin.x + event.clientX - pan.startX,
        y: pan.origin.y + event.clientY - pan.startY,
      };
      applyTransform();
    }
  }

  function handlePointerUp(event) {
    if (drag && event.pointerId === drag.pointerId) {
      const finished = drag;
      const movedRoom = finished.moved;
      const target = { ...finished.target };
      const valid = finished.valid;
      clearDragPreview();
      drag = null;
      justDragged = movedRoom;
      if (movedRoom && valid) {
        const start = gridRooms(lastArgs.draft).find(entry => entry.id === finished.roomId)?.position;
        if (start && (start[0] !== target.x || start[1] !== target.y)) {
          onMove?.(finished.roomId, [target.x, target.y, floor]);
        }
      }
      return;
    }
    if (pan && event.pointerId === pan.pointerId) pan = null;
  }

  function handleWheel(event) {
    if (!event.target.closest?.(".grid-map-viewport")) return;
    event.preventDefault();
    zoomAtPoint(event.deltaY < 0 ? 1.1 : 1 / 1.1, event.clientX, event.clientY);
  }

  function handleKeyDown(event) {
    if (!event.target.closest?.(".grid-map-viewport")) return;
    if (event.ctrlKey || event.metaKey || event.altKey) return;
    const active = activeEntry();
    if (!active) return;
    const [x, y, z] = active.position;
    let target = null;
    if (event.key === "ArrowUp") target = [x, y - 1, z];
    else if (event.key === "ArrowDown") target = [x, y + 1, z];
    else if (event.key === "ArrowLeft") target = [x + 1, y, z];
    else if (event.key === "ArrowRight") target = [x - 1, y, z];
    else if (event.key === "PageUp") target = [x, y, z + 1];
    else if (event.key === "PageDown") target = [x, y, z - 1];
    if (!target) return;
    event.preventDefault();
    onMove?.(active.id, target);
  }

  container.addEventListener("click", handleClick);
  container.addEventListener("pointerdown", handlePointerDown);
  container.addEventListener("pointermove", handlePointerMove);
  container.addEventListener("pointerup", handlePointerUp);
  container.addEventListener("pointercancel", handlePointerUp);
  container.addEventListener("wheel", handleWheel, { passive: false });
  container.addEventListener("keydown", handleKeyDown);

  return { fit, render };
}
