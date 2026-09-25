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

async function loginAccount(page, runtime, username) {
  const origin = new URL(runtime.baseURL).origin;
  const response = await page.request.post(`${runtime.baseURL}/api/auth/login`, {
    data: { username, password: PASSWORD },
    headers: { Origin: origin },
  });
  expect(response.ok(), await response.text()).toBeTruthy();
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
  if (await page.locator("#detail-layer [role=dialog]").count()) await page.keyboard.press("Escape");
  if (await page.locator("#panel-layer [role=dialog]").count()) await page.keyboard.press("Escape");
}

export async function openCore(page, id) {
  await closeOverlays(page);
  await page.locator(`#card-hand [data-core-id="${id}"]`).click();
  await expect(page.locator("#panel-layer [role=dialog]")).toBeVisible();
}

// Create an account and grant it builder power through the bootstrap admin.
// One browser context is reused: boot as siteadmin, run the grant, then sign
// back in as the editor. This avoids the cost of a second context and app boot.
export async function createEditorAccount(page, runtime, username = "editor") {
  await provisionAccount(page, runtime, username);
  await provisionAccount(page, runtime, "siteadmin");
  await loginAccount(page, runtime, "siteadmin");
  await page.goto(runtime.baseURL);
  await command(page, `.builder grant @${username}`);
  await loginAccount(page, runtime, username);
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
      const panel = page.locator("#editor-dock .edit-room-view");
      await expect(panel).toBeVisible();
      await expect(panel.locator(".editor-library-grid")).toBeVisible();
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

// Click across the floor until the prop with the given label is selected; returns its point.
export async function findPropByLabel(page, label) {
  const box = await page.locator("#board-canvas").boundingBox();
  for (let fy = 0.05; fy <= 0.95; fy += 0.05) {
    for (let fx = 0.05; fx <= 0.95; fx += 0.05) {
      const point = { x: box.x + box.width * fx, y: box.y + box.height * fy };
      await page.mouse.click(point.x, point.y);
      const name = await page.locator("#look-bar .look-name").textContent();
      if (name?.trim() === label) return point;
    }
  }
  throw new Error(`Could not find prop "${label}" on the board.`);
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
  const pendingCards = page.locator("canvas[data-card-front]:not([data-card-ready='true']):not([data-card-error='true'])");
  if (await pendingCards.count()) {
    await expect(pendingCards).toHaveCount(0, { timeout: 20_000 });
  }
  // The prop library lazily renders only thumbnails near the viewport, so wait
  // for the tiles the manager actually started rendering, not every clipped tile.
  const pendingThumbnails = page.locator('img[data-thumb-model][data-thumb-pending="true"]:not([data-thumb-ready="true"]):not([data-thumb-error="true"])');
  if (await pendingThumbnails.count()) {
    await expect(pendingThumbnails).toHaveCount(0, { timeout: 30_000 });
  }
  for (const frame of page.frames()) {
    await frame.evaluate(async () => {
      await document.fonts.ready;
      const visible = [...document.images].filter(image => {
        if (!image.currentSrc) return false;
        const box = image.getBoundingClientRect();
        return box.width && box.height && box.bottom > 0 && box.right > 0
          && box.top < innerHeight && box.left < innerWidth;
      });
      await Promise.all(visible.map(image => image.decode().catch(() => {})));
    });
  }
  if (!allowToasts) await expect(page.locator("#toast-stack .toast")).toHaveCount(0);
}
