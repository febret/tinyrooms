import test from "node:test";
import assert from "node:assert/strict";

import { buildBeaconCommand } from "../../client/app/js/commands.js";
import { createStore } from "../../client/app/js/state.js";

test("beacon commands target friends and support listing", () => {
  assert.equal(buildBeaconCommand("send", "friend-1"), ".beacon send @peep:friend-1");
  assert.equal(buildBeaconCommand("use", "friend-1"), ".beacon use @peep:friend-1");
  assert.equal(buildBeaconCommand("dismiss", "friend-1"), ".beacon dismiss @peep:friend-1");
  assert.equal(buildBeaconCommand("list"), ".beacon list");
});

test("bootstrap normalizes incoming beacons", () => {
  const store = createStore();
  store.dispatch({
    type: "bootstrap",
    user: {
      id: "self",
      inventory: [],
      beacons: [
        {
          from_account_id: "friend-1",
          from_username: "Pip",
          world_id: "scammon-academia",
          world_label: "Scammon Academy",
          room_id: "cafeteria",
          room_label: "The Cafeteria",
          created_at: "2026-10-20T10:00:00Z",
          cross_world: true,
        },
      ],
    },
  });

  assert.deepEqual(store.getState().user.beacons, [
    {
      fromAccountId: "friend-1",
      fromUsername: "Pip",
      worldId: "scammon-academia",
      worldLabel: "Scammon Academy",
      roomId: "cafeteria",
      roomLabel: "The Cafeteria",
      createdAt: "2026-10-20T10:00:00Z",
      crossWorld: true,
    },
  ]);
});
