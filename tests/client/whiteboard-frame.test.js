import test from "node:test";
import assert from "node:assert/strict";

import {
  DEFAULT_FRAME,
  FRAME_INNERS,
  FRAME_MATTES,
  FRAME_OUTERS,
  frameLayout,
  normalizeFrame,
} from "../../client/app/js/whiteboard-frame.js";

test("whiteboard frame offers five options for outer, inner, and matte styles", () => {
  assert.equal(FRAME_OUTERS.length, 5);
  assert.equal(FRAME_INNERS.length, 5);
  assert.equal(FRAME_MATTES.length, 5);
  assert.deepEqual(normalizeFrame(null), { ...DEFAULT_FRAME });
});

test("frame normalization falls back for unknown styles and colors", () => {
  const frame = normalizeFrame({
    outer: "marble",
    inner: "double",
    matte: "gallery",
    main: "red",
    accent: "#C9A45C",
  });
  assert.equal(frame.outer, DEFAULT_FRAME.outer);
  assert.equal(frame.inner, "double");
  assert.equal(frame.main, DEFAULT_FRAME.main);
  assert.equal(frame.accent, "#c9a45c");
});

test("frame layout reserves matching artwork and margin areas", () => {
  const layout = frameLayout({ outer: "flat", inner: "hairline", matte: "slim" });
  assert.equal(layout.artWidth, 1024);
  assert.equal(layout.artHeight, 640);
  assert.equal(layout.width, 1024 + layout.margin * 2);
  assert.equal(layout.height, 640 + layout.margin * 2);
  assert.equal(layout.artX, layout.margin);
  assert.equal(layout.artY, layout.margin);
});
