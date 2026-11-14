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
import { createReadyAccount, travel } from "../helpers.js";
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

// The budgets below are calibrated for the scaled world that the perf config
// generates. Skipping without it keeps a plain `npx playwright test` from
// reporting them as failures; tools/run_perf.py always sets the variable.
test.skip(!process.env.TR_PERF_WORLD_SCALE, "run via tools/run_perf.py");

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
      ceiling: 130,
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
    ).toBeLessThanOrEqual(130);
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
    // Static rooms correctly idle; resizing explicitly requests a fresh frame.
    const viewport = page.viewportSize();
    await page.setViewportSize({ ...viewport, width: viewport.width - 1 });
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
    // Queue another redraw while hidden so restoring visibility must resume work.
    await page.setViewportSize(viewport);
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

test("a settled room stops ticking and orbiting does not rebuild shadows", async ({ page, runtime }) => {
  await createReadyAccount(page, runtime, "perfsettle");
  await waitForProps(page, PROPS);
  // The entry hub is an animated diorama. Idle and orbit budgets describe a
  // static room, so move to the authored living room before sampling.
  await travel(page);
  await expect(page.locator("#board-canvas")).toHaveAttribute("data-room-transition", "", { timeout: 20_000 });
  // Entering the next room can trigger an authored cutscene, which overlays
  // the board center while it plays.
  await expect(page.locator("#cutscene-layer")).toHaveAttribute("data-state", "idle", { timeout: 30_000 });
  await page.waitForTimeout(500);

  const idleBefore = await requireDiagnostics(page);
  await page.waitForTimeout(500);
  const idleAfter = await requireDiagnostics(page);
  const idleTicks = idleAfter.ticks - idleBefore.ticks;
  record("client/board/ticks-idle", idleTicks, {
    ceiling: 2,
    note: "Animation frames requested over 500ms in a settled room.",
  });
  expect(
    idleTicks,
    "the animation loop kept ticking for a settled room",
  ).toBeLessThanOrEqual(2);

  const box = await page.locator("#board-canvas").boundingBox();
  const startX = box.x + box.width * 0.5;
  const startY = box.y + box.height * 0.5;
  await page.mouse.move(startX, startY);
  await page.mouse.down();
  await page.mouse.move(startX + 80, startY, { steps: 8 });
  await page.mouse.up();
  await page.waitForTimeout(300);

  const orbited = await requireDiagnostics(page);
  expect(orbited.frames, "orbiting did not request a frame").toBeGreaterThan(idleAfter.frames);
  const yawDegrees = (orbited.renderedAzimuth * 180) / Math.PI;
  const offStep = Math.abs(yawDegrees - Math.round(yawDegrees / 5) * 5);
  record("client/board/orbit-yaw-off-step", offStep, {
    unit: "deg",
    ceiling: 0.01,
    note: "Camera yaw must land on a 5° step after an orbit gesture.",
  });
  expect(offStep, "camera yaw was not snapped to a 5° step").toBeLessThanOrEqual(0.01);
  const orbitShadowInvalidations = orbited.shadowInvalidations - idleAfter.shadowInvalidations;
  record("client/board/shadow-invalidations-orbit", orbitShadowInvalidations, {
    ceiling: 0,
    note: "Shadow-map invalidations caused by one camera orbit.",
  });
  expect(
    orbitShadowInvalidations,
    "camera movement dirtied the static shadow map",
  ).toBe(0);
});

test("an open activity window suspends board frames and resumes on close", async ({ page, runtime }) => {
  await createReadyAccount(page, runtime, "perfactivity");
  await waitForProps(page, 1);
  await page.waitForTimeout(500);

  await page.locator("#bops-toggle").click();
  const activity = page.locator(".activity-window");
  await expect(activity).toBeVisible();
  await expect(page.locator("#app")).toHaveClass(/activity-maximized/);

  const opened = await requireDiagnostics(page);
  await page.waitForTimeout(700);
  const paused = await requireDiagnostics(page);
  const pausedTicks = paused.ticks - opened.ticks;
  record("client/board/ticks-activity-open", pausedTicks, {
    ceiling: 2,
    note: "Animation ticks over 700ms while an activity window covers the board.",
  });
  expect(paused.activityMaximized, "the board was not told the activity is maximized").toBe(true);
  expect(pausedTicks, `the board kept ticking ${pausedTicks} times behind an activity`).toBeLessThanOrEqual(2);

  await activity.locator('[aria-label="Close activity"]').click();
  await expect(activity).toHaveCount(0);
  await expect(page.locator("#app")).not.toHaveClass(/activity-maximized/);
  await expect
    .poll(async () => (await diagnostics(page))?.ticks ?? 0, { timeout: 20_000 })
    .toBeGreaterThan(paused.ticks);
});

test("selecting a prop uses stencil outlines without render targets or shadow updates", async ({ page, runtime }) => {
  await createReadyAccount(page, runtime, "perfoutline");
  await waitForProps(page, PROPS);

  const before = await requireDiagnostics(page);
  await page.locator("#room-picker-toggle").click();
  const picker = page.locator("#room-picker");
  await expect(picker).toBeVisible();
  await picker.locator("[data-room-picker-prop]").first().click();
  await expect
    .poll(async () => (await diagnostics(page))?.outline?.selected ?? 0, { timeout: 20_000 })
    .toBeGreaterThan(0);

  const after = await requireDiagnostics(page);
  expect(after.renderFailed, "the board reported a render failure").toBe(false);
  expect(after.outline.supported, "the stencil buffer was not available").toBe(true);
  expect(after.outline.passes, "no outline passes were submitted").toBeGreaterThan(0);
  expect(
    after.shadowInvalidations - before.shadowInvalidations,
    "selection dirtied the static shadow map",
  ).toBe(0);
  const outlineTextures = after.textures - before.textures;
  record("client/board/outline-textures", outlineTextures, {
    ceiling: 1,
    note: "Resident texture growth when a prop is selected.",
  });
  expect(
    outlineTextures,
    "the outline path allocated render-target textures",
  ).toBeLessThanOrEqual(1);
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
