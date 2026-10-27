import * as THREE from "three";
import { withBase } from "./base-path.js";

const EXIT_RENDER_KINDS = new Set(["door", "arrow", "stairs"]);
const TEXTURE_ROOT = "/app/assets/textures";

const EXIT_TEXTURE_FILES = {
  wood: "exit-wood.png",
  stone: "exit-stone.png",
  metal: "exit-metal.png",
};

const DEFAULT_EXIT_FINISH = {
  door: { style: "panel", main: "#b07a4a", accent: "#6b4a2f", texture: "plain" },
  arrow: { style: "floor", main: "#e8b23a", accent: "#7a4d00", texture: "plain" },
  stairs: { style: "straight", main: "#9d8b74", accent: "#5c3a20", texture: "plain" },
};

const textureCache = new Map();
let textureLoader = null;

/** Whether a prop is rendered from the built-in procedural exit geometry. */
export function isExitProp(prop) {
  const kind = prop?.renderKind || prop?.render_kind;
  return EXIT_RENDER_KINDS.has(kind);
}

/** Merge an authored finish recipe over the kind defaults. */
export function resolveExitFinish(prop) {
  const kind = prop?.renderKind || prop?.render_kind;
  const defaults = DEFAULT_EXIT_FINISH[kind] || DEFAULT_EXIT_FINISH.door;
  const recipe = prop?.exitStyle || prop?.exit_style || {};
  return {
    style: typeof recipe.style === "string" && recipe.style ? recipe.style : defaults.style,
    main: typeof recipe.main === "string" && recipe.main ? recipe.main : defaults.main,
    accent: typeof recipe.accent === "string" && recipe.accent ? recipe.accent : defaults.accent,
    texture: typeof recipe.texture === "string" && recipe.texture ? recipe.texture : defaults.texture,
  };
}

/** Key fields that require rebuilding an exit prop's mesh. */
export function exitPropModelKey(prop) {
  return JSON.stringify([prop?.renderKind || prop?.render_kind, resolveExitFinish(prop)]);
}

/** Load (and cache) the baked detail texture for a finish; null when plain. */
export function loadExitTexture(textureId) {
  if (!textureId || textureId === "plain" || !EXIT_TEXTURE_FILES[textureId]) {
    return Promise.resolve(null);
  }
  if (!textureCache.has(textureId)) {
    if (!textureLoader) textureLoader = new THREE.TextureLoader();
    const url = withBase(`${TEXTURE_ROOT}/${EXIT_TEXTURE_FILES[textureId]}`);
    textureCache.set(textureId, textureLoader.loadAsync(url).then(texture => {
      texture.colorSpace = THREE.SRGBColorSpace;
      texture.wrapS = THREE.RepeatWrapping;
      texture.wrapT = THREE.RepeatWrapping;
      return texture;
    }).catch(() => null));
  }
  return textureCache.get(textureId);
}

function part(geometry, color, x, y, z, options = {}) {
  const material = new THREE.MeshStandardMaterial({
    color,
    roughness: options.roughness ?? 0.75,
    metalness: options.metalness ?? 0,
    ...(options.map ? { map: options.map } : {}),
    ...(options.emissive ? { emissive: options.emissive, emissiveIntensity: options.emissiveIntensity ?? 0.5 } : {}),
  });
  const mesh = new THREE.Mesh(geometry, material);
  mesh.position.set(x, y, z);
  if (options.rotation) mesh.rotation.set(...options.rotation);
  mesh.castShadow = mesh.receiveShadow = true;
  return mesh;
}

function knob(x, y, z, color) {
  const mesh = new THREE.Mesh(
    new THREE.SphereGeometry(0.09, 12, 10),
    new THREE.MeshStandardMaterial({ color, metalness: 0.6, roughness: 0.35 }),
  );
  mesh.position.set(x, y, z);
  mesh.castShadow = mesh.receiveShadow = true;
  return mesh;
}

function createPanelDoor(finish, map) {
  const group = new THREE.Group();
  group.add(part(new THREE.BoxGeometry(0.26, 2.4, 0.22), finish.accent, -0.88, 1.2, 0));
  group.add(part(new THREE.BoxGeometry(0.26, 2.4, 0.22), finish.accent, 0.88, 1.2, 0));
  group.add(part(new THREE.BoxGeometry(2.02, 0.26, 0.22), finish.accent, 0, 2.4, 0));
  group.add(part(new THREE.BoxGeometry(1.5, 2.24, 0.12), finish.main, 0, 1.12, 0.02, { map }));
  group.add(knob(0.55, 1.05, 0.12, finish.accent));
  return group;
}

function createArchDoor(finish, map) {
  const group = new THREE.Group();
  group.add(part(new THREE.BoxGeometry(0.26, 1.5, 0.22), finish.accent, -0.88, 0.75, 0));
  group.add(part(new THREE.BoxGeometry(0.26, 1.5, 0.22), finish.accent, 0.88, 0.75, 0));
  group.add(part(new THREE.TorusGeometry(0.88, 0.12, 10, 24, Math.PI), finish.accent, 0, 1.5, 0));
  const shape = new THREE.Shape();
  shape.moveTo(-0.75, 0);
  shape.lineTo(-0.75, 1.5);
  shape.absarc(0, 1.5, 0.75, Math.PI, 0, true);
  shape.lineTo(0.75, 0);
  shape.closePath();
  const geometry = new THREE.ExtrudeGeometry(shape, { depth: 0.12, bevelEnabled: false });
  geometry.translate(0, 0, -0.06);
  group.add(part(geometry, finish.main, 0, 0, 0.02, { map }));
  group.add(knob(0.5, 0.95, 0.12, finish.accent));
  return group;
}

