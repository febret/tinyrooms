import { test, expect } from "./fixtures.js";
import { command, confirmSticker, createAccount, createEditorAccount, createReadyAccount, openCore, openEditRoom, openFriends, openRoomView, openSelf, openSkills, selectFirstProp, settleArtwork, travel } from "./helpers.js";

// Run explicitly with npm run test:visual. Missing baselines fail, never auto-pass.
function requestedFor() {
  const requested = new Set((process.env.TR_VISUAL_ONLY || "").split(",").map(name => name.trim()).filter(Boolean));
  return { requested, remaining: new Set(requested) };
}

// Freeze wall-clock display only; keep native timers/RAF and the WebGL compositor.
async function freezeClock(page) {
  await page.addInitScript(() => {
    const NativeDate = Date;
    const fixed = new NativeDate("2026-01-15T12:00:00Z").getTime();
    globalThis.Date = class extends NativeDate {
      constructor(...args) { super(...(args.length ? args : [fixed])); }
      static now() { return fixed; }
    };
  });
}

async function capture(page, testInfo, requested, remaining, name, options) {
  if (requested.size && !requested.has(name)) return;
  remaining.delete(name);
  await settleArtwork(page, options);
  await page.evaluate(() => {
    if (document.activeElement instanceof HTMLElement) document.activeElement.blur();
    // Reset horizontally scrollable card strips so captures are not scroll-position dependent.
    for (const selector of ["#card-hand", ".card-hand-strip", ".equipped-hand", "#peeps-panel"]) {
      for (const node of document.querySelectorAll(selector)) node.scrollLeft = 0;
    }
  });
  await page.mouse.move(0, 0);
  const candidate = testInfo.outputPath(`${name}-candidate.png`);
  await page.screenshot({ path: candidate, animations: "disabled", caret: "hide", timeout: 30_000 });
  await testInfo.attach(`${name} candidate (requires design review)`, { path: candidate, contentType: "image/png" });
  await expect.soft(page).toHaveScreenshot(`${name}.png`, {
    animations: "disabled", caret: "hide",
    ...(options?.mask ? { mask: options.mask } : {}),
  });
}

async function gotoRoom(page, way, label) {
  await command(page, `.go @way:${way}`);
  await expect(page.locator("#look-bar")).toContainText(label);
  await expect(page.locator("#board-canvas")).toHaveAttribute("data-board-ready", "true", { timeout: 20_000 });
}

