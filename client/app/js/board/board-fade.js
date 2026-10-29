import { DARK_MATERIAL, GHOST_MATERIAL } from "./board-resources.js";

const SHARED_MATERIALS = new Set([DARK_MATERIAL, GHOST_MATERIAL]);

function materialsOf(material) {
  if (Array.isArray(material)) return material.filter(Boolean);
  return material ? [material] : [];
}

/**
 * Capture a subtree's materials for an opacity fade.
 *
 * Shared dark/ghost overrides are cloned per root so fading one prop or room
 * cannot alter every other object using the same global material.
 */
export function collectFadeMaterials(root) {
  const materials = new Map();
  const assignments = [];
  const clones = new Map();

  const track = (material, cloned) => {
    if (materials.has(material)) return;
    materials.set(material, {
      material,
      opacity: material.opacity,
      transparent: material.transparent,
      depthWrite: material.depthWrite,
      cloned,
    });
  };

  root.traverse(object => {
    const originals = materialsOf(object.material);
    if (!originals.length) return;
    const next = originals.map(material => {
      if (!SHARED_MATERIALS.has(material)) {
        track(material, false);
        return material;
      }
      let clone = clones.get(material);
      if (!clone) {
        clone = material.clone();
        clones.set(material, clone);
      }
      track(clone, true);
      return clone;
    });
    if (next.every((material, index) => material === originals[index])) return;
    assignments.push({ object, original: object.material });
    object.material = Array.isArray(object.material) ? next : next[0];
  });

  return { materials: [...materials.values()], assignments };
}

/** Apply a 0..1 opacity multiplier and temporary depth-write suppression. */
export function applyFade(fade, alpha) {
  if (!fade) return;
  const value = Math.min(1, Math.max(0, Number(alpha) || 0));
  const fading = value < 1;
  for (const entry of fade.materials) {
    const { material } = entry;
    const transparent = entry.transparent || fading;
    if (material.transparent !== transparent) material.transparent = transparent;
    material.opacity = entry.opacity * value;
    material.depthWrite = fading ? false : entry.depthWrite;
  }
}

/** Restore original materials and dispose any per-fade shared clones. */
export function restoreFade(fade) {
  if (!fade) return;
  applyFade(fade, 1);
  for (const assignment of fade.assignments) assignment.object.material = assignment.original;
  fade.assignments.length = 0;
  for (const entry of fade.materials) {
    if (entry.cloned) entry.material.dispose();
  }
  fade.materials.length = 0;
}
