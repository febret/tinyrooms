/**
 * Decide how high a dragged prop should sit so it rests on any props it
 * intersects.
 *
 * Metrics are expressed in board space: `x`/`z` are world units, `halfX`/`halfZ`
 * are rotated footprint half-extents, and `topZ` is the elevation (authoritative
 * z units) of the prop's top face. Keeping the geometry out of the board module
 * makes the stacking rule unit-testable without a renderer.
 */

import { ELEVATION_PER_UNIT } from "../board-helpers.js";

/**
 * Footprint and top-elevation metrics used to decide how high a dragged prop rests.
 * The local model bounds are rotated into board space and enclosed by an AABB.
 */
export function stackMetrics(record, worldX, worldZ) {
  const bounds = record?.bounds;
  if (!bounds) return null;
  const scale = record.group.scale.x || 1;
  const halfLocalX = (bounds.max.x - bounds.min.x) / 2;
  const halfLocalZ = (bounds.max.z - bounds.min.z) / 2;
  const centerLocalX = (bounds.max.x + bounds.min.x) / 2;
  const centerLocalZ = (bounds.max.z + bounds.min.z) / 2;
  const angle = record.group.rotation.y || 0;
  const cos = Math.cos(angle);
  const sin = Math.sin(angle);
  return {
    id: record.id,
    x: worldX + scale * (cos * centerLocalX + sin * centerLocalZ),
    z: worldZ + scale * (-sin * centerLocalX + cos * centerLocalZ),
    halfX: scale * (Math.abs(cos) * halfLocalX + Math.abs(sin) * halfLocalZ),
    halfZ: scale * (Math.abs(sin) * halfLocalX + Math.abs(cos) * halfLocalZ),
    topZ: (Number(record.prop?.position?.[2]) || 0)
      + ((bounds.max.y - bounds.min.y) * scale) / ELEVATION_PER_UNIT,
  };
}

/** Axis-aligned footprint overlap between two props. */
export function footprintsOverlap(entry, other) {
  return Math.abs(entry.x - other.x) <= entry.halfX + other.halfX
    && Math.abs(entry.z - other.z) <= entry.halfZ + other.halfZ;
}

/**
 * Highest elevation the dragged prop can rest on without clipping its
 * neighbours, or 0 when nothing supports it.
 */
export function supportElevation(entry, others) {
  let elevation = 0;
  for (const other of Array.isArray(others) ? others : []) {
    if (!other || other.id === entry.id) continue;
    if (!footprintsOverlap(entry, other)) continue;
    elevation = Math.max(elevation, Number(other.topZ) || 0);
  }
  return elevation;
}
