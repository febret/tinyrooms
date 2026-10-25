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
    const designer = page.frameLocator('iframe[src*="sticker-designer"]');
    await expect(designer.locator("#custom-pane")).toBeVisible();
    await expect(designer.locator("#presets-pane")).toBeHidden();
    await expect(designer.locator('[data-mode="presets"]')).toBeHidden();
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
  await expect(page.locator("#core-tools [data-core-id]")).toHaveCount(3);
  await expect(page.locator("#multiverse-toggle")).toHaveCount(0);
  await expect(page.locator("#card-hand [data-core-id], #card-hand [data-core-expand]")).toHaveCount(0);
  for (const id of ["inventory", "journal", "phone"]) {
    await expect(page.locator(`#core-tools [data-core-id="${id}"]`)).toBeVisible();
  }
  await expect(page.locator("#peeps-panel")).toBeVisible();
  await expect(page.locator("#peeps-panel .peep-name")).toHaveCount(0);
  await expect(page.locator("#peeps-panel .peep-statuses")).toHaveCount(0);
  const statusButton = page.locator('#status-tools [data-status-toggle]');
  await expect(statusButton).toBeVisible();
  await statusButton.click();
  const statusJournal = page.getByRole("dialog", { name: "Identity card", exact: true });
  await expect(statusJournal).toBeVisible();
  await expect(statusJournal.locator('[data-id-flip="1"]')).toContainText("Skills");
  await page.keyboard.press("Escape");
  await expect(statusJournal).toBeHidden();
  const bopsButton = page.locator("#bops-toggle");
  await expect(bopsButton).toBeVisible();
  await expect(bopsButton.locator(".bops-number")).toBeVisible();
  await bopsButton.click();
  const shop = page.frameLocator('iframe[src*="/activities/shop/"]');
  await expect(page.locator('iframe[src*="/activities/shop/"]')).toBeVisible();
  await expect(shop.locator('[data-tab="cards"]')).toBeVisible();
  await page.locator('.activity-window [aria-label="Close activity"]').click();
  await expect(page.locator('iframe[src*="/activities/shop/"]')).toHaveCount(0);
  await page.locator("#settings summary").click();
  const peeps = page.locator('[data-top-action="peeps"]');
  await expect(peeps).toHaveAttribute("aria-pressed", "true");
  await peeps.click();
  await expect(page.locator("#peeps-panel")).toBeHidden();
  await expect(peeps).toHaveAttribute("aria-pressed", "false");
  await peeps.click();
  await expect(page.locator("#peeps-panel")).toBeVisible();
  await expect(peeps).toHaveAttribute("aria-pressed", "true");
  await page.locator("#sidebar-size").selectOption("large");
  await expect(page.locator("#app")).toHaveAttribute("data-sidebar-size", "large");
  await page.locator("#toolbar-size").selectOption("compact");
  await expect(page.locator("#app")).toHaveAttribute("data-toolbar-size", "compact");
  await page.locator("#sidebar-size").selectOption("normal");
  await page.locator("#toolbar-size").selectOption("normal");
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
  await expect(preview.locator("img.look-preview-card-icon")).toBeVisible();
  await preview.click();
  const inventory = page.getByRole("dialog", { name: "Inventory", exact: true });
  await expect(inventory).toBeVisible();
  await expect(inventory.locator(".inventory-preview canvas[data-card-face]")).toBeVisible();
  await expect(inventory.locator(".inventory-preview-name")).toHaveText(cardLabel);
  await inventory.locator('[data-inventory-tab="Emotes"]').click();
  const tiles = inventory.locator(".inventory-content .cards-grid .game-card");
  await expect(tiles.first()).toBeVisible();
  const inventoryPreview = inventory.locator(".inventory-preview canvas[data-card-face]");
  await expect(inventoryPreview).toBeVisible();
  const firstFace = await inventoryPreview.getAttribute("data-card-face");
  await tiles.nth(1).click();
  await expect(inventoryPreview).not.toHaveAttribute("data-card-face", firstFace);
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
  await expect(journal.locator("[data-journal-tab]")).toHaveCount(2);
  for (const tab of ["Tasks", "Memories"]) {
    const button = journal.locator(`[data-journal-tab="${tab}"]`);
    await button.click();
    await expect(button).toHaveAttribute("aria-pressed", "true");
    await expect(journal.locator(".journal-page")).toHaveCount(2);
    await expect(journal.locator(".journal-page-left")).toBeVisible();
    await expect(journal.locator(".journal-page-right")).toBeVisible();
  }
  await expect(journal.locator('[data-close-view="1"]')).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(journal).toBeHidden();
  await statusButton.click();
  const idCard = page.getByRole("dialog", { name: "Identity card", exact: true });
  await expect(idCard).toBeVisible();
  await expect(idCard.getByRole("progressbar", { name: "Next level", exact: true })).toBeVisible();
  for (const name of ["Health", "Energy", "Clean"]) {
    await expect(idCard.getByRole("progressbar", { name, exact: true })).toBeVisible();
  }
  await expect(idCard.locator("[data-level-up]")).toBeDisabled();
  await idCard.locator('[data-id-flip="1"]').click();
  await expect(idCard.locator('[data-id-flip="1"]')).toContainText("ID");
});

