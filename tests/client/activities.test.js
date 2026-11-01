import assert from "node:assert/strict";
import test from "node:test";

import {
  activityState,
  capturedPieces,
  isSquare,
  movesFrom,
  needsPromotion,
} from "../../worlds/tiny-arcade/activities/chess/model.js";
import { moveCircle, stepVelocity, stickVector } from "../../worlds/tiny-arcade/activities/paintball/arena.js";
import {
  applyActivityDelta,
  createParticipantInterpolator,
  createServerClock,
  projectilePosition,
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

test("captured pieces report missing ids by color", () => {
  const pieces = [{ id: "wP0", code: "wP" }, { id: "bN1", code: "bN" }];
  const captured = capturedPieces(pieces);
  assert.ok(captured.black.includes("P"));
  assert.ok(captured.white.includes("N"));
});

test("arena sticks normalize and deaden small drags", () => {
  const active = stickVector(0, 0, 30, 0, 100);
  assert.equal(active.active, true);
  assert.ok(Math.abs(active.magnitude - 0.3) < 1e-9);
  const idle = stickVector(0, 0, 2, 0, 100);
  assert.equal(idle.active, false);
});

test("arena movement slides along circular obstacles", () => {
  const obstacles = [{ id: "rock", kind: "circle", x: 30, y: 50, r: 5 }];
  const [x, y] = moveCircle(10, 50, 15, 0, 1.8, { width: 100, height: 100 }, obstacles);
  assert.ok(x < 30);
  assert.equal(y, 50);
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

test("projectiles extrapolate from spawn velocity and expire", () => {
  const projectile = { x: 0, y: 0, vx: 100, vy: 0, ttl: 1, spawnT: 1000 };
  assert.deepEqual(projectilePosition(projectile, 1500), [50, 0]);
  assert.equal(projectilePosition(projectile, 2500), null);
  assert.equal(typeof createServerClock().now(), "number");
});

test("projectile drag follows the exponential closed form", () => {
  const projectile = { x: 0, y: 0, vx: 100, vy: 0, ttl: 2, spawnT: 1000 };
  const [x] = projectilePosition(projectile, 2000, 1);
  assert.ok(Math.abs(x - (100 * (1 - Math.exp(-1)))) < 1e-6);
});

test("velocity easing accelerates and brakes", () => {
  const [rampX] = stepVelocity(0, 0, 24, 0, 160, 220, 0.05);
  assert.ok(Math.abs(rampX - 8) < 1e-9);
  const [stopX] = stepVelocity(24, 0, 0, 0, 160, 220, 0.05);
  assert.ok(Math.abs(stopX - 13) < 1e-9);
});
