import { test, expect } from "./fixtures.js";
import { command, createReadyAccount } from "./helpers.js";

test.use({ runtimeWorld: "tinytown" });

test("flip through Tiny Mag, buy a home, and meet roommates", async ({ page, runtime }) => {
  test.slow();
  await createReadyAccount(page, runtime, "siteadmin");
  await expect(page.locator("#keyring-toggle")).toBeVisible();
  await page.locator("#tinymag-toggle").click();
  const frame = page.frameLocator('iframe[src*="/activities/tiny-mag/"]');
  await expect(frame.getByRole("heading", { name: /TINY/ })).toBeVisible();
  await expect(frame.locator("#wallet")).toHaveText("160");
  await expect(frame.locator(".rail-group")).toHaveCount(4);
  await expect(frame.locator(".chip")).toHaveCount(0);

  await frame.locator("#next").click();
  await expect(frame.getByRole("heading", { name: "The issue" })).toBeVisible();
  await frame.locator('.contents-list li[data-page="district-downtown"]').click();
  await expect(frame.getByRole("heading", { name: "Downtown" })).toBeVisible();
  await expect(frame.locator(".district-home")).toHaveCount(5);
  await expect(frame.locator(".district-home .prop-unlocks").first()).toContainText(/Unlocks:/);
  const districtFits = await frame.locator(".page-scroll").evaluateAll(
    pages => pages.map(page => page.scrollHeight <= page.clientHeight + 1),
  );
  expect(districtFits).toEqual([true, true]);
  await frame.getByRole("button", { name: /Take the keys · 100 Bops/ }).first().click();
  await frame.getByRole("button", { name: /Confirm · 100 Bops/ }).click();
  await expect(frame.getByText("Owned", { exact: true })).toBeVisible();
  await expect(frame.locator("#wallet")).toHaveText("60");
  await expect(frame.locator("#homes-rail")).toHaveCount(0);

  // The owned-homes keyring lives outside the magazine now.
  await page.locator("#keyring-toggle").click();
  const keys = page.frameLocator('iframe[src*="/activities/keyring/"]');
  await expect(keys.getByRole("heading", { name: "The Keyring" })).toBeVisible();
  await expect(keys.locator(".key-hook")).toHaveCount(1);
  await keys.getByRole("button", { name: "Step inside" }).click();
  await expect(page.locator("#look-bar")).toContainText(/Entry|Nook|Hall/);

  // Activities are room-bound, so re-open Tiny Mag after moving into the home.
  await command(page, ".tinytown");
  await expect(frame.getByRole("heading", { name: /TINY/ })).toBeVisible();
  await frame.locator("#next").click();
  await frame.locator('.contents-list li[data-page="roommates"]').click();
  await expect(frame.getByRole("heading", { name: "The Roommate Files" })).toBeVisible();
  await expect(frame.locator(".roommate-profile")).toHaveCount(5);
  await expect(frame.locator(".roommate-description").first()).not.toBeEmpty();
  await expect(frame.locator(".trait-row, .mini-bars")).toHaveCount(0);
  await frame.getByRole("button", { name: "Ask to move in" }).first().click();
  await expect(frame.locator("#home-dialog")).toBeVisible();
  await expect(frame.locator(".home-choice")).toHaveCount(1);
  await frame.locator(".home-choice").first().click();
  await expect(frame.getByText("At home")).toBeVisible();
  await expect(frame.locator(".resident-profile")).toHaveCount(1);

  await frame.locator("#next").click();
  await expect(frame.getByRole("heading", { name: /Send it/ })).toBeVisible();
  await expect(frame.locator("#page-left").getByText("The submission desk", { exact: false })).toBeVisible();
  await expect(frame.locator(".art-card")).toHaveCount(0);

  await page.setViewportSize({ width: 520, height: 900 });
  await expect(frame.locator("#page-left")).toBeVisible();
  await expect(frame.locator("#page-right")).toBeHidden();
  await frame.locator("#next").click();
  await expect(frame.locator("#page-right")).toBeVisible();
  await expect(frame.locator("#page-left")).toBeHidden();

  const magFrame = await page.locator('iframe[src*="/activities/tiny-mag/"]').boundingBox();
  const magShell = await frame.locator(".mag-shell").boundingBox();
  expect(Math.abs(magShell.height - magFrame.height)).toBeLessThan(2);
  const magStage = await frame.locator(".mag-stage").boundingBox();
  const magBook = await frame.locator("#book").boundingBox();
  expect(magBook.height).toBeGreaterThan(magStage.height * 0.85);
  await frame.locator('.rail-btn[data-page="district-downtown"]').click();
  await expect(frame.locator("#page-left").getByRole("heading", { name: "Downtown" })).toBeVisible();
  const downtownHomes = frame.locator("#page-left .district-home");
  await expect(downtownHomes).toHaveCount(2);
  const downtownScroll = frame.locator("#page-left .page-scroll");
  await downtownScroll.evaluate(page => { page.scrollTop = page.scrollHeight; });
  await expect(downtownHomes.last()).toBeVisible();
  await expect(frame.locator("#page-left .district-note")).toBeVisible();
});
