import { test, expect } from "./fixtures.js";
import { command, confirmSticker, createAccount, openCore, settleArtwork, travel } from "./helpers.js";

// Run explicitly with npm run test:visual. Missing baselines fail, never auto-pass.
test("reference matrix: auth, onboarding, main, room, details, inventory, peep, bubbles, activity", async ({ page, runtime }, testInfo) => {
  test.setTimeout(240_000);
  const requested = new Set((process.env.TR_VISUAL_ONLY || "").split(",").map(name => name.trim()).filter(Boolean));
  const remaining = new Set(requested);
  // Freeze wall-clock display only; keep native timers/RAF and the WebGL compositor.
  await page.addInitScript(() => {
    const NativeDate = Date;
    const fixed = new NativeDate("2026-01-15T12:00:00Z").getTime();
    globalThis.Date = class extends NativeDate {
      constructor(...args) { super(...(args.length ? args : [fixed])); }
      static now() { return fixed; }
    };
  });
  async function capture(name, options) {
    if (requested.size && !requested.has(name)) return;
    remaining.delete(name);
    await settleArtwork(page, options);
    await page.mouse.move(0, 0);
    const candidate = testInfo.outputPath(`${name}-candidate.png`);
    await page.screenshot({ path: candidate, animations: "disabled", caret: "hide", timeout: 30_000 });
    await testInfo.attach(`${name} candidate (requires design review)`, { path: candidate, contentType: "image/png" });
    await expect.soft(page).toHaveScreenshot(`${name}.png`, {
      animations: "disabled", caret: "hide",
    });
  }
  await page.goto(runtime.baseURL);
  await expect(page.getByRole("button", { name: "Enter Tinyrooms" })).toBeVisible();
  await capture("auth");
  await createAccount(page, runtime, "sunbeam", false);
  await expect(page.frameLocator('iframe[src*="sticker-designer"]').locator("#confirm")).toBeEnabled();
  await capture("onboarding");
  await confirmSticker(page);
  await expect(page.getByRole("button", { name: "Select sunbeam", exact: true })).toBeVisible();
  await capture("main");
  await page.locator("#card-hand [data-core-expand]").click();
  await capture("expanded-core");
  await page.locator("#card-hand [data-core-expand]").click();
  await travel(page);
  await capture("playroom-main");
  await openCore(page, "room");
  await capture("room");
  await page.locator('#panel-layer [data-stack-id][data-scope="room"]').first().click();
  await page.locator("#actions-bar").getByRole("button", { name: "Inspect", exact: true }).click();
  await capture("details");
  await page.keyboard.press("Escape");
  await page.locator("#actions-bar").getByRole("button", { name: /Pick up/ }).click();
  await capture("quantity");
  await page.getByRole("button", { name: "Confirm", exact: true }).click();
  await expect(page.locator('#panel-layer [data-stack-id][data-scope="room"]')).toHaveCount(0);
  await openCore(page, "inventory");
  await capture("inventory");
  await page.keyboard.press("Escape");
  await page.getByRole("button", { name: "Select sunbeam", exact: true }).click();
  await capture("peep");
  for (const [style, message] of [["speech", "A little world, a place for you."], ["thought", "(.) A tiny thought."], ["spiky", "(!) Hello Tinyrooms!"]]) {
    await command(page, message);
    await expect(page.locator(`#bubble-layer .${style}`)).toBeVisible();
    await capture(`bubble-${style}`);
  }
  await page.locator("#bubble-layer .bubble").click();
  await expect(page.locator("#bubble-layer .bubble")).toHaveCount(0);
  for (const id of ["emotes", "skills", "journal", "self", "friends"]) {
    await openCore(page, id);
    await capture(id);
    await page.keyboard.press("Escape");
  }
  if (await page.locator("#card-hand [data-core-expand]").getAttribute("aria-expanded") === "true") {
    await page.locator("#card-hand [data-core-expand]").click();
  }
  await command(page, ".play sample");
  await expect(page.frameLocator('iframe[src*="dev-sample"]').locator("#state")).toContainText("sunbeam");
  await capture("activity");
  await page.getByRole("button", { name: "Close activity" }).click();
  await expect(page.locator(".activity-window")).toHaveCount(0);
  await page.locator("#chat-input").fill(".not-a-real-command");
  await page.getByRole("button", { name: "Send message", exact: true }).click();
  await expect(page.locator("#toast-stack .error").first()).toContainText(/unknown command/i);
  await capture("error-toast", { allowToasts: true });
  expect([...remaining], "Every requested screenshot name must exist in the matrix").toEqual([]);
});
