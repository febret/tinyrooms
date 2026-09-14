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

export async function createReadyAccount(page, runtime, username = "sunbeam") {
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
  await page.getByRole("button", { name: "Send message", exact: true }).click();
  await expect(page.locator("#chat-input")).toHaveValue("", { timeout: 20_000 });
}

export async function openCore(page, id) {
  if (await page.locator("#detail-layer [role=dialog]").count()) await page.keyboard.press("Escape");
  if (await page.locator("#panel-layer [role=dialog]").count()) await page.keyboard.press("Escape");
  const card = page.locator(`#card-hand [data-core-id="${id}"]`);
  if (!await card.count()) await page.locator("#card-hand [data-core-expand]").click();
  await card.click();
  await expect(page.locator("#panel-layer [role=dialog]")).toBeVisible();
}

export async function travel(page, exit = "exit0", label = "The Playroom") {
  await command(page, `.go @way:${exit}`);
  await expect(page.locator("#look-bar")).toContainText(label);
  await expect(page.locator("#board-canvas")).toHaveAttribute("data-board-ready", "true", { timeout: 20_000 });
}

export async function assertDock(page) {
  const size = page.viewportSize();
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(size.width);
  for (const selector of ["#chat-input", "#command-button", "#card-hand [data-core-id=room]", "#peeps-panel .self button"]) {
    const element = page.locator(selector);
    await expect(element).toBeVisible();
    const box = await element.boundingBox();
    expect(box.x, `${selector} left`).toBeGreaterThanOrEqual(0);
    expect(box.y, `${selector} top`).toBeGreaterThanOrEqual(0);
    expect(box.x + box.width, `${selector} right`).toBeLessThanOrEqual(size.width + 1);
    expect(box.y + box.height, `${selector} bottom`).toBeLessThanOrEqual(size.height + 1);
    expect(box.height, `${selector} touch height`).toBeGreaterThanOrEqual(44);
  }
}

export async function bootstrap(page) {
  const response = await page.request.get("/api/bootstrap");
  expect(response.ok()).toBeTruthy();
  return response.json();
}

export async function settleArtwork(page, { allowToasts = false } = {}) {
  if (await page.locator("#peeps-panel .self").count()) {
    await expect(page.locator("#board-canvas")).toHaveAttribute("data-board-ready", "true", { timeout: 20_000 });
  }
  for (const frame of page.frames()) {
    await frame.evaluate(async () => {
      await document.fonts.ready;
      const visible = [...document.images].filter(image => {
        const box = image.getBoundingClientRect();
        return box.width && box.height && box.bottom > 0 && box.right > 0
          && box.top < innerHeight && box.left < innerWidth;
      });
      await Promise.all(visible.map(image => image.decode()));
    });
  }
  if (!allowToasts) await expect(page.locator("#toast-stack .toast")).toHaveCount(0);
}
