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

test("gizmo handles rotate and rescale the selected prop", async ({ page, runtime }) => {
  await createEditorAccount(page, runtime, "editor");
  const panel = await openEditRoom(page);
  const canvas = page.locator("#board-canvas");
  await expect(canvas).toHaveAttribute("data-board-ready", "true", { timeout: 20_000 });
  const meta = panel.locator(".editor-meta");

  await panel.locator('[data-edit-add="plant"]').click();
  await expect(meta).toContainText("Position 50, 50");

  const dragHandle = async (attribute, delta) => {
    await expect(canvas).toHaveAttribute(attribute, /.+/);
    const [hx, hy] = (await canvas.getAttribute(attribute)).split(",").map(Number);
    const box = await canvas.boundingBox();
    await page.mouse.move(box.x + hx, box.y + hy);
    await page.mouse.down();
    await page.mouse.move(box.x + hx + delta.x, box.y + hy + delta.y, { steps: 8 });
    await page.mouse.up();
  };

  const beforeScale = await meta.textContent();
  await dragHandle("data-gizmo-scale", { x: 0, y: -45 });
  await expect(meta).not.toHaveText(beforeScale);
  await expect(meta).not.toContainText("Scale 1.00");

  const beforeRotate = await meta.textContent();
  await dragHandle("data-gizmo-rotate", { x: 0, y: -60 });
  await expect(meta).not.toHaveText(beforeRotate);
  await expect(meta).toContainText("Rotation ");
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

  const dragHandle = async (attribute, delta) => {
    const [hx, hy] = (await canvas.getAttribute(attribute)).split(",").map(Number);
    const box = await canvas.boundingBox();
    await page.mouse.move(box.x + hx, box.y + hy);
    await page.mouse.down();
    await page.mouse.move(box.x + hx + delta.x, box.y + hy + delta.y, { steps: 6 });
    await page.mouse.up();
  };
  await dragHandle("data-gizmo-rotate", { x: 0, y: -50 });
  await dragHandle("data-gizmo-scale", { x: 0, y: -40 });

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