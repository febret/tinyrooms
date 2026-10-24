import test from "node:test";
import assert from "node:assert/strict";

import { renderProperties } from "../../client/world-editor/js/panels/properties.js";
import { buildBoardRoom } from "../../client/world-editor/js/board-view.js";

function stateWithProp(instance) {
  return {
    draft: {
      rooms: {
        hub: {
          label: "Hub",
          board_image: "hub.png",
          props: { door: { prop: "wood-door", pos: [50, 50, 0], ...instance } },
          exits: {},
        },
      },
    },
    selection: { kind: "prop", id: "hub", sub: "door" },
    catalog: {
      props: [{
        id: "wood-door",
        label: "Wooden door",
        description: "A stock door description.",
        model_url: "/door.glb",
        render_kind: "model",
        scale: 1,
      }],
      activities: [],
      board_images: ["hub.png"],
    },
    editorSettings: {},
  };
}

test("the world editor renders a description override field", () => {
  const html = renderProperties(stateWithProp({ description: "The pink front door." }));
  assert.match(html, /data-instance-field="description"/);
  assert.match(html, /The pink front door\./);
  assert.match(html, /Stock: A stock door description\./);
});

test("the world editor renders a label override field", () => {
  const html = renderProperties(stateWithProp({ label: "Back Door" }));
  assert.match(html, /data-instance-field="label"/);
  assert.match(html, /Back Door/);
  assert.match(html, /Stock: Wooden door/);
});

test("the world editor keeps gameplay fields on the prop definition", () => {
  const state = stateWithProp({});
  state.catalog.props[0].behavior = "dispenser";
  const html = renderProperties(state);
  assert.doesNotMatch(html, /data-instance-field="behavior"/);
  assert.doesNotMatch(html, /data-instance-field="activity"/);
  assert.doesNotMatch(html, /data-instance-field="cooldown"/);
  assert.doesNotMatch(html, /data-instance-field="content"/);
  assert.doesNotMatch(html, /data-instance-field="recipes"/);
  assert.match(html, /behavior: dispenser/);
});

test("the world editor board preview uses the placed prop description", () => {
  const state = stateWithProp({ description: "The pink front door." });
  state.draft.rooms.hub.board_type = "basic";
  const room = buildBoardRoom(state.draft, state.catalog, "hub", "tutorial");
  assert.equal(room.props[0].description, "The pink front door.");
});

test("the world editor board preview uses the placed prop label", () => {
  const state = stateWithProp({ label: "Back Door" });
  state.draft.rooms.hub.board_type = "basic";
  const room = buildBoardRoom(state.draft, state.catalog, "hub", "tutorial");
  assert.equal(room.props[0].label, "Back Door");
});
