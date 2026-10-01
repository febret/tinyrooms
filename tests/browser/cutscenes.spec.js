import { test, expect } from "./fixtures.js";
import { command, createReadyAccount } from "./helpers.js";

// Cutscenes are disabled outright under reduced motion, so this spec only runs
// in the `desktop-motion` project (see playwright.config.js). The negative case
// lives in flows.spec.js, which runs with the suite-wide reduced motion. This is
// the single essential playback check: real frame intro, scene body, and outro.
function layer(page) {
  return page.locator("#cutscene-layer");
}

test("plays a cutscene from a command and tears the layer down", async ({ page, runtime }) => {
  // Real playback waits for a frame intro, a scene body, and the outro, which is
  // close to the 20s default ceiling.
  test.slow();
  await createReadyAccount(page, runtime, "director");
  await expect(layer(page)).toHaveAttribute("data-state", "idle");
  await command(page, ".cutscene molly-greet");
  await expect(page.locator(".cutscene-frame-movie")).toBeVisible();
  await expect(page.locator('.cutscene-stage[data-cutscene-stage="molly-greet"]')).toBeAttached();
  await expect(layer(page)).toHaveAttribute("data-state", "idle", { timeout: 20_000 });
  await expect(page.locator(".cutscene-root")).toHaveCount(0);
});
