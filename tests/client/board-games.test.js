import assert from "node:assert/strict";
import test from "node:test";

import { boardPositionToSquare, gridConfig, squareToBoardPosition } from "../../client/app/js/board/board-games/grid-geometry.js";
import { boardCoordinate } from "../../client/app/js/board/board-games/paintball.js";

const CONFIG = {
  columns: 8,
  rows: 8,
  origin: [22, 15],
  size: [56, 69.2],
};

test("gridConfig validates the renderer-owned layout", () => {
  assert.deepEqual(gridConfig(CONFIG), CONFIG);
  assert.equal(gridConfig({ ...CONFIG, columns: 0 }), null);
  assert.equal(gridConfig({ ...CONFIG, size: [0, 10] }), null);
  assert.equal(gridConfig(null), null);
});

test("squareToBoardPosition puts a8 at the far-left corner and h1 at the near-right", () => {
  const a8 = squareToBoardPosition(CONFIG, "a8");
  assert.ok(Math.abs(a8[0] - 25.5) < 1e-9);
  assert.ok(Math.abs(a8[1] - 19.325) < 1e-9);
  const h1 = squareToBoardPosition(CONFIG, "h1");
  assert.ok(Math.abs(h1[0] - 74.5) < 1e-9);
  assert.ok(Math.abs(h1[1] - 79.875) < 1e-9);
  assert.equal(squareToBoardPosition(CONFIG, "i1"), null);
  assert.equal(squareToBoardPosition(CONFIG, "a9"), null);
});

test("boardPositionToSquare reverses square centers", () => {
  for (const square of ["a1", "e2", "d4", "h8"]) {
    const position = squareToBoardPosition(CONFIG, square);
    assert.equal(boardPositionToSquare(CONFIG, position), square);
  }
  assert.equal(boardPositionToSquare(CONFIG, [0, 0]), "");
});

test("paintball board coordinates preserve zero and reject malformed values", () => {
  assert.equal(boardCoordinate(0), 0);
  assert.equal(boardCoordinate("0"), 0);
  assert.equal(boardCoordinate(42), 42);
  assert.equal(boardCoordinate(null), 50);
  assert.equal(boardCoordinate(undefined), 50);
  assert.equal(boardCoordinate(""), 50);
  assert.equal(boardCoordinate("nope"), 50);
  assert.equal(boardCoordinate(Number.NaN), 50);
});
