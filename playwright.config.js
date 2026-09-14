import { defineConfig } from "@playwright/test";

const updating = process.argv.some(value => value === "-u" || value.startsWith("--update-snapshots"));
if (updating && process.env.TR_UPDATE_SCREENSHOTS !== "1") {
  throw new Error("Baseline updates require TR_UPDATE_SCREENSHOTS=1 and manual reference review.");
}

export default defineConfig({
  testDir: "./tests/browser",
  timeout: 10_000,
  expect: { timeout: 10_000, toHaveScreenshot: { maxDiffPixels: 100, threshold: 0.15 } },
  fullyParallel: false,
  workers: 1,
  retries: 0,
  forbidOnly: !!process.env.CI,
  outputDir: ".test-results",
  snapshotPathTemplate: "{testDir}/baselines/{projectName}/{testFilePath}/{arg}{ext}",
  updateSnapshots: process.env.TR_UPDATE_SCREENSHOTS === "1" ? "all" : "none",
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
    launchOptions: {
      args: [
        "--use-angle=swiftshader",
        "--enable-unsafe-swiftshader",
        "--num-raster-threads=1",
        "--renderer-process-limit=2",
      ],
    },
  },
  projects: [
    { name: "desktop", use: { viewport: { width: 1280, height: 800 } } },
    { name: "portrait", use: { viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true } },
  ],
});
