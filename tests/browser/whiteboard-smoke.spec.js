import { test, expect } from "./fixtures.js";

test("whiteboard paint activity boots without a save button", async ({ page }) => {
  await page.goto("/activities/whiteboard/");
  await expect(page.locator(".paint-shell")).toBeVisible();
  await expect(page.locator("#brush-rail .brush")).toHaveCount(11);
  await expect(page.locator("#save")).toHaveCount(0);
  await expect(page.locator("#palette-toggle")).toBeVisible();
  await expect(page.locator("#frame-toggle")).toBeVisible();
  await expect(page.locator("#brush-size")).toBeVisible();
  await expect(page.locator("#board")).toBeVisible();
});
