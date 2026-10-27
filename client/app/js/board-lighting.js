export const MAX_PROP_LIGHTS = 6;
export const PROP_LIGHT_DISTANCE = 8;

// Render recipe for each environment, owned here. The environment *names*
// and the cycle length are owned by the server (see DAY_NIGHT_CYCLE_SECONDS
// and LIGHTING_ENVIRONMENTS in server/content/lighting.py); the client only
// reads the preset name from snapshots, and tests pin the shared vocabulary.
export const LIGHTING_PRESETS = {
  darkness: {
    hemisphere: 0.05, sunlight: 0.0, fill: 0.02,
    hemisphereSky: "#101018", hemisphereGround: "#050507",
    sun: "#000000", fillColor: "#1a2030",
    exposure: 0.5,
    spriteColor: "#7b8489", spriteOpacity: 0.55,
  },
  night: {
    hemisphere: 0.55, sunlight: 0.35, fill: 0.18,
    hemisphereSky: "#33456e", hemisphereGround: "#1c2438",
    sun: "#8da7e8", fillColor: "#8da8e4",
    exposure: 0.88,
    spriteColor: "#aab8d6", spriteOpacity: 0.9,
  },
  dusk: {
    hemisphere: 0.9, sunlight: 1.1, fill: 0.25,
    hemisphereSky: "#c98a6b", hemisphereGround: "#4a3a34",
    sun: "#ffbb7c", fillColor: "#9ab6d7",
    exposure: 0.95,
    spriteColor: "#dcb49d", spriteOpacity: 0.95,
  },
  day: {
    hemisphere: 1.45, sunlight: 2.0, fill: 0.45,
    hemisphereSky: "#fff3d9", hemisphereGround: "#496e69",
    sun: "#ffe6bb", fillColor: "#bce2df",
    exposure: 1.05,
    spriteColor: "#ffffff", spriteOpacity: 1,
  },
  dawn: {
    hemisphere: 1.0, sunlight: 1.4, fill: 0.3,
    hemisphereSky: "#f7c9a0", hemisphereGround: "#54483e",
    sun: "#ffd9a1", fillColor: "#9fcbd8",
    exposure: 1.0,
    spriteColor: "#eed2b8", spriteOpacity: 0.97,
  },
  fluorescent: {
    hemisphere: 0.7, sunlight: 0.5, fill: 0.22,
    hemisphereSky: "#c9b458", hemisphereGround: "#4a4423",
    sun: "#ffe9a8", fillColor: "#b8c48a",
    exposure: 0.85,
    spriteColor: "#e7e1c0", spriteOpacity: 0.93,
  },
};

// Prop lights are tuned up by roughly 30% so lamps and windows read clearly
// against the environment recipes above.
const FIXTURE_INTENSITY = 5.5;
const WINDOW_NIGHT_INTENSITY = 1.2;
const WINDOW_TWILIGHT_INTENSITY = 0.8;
// Point lights also raise the room's ambient floor a little. The lift is kept
// small and capped so a row of lamps cannot wash out daylight.
const AMBIENT_PER_LAMP = 0.4;
const AMBIENT_PER_WINDOW = 0.18;
const AMBIENT_BOOST_CAP = 1.0;
const AMBIENT_MAX_TOTAL = 2.0;

export function resolveRoomLighting(room) {
  const preset = room?.environment?.lighting_preset;
  const hasPreset = typeof preset?.name === "string" && LIGHTING_PRESETS[preset.name];
  // The board's effective darkness wins: a room darkened at runtime serializes
  // its props as dark, so a stale or mismatched preset must not light the scene.
  const name = room?.board?.dark ? "darkness" : (hasPreset ? preset.name : "day");
  return { name, ...LIGHTING_PRESETS[name] };
}

/** Ambient lift from switched-on lamps, so a couple of lamps light most of a room. */
export function ambientBoostForLampCount(lampCount, windowCount = 0) {
  const lamps = Number.isFinite(lampCount) ? Math.max(0, lampCount) : 0;
  const windows = Number.isFinite(windowCount) ? Math.max(0, windowCount) : 0;
  return Math.min(lamps * AMBIENT_PER_LAMP + windows * AMBIENT_PER_WINDOW, AMBIENT_BOOST_CAP);
}

/**
 * Count the props that contribute ambient light, independent of the point-light
 * budget. Switched-on fixtures always count; windows count when their pale
 * outside light is visible at night or twilight.
 */
export function selectAmbientSources(props, presetName) {
  let lamps = 0;
  let windows = 0;
  for (const prop of Array.isArray(props) ? props : []) {
    const light = prop?.light;
    if (!light || typeof light !== "object") continue;
    if (light.kind === "fixture") {
      if (light.on !== false) lamps += 1;
    } else if (light.kind === "window"
      && (presetName === "night" || presetName === "dusk" || presetName === "dawn")) {
      windows += 1;
    }
  }
  return { lamps, windows };
}

