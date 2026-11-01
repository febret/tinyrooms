export const GRID_DIRECTIONS = {
  north: [0, -1, 0],
  south: [0, 1, 0],
  east: [-1, 0, 0],
  west: [1, 0, 0],
  up: [0, 0, 1],
  down: [0, 0, -1],
};

export const GRID_DIRECTION_ORDER = ["north", "south", "east", "west", "up", "down"];
export const INT32_MIN = -(2 ** 31);
export const INT32_MAX = 2 ** 31 - 1;

const SEARCH_LIMIT = 96;

function isRoomObject(room) {
  return Boolean(room) && typeof room === "object";
}

export function parseGridPoint(raw) {
  let values = null;
  if (Array.isArray(raw) && raw.length === 3) values = raw;
  else if (isRoomObject(raw) && !Array.isArray(raw)) values = [raw.x, raw.y, raw.z];
  if (!values) return null;
  const point = [];
  for (const value of values) {
    if (typeof value !== "number" || !Number.isInteger(value)) return null;
    point.push(value);
  }
  if (point.length !== 3 || !inGridRange(point)) return null;
  return point;
}

export function inGridRange(point) {
  return point.every(value => value >= INT32_MIN && value <= INT32_MAX);
}

export function liveRooms(draft) {
  return Object.entries(draft?.rooms || {})
    .filter(([, room]) => isRoomObject(room) && !room.template)
    .map(([id, room]) => ({ id, room }));
}

export function gridRooms(draft) {
  return liveRooms(draft)
    .map(({ id, room }) => ({
      id,
      room,
      label: room.label || id,
      position: parseGridPoint(room.grid),
    }))
    .filter(entry => entry.position);
}

export function missingGridRooms(draft) {
  const positioned = new Set(gridRooms(draft).map(entry => entry.id));
  return liveRooms(draft)
    .filter(({ id }) => !positioned.has(id))
    .map(({ id }) => id);
}

export function cellKey(point) {
  return `${point[0]},${point[1]},${point[2]}`;
}

export function addPoints(point, vector) {
  return [point[0] + vector[0], point[1] + vector[1], point[2] + vector[2]];
}

function inverseVector(vector) {
  return [-vector[0], -vector[1], -vector[2]];
}

export function directionBetween(source, target) {
  if (!source || !target) return null;
  const delta = [target[0] - source[0], target[1] - source[1], target[2] - source[2]];
  for (const direction of GRID_DIRECTION_ORDER) {
    const vector = GRID_DIRECTIONS[direction];
    if (vector[0] === delta[0] && vector[1] === delta[1] && vector[2] === delta[2]) return direction;
  }
  return null;
}

export function buildOccupancy(entries) {
  const occupancy = new Map();
  for (const entry of entries) occupancy.set(cellKey(entry.position), entry.id);
  return occupancy;
}

export function roomAt(entries, point, exceptId = null) {
  const key = cellKey(point);
  return entries.find(entry => entry.id !== exceptId && cellKey(entry.position) === key) || null;
}

export function floorRooms(entries, floor) {
  return entries.filter(entry => entry.position[2] === floor);
}

export function gridBounds(entries) {
  if (!entries.length) return null;
  const xs = entries.map(entry => entry.position[0]);
  const ys = entries.map(entry => entry.position[1]);
  return {
    minX: Math.min(...xs),
    maxX: Math.max(...xs),
    minY: Math.min(...ys),
    maxY: Math.max(...ys),
  };
}

export function floorLinks(entries, floor) {
  const rooms = floorRooms(entries, floor);
  const occupancy = buildOccupancy(rooms);
  const links = [];
  for (const entry of rooms) {
    for (const direction of ["north", "south", "east", "west"]) {
      const neighborId = occupancy.get(cellKey(addPoints(entry.position, GRID_DIRECTIONS[direction])));
      if (neighborId && entry.id < neighborId) links.push({ from: entry.id, to: neighborId, direction });
    }
  }
  return links;
}

export function verticalNeighbors(entries, roomId) {
  const room = entries.find(entry => entry.id === roomId);
  if (!room) return { above: [], below: [] };
  const above = [];
  const below = [];
  for (const entry of entries) {
    if (entry.id === roomId || entry.position[0] !== room.position[0] || entry.position[1] !== room.position[1]) continue;
    if (entry.position[2] > room.position[2]) above.push(entry);
    if (entry.position[2] < room.position[2]) below.push(entry);
  }
  above.sort((a, b) => a.position[2] - b.position[2]);
  below.sort((a, b) => b.position[2] - a.position[2]);
  return { above, below };
}

