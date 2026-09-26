import test from "node:test";
import assert from "node:assert/strict";

import { DAMAGE_THRESHOLDS, peepDamageTier } from "../../app/js/peep-damage.js";

const at = (health, maxHealth = 50) => peepDamageTier({ health, maxHealth });

test("thresholds are ordered most-severe first", () => {
  assert.deepEqual(DAMAGE_THRESHOLDS, [[0.05, 4], [0.1, 3], [0.25, 2], [0.5, 1]]);
});

test("a healthy peep has no damage", () => {
  assert.equal(at(50), 0);
  assert.equal(at(37), 0);
  assert.equal(at(100, 100), 0);
});

test("each threshold is exclusive", () => {
  assert.equal(at(25), 0, "exactly 50% stays pristine");
  assert.equal(at(24.99), 1);
  assert.equal(at(12.5), 1, "exactly 25% stays one tier");
  assert.equal(at(12.49), 2);
  assert.equal(at(5), 2, "exactly 10% stays two tiers");
  assert.equal(at(4.99), 3);
  assert.equal(at(2.5), 3, "exactly 5% stays three tiers");
  assert.equal(at(2.49), 4);
  assert.equal(at(0), 4);
});

test("thresholds scale with the effective maximum", () => {
  assert.equal(at(49, 100), 1);
  assert.equal(at(24, 100), 2);
  assert.equal(at(9, 100), 3);
  assert.equal(at(4, 100), 4);
  assert.equal(at(149, 300), 1);
});

test("missing or invalid maxima never damage", () => {
  assert.equal(peepDamageTier(null), 0);
  assert.equal(peepDamageTier(undefined), 0);
  assert.equal(peepDamageTier({}), 0);
  assert.equal(peepDamageTier({ health: 0, maxHealth: 0 }), 0);
  assert.equal(peepDamageTier({ health: 5, maxHealth: -10 }), 0);
  assert.equal(peepDamageTier({ health: Number.NaN, maxHealth: 50 }), 0);
  assert.equal(peepDamageTier({ health: 10, maxHealth: Number.POSITIVE_INFINITY }), 0);
});

test("numeric strings are coerced", () => {
  assert.equal(peepDamageTier({ health: "12", maxHealth: "50" }), 2);
});
