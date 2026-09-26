// Counts DOM writes and forced synchronous layouts caused by application code.
//
// The performance suite cares that a state change does not thrash the DOM, not
// how long anything takes. Counting is fully deterministic, so these budgets
// hold on any machine.
//
// Only accesses attributed to a frame in `/app/js/` are counted. Chromium reads
// `scrollTop` and similar from its own internals while doing scroll anchoring
// and intersection work, and the test harness does it too while satisfying
// actionability checks; counting those would measure the browser and Playwright
// rather than the app. `new Error().stack` is expensive, which is why this
// instrumentation is only installed by the performance suite.

const APP_FRAME = /\/app\/js\/[^\s)]+/;

export async function installDomCounters(page) {
  await page.addInitScript(() => {
    const counts = {
      innerHTML: 0,
      setAttribute: 0,
      classList: 0,
      textContent: 0,
      inert: 0,
      querySelectorAll: 0,
      querySelector: 0,
      getBoundingClientRect: 0,
      offsetWidth: 0,
      offsetHeight: 0,
      clientWidth: 0,
      clientHeight: 0,
      scrollTop: 0,
      insertAdjacentHTML: 0,
      appendChild: 0,
    };
    const sites = {};
    let attribution = false;

    function appSite() {
      const stack = new Error().stack || "";
      for (const line of stack.split("\n").slice(1)) {
        if (line.includes("/app/js/")) {
          const file = line.split("/app/js/")[1].split(")")[0];
          const lineNumber = (line.match(/:(\d+):/) || [])[1];
          return `${file}:${lineNumber || "?"}`;
        }
      }
      return null;
    }

    /**
     * Record an access, but only when application code caused it.
     *
     * Chromium reads `scrollTop` and friends from its own internals during
     * scroll anchoring and intersection work, and the test harness does the same
     * while satisfying actionability checks. Counting those would measure the
     * browser and Playwright instead of the app, so an access with no `/app/js/`
     * frame in its stack is ignored.
     */
    function count(key) {
      if (!attribution) return;
      const site = appSite();
      if (!site) return;
      counts[key] += 1;
      sites[site] = (sites[site] || 0) + 1;
    }

    const innerHTMLDescriptor = Object.getOwnPropertyDescriptor(Element.prototype, "innerHTML");
    Object.defineProperty(Element.prototype, "innerHTML", {
      configurable: true,
      get() {
        return innerHTMLDescriptor.get.call(this);
      },
      set(value) {
        count("innerHTML");
        innerHTMLDescriptor.set.call(this, value);
      },
    });

    const setAttribute = Element.prototype.setAttribute;
    Element.prototype.setAttribute = function (name, value) {
      if (name === "inert") count("inert");
      else count("setAttribute");
      return setAttribute.call(this, name, value);
    };

    const classListToggle = DOMTokenList.prototype.toggle;
    DOMTokenList.prototype.toggle = function (...args) {
      count("classList");
      return classListToggle.apply(this, args);
    };

    const textNode = Object.getOwnPropertyDescriptor(Node.prototype, "textContent");
    Object.defineProperty(Node.prototype, "textContent", {
      configurable: true,
      get() {
        return textNode.get.call(this);
      },
      set(value) {
        if (value !== this.textContent) count("textContent");
        textNode.set.call(this, value);
      },
    });

    const insertAdjacentHTML = Element.prototype.insertAdjacentHTML;
    Element.prototype.insertAdjacentHTML = function (...args) {
      count("insertAdjacentHTML");
      return insertAdjacentHTML.apply(this, args);
    };

    const appendChild = Node.prototype.appendChild;
    Node.prototype.appendChild = function (...args) {
      count("appendChild");
      return appendChild.apply(this, args);
    };

    for (const [name, method] of [
      ["querySelectorAll", "querySelectorAll"],
      ["querySelector", "querySelector"],
    ]) {
      for (const target of [Document.prototype, Element.prototype]) {
        const original = target[method];
        target[method] = function (...args) {
          count(name);
          return original.apply(this, args);
        };
      }
    }

    // Layout-forcing reads. Each of these flushes pending style and layout.
    const rect = Element.prototype.getBoundingClientRect;
    Element.prototype.getBoundingClientRect = function (...args) {
      count("getBoundingClientRect");
      return rect.apply(this, args);
    };
    for (const [property, key] of [
      ["offsetWidth", "offsetWidth"],
      ["offsetHeight", "offsetHeight"],
      ["clientWidth", "clientWidth"],
      ["clientHeight", "clientHeight"],
    ]) {
      const descriptor = Object.getOwnPropertyDescriptor(Element.prototype, property);
      if (!descriptor?.get) continue;
      Object.defineProperty(Element.prototype, property, {
        configurable: true,
        get() {
          count(key);
          return descriptor.get.call(this);
        },
      });
    }
    const scrollTop = Object.getOwnPropertyDescriptor(Element.prototype, "scrollTop");
    if (scrollTop?.get) {
      Object.defineProperty(Element.prototype, "scrollTop", {
        configurable: true,
        get() {
          count("scrollTop");
          return scrollTop.get.call(this);
        },
        set(value) {
          scrollTop.set.call(this, value);
        },
      });
    }

    globalThis.__domCounts = {
      reset() {
        attribution = false;
        for (const key of Object.keys(counts)) counts[key] = 0;
        for (const key of Object.keys(sites)) delete sites[key];
        attribution = true;
      },
      /** Take a reading without attributing the reads that snapshot itself needs. */
      snapshot() {
        attribution = false;
        const forcedLayouts =
          counts.getBoundingClientRect +
          counts.offsetWidth +
          counts.offsetHeight +
          counts.clientWidth +
          counts.clientHeight +
          counts.scrollTop;
        const result = { ...counts, forcedLayouts };
        attribution = true;
        return result;
      },
      topSites(limit = 12) {
        return Object.entries(sites)
          .sort((a, b) => b[1] - a[1])
          .slice(0, limit)
          .map(([site, count]) => `${count}  ${site}`);
      },
    };
    attribution = true;
  });
}

/** Report collected counters to the shared perf output, honouring per-key ceilings. */
export async function reportDomCounts(page, prefix, record, ceilings = {}) {
  const snapshot = await page.evaluate(() => globalThis.__domCounts.snapshot());
  for (const [key, value] of Object.entries(snapshot)) {
    record(`${prefix}/${key}`, value, {
      unit: key === "forcedLayouts" ? "reflows" : "writes",
      ceiling: ceilings[key] ?? null,
      note: `DOM ${key} caused by the client while ${prefix.replace("client/dom/", "")}.`,
    });
  }
  const top = await page.evaluate(() => globalThis.__domCounts.topSites());
  if (top.length) console.log(`  top DOM access sites for ${prefix}:\n    ${top.join("\n    ")}`);
  return snapshot;
}
