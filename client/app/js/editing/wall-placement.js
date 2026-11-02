const WALL_EDGE_MARGIN = 8;

const EDGE_PLACEMENTS = {
  top: { position: (x, _y, z) => [x, 0, z], rotation: [0, 0, 0] },
  bottom: { position: (x, _y, z) => [x, 100, z], rotation: [0, 180, 0] },
  left: { position: (_x, y, z) => [0, y, z], rotation: [0, 90, 0] },
  right: { position: (_x, y, z) => [100, y, z], rotation: [0, 270, 0] },
};

/** Nearest board edge and its distance, or null when the position is off-board. */
export function nearestWallEdge(position) {
  const x = Number(position?.[0]);
  const y = Number(position?.[1]);
  if (!Number.isFinite(x) || !Number.isFinite(y)) return null;
  return [
    { edge: "top", distance: y },
    { edge: "bottom", distance: 100 - y },
    { edge: "left", distance: x },
    { edge: "right", distance: 100 - x },
  ].reduce((nearest, candidate) => (
    !nearest || candidate.distance < nearest.distance ? candidate : nearest
  ), null);
}

/**
 * Snap a wall onto a nearby room edge and turn its face into the room.
 *
 * Edges snap within a small margin so walls can still be placed freely in the
 * middle of a room. The authoritative position stays clamped to the board.
 */
export function snapWallPlacement(position, rotation, enabled = true) {
  const sourcePosition = Array.isArray(position) ? position : [50, 50, 0];
  const sourceRotation = Array.isArray(rotation) ? rotation : [0, 0, 0];
  if (!enabled) return { position: [...sourcePosition], rotation: [...sourceRotation] };
  const nearest = nearestWallEdge(sourcePosition);
  if (!nearest || nearest.distance > WALL_EDGE_MARGIN) {
    return { position: [...sourcePosition], rotation: [...sourceRotation] };
  }
  const placement = EDGE_PLACEMENTS[nearest.edge];
  return {
    position: placement.position(
      Number(sourcePosition[0]) || 0,
      Number(sourcePosition[1]) || 0,
      Number(sourcePosition[2]) || 0,
    ),
    rotation: [...placement.rotation],
  };
}
