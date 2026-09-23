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

export async function closeOverlays(page) {
  if (await page.locator("#detail-layer [role=dialog]").count()) await page.keyboard.press("Escape");
  if (await page.locator("#panel-layer [role=dialog]").count()) await page.keyboard.press("Escape");
}

export async function openCore(page, id) {
  await closeOverlays(page);
  await page.locator(`#card-hand [data-core-id="${id}"]`).click();
  await expect(page.locator("#panel-layer [role=dialog]")).toBeVisible();
}

// Select the room by clicking an empty board point, then open Room View from its quick actions.
// Create an account and grant it builder power through the bootstrap admin.
export async function createEditorAccount(page, runtime, username = "editor") {
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
  const context = await page.context().browser().newContext({ ignoreHTTPSErrors: true });
  try {
    const adminPage = await context.newPage();
    await createReadyAccount(adminPage, runtime, "siteadmin");
    await command(adminPage, `.builder grant @${username}`);
  } finally {
    await context.close();
  }
  await page.goto(runtime.baseURL);
  await expect(page.getByRole("button", { name: `Select ${username}`, exact: true })).toBeVisible();
  await expect(page.locator("#board-canvas")).toHaveAttribute("data-board-ready", "true");
}

// Select the room by clicking an empty board point, then open the editor.
export async function openEditRoom(page) {
  await closeOverlays(page);
  const box = await page.locator("#board-canvas").boundingBox();
  const action = page.locator("#actions-bar").getByRole("button", { name: "Edit Room", exact: true });
  for (const [fx, fy] of [[0.5, 0.06], [0.5, 0.94], [0.08, 0.5], [0.92, 0.5], [0.5, 0.5]]) {
    await page.mouse.click(box.x + box.width * fx, box.y + box.height * fy);
    if (await action.count()) {
      await action.click();
      const panel = page.locator("#panel-layer .edit-room-view");
      await expect(panel).toBeVisible();
      await expect(panel).toContainText("Add a prop");
      return panel;
    }
  }
  throw new Error("Could not open Edit Room: no board point selected the room.");
}

export async function openRoomView(page) {
  await closeOverlays(page);
  const box = await page.locator("#board-canvas").boundingBox();
  const action = page.locator("#actions-bar").getByRole("button", { name: "Open Room View", exact: true });
  for (const [fx, fy] of [[0.5, 0.06], [0.5, 0.94], [0.08, 0.5], [0.92, 0.5], [0.5, 0.5]]) {
    await page.mouse.click(box.x + box.width * fx, box.y + box.height * fy);
    if (await action.count()) {
      await action.click();
      await expect(page.locator("#panel-layer [role=dialog]")).toBeVisible();
      return;
    }
  }
  throw new Error("Could not open Room View: no board point selected the room.");
}

async function openPeepAction(page, label) {
  await closeOverlays(page);
  await page.locator("#peeps-panel .peep-chip.self [data-peep-id]").click();
  await page.locator("#actions-bar").getByRole("button", { name: label, exact: true }).click();
  await expect(page.locator("#panel-layer [role=dialog]")).toBeVisible();
}

export async function openSelf(page) {
  await openPeepAction(page, "Open Self");
}

export async function openFriends(page) {
  await openPeepAction(page, "Friends");
}

export async function openSkills(page) {
  await openPeepAction(page, "Skills");
}

// Click across the floor until a prop (not the room) is selected; returns whether one was found.
export async function selectFirstProp(page) {
  const box = await page.locator("#board-canvas").boundingBox();
  for (let fy = 0.05; fy <= 0.95; fy += 0.06) {
    for (let fx = 0.05; fx <= 0.95; fx += 0.06) {
      await page.mouse.click(box.x + box.width * fx, box.y + box.height * fy);
      if (await page.locator("#actions-bar").getByRole("button", { name: "Inspect", exact: true }).count()) return true;
    }
  }
  return false;
}

export async function travel(page, exit = "exit0", label = "The Playroom") {
  await command(page, `.go @way:${exit}`);
  await expect(page.locator("#look-bar")).toContainText(label);
  await expect(page.locator("#board-canvas")).toHaveAttribute("data-board-ready", "true", { timeout: 20_000 });
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
  const pendingModels = page.locator("canvas[data-prop-model]:not([data-model-ready='true']):not([data-model-error='true'])");
  if (await pendingModels.count()) {
    await expect(pendingModels).toHaveCount(0, { timeout: 20_000 });
  }
  const pendingThumbnails = page.locator("img[data-thumb-model]:not([data-thumb-ready='true']):not([data-thumb-error='true'])");
  if (await pendingThumbnails.count()) {
    await expect(pendingThumbnails).toHaveCount(0, { timeout: 20_000 });
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
