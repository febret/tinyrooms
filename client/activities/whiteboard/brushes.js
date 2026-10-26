export const BRUSHES = Object.freeze([
  {
    id: "marker", label: "Marker", kind: "round", size: 10, opacity: 95,
    spacing: 0.16, hardness: 1, flow: 1, pressureSize: 0.25, pressureOpacity: 0.1,
    icon: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 20l3-8 9-9 5 5-9 9z" fill="currentColor"/></svg>',
  },
  {
    id: "fineliner", label: "Fineliner", kind: "round", size: 4, opacity: 100,
    spacing: 0.12, hardness: 1, flow: 1, pressureSize: 0.15, pressureOpacity: 0.05,
    icon: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 19L7 13l9-9 4 4-9 9z" fill="none" stroke="currentColor" stroke-width="2.4"/></svg>',
  },
  {
    id: "pencil", label: "Pencil", kind: "grain", size: 6, opacity: 62,
    spacing: 0.12, hardness: 0.72, flow: 0.72, pressureSize: 0.42, pressureOpacity: 0.55,
    icon: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 20l1.5-5L16 4.5 19.5 8 9 18.5z" fill="none" stroke="currentColor" stroke-width="2.2"/></svg>',
  },
  {
    id: "charcoal", label: "Charcoal", kind: "grain", size: 22, opacity: 58,
    spacing: 0.22, hardness: 0.34, flow: 0.56, pressureSize: 0.55, pressureOpacity: 0.62,
    icon: '<svg viewBox="0 0 24 24" aria-hidden="true"><ellipse cx="12" cy="12" rx="8.5" ry="5.5" fill="currentColor" opacity="0.72"/></svg>',
  },
  {
    id: "crayon", label: "Crayon", kind: "grain", size: 14, opacity: 78,
    spacing: 0.18, hardness: 0.62, flow: 0.82, pressureSize: 0.34, pressureOpacity: 0.42,
    icon: '<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="6" y="4" width="12" height="16" rx="3" fill="none" stroke="currentColor" stroke-width="2.4"/></svg>',
  },
  {
    id: "soft-brush", label: "Soft brush", kind: "soft", size: 30, opacity: 72,
    spacing: 0.2, hardness: 0.28, flow: 0.58, pressureSize: 0.68, pressureOpacity: 0.55,
    icon: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 3c3 4 4 7 4 10a4 4 0 0 1-8 0c0-3 1-6 4-10z" fill="currentColor"/></svg>',
  },
  {
    id: "flat-brush", label: "Flat brush", kind: "flat", size: 26, opacity: 88,
    spacing: 0.2, hardness: 0.9, flow: 0.9, pressureSize: 0.48, pressureOpacity: 0.3,
    icon: '<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="5" y="8" width="14" height="8" rx="1.5" transform="rotate(-24 12 12)" fill="currentColor"/></svg>',
  },
  {
    id: "bristle", label: "Bristle", kind: "bristle", size: 24, opacity: 74,
    spacing: 0.26, hardness: 0.66, flow: 0.66, pressureSize: 0.52, pressureOpacity: 0.5,
    icon: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 6l14 3M5 11l14 3M5 16l14 3" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"/></svg>',
  },
  {
    id: "airbrush", label: "Airbrush", kind: "spray", size: 44, opacity: 42,
    spacing: 0.34, hardness: 0.18, flow: 0.4, pressureSize: 0.72, pressureOpacity: 0.68,
    icon: '<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="3" fill="currentColor"/><circle cx="12" cy="12" r="7.5" fill="none" stroke="currentColor" stroke-width="1.8" stroke-dasharray="2 3"/></svg>',
  },
  {
    id: "watercolor", label: "Watercolor", kind: "wash", size: 36, opacity: 38,
    spacing: 0.3, hardness: 0.22, flow: 0.34, pressureSize: 0.62, pressureOpacity: 0.58,
    icon: '<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="10" cy="13" r="7" fill="currentColor" opacity="0.48"/><circle cx="14.5" cy="10.5" r="4.4" fill="currentColor"/></svg>',
  },
  {
    id: "highlighter", label: "Highlighter", kind: "highlight", size: 34, opacity: 34,
    spacing: 0.18, hardness: 0.9, flow: 0.5, pressureSize: 0.18, pressureOpacity: 0.2,
    icon: '<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="4" y="9" width="16" height="6" rx="3" fill="currentColor" opacity="0.72"/></svg>',
  },
]);

export const BRUSH_BY_ID = Object.freeze(
  Object.fromEntries(BRUSHES.map(brush => [brush.id, brush])),
);

export function clamp(value, minimum, maximum) {
  return Math.min(maximum, Math.max(minimum, value));
}

export function pressureForEvent(event, speed = 0) {
  if (event?.pointerType === "pen" && typeof event?.pressure === "number" && event.pressure > 0) {
    return clamp(event.pressure, 0.08, 1);
  }
  // Mouse and touch fall back to speed: slow deliberate motion lays down more paint.
  return clamp(1 - speed / 2600, 0.34, 1);
}

export function dabSpacing(radius, spacingFactor) {
  return Math.max(1, radius * spacingFactor);
}

export function interpolatePoints(previous, current, spacing) {
  const [x1, y1] = previous;
  const [x2, y2] = current;
  const distance = Math.hypot(x2 - x1, y2 - y1);
  if (distance <= spacing) return [[x2, y2, Math.min(1, distance / Math.max(1, spacing))]];
  const steps = Math.max(1, Math.floor(distance / spacing));
  const points = [];
  for (let index = 1; index <= steps; index += 1) {
    const t = index / steps;
    points.push([x1 + (x2 - x1) * t, y1 + (y2 - y1) * t, 1]);
  }
  return points;
}

export function mulberry32(seed) {
  let value = seed >>> 0;
  return () => {
    value |= 0;
    value = (value + 0x6d2b79f5) | 0;
    let mixed = Math.imul(value ^ (value >>> 15), 1 | value);
    mixed = (mixed + Math.imul(mixed ^ (mixed >>> 7), 61 | mixed)) ^ mixed;
    return ((mixed ^ (mixed >>> 14)) >>> 0) / 4294967296;
  };
}
