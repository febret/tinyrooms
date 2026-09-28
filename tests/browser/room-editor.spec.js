import { test, expect } from "./fixtures.js";
import { createEditorAccount, dragProp, openEditRoom } from "./helpers.js";

// These flows drive the room editor's board gestures with a mouse, so they run on
// desktop; portrait layout is covered by the visual baselines.
test.beforeEach(({ isMobile }) => {
  test.skip(Boolean(isMobile), "Room editor gestures run on desktop; portrait is covered by test:visual.");
});

test("editor heading names the selection and grid tiles stay label-free", async ({ page, runtime }) => {
  await createEditorAccount(page, runtime, "editor");
  const panel = await openEditRoom(page);
  const selectedName = panel.locator("[data-edit-selected-name]");
  await expect(selectedName).toHaveText("No prop selected");
  // Tiles are thumbnail-only; the selected name lives in the heading box.
  expect(await panel.locator(".editor-library-item span").count()).toBe(0);
  await panel.locator('[data-edit-add="plant"]').click();
  await expect(selectedName).not.toHaveText("No prop selected");
});

test("dragging a prop onto another stacks it above the support", async ({ page, runtime }) => {
  await createEditorAccount(page, runtime, "editor");
  const panel = await openEditRoom(page);
  const canvas = page.locator("#board-canvas");
  await expect(canvas).toHaveAttribute("data-board-ready", "true", { timeout: 20_000 });

  await panel.locator('[data-edit-add="plant"]').click();
  await panel.locator('[data-edit-add="mustard-armchair"]').click();
  await expect(panel.locator(".editor-meta")).toContainText("Position 50, 50");
  await expect(canvas).toHaveAttribute("data-edit-elevation", "0");

  // The two props overlap, so a small drag lifts the moved one onto the other.
  await dragProp(page, panel, "Position 50, 50", { x: 18, y: 12 });
  await expect.poll(async () => Number(await canvas.getAttribute("data-edit-elevation"))).toBeGreaterThan(0);
});

test("dragging inside the gizmo drag circle moves the prop", async ({ page, runtime }) => {
  await createEditorAccount(page, runtime, "editor");
  const panel = await openEditRoom(page);
  const canvas = page.locator("#board-canvas");
  await expect(canvas).toHaveAttribute("data-board-ready", "true", { timeout: 20_000 });

  await panel.locator('[data-edit-add="plant"]').click();
  await expect(panel.locator(".editor-meta")).toContainText("Position 50, 50");
  // Wait for the prop model so the drag circle is sized from real bounds, not the fallback.
  await expect(canvas).toHaveAttribute("data-board-ready", "true", { timeout: 20_000 });
  const gizmo = await page.evaluate(() => window.__tinyroomsBoard.editGizmo());
  expect(gizmo).toBeTruthy();
  expect(gizmo.radiusPx).toBeGreaterThan(4);

  // Start on the far side of the circle from the rotate knob, clear of the prop body.
  const from = { x: gizmo.center.x - gizmo.radiusPx * 0.8, y: gizmo.center.y };
  await page.mouse.move(from.x, from.y);
  await page.mouse.down();
  await page.mouse.move(from.x + 30, from.y + 20, { steps: 8 });
  await page.mouse.up();

  await expect(panel.locator(".editor-meta")).not.toContainText("Position 50, 50");
});

test("dragging the rotate handle 100px horizontally turns the prop 20 degrees", async ({ page, runtime }) => {
  await createEditorAccount(page, runtime, "editor");
  const panel = await openEditRoom(page);
  const canvas = page.locator("#board-canvas");
  await expect(canvas).toHaveAttribute("data-board-ready", "true", { timeout: 20_000 });

  await panel.locator('[data-edit-add="plant"]').click();
  await expect(panel.locator(".editor-meta")).toContainText("Rotation 0");
  // Wait for the prop model so the rotate knob's measured screen point is stable.
  await expect(canvas).toHaveAttribute("data-board-ready", "true", { timeout: 20_000 });
  const gizmo = await page.evaluate(() => window.__tinyroomsBoard.editGizmo());
  expect(gizmo).toBeTruthy();

  await page.mouse.move(gizmo.rotate.x, gizmo.rotate.y);
  await page.mouse.down();
  await page.mouse.move(gizmo.rotate.x + 100, gizmo.rotate.y, { steps: 10 });
  await page.mouse.up();

  const text = await panel.locator(".editor-meta").textContent();
  const rotation = Number(/Rotation (-?\d+)/.exec(text)?.[1]);
  // 100px right is 20 degrees clockwise, normalized into [0, 360).
  expect(Math.min(Math.abs(rotation - 340), Math.abs(rotation - 20))).toBeLessThan(2);
});

test("the prop library stays static while props are edited", async ({ page, runtime }) => {
  await createEditorAccount(page, runtime, "editor");
  const panel = await openEditRoom(page);
  const canvas = page.locator("#board-canvas");
  await expect(canvas).toHaveAttribute("data-board-ready", "true", { timeout: 20_000 });

  await page.evaluate(() => {
    window.__gridMutations = 0;
    const grid = document.querySelector("#editor-dock .editor-library-grid");
    grid.dataset.probe = "kept";
    new MutationObserver(records => {
      for (const record of records) if (record.type === "childList") window.__gridMutations += 1;
    }).observe(grid, { childList: true, subtree: true });
  });

  // Add, drag, nudge, rotate and rescale a prop; none may touch the library DOM.
  await panel.locator('[data-edit-add="plant"]').click();
  await expect(panel.locator(".editor-meta")).toContainText("Position 50, 50");
  await dragProp(page, panel, "Position 50, 50", { x: 40, y: 25 });
  await page.keyboard.press("ArrowRight");
  await page.keyboard.press("]");
  await page.keyboard.press("=");

  // The lightweight path must still keep the editor chrome in sync.
  await expect(panel.locator("[data-editor-status]")).toContainText("Unsaved changes");
  await expect(panel.locator("[data-editor-save]")).toBeEnabled();
  await expect(panel.locator("[data-editor-undo]")).toBeEnabled();

  const result = await page.evaluate(() => {
    const grid = document.querySelector("#editor-dock .editor-library-grid");
    return {
      probe: grid.dataset.probe,
      mutations: window.__gridMutations,
      hasTile: Boolean(grid.querySelector(".editor-library-item")),
    };
  });
  expect(result.probe).toBe("kept");
  expect(result.hasTile).toBe(true);
  expect(result.mutations).toBe(0);
});