test("reference matrix: auth, onboarding, main, room, details, inventory, peep, bubbles, activity", async ({ page, runtime }, testInfo) => {
  test.setTimeout(240_000);
  const { requested, remaining } = requestedFor();
  await freezeClock(page);
  await page.goto(runtime.baseURL);
  await expect(page.getByRole("button", { name: "Enter Tinyrooms" })).toBeVisible();
  await capture(page, testInfo, requested, remaining, "auth");
  await createAccount(page, runtime, "sunbeam", false);
  const designerFrame = page.frameLocator('iframe[src*="sticker-designer"]');
  await expect(designerFrame.locator("#confirm")).toBeEnabled();
  await capture(page, testInfo, requested, remaining, "onboarding");
  await designerFrame.locator('[data-mode="custom"]').click();
  await expect(designerFrame.locator("body[data-sticker-ready='true']")).toBeVisible();
  await capture(page, testInfo, requested, remaining, "onboarding-custom");
  await designerFrame.locator('[data-mode="presets"]').click();
  await confirmSticker(page);
  await expect(page.getByRole("button", { name: "Select sunbeam", exact: true })).toBeVisible();
  await capture(page, testInfo, requested, remaining, "main");
  await travel(page);
  await capture(page, testInfo, requested, remaining, "playroom-main");
  await openRoomView(page);
  await capture(page, testInfo, requested, remaining, "room");
  await page.locator('#panel-layer [data-stack-id][data-scope="room"]').first().click();
  await page.locator("#actions-bar").getByRole("button", { name: "Inspect", exact: true }).click();
  await capture(page, testInfo, requested, remaining, "details");
  await page.keyboard.press("Escape");
  await page.locator('#panel-layer [data-stack-id][data-scope="room"]').first().click();
  await page.locator("#actions-bar").getByRole("button", { name: "Pick up 1", exact: true }).click();
  await expect(page.locator('#panel-layer [data-stack-id][data-scope="room"]')).toHaveCount(0);
  await openCore(page, "inventory");
  await capture(page, testInfo, requested, remaining, "inventory");
  await page.keyboard.press("Escape");
  await page.getByRole("button", { name: "Select sunbeam", exact: true }).click();
  await capture(page, testInfo, requested, remaining, "peep");
  for (const [style, message] of [["speech", "A little world, a place for you."], ["thought", "(.) A tiny thought."], ["spiky", "(!) Hello Tinyrooms!"]]) {
    await command(page, message);
    await expect(page.locator(`#bubble-layer .${style}`)).toBeVisible();
    await capture(page, testInfo, requested, remaining, `bubble-${style}`);
  }
  await page.locator("#bubble-layer .bubble").click();
  await expect(page.locator("#bubble-layer .bubble")).toHaveCount(0);
  for (const id of ["emotes", "journal"]) {
    await openCore(page, id);
    await capture(page, testInfo, requested, remaining, id);
    await page.keyboard.press("Escape");
  }
  await openSkills(page);
  await capture(page, testInfo, requested, remaining, "skills");
  await page.keyboard.press("Escape");
  for (const [id, open] of [["self", openSelf], ["friends", openFriends]]) {
    await open(page);
    await capture(page, testInfo, requested, remaining, id);
    await page.keyboard.press("Escape");
  }
  await command(page, ".play sample");
  await expect(page.frameLocator('iframe[src*="dev-sample"]').locator("#state")).toContainText("sunbeam");
  await capture(page, testInfo, requested, remaining, "activity");
  await page.getByRole("button", { name: "Close activity" }).click();
  await expect(page.locator(".activity-window")).toHaveCount(0);
  await page.locator("#chat-input").fill(".not-a-real-command");
  await page.getByRole("button", { name: "Send message", exact: true }).click();
  await expect(page.locator("#toast-stack .error").first()).toContainText(/unknown command/i);
  await capture(page, testInfo, requested, remaining, "error-toast", { allowToasts: true });
  expect([...remaining], "Every requested screenshot name must exist in the matrix").toEqual([]);
});

test("milestone 3 room editing: the editor panel", async ({ page, runtime }, testInfo) => {
  test.setTimeout(240_000);
  const { requested, remaining } = requestedFor();
  await freezeClock(page);
  await createEditorAccount(page, runtime, "editor");
  await openEditRoom(page);
  await page.locator('#editor-dock [data-edit-add="plant"]').click();
  await capture(page, testInfo, requested, remaining, "edit-room");
  expect([...remaining], "Every requested screenshot name must exist in the matrix").toEqual([]);
});

test("milestone 3 prop shop: the marketplace", async ({ page, runtime }, testInfo) => {
  test.setTimeout(240_000);
  const { requested, remaining } = requestedFor();
  await freezeClock(page);
  await createEditorAccount(page, runtime, "editor");
  const panel = await openEditRoom(page);
  await panel.getByRole("button", { name: /Prop Shop/ }).click();
  const frame = page.frameLocator('iframe[src*="prop-shop"]');
  await expect(frame.locator("body")).toHaveAttribute("data-shop-ready", "true", { timeout: 30_000 });
  await expect(frame.locator("canvas[data-prop-model][data-model-ready='true']")).toHaveCount(1, { timeout: 20_000 });
  await capture(page, testInfo, requested, remaining, "prop-shop");
  expect([...remaining], "Every requested screenshot name must exist in the matrix").toEqual([]);
});

