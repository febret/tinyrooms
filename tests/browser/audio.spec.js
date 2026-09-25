import { test, expect } from "./fixtures.js";
import { command, createReadyAccount } from "./helpers.js";

// Audio chat flows use fake microphones (see playwright.config.js) and two
// browser pages, so they run on desktop only.
test.beforeEach(({ isMobile }, testInfo) => {
  test.skip(Boolean(isMobile) && !testInfo.tags.includes("@mobile"), "Desktop-only flow; portrait is covered by test:visual.");
});

async function enableAudioChat(page) {
  await page.locator("#settings summary").click();
  await page.getByRole("button", { name: "Enable Audio Chat", exact: true }).click();
  await expect(page.getByRole("button", { name: "Disable Audio Chat", exact: true })).toBeVisible();
}

test.describe("audio chat", () => {
  test.slow();

  test("connects two audio-enabled users in the same room", async ({ page, browser, runtime }) => {
    test.setTimeout(60_000);
    await createReadyAccount(page, runtime, "alice");
    const context = await browser.newContext({
      ignoreHTTPSErrors: true,
      viewport: { width: 1280, height: 800 },
      permissions: ["microphone"],
    });
    try {
      const bobPage = await context.newPage();
      await createReadyAccount(bobPage, runtime, "bob");
      await expect(page.locator("#peeps-panel [data-peep-id]").filter({ hasText: "bob" })).toBeVisible();

      await enableAudioChat(page);
      await expect(page.locator("#peeps-panel .peep-chip.self .peep-audio")).toBeVisible();
      await expect(bobPage.locator("#peeps-panel .peep-chip").filter({ hasText: "alice" }).locator(".peep-audio")).toBeVisible();

      await enableAudioChat(bobPage);
      await expect(page.locator("#peeps-panel .peep-chip").filter({ hasText: "bob" }).locator(".peep-audio")).toBeVisible();

      await expect.poll(
        () => page.evaluate(() => Boolean(document.querySelector("#voice-audio audio")?.srcObject)),
        { timeout: 30_000 },
      ).toBeTruthy();

      await page.getByRole("button", { name: "Disable Audio Chat", exact: true }).click();
      await expect(bobPage.locator("#peeps-panel .peep-chip").filter({ hasText: "alice" }).locator(".peep-audio")).toHaveCount(0);
    } finally {
      await context.close();
    }
  });

  test("keeps audio enabled across a room move", async ({ page, browser, runtime }) => {
    test.setTimeout(90_000);
    await createReadyAccount(page, runtime, "alice");
    const context = await browser.newContext({
      ignoreHTTPSErrors: true,
      viewport: { width: 1280, height: 800 },
      permissions: ["microphone"],
    });
    try {
      const bobPage = await context.newPage();
      await createReadyAccount(bobPage, runtime, "bob");
      await expect(page.locator("#peeps-panel [data-peep-id]").filter({ hasText: "bob" })).toBeVisible();

      await enableAudioChat(page);
      await enableAudioChat(bobPage);
      await expect.poll(
        () => page.evaluate(() => Boolean(document.querySelector("#voice-audio audio")?.srcObject)),
        { timeout: 30_000 },
      ).toBeTruthy();

      await command(page, ".go @way:exit0");
      await expect(page.locator("#look-bar")).toContainText("The Playroom");
      await expect(page.locator("#peeps-panel .peep-chip.self .peep-audio")).toBeVisible();
      await expect(bobPage.locator("#peeps-panel .peep-chip").filter({ hasText: "alice" }).locator(".peep-audio")).toHaveCount(0);

      await command(bobPage, ".go @way:exit0");
      await expect(bobPage.locator("#look-bar")).toContainText("The Playroom");
      await expect(page.locator("#peeps-panel .peep-chip").filter({ hasText: "bob" }).locator(".peep-audio")).toBeVisible();
      await expect.poll(
        () => page.evaluate(() => Boolean(document.querySelector("#voice-audio audio")?.srcObject)),
        { timeout: 30_000 },
      ).toBeTruthy();
    } finally {
      await context.close();
    }
  });

  test("replaces send with push-to-talk for a ten second window", async ({ page, runtime }) => {
    test.setTimeout(60_000);
    await createReadyAccount(page, runtime, "alice");
    await enableAudioChat(page);
    const talk = page.locator("#push-to-talk");
    const progress = page.locator("#push-to-talk .talk-ring-progress");
    await expect(talk).toBeVisible();
    await expect(page.locator(".send-button")).toBeHidden();
    await expect(talk).toHaveAttribute("aria-pressed", "false");

    await talk.click();
    await expect(talk).toHaveAttribute("aria-pressed", "true");
    await expect.poll(() => progress.evaluate(element => Number(element.style.strokeDashoffset || "0"))).toBeLessThan(50);
    await talk.click();
    await expect(talk).toHaveAttribute("aria-pressed", "false");
    await expect.poll(() => progress.evaluate(element => Number(element.style.strokeDashoffset || "0"))).toBeGreaterThan(90);

    await talk.click();
    await expect(talk).toHaveAttribute("aria-pressed", "true");
    await expect(talk).toHaveAttribute("aria-pressed", "false", { timeout: 12_000 });
  });
});
