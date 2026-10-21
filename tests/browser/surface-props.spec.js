import { test, expect } from "./fixtures.js";

test("procedural sign and whiteboard render without GLTF requests", async ({ page }) => {
  const gltfRequests = [];
  page.on("request", request => {
    if (/\.(glb|gltf)(?:\?|$)/.test(request.url())) gltfRequests.push(request.url());
  });
  await page.route("**/__surface-render-check", route => route.fulfill({
    contentType: "text/html",
    body: `<!doctype html><html><head><script type="importmap">{"imports":{"three":"/app/vendor/three/three.module.js"}}</script></head>
      <body style="margin:0;background:#417f7c"><div style="width:900px;height:700px"><canvas id="board" style="width:100%;height:100%"></canvas></div><div id="status"></div></body></html>`,
  }));
  await page.goto("/__surface-render-check");
  await page.evaluate(async () => {
    const { createBoard } = await import("/app/js/board.js");
    window.board = createBoard({ canvas: document.querySelector("canvas"), overlay: document.querySelector("#status") });
    window.state = {
      user: { initialStickerComplete: true }, ui: { reducedMotion: true },
      room: {
        id: "surface-check", label: "Surfaces", board: { dark: true },
        props: [
          {
            id: "sign", propId: "builtin:sign", renderKind: "sign", label: "Sign",
            position: [45, 50, 0], rotation: [0, 0, 0], scale: 1, signStyle: "chalk",
            surface: { kind: "sign", revision: 1, content: { text: "Hello room" } },
          },
          {
            id: "board", propId: "builtin:whiteboard", renderKind: "whiteboard", label: "Whiteboard",
            position: [60, 50, 0], rotation: [0, 0, 0], scale: 1,
            surface: {
              kind: "whiteboard", revision: 1,
              content: {
                strokes: [{ color: "#d64545", width: 8, points: [[40, 40], [240, 180], [480, 80]] }],
                texts: [{ text: "Plan", x: 40, y: 240, size: 56, color: "#1f2933" }],
              },
            },
          },
        ],
      },
    };
    await window.board.render(window.state);
  });
  await expect(page.locator("canvas")).toHaveAttribute("data-board-ready", "true");
  expect(await page.evaluate(() => window.board.diagnostics().props)).toBe(2);
  expect(await page.evaluate(() => window.board.diagnostics().triangles)).toBeGreaterThan(10);
  await page.evaluate(async () => {
    window.state.room.props[0].signStyle = "neon";
    window.state.room.props[0].surface = { kind: "sign", revision: 2, content: { text: "Updated" } };
    window.state.room.props[1].surface.revision = 2;
    await window.board.render(window.state);
  });
  await expect(page.locator("canvas")).toHaveAttribute("data-board-ready", "true");
  expect(await page.evaluate(() => window.board.diagnostics().props)).toBe(2);
  expect(gltfRequests).toEqual([]);
  await page.evaluate(() => window.board.dispose());
});
