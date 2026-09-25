import { test, expect } from "./fixtures.js";
import { createReadyAccount, findPropByLabel } from "./helpers.js";

test.beforeEach(({ isMobile }, testInfo) => {
  test.skip(Boolean(isMobile) && !testInfo.tags.includes("@mobile"), "Desktop-only flow; portrait is covered by test:visual.");
});

test.describe("default quick actions", () => {
  test.slow();

  test("re-clicking an exit prop takes its default exit", async ({ page, runtime }) => {
    const sentCommands = [];
    page.on("websocket", socket => socket.on("framesent", ({ payload }) => {
      const envelope = JSON.parse(String(payload));
      if (envelope.type === "command") sentCommands.push(envelope.command);
    }));
    await createReadyAccount(page, runtime);
    const point = await findPropByLabel(page, "A Glowing Portal");
    await expect(page.locator("#look-bar .look-name")).toHaveText("A Glowing Portal");
    await expect(page.locator("#actions-bar").getByRole("button", { name: "Go across", exact: true })).toBeVisible();
    await page.mouse.click(point.x, point.y);
    await expect(page.locator("#look-bar")).toContainText("The Playroom");
    expect(sentCommands).toContain(".go @way:exit0");
  });
});
