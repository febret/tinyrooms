/**
 * Decide how high a dragged prop should sit so it rests on any props it
 * intersects.
 *
 * Metrics are expressed in board space: `x`/`z` are world units, `halfX`/`halfZ`
 * are rotated footprint half-extents, and `topZ` is the elevation (authoritative
 * z units) of the prop's top face. Keeping the geometry out of the board module
 * makes the stacking rule unit-testable without a renderer.
 */

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
