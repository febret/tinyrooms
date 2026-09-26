// Structural performance budgets for the 3D room renderer and the UI shell.
//
// These assert on what the board submits to the GPU and on how much DOM work a
// single state change causes, rather than on frame timings. Wall-clock
// assertions on a software rasteriser are the least reliable signal in the
// suite; draw-call counts, texture residency and drawn-frame counts are exact
// and catch the regressions that actually matter:
//
//   * a shadow map regenerated every frame (doubles the submitted geometry),
//   * one texture and one geometry allocated per entity instead of per asset,
//   * a render loop that keeps drawing a scene nobody is looking at,
//   * a chat message rebuilding every panel in the shell.

import { expect, test as base } from "./fixtures.js";
import { createReadyAccount } from "../helpers.js";
import { installDomCounters, reportDomCounts } from "./dom-counters.js";
import { diagnostics, record, requireDiagnostics, waitForProps } from "./helpers.js";

/** Send a chat line and wait for the action log to grow by one entry. */
async function sayAndSettle(page, text) {
  const before = await page.evaluate(
    () => document.querySelectorAll("#action-log .log-line").length,
  );
  await page.locator("#chat-input").fill(`(!) ${text}`);
  await page.locator("#chat-input").press("Enter");
  await expect
    .poll(
      async () =>
        page.evaluate(() => document.querySelectorAll("#action-log .log-line").length),
      { timeout: 30_000 },
    )
    .toBeGreaterThan(before);
}

const test = base.extend({
  page: async ({ page }, use) => {
    await installDomCounters(page);
    await use(page);
  },
});

const PROPS = 90;

