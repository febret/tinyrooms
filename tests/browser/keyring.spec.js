import { test, expect } from "./fixtures.js";
import { command, createReadyAccount } from "./helpers.js";

test.use({ runtimeWorld: "tinytown" });

test("hang keys on the Keyring, lock a door, and greet a roommate", async ({ page, runtime }) => {
  test.slow();
  await createReadyAccount(page, runtime, "siteadmin");
  await page.locator("#tinymag-toggle").click();
  const mag = page.frameLocator('iframe[src*="/activities/tiny-mag/"]');
  await expect(mag.getByRole("heading", { name: /TINY/ })).toBeVisible();
  await mag.locator("#next").click();
  await mag.locator('.contents-list li[data-page="district-downtown"]').click();
  await mag.getByRole("button", { name: /Take the keys · 100 Bops/ }).first().click();
  await mag.getByRole("button", { name: /Confirm · 100 Bops/ }).click();
  await expect(mag.getByText(/Owned ×1/)).toBeVisible();

  await page.locator("#keyring-toggle").click();
  const keys = page.frameLocator('iframe[src*="/activities/keyring/"]');
  await expect(keys.getByRole("heading", { name: "The Keyring" })).toBeVisible();
  await expect(keys.locator(".key-hook")).toHaveCount(1);
  await expect(keys.getByText("Micro Loft").first()).toBeVisible();
  await expect.poll(async () => keys.locator(".detail-key img").evaluate(
    img => img.complete && img.naturalWidth > 0,
  )).toBe(true);
  await expect(keys.locator(".open-empty")).toHaveCount(1);

  await keys.getByRole("button", { name: "Lock the front door" }).click();
  await expect(keys.locator(".detail-lock")).toHaveText("Front door locked");
  await keys.getByRole("button", { name: "Unlock the front door" }).click();
  await expect(keys.locator(".detail-lock")).toHaveText("Welcoming visitors");

  await keys.getByRole("button", { name: "Step inside" }).click();
  await expect(page.locator("#look-bar")).toContainText(/Entry|Nook|Hall/);

  // Adopt in the magazine, then check the roommate appears on the keyring.
  await command(page, ".tinytown");
  await expect(mag.getByRole("heading", { name: /TINY/ })).toBeVisible();
  await mag.locator("#next").click();
  await mag.locator('.contents-list li[data-page="roommates"]').click();
  await mag.getByRole("button", { name: "Ask to move in" }).first().click();
  await expect(mag.locator("#home-dialog")).toBeVisible();
  await mag.locator(".home-choice").first().click();
  await expect(mag.getByText("At home")).toBeVisible();

  await page.locator("#keyring-toggle").click();  await expect(keys.getByRole("heading", { name: "The Keyring" })).toBeVisible();
  await expect(keys.locator(".resident")).toHaveCount(1);

  await page.setViewportSize({ width: 390, height: 844 });
  const keysFrame = await page.locator('iframe[src*="/activities/keyring/"]').boundingBox();
  const keysShell = await keys.locator(".keyring-shell").boundingBox();
  expect(Math.abs(keysShell.height - keysFrame.height)).toBeLessThan(2);
  await keys.locator(".keyring-shell").evaluate(shell => { shell.scrollTop = shell.scrollHeight; });
  await expect(keys.locator(".open-houses")).toBeVisible();
});
