import { test as base, expect } from "@playwright/test";
import { spawn } from "node:child_process";
import { mkdir, mkdtemp, rm } from "node:fs/promises";
import { existsSync } from "node:fs";
import path from "node:path";

export { expect };

export function trackBrowserErrors(context, errors) {
  const track = page => page.on("pageerror", error => errors.push(error.stack || error.message));
  context.on("page", track);
  context.pages().forEach(track);
  context.on("response", response => {
    if (response.status() >= 400 && /^\/(?:app|assets|activities)\//.test(new URL(response.url()).pathname)) {
      errors.push(`Static asset HTTP ${response.status()}: ${response.url()}`);
    }
  });
}

async function limitAnimationFrameRate(context) {
  await context.addInitScript(() => {
    const nativeRequestAnimationFrame = globalThis.requestAnimationFrame.bind(globalThis);
    let lastFrame = Number.NEGATIVE_INFINITY;
    globalThis.requestAnimationFrame = callback => nativeRequestAnimationFrame(timestamp => {
      if (timestamp - lastFrame >= 200) {
        lastFrame = timestamp;
        callback(timestamp);
      } else {
        globalThis.requestAnimationFrame(callback);
      }
    });
  });
}

export const test = base.extend({
  runtime: async ({ playwright }, use, testInfo) => {
    const root = process.cwd();
    const runtimeRoot = path.join(root, ".browser-runtime");
    await mkdir(runtimeRoot, { recursive: true });
    const directory = await mkdtemp(path.join(runtimeRoot, "run-"));
    const localPython = path.join(root, ".venv", "Scripts", "python.exe");
    const python = process.env.TR_TEST_PYTHON || (existsSync(localPython) ? localPython : "python");
    const child = spawn(python, ["-u", path.join(root, "tools", "browser_test_runtime.py"), "--directory", directory], {
      cwd: root, stdio: ["pipe", "pipe", "pipe"], windowsHide: true,
      env: { ...process.env, PYTHONUTF8: "1", TZ: "UTC" },
    });
    let output = "";
    let spawnError;
    child.on("error", error => { spawnError = error; });
    child.stdout.on("data", chunk => { output += chunk; });
    child.stderr.on("data", chunk => { output += chunk; });
    const stopped = new Promise(resolve => child.once("close", resolve));
    let request;
    try {
      await expect.poll(() => {
        if (spawnError) throw spawnError;
        if (child.exitCode !== null) throw new Error(`Test runtime exited: ${output}`);
        return output.match(/\{"baseURL":\s*"([^"]+)"\}/)?.[1] || "";
      }, { timeout: 25_000, message: "Owned HTTPS runtime must announce its ephemeral port" }).not.toBe("");
      const baseURL = output.match(/\{"baseURL":\s*"([^"]+)"\}/)[1];
      request = await playwright.request.newContext({ baseURL, ignoreHTTPSErrors: true });
      await expect.poll(async () => {
        const response = await request.get("/api/session");
        return response.status();
      }).toBe(200);
      await use({ baseURL, invitation: "browser-test-invitation" });
    } finally {
      await request?.dispose();
      child.stdin.end();
      const timer = setTimeout(() => child.kill(), 5_000);
      await stopped;
      clearTimeout(timer);
      await testInfo.attach("isolated-server.log", { body: output, contentType: "text/plain" });
      await rm(directory, { recursive: true, force: true, maxRetries: 5, retryDelay: 200 });
    }
  },
  baseURL: async ({ runtime }, use) => use(runtime.baseURL),
  pageErrors: [async ({ context }, use) => {
    const errors = [];
    await limitAnimationFrameRate(context);
    trackBrowserErrors(context, errors);
    await use(errors);
    expect(errors, "No uncaught page/iframe exceptions or failed static assets").toEqual([]);
  }, { auto: true }],
});
