import { test, expect } from "./fixtures.js";
import { command, createReadyAccount, grantCardAsAdmin, loginAs, travel } from "./helpers.js";

// Cutscenes are disabled outright under reduced motion, so this spec only runs
// in the `desktop-motion` project (see playwright.config.js). The negative case
// lives in flows.spec.js, which runs with the suite-wide reduced motion.
function layer(page) {
  return page.locator("#cutscene-layer");
}

test.beforeEach(async ({ page, runtime }) => {
  // These flows wait for real playback: account setup plus a frame intro, a
  // scene body, and the outro, which is close to the 20s default ceiling.
  test.slow();
  await createReadyAccount(page, runtime, "director");
  await expect(layer(page)).toHaveAttribute("data-state", "idle");
});

test("plays a cutscene from a command and tears the layer down", async ({ page }) => {
  await command(page, ".cutscene molly-greet");
  await expect(page.locator(".cutscene-frame-movie")).toBeVisible();
  await expect(page.locator('.cutscene-stage[data-cutscene-stage="molly-greet"]')).toBeAttached();
  await expect(layer(page)).toHaveAttribute("data-state", "idle", { timeout: 20_000 });
  await expect(page.locator(".cutscene-root")).toHaveCount(0);
});

test("builds scene DOM and resolves both peep sprites", async ({ page }) => {
  await command(page, ".cutscene molly-greet @peep:molly");
  const me = page.locator(".cutscene-sprite-me");
  await expect(me).toHaveAttribute("data-sprite-kind", "sticker");
  await expect(me).toHaveAttribute("src", /\/assets\/stickers\//);
  const peep = page.locator(".cutscene-sprite-peep");
  await expect(peep).toHaveAttribute("data-sprite-kind", "sticker");
  await expect(peep).toHaveAttribute("src", /\/peeps\/molly\.png/);
  await expect(page.locator(".cutscene-line")).toContainText("director steps closer.");
  await expect(page.locator(".cutscene-heart").first()).toBeVisible();
  await expect(layer(page)).toHaveAttribute("data-state", "idle", { timeout: 20_000 });
});

test("shows captions from the definition text", async ({ page }) => {
  await command(page, ".cutscene molly-greet");
  await expect(page.locator(".cutscene-caption").first()).toContainText(/Purrrr\./);
  await expect(layer(page)).toHaveAttribute("data-state", "idle", { timeout: 20_000 });
});

test("the skip control ends playback early", async ({ page }) => {
  await command(page, ".cutscene molly-greet");
  // The Skip control only exists for a few seconds, so the click window is
  // deliberately tight: polling for it for ten seconds would outlive the scene.
  const skip = page.locator(".cutscene-skip");
  await expect(skip).toBeVisible({ timeout: 5_000 });
  await skip.click({ timeout: 5_000 });
  await expect(layer(page)).toHaveAttribute("data-state", "idle", { timeout: 20_000 });
});

test("Escape skips playback", async ({ page }) => {
  await command(page, ".cutscene molly-greet");
  await expect(page.locator(".cutscene-skip")).toBeVisible({ timeout: 5_000 });
  await page.keyboard.press("Escape");
  await expect(layer(page)).toHaveAttribute("data-state", "idle", { timeout: 20_000 });
});

test("the board is blocked while chat stays usable", async ({ page }) => {
  await command(page, ".cutscene molly-greet");
  await expect(page.locator(".cutscene-frame-movie")).toBeVisible();
  await expect(page.locator("#chat-input")).toBeEnabled();
  expect(
    await page.locator("#board-canvas").evaluate(node => node.inert || Boolean(node.closest("[inert]"))),
  ).toBe(true);
  await command(page, "hello from the audience");
  await expect(page.locator(".log-line.chat").last()).toContainText("hello from the audience");
  await expect(layer(page)).toHaveAttribute("data-state", "idle", { timeout: 20_000 });
});

test("a room cutscene plays for everyone in the room", async ({ page, context, runtime }) => {
  const second = await context.newPage();
  await createReadyAccount(second, runtime, "bystander");
  await command(page, ".cutscene victory-dance");
  await expect(page.locator(".cutscene-banner")).toHaveText("VICTORY DANCE");
  await expect(second.locator(".cutscene-frame-victory")).toBeVisible({ timeout: 20_000 });
  await expect(layer(page)).toHaveAttribute("data-state", "idle", { timeout: 20_000 });
  await second.close();
});

test("a cutscene emote plays for the room and leaves no bubble", async ({ page, runtime }) => {
  await grantCardAsAdmin(page, runtime, "director", "victory-dance");
  await loginAs(page, runtime, "director");
  await page.goto(runtime.baseURL);
  await page.locator('#card-hand [data-core-id="emotes"]').click();
  await page.locator('[data-emote-category="Scene"]').click();
  const tile = page.getByRole("button", { name: "Victory Dance", exact: true });
  await expect(tile).toBeVisible();
  await tile.click();
  await expect(page.locator(".cutscene-frame-victory")).toBeVisible();
  await expect(page.locator(".bubble.emote")).toHaveCount(0);
  await expect(layer(page)).toHaveAttribute("data-state", "idle", { timeout: 20_000 });
});

test("a room change clears a playing cutscene", async ({ page }) => {
  await command(page, ".cutscene molly-greet");
  await expect(page.locator(".cutscene-frame-movie")).toBeVisible();
  await travel(page, "exit0");
  await expect(layer(page)).toHaveAttribute("data-state", "idle", { timeout: 20_000 });
});

test("an unknown cutscene is rejected", async ({ page }) => {
  await page.locator("#chat-input").fill(".cutscene not-a-cutscene");
  await page.locator("#chat-input").press("Enter");
  await expect(page.locator("#toast-stack")).toContainText("no cutscene called");
  await expect(layer(page)).toHaveAttribute("data-state", "idle");
});
