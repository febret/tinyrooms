import * as THREE from "three";

/** Camera yaw is quantized to this step while the player orbits the room. */
export const ORBIT_SNAP_DEGREES = 5;
export const ORBIT_SNAP_RADIANS = THREE.MathUtils.degToRad(ORBIT_SNAP_DEGREES);

const _offset = new THREE.Vector3();
const _spherical = new THREE.Spherical();

/** Round a yaw angle to the nearest orbit step. */
export function snapOrbitAngle(angle, step = ORBIT_SNAP_RADIANS) {
  if (!Number.isFinite(angle) || !(step > 0)) return angle;
  return Math.round(angle / step) * step;
}

/**
 * Quantize the camera's yaw around `target` while preserving its radius and
 * pitch. Returns true when the camera actually moved.
 *
 * The board's idle render loop stops between draws. Snapping the yaw here means
 * a drag only asks for a new frame when it crosses a 5° step, instead of every
 * pointer/damping frame.
 */
export function snapCameraAzimuth(camera, target, step = ORBIT_SNAP_RADIANS) {
  _offset.subVectors(camera.position, target);
  if (_offset.lengthSq() === 0) return false;
  _spherical.setFromVector3(_offset);
  const snapped = snapOrbitAngle(_spherical.theta, step);
  if (Math.abs(snapped - _spherical.theta) < 1e-9) return false;
  _spherical.theta = snapped;
  _offset.setFromSpherical(_spherical);
  camera.position.copy(target).add(_offset);
  camera.lookAt(target);
  return true;
}
