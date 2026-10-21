import { test, expect } from "./fixtures.js";
import { PASSWORD, command, confirmSticker, createAccount, createReadyAccount, openCore, travel } from "./helpers.js";

// This functional suite is a deliberately minimal smoke set: it proves the app
// boots, the real WebSocket round-trips, core views render, and one end-to-end
// gameplay flow works. Comprehensive behavior lives in the Python
// (tests/test_*.py) and Node (tests/client/*.test.js) suites.

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

test("core toolbar, room picker, settings peeps, and Journal spreads render", async ({ page, runtime }) => {
  test.slow();
  await createReadyAccount(page, runtime);
  await expect(page.locator("#core-tools [data-core-id]")).toHaveCount(2);
  await expect(page.locator("#multiverse-toggle")).toHaveCount(0);
  await expect(page.locator("#card-hand [data-core-id], #card-hand [data-core-expand]")).toHaveCount(0);
  for (const id of ["inventory", "journal"]) {
    await expect(page.locator(`#core-tools [data-core-id="${id}"]`)).toBeVisible();
  }
  await expect(page.locator("#peeps-panel")).toBeVisible();
  await page.locator("#settings summary").click();
  const peeps = page.locator('[data-top-action="peeps"]');
  await expect(peeps).toHaveAttribute("aria-pressed", "true");
  await peeps.click();
  await expect(page.locator("#peeps-panel")).toBeHidden();
  await expect(peeps).toHaveAttribute("aria-pressed", "false");
  await peeps.click();
  await expect(page.locator("#peeps-panel")).toBeVisible();
  await expect(peeps).toHaveAttribute("aria-pressed", "true");
  await page.locator("#settings summary").click();
  const pickerToggle = page.locator("#room-picker-toggle");
  const picker = page.locator("#room-picker");
  await expect(page.locator('#core-tools [data-core-id="inventory"] + #room-picker-toggle')).toBeVisible();
  await pickerToggle.click();
  await expect(picker).toBeVisible();
  await expect(pickerToggle).toHaveAttribute("aria-expanded", "true");
  const prop = picker.locator("[data-room-picker-prop]").first();
  const propLabel = await prop.getAttribute("aria-label");
  await prop.click();
  await expect(picker).toBeHidden();
  await expect(page.locator("#look-bar")).toContainText(propLabel);
  await pickerToggle.click();
  await page.keyboard.press("Escape");
  await expect(picker).toBeHidden();
  await expect(pickerToggle).toHaveAttribute("aria-expanded", "false");
  await expect(page.locator("#look-bar")).toContainText(propLabel);
  await travel(page);
  await travel(page, "kitchen", "The Kitchen");
  await pickerToggle.click();
  const roomCard = picker.locator('[data-stack-id][data-scope="room"]').first();
  const cardLabel = await roomCard.locator("..").locator(".room-picker-label").innerText();
  await roomCard.click();
  await expect(picker).toBeHidden();
  await expect(page.locator("#look-bar")).toContainText(cardLabel);
  const preview = page.locator('[data-look-inspect="card"]');
  await expect(preview.locator("svg.card-face")).toBeVisible();
  await preview.click();
  const inventory = page.getByRole("dialog", { name: "Inventory", exact: true });
  await expect(inventory).toBeVisible();
  await expect(inventory.locator(".inventory-preview canvas[data-card-face]")).toBeVisible();
  await expect(inventory.locator(".inventory-preview-name")).toHaveText(cardLabel);
  await page.keyboard.press("Escape");
  await expect(inventory).toBeHidden();
  await expect(page.locator("#emote-toggle")).toBeVisible();
  await page.locator("#emote-toggle").click();
  await expect(page.locator("#emote-menu")).toHaveClass(/open/);
  await expect(page.locator("#emote-menu .emote-column")).toHaveCount(3);
  await page.keyboard.press("Escape");
  await expect(page.locator("#emote-menu")).not.toHaveClass(/open/);
  await openCore(page, "journal");
  const journal = page.getByRole("dialog", { name: "Journal", exact: true });
  await expect(journal).toBeVisible();
  await expect(journal.locator("[data-journal-tab]")).toHaveCount(5);
  for (const tab of ["Tasks", "Memories", "Self", "Skills", "Friends"]) {
    const button = journal.locator(`[data-journal-tab="${tab}"]`);
    await button.click();
    await expect(button).toHaveAttribute("aria-pressed", "true");
    await expect(journal.locator(".journal-page")).toHaveCount(2);
    await expect(journal.locator(".journal-page-left")).toBeVisible();
    await expect(journal.locator(".journal-page-right")).toBeVisible();
    if (tab === "Self") {
      await expect(journal.getByRole("progressbar", { name: "Next level", exact: true })).toBeVisible();
      for (const name of ["Health", "Energy", "Cleanliness"]) {
        await expect(journal.getByRole("progressbar", { name, exact: true })).toBeVisible();
      }
      await expect(journal.locator("[data-level-up]")).toBeDisabled();
    }
  }
});

