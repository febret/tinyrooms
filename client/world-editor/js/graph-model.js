import { uniqueId } from "./util.js";

export const GRAPH_METRICS = { columnWidth: 240, rowGap: 24, headHeight: 44, portHeight: 22, margin: 24 };

function entries(value) {
  return value && typeof value === "object" ? Object.entries(value) : [];
}

function preview(text, length = 60) {
  const value = String(text || "").replace(/\s+/g, " ").trim();
  return value.length > length ? `${value.slice(0, length - 1)}…` : value;
}

export function roomGraph(draft) {
  return {
    rootId: draft?.world?.entry_room || null,
    addLabel: "exit",
    portInputs: true,
    nodes: entries(draft?.rooms).map(([roomId, room]) => ({
      id: roomId,
      title: room?.label || roomId,
      subtitle: roomId,
      ports: entries(room?.exits).map(([exitId, exit]) => ({
        id: exitId,
        label: exit?.label || exitId,
        target: exit?.target || null,
      })),
    })),
  };
}

export function dialogGraph(dialog) {
  return {
    rootId: "start",
    addLabel: "choice",
    nodes: entries(dialog).map(([nodeId, node]) => ({
      id: nodeId,
      title: nodeId,
      subtitle: preview(node?.text),
      ports: (Array.isArray(node?.choices) ? node.choices : []).map((choice, index) => ({
        id: String(index),
        label: choice?.label || `Choice ${index + 1}`,
        target: choice?.end ? null : choice?.next || null,
      })),
    })),
  };
}

export function graphLinks(graph) {
  const byId = new Map(graph.nodes.map(node => [node.id, node]));
  const paired = new Set();
  const links = [];
  for (const node of graph.nodes) {
    for (const port of node.ports) {
      if (!byId.has(port.target) || paired.has(`${node.id}\n${port.id}`)) continue;
      const reverse = graph.portInputs && port.target !== node.id
        ? byId.get(port.target).ports.find(other => other.target === node.id && !paired.has(`${port.target}\n${other.id}`))
        : null;
      if (reverse) paired.add(`${port.target}\n${reverse.id}`);
      links.push({ from: node.id, port: port.id, to: port.target, toPort: reverse?.id ?? null });
    }
  }
  return links;
}

export function layoutGraph(graph, saved = new Map()) {
  const { columnWidth, rowGap, headHeight, portHeight, margin } = GRAPH_METRICS;
  const byId = new Map(graph.nodes.map(node => [node.id, node]));
  const depth = new Map();
  const order = [];
  const queue = [];
  if (byId.has(graph.rootId)) {
    depth.set(graph.rootId, 0);
    queue.push(graph.rootId);
  }
  while (queue.length) {
    const id = queue.shift();
    order.push(id);
    for (const port of byId.get(id).ports) {
      if (!byId.has(port.target) || depth.has(port.target)) continue;
      depth.set(port.target, depth.get(id) + 1);
      queue.push(port.target);
    }
  }
  const orphanColumn = depth.size ? Math.max(...depth.values()) + 1 : 0;
  const columnTops = [];
  const positions = new Map();
  for (const node of [...order.map(id => byId.get(id)), ...graph.nodes.filter(node => !depth.has(node.id))]) {
    const column = depth.get(node.id) ?? orphanColumn;
    const top = columnTops[column] ?? margin;
    positions.set(node.id, saved.get(node.id) || { x: margin + column * columnWidth, y: top });
    columnTops[column] = top + headHeight + (node.ports.length + 1) * portHeight + rowGap;
  }
  return positions;
}

export function removeRoom(draft, roomId) {
  if (!draft.rooms?.[roomId]) return false;
  delete draft.rooms[roomId];
  for (const room of Object.values(draft.rooms)) {
    for (const [exitId, exit] of entries(room?.exits)) {
      if (exit?.target === roomId) delete room.exits[exitId];
    }
  }
  if (draft.world?.entry_room === roomId) draft.world.entry_room = Object.keys(draft.rooms)[0] || "";
  return true;
}

export function applyRoomGraphChanges(draft, changes) {
  let changed = false;
  for (const change of changes) {
    const room = draft.rooms?.[change.from];
    if (change.type === "remove") {
      changed = removeRoom(draft, change.node) || changed;
    } else if (change.type === "link" && room && draft.rooms[change.to]) {
      if (!room.exits || typeof room.exits !== "object") room.exits = {};
      const exit = change.port === null ? null : room.exits[change.port];
      if (exit) exit.target = change.to;
      else room.exits[uniqueId(Object.keys(room.exits), "exit")] = { label: draft.rooms[change.to].label || change.to, target: change.to };
      const reverse = change.toPort == null ? null : draft.rooms[change.to].exits?.[change.toPort];
      if (reverse) reverse.target = change.from;
      changed = true;
    } else if (change.type === "unlink") {
      const reverse = change.toPort == null ? null : draft.rooms?.[change.to]?.exits?.[change.toPort];
      if (reverse?.target === change.from) {
        delete draft.rooms[change.to].exits[change.toPort];
        changed = true;
      }
      if (room?.exits?.[change.port]?.target === change.to) {
        delete room.exits[change.port];
        changed = true;
      }
    }
  }
  return changed;
}

function endChoice(choice) {
  delete choice.next;
  choice.end = true;
}

export function applyDialogGraphChanges(dialog, changes) {
  if (!dialog || typeof dialog !== "object") return false;
  let changed = false;
  for (const change of changes) {
    const node = dialog[change.from];
    if (change.type === "remove") {
      if (change.node === "start" || !dialog[change.node]) continue;
      delete dialog[change.node];
      for (const other of Object.values(dialog)) {
        for (const choice of other?.choices || []) {
          if (choice?.next === change.node) endChoice(choice);
        }
      }
      changed = true;
    } else if (change.type === "link" && node && dialog[change.to]) {
      if (!Array.isArray(node.choices)) node.choices = [];
      const choice = change.port === null ? null : node.choices[Number(change.port)];
      if (choice) {
        delete choice.end;
        choice.next = change.to;
      } else {
        node.choices.push({ label: "Choice", next: change.to });
      }
      changed = true;
    } else if (change.type === "unlink") {
      const choice = node?.choices?.[Number(change.port)];
      if (choice?.next === change.to) {
        endChoice(choice);
        changed = true;
      }
    }
  }
  return changed;
}
