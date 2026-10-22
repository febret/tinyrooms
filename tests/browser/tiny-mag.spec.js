import { test, expect } from "./fixtures.js";
import { command, createReadyAccount } from "./helpers.js";

test.use({ runtimeWorld: "tinytown" });

test("flip through Tiny Mag, buy a home, and meet roommates", async ({ page, runtime }) => {
  test.slow();
  await createReadyAccount(page, runtime, "siteadmin");
  await command(page, ".tinytown");
  const frame = page.frameLocator('iframe[src*="/activities/tiny-mag/"]');
  await expect(frame.getByRole("heading", { name: /TINY/ })).toBeVisible();
  await expect(frame.locator("#wallet")).toHaveText("160");

  await frame.getByRole("button", { name: "03" }).click();
  await expect(frame.getByRole("heading", { name: "Property", exact: true })).toBeVisible();
  await frame.getByRole("button", { name: /Buy · 100 Bops/ }).first().click();
  await frame.getByRole("button", { name: /Confirm · 100 Bops/ }).click();
  await expect(frame.getByText(/Owned ×1/)).toBeVisible();
  await expect(frame.locator("#wallet")).toHaveText("60");

  await frame.getByRole("button", { name: "04" }).click();
  await expect(frame.getByRole("heading", { name: "My", exact: false })).toBeVisible();
  await frame.getByRole("button", { name: "Enter", exact: true }).first().click();
  await expect(page.locator("#look-bar")).toContainText(/Entry|Nook|Hall/);

  await frame.getByRole("button", { name: "05" }).click();
  await expect(frame.locator(".roommate-board .roommate-ad")).toHaveCount(5);
  await frame.getByRole("button", { name: "Invite to move in" }).first().click();
  await expect(frame.getByText("Already home")).toBeVisible();

  await frame.getByRole("button", { name: "06" }).click();
  await expect(frame.getByRole("heading", { name: "The Gallery" })).toBeVisible();
  await expect(frame.locator(".art-card")).toHaveCount(14);
});
