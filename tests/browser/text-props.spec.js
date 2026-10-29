import { test, expect } from "./fixtures.js";

test("procedural text renders, updates and releases stale models without GLTF requests", async ({ page }, testInfo) => {
  const gltfRequests = [];
  page.on("request", request => {
    if (/\.(glb|gltf)(?:\?|$)/.test(request.url())) gltfRequests.push(request.url());
  });
  let releaseFont;
  const heldFont = new Promise(resolve => { releaseFont = resolve; });
  await page.route("**/helvetiker_regular.typeface.json", async route => {
    await heldFont;
    await route.continue();
  });
  await page.route("**/__text-render-check", route => route.fulfill({
    contentType: "text/html",
    body: `<!doctype html><html><head><script type="importmap">{"imports":{"three":"/app/vendor/three/three.module.js"}}</script></head>
      <body style="margin:0;background:#417f7c"><div style="width:900px;height:700px"><canvas id="board" style="width:100%;height:100%"></canvas></div><div id="status"></div></body></html>`,
  }));
  await page.goto("/__text-render-check");
  await page.evaluate(async () => {
    const THREE = await import("three");
    const { createBoard } = await import("/app/js/board/board.js");
    window.disposedTextGeometries = 0;
    const dispose = THREE.BufferGeometry.prototype.dispose;
    THREE.BufferGeometry.prototype.dispose = function () {
      if (this.type === "TextGeometry") window.disposedTextGeometries++;
      return dispose.call(this);
    };
    window.board = createBoard({ canvas: document.querySelector("canvas"), overlay: document.querySelector("#status") });
    window.state = {
      user: { initialStickerComplete: true }, ui: { reducedMotion: true },
      room: { id: "text-check", label: "Text", board: { dark: true }, props: [{
        id: "sign", propId: "builtin:text", renderKind: "text", label: "Sign",
        position: [50, 50, 0], scale: 1, text: { content: "Café", font_id: "sans", color: "#ff8844" },
      }] },
    };
    await window.board.render(window.state);
  });
  await expect(page.locator("#status")).toHaveAttribute("data-status", "loading");
  await page.evaluate(async () => {
    window.state.room.props[0].text = { content: "Serif", font_id: "serif", color: "#ffdd88" };
    await window.board.render(window.state);
  });
  await expect.poll(() => page.evaluate(() => window.board.diagnostics().triangles)).toBeGreaterThan(100);
  releaseFont();
  await expect(page.locator("canvas")).toHaveAttribute("data-board-ready", "true");
  await expect.poll(() => page.evaluate(() => window.disposedTextGeometries)).toBe(1);
  await page.evaluate(async () => {
    window.state.room.props[0].text = { content: "Display", font_id: "mono", color: "#88ddff" };
    window.state.room.props[0].position = [50, 50, 3];
    window.state.room.props[0].rotation = [0, 0.2, 0];
    window.state.room.props[0].scale = 1.2;
    await window.board.render(window.state);
  });
  await expect(page.locator("canvas")).toHaveAttribute("data-board-ready", "true");
  await expect.poll(() => page.evaluate(() => window.disposedTextGeometries)).toBe(2);
  const before = await page.evaluate(() => window.board.diagnostics().frames);
  await page.evaluate(async () => {
    window.state.room.props[0].scale = 1.4;
    await window.board.render(window.state);
  });
  await expect.poll(() => page.evaluate(() => window.board.diagnostics().frames)).toBeGreaterThan(before);
  await page.screenshot({ path: testInfo.outputPath("text-props.png") });
  expect(await page.evaluate(() => window.disposedTextGeometries)).toBe(2);
  await page.evaluate(async () => {
    window.state.room.props = [];
    await window.board.render(window.state);
  });
  expect(await page.evaluate(() => window.disposedTextGeometries)).toBe(3);
  expect(await page.evaluate(() => window.board.diagnostics().props)).toBe(0);
  expect(gltfRequests).toEqual([]);
  await page.evaluate(() => window.board.dispose());
});
