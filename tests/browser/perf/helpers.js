// Shared helpers for the browser performance suite.
//
// The suite pushes a synthetic prop set into a room through the real layout
// API rather than generating a separate world, so the measured scene is built
// by exactly the same code path a player would use.

import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname } from "node:path";
import { expect } from "@playwright/test";

export const REPO_ROOT = process.cwd();
export const BASELINE_PATH = `${REPO_ROOT}/tests/perf/baselines/perf-baselines.json`;

/** Merge this process's metrics into the shared perf output file. */
export function record(name, value, { unit = "count", ceiling = null, note = "" } = {}) {
  const target = process.env.TR_PERF_OUT;
  const payload = { value: Math.round(Number(value) * 10000) / 10000, unit, note };
  if (!target) return value;
  let merged = {};
  if (existsSync(target)) {
    try {
      merged = JSON.parse(readFileSync(target, "utf8"));
    } catch {
      merged = {};
    }
  }
  merged[name] = payload;
  mkdirSync(dirname(target), { recursive: true });
  writeFileSync(target, `${JSON.stringify(merged, null, 2)}\n`, "utf8");
  if (ceiling !== null && value > ceiling) {
    throw new Error(`${name}: ${value}${unit} exceeds the ceiling of ${ceiling}${unit}. ${note}`);
  }
  return value;
}

/** Read the board's resource counters. */
export function diagnostics(page) {
  return page.evaluate(() => globalThis.__tinyroomsBoard?.diagnostics() ?? null);
}

export function csrf(page) {
  return page.evaluate(
    () => document.cookie.split("; ").find(c => c.startsWith("tr_csrf="))?.slice("tr_csrf=".length) ?? "",
  );
}

export const ORIGIN_FALLBACK = "https://127.0.0.1";

/**
 * Replace a room's props with *count* generated entries via the layout API.
 *
 * The response includes the patched layout, so a stale revision surfaces as a
 * failed request rather than a silently ignored write.
 */
export async function seedProps(page, runtime, roomId, count, { propId = "plant" } = {}) {
  const token = await csrf(page);
  const base = runtime.baseURL;
  const current = await (await page.request.get(`${base}/api/rooms/${roomId}/layout`)).json();
  const props = Array.from({ length: count }, (_, index) => ({
    id: `perf-prop-${index}`,
    prop_id: propId,
    position: [6 + (index % 20) * 4.4, 8 + Math.floor(index / 20) * 4.4, 0],
    rotation: [0, 0, 0],
    scale: 0.6,
  }));
  const response = await page.request.post(`${base}/api/rooms/${roomId}/layout`, {
    data: { base_revision: current.layout.revision, patch: { props } },
    headers: { Origin: new URL(base).origin, "X-CSRF-Token": token },
  });
  expect(response.ok(), await response.text()).toBeTruthy();
  return props.length;
}

/** Wait until the board has drawn the expected number of props. */
export async function waitForProps(page, expected, timeout = 90_000) {
  await expect
    .poll(async () => (await diagnostics(page))?.props ?? 0, { timeout, intervals: [250] })
    .toBeGreaterThanOrEqual(expected);
}

/** Read the board counters as a plain object, failing if the hook is missing. */
export async function requireDiagnostics(page) {
  const values = await diagnostics(page);
  expect(values, "board diagnostics hook is missing").toBeTruthy();
  return values;
}

/**
 * Count DOM writes and forced reflows for the duration of `action`.
 *
 * The counters are installed by `installDomCounters`, so nothing here depends
 * on app internals.
 */
export async function measureDom(page, action) {
  await page.evaluate(() => globalThis.__domCounts.reset());
  await action();
  return page.evaluate(() => globalThis.__domCounts.snapshot());
}
