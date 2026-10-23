import test from "node:test";
import assert from "node:assert/strict";

import { layoutPeeps } from "../../client/app/js/peep-groups.js";

test("the dialoging peep stays visible when overflow peeps are grouped", () => {
  const peeps = Array.from({ length: 7 }, (_, index) => ({ id: `peep-${index}` }));
  const layout = layoutPeeps(peeps, { dialogId: "peep-4", limit: 5 });

  assert.ok(layout.visible.some(peep => peep.id === "peep-4"));
  assert.ok(!layout.grouped.some(peep => peep.id === "peep-4"));
});
