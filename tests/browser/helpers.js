import { expect } from "./fixtures.js";

export const PASSWORD = "Test-password-42";

export async function createAccount(page, runtime, username = "sunbeam", confirm = true) {
  await page.goto(runtime.baseURL);
  await page.getByRole("button", { name: "Create New Account", exact: true }).click();
  await page.getByLabel("Username", { exact: true }).fill(username);
  await page.getByLabel("Password", { exact: true }).fill(PASSWORD);
  await page.getByLabel("Invitation passphrase").fill(runtime.invitation);
  await page.getByRole("button", { name: "Create account", exact: true }).click();
  const activity = page.locator(".activity-window");
  await expect(activity).toBeVisible();
  await expect(activity.locator("iframe")).toHaveAttribute("src", /sticker-designer/);
  if (!confirm) return;
  await confirmSticker(page);
  await expect(page.getByRole("button", { name: `Select ${username}`, exact: true })).toBeVisible();
  await expect(page.locator("#board-canvas")).toHaveAttribute("data-board-ready", "true", { timeout: 20_000 });
}

async function provisionAccount(page, runtime, username) {
  const origin = new URL(runtime.baseURL).origin;
  const created = await page.request.post(`${runtime.baseURL}/api/auth/create`, {
    data: { username, password: PASSWORD, passphrase: runtime.invitation },
    headers: { Origin: origin },
  });
  expect(created.ok(), await created.text()).toBeTruthy();
  const { csrf_token: csrfToken } = await created.json();
  const confirmed = await page.request.post(`${runtime.baseURL}/api/stickers/confirm`, {
    data: { sticker: "s1.png" },
    headers: { Origin: origin, "X-CSRF-Token": csrfToken },
  });
  expect(confirmed.ok(), await confirmed.text()).toBeTruthy();
}

export async function createReadyAccount(page, runtime, username = "sunbeam") {
  await provisionAccount(page, runtime, username);
  await page.goto(runtime.baseURL);
  await expect(page.getByRole("button", { name: `Select ${username}`, exact: true })).toBeVisible();
  await expect(page.locator("#board-canvas")).toHaveAttribute("data-board-ready", "true");
}

export async function confirmSticker(page) {
  const frame = page.frameLocator('iframe[src*="sticker-designer"]');
  await expect(frame.locator("#confirm")).toBeEnabled();
  await frame.locator("#confirm").click();
  await expect(page.locator('iframe[src*="sticker-designer"]')).toHaveCount(0);
  await expect(page.locator("#chat-input")).toBeEnabled();
}

export async function command(page, text) {
  await page.locator("#chat-input").fill(text);
  await page.locator("#chat-input").press("Enter");
  await expect(page.locator("#chat-input")).toHaveValue("", { timeout: 20_000 });
}

export async function closeOverlays(page) {
  if (await page.locator("#panel-layer [role=dialog]").count()) await page.keyboard.press("Escape");
}

export async function openCore(page, id) {
  await closeOverlays(page);
  await page.locator(`#core-tools [data-core-id="${id}"]`).click();
  await expect(page.locator("#panel-layer [role=dialog]")).toBeVisible();
}

export async function openEditRoom(page) {
  await closeOverlays(page);
  const action = page.locator("#core-tools [data-edit-room]");
  if (!(await action.count())) throw new Error("Could not open Edit Room: the room is not editable.");
  await action.click();
  const panel = page.locator("#editor-dock .edit-room-view");
  await expect(panel).toBeVisible();
  await expect(panel.locator(".editor-library-grid")).toBeVisible();
  return panel;
}

export async function travel(page, exit = "exit0", label = "The Living Room") {
  await command(page, `.go @way:${exit}`);
  await expect(page.locator("#look-bar")).toContainText(label);
  await expect(page.locator("#board-canvas")).toHaveAttribute("data-board-ready", "true", { timeout: 20_000 });
}
