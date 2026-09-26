import { test, expect } from "./fixtures.js";
import { command, createReadyAccount } from "./helpers.js";

// Peep health wear is DOM-only; these assertions run on desktop and portrait.
test.describe("peep damage markers", () => {
  test.slow();

  test("an admin drives health tiers with .gm setcounter", async ({ page, runtime }) => {
    await createReadyAccount(page, runtime, "siteadmin");
    const marker = page.locator("#peeps-panel .peep-chip.self .peep-marker");
    await command(page, ".gm setcounter @self health 24");
    await expect(marker).toHaveAttribute("data-damage", "1");
    await command(page, ".gm setcounter health 12");
    await expect(marker).toHaveAttribute("data-damage", "2");
    await command(page, ".gm setcounter health 2");
    await expect(marker).toHaveAttribute("data-damage", "4");
    await command(page, ".gm setcounter health 50");
    await expect(marker).toHaveAttribute("data-damage", "0");
  });

  test("tiers health and loads the cumulative overlay art", async ({ page, runtime }) => {
    await createReadyAccount(page, runtime);
    const tiers = await page.evaluate(async () => {
      const { peepDamageTier } = await import("/app/js/peep-damage.js");
      return {
        healthy: peepDamageTier({ health: 50, maxHealth: 50 }),
        scuffed: peepDamageTier({ health: 24, maxHealth: 50 }),
        splatted: peepDamageTier({ health: 12, maxHealth: 50 }),
        cracked: peepDamageTier({ health: 4, maxHealth: 50 }),
        broken: peepDamageTier({ health: 2, maxHealth: 50 }),
      };
    });
    expect(tiers).toEqual({ healthy: 0, scuffed: 1, splatted: 2, cracked: 3, broken: 4 });

    const marker = page.locator("#peeps-panel .peep-chip.self .peep-marker");
    await expect(marker).toHaveAttribute("data-damage", "0");
    const overlays = await page.evaluate(() => {
      const node = document.querySelector("#peeps-panel .peep-chip.self .peep-marker");
      node.dataset.damage = "4";
      const style = selector => getComputedStyle(node.querySelector(selector)).backgroundImage;
      return { wear: style(".peep-damage.wear"), gashes: style(".peep-damage.gashes") };
    });
    expect(overlays.wear).toContain("/app/assets/peep-damage/scuffs.svg");
    for (const asset of ["broken.svg", "cracks.svg", "splats.svg"]) {
      expect(overlays.gashes).toContain(`/app/assets/peep-damage/${asset}`);
    }
    const statuses = await page.evaluate(async () => Promise.all(
      ["scuffs.svg", "splats.svg", "cracks.svg", "broken.svg"].map(async name =>
        (await fetch(`/app/assets/peep-damage/${name}`)).status),
    ));
    expect(statuses).toEqual([200, 200, 200, 200]);
  });
});
