import test from "node:test";
import assert from "node:assert/strict";

import {
  DARK_SPRITE_LIGHTING,
  LIGHTING_PRESETS,
  MAX_PROP_LIGHTS,
  ambientBoostForLampCount,
  applyBoardBackdrop,
  backdropForPreset,
  clearBoardBackdrop,
  lightingTint,
  lightingTintKey,
  propLightWorldPosition,
  resolveRoomLighting,
  selectAmbientSources,
  selectPropLights,
  spriteLightingForPreset,
} from "../../client/app/js/board-lighting.js";
import { daylightForPhase } from "../../client/app/js/board-diorama-daylight.js";

test("presets cover darkness, night, dusk, day, dawn, and fluorescent with render tuning", () => {
  for (const name of ["darkness", "night", "dusk", "day", "dawn", "fluorescent"]) {
    const preset = LIGHTING_PRESETS[name];
    assert.ok(Number.isFinite(preset.hemisphere));
    assert.ok(Number.isFinite(preset.sunlight));
    assert.ok(Number.isFinite(preset.fill));
    assert.ok(preset.exposure > 0);
    assert.match(preset.spriteColor, /^#[0-9a-f]{6}$/);
    assert.ok(preset.spriteOpacity > 0 && preset.spriteOpacity <= 1);
  }
});

test("dark rooms resolve to darkness and others fall back to day", () => {
  assert.equal(resolveRoomLighting({ board: { dark: true } }).name, "darkness");
  assert.equal(resolveRoomLighting({ board: { dark: false } }).name, "day");
  assert.equal(resolveRoomLighting(null).name, "day");
  assert.equal(
    resolveRoomLighting({ environment: { lighting_preset: { name: "dawn" } }, board: { dark: false } }).name,
    "dawn",
  );
});

test("lamps are bright point lights that also lift the ambient level", () => {
  const lamp = { id: "lamp", position: [50, 50, 0], light: { kind: "fixture", on: true, color: "#ffd9a1" } };
  const night = selectPropLights([lamp], "night");
  assert.equal(night.lights[0].kind, "fixture");
  assert.equal(night.lights[0].intensity, 5.5);
  assert.equal(night.lamps, 1);
  assert.equal(night.windows, 0);
  assert.equal(ambientBoostForLampCount(0), 0);
  assert.equal(ambientBoostForLampCount(1), 0.4);
  assert.equal(ambientBoostForLampCount(2), 0.8);
  assert.equal(ambientBoostForLampCount(10), 1);
  assert.equal(ambientBoostForLampCount(0, 2), 0.36);
  assert.equal(ambientBoostForLampCount(2, 2), 1);
});

test("ambient sources count even when their point lights are budgeted out", () => {
  const props = [
    { id: "lamp-on", light: { kind: "fixture", on: true } },
    { id: "lamp-off", light: { kind: "fixture", on: false } },
    { id: "window", light: { kind: "window" } },
    { id: "table", light: undefined },
  ];
  assert.deepEqual(selectAmbientSources(props, "night"), { lamps: 1, windows: 1 });
  assert.deepEqual(selectAmbientSources(props, "dusk"), { lamps: 1, windows: 1 });
  assert.deepEqual(selectAmbientSources(props, "day"), { lamps: 0, windows: 0 });
  assert.deepEqual(selectAmbientSources(props, "darkness"), { lamps: 1, windows: 0 });
});

test("windows emit in night, dusk, and dawn, and lift ambient at night", () => {
  const window = { id: "win", position: [10, 10, 0], light: { kind: "window", on: true, color: "#8da7e8" } };
  assert.equal(selectPropLights([window], "night").lights[0].intensity, 1.2);
  assert.equal(selectPropLights([window], "dusk").lights[0].intensity, 0.8);
  assert.equal(selectPropLights([window], "dawn").lights[0].intensity, 0.8);
  assert.deepEqual(selectPropLights([window], "day").lights, []);
  assert.deepEqual(selectPropLights([window], "darkness").lights, []);
  assert.equal(selectPropLights([window], "night").windows, 1);
});

test("windows survive the light budget ahead of fixtures", () => {
  const fixtures = Array.from({ length: MAX_PROP_LIGHTS }, (_, index) => ({
    id: `lamp-${index}`,
    position: [50, 50, 0],
    light: { kind: "fixture", on: true, color: "#ffd9a1" },
  }));
  const window = { id: "win", position: [10, 10, 0], light: { kind: "window", on: true, color: "#8da7e8" } };
  const selection = selectPropLights([...fixtures, window], "night");
  const ids = selection.lights.map(entry => entry.id);
  assert.equal(ids.length, MAX_PROP_LIGHTS);
  assert.ok(ids.includes("win"));
  assert.equal(selection.windows, 1);
  assert.equal(selection.lamps, MAX_PROP_LIGHTS - 1);
});

test("windows only light at night while fixtures light when switched on", () => {
  const props = [
    { id: "lamp", position: [50, 50, 0], light: { kind: "fixture", on: true, color: "#ffd9a1" } },
    { id: "window", position: [10, 10, 0], light: { kind: "window", on: true, color: "#8da7e8" } },
  ];
  const night = selectPropLights(props, "night").lights.map(entry => entry.id).sort();
  assert.deepEqual(night, ["lamp", "window"]);
  assert.deepEqual(selectPropLights(props, "day").lights.map(entry => entry.id), []);
  assert.deepEqual(
    selectPropLights([{ ...props[0], light: { kind: "fixture", on: false } }], "night").lights,
    [],
  );
});

test("prop lights are capped for performance", () => {
  const props = Array.from({ length: MAX_PROP_LIGHTS + 3 }, (_, index) => ({
    id: `lamp-${index}`,
    position: [50, 50, 0],
    light: { kind: "fixture", on: true, color: "#ffd9a1" },
  }));
  const selection = selectPropLights(props, "night");
  assert.equal(selection.lights.length, MAX_PROP_LIGHTS);
  assert.equal(selection.lamps, MAX_PROP_LIGHTS);
});

test("prop light positions project above the board", () => {
  const [x, y, z] = propLightWorldPosition([50, 50, 0]);
  assert.equal(x, 0);
  assert.ok(y > 1);
  assert.equal(z, 0);
});

test("sprite lighting follows presets and diorama daylight", () => {
  assert.deepEqual(lightingTint(spriteLightingForPreset(LIGHTING_PRESETS.day)), {
    color: "#ffffff",
    opacity: 1,
  });
  const night = lightingTint(spriteLightingForPreset(LIGHTING_PRESETS.night));
  assert.equal(night.color, "#aab8d6");
  assert.equal(night.opacity, 0.9);
  assert.deepEqual(DARK_SPRITE_LIGHTING, {
    color: LIGHTING_PRESETS.darkness.spriteColor,
    opacity: LIGHTING_PRESETS.darkness.spriteOpacity,
  });

  const day = lightingTint(spriteLightingForPreset(daylightForPhase(0.5)));
  const dark = lightingTint(spriteLightingForPreset(daylightForPhase(0)));
  assert.equal(day.opacity, 1);
  assert.ok(dark.opacity < day.opacity);
  assert.notEqual(day.color, dark.color);
  assert.equal(lightingTintKey({ color: "#123456", opacity: 0.5001 }), "#123456|0.50");
});

test("board backdrop follows preset colors and clears when removed", () => {
  const preset = LIGHTING_PRESETS.night;
  assert.deepEqual(backdropForPreset(preset), {
    top: preset.hemisphereSky,
    bottom: preset.hemisphereGround,
  });
  const element = { style: { background: "" }, dataset: {} };
  assert.equal(applyBoardBackdrop(element, "#112233", "#445566"), true);
  assert.match(element.style.background, /#112233/);
  assert.match(element.style.background, /#445566/);
  assert.equal(applyBoardBackdrop(element, "#112233", "#445566"), false);
  clearBoardBackdrop(element);
  assert.equal(element.style.background, "");
});
