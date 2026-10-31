const SWIPE_OFFSETS = new Map([
  ["swipe-east", [-1, 0, 0]],
  ["swipe-west", [1, 0, 0]],
  ["swipe-north", [0, 0, 1]],
  ["swipe-south", [0, 0, -1]],
  ["swipe-up", [0, -1, 0]],
  ["swipe-down", [0, 1, 0]],
]);

export const ROOM_TRANSITION_MS = 480;
export const ROOM_TRANSITION_OPTIONS = [
  { value: "crossfade", label: "Crossfade" },
  { value: "zoom-in", label: "Zoom in" },
  { value: "swipe-east", label: "Swipe east" },
  { value: "swipe-west", label: "Swipe west" },
  { value: "swipe-north", label: "Swipe north" },
  { value: "swipe-south", label: "Swipe south" },
  { value: "swipe-up", label: "Swipe up" },
  { value: "swipe-down", label: "Swipe down" },
];
export const ROOM_TRANSITION_TYPES = new Set(ROOM_TRANSITION_OPTIONS.map(option => option.value));

/** Normalize authored transition metadata, rejecting unknown values. */
export function normalizeRoomTransition(value) {
  const type = typeof value === "string"
    ? value
    : value && typeof value.type === "string" ? value.type : "";
  return ROOM_TRANSITION_TYPES.has(type) ? type : "";
}

export function easeInOutCubic(value) {
  const t = Math.min(1, Math.max(0, Number(value) || 0));
  return t < 0.5 ? 4 * t * t * t : 1 - ((-2 * t + 2) ** 3) / 2;
}

/**
 * Resolve one transition frame as root transforms.
 *
 * Progress 0 is the old room fully visible; progress 1 is the new room settled.
 * Swipe offsets use world axes so camera orbit does not change the authored
 * direction. `view` carries the world-space extents that clear the viewport.
 */
export function transitionFrame(type, progress, { width = 12, height = 10, depth = 12 } = {}) {
  const t = easeInOutCubic(progress);
  const swipe = SWIPE_OFFSETS.get(type);
  if (swipe) {
    const extent = [width, height, depth];
    const oldOffset = swipe.map((axis, index) => axis * extent[index] * t + 0);
    const newOffset = swipe.map((axis, index) => -axis * extent[index] * (1 - t) + 0);
    return { oldOffset, newOffset, oldScale: 1, newScale: 1, oldOpacity: 1 };
  }
  if (type === "zoom-in") {
    return {
      oldOffset: [0, 0, 0],
      newOffset: [0, 0, 0],
      oldScale: 1 + 0.9 * t,
      newScale: 0.72 + 0.28 * t,
      oldOpacity: 1 - t,
    };
  }
  return {
    oldOffset: [0, 0, 0],
    newOffset: [0, 0, 0],
    oldScale: 1,
    newScale: 1,
    oldOpacity: 1 - t,
  };
}

export function usesFade(type) {
  return type === "crossfade" || type === "zoom-in";
}
