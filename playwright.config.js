import { defineConfig } from "@playwright/test";

// ANGLE picks the native backend and falls back to SwiftShader when no GPU exists.
const glMode = process.env.TR_BROWSER_GL || "default";
const softwareGl = glMode === "swiftshader";
const glArgs = softwareGl
  ? ["--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--num-raster-threads=1", "--renderer-process-limit=2"]
  : [`--use-angle=${glMode}`, "--ignore-gpu-blocklist"];
// Fake media lets audio chat tests acquire a synthetic microphone without a
// physical device or a permission prompt.
const mediaArgs = [
  "--use-fake-device-for-media-stream",
  "--use-fake-ui-for-media-stream",
];
// Software rendering is CPU-bound and does not parallelize well; GPU rendering does.
const defaultWorkers = softwareGl ? 1 : 4;

export default defineConfig({
  testDir: "./tests/browser",
  // Each test boots its own HTTPS server (now loading mods) and account, so a
  // 10s ceiling flakes under parallel workers. Assertions still fail fast.
  timeout: 20_000,
  expect: { timeout: 10_000 },
  fullyParallel: true,
  // Functional flows are isolated per test (own server, users, database), so they
  // run in parallel. Override with TR_BROWSER_WORKERS=<n>.
  workers: Number(process.env.TR_BROWSER_WORKERS || defaultWorkers),
  // Each test boots its own server under parallel load, so a rare timing flake is
  // expected; one retry keeps the suite trustworthy without hiding real failures
  // (which fail both attempts).
  retries: 1,
  forbidOnly: !!process.env.CI,
  outputDir: ".test-results",
  reporter: [["list"], ["html", { open: "never", outputFolder: ".playwright-report" }]],
  use: {
    actionTimeout: 10_000,
    browserName: "chromium",
    ...(process.env.TR_BROWSER_CHANNEL ? { channel: process.env.TR_BROWSER_CHANNEL } : {}),
    ignoreHTTPSErrors: true,
    locale: "en-US",
    timezoneId: "UTC",
    reducedMotion: "reduce",
    colorScheme: "dark",
    deviceScaleFactor: 1,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    permissions: ["microphone"],
    launchOptions: {
      args: [...glArgs, ...mediaArgs],
    },
  },
  projects: [
    {
      name: "desktop",
      // Cutscene playback needs motion, so its spec only runs in desktop-motion.
      testIgnore: /cutscenes\.spec\.js/,
      use: { viewport: { width: 1280, height: 800 } },
    },
    // Cutscenes are disabled outright under reduced motion, so the suite's
    // default `reduce` setting can never exercise one. This project opts back
    // in for cutscene specs only; every other project keeps reduced motion.
    {
      name: "desktop-motion",
      testMatch: /cutscenes\.spec\.js/,
      use: { viewport: { width: 1280, height: 800 }, reducedMotion: "no-preference" },
    },
  ],
});
