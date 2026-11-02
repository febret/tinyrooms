// Board-wide lighting and camera-independent effect helpers.
//
// Kept out of `board.js` so the draw loop stays small: fixed scene lights
// plus the scared-status shake for the whole room. Environment presets live
// in `board-lighting.js`.

import * as THREE from "three";

import { LIGHTING_PRESETS } from "./board-lighting.js";

/** Create the scene's fixed lights, including the shadow-casting sun. */
export function createBoardLights(scene) {
  const day = LIGHTING_PRESETS.day;
  const hemisphere = new THREE.HemisphereLight(day.hemisphereSky, day.hemisphereGround, day.hemisphere);
  scene.add(hemisphere);
  const sunlight = new THREE.DirectionalLight(day.sun, day.sunlight);
  sunlight.position.set(-5, 12, 7);
  sunlight.castShadow = true;
  sunlight.shadow.mapSize.set(2048, 2048);
  Object.assign(sunlight.shadow.camera, { left: -12, right: 12, top: 12, bottom: -12, near: 0.5, far: 45 });
  sunlight.shadow.normalBias = 0.025;
  sunlight.shadow.bias = -0.0001;
  scene.add(sunlight);
  const fill = new THREE.DirectionalLight(day.fillColor, day.fill);
  fill.position.set(5, 5, -4);
  scene.add(fill);
  return { hemisphere, sunlight, fill };
}

/** Whether the local user currently carries the scared status in *state*. */
export function selfIsScared(state) {
  const selfPeep = (state.room?.occupants || []).find(peep => peep.id === state.user?.id);
  return (selfPeep?.statuses || state.user?.statuses || []).includes("scared");
}

/** Restore the canonical scene lights after a room owns them temporarily. */
export function resetBoardLights({ hemisphere, sunlight, fill }) {
  const day = LIGHTING_PRESETS.day;
  hemisphere.color.set(day.hemisphereSky);
  hemisphere.groundColor.set(day.hemisphereGround);
  sunlight.color.set(day.sun);
  sunlight.position.set(-5, 12, 7);
  fill.color.set(day.fillColor);
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