test("milestone 2 additions: prop details, swap sticker, targeting, shop", async ({ page, runtime }, testInfo) => {
  test.setTimeout(240_000);
  const { requested, remaining } = requestedFor();
  await freezeClock(page);
  await createReadyAccount(page, runtime);

  expect(await selectFirstProp(page), "At least one interactive prop must be selectable on the Hub board").toBe(true);
  await capture(page, testInfo, requested, remaining, "selected-prop");
  await page.locator("#actions-bar").getByRole("button", { name: "Inspect", exact: true }).click();
  await capture(page, testInfo, requested, remaining, "prop-details");
  await page.keyboard.press("Escape");
  await page.keyboard.press("Escape");

  await openSelf(page);
  await page.locator("#panel-layer").getByRole("button", { name: "Swap Sticker…", exact: true }).click();
  await expect(page.getByRole("dialog", { name: "Swap Sticker" })).toBeVisible();
  await capture(page, testInfo, requested, remaining, "swap-sticker");
  await page.keyboard.press("Escape");

  await gotoRoom(page, "exit0", "The Playroom");
  await gotoRoom(page, "exit0", "Sunflower Foyer");
  await gotoRoom(page, "kitchen", "The Buttercup Kitchen");
  await openRoomView(page);
  await page.locator("#panel-layer").getByRole("button", { name: /Tomato Sauce/ }).click();
  await page.locator("#actions-bar").getByRole("button", { name: "Pick up 1", exact: true }).click();
  await openCore(page, "inventory");
  const owned = page.locator("#panel-layer").getByRole("button", { name: /Tomato Sauce/ });
  await owned.click();
  const equip = page.locator("#actions-bar").getByRole("button", { name: "Equip", exact: true });
  if (await equip.count()) await equip.click();
  await owned.click();
  await page.locator("#actions-bar").getByRole("button", { name: "Use on…", exact: true }).click();
  await expect(page.locator("#actions-bar .targeting-hint")).toBeVisible();
  await capture(page, testInfo, requested, remaining, "targeting");
  await page.keyboard.press("Escape");

  await command(page, ".shop");
  const shop = page.locator("#shop-dock");
  await expect(shop.locator(".shop-pack")).toHaveCount(3);
  await capture(page, testInfo, requested, remaining, "shop");
  await shop.locator(".shop-pack").filter({ hasText: "Tinyrooms Base Pack" }).getByRole("button", { name: "Buy" }).click();
  const confirm = page.locator(".global-dialog");
  await expect(confirm).toBeVisible();
  await confirm.getByRole("button", { name: "Buy", exact: true }).click();
  // The reveal contents are randomly drawn, so the layout is covered by flows.spec.js
  // rather than a pixel baseline.
  await expect(page.locator(".pack-reveal")).toBeVisible();
  await expect(page.locator(".pack-reveal-card")).toHaveCount(3);

  expect([...remaining], "Every requested screenshot name must exist in the matrix").toEqual([]);
});

test("milestone 3 phase F: world editor and card database", async ({ page, runtime }, testInfo) => {
  test.setTimeout(240_000);
  const { requested, remaining } = requestedFor();
  await freezeClock(page);
  await createEditorAccount(page, runtime, "curator");

  await page.goto(`${runtime.baseURL}/world-editor/`);
  await expect(page.locator("#we-canvas")).toHaveAttribute("data-board-ready", "true", { timeout: 20_000 });
  // The live WebGL board renders nondeterministically under SwiftShader; its
  // behavior is covered by flows.spec.js, so mask the canvas pixels here.
  await capture(page, testInfo, requested, remaining, "world-editor", { mask: [page.locator("#we-canvas")] });

  await page.goto(`${runtime.baseURL}/card-database/`);
  await expect(page.locator(".card-tile").first()).toBeVisible();
  await capture(page, testInfo, requested, remaining, "card-database");

  expect([...remaining], "Every requested screenshot name must exist in the matrix").toEqual([]);
});

test("milestone 3 phase G: lazor rush ready state", async ({ page, runtime }, testInfo) => {
  test.setTimeout(240_000);
  const { requested, remaining } = requestedFor();
  await freezeClock(page);
  await createReadyAccount(page, runtime);
  await travel(page);
  await command(page, ".play molly");
  const frame = page.frameLocator('iframe[src*="lazor-rush"]');
  await expect(frame.locator("#start")).toBeVisible();
  await expect(frame.locator("#overlay-title")).toHaveText("Lazor Rush");
  await expect(frame.locator("#stage")).toHaveAttribute("data-molly-ready", "true");
  await capture(page, testInfo, requested, remaining, "lazor-rush");

  expect([...remaining], "Every requested screenshot name must exist in the matrix").toEqual([]);
});
