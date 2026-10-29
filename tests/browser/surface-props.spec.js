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
    const { createBoard } = await import("/app/js/board/board.js");
    window.board = createBoard({ canvas: document.querySelector("canvas"), overlay: document.querySelector("#status") });
    const artwork = document.createElement("canvas");
    artwork.width = 1024;
    artwork.height = 640;
    const painting = artwork.getContext("2d");
    painting.fillStyle = "#fbfbf7";
    painting.fillRect(0, 0, 1024, 640);
    painting.strokeStyle = "#d64545";
    painting.lineWidth = 8;
    painting.lineCap = "round";
    painting.beginPath();
    painting.moveTo(40, 40);
    painting.lineTo(240, 180);
    painting.lineTo(480, 80);
    painting.stroke();
    painting.fillStyle = "#1f2933";
    painting.font = "600 56px Trebuchet MS, sans-serif";
    painting.fillText("Plan", 40, 240);
    const frame = { outer: "bevel", inner: "hairline", matte: "gallery", main: "#7a5230", accent: "#c9a45c" };
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
                image: artwork.toDataURL("image/png"),
                frame,
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
