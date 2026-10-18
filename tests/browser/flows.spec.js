import { test, expect } from "./fixtures.js";
import { PASSWORD, command, confirmSticker, createAccount, createReadyAccount, openCore, openEditRoom, travel } from "./helpers.js";

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
  await pickerToggle.click();
  const roomCard = picker.locator('[data-stack-id][data-scope="room"]').first();
  const cardLabel = await roomCard.getAttribute("aria-label");
  await roomCard.click();
  await expect(picker).toBeHidden();
  await expect(page.locator("#look-bar")).toContainText(cardLabel);
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

  test("buy, design, and enter a player bedroom from the corridor", async ({ page, runtime }, testInfo) => {
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
    const editor = await openEditRoom(page);
    await expect(page.locator("#card-hand")).toBeHidden();
    await editor.getByRole("button", { name: "Add text", exact: true }).click();
    const textDialog = page.getByRole("dialog", { name: "Add text", exact: true });
    await textDialog.getByLabel("Text", { exact: true }).fill("Café\nWelcome");
    await textDialog.getByLabel("Font", { exact: true }).selectOption("serif");
    await textDialog.getByLabel("Color", { exact: true }).fill("#cc6633");
    await expect(textDialog.getByRole("button", { name: "Create", exact: true })).toBeEnabled();
    await expect(textDialog.locator("canvas")).toHaveAttribute("data-board-ready", "true");
    await page.screenshot({ path: testInfo.outputPath("text-dialog-desktop.png") });
    await page.setViewportSize({ width: 390, height: 844 });
    await expect(textDialog.getByRole("button", { name: "Create", exact: true })).toBeVisible();
    await page.screenshot({ path: testInfo.outputPath("text-dialog-mobile.png") });
    await page.setViewportSize({ width: 1280, height: 800 });
    await textDialog.getByRole("button", { name: "Create", exact: true }).click();
    await expect(textDialog).toHaveCount(0);
    await expect(editor.locator("[data-edit-selected-name]")).toHaveText("Café Welcome");
    await page.keyboard.press("ArrowRight");
    await page.keyboard.press("+");
    await editor.getByRole("button", { name: "Edit text", exact: true }).click();
    const editText = page.getByRole("dialog", { name: "Edit text", exact: true });
    await editText.getByLabel("Text", { exact: true }).fill("Café\nHello!");
    await editText.getByRole("button", { name: "Apply", exact: true }).click();
    await editor.getByRole("button", { name: "Undo", exact: true }).click();
    await expect(editor.locator("[data-edit-selected-name]")).toHaveText("Café Welcome");
    await editor.getByRole("button", { name: "Redo", exact: true }).click();
    const savedLayout = page.waitForResponse(response => response.url().includes("/layout") && response.request().method() === "POST");
    await editor.getByRole("button", { name: "Close room editor", exact: true }).click();
    const saved = await (await savedLayout).json();
    const sign = saved.layout.props.find(prop => prop.prop_id === "builtin:text");
    expect(sign.text).toEqual({ content: "Café\nHello!", font_id: "serif", color: "#cc6633" });
    expect(sign.position[0]).toBe(55);
    expect(sign.scale).toBeGreaterThan(1);
    await expect(editor).toHaveCount(0);
    await expect(page.locator("#card-hand")).toBeVisible();
    await expect(page.locator(".interaction-dock")).toBeVisible();
    await page.reload();
    await expect(page.locator("#board-canvas")).toHaveAttribute("data-board-ready", "true");
    const reloadLayout = page.waitForResponse(response => response.url().includes("/layout") && response.request().method() === "GET");
    const reloadedEditor = await openEditRoom(page);
    const layout = await (await reloadLayout).json();
    await expect(reloadedEditor.getByRole("button", { name: "Add text", exact: true })).toBeVisible();
    expect(layout.layout.props.find(prop => prop.id === sign.id)).toEqual(sign);
  });
});