test("journal keeps a two-page spread on large portrait screens", async ({ page, runtime }) => {
  await page.setViewportSize({ width: 1024, height: 1366 });
  await createReadyAccount(page, runtime);
  await openCore(page, "journal");
  const journal = page.getByRole("dialog", { name: "Journal", exact: true });
  const left = await journal.locator(".journal-page-left").boundingBox();
  const right = await journal.locator(".journal-page-right").boundingBox();
  expect(left).not.toBeNull();
  expect(right).not.toBeNull();
  expect(right.x).toBeGreaterThan(left.x + left.width * 0.5);
  expect(Math.abs(right.y - left.y)).toBeLessThan(12);
});

test("room board recovers from WebGL context loss", async ({ page, runtime }) => {
  await createReadyAccount(page, runtime);
  const canvas = page.locator("#board-canvas");
  await expect(canvas).toHaveAttribute("data-board-ready", "true");
  await page.evaluate(() => {
    const target = document.querySelector("#board-canvas");
    const gl = target.getContext("webgl2") || target.getContext("webgl");
    const extension = gl.getExtension("WEBGL_lose_context");
    window.__trContextLoss = extension;
    extension.loseContext();
  });
  await expect(page.locator("#board-overlay")).toContainText("Restoring the board");
  await page.evaluate(() => window.__trContextLoss.restoreContext());
  await expect.poll(() => page.evaluate(() => window.__tinyroomsBoard.diagnostics().renderFailed)).toBe(false);
  await expect(canvas).toHaveAttribute("data-board-ready", "true");
});

test("inventory previews cards inline and retargets on selection", async ({ page, runtime }) => {
  await createReadyAccount(page, runtime);
  await openCore(page, "inventory");
  const inventory = page.getByRole("dialog", { name: "Inventory", exact: true });
  await inventory.locator('[data-inventory-tab="Emotes"]').click();
  const tiles = inventory.locator(".inventory-content .cards-grid .game-card");
  await expect(tiles.first()).toBeVisible();
  const preview = inventory.locator(".inventory-preview canvas[data-card-face]");
  await expect(preview).toBeVisible();
  const firstFace = await preview.getAttribute("data-card-face");
  await tiles.nth(1).click();
  await expect(preview).not.toHaveAttribute("data-card-face", firstFace);
});

test("inventory places the preview below the grid on portrait devices", async ({ page, runtime }) => {
  await page.setViewportSize({ width: 480, height: 900 });
  await createReadyAccount(page, runtime);
  await openCore(page, "inventory");
  const inventory = page.getByRole("dialog", { name: "Inventory", exact: true });
  await inventory.locator('[data-inventory-tab="Emotes"]').click();
  const grid = inventory.locator(".inventory-content .cards-grid");
  const preview = inventory.locator(".inventory-preview");
  await expect(preview).toBeVisible();
  const gridBox = await grid.boundingBox();
  const previewBox = await preview.boundingBox();
  expect(previewBox.y).toBeGreaterThan(gridBox.y);
});

test("admins can open the Multiverse activity from the toolbar", async ({ page, runtime }) => {
  await createReadyAccount(page, runtime, "siteadmin");
  const toggle = page.locator("#multiverse-toggle");
  await expect(toggle).toBeVisible();
  await toggle.click();
  await expect(page.locator('iframe[src*="multiverse"]')).toBeVisible();
  await expect(page.frameLocator('iframe[src*="multiverse"]').locator("#multiverse-error")).toBeVisible();
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
    await command(page, ".talk caretaker");
    await expect(page.locator("#look-bar")).toContainText("Welcome in!");
    const exit = page.locator("#actions-bar").getByRole("button", { name: "Exit Conversation", exact: true });
    await expect(exit).toBeVisible();
    await page.locator("#actions-bar").getByRole("button", { name: "House chores", exact: true }).click();
    await expect(page.locator("#look-bar")).toContainText("Supplies and a vacuum are behind the kitchen.");
    await expect(exit).toBeVisible();
    await exit.click();
    await expect(exit).toHaveCount(0);
    expect(sentCommands).toContain(".talk caretaker");
    expect(sentCommands.some(item => item.startsWith(".dialog "))).toBe(true);
    expect(sentCommands).toContain(".dialog_end");
  });
});

