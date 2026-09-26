import { defineConfig } from "@playwright/test";

// The performance suite renders a deliberately crowded room and asserts on GPU
// resource counts and drawn frames. Those budgets are deterministic, but the
// harness is still serial and software-rendered: it measures structure, not
// speed, and correctness under parallel load is not worth the flake risk.
//
// The disposable server is told to generate a scaled world instead of copying
// the authored one. Workers are forked from this process, so setting the
// variable here reaches every browser test that boots a runtime.
process.env.TR_PERF_WORLD_SCALE = "props_per_room=90,peeps_per_room=8,cards_per_room=10,rooms=3,aura_rooms=1";

export const PERF_PROPS = 90;
export default defineConfig({
  testDir: "./tests/browser/perf",
  timeout: 180_000,
  expect: { timeout: 30_000 },
  fullyParallel: false,
  workers: 1,
  retries: 0,
  forbidOnly: !!process.env.CI,
  outputDir: ".test-results-perf",
  reporter: [["list"]],
  use: {
    actionTimeout: 30_000,
    browserName: "chromium",
    ...(process.env.TR_BROWSER_CHANNEL ? { channel: process.env.TR_BROWSER_CHANNEL } : {}),
    ignoreHTTPSErrors: true,
    locale: "en-US",
    timezoneId: "UTC",
    colorScheme: "dark",
    deviceScaleFactor: 1,
    trace: "retain-on-failure",
    permissions: ["microphone"],
    launchOptions: {
      args: [
        // SwiftShader keeps draw-call and geometry counts independent of the
        // host GPU. Frame timings are never asserted on.
        "--use-angle=swiftshader",
        "--enable-unsafe-swiftshader",
        "--num-raster-threads=1",
        "--renderer-process-limit=2",
        "--use-fake-device-for-media-stream",
        "--use-fake-ui-for-media-stream",
      ],
    },
  },
  projects: [{ name: "desktop", use: { viewport: { width: 1280, height: 800 } } }],
});
