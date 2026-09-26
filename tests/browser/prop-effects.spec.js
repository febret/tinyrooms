import { test, expect } from "./fixtures.js";
import { createReadyAccount } from "./helpers.js";

test.beforeEach(({ isMobile }, testInfo) => {
  test.skip(Boolean(isMobile) && !testInfo.tags.includes("@mobile"), "Desktop-only flow; portrait is covered by test:visual.");
});

test("prop effects build transform, material, and particle layers from descriptors", async ({ page, runtime }) => {
  await page.goto(runtime.baseURL);
  const result = await page.evaluate(async () => {
    const THREE = await import("/app/vendor/three/three.module.js");
    const { createPropEffects } = await import("/app/js/prop-effects.js");
    const group = new THREE.Group();
    const visual = new THREE.Group();
    group.add(visual);
    const model = new THREE.Mesh(new THREE.BoxGeometry(1, 1, 1), new THREE.MeshStandardMaterial());
    visual.add(model);
    const bounds = new THREE.Box3().setFromObject(model);
    const effectSets = {
      idle: [
        { id: "glow", label: "Glow", layers: [{ type: "material", emissive: "#ff0000", emissive_intensity: 1 }] },
        { id: "hover", label: "Hover", layers: [{ type: "transform", motion: "bob", amplitude: 0.1, period: 2 }] },
        { id: "smoke", label: "Smoke", layers: [{ type: "particle", preset: "smoke", texture_url: "/assets/fx/smoke-puff.png", max_particles: 4, rate: 1 }] },
      ],
    };
    const loader = { load: (url, onLoad) => onLoad({ colorSpace: null }) };
    const controller = createPropEffects({
      group, visual, model, bounds, effectSets, activeEffect: "idle",
      reducedMotion: false, textureLoader: loader, pixelScale: () => 600,
    });
    controller.update(0.05);
    const points = group.children.filter(child => child.isPoints).length;
    const count = controller.activeCount;
    const initialScale = controller.sizeScale;
    group.scale.setScalar(2.5);
    controller.update(0.05);
    const scaled = controller.sizeScale;
    controller.dispose();
    const disabled = createPropEffects({
      group, visual, model, bounds, effectSets, activeEffect: "idle",
      reducedMotion: true, textureLoader: loader, pixelScale: () => 600,
    });
    return { points, count, initialScale, scaled, disabled };
  });
  expect(result.points).toBe(1);
  expect(result.count).toBe(3);
  expect(result.initialScale).toBe(1);
  expect(result.scaled).toBe(2.5);
  expect(result.disabled).toBeNull();
});

test("renders effects on the board when motion is allowed", async ({ page, runtime }) => {
  await page.emulateMedia({ reducedMotion: "no-preference" });
  await createReadyAccount(page, runtime);
  const canvas = page.locator("#board-canvas");
  await expect(canvas).toHaveAttribute("data-board-ready", "true");
  await expect.poll(async () => Number(await canvas.getAttribute("data-fx-count") || "0")).toBeGreaterThan(0);
});

test("disables effects under reduced motion", async ({ page, runtime }) => {
  await createReadyAccount(page, runtime);
  const canvas = page.locator("#board-canvas");
  await expect(canvas).toHaveAttribute("data-board-ready", "true");
  await expect(canvas).toHaveAttribute("data-fx-count", "0");
});