export function customExitLinks(draft, roomId) {
  const entries = gridRooms(draft);
  const byId = new Map(entries.map(entry => [entry.id, entry]));
  const room = byId.get(roomId);
  const exits = room?.room.exits;
  if (!room || !isRoomObject(exits)) return [];
  const links = [];
  for (const [exitId, exit] of Object.entries(exits)) {
    if (!isRoomObject(exit) || typeof exit.target !== "string") continue;
    const target = byId.get(exit.target);
    if (!target || directionBetween(room.position, target.position)) continue;
    links.push({ exit: exitId, label: exit.label || exitId, from: roomId, to: target.id });
  }
  return links;
}

export function repairDirectionalExits(draft) {
  const entries = gridRooms(draft);
  const occupancy = buildOccupancy(entries);
  const retargeted = [];
  const removed = [];
  const detachedProps = [];
  for (const entry of entries) {
    const exits = entry.room.exits;
    if (!isRoomObject(exits)) continue;
    for (const direction of GRID_DIRECTION_ORDER) {
      const exit = exits[direction];
      if (!isRoomObject(exit)) continue;
      if (typeof exit.target_world === "string" && exit.target_world) continue;
      const neighborId = occupancy.get(cellKey(addPoints(entry.position, GRID_DIRECTIONS[direction])));
      if (neighborId) {
        if (exit.target !== neighborId) {
          const previous = typeof exit.target === "string" ? exit.target : "";
          exit.target = neighborId;
          retargeted.push({ room: entry.id, exit: direction, from: previous, to: neighborId });
        }
        continue;
      }
      const previousTarget = typeof exit.target === "string" ? exit.target : "";
      delete exits[direction];
      removed.push({ room: entry.id, exit: direction, target: previousTarget });
      for (const [instanceId, instance] of Object.entries(entry.room.props || {})) {
        if (isRoomObject(instance) && instance.exit_to === direction) {
          delete instance.exit_to;
          detachedProps.push({ room: entry.id, prop: instanceId, exit: direction });
        }
      }
    }
  }
  return { retargeted, removed, detachedProps };
}

export function moveRoom(draft, roomId, target) {
  const rooms = draft?.rooms;
  const room = isRoomObject(rooms) ? rooms[roomId] : null;
  if (!room) return { ok: false, reason: "missing" };
  if (room.template) return { ok: false, reason: "template" };
  const point = parseGridPoint(target);
  if (!point) return { ok: false, reason: "invalid" };
  const occupant = roomAt(gridRooms(draft), point, roomId);
  if (occupant) return { ok: false, reason: "occupied", occupant: occupant.id };
  room.grid = [...point];
  const repair = repairDirectionalExits(draft);
  return { ok: true, position: [...point], ...repair };
}

function firstFreeNeighbor(seed, occupancy, allowedId = null, strict = true) {
  for (const direction of GRID_DIRECTION_ORDER) {
    const candidate = addPoints(seed, GRID_DIRECTIONS[direction]);
    if (!inGridRange(candidate) || occupancy.has(cellKey(candidate))) continue;
    if (strict && allowedId !== null) {
      let touchesOther = false;
      for (const vector of Object.values(GRID_DIRECTIONS)) {
        const neighborId = occupancy.get(cellKey(addPoints(candidate, vector)));
        if (neighborId && neighborId !== allowedId) {
          touchesOther = true;
          break;
        }
      }
      if (touchesOther) continue;
    }
    return candidate;
  }
  return null;
}

function findFreeCell(occupancy, seed, { isolated = false, limit = SEARCH_LIMIT } = {}) {
  for (let radius = 0; radius <= limit; radius += 1) {
    for (let dx = -radius; dx <= radius; dx += 1) {
      for (let dy = -radius; dy <= radius; dy += 1) {
        for (let dz = isolated ? 0 : -radius; dz <= (isolated ? 0 : radius); dz += 1) {
          const distance = isolated
            ? Math.max(Math.abs(dx), Math.abs(dy))
            : Math.max(Math.abs(dx), Math.abs(dy), Math.abs(dz));
          if (distance !== radius) continue;
          const candidate = [seed[0] + dx, seed[1] + dy, seed[2] + dz];
          if (!inGridRange(candidate) || occupancy.has(cellKey(candidate))) continue;
          if (!isolated) return candidate;
          const touches = Object.values(GRID_DIRECTIONS).some(vector => occupancy.has(cellKey(addPoints(candidate, vector))));
          if (!touches) return candidate;
        }
      }
    }
  }
  return null;
}