/** Sprite tint recipe for an environment preset (sprites cannot receive lights). */
export function spriteLightingForPreset(preset) {
  return {
    color: preset?.spriteColor || "#ffffff",
    opacity: Number.isFinite(preset?.spriteOpacity) ? preset.spriteOpacity : 1,
  };
}

/** Sprite tint recipe for an interpolated diorama daylight frame. */
export function spriteLightingForDaylight(daylight) {
  return {
    color: daylight?.sprite || "#ffffff",
    opacity: Number.isFinite(daylight?.spriteOpacity) ? daylight.spriteOpacity : 1,
  };
}

function cssColor(value) {
  if (typeof value === "string") return value;
  if (typeof value?.getStyle === "function") return value.getStyle();
  return String(value ?? "#000000");
}

/** Sky/ground pair used to paint the backdrop behind the transparent board canvas. */
export function backdropForPreset(preset) {
  return {
    top: preset?.hemisphereSky || "#061923",
    bottom: preset?.hemisphereGround || "#041018",
  };
}

/** Paint (or update) the board backdrop without touching the app shell theme. */
export function applyBoardBackdrop(element, top, bottom) {
  if (!element?.style) return false;
  const key = `${cssColor(top)}|${cssColor(bottom)}`;
  if (element.dataset?.boardBackdrop === key) return false;
  if (element.dataset) element.dataset.boardBackdrop = key;
  element.style.background = `radial-gradient(ellipse at 50% 42%, ${cssColor(top)} 0%, ${cssColor(bottom)} 82%)`;
  return true;
}

/** Restore the default page backdrop when no room is on screen. */
export function clearBoardBackdrop(element) {
  if (!element?.style) return;
  if (element.dataset) delete element.dataset.boardBackdrop;
  element.style.background = "";
}

export function applyEnvironmentLighting(lights, preset, renderer, lampCount = 0, windowCount = 0) {
  let changed = false;
  const { hemisphere, sunlight, fill } = lights;
  const ambient = Math.min(
    preset.hemisphere + ambientBoostForLampCount(lampCount, windowCount),
    AMBIENT_MAX_TOTAL,
  );
  if (hemisphere.intensity !== ambient) {
    hemisphere.intensity = ambient;
    changed = true;
  }
  hemisphere.color.set(preset.hemisphereSky);
  hemisphere.groundColor.set(preset.hemisphereGround);
  if (sunlight.intensity !== preset.sunlight) {
    sunlight.intensity = preset.sunlight;
    changed = true;
  }
  sunlight.color.set(preset.sun);
  if (fill.intensity !== preset.fill) {
    fill.intensity = preset.fill;
    changed = true;
  }
  fill.color.set(preset.fillColor);
  if (renderer && renderer.toneMappingExposure !== preset.exposure) {
    renderer.toneMappingExposure = preset.exposure;
    changed = true;
  }
  return changed;
}

function propLightContribution(prop, presetName) {
  const light = prop?.light;
  if (!light || typeof light !== "object") return null;
  if (light.kind === "fixture") {
    if (light.on === false || presetName === "day") return null;
    return { kind: "fixture", color: typeof light.color === "string" ? light.color : "#ffd9a1", intensity: FIXTURE_INTENSITY };
  }
  if (light.kind === "window") {
    if (presetName === "night") {
      return { kind: "window", color: typeof light.color === "string" ? light.color : "#8da7e8", intensity: WINDOW_NIGHT_INTENSITY };
    }
    if (presetName === "dusk" || presetName === "dawn") {
      return { kind: "window", color: typeof light.color === "string" ? light.color : "#8da7e8", intensity: WINDOW_TWILIGHT_INTENSITY };
    }
    return null;
  }
  return null;
}

export function selectPropLights(props, presetName, limit = MAX_PROP_LIGHTS) {
  // Windows sort first so they always survive the light budget.
  const ordered = [...(props || [])].sort((left, right) => (
    (left?.light?.kind === "window" ? 0 : 1) - (right?.light?.kind === "window" ? 0 : 1)
  ));
  const lights = [];
  let lamps = 0;
  let windows = 0;
  for (const prop of ordered) {
    const contribution = propLightContribution(prop, presetName);
    if (!contribution) continue;
    lights.push({
      id: prop.id,
      position: Array.isArray(prop.position) ? prop.position : [50, 50, 0],
      ...contribution,
    });
    if (contribution.kind === "fixture") lamps += 1;
    else windows += 1;
    if (lights.length >= limit) break;
  }
  return { lights, lamps, windows };
}

export function propLightWorldPosition(position) {
  const [x = 50, y = 50, z = 0] = Array.isArray(position) ? position : [];
  return [(x - 50) * 0.105, z * 0.1 + 1.2, (y - 50) * 0.085];
}
