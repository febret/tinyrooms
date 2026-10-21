// Board-wide lighting and camera-independent effect helpers.
//
// Kept out of `board.js` so the draw loop stays small: dark rooms bias the
// scene lights toward a dim, shadowed grey, and the scared status jitters the
// whole room (floor and props together) for an anxiety-inducing shake.

import * as THREE from "three";

const DARK_LIGHTING = {
  hemisphere: 0.32,
  sunlight: 0.62,
  fill: 0.08,
};

const LIT_LIGHTING = {
  hemisphere: 1.45,
  sunlight: 2,
  fill: 0.45,
};

/** Create the scene's fixed lights, including the shadow-casting sun. */
export function createBoardLights(scene) {
  const hemisphere = new THREE.HemisphereLight("#fff2d5", "#496e69", LIT_LIGHTING.hemisphere);
  scene.add(hemisphere);
  const sunlight = new THREE.DirectionalLight("#ffe6bb", LIT_LIGHTING.sunlight);
  sunlight.position.set(-5, 12, 7);
  sunlight.castShadow = true;
  sunlight.shadow.mapSize.set(2048, 2048);
  Object.assign(sunlight.shadow.camera, { left: -12, right: 12, top: 12, bottom: -12, near: 0.5, far: 45 });
  sunlight.shadow.normalBias = 0.025;
  sunlight.shadow.bias = -0.0001;
  scene.add(sunlight);
  const fill = new THREE.DirectionalLight("#bce2df", LIT_LIGHTING.fill);
  fill.position.set(5, 5, -4);
  scene.add(fill);
  return { hemisphere, sunlight, fill };
}

/** Whether the local user currently carries the scared status in *state*. */
export function selfIsScared(state) {
  const selfPeep = (state.room?.occupants || []).find(peep => peep.id === state.user?.id);
  return (selfPeep?.statuses || state.user?.statuses || []).includes("scared");
}

/** Dim or restore the scene lights for a dark room. Returns true when changed. */
export function applyDarkLighting({ hemisphere, sunlight, fill }, dark) {
  const target = dark ? DARK_LIGHTING : LIT_LIGHTING;
  let changed = false;
  if (hemisphere.intensity !== target.hemisphere) {
    hemisphere.intensity = target.hemisphere;
    changed = true;
  }
  if (sunlight.intensity !== target.sunlight) {
    sunlight.intensity = target.sunlight;
    changed = true;
  }
  if (fill.intensity !== target.fill) {
    fill.intensity = target.fill;
    changed = true;
  }
  return changed;
}

/** Offset a room group by an erratic, high-frequency shake (no-op when settled). */
export function scaredShake(group, elapsed) {
  const amplitude = 0.05 + 0.04 * Math.abs(Math.sin(elapsed * 6.1));
  const x = (Math.sin(elapsed * 43.0) + Math.sin(elapsed * 71.0)) * amplitude * 0.5;
  const z = (Math.cos(elapsed * 51.0) + Math.cos(elapsed * 89.0)) * amplitude * 0.5;
  group.position.set(x, 0, z);
  group.rotation.y = Math.sin(elapsed * 33.0) * 0.004;
}

/** Return a room group to its resting transform after the scare ends. */
export function settleShake(group) {
  group.position.set(0, 0, 0);
  group.rotation.y = 0;
}
