import { test, expect } from "./fixtures.js";
import { PASSWORD, command, confirmSticker, createAccount, createReadyAccount, openCore, openEditRoom, travel } from "./helpers.js";

// This functional suite is a deliberately minimal smoke set: it proves the app
// boots, the real WebSocket round-trips, core views render, and one end-to-end
// gameplay flow works. Comprehensive behavior lives in the Python
// (tests/test_*.py) and Node (tests/client/*.test.js) suites, and rendered
// states are captured by screenshots.spec.js (`npm run test:visual`).
// Portrait layout is covered by the visual baselines, so these run desktop-only.
test.beforeEach(({ isMobile }) => {
  test.skip(Boolean(isMobile), "Desktop-only smoke flow; portrait is covered by test:visual.");
});

test.describe("account onboarding", () => {
  test.slow();
  // Account creation and the sticker designer do enough work that a busy
  // parallel worker can briefly miss Playwright's 10s actionability window.
  test.use({ actionTimeout: 30_000 });

  test("is mandatory, persists, and shows login errors", async ({ page, runtime }) => {
    const sockets = [];
    page.on("websocket", socket => sockets.push(socket));
    await createAccount(page, runtime, "sunbeam", false);
    expect(sockets).toHaveLength(0);
    await page.keyboard.press("Escape");
    await expect(page.locator('iframe[src*="sticker-designer"]')).toBeVisible();
    expect(await page.locator("#chat-input").evaluate(node => node.disabled || Boolean(node.closest("[inert]")))).toBe(true);
    await confirmSticker(page);
    await expect(page.getByRole("button", { name: "Select sunbeam", exact: true })).toBeVisible();
    await page.locator("#settings summary").click();
    await page.getByRole("button", { name: "Log out" }).click();
    await page.getByLabel("Username", { exact: true }).fill("sunbeam");
    await page.getByLabel("Password", { exact: true }).fill("incorrect-password");
    await page.getByRole("button", { name: "Enter Tinyrooms" }).click();
    await expect(page.locator(".auth-error")).not.toBeEmpty();
    await page.getByLabel("Password", { exact: true }).fill(PASSWORD);
    await page.getByRole("button", { name: "Enter Tinyrooms" }).click();
    await expect(page.getByRole("button", { name: "Select sunbeam", exact: true })).toBeVisible();
    await expect(page.locator(".activity-window")).toHaveCount(0);
  });
});

test("all core cards are always visible without an expander", async ({ page, runtime }) => {
  test.slow();
  await createReadyAccount(page, runtime);
  await expect(page.locator("#card-hand [data-core-id]")).toHaveCount(3);
  await expect(page.locator("#card-hand [data-core-expand]")).toHaveCount(0);
  for (const id of ["emotes", "inventory", "journal"]) {
    await expect(page.locator(`#card-hand [data-core-id="${id}"]`)).toBeVisible();
  }
  await openCore(page, "journal");
  await expect(page.locator("#panel-layer [role=dialog]")).toBeVisible();
});

test.describe("cutscenes under reduced motion", () => {
  // The whole suite runs with `prefers-reduced-motion: reduce`, under which
  // cutscenes are disabled outright. Positive coverage lives in
  // cutscenes.spec.js, which opts back in through the desktop-motion project.
  test("never builds the cutscene layer", async ({ page, runtime }) => {
    await createReadyAccount(page, runtime);
    const layer = page.locator("#cutscene-layer");
    await expect(layer).toHaveAttribute("data-state", "idle");
    await command(page, ".cutscene molly-greet");
    await page.waitForTimeout(1_000);
    await expect(layer).toHaveAttribute("data-state", "idle");
    await expect(layer).toBeHidden();
    await expect(page.locator(".cutscene-root")).toHaveCount(0);
  });
});

test.describe("milestone 3 dialogs", () => {
  test.slow();

  test("talk, choose an option, and exit a declarative dialog", async ({ page, runtime }) => {
    const sentCommands = [];
    page.on("websocket", socket => socket.on("framesent", ({ payload }) => {
      const envelope = JSON.parse(String(payload));
      if (envelope.type === "command") sentCommands.push(envelope.command);
    }));
    await createReadyAccount(page, runtime);
    await travel(page);
    await command(page, ".talk molly");
    await expect(page.locator("#look-bar")).toContainText("Mrrp!");
    const exit = page.locator("#actions-bar").getByRole("button", { name: "Exit Conversation", exact: true });
    await expect(exit).toBeVisible();
    const choices = page.locator("#actions-bar button").filter({ hasNotText: "Exit Conversation" });
    await expect(choices.first()).toBeVisible();
    await choices.first().click();
    await expect(page.locator("#look-bar")).not.toContainText("Mrrp!");
    await expect(exit).toBeVisible();
    await exit.click();
    await expect(exit).toHaveCount(0);
    expect(sentCommands).toContain(".talk molly");
    expect(sentCommands.some(item => item.startsWith(".dialog "))).toBe(true);
    expect(sentCommands).toContain(".dialog_end");
  });
});

test.describe("bedrooms and doors", () => {
  test.slow();
  test.setTimeout(60_000);

  test("buy, design, and enter a player bedroom from the corridor", async ({ page, runtime }) => {
    await createReadyAccount(page, runtime, "doorkeeper");
    // The hub's stone archway model must load without error.
    await expect(page.locator("canvas[data-prop-model][data-model-error='true']")).toHaveCount(0);

    await command(page, ".play bedrooms");
    const activity = page.locator(".activity-window");
    await expect(activity.locator("iframe")).toHaveAttribute("src", /bedrooms/);

    const frame = page.frameLocator('iframe[src*="bedrooms"]');
    await expect(frame.locator("#bops")).toContainText("10 Bops", { timeout: 20_000 });
    await frame.locator("#get-door").click();
    await expect(frame.locator("#my-door")).toBeVisible({ timeout: 20_000 });
    await expect(frame.locator("#bops")).toContainText("0 Bops");

    await frame.locator(".door-card.own .door-design").click();
    await expect(frame.locator("#designer")).toBeVisible();
    const colorRow = frame.locator("#controls .control-row", { hasText: "Door Color" });
    await colorRow.locator("button.swatch").nth(1).click();
    await frame.locator('#controls input[type="text"]').fill("Welcome");
    await frame.locator("#designer-save").click();
    await expect(frame.locator("#feedback")).toContainText("Door updated.");

    await frame.locator(".door-card.own").click({ position: { x: 54, y: 30 } });
    await expect(page.locator("#look-bar")).toContainText("Bedroom", { timeout: 20_000 });
    await expect(page.locator("#board-canvas")).toHaveAttribute("data-board-ready", "true", { timeout: 20_000 });
    await expect(page.locator('iframe[src*="bedrooms"]')).toHaveCount(0);

    // The owner can edit their own room.
    await openEditRoom(page);
  });
});
