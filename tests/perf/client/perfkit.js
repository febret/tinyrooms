// Shared measurement plumbing for the client performance benchmarks.
//
// Mirrors `tests/perf/perfkit.py` so all three tiers report through the same
// JSON shape and `tools/perf_report.py` can compare them together.

import { writeFileSync, mkdirSync, readFileSync, existsSync } from "node:fs";
import { dirname } from "node:path";
import { fileURLToPath } from "node:url";

export const REPO_ROOT = fileURLToPath(new URL("../../..", import.meta.url));

const records = new Map();

/** Record a metric, failing loudly when it breaches an absolute ceiling. */
export function record(name, value, { unit = "ms", ceiling = null, lowerIsBetter = true, note = "" } = {}) {
  records.set(name, {
    value: Math.round(Number(value) * 10000) / 10000,
    unit,
    lower_is_better: lowerIsBetter,
    note,
  });
  if (ceiling === null) return value;
  const breach = lowerIsBetter ? value > ceiling : value < ceiling;
  if (breach) {
    const relation = lowerIsBetter ? "ceiling" : "floor";
    throw new Error(
      `${name}: ${value}${unit} breaches the absolute ${relation} of ${ceiling}${unit}. ${note}`,
    );
  }
  return value;
}

export function flush() {
  const target = process.env.TR_PERF_OUT;
  if (!target) return;
  let merged = {};
  if (existsSync(target)) {
    try {
      merged = JSON.parse(readFileSync(target, "utf8"));
    } catch {
      merged = {};
    }
  }
  for (const [name, payload] of records) merged[name] = payload;
  mkdirSync(dirname(target), { recursive: true });
  writeFileSync(target, `${JSON.stringify(merged, null, 2)}\n`, "utf8");
}

process.on("exit", flush);

/**
 * Time `fn` and return the median run in milliseconds.
 *
 * The median rather than the mean, so a single GC pause or a stray timer does
 * not decide the result.
 */
export function medianMs(fn, { iterations = 30, warmup = 5 } = {}) {
  for (let index = 0; index < warmup; index += 1) fn();
  const samples = [];
  for (let index = 0; index < iterations; index += 1) {
    const started = performance.now();
    fn();
    samples.push(performance.now() - started);
  }
  samples.sort((a, b) => a - b);
  return samples[Math.floor(samples.length / 2)];
}

/**
 * Assert that scaling the workload by `factor` costs at most `maxFactor` times
 * more. A linear pass tracks the factor; a quadratic pass squares it.
 *
 * The ratio is only recorded when the larger sample is big enough to time
 * reliably. Below that, a ratio of two sub-millisecond medians swings by 50%
 * between runs on identical code, which would make the baseline report cry
 * wolf. The assertion still runs either way -- only the bookkeeping is skipped.
 */
const MIN_TRACKABLE_MS = 0.5;

export function assertScales(assert, name, small, large, { factor, maxFactor, smallN, largeN }) {
  const growth = (large + 0.02) / (small + 0.02);
  const allowed = factor * maxFactor;
  if (growth > allowed) {
    assert.fail(
      `${name}: ${largeN} units cost ${growth.toFixed(2)}x the ${smallN}-unit case ` +
        `(${small.toFixed(3)} -> ${large.toFixed(3)}), over the ${allowed.toFixed(2)}x allowed ` +
        `for a ${factor}x workload increase. This usually means an inner loop scans the whole ` +
        `collection per item.`,
    );
  }
  if (large >= MIN_TRACKABLE_MS) {
    record(`perf/${name}/growth`, growth, { unit: "ratio" });
  } else {
    console.log(
      `  (skipping baseline for ${name}/growth: ${large.toFixed(3)}ms is below the ` +
        `${MIN_TRACKABLE_MS}ms tracking floor)`,
    );
  }
}
