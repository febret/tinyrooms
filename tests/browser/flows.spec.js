import { test, expect } from "./fixtures.js";
import { PASSWORD, bootstrap, command, confirmSticker, createAccount, createEditorAccount, createReadyAccount, openCore, openEditRoom, openFriends, openRoomView, openSelf, openSkills, selectFirstProp, travel } from "./helpers.js";

// Functional flows run on desktop only; portrait layout is covered by the visual
// baselines. Tag genuinely mobile-sensitive flows with { tag: "@mobile" }.
test.beforeEach(({ isMobile }, testInfo) => {
  test.skip(Boolean(isMobile) && !testInfo.tags.includes("@mobile"), "Desktop-only flow; portrait is covered by test:visual.");
});

test.describe("account onboarding", () => {
  test.slow();

  test("is mandatory, persists, and shows login errors", { tag: "@mobile" }, async ({ page, runtime }) => {
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

test("all core cards are always visible without an expander", { tag: "@mobile" }, async ({ page, runtime }) => {
  test.slow();
  await createReadyAccount(page, runtime);
  await expect(page.locator("#card-hand [data-core-id]")).toHaveCount(3);
  await expect(page.locator("#card-hand [data-core-expand]")).toHaveCount(0);
  for (const id of ["emotes", "inventory", "journal"]) {
    await expect(page.locator(`#card-hand [data-core-id="${id}"]`)).toBeVisible();
  }
  await openCore(page, "journal");
  await expect(page.locator("#panel-layer [role=dialog]")).toBeVisible();
});

test.describe("room and inventory", () => {
  test.slow();

  test("support pickup and drop", { tag: "@mobile" }, async ({ page, runtime }) => {
    await createReadyAccount(page, runtime);
    await travel(page);
    await openRoomView(page);
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
    await openRoomView(page);
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
    await openRoomView(page);
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
    await openRoomView(page);
    await expect(roomCards).toHaveCount(1);
  });
});

test("overlay blocks board hit testing and command menu sends commands", { tag: "@mobile" }, async ({ page, runtime }) => {
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

test("sample activity bridges chat and supports minimize, maximize, close", { tag: "@mobile" }, async ({ page, runtime }) => {
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

test.describe("client module logic", () => {
  test("card and editor modules expose expected actions and store transitions", async ({ page, runtime }) => {
    await page.goto(runtime.baseURL);
    const summary = await page.evaluate(async () => {
      const { selectionActions } = await import("/app/js/cards.js");
      const { editRoomView } = await import("/app/js/views/edit-room-view.js");
      const { normalizeEditorView, editorReducer, selectedInstance } = await import("/app/js/editing/edit-reducer.js");

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

      const room = { id: "bedroom", label: "Bedroom", description: "", props: [], roomCards: [], inventory: [], quickActions: [], board: { palette: [], imageStyle: "" } };
      const editLabels = canEdit => selectionActions({
        room: { ...room, canEditRoom: canEdit },
        selection: { kind: "room", id: "bedroom" },
        views: {}, user: {},
      }).map(action => action.label);
      const editor = normalizeEditorView({
        room_id: "bedroom", revision: 3, can_edit: true, props: [],
        library: [{ prop_id: "plant", label: "Little Monstera", model_url: "/x.glb", base_scale: 1 }],
        environment_whitelist: ["palette"], environment: {},
      });

      const prop = { id: "portal0", label: "Portal", description: "", modelUrl: "/assets/portal.glb", scale: 1, quickActions: [] };
      const skill = {
        stackId: "inv:skill", quantity: 1, pinned: false, equipped: false,
        definition: { label: "Sturdy", type: "skill", imageUrl: "", rarity: "Common" },
        quickActions: [],
      };
      const propActions = selectionActions({
        room: { props: [prop], roomCards: [], inventory: [] },
        selection: { kind: "prop", id: "portal0" },
        views: {}, user: {},
      });
      const skillActions = selectionActions({
        room: { props: [], roomCards: [], inventory: [skill] },
        selection: { kind: "inventory-card", id: "inv:skill" },
        views: {}, user: {},
      });

      let state = { editor: null };
      state = editorReducer(state, {
        type: "editor-open",
        view: {
          room_id: "hub", revision: 2, can_edit: true, props: [],
          library: [{ prop_id: "plant", label: "Plant", base_scale: 1, scale_min: 0.25, scale_max: 4 }],
          environment_whitelist: ["palette"], environment: {},
        },
      });
      state = editorReducer(state, { type: "editor-add", propId: "plant" });
      const added = state.editor.props.length;
      const id = state.editor.selectedId;
      state = editorReducer(state, { type: "editor-nudge", dx: 5, dy: 5 });
      const moved = selectedInstance(state.editor).position;
      state = editorReducer(state, { type: "editor-undo" });
      const undone = selectedInstance(state.editor).position;
      state = editorReducer(state, { type: "editor-redo" });
      const redone = selectedInstance(state.editor).position;
      state = editorReducer(state, { type: "editor-env", key: "palette", value: ["#111111", "#222222", "#333333"] });
      const dirty = state.editor.dirty;
      state = editorReducer(state, { type: "editor-close" });

      return {
        single: describe(selectionActions(stateFor("room-card", stack("a", 1, "pickup")))),
        multi: describe(selectionActions(stateFor("room-card", stack("b", 2, "pickup")))),
        owned: describe(selectionActions(stateFor("inventory-card", stack("c", 3, "drop")))),
        pinned: describe(selectionActions(stateFor("room-card", stack("d", 2, "pickup", true)))),
        edit: {
          owned: editLabels(true),
          locked: editLabels(false),
          lockedView: editRoomView({ room: { ...room, canEditRoom: false } }).includes("do not have permission"),
          editorView: editRoomView({ room: { ...room, canEditRoom: true }, editor }).includes("Add a prop"),
        },
        prop: propActions.find(action => action.label === "Inspect")?.local,
        slot: skillActions.find(action => action.label === "Slot…")?.local,
        store: { added, id, moved, undone, redone, dirty, closed: state.editor },
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
    expect(summary.edit.owned).toContain("Edit Room");
    expect(summary.edit.locked).not.toContain("Edit Room");
    expect(summary.edit.lockedView).toBe(true);
    expect(summary.edit.editorView).toBe(true);
    expect(summary.prop).toEqual({ type: "open-view", view: "prop-details", propId: "portal0" });
    expect(summary.slot).toEqual({ type: "open-view", view: "skills", stackId: "inv:skill" });
    expect(summary.store.added).toBe(1);
    expect(summary.store.id).toMatch(/^custom:/);
    expect(summary.store.moved).toEqual([55, 55, 0]);
    expect(summary.store.undone).toEqual([50, 50, 0]);
    expect(summary.store.redone).toEqual([55, 55, 0]);
    expect(summary.store.dirty).toBe(true);
    expect(summary.store.closed).toBeNull();
  });

  test("coin effects break Bops into 100/10/1 denominations", async ({ page, runtime }) => {
    await page.goto(runtime.baseURL);
    const breakdowns = await page.evaluate(async () => {
      const { coinBreakdown } = await import("/app/js/coin-effects.js");
      return {
        zero: coinBreakdown(0),
        one: coinBreakdown(1),
        twentyThree: coinBreakdown(23),
        oneTwentyFive: coinBreakdown(125),
        nineNinetyNine: coinBreakdown(999),
      };
    });
    expect(breakdowns.zero).toEqual([]);
    expect(breakdowns.one).toEqual([1]);
    expect(breakdowns.twentyThree).toEqual([10, 10, 1, 1, 1]);
    expect(breakdowns.oneTwentyFive).toEqual([100, 10, 10, 1, 1, 1, 1, 1]);
    expect(breakdowns.nineNinetyNine).toEqual([
      100, 100, 100, 100, 100, 100, 100, 100, 100,
      10, 10, 10, 10, 10, 10, 10, 10, 10,
      1, 1, 1, 1, 1, 1, 1, 1, 1,
    ]);
  });
});

test.describe("core milestone 2 views", () => {
  test.slow();

  test("self view shows progression and counters", async ({ page, runtime }) => {
    await createReadyAccount(page, runtime);
    await openSelf(page);
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
    await openSkills(page);
    const panel = page.locator("#panel-layer [role=dialog]");
    await expect(panel.locator(".skill-slot")).toHaveCount(15);
    await expect(panel.locator(".skill-slot.locked")).toHaveCount(15);
  });

  test("friends and journal show intentional states", async ({ page, runtime }) => {
    await createReadyAccount(page, runtime);
    await openFriends(page);
    await expect(page.locator("#panel-layer")).toContainText("No friends yet");
    await openCore(page, "journal");
    const journal = page.locator("#panel-layer [role=dialog]");
    await expect(journal.getByRole("button", { name: "Tasks", exact: true })).toBeVisible();
    await journal.getByRole("button", { name: "Memories", exact: true }).click();
    await expect(journal).toContainText("No memories this month");
  });

  test("swap sticker dialog opens from self view", async ({ page, runtime }) => {
    await createReadyAccount(page, runtime);
    await openSelf(page);
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

  test("playing an emote shows an emoji bubble and no toast", async ({ page, runtime }) => {
    await createReadyAccount(page, runtime);
    await openCore(page, "emotes");
    await page.locator("#panel-layer").getByRole("button", { name: "Smile", exact: true }).click();
    await expect(page.locator("#panel-layer [role=dialog]")).toHaveCount(0);
    const bubble = page.locator("#bubble-layer .bubble.emote");
    await expect(bubble).toBeVisible();
    await expect(bubble.locator("img.bubble-image")).toHaveAttribute("src", /smile\.webp$/);
    expect(await page.locator("#toast-stack .toast").count()).toBe(0);
  });

  test("playing an animation emote shows a gif bubble sized to the animation", async ({ page, runtime }) => {
    await createReadyAccount(page, runtime);
    await command(page, ".shop");
    const shop = page.locator("#shop-dock");
    await expect(shop.locator(".shop-pack")).toHaveCount(3);
    await shop.locator(".shop-pack").filter({ hasText: "Memebase Pack" }).getByRole("button", { name: "Buy" }).click();
    const confirm = page.locator(".global-dialog");
    await expect(confirm).toBeVisible();
    await confirm.getByRole("button", { name: "Buy", exact: true }).click();
    await expect(page.locator(".pack-reveal-card")).toHaveCount(3);
    await page.locator(".pack-reveal-close").click();
    await shop.getByRole("button", { name: "Close", exact: true }).click();
    await expect(shop).toBeHidden();
    await page.reload();
    await expect(page.locator("#board-canvas")).toHaveAttribute("data-board-ready", "true", { timeout: 20_000 });
    await openCore(page, "emotes");
    const panel = page.locator("#panel-layer [role=dialog]");
    await panel.getByRole("button", { name: "Animation", exact: true }).click();
    const card = panel.locator(".game-card").first();
    await expect(card).toBeVisible();
    await card.click();
    await expect(panel).toHaveCount(0);
    const image = page.locator("#bubble-layer .bubble.emote-animation img.bubble-image");
    await expect(image).toHaveAttribute("src", /^\/assets\/memebase\//);
    await expect(image).toBeVisible();
    const box = await image.boundingBox();
    expect(box.width).toBeGreaterThan(40);
    expect(box.height).toBeGreaterThan(40);
    expect(box.width).toBeLessThanOrEqual(160);
    expect(box.height).toBeLessThanOrEqual(160);
  });

});

test.describe("milestone 2 activities and targeting", () => {
  test.slow();

  test("shop dock lists packs and reveals committed cards", async ({ page, runtime }) => {
    await createReadyAccount(page, runtime);
    await command(page, ".shop");
    const shop = page.locator("#shop-dock");
    await expect(shop).toBeVisible();
    await expect(shop.locator(".shop-pack")).toHaveCount(3);
    await expect(shop.locator(".shop-balance")).toContainText("10 Bops");
    await shop.locator(".shop-pack").filter({ hasText: "Tinyrooms Base Pack" }).getByRole("button", { name: "Buy" }).click();
    const confirm = page.locator(".global-dialog");
    await expect(confirm).toBeVisible();
    await confirm.getByRole("button", { name: "Buy", exact: true }).click();
    await expect(page.locator(".pack-reveal")).toBeVisible();
    await expect(page.locator(".pack-reveal-card")).toHaveCount(3);
    await page.locator(".pack-reveal-close").click();
    await expect(page.locator(".pack-reveal")).toHaveCount(0);
    await expect(shop.locator(".shop-balance")).toContainText("0 Bops");
  });

  test("inventory Card Shop button opens the shop dock", async ({ page, runtime }) => {
    await createReadyAccount(page, runtime);
    await openCore(page, "inventory");
    await page.locator("#panel-layer").getByRole("button", { name: "Card Shop", exact: true }).click();
    await expect(page.locator("#panel-layer [role=dialog]")).toHaveCount(0);
    const shop = page.locator("#shop-dock");
    await expect(shop).toBeVisible();
    await expect(shop.locator(".shop-pack")).toHaveCount(3);
  });

  test("selling a card from the inventory credits Bops", async ({ page, runtime }) => {
    await createReadyAccount(page, runtime);
    await openCore(page, "inventory");
    const panel = page.locator("#panel-layer [role=dialog]");
    await panel.getByRole("button", { name: "Smile", exact: true }).click();
    await page.locator("#actions-bar").getByRole("button", { name: /^Sell 1/ }).click();
    await page.locator(".global-dialog").getByRole("button", { name: "Sell", exact: true }).click();
    await expect(page.locator(".coin-motion-layer")).toHaveAttribute("data-last-coins", "1");
    await expect.poll(async () => (await bootstrap(page)).user.bops).toBe(11);
  });

  test("targeting a healing card previews, cancels, and rejects full health", async ({ page, runtime }) => {
    await createReadyAccount(page, runtime);
    await command(page, ".go @way:exit0");
    await expect(page.locator("#look-bar")).toContainText("The Playroom");
    await command(page, ".go @way:exit0");
    await expect(page.locator("#look-bar")).toContainText("Sunflower Foyer");
    await command(page, ".go @way:kitchen");
    await expect(page.locator("#look-bar")).toContainText("The Buttercup Kitchen");
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
    await page.keyboard.press("Escape");
    await expect(page.locator("#actions-bar .targeting-hint")).toHaveCount(0);
    await openCore(page, "inventory");
    await owned.click();
    await page.locator("#actions-bar").getByRole("button", { name: "Use on…", exact: true }).click();
    await page.getByRole("button", { name: "Select sunbeam", exact: true }).click();
    await expect(page.locator("#toast-stack .error").first()).toContainText(/full Health/i);
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

test.describe("milestone 3 journal", () => {
  test.slow();

  test("shows real tasks and round-trips a manual memory", async ({ page, runtime }) => {
    await createReadyAccount(page, runtime);
    await travel(page);
    await command(page, ".go @way:exit0");
    await expect(page.locator("#look-bar")).toContainText("Sunflower Foyer");
    await openCore(page, "journal");
    const journal = page.locator("#panel-layer [role=dialog]");
    await expect(journal).toContainText("A Tour of the Little House");
    await journal.locator('[data-task-id="house-tour"]').click();
    await page.locator("#actions-bar").getByRole("button", { name: "Memories", exact: true }).click();
    await expect(journal.locator(".memory-filter")).toBeVisible();
    await expect(journal.locator(".memory-list")).toContainText("Step through the dollhouse");
    await journal.getByRole("button", { name: "Memories", exact: true }).click();
    await expect(journal.locator(".memory-filter")).toHaveCount(0);
    await page.locator("#chat-input").fill("Browser memory");
    await page.locator("#actions-bar").getByRole("button", { name: "New Memory", exact: true }).click();
    await expect(journal.locator(".memory-list")).toContainText("Browser memory");
    await expect(journal.locator(".memory-entry.manual").first().getByRole("button", { name: "Edit", exact: true })).toBeVisible();
    await expect.poll(async () => journal.locator(".cal-cell.has-memories").count()).toBeGreaterThan(0);
  });
});

test.describe("milestone 2 polish: prop viewer and journal calendar", () => {
  test.slow();

  test("selecting a prop shows a model preview and the details viewer orbits", async ({ page, runtime }) => {
    await createReadyAccount(page, runtime);
    expect(await selectFirstProp(page), "A Hub prop must be selectable").toBe(true);
    const lookCanvas = page.locator("#look-bar canvas.look-preview-3d");
    await expect(lookCanvas).toBeVisible();
    await expect(lookCanvas).toHaveAttribute("data-model-ready", "true", { timeout: 20_000 });
    const selectedModel = await lookCanvas.getAttribute("data-prop-model");
    expect(selectedModel, "The selected prop must publish its model URL").toBeTruthy();
    await page.locator("#actions-bar").getByRole("button", { name: "Inspect", exact: true }).click();
    const canvas = page.locator("#panel-layer canvas.prop-preview-canvas");
    await expect(canvas).toBeVisible();
    await expect(canvas).toHaveAttribute("data-prop-model", selectedModel);
    const box = await canvas.boundingBox();
    await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
    await page.mouse.down();
    await page.mouse.move(box.x + box.width / 2 + 45, box.y + box.height / 2 + 12, { steps: 6 });
    await page.mouse.up();
    await expect(canvas).toBeVisible();
    await page.keyboard.press("Escape");
    await expect(page.locator("#panel-layer canvas.prop-preview-canvas")).toHaveCount(0);
  });

  test("inspecting a card opens a two-panel view with a rotatable 3D card", async ({ page, runtime }) => {
    await createReadyAccount(page, runtime);
    await travel(page);
    await openRoomView(page);
    await page.locator('#panel-layer [data-stack-id][data-scope="room"]').first().click();
    await page.locator("#actions-bar").getByRole("button", { name: "Inspect", exact: true }).click();
    const canvas = page.locator("#detail-layer canvas.card-preview-canvas");
    await expect(canvas).toBeVisible();
    await expect(canvas).toHaveAttribute("data-card-ready", "true", { timeout: 20_000 });
    await expect(canvas).toHaveAttribute("data-card-front", /assets/);
    const box = await canvas.boundingBox();
    await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
    await page.mouse.down();
    await page.mouse.move(box.x + box.width / 2 + 60, box.y + box.height / 2, { steps: 8 });
    await page.mouse.up();
    await expect(canvas).toBeVisible();
    await expect(page.locator("#detail-layer .card-view-info")).toContainText("Quantity");
    await page.keyboard.press("Escape");
    await expect(page.locator("#detail-layer canvas.card-preview-canvas")).toHaveCount(0);
  });

  test("clicking another hand card retargets the open card view", async ({ page, runtime }) => {
    await createReadyAccount(page, runtime);
    await travel(page);
    await openRoomView(page);
    await page.locator('#panel-layer [data-stack-id][data-scope="room"]').first().click();
    await page.locator("#actions-bar").getByRole("button", { name: "Pick up 1", exact: true }).click();
    await page.keyboard.press("Escape");
    await command(page, ".go @way:exit0");
    await expect(page.locator("#look-bar")).toContainText("Sunflower Foyer");
    await command(page, ".go @way:kitchen");
    await expect(page.locator("#look-bar")).toContainText("The Buttercup Kitchen");
    await openRoomView(page);
    await page.locator('#panel-layer [data-stack-id][data-scope="room"]').first().click();
    await page.locator("#actions-bar").getByRole("button", { name: "Pick up 1", exact: true }).click();
    await page.keyboard.press("Escape");
    const hand = page.locator(".equipped-hand [data-stack-id]");
    await expect(hand).toHaveCount(2);
    await hand.first().click();
    await page.locator("#actions-bar").getByRole("button", { name: "Inspect", exact: true }).click();
    const title = page.locator("#detail-layer .card-view-info h2");
    await expect(title).toBeVisible();
    const firstTitle = await title.textContent();
    await hand.nth(1).click();
    await expect(title).not.toHaveText(firstTitle);
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

test.describe("multiplayer peep movement", () => {
  test.slow();

  test("moving between rooms does not raise a moved-to toast", async ({ page, runtime }) => {
    await createReadyAccount(page, runtime);
    await command(page, ".go @way:exit0");
    await expect(page.locator("#look-bar")).toContainText("The Playroom");
    await expect(page.locator("#toast-stack .toast").filter({ hasText: /moved to/i })).toHaveCount(0);
  });

  test("shows move bubbles for leaving and arriving peeps and follows an exit", async ({ page, browser, runtime }) => {
    test.setTimeout(60_000);
    await createReadyAccount(page, runtime, "alice");
    const context = await browser.newContext({ ignoreHTTPSErrors: true, viewport: { width: 1280, height: 800 } });
    try {
      const bobPage = await context.newPage();
      await createReadyAccount(bobPage, runtime, "bob");
      await expect(page.locator("#peeps-panel [data-peep-id]").filter({ hasText: "bob" })).toBeVisible();

      await command(bobPage, ".go @way:exit0");
      await expect(bobPage.locator("#look-bar")).toContainText("The Playroom");

      const departed = page.locator(".bubble.move").filter({ hasText: /bob went/i });
      await expect(departed).toBeVisible();
      await expect(departed).toHaveClass(/actionable/);
      await expect(departed).toContainText(/cross the portal/i);

      await command(bobPage, ".go @way:hub");
      await expect(bobPage.locator("#look-bar")).toContainText("The Hub");

      const arrived = page.locator(".bubble.move").filter({ hasText: /bob came from/i });
      await expect(arrived).toBeVisible();
      await expect(arrived).toContainText("The Playroom");

      await arrived.click();
      await expect(page.locator("#look-bar")).toContainText("The Playroom");
    } finally {
      await context.close();
    }
  });
});

test.describe("milestone 3 crafting", () => {
  test.slow();

  test("crafting activity previews a recipe and requires ingredients", async ({ page, runtime }) => {
    await createReadyAccount(page, runtime);
    await travel(page);
    await command(page, ".go @way:exit0");
    await expect(page.locator("#look-bar")).toContainText("Sunflower Foyer");
    await command(page, ".go @way:kitchen");
    await expect(page.locator("#look-bar")).toContainText("The Buttercup Kitchen");
    await command(page, ".craft @prop:workbench0");
    const activity = page.locator(".activity-window");
    await expect(activity).toBeVisible();
    const frame = page.frameLocator('iframe[src*="crafting"]');
    await expect(frame.locator(".recipe-button")).toHaveCount(1);
    await expect(frame.locator(".recipe-button")).toContainText("Bag it neatly");
    await frame.locator(".recipe-button").click();
    await expect(frame.locator("#detail h2")).toHaveText("Bag it neatly");
    await expect(frame.locator(".ingredient")).toHaveCount(2);
    await expect(frame.locator(".ingredient .empty")).toHaveCount(2);
    await expect(frame.locator("#confirm")).toBeDisabled();
    await page.getByRole("button", { name: "Close activity" }).click();
    await expect(activity).toHaveCount(0);
  });
});

async function findEditorProp(page, panel, expected) {
  const box = await page.locator("#board-canvas").boundingBox();
  // Deselect first so a hit can only be the prop body, never a visible gizmo handle.
  await page.mouse.click(box.x + box.width * 0.95, box.y + box.height * 0.9);
  const candidates = [];
  for (let fy = 0.25; fy <= 0.8; fy += 0.03) {
    for (let fx = 0.38; fx <= 0.85; fx += 0.03) {
      candidates.push([fx, fy, Math.hypot(fx - 0.55, fy - 0.42)]);
    }
  }
  candidates.sort((left, right) => left[2] - right[2]);
  const metaLocator = panel.locator(".editor-meta");
  for (const [fx, fy] of candidates) {
    const x = box.x + box.width * fx;
    const y = box.y + box.height * fy;
    await page.mouse.click(x, y);
    const text = await metaLocator.count() ? await metaLocator.textContent() : "";
    if (text?.includes(expected)) return { x, y };
  }
  throw new Error(`Could not locate prop at ${expected} on the board.`);
}

async function dragProp(page, panel, expected, delta, { touch = false } = {}) {
  for (let attempt = 0; attempt < 3; attempt += 1) {
    const point = await findEditorProp(page, panel, expected);
    const target = { x: point.x + delta.x, y: point.y + delta.y };
    if (touch) {
      await touchDrag(page, point, target);
    } else {
      await page.mouse.move(point.x, point.y);
      await page.mouse.down();
      await page.mouse.move(target.x, target.y, { steps: 8 });
      await page.mouse.up();
    }
    const metaLocator = panel.locator(".editor-meta");
    const text = await metaLocator.count() ? await metaLocator.textContent() : "";
    if (text && !text.includes(expected)) return text;
  }
  throw new Error(`Drag did not move the prop from ${expected}.`);
}

async function touchDrag(page, from, to) {
  const client = await page.context().newCDPSession(page);
  const point = (x, y) => [{ x, y, radiusX: 2, radiusY: 2, force: 1, id: 1 }];
  await client.send("Emulation.setTouchEmulationEnabled", { enabled: true, maxTouchPoints: 1 });
  try {
    await client.send("Input.dispatchTouchEvent", { type: "touchStart", touchPoints: point(from.x, from.y) });
    for (let step = 1; step <= 6; step += 1) {
      await client.send("Input.dispatchTouchEvent", {
        type: "touchMove",
        touchPoints: point(from.x + (to.x - from.x) * step / 6, from.y + (to.y - from.y) * step / 6),
      });
    }
    await client.send("Input.dispatchTouchEvent", { type: "touchEnd", touchPoints: [] });
  } finally {
    await client.send("Emulation.setTouchEmulationEnabled", { enabled: false });
    await client.detach();
  }
}

test.describe("milestone 3 room editing", () => {
  test.slow();
  test.setTimeout(60_000);

  test("admins see the Edit Room action without ownership", async ({ page, runtime }) => {
    await createReadyAccount(page, runtime, "siteadmin");
    const panel = await openEditRoom(page);
    await expect(panel).toContainText("Add a prop");
    // Library tiles are static images, never per-tile WebGL contexts.
    await expect(panel.locator("img.editor-thumb")).toHaveCount(1);
    await expect(panel.locator("canvas.editor-thumb")).toHaveCount(0);
  });

  test("editor keeps the board orbitable on empty space", async ({ page, runtime, isMobile }) => {
    test.skip(Boolean(isMobile), "Pointer orbit check runs on desktop; portrait has the visual capture.");
    await createEditorAccount(page, runtime, "editor");
    await openEditRoom(page);
    const canvas = page.locator("#board-canvas");
    await expect(canvas).toHaveAttribute("data-board-ready", "true", { timeout: 20_000 });
    const before = await canvas.screenshot();
    const box = await canvas.boundingBox();
    await page.mouse.move(box.x + box.width * 0.5, box.y + box.height * 0.12);
    await page.mouse.down();
    await page.mouse.move(box.x + box.width * 0.64, box.y + box.height * 0.18, { steps: 8 });
    await page.mouse.up();
    const after = await canvas.screenshot();
    expect(Buffer.compare(before, after)).not.toBe(0);
  });

  test("environment palette edits mark the draft dirty", async ({ page, runtime, isMobile }) => {
    test.skip(Boolean(isMobile), "Palette input interaction runs on desktop.");
    await createEditorAccount(page, runtime, "editor");
    const panel = await openEditRoom(page);
    const input = panel.locator('[data-edit-palette="0"]');
    const before = await input.inputValue();
    const next = before.toLowerCase() === "#112233" ? "#223344" : "#112233";
    await input.evaluate((node, value) => {
      node.value = value;
      node.dispatchEvent(new Event("change", { bubbles: true }));
    }, next);
    await expect(panel.locator(".editor-status")).toContainText("Unsaved changes");
    await expect(panel.locator('[data-edit-palette="0"]')).toHaveValue(next);
  });

  test("editor adds, transforms, snaps, and undoes a decorative prop", async ({ page, runtime, isMobile }) => {
    test.skip(Boolean(isMobile), "Editor pointer flow is covered on desktop; portrait has a visual capture.");
    await createEditorAccount(page, runtime, "editor");
    const panel = await openEditRoom(page);
    await expect(panel.locator(".editor-library-item")).toHaveCount(1);
    const meta = panel.locator(".editor-meta");

    await panel.locator('[data-edit-add="plant"]').click();
    await expect(meta).toContainText("Position 50, 50");
    await expect(page.locator("#board-canvas")).toHaveAttribute("data-board-ready", "true", { timeout: 20_000 });
    await page.evaluate(() => {
      window.__contextLost = 0;
      document.querySelector("#board-canvas").addEventListener("webglcontextlost", () => { window.__contextLost += 1; });
    });

    const afterDrag = await dragProp(page, panel, "Position 50, 50", { x: 140, y: 70 });
    await expect(meta).not.toContainText("Position 50, 50");
    const position = /Position \d+, \d+/.exec(afterDrag || "")?.[0];

    // Touch drag moves the same prop again.
    const afterTouch = await dragProp(page, panel, position, { x: -70, y: 35 }, { touch: true });
    await expect(meta).not.toHaveText(afterDrag);
    expect(afterTouch).not.toBe(afterDrag);

    // Keyboard nudge with position snapping.
    const beforeNudge = await meta.textContent();
    await page.keyboard.press("ArrowRight");
    await expect(meta).not.toHaveText(beforeNudge);

    await panel.getByRole("button", { name: "Rotate +15°", exact: true }).click();
    await expect(meta).toContainText("Rotation 15°");
    await panel.getByRole("button", { name: "Larger", exact: true }).click();
    await expect(meta).not.toContainText("Scale 1.00");

    const beforeUndo = await meta.textContent();
    await panel.getByRole("button", { name: "Undo", exact: true }).click();
    await expect(meta).not.toHaveText(beforeUndo);

    // Turning snapping off allows fine nudges.
    await panel.locator('[data-edit-snap="position"]').uncheck();
    const beforeFine = await meta.textContent();
    await page.keyboard.press("ArrowRight");
    await expect(meta).not.toHaveText(beforeFine);

    // Dragging must not churn WebGL contexts and evict the room board.
    expect(await page.evaluate(() => window.__contextLost)).toBe(0);
  });

  test("closing the editor with unsaved changes asks for confirmation", async ({ page, runtime }) => {
    await createEditorAccount(page, runtime, "editor");
    const panel = await openEditRoom(page);
    await panel.locator('[data-edit-add="plant"]').click();
    await page.keyboard.press("Escape");
    const dialog = page.locator("#global-modal-layer [role=dialog]");
    await expect(dialog).toContainText("Discard unsaved changes?");
    await dialog.getByRole("button", { name: "Cancel", exact: true }).click();
    await expect(panel).toBeVisible();
  });

  test("saving the editor updates a second client in the room", async ({ browser, page, runtime }) => {
    await createEditorAccount(page, runtime, "editor");
    const panel = await openEditRoom(page);
    await panel.locator('[data-edit-add="plant"]').click();

    const viewerContext = await browser.newContext({ ignoreHTTPSErrors: true, reducedMotion: "reduce" });
    const events = [];
    const viewerPage = await viewerContext.newPage();
    viewerPage.on("websocket", socket => socket.on("framereceived", frame => {
      try {
        const data = JSON.parse(frame.payload);
        if (data.type === "room.event" && data.event?.type === "room.layout.updated") events.push(data.event);
      } catch {
        // Ignore non-JSON frames.
      }
    }));
    try {
      await createReadyAccount(viewerPage, runtime, "viewer");
      await panel.getByRole("button", { name: "Save layout", exact: true }).click();
      await expect(page.locator("#toast-stack")).toContainText("Layout saved.");
      await expect.poll(() => events.length, { timeout: 15_000 }).toBeGreaterThan(0);
      expect(events[0].props.length).toBeGreaterThan(1);
    } finally {
      await viewerContext.close();
    }
  });

  test("editor surfaces a stale revision and can reapply", async ({ page, runtime }) => {
    await createEditorAccount(page, runtime, "editor");
    const panel = await openEditRoom(page);
    await panel.locator('[data-edit-add="plant"]').click();

    const origin = new URL(runtime.baseURL).origin;
    const csrf = await page.evaluate(() => document.cookie.split("; ").find(cookie => cookie.startsWith("tr_csrf="))?.slice("tr_csrf=".length));
    const current = await (await page.request.get(`${runtime.baseURL}/api/rooms/hub/layout`)).json();
    const external = await page.request.post(`${runtime.baseURL}/api/rooms/hub/layout`, {
      data: { base_revision: current.layout.revision, patch: { props: current.layout.props } },
      headers: { Origin: origin, "X-CSRF-Token": csrf },
    });
    expect(external.ok(), await external.text()).toBeTruthy();

    await panel.getByRole("button", { name: "Save layout", exact: true }).click();
    await expect(panel.locator(".editor-conflict")).toBeVisible();
    await panel.getByRole("button", { name: "Reapply my changes", exact: true }).click();
    await expect(page.locator("#toast-stack")).toContainText("Layout saved.");
    await expect(panel.locator(".editor-conflict")).toHaveCount(0);
  });
});

test.describe("bedrooms and doors", () => {
  test.slow();
  test.setTimeout(60_000);

  test("buy, design, and enter a player bedroom from the corridor", async ({ page, runtime }) => {
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
    await openEditRoom(page);
  });
});


test.describe("world editor and card database", () => {
  test.slow();
  test.setTimeout(60_000);

  test("draft, validate, preview, and publish a world", async ({ page, runtime }) => {
    await createEditorAccount(page, runtime, "worldsmith");
    await page.goto(`${runtime.baseURL}/world-editor/`);
    await expect(page.locator("#we-toolbar")).toContainText("World Editor");
    await expect(page.locator("#we-canvas")).toHaveAttribute("data-board-ready", "true", { timeout: 20_000 });

    await page.locator(".room-item", { hasText: "The Hub" }).click();
    const label = page.locator('input[data-room-field="label"]');
    await expect(label).toHaveValue("The Hub");
    await label.fill("Edited Hub");
    await label.blur();
    await expect(page.locator(".dirty-marker")).toContainText("Unsaved changes");

    await page.getByRole("button", { name: "Save Draft", exact: true }).click();
    await expect(page.locator("#we-toast")).toContainText("saved", { timeout: 20_000 });

    await page.getByRole("button", { name: "Validate", exact: true }).click();
    await expect(page.locator("#we-validation")).toContainText("No validation errors");

    await page.getByRole("button", { name: "Preview", exact: true }).click();
    await expect(page.getByRole("button", { name: "Stop preview", exact: true })).toBeVisible();
    await page.getByRole("button", { name: "Stop preview", exact: true }).click();

    await page.getByRole("button", { name: "Publish", exact: true }).click();
    await expect(page.locator("#we-toast")).toContainText("Published revision 1", { timeout: 20_000 });
  });

  test("room canvas reuses the in-game prop editor", async ({ page, runtime }) => {
    await createEditorAccount(page, runtime, "roomsmith");
    await page.goto(`${runtime.baseURL}/world-editor/`);
    await expect(page.locator("#we-canvas")).toHaveAttribute("data-board-ready", "true", { timeout: 20_000 });

    const box = await page.locator("#we-canvas").boundingBox();
    let found = null;
    for (let fy = 0.1; fy <= 0.9 && !found; fy += 0.08) {
      for (let fx = 0.1; fx <= 0.9; fx += 0.08) {
        await page.mouse.click(box.x + box.width * fx, box.y + box.height * fy);
        if (await page.locator("#we-properties .properties-head").filter({ hasText: "Prop ·" }).count()) {
          found = { x: box.x + box.width * fx, y: box.y + box.height * fy };
          break;
        }
      }
    }
    expect(found, "expected a prop to be selectable in the scene").not.toBeNull();

    const xInput = page.locator('input[data-instance-field="pos.0"]');
    await expect(xInput).toBeVisible();
    const before = await xInput.inputValue();
    await page.mouse.move(found.x, found.y);
    await page.mouse.down();
    await page.mouse.move(found.x + 48, found.y + 24, { steps: 6 });
    await page.mouse.up();
    await expect(page.locator(".dirty-marker")).toContainText("Unsaved changes");
    await expect(xInput).not.toHaveValue(before);
  });

  test("card database lists cards, packs, and recipes", async ({ page, runtime }) => {
    await createEditorAccount(page, runtime, "cardcat");
    await page.goto(`${runtime.baseURL}/card-database/`);
    await expect(page.locator(".card-tile").first()).toBeVisible();
    await expect(page.getByRole("heading", { name: "Packs", exact: true })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Recipes", exact: true })).toBeVisible();

    await page.locator("#cdb-search").fill("tasty");
    await expect(page.locator(".card-tile", { hasText: "Tasty Toast" })).toHaveCount(1);
  });
});


test.describe("milestone 3 lazor rush", () => {
  test.slow();

  test("plays a round with the mouse and records a personal best", async ({ page, runtime }) => {
    await createReadyAccount(page, runtime);
    await travel(page);
    await command(page, ".play molly");
    const activity = page.locator(".activity-window");
    await expect(activity).toBeVisible();
    const frame = page.frameLocator('iframe[src*="lazor-rush"]');
    const stage = frame.locator("#stage");
    await expect(stage).toBeVisible();
    await frame.locator("#start").click();
    await expect(frame.locator("#overlay")).toBeHidden();
    const box = await stage.boundingBox();
    await stage.hover({ position: { x: box.width * 0.86, y: box.height * 0.18 } });
    await expect(frame.locator("#overlay-title")).toHaveText("Caught!", { timeout: 20_000 });
    await expect(frame.locator("#personal-best")).not.toHaveText("—");
    await page.getByRole("button", { name: "Close activity" }).click();
    await expect(activity).toHaveCount(0);
  });

  test("keeps the round running while minimized", { tag: "@mobile" }, async ({ page, runtime }) => {
    await createReadyAccount(page, runtime);
    await travel(page);
    await command(page, ".play molly");
    const frame = page.frameLocator('iframe[src*="lazor-rush"]');
    await expect(frame.locator("#start")).toBeVisible();
    await frame.locator("#start").click();
    await expect(frame.locator("#overlay")).toBeHidden();
    await page.getByRole("button", { name: "Minimize activity" }).click();
    await page.waitForTimeout(4000);
    await page.getByRole("button", { name: /Restore activity|Minimize activity/ }).click();
    await expect(frame.locator("#overlay-title")).toHaveText("Caught!", { timeout: 20_000 });
    await page.getByRole("button", { name: "Close activity" }).click();
    await expect(page.locator(".activity-window")).toHaveCount(0);
  });

  test("keeps the round running while covered by another view", async ({ page, runtime }) => {
    await createReadyAccount(page, runtime);
    await travel(page);
    await command(page, ".play molly");
    const frame = page.frameLocator('iframe[src*="lazor-rush"]');
    await expect(frame.locator("#start")).toBeVisible();
    await frame.locator("#start").click();
    await expect(frame.locator("#overlay")).toBeHidden();
    await openCore(page, "journal");
    await page.waitForTimeout(3500);
    await page.keyboard.press("Escape");
    await expect(frame.locator("#overlay-title")).toHaveText("Caught!", { timeout: 20_000 });
    await page.getByRole("button", { name: "Close activity" }).click();
    await expect(page.locator(".activity-window")).toHaveCount(0);
  });

  test("touch drag leads the laser", { tag: "@mobile" }, async ({ page, runtime, isMobile }) => {
    test.skip(!isMobile, "Touch flow is portrait-only.");
    await createReadyAccount(page, runtime);
    await travel(page);
    await command(page, ".play molly");
    const frame = page.frameLocator('iframe[src*="lazor-rush"]');
    await expect(frame.locator("#start")).toBeVisible();
    await frame.locator("#start").click();
    await expect(frame.locator("#overlay")).toBeHidden();
    const stage = frame.locator("#stage");
    const box = await stage.boundingBox();
    await stage.tap({ position: { x: box.width * 0.86, y: box.height * 0.18 } });
    await expect(frame.locator("#overlay-title")).toHaveText("Caught!", { timeout: 20_000 });
    await page.getByRole("button", { name: "Close activity" }).click();
    await expect(page.locator(".activity-window")).toHaveCount(0);
  });
});