function createSlabDoor(finish, map) {
  const group = new THREE.Group();
  group.add(part(new THREE.BoxGeometry(1.6, 2.4, 0.14), finish.main, 0, 1.2, 0, { map }));
  group.add(part(new THREE.BoxGeometry(0.18, 2.0, 0.05), finish.accent, 0.45, 1.1, 0.085));
  const handle = new THREE.Mesh(
    new THREE.CylinderGeometry(0.045, 0.045, 0.9, 10),
    new THREE.MeshStandardMaterial({ color: finish.accent, metalness: 0.6, roughness: 0.35 }),
  );
  handle.position.set(-0.5, 1.1, 0.12);
  handle.castShadow = handle.receiveShadow = true;
  group.add(handle);
  return group;
}

function createDoor(finish, map) {
  if (finish.style === "arch") return createArchDoor(finish, map);
  if (finish.style === "slab") return createSlabDoor(finish, map);
  return createPanelDoor(finish, map);
}

function createFloorArrow(finish, map) {
  const group = new THREE.Group();
  group.add(part(new THREE.BoxGeometry(1.5, 0.04, 2.2), finish.accent, 0, 0.02, 0.1));
  group.add(part(new THREE.BoxGeometry(0.36, 0.12, 1.2), finish.main, 0, 0.1, -0.35, { map, emissive: finish.accent, emissiveIntensity: 0.35 }));
  const headGeometry = new THREE.ConeGeometry(0.55, 0.8, 4);
  headGeometry.rotateX(Math.PI / 2);
  const head = new THREE.Mesh(headGeometry,
    new THREE.MeshStandardMaterial({ color: finish.main, roughness: 0.6, map: map || null, emissive: finish.accent, emissiveIntensity: 0.35 }));
  head.scale.set(1, 0.18, 1);
  head.position.set(0, 0.04 + 0.55 * 0.18, 0.55);
  head.castShadow = head.receiveShadow = true;
  group.add(head);
  return group;
}

function createSignpostArrow(finish, map) {
  const group = new THREE.Group();
  group.add(part(new THREE.BoxGeometry(0.7, 0.12, 0.7), finish.accent, 0, 0.06, 0));
  group.add(part(new THREE.CylinderGeometry(0.09, 0.11, 2.2, 10), finish.accent, 0, 1.2, 0));
  group.add(part(new THREE.BoxGeometry(1.3, 0.5, 0.1), finish.main, -0.2, 1.95, 0, { map }));
  const headGeometry = new THREE.ConeGeometry(0.36, 0.6, 4);
  headGeometry.rotateZ(-Math.PI / 2);
  headGeometry.rotateY(Math.PI / 4);
  group.add(part(headGeometry, finish.main, 0.7, 1.95, 0, { map }));
  return group;
}

function createArrow(finish, map) {
  if (finish.style === "signpost") return createSignpostArrow(finish, map);
  return createFloorArrow(finish, map);
}

function createStraightStairs(finish, map, width = 1.7) {
  const group = new THREE.Group();
  const steps = 5;
  const rise = 0.24;
  const run = 0.38;
  for (let index = 0; index < steps; index += 1) {
    const height = (index + 1) * rise;
    group.add(part(
      new THREE.BoxGeometry(width, height, run),
      index % 2 ? finish.accent : finish.main,
      0, height / 2, -index * run,
      { ...(index % 2 ? {} : { map }) },
    ));
  }
  return group;
}

function createGrandStairs(finish, map) {
  const group = new THREE.Group();
  const width = 2.6;
  const steps = 5;
  const rise = 0.24;
  const run = 0.38;
  const rail = 0.4;
  for (let index = 0; index < steps; index += 1) {
    const height = (index + 1) * rise;
    group.add(part(
      new THREE.BoxGeometry(width, height, run),
      index % 2 ? finish.accent : finish.main,
      0, height / 2, -index * run,
      { ...(index % 2 ? {} : { map }) },
    ));
    for (const side of [-1, 1]) {
      const wallHeight = height + rail;
      group.add(part(
        new THREE.BoxGeometry(0.18, wallHeight, run),
        finish.accent,
        side * (width / 2 + 0.09), wallHeight / 2, -index * run,
      ));
    }
  }
  return group;
}

function createStairs(finish, map) {
  if (finish.style === "grand") return createGrandStairs(finish, map);
  return createStraightStairs(finish, map);
}

/**
 * Build a procedural exit marker, upright and grounded on y=0.
 * `textures` maps texture ids to loaded THREE textures (or null).
 */
export function createExitProp(prop, textures = {}) {
  const finish = resolveExitFinish(prop);
  const map = textures[finish.texture] || null;
  const kind = prop?.renderKind || prop?.render_kind;
  if (kind === "arrow") return createArrow(finish, map);
  if (kind === "stairs") return createStairs(finish, map);
  return createDoor(finish, map);
}
