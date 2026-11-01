import assert from "node:assert/strict";
import test from "node:test";

import {
  activityState,
  isSquare,
  movesFrom,
  needsPromotion,
} from "../../worlds/tiny-arcade/activities/chess/model.js";
import {
  applyActivityDelta,
  createParticipantInterpolator,
} from "../../worlds/tiny-arcade/activities/paintball/sync.js";

test("chess squares validate files and ranks", () => {
  assert.equal(isSquare("e4"), true);
  assert.equal(isSquare("i4"), false);
  assert.equal(isSquare("e9"), false);
});

test("chess state selectors expose legal destinations", () => {
  const state = {
    pieces: [{ id: "wP4", code: "wP", square: "e2" }],
    moves: { e2: ["e3", "e4"] },
    hazards: { e4: "threat" },
  };
  assert.deepEqual(movesFrom(state, "e2"), ["e3", "e4"]);
  assert.equal(needsPromotion({ code: "wP" }, "e8"), true);
  assert.equal(needsPromotion({ code: "bP" }, "e1"), true);
  assert.equal(needsPromotion({ code: "wN" }, "e8"), false);
  assert.deepEqual(activityState({ room: { activities: { chess: { kind: "chess", state } } } }), state);
});

test("paintball deltas merge and reject out-of-order frames", () => {
  const base = { seq: 7, t: 1000, participants: [{ id: "u1", x: 10, y: 20 }], projectiles: [], splats: [] };
  const delta = {
    from: 7, seq: 8, t: 1066,
    participants: [{ id: "u1", x: 11.5 }],
    projectiles_add: [{ id: 4, x: 12, y: 20, vx: 70, vy: 0, ttl: 1.1, color: "#ff4d6d" }],
  };
  const next = applyActivityDelta(base, delta);
  assert.equal(next.seq, 8);
  assert.equal(next.participants[0].x, 11.5);
  assert.equal(next.participants[0].y, 20);
  assert.equal(next.projectiles.length, 1);
  assert.equal(applyActivityDelta(next, { ...delta, seq: 9 }), null);
});

test("participant interpolation lerps between authoritative samples", () => {
  const buffer = createParticipantInterpolator({ delayMs: 90 });
  buffer.push([{ id: "u1", x: 0, y: 0 }], 1000);
  buffer.push([{ id: "u1", x: 10, y: 0 }], 1100);
  assert.deepEqual(buffer.sample("u1", 1050), [5, 0]);
  assert.deepEqual(buffer.sample("u1", 1200), [10, 0]);
});
