// A performance-suite fixture built on the shared runtime, minus the rAF clamp.
//
// The functional fixture throttles `requestAnimationFrame` to 5 fps so that
// visual snapshots are deterministic. The frame-counting assertions here need
// the real loop, so the clamp is replaced while everything else, including the
// per-test HTTPS server, is reused unchanged.

import { test as base, expect } from "../fixtures.js";

export const test = base.extend({
  pageErrors: async ({ context }, use) => {
    // Re-declare to opt out of the auto fixture that installs the rAF clamp.
    // Error tracking is still valuable, so the listeners stay.
    const errors = [];
    const track = page => page.on("pageerror", error => errors.push(error.stack || error.message));
    context.on("page", track);
    context.pages().forEach(track);
    context.on("response", response => {
      if (response.status() >= 400 && /^\/(?:app|assets|activities)\//.test(new URL(response.url()).pathname)) {
        errors.push(`Static asset HTTP ${response.status()}: ${response.url()}`);
      }
    });
    await use(errors);
    expect(errors, "No uncaught page exceptions or failed static assets").toEqual([]);
  },
});

export { expect };
