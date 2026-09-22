import { test, expect } from "./fixtures.js";
import { PASSWORD, bootstrap, command, confirmSticker, createAccount, createReadyAccount, openCore, selectFirstProp, travel } from "./helpers.js";

test.describe("account onboarding", () => {
  test.slow();

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

test("core expansion exposes a favorited card", async ({ page, runtime }) => {
  await createReadyAccount(page, runtime);
  await page.locator("#card-hand [data-core-expand]").click();
  await expect(page.locator("#card-hand [data-core-id]")).toHaveCount(8);
  await openCore(page, "journal");
  const favorite = page.locator("#actions-bar").getByRole("button", { name: "Favorite", exact: true });
  await favorite.click();
  await expect.poll(async () => (await bootstrap(page)).user.favorites).toContain("journal");
  await page.keyboard.press("Escape");
  await page.locator("#card-hand [data-core-expand]").click();
  await expect(page.locator('#card-hand [data-core-id="journal"]')).toBeVisible();
});

test.describe("room and inventory", () => {
  test.slow();

  test("support pickup and drop", async ({ page, runtime }) => {
    await createReadyAccount(page, runtime);
    await travel(page);
    await openCore(page, "room");
    const roomCards = page.locator('#panel-layer [data-stack-id][data-scope="room"]');
    await expect(roomCards).toHaveCount(1);
    await roomCards.first().click();
    await expect(page.locator("#actions-bar").getByRole("button", { name: "Pick up…", exact: true })).toHaveCount(0);
    await page.locator("#actions-bar").getByRole("button", { name: "Pick up 1", exact: true }).click();
    await expect(page.getByRole("button", { name: "Confirm", exact: true })).toHaveCount(0);
    await expect(roomCards).toHaveCount(0);
    await openCore(page, "inventory");
    const inventoryCards = page.locator("#panel-layer").getByRole("button", { name: /Fancy Wallet/ });
    await expect(inventoryCards).toHaveCount(1);
    await inventoryCards.first().click();
    await expect(page.locator("#actions-bar").getByRole("button", { name: "Drop…", exact: true })).toHaveCount(0);
    await page.locator("#actions-bar").getByRole("button", { name: "Drop 1", exact: true }).click();
    await expect(page.getByRole("button", { name: "Confirm", exact: true })).toHaveCount(0);
    await expect(inventoryCards).toHaveCount(0);
    await openCore(page, "room");
    await expect(roomCards).toHaveCount(1);
  });

  test("dragging from the equipped hand drops a card at the pointer", async ({ page, runtime }) => {
    const sentCommands = [];
    page.on("websocket", socket => socket.on("framesent", ({ payload }) => {
      const envelope = JSON.parse(String(payload));
      if (envelope.type === "command") sentCommands.push(envelope.command);
    }));
    await createReadyAccount(page, runtime);
    await travel(page);
    await openCore(page, "room");
    const roomCards = page.locator('#panel-layer [data-stack-id][data-scope="room"]');
    await expect(roomCards).toHaveCount(1);
    await roomCards.first().click();
    await page.locator("#actions-bar").getByRole("button", { name: "Pick up 1", exact: true }).click();
    await expect(roomCards).toHaveCount(0);
    await page.keyboard.press("Escape");
    await expect(page.locator("#board-canvas")).toHaveAttribute("data-board-ready", "true", { timeout: 20_000 });
    const tile = page.locator(".equipped-hand [data-stack-id]").first();
    await expect(tile).toBeVisible();
    const tileBox = await tile.boundingBox();
    const boardBox = await page.locator("#board-canvas").boundingBox();
    await page.mouse.move(tileBox.x + tileBox.width / 2, tileBox.y + tileBox.height / 2);
    await page.mouse.down();
    await page.mouse.move(boardBox.x + boardBox.width * 0.35, boardBox.y + boardBox.height * 0.45, { steps: 10 });
    await page.mouse.up();
    await expect.poll(() => sentCommands.filter(command => command.startsWith(".drop ")).at(-1))
      .toMatch(/^\.drop @card:\S+ 1 \d+\.\d{2} \d+\.\d{2} \d+\.\d{2}$/);
    await openCore(page, "room");
    await expect(roomCards).toHaveCount(1);
  });

  test("multi-card stacks offer direct and dialog actions", async ({ page, runtime }) => {
    // Multi-copy stacks are not reachable in milestone rooms, so exercise the
    // real client module with fabricated selection state instead of gameplay.
    await page.goto(runtime.baseURL);
    const summary = await page.evaluate(async () => {
      const { selectionActions } = await import("/app/js/cards.js");
      const stack = (stackId, quantity, intent, pinned = false) => ({
        stackId, quantity, pinned,
        definition: { label: "Tasty Toast", description: "Yum.", imageUrl: "", rarity: "Common", type: "item" },
        quickActions: [
          { label: intent === "pickup" ? "Pick up 1" : "Drop 1", command: `.${intent} @card:${stackId} 1` },
        ],
      });
      const stateFor = (kind, current) => ({
        room: {
          label: "Room", description: "",
          roomCards: kind === "room-card" ? [current] : [],
          inventory: kind === "inventory-card" ? [current] : [],
        },
        selection: { kind, id: current.stackId },
        views: {}, user: {},
      });
      const describe = actions => actions.map(action => ({
        label: action.label,
        target: action.command
          ? `command:${action.command}`
          : `local:${action.local?.type}:${action.local?.max}:${action.local?.intent}`,
        disabled: Boolean(action.disabled),
      }));
      return {
        single: describe(selectionActions(stateFor("room-card", stack("a", 1, "pickup")))),
        multi: describe(selectionActions(stateFor("room-card", stack("b", 2, "pickup")))),
        owned: describe(selectionActions(stateFor("inventory-card", stack("c", 3, "drop")))),
        pinned: describe(selectionActions(stateFor("room-card", stack("d", 2, "pickup", true)))),
      };
    });
    expect(summary.single.map(action => action.label)).toEqual(["Inspect", "Pick up 1"]);
    expect(summary.single[1].target).toBe("command:.pickup @card:a 1");
    expect(summary.multi.map(action => action.label)).toEqual(["Inspect", "Pick up 1", "Pick up…"]);
    expect(summary.multi[1].target).toBe("command:.pickup @card:b 1");
    expect(summary.multi[2].target).toBe("local:quantity:2:pickup");
    expect(summary.owned.map(action => action.label)).toEqual(["Inspect", "Drop 1", "Drop…", "Equip"]);
    expect(summary.owned[2].target).toBe("local:quantity:3:drop");
    expect(summary.pinned.filter(action => action.label.startsWith("Pick up")).every(action => action.disabled)).toBe(true);
  });
});

test("overlay blocks board hit testing and command menu sends commands", async ({ page, runtime }) => {
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
  await page.getByRole("button", { name: "Open command menu" }).click();
  await expect(page.getByRole("dialog", { name: "Commands", exact: true })).toBeVisible();
  await page.getByRole("searchbox", { name: "Search commands" }).fill("pickup");
  await page.locator(".command-row").filter({ hasText: "pickup" }).first().click();
  await expect(page.locator("#chat-input")).toHaveValue(".pickup");
  await page.getByRole("button", { name: "Send message", exact: true }).click();
  await expect.poll(() => sentCommands.at(-1)).toBe(".pickup");
  expect(sentCommands.some(command => command.startsWith('.say ".pickup'))).toBe(false);
  await expect(page.locator("#toast-stack .error").first()).toBeVisible();
});

test("sample activity bridges chat and supports minimize, maximize, close", async ({ page, runtime }) => {
  await createReadyAccount(page, runtime);
  await command(page, ".play sample");
  const activity = page.locator(".activity-window");
  await expect(activity).toBeVisible();
  const frame = page.frameLocator('iframe[src*="dev-sample"]');
  await expect(frame.locator("#state")).toContainText("sunbeam");
  await page.locator("#chat-input").fill("");
  await frame.getByRole("button", { name: "Send chat line" }).click();
  await expect(page.locator("#bubble-layer")).toContainText("Hello from Development Activity!");
  await page.locator("#bubble-layer .bubble").click();
  await expect(page.locator("#bubble-layer .bubble")).toHaveCount(0);
  await page.getByRole("button", { name: "Minimize activity" }).click();
  await expect(activity.locator("iframe")).toBeHidden();
  await page.getByRole("button", { name: /Restore activity|Minimize activity/ }).click();
  await expect(activity.locator("iframe")).toBeVisible();
  await page.getByRole("button", { name: "Maximize activity" }).click();
  await expect(activity).toHaveClass(/maximized/);
  await page.getByRole("button", { name: "Close activity" }).click();
  await expect(activity).toHaveCount(0);
});

test.describe("core milestone 2 views", () => {
  test.slow();

  test("self view shows progression and counters", async ({ page, runtime }) => {
    await createReadyAccount(page, runtime);
    await openCore(page, "self");
    const panel = page.locator("#panel-layer [role=dialog]");
    await expect(panel).toContainText("Level 0");
    await expect(panel).toContainText("Guest");
    await expect(panel).toContainText("Health");
    await expect(panel).toContainText("Cleanliness");
    await expect(panel.getByRole("button", { name: /Level Up/ })).toBeDisabled();
  });

  test("inventory view offers claim action and bops header", async ({ page, runtime }) => {
    await createReadyAccount(page, runtime);
    await openCore(page, "inventory");
    const panel = page.locator("#panel-layer [role=dialog]");
    await expect(panel).toContainText("Bops");
    await panel.getByRole("button", { name: "Claim Daily Bops", exact: true }).click();
    await expect.poll(async () => (await bootstrap(page)).user.bops).toBe(11);
  });

  test("skills view renders fifteen locked slots at level zero", async ({ page, runtime }) => {
    await createReadyAccount(page, runtime);
    await openCore(page, "skills");
    const panel = page.locator("#panel-layer [role=dialog]");
    await expect(panel.locator(".skill-slot")).toHaveCount(15);
    await expect(panel.locator(".skill-slot.locked")).toHaveCount(15);
  });

  test("friends, journal, and edit room show intentional states", async ({ page, runtime }) => {
    await createReadyAccount(page, runtime);
    await openCore(page, "friends");
    await expect(page.locator("#panel-layer")).toContainText("No friends yet");
    await openCore(page, "journal");
    const journal = page.locator("#panel-layer [role=dialog]");
    await expect(journal.getByRole("button", { name: "Tasks", exact: true })).toBeVisible();
    await journal.getByRole("button", { name: "Memories", exact: true }).click();
    await expect(journal).toContainText("No memories yet");
    await openCore(page, "edit-room");
    await expect(page.locator("#panel-layer")).toContainText("do not have permission");
  });

  test("swap sticker dialog opens from self view", async ({ page, runtime }) => {
    await createReadyAccount(page, runtime);
    await openCore(page, "self");
    await page.locator("#panel-layer").getByRole("button", { name: "Swap Sticker…", exact: true }).click();
    const dialog = page.getByRole("dialog", { name: "Swap Sticker" });
    await expect(dialog).toBeVisible();
    await expect(dialog.locator(".sticker-choice")).toHaveCount(21);
    await page.keyboard.press("Escape");
    await expect(dialog).toHaveCount(0);
  });

  test("emotes view exposes expression, animation, and effects categories", async ({ page, runtime }) => {
    await createReadyAccount(page, runtime);
    await openCore(page, "emotes");
    const panel = page.locator("#panel-layer [role=dialog]");
    await expect(panel.getByRole("button", { name: "Expression", exact: true })).toBeVisible();
    await expect(panel.getByRole("button", { name: "Animation", exact: true })).toBeVisible();
    await expect(panel.getByRole("button", { name: "Effects", exact: true })).toBeVisible();
  });
});

test.describe("milestone 2 activities and targeting", () => {
  test.slow();

  test("shop activity lists packs and reveals committed cards", async ({ page, runtime }) => {
    await createReadyAccount(page, runtime);
    await command(page, ".shop");
    const activity = page.locator(".activity-window");
    await expect(activity).toBeVisible();
    const frame = page.frameLocator('iframe[src*="shop"]');
    await expect(frame.locator(".pack-card")).toHaveCount(2);
    await expect(frame.locator("#balance")).toContainText("10 Bops");
    await frame.locator(".pack-card").filter({ hasText: "Base Pack" }).getByRole("button", { name: "Buy" }).click();
    await expect(frame.locator("#confirm")).toBeVisible();
    await frame.locator("#confirm-ok").click();
    await expect(frame.locator("#reveal")).toBeVisible();
    await expect(frame.locator(".reveal-card")).toHaveCount(3);
    await frame.locator("#reveal-close").click();
    await expect(frame.locator("#reveal")).toBeHidden();
    await expect(frame.locator("#balance")).toContainText("0 Bops");
  });

  test("targeting a healing card previews, cancels, and rejects full health", async ({ page, runtime }) => {
    await createReadyAccount(page, runtime);
    await command(page, ".go @way:exit0");
    await expect(page.locator("#look-bar")).toContainText("The Playroom");
    await command(page, ".go @way:exit0");
    await expect(page.locator("#look-bar")).toContainText("Sunflower Foyer");
    await command(page, ".go @way:kitchen");
    await expect(page.locator("#look-bar")).toContainText("The Buttercup Kitchen");
    await openCore(page, "room");
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
    await page.keyboard.press("Escape");
    await expect(page.locator("#actions-bar .targeting-hint")).toHaveCount(0);
    await openCore(page, "inventory");
    await owned.click();
    await page.locator("#actions-bar").getByRole("button", { name: "Use on…", exact: true }).click();
    await page.getByRole("button", { name: "Select sunbeam", exact: true }).click();
    await expect(page.locator("#toast-stack .error").first()).toContainText(/full Health/i);
  });
});

test.describe("milestone 2 polish: prop viewer and journal calendar", () => {
  test.slow();

  test("selecting a prop shows a model preview and the details viewer orbits", async ({ page, runtime }) => {
    await createReadyAccount(page, runtime);
    expect(await selectFirstProp(page), "A Hub prop must be selectable").toBe(true);
    await expect(page.locator("#look-preview-layer canvas.look-preview-3d")).toBeVisible();
    await expect(page.locator("#look-preview-layer canvas.look-preview-3d")).toHaveAttribute("data-model-ready", "true", { timeout: 20_000 });
    await page.locator("#actions-bar").getByRole("button", { name: "Inspect", exact: true }).click();
    const canvas = page.locator("#panel-layer canvas.prop-preview-canvas");
    await expect(canvas).toBeVisible();
    await expect(canvas).toHaveAttribute("data-prop-model", /\.glb$/);
    const box = await canvas.boundingBox();
    await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
    await page.mouse.down();
    await page.mouse.move(box.x + box.width / 2 + 45, box.y + box.height / 2 + 12, { steps: 6 });
    await page.mouse.up();
    await expect(canvas).toBeVisible();
    await page.keyboard.press("Escape");
    await expect(page.locator("#panel-layer canvas.prop-preview-canvas")).toHaveCount(0);
  });

  test("journal memories shows a calendar with month navigation", async ({ page, runtime }) => {
    await createReadyAccount(page, runtime);
    await openCore(page, "journal");
    await page.locator("#panel-layer").getByRole("button", { name: "Memories", exact: true }).click();
    const calendar = page.locator("#panel-layer .journal-calendar");
    await expect(calendar).toBeVisible();
    expect(await calendar.locator(".cal-days .cal-cell:not(.empty)").count()).toBeGreaterThanOrEqual(28);
    const label = await calendar.locator(".cal-header strong").textContent();
    await calendar.getByRole("button", { name: "Next month" }).click();
    await expect(calendar.locator(".cal-header strong")).not.toHaveText(label);
    await calendar.getByRole("button", { name: "Previous month" }).click();
    await expect(calendar.locator(".cal-header strong")).toHaveText(label);
  });
});
