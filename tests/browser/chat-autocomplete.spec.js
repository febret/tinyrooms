import { test, expect } from "./fixtures.js";
import { createReadyAccount, openCore } from "./helpers.js";

// Functional flows run on desktop only unless tagged @mobile; these tests cover
// the chat-bar autocomplete behaviour and are tagged so portrait also runs them.
test.beforeEach(({ isMobile }, testInfo) => {
  test.skip(Boolean(isMobile) && !testInfo.tags.includes("@mobile"), "Desktop-only flow; portrait is covered by test:visual.");
});

test("overlay blocks board hit testing and chat autocompletes commands", { tag: "@mobile" }, async ({ page, runtime }) => {
  const sentCommands = [];
  page.on("websocket", socket => socket.on("framesent", ({ payload }) => {
    const envelope = JSON.parse(String(payload));
    if (envelope.type === "command") sentCommands.push(envelope.command);
  }));
  await createReadyAccount(page, runtime);
  await openCore(page, "inventory");
  const board = await page.locator("#board-canvas").boundingBox();
  expect(await page.evaluate(({ x, y }) => document.elementFromPoint(x, y)?.id, {
    x: board.x + board.width - 3, y: board.y + board.height / 2,
  })).not.toBe("board-canvas");
  await page.keyboard.press("Escape");
  await expect(page.getByRole("button", { name: "Open command menu" })).toHaveCount(0);
  await page.locator("#chat-input").fill(".pick");
  const completions = page.locator("#chat-completions");
  await expect(completions).toBeVisible();
  await expect(completions.getByRole("option").filter({ hasText: ".pickup" }).first()).toBeVisible();
  await page.locator("#chat-input").press("ArrowDown");
  await expect(completions.getByRole("option").first()).toHaveClass(/active/);
  await page.locator("#chat-input").press("Enter");
  await expect(page.locator("#chat-input")).toHaveValue(/^\.pickup $/);
  await expect(completions).toBeHidden();
  await page.getByRole("button", { name: "Send message", exact: true }).click();
  await expect.poll(() => sentCommands.at(-1)).toBe(".pickup");
  expect(sentCommands.some(command => command.startsWith('.say ".pickup'))).toBe(false);
  await expect(page.locator("#toast-stack .error").first()).toBeVisible();
  await page.locator("#settings summary").click();
  await page.getByRole("button", { name: "Commands", exact: true }).click();
  await expect(page.getByRole("dialog", { name: "Commands", exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Close", exact: true }).click();
});

test("chat autocompletes room identifiers after @", { tag: "@mobile" }, async ({ page, runtime }) => {
  const sentCommands = [];
  page.on("websocket", socket => socket.on("framesent", ({ payload }) => {
    const envelope = JSON.parse(String(payload));
    if (envelope.type === "command") sentCommands.push(envelope.command);
  }));
  await createReadyAccount(page, runtime);
  await page.locator("#chat-input").fill(".go @w");
  const completions = page.locator("#chat-completions");
  await expect(completions).toBeVisible();
  await expect(completions.getByRole("option").filter({ hasText: "@way:" }).first()).toBeVisible();
  await page.locator("#chat-input").press("ArrowDown");
  await page.locator("#chat-input").press("Enter");
  await expect(page.locator("#chat-input")).toHaveValue(".go @way:");
  await expect(completions.getByRole("option").filter({ hasText: "exit0" }).first()).toBeVisible();
  await page.locator("#chat-input").press("ArrowDown");
  await page.locator("#chat-input").press("Enter");
  await expect(page.locator("#chat-input")).toHaveValue(".go @way:exit0 ");
  await expect(completions).toBeHidden();
  await page.getByRole("button", { name: "Send message", exact: true }).click();
  await expect.poll(() => sentCommands.at(-1)).toBe(".go @way:exit0");
});
