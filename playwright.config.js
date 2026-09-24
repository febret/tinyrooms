import { defineConfig } from "@playwright/test";

const updating = process.argv.some(value => value === "-u" || value.startsWith("--update-snapshots"));
if (updating && process.env.TR_UPDATE_SCREENSHOTS !== "1") {
  throw new Error("Baseline updates require TR_UPDATE_SCREENSHOTS=1 and manual reference review.");
}

// Visual capture needs deterministic pixels, so it always renders with SwiftShader
// and stays serial. Functional flows never diff pixels, so they run on the GPU
// (ANGLE picks the native backend and falls back to SwiftShader when no GPU exists),
// which frees the CPU and lets the isolated tests run in parallel.
const visualRun = process.argv.some(value => value.includes("screenshots.spec.js"));
const glMode = visualRun ? "swiftshader" : (process.env.TR_BROWSER_GL || "default");
const softwareGl = glMode === "swiftshader";
const glArgs = softwareGl
  ? ["--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--num-raster-threads=1", "--renderer-process-limit=2"]
  : [`--use-angle=${glMode}`, "--ignore-gpu-blocklist"];
// Software rendering is CPU-bound and does not parallelize well; GPU rendering does.
const defaultWorkers = softwareGl ? 1 : 4;

export default defineConfig({
  testDir: "./tests/browser",
  // Each test boots its own HTTPS server (now loading mods) and account, so a
  // 10s ceiling flakes under parallel workers. Assertions still fail fast.
  timeout: 20_000,
  // maxDiffPixels tolerates small, stable rendering differences in the animated
  // SVG/WebGL shader background. Tighter thresholds (e.g. 100) fail on that
  // noise rather than on real UI changes, so keep this deliberately loose.
  expect: { timeout: 10_000, toHaveScreenshot: { maxDiffPixels: 300, threshold: 0.15 } },
  fullyParallel: !visualRun,
  // Functional flows are isolated per test (own server, users, database), so they
  // run in parallel. Override with TR_BROWSER_WORKERS=<n>.
  workers: visualRun ? 1 : Number(process.env.TR_BROWSER_WORKERS || defaultWorkers),
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
      args: glArgs,
    },
  },
  projects: [
    { name: "desktop", use: { viewport: { width: 1280, height: 800 } } },
    { name: "portrait", use: { viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true } },
  ],
});