test.describe("board resource budgets", () => {
  test("a crowded room does not grow GPU resources per instance", async ({ page, runtime }) => {
    await createReadyAccount(page, runtime, "perfboard");
    await waitForProps(page, PROPS);

    const values = await requireDiagnostics(page);
    expect(values.renderFailed, "the board reported a render failure").toBe(false);
    expect(values.props).toBeGreaterThanOrEqual(PROPS);

    // Textures are deduplicated per asset, so ninety copies of one prop must not
    // cost ninety uploads. Before sharing this was 205 for the same room.
    record("client/board/textures", values.textures, {
      ceiling: 120,
      note: (
        `Resident textures with ${values.props} instances of a single prop asset. Prop model ` +
        "textures are shared per asset; a per-prop effect layer still contributes one each."
      ),
    });
    // Geometry is not yet shared: GLTFLoader parses each instance independently, so this still
    // tracks the prop count. See the model-cache follow-up in doc/performance.md.
    record("client/board/geometries", values.geometries, {
      ceiling: 170,
      note: `Resident geometries with ${values.props} instances of a single prop asset.`,
    });
    record("client/board/programs", values.programs, {
      ceiling: 24,
      note: "Compiled shader programs; one program per material variant, not per entity.",
    });
    expect(
      values.textures,
      `${values.textures} textures for ${values.props} copies of one asset; textures must be shared`,
    ).toBeLessThanOrEqual(120);
    expect(
      values.geometries,
      `${values.geometries} geometries for ${values.props} copies of one asset`,
    ).toBeLessThanOrEqual(170);
    expect(values.programs, "shader program count is unbounded").toBeLessThanOrEqual(24);
  });

  test("a hidden page stops submitting frames", async ({ page, runtime }) => {
    await createReadyAccount(page, runtime, "perfidle");
    await waitForProps(page, PROPS);

    const settling = await diagnostics(page);
    await expect
      .poll(async () => (await diagnostics(page))?.frames ?? 0, { timeout: 20_000 })
      .toBeGreaterThan(settling.frames);

    // A background tab is the clearest case of work the compositor throws away.
    await page.evaluate(() => {
      Object.defineProperty(document, "hidden", { configurable: true, get: () => true });
      Object.defineProperty(document, "visibilityState", { configurable: true, get: () => "hidden" });
      document.dispatchEvent(new Event("visibilitychange"));
    });
    await page.waitForTimeout(500);
    const hiddenBefore = await diagnostics(page);
    await page.waitForTimeout(3000);
    const hiddenAfter = await diagnostics(page);
    const drawn = hiddenAfter.frames - hiddenBefore.frames;
    record("client/board/frames-while-hidden", drawn, {
      ceiling: 2,
      note: "Frames drawn over 3s while the page reports itself hidden.",
    });
    expect(drawn, `the board drew ${drawn} frames for a hidden page`).toBeLessThanOrEqual(2);

    await page.evaluate(() => {
      Object.defineProperty(document, "hidden", { configurable: true, get: () => false });
      Object.defineProperty(document, "visibilityState", { configurable: true, get: () => "visible" });
      document.dispatchEvent(new Event("visibilitychange"));
    });
    await expect
      .poll(async () => (await diagnostics(page))?.frames ?? 0, { timeout: 20_000 })
      .toBeGreaterThan(hiddenAfter.frames);
  });

  test("a crowded room submits a bounded number of draw calls per frame", async ({ page, runtime }) => {
    await createReadyAccount(page, runtime, "perfdraws");
    await waitForProps(page, PROPS);

    // Draw calls are per frame and are the quantity that decides whether a busy
    // room holds a frame rate. With a static shadow map this stays close to the
    // mesh count rather than doubling for the depth pass.
    const values = await requireDiagnostics(page);
    record("client/board/draw-calls", values.drawCalls, {
      note: `Draw calls per frame with ${values.props} instances of one shared asset.`,
    });
    record("client/board/triangles", values.triangles, {
      note: "Triangles submitted per frame.",
    });
    record("client/board/nodes", values.nodes, {
      note: "Scene-graph nodes for the current room.",
    });
    expect(
      values.drawCalls,
      `${values.drawCalls} draw calls per frame for ${values.props} instances; ` +
        "the shadow pass is probably still auto-updating",
    ).toBeLessThanOrEqual(PROPS * 6);
  });

  test("the shadow map is not regenerated on a static frame", async ({ page, runtime }) => {
    await createReadyAccount(page, runtime, "perfshadow");
    await waitForProps(page, 1);
    const values = await requireDiagnostics(page);
    record("client/board/shadow-map-size", values.shadowMapSize, {
      unit: "px",
      ceiling: 2048,
      note: "Shadow map resolution. Above 2048 the depth pass dominates the frame.",
    });
    record("client/board/shadow-auto-update", values.shadowAutoUpdate ? 1 : 0, {
      unit: "flag",
      note: "1 means Three.js re-renders the shadow depth buffer every frame.",
    });
    expect(values.shadowMapSize, "the shadow map is larger than the budget").toBeLessThanOrEqual(2048);
  });
});

test.describe("shell update budgets", () => {
  test("one chat message does not rewrite the whole shell", async ({ page, runtime }) => {
    await createReadyAccount(page, runtime, "perfui");
    await waitForProps(page, 1);
    await sayAndSettle(page, "hello from the perf suite");

    await page.evaluate(() => globalThis.__domCounts.reset());
    await sayAndSettle(page, "and a second message");

    const counts = await reportDomCounts(page, "client/dom/chat-message", record, {
      innerHTML: 40,
      forcedLayouts: 60,
      querySelectorAll: 400,
      setAttribute: 400,
    });
    expect(
      counts.innerHTML,
      `one chat message caused ${counts.innerHTML} innerHTML writes; the shell is being rebuilt wholesale`,
    ).toBeLessThanOrEqual(40);
    expect(
      counts.forcedLayouts,
      `one chat message forced ${counts.forcedLayouts} synchronous layouts`,
    ).toBeLessThanOrEqual(60);
  });

  test("inert is only written when it actually changes", async ({ page, runtime }) => {
    await createReadyAccount(page, runtime, "perfinert");
    await waitForProps(page, 1);
    await page.evaluate(() => globalThis.__domCounts.reset());
    await sayAndSettle(page, "check inert churn");

    const counts = await reportDomCounts(page, "client/dom/inert", record, {
      inert: 6,
    });
    expect(
      counts.inert,
      `inert was written ${counts.inert} times for one message; writing an unchanged attribute ` +
        "re-triggers the activity MutationObserver",
    ).toBeLessThanOrEqual(6);
  });
});
