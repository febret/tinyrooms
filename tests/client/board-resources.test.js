import test from "node:test";
import assert from "node:assert/strict";

import { loadSharedTexture, sharedCardGeometry } from "../../client/app/js/board-resources.js";

test("room card geometry merges the four edge groups", () => {
  const geometry = sharedCardGeometry();
  assert.deepEqual(geometry.groups, [
    { start: 0, count: 24, materialIndex: 0 },
    { start: 24, count: 6, materialIndex: 1 },
    { start: 30, count: 6, materialIndex: 2 },
  ]);
});

test("concurrent URL texture loads share one upload", async () => {
  const url = `test://texture-dedupe-${Date.now()}`;
  const texture = { isTexture: true };
  let loads = 0;
  const loader = {
    load(_url, onLoad) {
      loads += 1;
      queueMicrotask(() => onLoad(texture));
    },
  };
  const [first, second] = await Promise.all([
    loadSharedTexture(url, loader),
    loadSharedTexture(url, loader),
  ]);
  assert.equal(loads, 1);
  assert.equal(first, texture);
  assert.equal(second, texture);
  assert.equal(await loadSharedTexture(url, loader), texture);
  assert.equal(loads, 1);
});
