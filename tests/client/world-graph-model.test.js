import test from "node:test";
import assert from "node:assert/strict";

import {
  applyDialogGraphChanges,
  applyRoomGraphChanges,
  dialogGraph,
  graphLinks,
  layoutGraph,
  roomGraph,
} from "../../world-editor/js/graph-model.js";

function draft() {
  return {
    world: { entry_room: "hub" },
    rooms: {
      hub: { label: "Hub", exits: { portal: { label: "Portal", target: "play" } } },
      play: { label: "Play", exits: { back: { label: "Back", target: "hub" }, broken: { target: "missing" } } },
      attic: { label: "Attic" },
    },
  };
}

function dialog() {
  return {
    start: { text: "Hi", choices: [{ label: "More", next: "more" }, { label: "Bye", end: true }] },
    more: { text: "Details", choices: [{ label: "Back", next: "start" }] },
    stray: { text: "Unreached", choices: [] },
  };
}

test("room graph exposes exits as ordered ports and only links known rooms", () => {
  const graph = roomGraph(draft());
  assert.equal(graph.rootId, "hub");
  assert.deepEqual(graph.nodes.map(node => node.id), ["hub", "play", "attic"]);
  assert.deepEqual(graph.nodes[1].ports.map(port => [port.id, port.label, port.target]), [
    ["back", "Back", "hub"],
    ["broken", "broken", "missing"],
  ]);
  assert.deepEqual(graphLinks(graph), [
    { from: "hub", port: "portal", to: "play", toPort: "back" },
  ]);
});

test("two-way exits pair once, extra exits stay one-way, and dialogs never pair", () => {
  const value = draft();
  value.rooms.hub.exits.again = { target: "play" };
  value.rooms.attic.exits = { up: { target: "hub" } };
  assert.deepEqual(graphLinks(roomGraph(value)), [
    { from: "hub", port: "portal", to: "play", toPort: "back" },
    { from: "hub", port: "again", to: "play", toPort: null },
    { from: "attic", port: "up", to: "hub", toPort: null },
  ]);
  assert.deepEqual(graphLinks(dialogGraph(dialog())).map(link => link.toPort), [null, null]);
});

test("dialog graph exposes choices as ports and end choices as unlinked", () => {
  const graph = dialogGraph(dialog());
  assert.equal(graph.rootId, "start");
  assert.deepEqual(graph.nodes[0].ports.map(port => [port.id, port.target]), [["0", "more"], ["1", null]]);
  assert.equal(graph.nodes[1].subtitle, "Details");
});

test("layout places nodes in breadth-first columns with orphans last and keeps saved positions", () => {
  const graph = dialogGraph(dialog());
  const positions = layoutGraph(graph);
  assert.ok(positions.get("start").x < positions.get("more").x);
  assert.ok(positions.get("more").x < positions.get("stray").x);
  const saved = new Map([["more", { x: 5, y: 7 }]]);
  assert.deepEqual(layoutGraph(graph, saved).get("more"), { x: 5, y: 7 });
});

test("room graph links retarget exits, add exits, and unlink deletes them", () => {
  const value = draft();
  assert.equal(applyRoomGraphChanges(value, [{ type: "link", from: "hub", port: "portal", to: "attic" }]), true);
  assert.equal(value.rooms.hub.exits.portal.target, "attic");
  applyRoomGraphChanges(value, [{ type: "link", from: "attic", port: null, to: "hub" }]);
  assert.deepEqual(value.rooms.attic.exits, { "exit-1": { label: "Hub", target: "hub" } });
  applyRoomGraphChanges(value, [{ type: "unlink", from: "play", port: "back", to: "hub" }]);
  assert.equal(value.rooms.play.exits.back, undefined);
  assert.equal(applyRoomGraphChanges(value, [{ type: "unlink", from: "play", port: "broken", to: "hub" }]), false);
});

test("linking onto an exit input pairs both exits and unlinking a pair removes both", () => {
  const value = draft();
  value.rooms.attic.exits = { down: { label: "Down", target: "attic" } };
  applyRoomGraphChanges(value, [{ type: "link", from: "play", port: null, to: "attic", toPort: "down" }]);
  assert.equal(value.rooms.play.exits["exit-1"].target, "attic");
  assert.equal(value.rooms.attic.exits.down.target, "play");
  applyRoomGraphChanges(value, [{ type: "unlink", from: "hub", port: "portal", to: "play", toPort: "back" }]);
  assert.equal(value.rooms.hub.exits.portal, undefined);
  assert.equal(value.rooms.play.exits.back, undefined);
});

test("removing a room node clears inbound exits and repairs the entry room", () => {
  const value = draft();
  assert.equal(applyRoomGraphChanges(value, [{ type: "remove", node: "hub" }]), true);
  assert.deepEqual(Object.keys(value.rooms), ["play", "attic"]);
  assert.deepEqual(Object.keys(value.rooms.play.exits), ["broken"]);
  assert.equal(value.world.entry_room, "play");
});

test("dialog graph edits set next, add choices, end unlinked choices, and protect start", () => {
  const value = dialog();
  applyDialogGraphChanges(value, [{ type: "link", from: "start", port: "1", to: "stray" }]);
  assert.deepEqual(value.start.choices[1], { label: "Bye", next: "stray" });
  applyDialogGraphChanges(value, [{ type: "link", from: "stray", port: null, to: "start" }]);
  assert.deepEqual(value.stray.choices, [{ label: "Choice", next: "start" }]);
  applyDialogGraphChanges(value, [{ type: "unlink", from: "start", port: "0", to: "more" }]);
  assert.deepEqual(value.start.choices[0], { label: "More", end: true });
  assert.equal(applyDialogGraphChanges(value, [{ type: "remove", node: "start" }]), false);
  applyDialogGraphChanges(value, [{ type: "remove", node: "stray" }]);
  assert.equal(value.stray, undefined);
  assert.deepEqual(value.start.choices[1], { label: "Bye", end: true });
});
