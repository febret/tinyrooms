import { test, expect } from "./fixtures.js";
import { createReadyAccount } from "./helpers.js";

// The shared desktop project runs with reduced motion, which disables
// cutscene playback, so this spec opts back in like a motion project.
test.use({ reducedMotion: "no-preference", viewport: { width: 1280, height: 800 } });

test("admins open the catalog and preview a cutscene", async ({ page, runtime }) => {
  test.slow();
  await createReadyAccount(page, runtime, "siteadmin");
  await page.goto(`${runtime.baseURL}/cutscene-catalog/`);
  await expect(page.getByRole("heading", { name: "Cutscene Catalog" })).toBeVisible();
  await page.getByRole("button", { name: "You Got the Multiverse Map!" }).click();
  await expect(page.locator("#cc-detail")).toContainText("multiverse-map-found");
  await page.getByRole("button", { name: "Preview locally", exact: true }).click();
  await expect(page.locator('.cutscene-stage[data-cutscene-stage="multiverse-map-found"]')).toBeAttached();
  await expect(page.locator(".cutscene-map-card")).toBeVisible();
  await expect(page.locator("#cutscene-layer")).toHaveAttribute("data-state", "idle", { timeout: 20_000 });
});
