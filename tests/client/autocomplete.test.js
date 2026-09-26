import test from "node:test";
import assert from "node:assert/strict";

import { activeToken, commandCompletions, identifierCompletions } from "../../app/js/autocomplete.js";

const CATALOG = [
  { name: ".pickup", usage: ".pickup @card:<stack> <qty>", summary: "Pick up a room stack quantity.", power: null },
  { name: ".drop", usage: ".drop @card:<stack> <qty> [x y z]", summary: "Drop an owned stack quantity.", power: null },
  { name: ".merge", usage: ".merge @card:<from> @card:<to> [quantity]", summary: "Merge two stacks.", power: "builder" },
];

const STATE = {
  user: {
    powers: [],
    journal: { memories: [{ memoryId: "mem1", author: "sunbeam", text: "First light over the hub" }] },
  },
  room: {
    occupants: [{ id: "acct-1", username: "sunbeam", label: "sunbeam" }],
    npcs: [{ id: "molly", label: "Molly", description: "A watchful mole" }],
    roomCards: [{ stackId: "room:abc", definition: { label: "Copper Coin" } }],
    inventory: [{ stackId: "inv:xyz", definition: { label: "Copper Coin" } }],
    props: [{ id: "portal0", label: "A Glowing Portal", description: "A familiar doorway." }],
    exits: [{ id: "exit0", label: "Cross the portal", targetRoomId: "playroom" }],
  },
};

test("activeToken returns the whitespace-delimited run at the caret", () => {
  assert.deepEqual(activeToken(".pick", 5), { start: 0, end: 5, token: ".pick" });
  assert.deepEqual(activeToken(".go @w", 6), { start: 4, end: 6, token: "@w" });
  assert.deepEqual(activeToken(".pickup ", 8), { start: 8, end: 8, token: "" });
  assert.deepEqual(activeToken("", 0), { start: 0, end: 0, token: "" });
});

test("commandCompletions filters by name prefix and hides gated commands", () => {
  const items = commandCompletions(CATALOG, new Set(), "pick");
  assert.equal(items.length, 1);
  assert.equal(items[0].label, ".pickup");
  assert.equal(items[0].insert, ".pickup ");
  assert.equal(items[0].detail, ".pickup @card:<stack> <qty>");
  assert.equal(items[0].summary, "Pick up a room stack quantity.");
});

test("commandCompletions includes gated commands only with the matching power", () => {
  assert.deepEqual(commandCompletions(CATALOG, new Set(), "merge"), []);
  const items = commandCompletions(CATALOG, new Set(["builder"]), "merge");
  assert.equal(items[0].label, ".merge");
});

test("commandCompletions normalizes placeholder-laden fallback names", () => {
  const items = commandCompletions([{ name: ".merge @card:<src> @card:<dst> [qty]", summary: "Merge two stacks." }], new Set(), "merge");
  assert.equal(items[0].label, ".merge");
  assert.equal(items[0].insert, ".merge ");
});

test("identifierCompletions offers @-kind tokens for a bare @ prefix", () => {
  assert.ok(identifierCompletions(STATE, "@w").some(item => item.insert === "@way:"));
  assert.ok(identifierCompletions(STATE, "@m").some(item => item.insert === "@memory:"));
  assert.deepEqual(identifierCompletions(STATE, "@nope:"), []);
});

test("identifierCompletions offers bare peep mentions", () => {
  assert.ok(identifierCompletions(STATE, "@su").some(item => item.insert === "@sunbeam "));
});

test("identifierCompletions resolves props, cards, peeps, ways, and memories", () => {
  assert.deepEqual(identifierCompletions(STATE, "@prop:por").map(item => item.insert), ["@prop:portal0 "]);
  assert.deepEqual(
    identifierCompletions(STATE, "@card:").map(item => item.insert),
    ["@card:room:abc ", "@card:inv:xyz "],
  );
  const peeps = identifierCompletions(STATE, "@peep:");
  assert.deepEqual(peeps.map(item => item.insert), ["@peep:acct-1 ", "@peep:molly "]);
  assert.deepEqual(peeps.map(item => item.label), ["sunbeam", "Molly"]);
  assert.deepEqual(identifierCompletions(STATE, "@way:exit").map(item => item.insert), ["@way:exit0 "]);
  assert.deepEqual(identifierCompletions(STATE, "@memory:mem").map(item => item.insert), ["@memory:mem1 "]);
});
