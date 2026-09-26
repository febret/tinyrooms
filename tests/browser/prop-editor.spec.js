import { test, expect } from "./fixtures.js";
import { createReadyAccount, findPropByLabel } from "./helpers.js";

test.describe("prop editor", () => {
  // These flows boot the game, open the editor, publish, reload, and re-load.
  test.describe.configure({ timeout: 60_000 });

  test("deep link preselects a prop", async ({ page, runtime }) => {
    await createReadyAccount(page, runtime, "siteadmin");
    await page.goto(`${runtime.baseURL}/prop-editor/?prop=portal`);
    await expect(page.locator('[data-pe-prop="label"]')).toHaveValue("A Glowing Portal");
    await expect(page.locator(".pe-preview-info")).toContainText("A Glowing Portal");
  });

  test("admin opens the prop editor from a selected prop", async ({ page, runtime }) => {
    await createReadyAccount(page, runtime, "siteadmin");
    await findPropByLabel(page, "A Glowing Portal");
    const edit = page.locator("#actions-bar").getByRole("button", { name: "Edit Prop", exact: true });
    await expect(edit).toBeVisible();

    const [popup] = await Promise.all([
      page.context().waitForEvent("page"),
      edit.click(),
    ]);
    await popup.waitForLoadState();
    await expect(popup).toHaveURL(/\/prop-editor\/\?prop=portal/);
    await expect(popup.locator('[data-pe-prop="label"]')).toHaveValue("A Glowing Portal");
  });

  test("non-admin players do not see Edit Prop", async ({ page, runtime }) => {
    await createReadyAccount(page, runtime, "player");
    await findPropByLabel(page, "A Glowing Portal");
    await expect(page.locator("#actions-bar").getByRole("button", { name: "Inspect", exact: true })).toBeVisible();
    await expect(page.locator("#actions-bar").getByRole("button", { name: "Edit Prop", exact: true })).toHaveCount(0);
  });

  test("admin edits a world prop and reloads the world", async ({ page, runtime }) => {
    await createReadyAccount(page, runtime, "siteadmin");
    await page.goto(`${runtime.baseURL}/prop-editor/`);

    await expect(page.locator(".pe-shell")).toBeVisible();
    await expect(page.locator(".editor-library-item").first()).toBeVisible();

    await page.locator('.editor-library-item[data-edit-add="plant"]').click();
    await expect(page.locator(".pe-preview-info")).toContainText("Little Monstera");

    const label = page.locator('[data-pe-prop="label"]');
    await expect(label).toHaveValue("Little Monstera");
    await label.fill("Browser Monstera");
    await label.blur();

    await page.getByRole("button", { name: "Save prop" }).click();
    await expect(page.locator("#pe-toast")).toContainText("Prop saved");
    await expect(page.getByRole("button", { name: "Save prop" })).toBeDisabled();

    await page.getByRole("button", { name: "Reload world" }).click();
    await expect(page.locator("#pe-toast")).toContainText("World reloaded");

    await page.reload();
    await page.locator('.editor-library-item[data-edit-add="plant"]').click();
    await expect(page.locator('[data-pe-prop="label"]')).toHaveValue("Browser Monstera");
  });

  test("preview fills the stage and renders the active effect set", async ({ page, runtime }) => {
    await createReadyAccount(page, runtime, "siteadmin");
    await page.goto(`${runtime.baseURL}/prop-editor/?prop=portal`);

    const canvas = page.locator("#pe-preview-canvas");
    await expect(canvas).toHaveAttribute("data-model-ready", "true", { timeout: 30_000 });
    // Portal's active set is `idle` (smoke particle + ember-glow material).
    await expect(canvas).toHaveAttribute("data-fx-count", "2", { timeout: 30_000 });

    const stageBox = await page.locator(".pe-stage").boundingBox();
    const canvasBox = await canvas.boundingBox();
    expect(Math.abs(canvasBox.width - stageBox.width)).toBeLessThanOrEqual(2);
    expect(Math.abs(canvasBox.height - stageBox.height)).toBeLessThanOrEqual(2);
  });

  test("admin edits an effect layer stack", async ({ page, runtime }) => {
    await createReadyAccount(page, runtime, "siteadmin");
    await page.goto(`${runtime.baseURL}/prop-editor/`);

    await page.getByRole("button", { name: "Effects", exact: true }).click();
    await page.locator("[data-pe-effect-select]").selectOption("smoke");

    const label = page.locator('[data-pe-effect="label"]');
    await expect(label).toHaveValue("Smoke");
    await label.fill("Browser Smoke");
    await label.blur();
    await page.locator('[data-pe-effect="layers.0.rate"]').fill("11");
    await page.locator('[data-pe-effect="layers.0.rate"]').blur();

    await page.getByRole("button", { name: "Save effect" }).click();
    await expect(page.locator("#pe-toast")).toContainText("Effect saved");
  });

  test("non-admin accounts are denied", async ({ page, runtime }) => {
    await createReadyAccount(page, runtime, "player");
    const response = await page.goto(`${runtime.baseURL}/prop-editor/`);
    expect(response.status()).toBe(403);
    await expect(page.locator("body")).toContainText("permission");
  });
});
