import test from "node:test";
import assert from "node:assert/strict";

import { peepDamageTier } from "../../app/js/peep-damage.js";

const at = (health, maxHealth = 50) => peepDamageTier({ health, maxHealth });

test("maps a health fraction to the cumulative damage tier", () => {
  assert.equal(at(50), 0);
  assert.equal(at(24), 1);
  assert.equal(at(12), 2);
  assert.equal(at(4), 3);
  assert.equal(at(2), 4);
  assert.equal(at(49, 100), 1, "a larger maximum shifts the thresholds");
});

test("treats each threshold as exclusive", () => {
  assert.equal(at(25), 0, "exactly 50% stays pristine");
  assert.equal(at(12.5), 1, "exactly 25% stays one tier");
  assert.equal(at(5), 2, "exactly 10% stays two tiers");
  assert.equal(at(2.5), 3, "exactly 5% stays three tiers");
  assert.equal(at(0), 4);
});