function findFreeCellNear(occupancy, seed, limit = SEARCH_LIMIT) {
  return findFreeCell(occupancy, seed, { limit });
}

function findIsolatedFreeCell(occupancy, origin = [0, 0, 0], limit = SEARCH_LIMIT) {
  return findFreeCell(occupancy, origin, { isolated: true, limit });
}

function exitTargets(room, liveIds) {
  const exits = isRoomObject(room.exits) ? Object.entries(room.exits) : [];
  return exits
    .filter(([, exit]) => isRoomObject(exit) && typeof exit.target === "string" && liveIds.has(exit.target))
    .map(([exitId, exit]) => ({ exitId, target: exit.target }));
}

function placeLinkedOrIsolated(draft, roomId, room, placed, occupancy) {
  const liveIds = new Set(liveRooms(draft).map(entry => entry.id));
  for (const { exitId, target } of exitTargets(room, liveIds)) {
    const seed = placed.get(target);
    if (!seed) continue;
    if (GRID_DIRECTIONS[exitId]) {
      const candidate = addPoints(seed, inverseVector(GRID_DIRECTIONS[exitId]));
      if (inGridRange(candidate) && !occupancy.has(cellKey(candidate))) return candidate;
      continue;
    }
    const candidate = firstFreeNeighbor(seed, occupancy, target, true);
    if (candidate) return candidate;
  }
  for (const [placedId, seed] of placed) {
    const placedRoom = draft?.rooms?.[placedId];
    if (!isRoomObject(placedRoom)) continue;
    for (const { exitId, target } of exitTargets(placedRoom, liveIds)) {
      if (target !== roomId) continue;
      if (GRID_DIRECTIONS[exitId]) {
        const candidate = addPoints(seed, GRID_DIRECTIONS[exitId]);
        if (inGridRange(candidate) && !occupancy.has(cellKey(candidate))) return candidate;
        continue;
      }
      const candidate = firstFreeNeighbor(seed, occupancy, placedId, true);
      if (candidate) return candidate;
    }
  }
  return findIsolatedFreeCell(occupancy);
}

function graphInitialPositions(draft, rooms) {
  const placed = new Map();
  const occupancy = new Map();
  const liveIds = rooms.map(({ id }) => id);
  const entryId = typeof draft?.world?.entry_room === "string" ? draft.world.entry_room : "";
  const seedId = liveIds.includes(entryId) ? entryId : liveIds[0];
  placed.set(seedId, [0, 0, 0]);
  occupancy.set(cellKey([0, 0, 0]), seedId);
  for (const { id, room } of rooms) {
    if (placed.has(id)) continue;
    const candidate = placeLinkedOrIsolated(draft, id, room, placed, occupancy) || findFreeCellNear(occupancy, [0, 0, 0]);
    if (!candidate) continue;
    placed.set(id, candidate);
    occupancy.set(cellKey(candidate), id);
  }
  return Object.fromEntries(placed);
}

export function nextFreeCell(draft, { anchorId = null } = {}) {
  const entries = gridRooms(draft);
  if (!entries.length) return null;
  const anchor = entries.find(entry => entry.id === anchorId) || entries[0];
  const occupancy = buildOccupancy(entries);
  return firstFreeNeighbor(anchor.position, occupancy, anchor.id, true)
    || findFreeCellNear(occupancy, anchor.position);
}

export function ensureGridLayout(draft) {
  const rooms = liveRooms(draft);
  if (!rooms.length) return { created: 0, positions: {} };
  const existing = gridRooms(draft);
  if (!existing.length) {
    const positions = graphInitialPositions(draft, rooms);
    for (const { id, room } of rooms) {
      if (positions[id]) room.grid = [...positions[id]];
    }
    return { created: rooms.length, positions };
  }
  const placed = new Map(existing.map(entry => [entry.id, [...entry.position]]));
  const occupancy = buildOccupancy(existing);
  const positions = {};
  for (const { id, room } of rooms) {
    if (placed.has(id)) continue;
    const candidate = placeLinkedOrIsolated(draft, id, room, placed, occupancy) || findFreeCellNear(occupancy, [0, 0, 0]);
    if (!candidate) continue;
    room.grid = [...candidate];
    placed.set(id, [...candidate]);
    occupancy.set(cellKey(candidate), id);
    positions[id] = [...candidate];
  }
  return { created: Object.keys(positions).length, positions };
}
