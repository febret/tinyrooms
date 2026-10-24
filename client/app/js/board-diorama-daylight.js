// The ten-minute day/night clock for the TinyTown diorama.

import * as THREE from "three";

// The server is authoritative for the cycle length and always sends
// day_cycle_seconds in snapshots (see DAY_NIGHT_CYCLE_SECONDS in
// server/content/lighting.py). This constant is only a fallback for rooms
// whose snapshot carries no usable duration; a parity test pins the two
// together, since the runtimes cannot share code.
export const DIORAMA_CYCLE_SECONDS = 600.0;

/** Normalize a room environment phase into a continuous ten-minute cycle. */
export function normalizeDayCycle(environment) {
  const rawDuration = Number(environment?.day_cycle_seconds);
  const duration = Number.isFinite(rawDuration) && rawDuration >= 30
    ? Math.min(rawDuration, 900)
    : DIORAMA_CYCLE_SECONDS;
  const rawPhase = Number(environment?.time_of_day);
  const fallback = ((Date.now() / 1000) % duration) / duration;
  const phase = Number.isFinite(rawPhase) ? rawPhase : fallback;
  return { phase: ((phase % 1) + 1) % 1, duration };
}

/** Advance a cycle by elapsed seconds, wrapping at its duration. */
export function cyclePhaseAt(cycle, elapsedSeconds) {
  const duration = cycle.duration || DIORAMA_CYCLE_SECONDS;
  const elapsed = Number.isFinite(elapsedSeconds) ? elapsedSeconds : 0;
  return (((cycle.phase + elapsed / duration) % 1) + 1) % 1;
}

const DAY_KEYS = [
  {
    at: 0,
    ambient: 0.62, sun: 0.02, fill: 0.2, night: 1,
    sky: "#435582", ground: "#263340", sunColor: "#8da7e8", fillColor: "#8da8e4",
    water: 0.18, exposure: 0.88,
  },
  {
    at: 0.18,
    ambient: 0.64, sun: 0.02, fill: 0.21, night: 1,
    sky: "#4b5c84", ground: "#273542", sunColor: "#93a5dd", fillColor: "#8ca3df",
    water: 0.19, exposure: 0.89,
  },
  {
    at: 0.24,
    ambient: 0.7, sun: 0.55, fill: 0.16, night: 0.65,
    sky: "#c58f78", ground: "#453c38", sunColor: "#ffbb7c", fillColor: "#9ab6d7",
    water: 0.35, exposure: 0.86,
  },
  {
    at: 0.3,
    ambient: 1.15, sun: 1.7, fill: 0.34, night: 0.12,
    sky: "#f7d6ae", ground: "#5b6554", sunColor: "#ffd9a1", fillColor: "#9fcbd8",
    water: 0.8, exposure: 1.0,
  },
  {
    at: 0.5,
    ambient: 1.5, sun: 2.4, fill: 0.46, night: 0,
    sky: "#e8f1ef", ground: "#6a7f63", sunColor: "#fff1cf", fillColor: "#b9e0e0",
    water: 1, exposure: 1.08,
  },
  {
    at: 0.7,
    ambient: 1.25, sun: 2.0, fill: 0.38, night: 0,
    sky: "#f8dfb5", ground: "#6b6c55", sunColor: "#ffe1a4", fillColor: "#b6d9dc",
    water: 0.9, exposure: 1.03,
  },
  {
    at: 0.76,
    ambient: 0.85, sun: 1.15, fill: 0.24, night: 0.25,
    sky: "#f0b087", ground: "#584d45", sunColor: "#ffb16d", fillColor: "#a9c1d6",
    water: 0.62, exposure: 0.95,
  },
  {
    at: 0.82,
    ambient: 0.55, sun: 0.3, fill: 0.12, night: 0.75,
    sky: "#8b6d83", ground: "#302f3c", sunColor: "#ee8f68", fillColor: "#8497c4",
    water: 0.3, exposure: 0.85,
  },
  {
    at: 0.9,
    ambient: 0.62, sun: 0.02, fill: 0.2, night: 1,
    sky: "#455883", ground: "#25333f", sunColor: "#94a6dc", fillColor: "#8ba5e2",
    water: 0.18, exposure: 0.88,
  },
  {
    at: 1,
    ambient: 0.62, sun: 0.02, fill: 0.2, night: 1,
    sky: "#435582", ground: "#263340", sunColor: "#8da7e8", fillColor: "#8da8e4",
    water: 0.18, exposure: 0.88,
  },
];

const COLOR_FIELDS = ["sky", "ground", "sunColor", "fillColor"];

function mixLighting(from, to, t) {
  const mixed = { ...from, ...to };
  for (const field of COLOR_FIELDS) {
    mixed[field] = new THREE.Color(from[field]).lerp(new THREE.Color(to[field]), t);
  }
  for (const field of ["ambient", "sun", "fill", "night", "water", "exposure"]) {
    mixed[field] = from[field] + (to[field] - from[field]) * t;
  }
  mixed.at = from.at + (to.at - from.at) * t;
  return mixed;
}

/** Interpolated light and colour recipe for a phase in [0, 1). */
export function daylightForPhase(phase) {
  const wrapped = ((Number(phase) || 0) % 1 + 1) % 1;
  for (let index = 1; index < DAY_KEYS.length; index += 1) {
    const right = DAY_KEYS[index];
    if (wrapped <= right.at) {
      const left = DAY_KEYS[index - 1];
      const span = right.at - left.at || 1;
      return mixLighting(left, right, (wrapped - left.at) / span);
    }
  }
  return mixLighting(DAY_KEYS[0], DAY_KEYS[0], 0);
}