test("phone opens apps, friends, and the personal chiptune player", async ({ page, runtime }) => {
  test.slow();
  await page.route("**/api/chiptune/suggestions*", route => route.fulfill({
    json: {
      ok: true,
      top: [{ id: "top-1", title: "Top Track", subtitle: "Game", kind: "file" }],
      community: [{ id: "star-1", title: "Starred Track", subtitle: "Starred by 2 Tinyrooms players", kind: "file", stars: 2 }],
    },
  }));
  await createReadyAccount(page, runtime);
  await openCore(page, "phone");
  const phone = page.getByRole("dialog", { name: "Phone", exact: true });
  await expect(phone).toBeVisible();
  await expect(phone.locator(".phone-lid svg")).toBeVisible();
  await expect(phone.locator("[data-phone-app]")).toHaveCount(2);
  const toolbar = await page.locator(".topbar").boundingBox();
  const device = await phone.locator(".phone-device").boundingBox();
  expect(device.y).toBeGreaterThanOrEqual(toolbar.y + toolbar.height);

  await phone.locator('[data-phone-app="friends"]').click();
  await expect(phone).toContainText("Incoming beacons");
  await expect(phone).toContainText("Incoming requests");
  const keypad = phone.locator(".phone-keypad");
  await expect(keypad.locator("button")).toHaveCount(9);
  await expect(keypad.locator('[data-phone-key="volume-up"]')).toBeDisabled();
  await expect(keypad.locator('[data-phone-key="volume-down"]')).toBeDisabled();
  await expect(keypad.locator('[data-phone-key="messages"]')).toBeDisabled();
  await expect(keypad.locator('[data-phone-key="friend-prev"]')).toBeDisabled();
  await expect(keypad.locator('[data-phone-key="friend-next"]')).toBeDisabled();
  await expect(phone.locator(".phone-lcd")).toHaveCSS("font-size", "13.5px");

  await phone.locator('[data-phone-home="1"]').first().click();
  await expect(phone.locator("[data-phone-app]")).toHaveCount(2);

  await phone.locator('[data-phone-app="chiptune"]').click();
  await expect(phone.getByText("TOP TRACKS", { exact: true })).toBeVisible();
  await expect(phone.getByText("STARRED BY PEEPS", { exact: true })).toBeVisible();
  await expect(phone.locator(".phone-track")).toHaveCount(2);
  await expect(phone.getByRole("button", { name: "Play Top Track", exact: true })).toBeVisible();
  await phone.getByRole("button", { name: "Play Top Track", exact: true }).click();
  await expect(phone.locator(".phone-now-playing.playing")).toBeVisible();
  await keypad.locator('[data-phone-key="music-next"]').click();
  await expect(phone.locator(".phone-now-copy strong")).toContainText("Starred Track");
  await keypad.locator('[data-phone-key="music-prev"]').click();
  await expect(phone.locator(".phone-now-copy strong")).toContainText("Top Track");
  await keypad.locator('[data-phone-key="music-star"]').click();
  await expect(keypad.locator('[data-phone-key="music-star"]')).toHaveAttribute("aria-pressed", "true");

  await page.setViewportSize({ width: 390, height: 844 });
  const mobileToolbar = await page.locator(".topbar").boundingBox();
  const mobileDevice = await phone.locator(".phone-device").boundingBox();
  expect(mobileDevice.y).toBeGreaterThanOrEqual(mobileToolbar.y + mobileToolbar.height);
  expect(Math.abs(mobileDevice.x + mobileDevice.width / 2 - 195)).toBeLessThan(3);

  await phone.locator(".phone-close[data-close-view]").click();
  await expect(phone).toBeHidden();
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

test("admins see the Multiverse toggle in the toolbar", async ({ page, runtime }) => {
  await createReadyAccount(page, runtime, "siteadmin");
  await expect(page.locator("#multiverse-toggle")).toBeVisible();
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

test("emote chat bubbles appear and dismiss", async ({ page, runtime }) => {
  await createReadyAccount(page, runtime);
  await page.locator("#emote-toggle").click();
  const emote = page.locator("#emote-menu [data-emote-play]").first();
  await expect(emote).toBeVisible();
  await emote.click();
  const bubbles = page.locator("#bubble-layer .bubble:not(.move)");
  await expect(bubbles).toHaveCount(1);
  await bubbles.first().click();
  await expect(bubbles).toHaveCount(0);
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
    const dialogBubble = page.locator("#look-bar .look-dialog-bubble");
    await expect(dialogBubble).toContainText("Welcome in!");
    await expect(page.locator('[data-peep-id="caretaker"]')).toHaveAttribute("aria-pressed", "true");
    const otherPeep = page.locator('[data-peep-id]:not([data-peep-id="caretaker"])').first();
    await otherPeep.click();
    await expect(dialogBubble).toHaveCount(0);
    const exit = page.locator("#actions-bar").getByRole("button", { name: "Exit Conversation", exact: true });
    await expect(exit).toBeVisible();
    await page.locator("#actions-bar").getByRole("button", { name: "House chores", exact: true }).click();
    await expect(dialogBubble).toContainText("Supplies and a vacuum are behind the kitchen.");
    await expect(page.locator('[data-peep-id="caretaker"]')).toHaveAttribute("aria-pressed", "true");
    await expect(exit).toBeVisible();
    await exit.click();
    await expect(exit).toHaveCount(0);
    await expect(dialogBubble).toHaveCount(0);
    expect(sentCommands).toContain(".talk caretaker");
    expect(sentCommands.some(item => item.startsWith(".dialog "))).toBe(true);
    expect(sentCommands).toContain(".dialog_end");
  });
});

