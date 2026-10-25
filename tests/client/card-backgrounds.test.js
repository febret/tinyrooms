import test from "node:test";
import assert from "node:assert/strict";

import { cardFaceSvg } from "../../client/app/js/card-face.js";
import { cardBackground, cardBackgroundGroup } from "../../client/app/js/card-style.js";
import { cardBackdropStyle } from "../../client/app/js/views/view-helpers.js";

test("background groups mirror the server resolver", () => {
  assert.equal(cardBackgroundGroup({ rarity: "Legendary", tags: ["supermarket", "food"] }), "food");
  assert.equal(cardBackgroundGroup({ rarity: "Common", tags: ["paintball-ammo", "paintball-color-cherry"] }), "paint");
  assert.equal(cardBackgroundGroup({ rarity: "Common", tags: ["subject:reading"] }), "subject");
  assert.equal(cardBackgroundGroup({ rarity: "Common", tags: ["skill:math"] }), "subject");
  assert.equal(cardBackgroundGroup({ rarity: "Common", tags: ["topic"] }), "topic");
  assert.equal(cardBackgroundGroup({ rarity: "Common", tags: ["medicine"] }), "medicine");
  assert.equal(cardBackgroundGroup({ rarity: "Common", tags: ["utility"] }), "utility");
  assert.equal(cardBackgroundGroup({ rarity: "Epic", tags: [] }), "epic");
  assert.equal(cardBackgroundGroup({ rarity: "bogus", tags: [] }), "common");
});

test("background URLs resolve to the card-backgrounds asset set", () => {
  assert.equal(cardBackground({ rarity: "Rare", tags: [] }).url, "/assets/card-backgrounds/bg-rarity-rare.png");
  assert.equal(cardBackground({ rarity: "Common", tags: ["food"] }).url, "/assets/card-backgrounds/bg-tag-food.png");
});

test("explicit server background URLs win over the local fallback", () => {
  const resolved = cardBackground({ rarity: "Common", tags: [], backgroundUrl: "/assets/card-backgrounds/bg-tag-paint.png" });
  assert.equal(resolved.url, "/assets/card-backgrounds/bg-tag-paint.png");
});

test("card faces layer the backdrop under a contained subject", () => {
  const svg = cardFaceSvg(
    { label: "Carrot", description: "Crunchy.", type: "item", rarity: "Common", tags: ["food"], imageUrl: "/assets/supermarket/market-carrot.png" },
    { idPrefix: "bgtest" },
  );
  const backdropIndex = svg.indexOf("bg-tag-food.png");
  const subjectIndex = svg.indexOf("market-carrot.png");
  assert.ok(backdropIndex !== -1, "expected the themed backdrop in the art box");
  assert.ok(subjectIndex !== -1, "expected the subject art in the art box");
  assert.ok(backdropIndex < subjectIndex, "expected the backdrop to layer under the subject");
  assert.ok(svg.includes('preserveAspectRatio="xMidYMid slice"'), "backdrop fills the box");
  assert.ok(svg.includes('preserveAspectRatio="xMidYMid meet"'), "subject is contained, not cropped");
});

test("illustration backdrops reuse the themed background", () => {
  const style = cardBackdropStyle({ rarity: "Rare", tags: [], backgroundUrl: "" });
  assert.ok(style.includes("/assets/card-backgrounds/bg-rarity-rare.png"), style);
});
