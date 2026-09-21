import { test, expect } from "./fixtures.js";
import { PASSWORD, bootstrap, command, confirmSticker, createAccount, createReadyAccount, openCore, travel } from "./helpers.js";

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
  await expect(page.locator("#card-hand [data-core-id]")).toHaveCount(7);
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

  test("pickup equips the card into the hand", async ({ page, runtime }) => {
    await createReadyAccount(page, runtime);
    await travel(page);
    await openCore(page, "room");
    await page.locator('#panel-layer [data-stack-id][data-scope="room"]').first().click();
    await page.locator("#actions-bar").getByRole("button", { name: "Pick up 1", exact: true }).click();
    await expect(page.locator('#card-hand [aria-label="Equipped cards"]').getByRole("button", { name: /Fancy Wallet/ })).toHaveCount(1);
    await openCore(page, "inventory");
    await expect(page.locator("#panel-layer").getByRole("button", { name: /Fancy Wallet, equipped/ })).toHaveCount(1);
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
    expect(summary.owned.map(action => action.label)).toEqual(["Inspect", "Drop 1", "Drop…"]);
    expect(summary.owned[2].target).toBe("local:quantity:3:drop");
    expect(summary.pinned.filter(action => action.label.startsWith("Pick up")).every(action => action.disabled)).toBe(true);
  });
});

test("hub portal prop requests its glb animation", async ({ page, runtime }) => {
  const snapshots = [];
  page.on("websocket", socket => socket.on("framereceived", ({ payload }) => {
    try {
      const envelope = JSON.parse(String(payload));
      if (envelope.type === "room.snapshot" && envelope.room) snapshots.push(envelope);
    } catch {
      // Ignore non-JSON control frames.
    }
  }));
  await createReadyAccount(page, runtime);
  await expect.poll(() => snapshots.find(snapshot => snapshot.room?.id === "hub")).not.toBeUndefined();
  const hub = snapshots.find(snapshot => snapshot.room?.id === "hub").room;
  expect(hub.props.find(prop => prop.id === "portal0")?.animation).toBe("auto");
  await expect(page.locator("#board-canvas")).toHaveAttribute("data-board-ready", "true");
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
