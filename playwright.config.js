import { defineConfig } from "@playwright/test";

const updating = process.argv.some(value => value === "-u" || value.startsWith("--update-snapshots"));
if (updating && process.env.TR_UPDATE_SCREENSHOTS !== "1") {
  throw new Error("Baseline updates require TR_UPDATE_SCREENSHOTS=1 and manual reference review.");
}

// Visual capture stays serial so SwiftShader rendering is deterministic. Functional
// flows are isolated per test (own server, users, database) and run in parallel.
const visualRun = process.argv.some(value => value.includes("screenshots.spec.js"));

export default defineConfig({
  testDir: "./tests/browser",
  timeout: 10_000,
  // maxDiffPixels tolerates small, stable rendering differences in the animated
  // SVG/WebGL shader background. Tighter thresholds (e.g. 100) fail on that
  // noise rather than on real UI changes, so keep this deliberately loose.
  expect: { timeout: 10_000, toHaveScreenshot: { maxDiffPixels: 300, threshold: 0.15 } },
  fullyParallel: !visualRun,
  // Functional flows are isolated per test, so CI can run them in parallel. Local
  // developer machines are often GPU/CPU constrained; serial is faster there.
  // Override with TR_BROWSER_WORKERS=<n>.
  workers: visualRun ? 1 : Number(process.env.TR_BROWSER_WORKERS || (process.env.CI ? 4 : 1)),
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
        "--use-angle=d3d11",
        "--ignore-gpu-blocklist",
      ],
    },
  },
  projects: [
    { name: "desktop", use: { viewport: { width: 1280, height: 800 } } },
    { name: "portrait", use: { viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true } },
  ],
});
